#!/usr/bin/env python3
"""Measure whether a frozen acceptance target still holds on a fresh labeled sample.

Purpose: Reuse the baseline scorer's verdict and interval to report later drift.
Scope: Bind a new measurement to verified acceptance bytes, a passing original baseline,
    and a different gold digest; check label and image reuse when original labels are available.
Usage: Run this CLI with acceptance, baseline evidence, fresh gold/prediction files, task,
    ledger, session, and a new evidence output path. Supply baseline-gold or discover it by
    digest in the ledger folder. Optional frozen-ledger checks remain owned by the scorer.
Outputs: Exclusive JSON evidence, one idempotent ledger event, and plain and JSON stdout.
Failure: Refusals exit 2 with one recheck-error line; scoring times out after 900 seconds.
    Any exception before the ledger append returns rolls back owned evidence. Scorer refusal
    creates no output folder. Drift itself always exits zero.
Used by: Later project monitoring runs and evals/recheck/assert_recheck.py.
"""

from __future__ import annotations

import argparse
import json
import math
import subprocess
import sys
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from typing import Any, NoReturn

from prediction_freeze import append_ledger_row, require_helper
from proof_chain import load_acceptance, load_json, parse_utc, sha256_file
from score_baseline import load_labels


class Drift(str, Enum):
    """Whether the fresh scorer verdict still supports the accepted target."""

    HOLDS = "holds"
    DRIFTED = "drifted"
    UNCERTAIN = "uncertain"


class Shift(str, Enum):
    """Direction of a whole fresh interval relative to the baseline estimate."""

    WORSE = "worse"
    BETTER = "better"
    NO = "no"
    UNKNOWN = "unknown"


class Comparator(str, Enum):
    """Whether larger or smaller measurements satisfy the accepted target."""

    GTE = "gte"
    LTE = "lte"


class Verdict(str, Enum):
    """The scorer's four verdicts, converted at the child-record boundary."""

    PASS = "pass"
    BELOW_TARGET = "below-target"
    INCONCLUSIVE = "inconclusive"
    NO_VERDICT = "no-verdict"


class FreezeState(str, Enum):
    """Whether the scorer verified a freeze and declared an independent measurement."""

    INDEPENDENT = "independent"
    NOT_INDEPENDENT = "not-independent"
    NOT_FROZEN = "not-frozen"


@dataclass(frozen=True)
class Baseline:
    """Validated original measurement fields needed for provenance and comparison."""

    acceptance_id: str
    acceptance_sha256: str
    metric: str
    observed_value: float | None
    gold_sha256: str
    measured_at: str
    task: str


@dataclass(frozen=True)
class ScorerResult:
    """A child scorer record and its converted comparison fields and plain output."""

    record: dict[str, Any]
    plain: str
    drift: Drift
    comparator: Comparator
    interval: tuple[float, float] | None


class _Parser(argparse.ArgumentParser):
    """Route command-line refusals through the same single-line error contract."""

    def error(self, message: str) -> NoReturn:
        """Refuse invalid arguments without argparse's extra usage lines.

        Examples:
            >>> _Parser().error("missing input")
            Traceback (most recent call last):
            ...
            ValueError: missing input
        """
        raise ValueError(message)


def _parse_args() -> argparse.Namespace:
    """Read paths and session metadata without constraining the scorer's task names."""
    parser = _Parser(description=__doc__.splitlines()[0])
    for name in ("acceptance", "baseline-evidence", "gold", "pred", "ledger", "evidence-out"):
        parser.add_argument(f"--{name}", required=True, type=Path)
    parser.add_argument("--task", required=True)
    parser.add_argument("--session", required=True)
    parser.add_argument("--skill", default="deliver-cv-project")
    parser.add_argument("--frozen-ledger", type=Path)
    parser.add_argument("--baseline-gold", type=Path)
    return parser.parse_args()


def _text(record: dict[str, Any], field: str) -> str:
    """Require a nonempty text field from an external JSON record."""
    value = record.get(field)
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"baseline scorer record needs {field}")
    return value


def _digest(record: dict[str, Any], field: str) -> str:
    """Require a lowercase SHA-256 field from a scorer record."""
    value = _text(record, field)
    if len(value) != 64 or any(char not in "0123456789abcdef" for char in value):
        raise ValueError(f"baseline scorer record needs a SHA-256 {field}")
    return value


def _number(value: Any) -> float | None:
    """Require a finite observed value or the scorer's null estimate."""
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
        raise ValueError("scorer observed values and interval bounds must be finite numbers or null")
    return float(value)


def _load_baseline(path: Path) -> Baseline:
    """Validate required scorer provenance before inspecting any later measurement."""
    record = load_json(path, "baseline evidence")
    if isinstance(record.get("recheck"), dict):
        raise ValueError("baseline evidence must not be a recheck")
    if record.get("verdict") != Verdict.PASS.value:
        raise ValueError("baseline evidence must have a pass verdict")
    target = record.get("target")
    if not isinstance(target, dict) or "observed_value" not in record:
        raise ValueError("baseline must be a scorer record with target and observed_value")
    baseline = Baseline(
        _text(target, "acceptance_id"),
        _digest(target, "acceptance_sha256"),
        _text(target, "metric"),
        _number(record["observed_value"]),
        _digest(record, "gold_sha256"),
        _text(record, "measured_at"),
        _text(record, "task"),
    )
    parse_utc(baseline.measured_at, "baseline measured_at")
    return baseline


def _check_paths(args: argparse.Namespace) -> None:
    """Reject symlinks in all lexical path components before reading any input."""
    paths = (
        args.acceptance,
        args.baseline_evidence,
        args.gold,
        args.pred,
        args.ledger,
        args.frozen_ledger,
        args.baseline_gold,
        args.evidence_out,
    )
    for path in paths:
        if path is None:
            continue
        absolute = path if path.is_absolute() else Path.cwd() / path
        for candidate in (absolute, *absolute.parents):
            try:
                if candidate.is_symlink():
                    raise ValueError(f"path may not contain a symlink: {candidate}")
            except OSError as exc:
                raise ValueError(f"cannot inspect path {candidate}: {exc}") from exc


def _baseline_labels(args: argparse.Namespace, dataset_sha256: str) -> Path | None:
    """Find the original labels by verified digest, refusing an incorrect explicit path."""
    if args.baseline_gold is not None:
        if sha256_file(args.baseline_gold) != dataset_sha256:
            raise ValueError("baseline gold SHA-256 differs from the acceptance dataset")
        return Path(args.baseline_gold)
    if not args.ledger.parent.is_dir():
        return None
    for path in args.ledger.parent.iterdir():
        if not path.is_symlink() and path.is_file() and sha256_file(path) == dataset_sha256:
            return path
    return None


def _check_overlap(args: argparse.Namespace, dataset_sha256: str) -> bool:
    """Refuse reused labels or image identities when the original labels are available."""
    original = _baseline_labels(args, dataset_sha256)
    if original is None:
        return False
    baseline_labels = load_labels(original, args.task)
    fresh_labels = load_labels(args.gold, args.task)
    if fresh_labels == baseline_labels:
        raise ValueError("gold label maps match the baseline; labels must be a fresh sample")
    overlap = len(baseline_labels.keys() & fresh_labels.keys())
    if overlap:
        raise ValueError(f"fresh gold shares {overlap} image identities with the baseline")
    return True


def _preflight(args: argparse.Namespace, baseline: Baseline) -> bool:
    """Bind provenance and freshness to verified acceptance, then check label overlap."""
    acceptance = load_acceptance(args.acceptance)
    if sha256_file(args.acceptance) != baseline.acceptance_sha256:
        raise ValueError("acceptance SHA-256 differs from the baseline's frozen target")
    if baseline.acceptance_id != acceptance["acceptance_id"]:
        raise ValueError("baseline acceptance_id differs from the acceptance")
    if baseline.gold_sha256 != acceptance["dataset_sha256"]:
        raise ValueError("baseline gold SHA-256 differs from the acceptance dataset")
    if args.task != baseline.task:
        raise ValueError("task differs from the baseline task")
    if sha256_file(args.gold) == acceptance["dataset_sha256"]:
        raise ValueError("gold SHA-256 matches the acceptance dataset; labels must be a fresh sample")
    if args.evidence_out.exists() or args.evidence_out.is_symlink():
        raise ValueError("evidence output already exists; choose a new path")
    if args.evidence_out.resolve() == args.ledger.resolve():
        raise ValueError("evidence output and ledger must use different paths")
    return _check_overlap(args, acceptance["dataset_sha256"])


def _scorer_result(record: dict[str, Any], plain: str) -> ScorerResult:
    """Convert the child's closed option sets once and retain its full JSON record."""
    verdict = Verdict(record["verdict"])
    comparator = Comparator(record["target"]["comparator"])
    low, high = _number(record.get("interval_lower")), _number(record.get("interval_upper"))
    interval = (low, high) if low is not None and high is not None else None
    drift = {
        Verdict.PASS: Drift.HOLDS,
        Verdict.BELOW_TARGET: Drift.DRIFTED,
        Verdict.INCONCLUSIVE: Drift.UNCERTAIN,
        Verdict.NO_VERDICT: Drift.UNCERTAIN,
    }[verdict]
    return ScorerResult(record, plain, drift, comparator, interval)


def _run_scorer(args: argparse.Namespace) -> ScorerResult:
    """Read the scorer's JSON stdout without creating output folders before success."""
    command = [
        sys.executable,
        str(Path(__file__).with_name("score_baseline.py")),
        "--gold",
        str(args.gold),
        "--pred",
        str(args.pred),
        "--task",
        args.task,
        "--acceptance",
        str(args.acceptance),
    ]
    if args.frozen_ledger is not None:
        command.extend(("--frozen-ledger", str(args.frozen_ledger)))
    try:
        done = subprocess.run(command, capture_output=True, text=True, encoding="utf-8", check=False, timeout=900)
    except subprocess.TimeoutExpired as exc:
        raise ValueError("scorer timed out after 900 seconds") from exc
    if done.returncode != 0:
        lines = (done.stderr.strip() or done.stdout.strip()).splitlines()
        raise ValueError(lines[-1] if lines else f"scorer exited {done.returncode}")
    lines = done.stdout.splitlines()
    record = json.loads(lines[-1])
    if not isinstance(record, dict):
        raise ValueError("fresh scorer evidence must contain a JSON object")
    return _scorer_result(record, lines[0])


def compare_baseline(interval: tuple[float, float] | None, baseline: float | None, comparator: Comparator) -> Shift:
    """Compare the entire fresh interval with the original point estimate.

    Args:
        interval: Fresh 95% bounds, or no interval.
        baseline: Original observed value, or no estimate.
        comparator: Direction in which the frozen target is met.

    Returns:
        Better, worse, overlapping, or unavailable comparison.

    Examples:
        >>> compare_baseline((0.3, 0.5), 0.8, Comparator.GTE).value
        'worse'
        >>> compare_baseline((0.3, 0.5), 0.8, Comparator.LTE).value
        'better'
        >>> compare_baseline((0.3, 0.5), 0.5, Comparator.GTE).value
        'no'
        >>> compare_baseline(None, 0.8, Comparator.GTE).value
        'unknown'
        >>> compare_baseline((0.3, 0.5), None, Comparator.LTE).value
        'unknown'
    """
    if interval is None or baseline is None:
        return Shift.UNKNOWN
    low, high = interval
    if low <= baseline <= high:
        return Shift.NO
    better = low > baseline if comparator == Comparator.GTE else high < baseline
    return Shift.BETTER if better else Shift.WORSE


@contextmanager
def _write_exclusive(path: Path, record: dict[str, Any]) -> Iterator[None]:
    """Own exclusive evidence through the append, rolling it back on any exception."""
    stream = path.open("x", encoding="utf-8", newline="\n")
    try:
        with stream:
            json.dump(record, stream, indent=2, allow_nan=False)
            stream.write("\n")
        yield
    except BaseException:
        path.unlink(missing_ok=True)
        raise


def _value(value: float | None) -> str:
    """Render an estimate consistently for notes and the plain summary, preserving zero."""
    return "none" if value is None else str(value)


def _freeze_state(record: dict[str, Any]) -> FreezeState:
    """Convert the scorer's freeze object to the recheck's closed state set."""
    freeze = record.get("predictions_frozen")
    if not isinstance(freeze, dict):
        return FreezeState.NOT_FROZEN
    return FreezeState.INDEPENDENT if freeze.get("independent") is True else FreezeState.NOT_INDEPENDENT


def _record_measurement(
    args: argparse.Namespace,
    fresh: ScorerResult,
    baseline: Baseline,
    shift: Shift,
    overlap_checked: bool,
) -> None:
    """Write final evidence and append the bound ledger event, rolling evidence back on refusal."""
    record = fresh.record
    record["recheck"] = {
        "baseline_evidence_sha256": sha256_file(args.baseline_evidence),
        "baseline_measured_at": baseline.measured_at,
        "baseline_observed_value": baseline.observed_value,
        "baseline_gold_sha256": baseline.gold_sha256,
        "drift": fresh.drift.value,
        "shifted_from_baseline": shift.value,
        "image_overlap_checked": overlap_checked,
        "predictions_frozen": _freeze_state(record).value,
    }
    _reuse_measurement_time(args.ledger, _event_id(args, record), record)
    args.evidence_out.parent.mkdir(parents=True, exist_ok=True)
    with _write_exclusive(args.evidence_out, record):
        _append_measurement(args, fresh, baseline, shift)


def _event_id(args: argparse.Namespace, record: dict[str, Any]) -> str:
    """Bind one measurement identity to its acceptance, baseline, predictions, and labels."""
    identities = (
        record["target"]["acceptance_sha256"],
        record["recheck"]["baseline_evidence_sha256"],
        record["pred_sha256"],
        record["gold_sha256"],
    )
    suffix = "-".join(digest[:12] for digest in identities)
    return f"manual:{args.session}:recheck_measured:{suffix}"


def _reuse_measurement_time(ledger: Path, event_id: str, record: dict[str, Any]) -> None:
    """Retain a prior measurement's time so an exact replay preserves its evidence digest."""
    if not ledger.is_file():
        return
    for line in ledger.read_text(encoding="utf-8").splitlines():
        try:
            row = json.loads(line)
        except ValueError:
            continue
        if not isinstance(row, dict) or row.get("event_id") != event_id or row.get("status") != "success":
            continue
        measured_at = row.get("evidence_measured_at")
        if isinstance(measured_at, str):
            parse_utc(measured_at, "prior recheck measured_at")
            record["measured_at"] = measured_at
        return


def _append_measurement(args: argparse.Namespace, fresh: ScorerResult, baseline: Baseline, shift: Shift) -> None:
    """Append evidence-derived fields under an acceptance- and baseline-specific event ID."""
    notes = _summary(fresh, baseline, shift)
    append_ledger_row(
        require_helper(),
        args.ledger,
        [
            "--session",
            args.session,
            "--skill",
            args.skill,
            "--action",
            "recheck_measured",
            "--status",
            "success",
            "--source",
            "skill",
            "--acceptance",
            str(args.acceptance),
            "--evidence",
            str(args.evidence_out),
            "--event-id",
            _event_id(args, fresh.record),
            "--notes",
            notes,
        ],
    )


def _summary(fresh: ScorerResult, baseline: Baseline, shift: Shift) -> str:
    """State the drift and geometric interval position without reversing error metrics."""
    sentence = "No interval to compare with the baseline value."
    if shift == Shift.NO:
        sentence = "The fresh interval includes the baseline value."
    elif shift in (Shift.WORSE, Shift.BETTER):
        below = (shift == Shift.WORSE) == (fresh.comparator == Comparator.GTE)
        direction = "below" if below else "above"
        sentence = f"The fresh interval lies wholly {direction} the baseline value."
    summary = (
        f"Recheck against acceptance {fresh.record['target']['acceptance_id']}: {fresh.drift.value.upper()}. "
        f"Baseline {_value(baseline.observed_value)} on {baseline.measured_at}; "
        f"now {_value(fresh.record['observed_value'])}. {sentence}"
    )
    if shift != Shift.UNKNOWN:
        summary += " This compares the fresh interval with the baseline's single value; it is not a test of change."
    recheck = fresh.record["recheck"]
    if not recheck["image_overlap_checked"]:
        summary += " Overlap with the baseline images was not checked."
    freeze = FreezeState(recheck["predictions_frozen"])
    if freeze == FreezeState.NOT_FROZEN:
        summary += " The fresh predictions were not frozen before scoring."
    elif freeze == FreezeState.NOT_INDEPENDENT:
        summary += " The freeze says this is not an independent measurement."
    return summary


def main() -> int:
    """Run one recheck, returning zero for any measured drift status and two for refusal.

    Examples:
        Use ``python3 resources/scripts/recheck.py --help`` to see required input paths.
    """
    try:
        args = _parse_args()
        _check_paths(args)
        baseline = _load_baseline(args.baseline_evidence)
        overlap_checked = _preflight(args, baseline)
        fresh = _run_scorer(args)
        shift = compare_baseline(fresh.interval, baseline.observed_value, fresh.comparator)
        _record_measurement(args, fresh, baseline, shift, overlap_checked)
    except (OSError, ValueError, KeyError, TypeError, IndexError) as exc:
        reason = " ".join(str(exc).splitlines())
        print(f"recheck-error: {reason}", file=sys.stderr)
        return 2
    print(fresh.plain)
    print(_summary(fresh, baseline, shift))
    print(json.dumps(fresh.record, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
