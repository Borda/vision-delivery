#!/usr/bin/env python3
"""Read prediction freezes back from the Sentinel ledger and check a prediction file against them.

A rung 0 prediction file is frozen by `freeze_predictions.py` before it is scored: the ledger
helper (`scripts/ledger_append.py`) hashes the prediction file and the gold label file and appends
one `predictions_frozen` row with both SHA-256 digests, the label file's name relative to the
ledger folder (`label_set`), a short digest of every label (`label_digests`), how the labels were
entered (`label_entry`), two label-change checks, and who wrote the predictions (`predictor`). The
labeling helper (`label_gold.py`) appends a `labels_recorded` row after every write of a label file.

This module reads those rows. It writes the ledger only by running the ledger helper
(`append_ledger_row`), the single writer, which computes every digest and check itself.

Only a row with `status: success`, a `ts` in the helper's `YYYY-MM-DDTHH:MM:SSZ` form, a relative
`label_set` that stays inside the project folder (the ledger folder's parent), and `label_digests`
counts as a freeze. Any other row is ignored.

What a freeze shows: the prediction file and the label file were fixed before this scoring run, and
no label differs from an earlier freeze of the same image name. What it does not show: that the
predicting agent never opened the label file (both run on the user's machine under the same
account), that a ledger row was not written by hand, or that no scoring run happened before the
freeze.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import subprocess
import sys
from collections.abc import Mapping
from dataclasses import dataclass
from enum import Enum
from pathlib import Path, PurePosixPath, PureWindowsPath
from typing import Any

from proof_chain import sha256_file

#: Ledger action written by `scripts/ledger_append.py` for a frozen prediction file.
PREDICTIONS_FROZEN = "predictions_frozen"
#: Ledger action written by `scripts/ledger_append.py` after the labeling helper writes a label file.
LABELS_RECORDED = "labels_recorded"
LEDGER_DIR = ".vision-delivery"
LEDGER_NAME = "ledger.jsonl"
#: The single ledger writer, at `<plugin-root>/scripts/ledger_append.py` in the repository and the package.
LEDGER_HELPER = Path(__file__).resolve().parents[2] / "scripts" / "ledger_append.py"
HELPER_TIMEOUT_SECONDS = 60
#: Hex characters kept from each per-image label digest; the ledger helper keeps the same number.
LABEL_DIGEST_HEX = 16
_SHA256 = re.compile(r"[0-9a-f]{64}")
_LABEL_DIGEST = re.compile(rf"[0-9a-f]{{{LABEL_DIGEST_HEX}}}")
_TS = re.compile(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z")
#: Text fields a freeze row must carry, in the order `parse_freeze` unpacks them.
_FREEZE_TEXT_FIELDS = ("event_id", "ts", "label_set", "pred_sha256", "gold_sha256")


class Predictor(str, Enum):
    """Who the freeze declares wrote the prediction file; the helper cannot check the declaration."""

    ISOLATED_SUBAGENT = "isolated-subagent"
    SAME_SESSION = "same-session"


class LabelEntry(str, Enum):
    """How the labels of a frozen label file reached the labeling helper, from its `labels_recorded` rows."""

    INTERACTIVE_TERMINAL = "interactive-terminal"
    RECORD_OPTION = "record-option"
    MIXED = "mixed"
    UNRECORDED = "unrecorded"


#: The scorer's sentence for each label entry that needs one.
_ENTRY_SENTENCES = {
    LabelEntry.RECORD_OPTION: (
        "Labels were entered through the helper's --record option, the path an agent uses to transcribe labels "
        "given in chat: check them."
    ),
    LabelEntry.MIXED: (
        "Some labels were entered through the helper's --record option, the path an agent uses to transcribe "
        "labels given in chat: check them."
    ),
    LabelEntry.UNRECORDED: "The label file was not written by the labeling helper.",
}


@dataclass(frozen=True)
class PredictionFreeze:
    """One successful `predictions_frozen` ledger row."""

    event_id: str
    frozen_at: str
    pred_sha256: str
    gold_sha256: str
    label_set: str
    predictor: Predictor
    label_digests: Mapping[str, str]
    label_entry: LabelEntry
    labels_changed_after_predictions: bool


@dataclass(frozen=True)
class FreezeCheck:
    """A freeze matched to the files being scored, with the label-change count recomputed from the ledger."""

    freeze: PredictionFreeze
    labels_changed_after_freeze: int
    ledger_is_project_ledger: bool

    @property
    def independent(self) -> bool:
        """Return whether the declared predictor is an isolated subagent and no label-change check is set."""
        return (
            self.freeze.predictor == Predictor.ISOLATED_SUBAGENT
            and self.labels_changed_after_freeze == 0
            and not self.freeze.labels_changed_after_predictions
        )

    def plain_note(self) -> str:
        """Return the sentences the scorer adds to its verdict line, built from the evidence fields.

        Examples:
            >>> freeze = PredictionFreeze("e", "t", "a" * 64, "b" * 64, "g.jsonl", Predictor.ISOLATED_SUBAGENT, {},
            ...                           LabelEntry.INTERACTIVE_TERMINAL, False)
            >>> FreezeCheck(freeze, 0, True).plain_note().startswith("Predictions and labels were fixed before this")
            True
            >>> FreezeCheck(freeze, 2, True).plain_note().split(". ")[1]
            '2 labels changed after an earlier prediction freeze: this is not an independent measurement.'
        """
        if self.freeze.predictor == Predictor.ISOLATED_SUBAGENT:
            sentences = [
                "Predictions and labels were fixed before this scoring run; the freeze records the predictions as "
                "written by an isolated subagent."
            ]
        else:
            sentences = [
                "Predictions and labels were fixed before this scoring run, but the predictions came from the same "
                "session that holds the labels, so independence was not enforced."
            ]
        changes: list[str] = []
        count = self.labels_changed_after_freeze
        if count:
            changes.append(f"{count} {'label' if count == 1 else 'labels'} changed after an earlier prediction freeze")
        if self.freeze.labels_changed_after_predictions:
            changes.append("labels changed after the prediction file was written")
        if changes:
            text = " and ".join(changes)
            sentences.append(f"{text[0].upper()}{text[1:]}: this is not an independent measurement.")
        entry = _ENTRY_SENTENCES.get(self.freeze.label_entry)
        if entry:
            sentences.append(entry)
        return " ".join(sentences)

    def evidence(self) -> dict[str, Any]:
        """Return the `predictions_frozen` block the scorer copies into its machine record.

        Examples:
            >>> freeze = PredictionFreeze("e1", "2026-11-10T00:00:00Z", "a" * 64, "b" * 64, "g.jsonl",
            ...                           Predictor.SAME_SESSION, {}, LabelEntry.UNRECORDED, False)
            >>> block = FreezeCheck(freeze, 0, True).evidence()
            >>> block["predictor_declared"], block["label_entry"], block["independent"]
            ('same-session', 'unrecorded', False)
        """
        return {
            "event_id": self.freeze.event_id,
            "frozen_at": self.freeze.frozen_at,
            "label_set": self.freeze.label_set,
            "pred_sha256": self.freeze.pred_sha256,
            "gold_sha256": self.freeze.gold_sha256,
            "predictor_declared": self.freeze.predictor.value,
            "label_entry": self.freeze.label_entry.value,
            "labels_changed_after_freeze": self.labels_changed_after_freeze,
            "labels_changed_after_predictions": self.freeze.labels_changed_after_predictions,
            "ledger_is_project_ledger": self.ledger_is_project_ledger,
            "independent": self.independent,
        }


def label_digest(image: str, value: Any) -> str:
    """Return the short digest of one label: SHA-256 over the image name, a NUL byte, and the JSON value.

    `scripts/ledger_append.py` computes the same digest when it records a label file.

    Examples:
        >>> label_digest("a.jpg", 3)
        'c4b1dc71acee4c73'
    """
    text = f"{image}\0{json.dumps(value)}"
    return hashlib.sha256(text.encode("utf-8")).hexdigest()[:LABEL_DIGEST_HEX]


def label_digests(labels: Mapping[str, Any]) -> dict[str, str]:
    """Return every image's label digest for labels already read by the scorer's loader.

    Examples:
        >>> label_digests({"a.jpg": 3})
        {'a.jpg': 'c4b1dc71acee4c73'}
    """
    return {image: label_digest(image, value) for image, value in labels.items()}


def is_project_ledger(ledger: Path) -> bool:
    """Return whether a ledger is a project ledger: a `ledger.jsonl` file directly in a `.vision-delivery` folder.

    Examples:
        >>> is_project_ledger(Path("/p/.vision-delivery/ledger.jsonl")), is_project_ledger(Path("/p/second.jsonl"))
        (True, False)
    """
    path = Path(os.path.abspath(ledger))
    return path.name == LEDGER_NAME and path.parent.name == LEDGER_DIR


def _leaves_project(label_set: str) -> bool:
    """Return whether a ledger-relative path is absolute or leaves the project folder, the ledger folder's parent.

    Examples:
        >>> [_leaves_project(path) for path in ("gold.jsonl", "../labels/gold.jsonl", "../../gold.jsonl", "/g.jsonl")]
        [False, False, True, True]
    """
    if not label_set or PurePosixPath(label_set).is_absolute() or PureWindowsPath(label_set).is_absolute():
        return True
    depth = 1
    for part in PurePosixPath(label_set.replace("\\", "/")).parts:
        depth += -1 if part == ".." else 1
        if depth < 0:
            return True
    return depth < 1


def ledger_for_labels(labels: Path, ledger: Path | None) -> Path:
    """Return the ledger for a label file: the named one, or `ledger.jsonl` in the `.vision-delivery` folder holding it.

    The working directory is never used. The label file must sit inside the project folder, the
    folder that holds the ledger's folder, because freezes and label rows name it relative to the
    ledger's folder.

    Raises:
        ValueError: When no ledger is named and the label file is not inside a `.vision-delivery`
            folder, or when the label file sits outside the project folder.

    Examples:
        >>> ledger_for_labels(Path("/p/.vision-delivery/gold.jsonl"), None).as_posix()
        '/p/.vision-delivery/ledger.jsonl'
        >>> try:
        ...     ledger_for_labels(Path("/p/frames/gold.jsonl"), None)
        ... except ValueError as exc:
        ...     print(str(exc).split(":")[0])
        pass --ledger
    """
    labels_path = Path(os.path.abspath(labels))
    if ledger is None:
        folder = next((parent for parent in labels_path.parents if parent.name == LEDGER_DIR), None)
        if folder is None:
            raise ValueError(
                f"pass --ledger: the label file {labels} is not inside a {LEDGER_DIR} folder, so there is no project "
                f"ledger to use; keep label files in <project>/{LEDGER_DIR}/ or name the project ledger"
            )
        ledger = folder / LEDGER_NAME
    ledger_dir = os.path.realpath(os.path.abspath(ledger.parent))
    # The label file itself is not resolved: a symbolic link there is refused by the code that opens it.
    located = os.path.join(os.path.realpath(labels_path.parent), labels_path.name)
    project = Path(ledger_dir).parent
    try:
        inside = Path(os.path.relpath(located, project)).as_posix()
    except ValueError as exc:
        raise ValueError(f"the label file must be on the same drive as the ledger: {exc}") from exc
    if inside in (".", "..") or inside.startswith("../"):
        raise ValueError(
            f"the label file {labels} must sit inside the project folder {project}, the folder that holds the ledger "
            f"folder, so freezes can name it; move it there (for example {project / 'labels' / 'gold.jsonl'})"
        )
    return ledger


def require_helper(helper: Path = LEDGER_HELPER) -> Path:
    """Return the ledger helper path, or refuse when it is missing or a symbolic link.

    Raises:
        ValueError: When the helper is not a regular file.
    """
    if helper.is_symlink() or not helper.is_file():
        raise ValueError(f"cannot find the ledger helper at {helper}; pass --ledger-helper")
    return helper


def append_ledger_row(helper: Path, ledger: Path, arguments: list[str]) -> None:
    """Append one row through the single ledger writer, which computes every digest and check itself.

    Raises:
        ValueError: When the helper is missing, does not finish in time, or refuses the row.
    """
    command = [sys.executable, str(require_helper(helper)), "--ledger", str(ledger), *arguments]
    try:
        done = subprocess.run(command, capture_output=True, text=True, check=False, timeout=HELPER_TIMEOUT_SECONDS)
    except subprocess.TimeoutExpired as exc:
        raise ValueError(f"the ledger helper did not finish within {HELPER_TIMEOUT_SECONDS} seconds") from exc
    if done.returncode != 0:
        reason = done.stderr.strip().splitlines()[-1] if done.stderr.strip() else f"exit {done.returncode}"
        raise ValueError(f"the ledger helper refused the row: {reason}")


def _checked_digests(value: Any) -> dict[str, str] | None:
    """Return a row's `label_digests` when every entry is an image name and a short hex digest."""
    if not isinstance(value, dict) or not value:
        return None
    if not all(
        isinstance(key, str) and isinstance(item, str) and _LABEL_DIGEST.fullmatch(item) for key, item in value.items()
    ):
        return None
    return dict(value)


def _checked_facts(row: dict[str, Any]) -> tuple[Predictor, LabelEntry, bool] | None:
    """Return a freeze row's predictor, label entry, and labels-changed-after-predictions flag, or None."""
    after_predictions, changed = row.get("labels_changed_after_predictions"), row.get("labels_changed_after_freeze")
    if not isinstance(after_predictions, bool) or isinstance(changed, bool) or not isinstance(changed, int):
        return None
    try:
        return Predictor(row.get("predictor")), LabelEntry(row.get("label_entry")), after_predictions
    except ValueError:
        return None


def parse_freeze(row: Any) -> PredictionFreeze | None:
    """Return the freeze one parsed ledger row records, or None when the row is not a successful freeze.

    Examples:
        >>> row = {"action": "predictions_frozen", "status": "success", "event_id": "e", "ts": "2026-11-10T00:00:00Z",
        ...        "pred_sha256": "a" * 64, "gold_sha256": "b" * 64, "label_set": "gold.jsonl",
        ...        "label_digests": {"a.jpg": "c4b1dc71acee4c73"}, "label_entry": "interactive-terminal",
        ...        "labels_changed_after_freeze": 0, "labels_changed_after_predictions": False,
        ...        "predictor": "isolated-subagent"}
        >>> parse_freeze(row).predictor.value
        'isolated-subagent'
        >>> [parse_freeze({**row, **change}) is None for change in ({"status": "attempted"}, {"ts": "x"},
        ...  {"label_set": "../../gold.jsonl"}, {"label_digests": None}, {"pred_sha256": "x"})]
        [True, True, True, True, True]
    """
    if not isinstance(row, dict) or row.get("action") != PREDICTIONS_FROZEN or row.get("status") != "success":
        return None
    texts = [value for value in (row.get(name) for name in _FREEZE_TEXT_FIELDS) if isinstance(value, str) and value]
    if len(texts) != len(_FREEZE_TEXT_FIELDS):
        return None
    event_id, frozen_at, label_set, pred_sha256, gold_sha256 = texts
    if not (_TS.fullmatch(frozen_at) and _SHA256.fullmatch(pred_sha256) and _SHA256.fullmatch(gold_sha256)):
        return None
    digests, facts = _checked_digests(row.get("label_digests")), _checked_facts(row)
    if _leaves_project(label_set) or digests is None or facts is None:
        return None
    predictor, entry, after_predictions = facts
    return PredictionFreeze(
        event_id, frozen_at, pred_sha256, gold_sha256, label_set, predictor, digests, entry, after_predictions
    )


def read_freezes(ledger: Path) -> list[PredictionFreeze]:
    """Return every successful prediction freeze in ledger order; a missing ledger holds none.

    Lines that are not JSON are skipped, as the ledger helper does when it reads the file.

    Raises:
        ValueError: When the ledger path is a symbolic link or not a regular file.

    Examples:
        >>> import tempfile
        >>> with tempfile.TemporaryDirectory() as raw:
        ...     read_freezes(Path(raw) / "ledger.jsonl")
        []
    """
    if not ledger.exists() and not ledger.is_symlink():
        return []
    if ledger.is_symlink() or not ledger.is_file():
        raise ValueError(f"ledger must be a regular non-symlink file: {ledger}")
    freezes: list[PredictionFreeze] = []
    for line in ledger.read_text(encoding="utf-8").split("\n"):
        try:
            row = json.loads(line.removesuffix("\r"))
        except json.JSONDecodeError:
            continue
        freeze = parse_freeze(row)
        if freeze is not None:
            freezes.append(freeze)
    return freezes


def label_set_path(ledger: Path, freeze: PredictionFreeze) -> str:
    """Return the real path of the gold label file a freeze names; `label_set` is relative to the ledger folder.

    Examples:
        >>> freeze = PredictionFreeze("e", "t", "a" * 64, "b" * 64, "labels/gold.jsonl", Predictor.SAME_SESSION, {},
        ...                           LabelEntry.UNRECORDED, False)
        >>> label_set_path(Path("/p/.vision-delivery/ledger.jsonl"), freeze).endswith("labels/gold.jsonl")
        True
    """
    return os.path.realpath(ledger.parent / freeze.label_set)


def freezes_for_label_set(ledger: Path, labels: Path) -> list[PredictionFreeze]:
    """Return the freezes whose gold label file is `labels`, matched by real path.

    Examples:
        >>> import tempfile
        >>> with tempfile.TemporaryDirectory() as raw:
        ...     freezes_for_label_set(Path(raw) / "ledger.jsonl", Path(raw) / "gold.jsonl")
        []
    """
    target = os.path.realpath(labels)
    return [freeze for freeze in read_freezes(ledger) if label_set_path(ledger, freeze) == target]


def labels_changed_after_freeze(earlier: list[PredictionFreeze], digests: Mapping[str, str]) -> int:
    """Return how many images carry a label other than the one an earlier freeze recorded for the same name.

    Examples:
        >>> first = PredictionFreeze("e", "t", "a" * 64, "b" * 64, "g.jsonl", Predictor.SAME_SESSION,
        ...                          {"a.jpg": "1" * 16, "b.jpg": "2" * 16}, LabelEntry.UNRECORDED, False)
        >>> labels_changed_after_freeze([first], {"a.jpg": "1" * 16, "b.jpg": "3" * 16, "c.jpg": "4" * 16})
        1
    """
    changed = {
        image
        for freeze in earlier
        for image, digest in digests.items()
        if freeze.label_digests.get(image, digest) != digest
    }
    return len(changed)


def require_freeze(ledger: Path, pred: Path, gold: Path, gold_labels: Mapping[str, Any]) -> FreezeCheck:
    """Return the earliest freeze recording this exact prediction file and gold file, or refuse.

    The label-change count is recomputed from the label file and the freezes before the matched
    one; the row's own count is not trusted. A matched freeze is returned even when that count is
    not zero: the scorer then says the result is not independent.

    Raises:
        ValueError: When no successful freeze holds both current digests. The message says
            whether the predictions were never frozen or the labels changed after the freeze.

    Examples:
        >>> import tempfile
        >>> with tempfile.TemporaryDirectory() as raw:
        ...     pred, gold = Path(raw) / "pred.jsonl", Path(raw) / "gold.jsonl"
        ...     _ = pred.write_text("{}\\n"), gold.write_text("[]\\n")
        ...     try:
        ...         require_freeze(Path(raw) / "ledger.jsonl", pred, gold, {})
        ...     except ValueError as exc:
        ...         print(str(exc).split(":")[0])
        the prediction file was not frozen before scoring
    """
    pred_sha256, gold_sha256 = sha256_file(pred), sha256_file(gold)
    freezes = read_freezes(ledger)
    for index, freeze in enumerate(freezes):
        if (freeze.pred_sha256, freeze.gold_sha256) == (pred_sha256, gold_sha256):
            changed = labels_changed_after_freeze(freezes[:index], label_digests(gold_labels))
            return FreezeCheck(freeze, changed, is_project_ledger(ledger))
    if any(freeze.pred_sha256 == pred_sha256 for freeze in freezes):
        raise ValueError(
            "the gold labels changed after these predictions were frozen: the ledger records this prediction file "
            "with a different gold file, so labels may have been fitted to the predictions; score the labels that "
            "existed at the freeze, or label a new set and run a fresh prediction on it"
        )
    raise ValueError(
        f"the prediction file was not frozen before scoring: no successful {PREDICTIONS_FROZEN} row in {ledger} "
        f"has its SHA-256 {pred_sha256}; freeze it with freeze_predictions.py before scoring, or a file that "
        "changed after its freeze is being scored"
    )
