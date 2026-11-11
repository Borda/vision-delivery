#!/usr/bin/env python3
"""Append one record to .vision-delivery/ledger.jsonl safely.

Uses json.dumps — safe for any field value including single quotes,
newlines, or other shell-special characters. Never use echo '...' >>
for ledger writes (shell injection risk on free-form notes/entity_id).

Usage:
    python3 scripts/ledger_append.py \
        --session m1-acceptance --skill detect-and-analyze \
        --action artifact_verified --event-id manual:m1:artifact:1 \
        --status success --notes "acceptance_id=m1; digest=abc123"

A successful ``predictions_frozen`` row freezes a rung 0 prediction file before scoring. The
helper hashes the prediction file and the gold label file itself; run it through
``resources/scripts/freeze_predictions.py``, which checks both files first:

    python3 scripts/ledger_append.py \
        --session m1 --skill detect-and-analyze --action predictions_frozen \
        --event-id manual:m1:predictions_frozen:1 --status success \
        --pred .vision-delivery/pred-rung0-m1.jsonl --gold .vision-delivery/gold-m1.jsonl \
        --predictor isolated-subagent

The gold label file must sit inside the project folder, the folder that holds the ledger's
folder. The row records a short digest of every label (``label_digests``), how the labels
were entered (``label_entry``), and two label-change checks computed from the ledger:
``labels_changed_after_freeze`` (images whose label differs from the label an earlier freeze
in this ledger recorded for the same image name) and
``labels_changed_after_predictions`` (the labeling helper last wrote this label file after the
prediction file was written, or the file changed since that write). A freeze with either check set
is refused unless ``--acknowledge-label-change`` is passed; the row then carries the values. A
freeze of a label file that an earlier freeze recorded with other content is always refused.

A successful ``labels_recorded`` row is appended by ``resources/scripts/label_gold.py`` after each
write. It records the gold file's digest, ``label_set``, ``label_digests`` and ``label_entry``
(``interactive-terminal`` or ``record-option``), never a label value.

A successful ``action_brief_emitted`` row is what the Claude Code PreToolUse gate reads
before a paid or state-changing provider call. It must carry every structured field:

    python3 scripts/ledger_append.py \
        --session m1 --skill detect-and-analyze --action action_brief_emitted \
        --operation trainings_create --event-id manual:m1:brief:1 --status success \
        --scope "train detection model on project conveyor, version 3" \
        --cost-amount 10 --cost-unit credits \
        --cost-source "Roboflow plans-and-pricing skill, training table" \
        --cost-as-of 2026-11-10 \
        --data-movement "none; the dataset is already in the workspace" \
        --rollback "cancel the training job; spent credits are not refunded"
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import re
import stat
import sys
import time
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import date, datetime, timedelta, timezone
from enum import Enum
from pathlib import Path
from typing import Any


def _project_root() -> Path:
    """Return the user's project root so nested working directories share one ledger.

    Examples:
        >>> isinstance(_project_root(), Path)
        True
    """
    declared = os.environ.get("CLAUDE_PROJECT_DIR", "")
    if declared and Path(declared).is_absolute():
        return Path(declared)
    start = Path.cwd()
    for candidate in (start, *start.parents):
        if (candidate / ".vision-delivery").exists() or (candidate / ".git").exists():
            return candidate
    return start


LEDGER = _project_root() / ".vision-delivery" / "ledger.jsonl"
VERSION = "0.5.0"
LOCK_TIMEOUT_SECONDS = 5.0
LOCK_RETRY_SECONDS = 0.01
PROOF_ACTIONS = {
    "baseline_measured",
    "recheck_measured",
    "artifact_verified",
    "delivery_handoff_emitted",
    "crossover_delivered",
    "decision_report_emitted",
}
ARTIFACT_ACTIONS = {"artifact_verified", "delivery_handoff_emitted"}
REPORT_ACTION = "decision_report_emitted"
BRIEF_ACTION = "action_brief_emitted"
GATE_POLICY = Path(__file__).resolve().parents[1] / "hooks" / "gate-policy.json"
MAX_CALL_BUDGET = 1000
#: A cost estimate dated further back than this is not a current price; the gate applies the same limit.
COST_MAX_AGE_DAYS = 90
ISO_DATE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
OPERATION_NAME = re.compile(r"^[A-Za-z0-9_-]{1,200}$")
BRIEF_TEXT_FIELDS = ("scope", "cost_unit", "cost_source", "data_movement", "rollback")
PREDICTIONS_ACTION = "predictions_frozen"
#: Who wrote a frozen prediction file; ``same-session`` records that independence was not enforced.
PREDICTORS = ("isolated-subagent", "same-session")
#: Ledger action the labeling helper appends after every write of a gold label file.
LABELS_ACTION = "labels_recorded"
#: How the labeling helper received the labels of one write.
LABEL_ENTRIES = ("interactive-terminal", "record-option")
#: Label entry of a freeze whose label file the labeling helper wrote in both ways.
MIXED_ENTRY = "mixed"
#: Label entry of a freeze whose label file has no ``labels_recorded`` row.
UNRECORDED_ENTRY = "unrecorded"
#: Hex characters kept from each per-image label digest.
LABEL_DIGEST_HEX = 16
LABEL_FIELDS = ("count", "flag", "text")
TS_FORMAT = "%Y-%m-%dT%H:%M:%SZ"


class RecheckDrift(str, Enum):
    """The three measured outcomes accepted from recheck evidence."""

    HOLDS = "holds"
    DRIFTED = "drifted"
    UNCERTAIN = "uncertain"


class RecheckShift(str, Enum):
    """Positions of a fresh interval relative to the baseline point estimate."""

    WORSE = "worse"
    BETTER = "better"
    NO = "no"
    UNKNOWN = "unknown"


class RecheckFreeze(str, Enum):
    """Whether the fresh predictions were frozen independently before scoring."""

    INDEPENDENT = "independent"
    NOT_INDEPENDENT = "not-independent"
    NOT_FROZEN = "not-frozen"


def _operation_class(operation: str) -> str:
    """Return the gate class of a provider operation, as the PreToolUse gate will read it.

    An operation the policy does not list is gated, so it reports the policy's default class
    and a warning is printed: the name may be misspelled. A tool is ``open`` only when the
    policy also records the provider's read-only flag, matching the gate.

    Raises:
        ValueError: When the gate policy is missing or unreadable, because the brief could
            then not be checked against what the gate enforces.
    """
    try:
        policy = json.loads(GATE_POLICY.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ValueError(
            f"cannot read the gate policy {GATE_POLICY.name}, so the brief cannot be checked: {exc}"
        ) from exc
    tools = policy.get("tools") if isinstance(policy, dict) else None
    if not isinstance(tools, dict):
        raise ValueError(f"the gate policy {GATE_POLICY.name} has no tools table, so the brief cannot be checked")
    entry = tools.get(operation)
    if not isinstance(entry, dict):
        print(
            f"ledger-append-warning: {operation} is not in the gate policy; check the spelling. "
            "The gate treats an unlisted operation as gated.",
            file=sys.stderr,
        )
        return "brief"
    operation_class = str(entry.get("class", "brief"))
    if operation_class == "open" and entry.get("read_only") is not True:
        return "brief"
    return operation_class if operation_class in ("open", "brief", "budget") else "brief"


def _brief_cost(args: argparse.Namespace) -> tuple[float, str]:
    """Validate the cost estimate and its date for an action brief."""
    amount = args.cost_amount
    if amount is None or not math.isfinite(amount) or amount < 0:
        raise ValueError("--cost-amount must be a finite number of zero or more (the upper estimate)")
    raw_date = args.cost_as_of or ""
    try:
        if not ISO_DATE.match(raw_date):
            raise ValueError(raw_date)
        as_of = date.fromisoformat(raw_date)
    except ValueError:
        raise ValueError("--cost-as-of must be the date of the price source, as YYYY-MM-DD") from None
    today = datetime.now(timezone.utc).date()
    if as_of > today + timedelta(days=1):
        raise ValueError("--cost-as-of may not be in the future")
    if as_of < today - timedelta(days=COST_MAX_AGE_DAYS):
        raise ValueError(
            f"--cost-as-of is more than {COST_MAX_AGE_DAYS} days old; look the price up again and use today's source"
        )
    return amount, as_of.isoformat()


def _brief_call_budget(operation: str, call_budget: int | None) -> int | None:
    """Check the call budget against the operation's gate class."""
    operation_class = _operation_class(operation)
    if operation_class == "open":
        raise ValueError(f"{operation} is read-only in the gate policy and needs no action brief")
    if call_budget is not None and not 1 <= call_budget <= MAX_CALL_BUDGET:
        raise ValueError(f"--call-budget must be between 1 and {MAX_CALL_BUDGET}")
    if operation_class == "budget" and call_budget is None:
        raise ValueError(f"{operation} runs under a call budget: pass --call-budget with the number of calls")
    if operation_class == "brief" and call_budget is not None:
        raise ValueError(f"{operation} needs one brief per execution; --call-budget does not apply")
    return call_budget


def _brief_fields(args: argparse.Namespace) -> dict[str, Any]:
    """Return the structured action brief the PreToolUse gate requires.

    Args:
        args: Parsed command-line arguments.

    Returns:
        The ``brief`` object stored on the ledger row.

    Raises:
        ValueError: When the operation or any structured field is missing or invalid.
    """
    operation = args.operation.strip()
    if not OPERATION_NAME.match(operation) or operation.startswith("mcp__"):
        raise ValueError("--operation must be the exact provider operation name, such as trainings_create")
    missing = [f"--{name.replace('_', '-')}" for name in BRIEF_TEXT_FIELDS if not (getattr(args, name) or "").strip()]
    if missing:
        raise ValueError(f"a successful {BRIEF_ACTION} needs {', '.join(missing)}")
    amount, as_of = _brief_cost(args)
    brief: dict[str, Any] = {name: getattr(args, name).strip() for name in BRIEF_TEXT_FIELDS}
    brief["cost_amount"] = amount
    brief["cost_as_of"] = as_of
    call_budget = _brief_call_budget(operation, args.call_budget)
    if call_budget is not None:
        brief["call_budget"] = call_budget
    return brief


def label_digest(image: str, value: Any) -> str:
    """Return the short digest of one label: SHA-256 over the image name, a NUL byte, and the JSON value.

    The reader in ``resources/scripts/prediction_freeze.py`` computes the same digest.

    Examples:
        >>> label_digest("a.jpg", 3), label_digest("a.jpg", True) == label_digest("a.jpg", 1)
        ('c4b1dc71acee4c73', False)
    """
    text = f"{image}\0{json.dumps(value)}"
    return hashlib.sha256(text.encode("utf-8")).hexdigest()[:LABEL_DIGEST_HEX]


def _valid_label_value(field: str, value: Any) -> bool:
    """Check a label's type and text bounds without normalizing its value."""
    if field == "flag":
        return isinstance(value, bool)
    if field == "text":
        return (
            isinstance(value, str) and len(value) <= 10_000 and not any("\ud800" <= char <= "\udfff" for char in value)
        )
    return isinstance(value, int) and not isinstance(value, bool) and value >= 0


def _label_row(raw: str, number: int) -> tuple[str, Any]:
    """Return the image name and label value of one gold line, or refuse a line that is not a label."""
    try:
        row = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise ValueError(f"--gold line {number} is not JSON: {exc}") from exc
    fields = [name for name in LABEL_FIELDS if isinstance(row, dict) and name in row]
    image = row.get("image") if isinstance(row, dict) else None
    if not isinstance(image, str) or not image or len(fields) != 1:
        raise ValueError(
            f"--gold line {number} needs a non-empty 'image' and exactly one of 'count', 'flag', or 'text'"
        )
    value = row[fields[0]]
    if not _valid_label_value(fields[0], value):
        raise ValueError(f"--gold line {number} has an invalid {fields[0]}")
    return image, value


def _label_digests(path: Path) -> dict[str, str]:
    """Return every image's label digest in a gold label file; the caller cannot supply them.

    Raises:
        ValueError: When a line is not a label, an image repeats, or the file holds no label.
    """
    digests: dict[str, str] = {}
    for number, raw in enumerate(path.read_bytes().decode("utf-8").split("\n"), 1):
        raw = raw.removesuffix("\r")
        if not raw.strip():
            continue
        image, value = _label_row(raw, number)
        if image in digests:
            raise ValueError(f"--gold line {number} repeats image {image!r}")
        digests[image] = label_digest(image, value)
    if not digests:
        raise ValueError("--gold holds no labeled image")
    return digests


def _file_sha256(path: Path, name: str) -> str:
    """Return the SHA-256 of a regular, non-symlink input file."""
    if path.is_symlink() or not path.is_file():
        raise ValueError(f"--{name} must be a regular non-symlink file")
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _ledger_dir(ledger: Path) -> Path:
    """Return the real path of the folder that holds the ledger."""
    return Path(os.path.realpath(_absolute_path(ledger).parent))


def _label_set(ledger: Path, gold: Path) -> str:
    """Return the gold file's path relative to the ledger folder; a file outside the project folder is refused.

    The project folder is the parent of the ledger folder, so ``label_set`` may start with one ``../``.
    """
    ledger_dir = _ledger_dir(ledger)
    located = os.path.realpath(gold)
    try:
        relative = Path(os.path.relpath(located, ledger_dir)).as_posix()
        inside = Path(os.path.relpath(located, ledger_dir.parent)).as_posix()
    except ValueError as exc:
        raise ValueError(f"--gold must be on the same drive as the ledger: {exc}") from exc
    if inside in (".", "..") or inside.startswith("../"):
        raise ValueError(
            f"--gold must sit inside the project folder {ledger_dir.parent}, the folder that holds the ledger folder "
            f"(for example {ledger_dir.parent / 'labels' / 'gold.jsonl'})"
        )
    return relative


def _gold_fields(args: argparse.Namespace) -> dict[str, Any]:
    """Return the gold file's digest, ``label_set``, and per-image label digests, all computed here."""
    return {
        "gold_sha256": _file_sha256(args.gold, "gold"),
        "label_set": _label_set(Path(args.ledger), args.gold),
        "label_digests": _label_digests(args.gold),
    }


def _prediction_fields(args: argparse.Namespace) -> dict[str, Any]:
    """Return the file facts a successful ``predictions_frozen`` or ``labels_recorded`` row records.

    The helper hashes the files itself; caller-supplied digests are never accepted. ``label_set``
    is the gold file's path relative to the ledger folder, so the label file can be recognised later
    without recording an absolute path. Every other action returns no fields.

    Args:
        args: Parsed command-line arguments.

    Returns:
        For a freeze: ``pred_sha256``, ``gold_sha256``, ``label_set``, ``label_digests``, and
        ``predictor``. For a labels row: the gold fields and ``label_entry``. Otherwise an empty mapping.

    Raises:
        ValueError: When an option is missing, a file is missing, a symbolic link, or not a label
            file, or the gold file sits outside the ledger folder.

    Examples:
        >>> _prediction_fields(argparse.Namespace(status="failed", action=PREDICTIONS_ACTION))
        {}
    """
    if args.status != "success" or args.action not in (PREDICTIONS_ACTION, LABELS_ACTION):
        return {}
    if args.action == LABELS_ACTION:
        if args.gold is None or not args.label_entry:
            raise ValueError(f"a successful {LABELS_ACTION} needs --gold and --label-entry")
        return {**_gold_fields(args), "label_entry": args.label_entry}
    if args.pred is None or args.gold is None or not args.predictor:
        raise ValueError(f"a successful {PREDICTIONS_ACTION} needs --pred, --gold, and --predictor")
    pred_sha256 = _file_sha256(args.pred, "pred")
    return {"pred_sha256": pred_sha256, **_gold_fields(args), "predictor": args.predictor}


def _read_recheck_evidence(path: Path, acceptance_sha256: str) -> tuple[bytes, dict[str, Any]]:
    """Read regular recheck evidence and verify its target against the selected acceptance."""
    _reject_symlink_path(_absolute_path(path))
    if not path.is_file():
        raise ValueError("--evidence must be a regular non-symlink JSON file")
    try:
        raw = path.read_bytes()
        evidence = json.loads(raw)
    except (OSError, ValueError) as exc:
        raise ValueError(f"cannot read recheck evidence: {exc}") from exc
    recheck = evidence.get("recheck") if isinstance(evidence, dict) else None
    target = evidence.get("target") if isinstance(evidence, dict) else None
    if not isinstance(recheck, dict) or not isinstance(target, dict):
        raise ValueError("--evidence needs recheck and target objects")
    if target.get("acceptance_sha256") != acceptance_sha256:
        raise ValueError("recheck evidence is bound to a different acceptance")
    return raw, evidence


def _recheck_timestamp(value: Any) -> str:
    """Validate an evidence measurement's UTC timestamp while preserving its exact spelling."""
    if not isinstance(value, str):
        raise ValueError("recheck measured_at must be a UTC timestamp")
    try:
        moment = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ValueError("recheck measured_at must be a UTC timestamp") from exc
    if moment.utcoffset() != timedelta(0):
        raise ValueError("recheck measured_at must be a UTC timestamp")
    return value


def _recheck_fields(args: argparse.Namespace, acceptance_sha256: str) -> dict[str, Any]:
    """Derive a recheck's structured facts only from evidence bound to this acceptance.

    Args:
        args: Parsed options, including the evidence path and action.
        acceptance_sha256: Digest already computed from the acceptance artifact.

    Returns:
        Evidence digest, measured drift and shift, and the freeze state when recorded.

    Raises:
        ValueError: If evidence is missing, invalid, or bound to another acceptance.
    """
    if args.evidence is not None and args.action != "recheck_measured":
        raise ValueError("--evidence is only valid for recheck_measured")
    if args.status != "success" or args.action != "recheck_measured":
        return {}
    if args.evidence is None:
        raise ValueError("a successful recheck_measured needs --evidence")
    raw, evidence = _read_recheck_evidence(args.evidence, acceptance_sha256)
    recheck = evidence["recheck"]
    fields = {
        "evidence_sha256": hashlib.sha256(raw).hexdigest(),
        "drift": RecheckDrift(recheck.get("drift")).value,
        "shifted": RecheckShift(recheck.get("shifted_from_baseline")).value,
    }
    if "predictions_frozen" in recheck:
        fields["predictions_frozen"] = RecheckFreeze(recheck["predictions_frozen"]).value
    if "measured_at" in evidence:
        fields["evidence_measured_at"] = _recheck_timestamp(evidence["measured_at"])
    return fields


def _row_time(row: dict[str, Any]) -> float | None:
    """Return a row's ``ts`` as seconds since the epoch, or None when it is not in the helper's form."""
    try:
        return datetime.strptime(str(row.get("ts")), TS_FORMAT).replace(tzinfo=timezone.utc).timestamp()
    except ValueError:
        return None


def _same_label_set(row: dict[str, Any], label_set: str, ledger_dir: Path) -> bool:
    """Return whether a row's ``label_set`` names the same label file, compared by real path."""
    named = row.get("label_set")
    if not isinstance(named, str) or not named:
        return False
    return os.path.realpath(ledger_dir / named) == os.path.realpath(ledger_dir / label_set)


def _changed_after_freeze(freezes: list[dict[str, Any]], digests: dict[str, str]) -> int:
    """Return how many images now carry a label other than the one an earlier freeze recorded for that name."""
    changed: set[str] = set()
    for row in freezes:
        recorded = row.get("label_digests")
        if isinstance(recorded, dict):
            changed.update(image for image, digest in digests.items() if recorded.get(image, digest) != digest)
    return len(changed)


def _changed_after_predictions(recorded: list[dict[str, Any]], gold_sha256: str, pred_mtime: float) -> bool:
    """Return whether the labeling helper wrote this label file after the predictions, or the file changed since.

    A labels row whose time cannot be read counts as later, because it cannot be ordered.
    """
    if not recorded:
        return False
    if recorded[-1].get("gold_sha256") != gold_sha256:
        return True
    times = [_row_time(row) for row in recorded]
    return any(moment is None or moment > pred_mtime for moment in times)


def _label_entry(recorded: list[dict[str, Any]]) -> str:
    """Return how this label file's labels reached the helper, from its ``labels_recorded`` rows."""
    entries = {row.get("label_entry") for row in recorded} & set(LABEL_ENTRIES)
    if not entries:
        return UNRECORDED_ENTRY
    return str(entries.pop()) if len(entries) == 1 else MIXED_ENTRY


def _refuse_changed_label_file(freezes: list[dict[str, Any]], fields: dict[str, Any], ledger_dir: Path) -> None:
    """Refuse a freeze of a label file that an earlier freeze recorded with other content."""
    for row in freezes:
        if _same_label_set(row, fields["label_set"], ledger_dir) and row.get("gold_sha256") != fields["gold_sha256"]:
            raise ValueError(
                f"this gold label file changed after predictions for it were frozen at {row.get('ts')} "
                f"(ledger event {row.get('event_id')}); start a new label file, run a fresh prediction on all "
                "of its images, and freeze that"
            )


def _freeze_facts(records: list[dict[str, Any]], fields: dict[str, Any], args: argparse.Namespace) -> dict[str, Any]:
    """Return a freeze's label entry and label-change checks, computed from the ledger it is appended to.

    Raises:
        ValueError: When the label file changed since an earlier freeze of it, or a label-change
            check is set and ``--acknowledge-label-change`` was not passed.
    """
    ledger_dir = _ledger_dir(Path(args.ledger))
    successes = [row for row in records if row.get("status") == "success"]
    freezes = [row for row in successes if row.get("action") == PREDICTIONS_ACTION]
    _refuse_changed_label_file(freezes, fields, ledger_dir)
    recorded = [
        row
        for row in successes
        if row.get("action") == LABELS_ACTION and _same_label_set(row, fields["label_set"], ledger_dir)
    ]
    changed = _changed_after_freeze(freezes, fields["label_digests"])
    after_predictions = _changed_after_predictions(recorded, fields["gold_sha256"], args.pred.stat().st_mtime)
    if (changed or after_predictions) and not args.acknowledge_label_change:
        noun = "label differs" if changed == 1 else "labels differ"
        reasons = [f"{changed} {noun} from an earlier prediction freeze in this ledger"] if changed else []
        if after_predictions:
            reasons.append(
                "the labeling helper wrote this label file after the prediction file was written, "
                "or the file changed since its last recorded write"
            )
        raise ValueError(
            f"labels changed after predictions existed: {'; '.join(reasons)}. A score on these files is not an "
            "independent measurement. Label a new set and run a fresh prediction on it, or pass "
            "--acknowledge-label-change to record the freeze with these facts; the scorer then says so"
        )
    return {
        "label_entry": _label_entry(recorded),
        "labels_changed_after_freeze": changed,
        "labels_changed_after_predictions": after_predictions,
    }


def _locked_fields(records: list[dict[str, Any]], record: dict[str, Any], args: argparse.Namespace) -> dict[str, Any]:
    """Return the fields computed from the ledger under its lock: a successful freeze's label facts, else none."""
    if args.status != "success" or args.action != PREDICTIONS_ACTION:
        return {}
    return _freeze_facts(records, record, args)


def _absolute_path(path: Path) -> Path:
    """Return an absolute lexical path without resolving symbolic links."""
    return path if path.is_absolute() else Path.cwd() / path


def _reject_symlink_path(path: Path) -> None:
    """Reject a path when it or any existing ancestor is a symbolic link."""
    for candidate in (path, *path.parents):
        try:
            if candidate.is_symlink():
                raise ValueError(f"ledger path may not contain a symlink: {candidate}")
        except OSError as exc:
            raise ValueError(f"cannot inspect ledger path {candidate}: {exc}") from exc


def _prepare_ledger_path(path: Path) -> Path:
    """Create and validate the ledger parent without following symbolic links."""
    ledger_path = _absolute_path(path)
    _reject_symlink_path(ledger_path)
    try:
        ledger_path.parent.mkdir(parents=True, exist_ok=True)
    except OSError as exc:
        raise ValueError(f"cannot create ledger directory: {exc}") from exc
    _reject_symlink_path(ledger_path)
    if ledger_path.exists():
        try:
            mode = ledger_path.stat().st_mode
        except OSError as exc:
            raise ValueError(f"cannot inspect ledger file: {exc}") from exc
        if not stat.S_ISREG(mode):
            raise ValueError(f"ledger path must be a regular file: {ledger_path}")
    return ledger_path


@contextmanager
def _ledger_lock(ledger_path: Path) -> Iterator[None]:
    """Serialize ledger reads and appends with an atomically-created directory."""
    lock_path = ledger_path.with_name(f"{ledger_path.name}.lock")
    deadline = time.monotonic() + LOCK_TIMEOUT_SECONDS
    while True:
        _reject_symlink_path(lock_path)
        try:
            lock_path.mkdir()
            break
        except FileExistsError:
            _reject_symlink_path(lock_path)
            if time.monotonic() >= deadline:
                raise ValueError(f"timed out waiting for ledger lock: {lock_path}") from None
            time.sleep(LOCK_RETRY_SECONDS)
        except OSError as exc:
            raise ValueError(f"cannot create ledger lock: {exc}") from exc
    try:
        yield
    finally:
        try:
            if lock_path.is_dir() and not lock_path.is_symlink():
                lock_path.rmdir()
        except OSError:
            pass


def _comparable_record(record: dict[str, Any]) -> dict[str, Any]:
    """Remove the generated timestamp before duplicate-content comparison."""
    return {key: value for key, value in record.items() if key != "ts"}


def _read_records(ledger_path: Path) -> list[dict[str, Any]]:
    """Read ledger records while preserving malformed rows for append tolerance."""
    if not ledger_path.exists():
        return []
    records: list[dict[str, Any]] = []
    for line in ledger_path.read_text(encoding="utf-8").splitlines():
        try:
            parsed = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(parsed, dict):
            records.append(parsed)
    return records


def _append_record(ledger_path: Path, record: dict[str, Any]) -> None:
    """Append one JSON record after checking the target is still a regular file."""
    _prepare_ledger_path(ledger_path)
    flags = os.O_WRONLY | os.O_APPEND | os.O_CREAT
    if hasattr(os, "O_NOFOLLOW"):
        flags |= os.O_NOFOLLOW
    try:
        descriptor = os.open(ledger_path, flags, 0o600)
    except OSError as exc:
        raise ValueError(f"cannot open ledger safely: {exc}") from exc
    with os.fdopen(descriptor, "a", encoding="utf-8") as file:
        file.write(json.dumps(record, allow_nan=False) + "\n")


def _acceptance_binding(path: Path) -> tuple[str, str]:
    """Load a complete frozen acceptance artifact and return its ID and digest."""
    if path.is_symlink() or not path.is_file():
        raise ValueError("acceptance must be a regular non-symlink JSON file")
    try:
        raw = path.read_bytes()
        data = json.loads(raw)
    except (OSError, json.JSONDecodeError) as exc:
        raise ValueError(f"cannot read acceptance artifact: {exc}") from exc
    required = {
        "schema_version",
        "acceptance_id",
        "frozen_at",
        "metric",
        "comparator",
        "threshold",
        "unit",
        "dataset_sha256",
        "model_or_pipeline",
        "confirmed_by",
    }
    if not isinstance(data, dict) or data.get("schema_version") != "1":
        raise ValueError("acceptance must use Sentinel schema 1")
    if required - data.keys():
        raise ValueError("acceptance is missing frozen fields")
    acceptance_id = data.get("acceptance_id")
    if not isinstance(acceptance_id, str) or not acceptance_id.strip():
        raise ValueError("acceptance_id must be non-empty text")
    dataset_digest = data.get("dataset_sha256")
    if (
        not isinstance(dataset_digest, str)
        or len(dataset_digest) != 64
        or any(character not in "0123456789abcdef" for character in dataset_digest)
    ):
        raise ValueError("acceptance dataset_sha256 must be lowercase SHA-256")
    threshold = data.get("threshold")
    if isinstance(threshold, bool) or not isinstance(threshold, int | float) or not math.isfinite(threshold):
        raise ValueError("acceptance threshold must be finite numeric")
    if data.get("comparator") not in {"gte", "lte"}:
        raise ValueError("acceptance comparator must be gte or lte")
    return acceptance_id, hashlib.sha256(raw).hexdigest()


def _artifact_tree_digest(root: Path) -> str:
    """Return a deterministic digest for a non-symlink artifact tree."""
    if root.is_symlink() or not root.is_dir():
        raise ValueError("artifact directory must be a non-symlink directory")
    entries = sorted(root.rglob("*"))
    if not entries:
        raise ValueError("artifact directory contains no files")
    digest = hashlib.sha256(b"SENTINEL-TREE-V2\0")
    for path in entries:
        if path.is_symlink():
            raise ValueError(f"artifact directory contains a symlink: {path}")
        relative = path.relative_to(root).as_posix().encode()
        mode = path.lstat().st_mode
        if stat.S_ISDIR(mode):
            entry_type = b"D"
            content = b""
        elif stat.S_ISREG(mode):
            entry_type = b"F"
            content = path.read_bytes()
        else:
            raise ValueError(f"artifact directory contains a special file: {path}")
        digest.update(entry_type)
        digest.update(len(relative).to_bytes(8, "big"))
        digest.update(relative)
        digest.update(stat.S_IMODE(mode).to_bytes(4, "big"))
        digest.update(len(content).to_bytes(8, "big"))
        digest.update(content)
    return digest.hexdigest()


def _build_parser() -> argparse.ArgumentParser:
    """Return the command-line parser for one ledger record."""
    p = argparse.ArgumentParser(description="Append a ledger record.")
    p.add_argument("--session", required=True)
    p.add_argument("--skill", required=True)
    p.add_argument("--action", required=True)
    p.add_argument("--entity-id", default="")
    p.add_argument("--event-id", required=True)
    p.add_argument(
        "--status",
        choices=("attempted", "success", "failed", "timeout", "cancelled", "unknown"),
        required=True,
    )
    p.add_argument("--source", choices=("skill", "hook", "import"), default="skill")
    p.add_argument("--notes", default="")
    p.add_argument(
        "--operation",
        default="",
        help="exact provider operation an action_brief_emitted row covers (read by the PreToolUse gate)",
    )
    p.add_argument("--scope", default="", help="action brief: what runs on what")
    p.add_argument("--cost-amount", type=float, default=None, help="action brief: upper cost estimate")
    p.add_argument("--cost-unit", default="", help="action brief: unit of the estimate, such as credits or USD")
    p.add_argument("--cost-source", default="", help="action brief: where the price comes from")
    p.add_argument("--cost-as-of", default="", help="action brief: date of the price source (YYYY-MM-DD)")
    p.add_argument("--data-movement", default="", help="action brief: what leaves this machine, or 'none'")
    p.add_argument("--rollback", default="", help="action brief: how to undo, or 'not reversible'")
    p.add_argument("--call-budget", type=int, default=None, help="action brief: calls covered (budget operations)")
    p.add_argument("--acceptance", type=Path)
    p.add_argument("--evidence", type=Path, help="recheck_measured: evidence bound to the acceptance")
    p.add_argument("--artifact-dir", type=Path)
    p.add_argument("--report", type=Path)
    p.add_argument("--streams", type=int, default=None)
    p.add_argument("--decision", default=None)
    p.add_argument("--pred", type=Path, help="predictions_frozen: the prediction file to freeze")
    p.add_argument("--gold", type=Path, help="predictions_frozen: the gold label file it will be scored against")
    p.add_argument("--predictor", choices=PREDICTORS, default="", help="predictions_frozen: who wrote the predictions")
    p.add_argument(
        "--acknowledge-label-change",
        action="store_true",
        help="predictions_frozen: record the freeze although labels changed after predictions existed",
    )
    p.add_argument("--label-entry", choices=LABEL_ENTRIES, default="", help="labels_recorded: how labels were entered")
    p.add_argument("--ledger", default=str(LEDGER))
    return p


def _action_brief_fields(args: argparse.Namespace, p: argparse.ArgumentParser) -> dict[str, Any]:
    """Validate a successful action brief before preparing any proof bindings."""
    if args.status != "success" or args.action != BRIEF_ACTION:
        return {}
    if not args.operation.strip():
        p.error(f"--operation is required for successful {BRIEF_ACTION}")
    return _brief_fields(args)


def _proof_binding_fields(args: argparse.Namespace, p: argparse.ArgumentParser) -> dict[str, Any]:
    """Bind successful proof rows, and other proof rows whose files were supplied."""
    acceptance_id = ""
    acceptance_sha256 = ""
    artifact_sha256 = ""
    # Bind failed rows too when files are supplied, so readers can identify their target and artifact.
    if args.action in PROOF_ACTIONS and (args.status == "success" or args.acceptance is not None):
        if args.acceptance is None:
            p.error(f"--acceptance is required for successful {args.action}")
        acceptance_id, acceptance_sha256 = _acceptance_binding(args.acceptance)
    if args.action in ARTIFACT_ACTIONS and (args.status == "success" or args.artifact_dir is not None):
        if args.artifact_dir is None:
            p.error(f"--artifact-dir is required for successful {args.action}")
        artifact_sha256 = _artifact_tree_digest(args.artifact_dir)
    fields = {}
    if acceptance_id:
        fields["acceptance_id"] = acceptance_id
        fields["acceptance_sha256"] = acceptance_sha256
    if artifact_sha256:
        fields["artifact_sha256"] = artifact_sha256
    return fields


def _report_digest(args: argparse.Namespace, p: argparse.ArgumentParser) -> str:
    """Validate and hash the report required by a successful report row."""
    if args.status != "success" or args.action != REPORT_ACTION:
        return ""
    if args.report is None:
        p.error("--report is required for successful decision_report_emitted")
    if args.report.is_symlink() or not args.report.is_file():
        p.error("--report must be a regular non-symlink file")
    return hashlib.sha256(args.report.read_bytes()).hexdigest()


def _build_record(args: argparse.Namespace, p: argparse.ArgumentParser) -> dict[str, Any]:
    """Validate fields in CLI order and assemble the row in its original key order."""
    try:
        brief = _action_brief_fields(args, p)
        proof_fields = _proof_binding_fields(args, p)
        report_sha256 = _report_digest(args, p)
        prediction_fields = _prediction_fields(args) | _recheck_fields(args, proof_fields.get("acceptance_sha256", ""))
    except ValueError as exc:
        p.error(str(exc))

    record = {
        "ts": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "session": args.session,
        "skill": args.skill,
        "action": args.action,
        "entity_id": args.entity_id,
        "version": VERSION,
        "status": args.status,
        "source": args.source,
        "event_id": args.event_id,
        "notes": args.notes,
    }
    record.update(proof_fields)
    if report_sha256:
        record["report_sha256"] = report_sha256
    if args.operation:
        record["operation"] = args.operation.strip()
    if brief:
        record["brief"] = brief
    if args.streams is not None:
        record["streams"] = args.streams
    if args.decision is not None:
        record["decision"] = args.decision
    record.update(prediction_fields)
    return record


def _write_record(ledger_path: Path, record: dict[str, Any], args: argparse.Namespace) -> int:
    """Append under the ledger lock, preserving idempotence and integrity error exits."""
    try:
        ledger_path = _prepare_ledger_path(ledger_path)
        with _ledger_lock(ledger_path):
            ledger_path = _prepare_ledger_path(ledger_path)
            records = _read_records(ledger_path)
            record.update(_locked_fields(records, record, args))
            for existing in records:
                if existing.get("event_id") != args.event_id:
                    continue
                if _comparable_record(existing) == _comparable_record(record):
                    return 0
                print(
                    f"ledger-integrity-conflict: event_id {args.event_id!r} already exists with different content",
                    file=sys.stderr,
                )
                return 2
            _append_record(ledger_path, record)
    except ValueError as exc:
        print(f"ledger-append-error: {exc}", file=sys.stderr)
        return 2

    return 0


def main() -> int:
    """Parse, prepare, and append one ledger row without changing CLI diagnostics."""
    p = _build_parser()
    args = p.parse_args()
    record = _build_record(args, p)
    ledger_path = Path(args.ledger)
    if not args.event_id.strip():
        p.error("--event-id must not be empty")
    return _write_record(ledger_path, record, args)


if __name__ == "__main__":
    sys.exit(main())
