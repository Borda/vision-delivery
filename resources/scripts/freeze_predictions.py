#!/usr/bin/env python3
"""Freeze a rung 0 prediction file in the project ledger before it is scored.

Run this right after the predictor has written its file and before `score_baseline.py` opens the
gold labels. It checks that both files are valid label files for the task and that every prediction
names a gold image, then records a `predictions_frozen` row through `scripts/ledger_append.py`, the
single ledger writer. The writer hashes both files itself, records a short digest of every label,
and checks the ledger:

- it refuses a label file that an earlier freeze recorded with other content;
- it refuses, unless `--acknowledge-label-change` is passed, when an image's label differs from the
  label an earlier freeze in this ledger recorded for the same image name, or when the labeling
  helper wrote this label file after the prediction file was written (or the file changed since that
  write). With the option the row records these facts and the scorer says the result is not
  independent.

Score afterwards with `score_baseline.py --frozen-ledger <ledger>`: the scorer refuses a prediction
file or a gold file whose SHA-256 differs from the frozen pair.

The ledger is `--ledger`, or `ledger.jsonl` in the `.vision-delivery` folder that holds the gold
file; the gold file must sit inside the ledger's folder. The working directory is never used.

A freeze shows that both files were fixed before this scoring run. It does not show that the
predicting agent never opened the label file (both run under the same account), that a ledger row
was not written by hand, or that no scoring run happened before the freeze.

Exit codes: 0 when the freeze is recorded (or was already recorded with identical content); 2 when
an input is unusable, the ledger helper refuses, or a label change is found and not acknowledged.
"""

from __future__ import annotations

import argparse
import json
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from prediction_freeze import (
    LEDGER_HELPER,
    PREDICTIONS_FROZEN,
    Predictor,
    append_ledger_row,
    ledger_for_labels,
    read_freezes,
)
from proof_chain import sha256_file
from score_baseline import load_labels

DIGEST_PREFIX = 12


@dataclass(frozen=True)
class CheckedFiles:
    """Digests and image counts of a gold file and a prediction file that passed the input checks."""

    gold_sha256: str
    pred_sha256: str
    gold_images: int
    predictions: int

    @property
    def missing(self) -> int:
        """Return how many gold images have no prediction.

        Examples:
            >>> CheckedFiles("a" * 64, "b" * 64, 24, 23).missing
            1
        """
        return self.gold_images - self.predictions


def event_id(session: str, files: CheckedFiles) -> str:
    """Return the stable event ID of one freeze: the same files in the same session reuse it.

    Examples:
        >>> event_id("s1", CheckedFiles("a" * 64, "b" * 64, 3, 3))
        'manual:s1:predictions_frozen:bbbbbbbbbbbb-aaaaaaaaaaaa'
    """
    pred, gold = files.pred_sha256[:DIGEST_PREFIX], files.gold_sha256[:DIGEST_PREFIX]
    return f"manual:{session}:{PREDICTIONS_FROZEN}:{pred}-{gold}"


def freeze_notes(task: str, predictor: Predictor, files: CheckedFiles) -> str:
    """Return the non-secret notes stored on the freeze row.

    Examples:
        >>> freeze_notes("count", Predictor.SAME_SESSION, CheckedFiles("a" * 64, "b" * 64, 24, 24))
        'task=count; gold_images=24; predictions=24; missing=0; predictor=same-session; independence not enforced'
    """
    notes = (
        f"task={task}; gold_images={files.gold_images}; predictions={files.predictions}; "
        f"missing={files.missing}; predictor={predictor.value}"
    )
    return notes + ("; independence not enforced" if predictor == Predictor.SAME_SESSION else "")


def check_files(gold: Path, pred: Path, task: str) -> CheckedFiles:
    """Hash both files and check that they are valid label files and that every prediction names a gold image.

    Raises:
        ValueError: When a file is a symbolic link, is malformed, or names an image the gold file lacks.

    Examples:
        >>> import tempfile
        >>> with tempfile.TemporaryDirectory() as raw:
        ...     gold, pred = Path(raw) / "gold.jsonl", Path(raw) / "pred.jsonl"
        ...     _ = gold.write_text('{"image": "a.jpg", "count": 2}\\n{"image": "b.jpg", "count": 0}\\n')
        ...     _ = pred.write_text('{"image": "a.jpg", "count": 1}\\n')
        ...     check_files(gold, pred, "count").missing
        1
    """
    gold_sha256, pred_sha256 = sha256_file(gold), sha256_file(pred)
    gold_labels = load_labels(gold, task)
    pred_labels = load_labels(pred, task)
    extra = sorted(set(pred_labels) - set(gold_labels))
    if extra:
        raise ValueError(f"predictions name images missing from the gold file: {extra[:5]}")
    return CheckedFiles(gold_sha256, pred_sha256, len(gold_labels), len(pred_labels))


def helper_arguments(args: argparse.Namespace, identity: str, notes: str) -> list[str]:
    """Return the ledger helper arguments of one freeze row.

    Examples:
        >>> namespace = argparse.Namespace(session="s", skill="k", pred=Path("p"), gold=Path("g"),
        ...                                predictor="same-session", acknowledge_label_change=True)
        >>> helper_arguments(namespace, "e", "n")[-1]
        '--acknowledge-label-change'
    """
    arguments = [
        "--session",
        args.session,
        "--skill",
        args.skill,
        "--action",
        PREDICTIONS_FROZEN,
        "--event-id",
        identity,
        "--status",
        "success",
        "--pred",
        str(args.pred),
        "--gold",
        str(args.gold),
        "--predictor",
        args.predictor,
        "--notes",
        notes,
    ]
    return [*arguments, "--acknowledge-label-change"] if args.acknowledge_label_change else arguments


def freeze(args: argparse.Namespace) -> dict[str, Any]:
    """Check both files, record the freeze, and confirm the ledger holds the digests just checked.

    Raises:
        ValueError: When any check fails, the ledger helper refuses, or the files changed while the
            freeze was being recorded.
    """
    ledger = ledger_for_labels(args.gold, args.ledger)
    predictor = Predictor(args.predictor)
    files = check_files(args.gold, args.pred, args.task)
    identity = event_id(args.session, files)
    append_ledger_row(
        args.ledger_helper, ledger, helper_arguments(args, identity, freeze_notes(args.task, predictor, files))
    )
    recorded = next((item for item in read_freezes(ledger) if item.event_id == identity), None)
    if recorded is None:
        raise ValueError(f"the ledger {ledger} holds no successful freeze with event ID {identity}")
    if (recorded.pred_sha256, recorded.gold_sha256) != (files.pred_sha256, files.gold_sha256):
        raise ValueError("a file changed while the freeze was being recorded; write the predictions again and refreeze")
    return {
        "status": "frozen",
        "event_id": identity,
        "frozen_at": recorded.frozen_at,
        "pred_sha256": files.pred_sha256,
        "gold_sha256": files.gold_sha256,
        "label_set": recorded.label_set,
        "predictor": predictor.value,
        "label_entry": recorded.label_entry.value,
        "labels_changed_after_predictions": recorded.labels_changed_after_predictions,
        "gold_images": files.gold_images,
        "predictions": files.predictions,
        "missing_predictions": files.missing,
        "ledger": str(ledger),
    }


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    """Parse freeze inputs."""
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--task", required=True, choices=("count", "flag"))
    parser.add_argument("--gold", required=True, type=Path, help="gold label file the predictions will be scored on")
    parser.add_argument("--pred", required=True, type=Path, help="prediction file to freeze")
    parser.add_argument(
        "--predictor",
        required=True,
        choices=[item.value for item in Predictor],
        help="isolated-subagent, or same-session when the host has no subagent tool (independence not enforced)",
    )
    parser.add_argument("--session", required=True, help="stable session slug used in the event ID")
    parser.add_argument("--skill", required=True, help="skill that ran the prediction")
    parser.add_argument(
        "--ledger", type=Path, help="project ledger (default: ledger.jsonl in the .vision-delivery folder of --gold)"
    )
    parser.add_argument(
        "--acknowledge-label-change",
        action="store_true",
        help="record the freeze although labels changed after predictions existed; the score is then not independent",
    )
    parser.add_argument("--ledger-helper", type=Path, default=LEDGER_HELPER, help=argparse.SUPPRESS)
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    """Freeze the prediction file and print the recorded binding as one JSON line."""
    args = parse_args(argv)
    try:
        result = freeze(args)
    except (ValueError, OSError) as exc:
        print(f"freeze-predictions-error: {exc}", file=sys.stderr)
        return 2
    print(json.dumps(result, sort_keys=True))
    return 0


if __name__ == "__main__":
    sys.exit(main())
