#!/usr/bin/env python3
"""Validate one locally digest-bound Sentinel decision chain.

The baseline must be the evidence that `score_baseline.py --acceptance --evidence-out` writes: a
record with a `target` block, `task`, `gold_sha256`, and `pred_sha256`. Any other record is
refused. The validator finds the label file and the prediction file by those digests, scores them
again in this process with the scorer's own functions, and requires the record to match the
result field by field. It never runs artifact code.

A chain also fails when a later ledger row contradicts it: a failed run of a proof action after its
success, or a later recheck that scored below the target.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import sys
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from enum import Enum
from pathlib import Path
from typing import Any

from proof_chain import SHA256_RE, load_acceptance, load_json, parse_utc, sha256_file
from score_baseline import (
    Target,
    check_target,
    load_labels,
    metric_dispatch,
    score_target,
)
from validate_delivery_handoff import validate_handoff

STATE_DIR = ".vision-delivery"
REQUIRED_LEDGER_ACTIONS = {
    "baseline_measured",
    "artifact_verified",
    "delivery_handoff_emitted",
    "crossover_delivered",
}
REPORT_ACTION = "decision_report_emitted"
RECHECK_ACTION = "recheck_measured"
ARTIFACT_LEDGER_ACTIONS = {"artifact_verified", "delivery_handoff_emitted"}
#: Ledger statuses that open an action without deciding it; every other non-success status contradicts a success.
OPEN_STATUSES = frozenset({"attempted"})
#: Target fields of scorer evidence; they sit in its `target` block.
TARGET_FIELDS = ("acceptance_id", "acceptance_sha256", "metric", "comparator", "threshold")
#: Fields scorer evidence must carry before anything else is read from it.
SCORER_FIELDS = ("target", "task", "gold_sha256", "pred_sha256")
UNCERTAIN_RECHECK = "The latest recheck could not show whether the target still holds; label more fresh images."


class Task(str, Enum):
    """The scorer task a baseline was measured for."""

    COUNT = "count"
    FLAG = "flag"
    TEXT = "text"


class Drift(str, Enum):
    """The result a recheck recorded for a frozen target on a fresh sample."""

    HOLDS = "holds"
    DRIFTED = "drifted"
    UNCERTAIN = "uncertain"


@dataclass(frozen=True)
class ScoredSearch:
    """Where to find the label file and prediction file a baseline names by digest."""

    state_dir: Path
    gold: Path | None = None
    pred: Path | None = None


@dataclass(frozen=True)
class ScoredFiles:
    """The label file and prediction file whose digests a baseline names."""

    gold: Path
    pred: Path


@dataclass(frozen=True)
class ChainInputs:
    """Paths of the files that make up one decision chain."""

    project_root: Path
    acceptance: Path
    baseline: Path
    handoff: Path
    ledger: Path
    economics: Path
    report: Path | None = None
    gold: Path | None = None
    pred: Path | None = None


def _binding(data: dict[str, Any], label: str) -> tuple[str, str]:
    """Return required acceptance ID and digest fields from one record."""
    acceptance_id = data.get("acceptance_id")
    acceptance_sha256 = data.get("acceptance_sha256")
    if not isinstance(acceptance_id, str) or not acceptance_id:
        raise ValueError(f"{label} is missing acceptance_id")
    if not isinstance(acceptance_sha256, str) or len(acceptance_sha256) != 64:
        raise ValueError(f"{label} is missing acceptance_sha256")
    return acceptance_id, acceptance_sha256


def _validate_binding(data: dict[str, Any], label: str, acceptance_id: str, acceptance_sha256: str) -> None:
    """Require one record to carry the selected acceptance binding."""
    if _binding(data, label) != (acceptance_id, acceptance_sha256):
        raise ValueError(f"{label} does not match the frozen acceptance")


def _scorer_shape(baseline: dict[str, Any]) -> tuple[dict[str, Any], Task]:
    """Return the target block and task of scorer evidence, and refuse any other record."""
    target = baseline.get("target")
    if any(field not in baseline for field in SCORER_FIELDS) or not isinstance(target, dict):
        raise ValueError(
            "baseline must be scorer evidence with target, task, gold_sha256, and pred_sha256;"
            " write it with score_baseline.py --acceptance --evidence-out"
        )
    for field in ("gold_sha256", "pred_sha256"):
        if not isinstance(baseline[field], str) or SHA256_RE.fullmatch(baseline[field]) is None:
            raise ValueError(f"baseline {field} must be lowercase SHA-256")
    try:
        task = Task(baseline["task"])
    except ValueError as exc:
        raise ValueError(f"baseline task must be one of {[item.value for item in Task]}") from exc
    return target, task


def _check_no_shadow(baseline: dict[str, Any], target: dict[str, Any]) -> None:
    """Refuse a top-level copy of a target field or of the dataset digest that disagrees with the scorer's own."""
    for field in TARGET_FIELDS:
        if field in baseline and baseline[field] != target.get(field):
            raise ValueError(f"baseline top-level {field} disagrees with its target block")
    if "dataset_sha256" in baseline and baseline["dataset_sha256"] != baseline["gold_sha256"]:
        raise ValueError("baseline top-level dataset_sha256 disagrees with its gold_sha256")


def _check_scored_verdict(baseline: dict[str, Any], comparator: str, threshold: float) -> None:
    """Reject a baseline unless its verdict is pass and its 95% interval bound clears the threshold."""
    verdict = baseline.get("verdict")
    if verdict is None:
        raise ValueError("baseline verdict is missing; only pass counts as a passed acceptance")
    if verdict != "pass":
        raise ValueError(f"baseline verdict is {verdict}; only pass counts as a passed acceptance")
    bound = baseline.get("interval_lower" if comparator == "gte" else "interval_upper")
    if bound is None:
        raise ValueError("baseline pass verdict has no 95% interval bound")
    if isinstance(bound, bool) or not isinstance(bound, int | float) or not math.isfinite(bound):
        raise ValueError("baseline interval bound must be finite numeric")
    if not (bound >= threshold if comparator == "gte" else bound <= threshold):
        raise ValueError("baseline 95% interval does not clear the frozen threshold")


def check_baseline_record(baseline: dict[str, Any], acceptance: dict[str, Any], acceptance_sha256: str) -> Task:
    """Check what a scorer evidence record states about itself against the frozen acceptance.

    Binding fields are read only from the record's `target` block. Its `gold_sha256` must equal
    the acceptance `dataset_sha256`. This check reads no other file; `check_baseline` adds the
    re-score.

    Args:
        baseline: The scorer evidence record.
        acceptance: The frozen acceptance record.
        acceptance_sha256: SHA-256 of the frozen acceptance file.

    Returns:
        The scorer task the record names.

    Raises:
        ValueError: When the record is not scorer evidence, names another target or dataset, has
            no pass verdict, does not clear the threshold, or predates the acceptance.

    Examples:
        >>> acceptance = {"acceptance_id": "a/v1", "dataset_sha256": "d" * 64, "model_or_pipeline": "m",
        ...               "metric": "accuracy", "comparator": "gte", "threshold": 0.8,
        ...               "frozen_at": "2026-01-01T00:00:00Z"}
        >>> scored = {"target": {"acceptance_id": "a/v1", "acceptance_sha256": "s" * 64, "metric": "accuracy",
        ...           "comparator": "gte", "threshold": 0.8}, "task": "flag", "gold_sha256": "d" * 64,
        ...           "pred_sha256": "e" * 64, "observed_value": 1.0, "verdict": "pass", "interval_lower": 0.91,
        ...           "passes_acceptance": True, "measured_at": "2026-01-02T00:00:00Z"}
        >>> check_baseline_record(scored, acceptance, "s" * 64).value
        'flag'
        >>> check_baseline_record({**scored, "threshold": 0.1}, acceptance, "s" * 64)
        Traceback (most recent call last):
        ...
        ValueError: baseline top-level threshold disagrees with its target block
        >>> check_baseline_record({"verdict": "pass"}, acceptance, "s" * 64)  # doctest: +ELLIPSIS
        Traceback (most recent call last):
        ...
        ValueError: baseline must be scorer evidence with target, task, gold_sha256, and pred_sha256; ...
    """
    target, task = _scorer_shape(baseline)
    _check_no_shadow(baseline, target)
    _validate_binding(target, "baseline result", str(acceptance["acceptance_id"]), acceptance_sha256)
    if baseline["gold_sha256"] != acceptance["dataset_sha256"]:
        raise ValueError("baseline dataset digest does not match acceptance")
    for field in ("metric", "comparator", "threshold"):
        if target.get(field) != acceptance[field]:
            raise ValueError(f"baseline {field} does not match acceptance")
    observed = baseline.get("observed_value")
    if isinstance(observed, bool) or not isinstance(observed, int | float) or not math.isfinite(observed):
        raise ValueError("baseline observed_value must be finite numeric")
    threshold = float(acceptance["threshold"])
    _check_scored_verdict(baseline, str(acceptance["comparator"]), threshold)
    passes = observed >= threshold if acceptance["comparator"] == "gte" else observed <= threshold
    if baseline.get("passes_acceptance") is not passes:
        raise ValueError("baseline passes_acceptance disagrees with the frozen criterion")
    if not passes:
        raise ValueError("baseline does not pass the frozen acceptance criterion")
    measured_at = parse_utc(baseline.get("measured_at"), "baseline measured_at")
    if measured_at < parse_utc(acceptance["frozen_at"], "acceptance frozen_at"):
        raise ValueError("baseline measurement predates frozen acceptance")
    if measured_at > datetime.now(timezone.utc) + timedelta(minutes=5):
        raise ValueError("baseline measurement is unreasonably far in the future")
    return task


def _state_files(state_dir: Path) -> list[Path]:
    """Return the regular non-symlink files directly inside the state folder, or none when it is a symlink."""
    if state_dir.is_symlink() or not state_dir.is_dir():
        return []
    return sorted(path for path in state_dir.iterdir() if not path.is_symlink() and path.is_file())


def find_scored_files(baseline: dict[str, Any], search: ScoredSearch) -> ScoredFiles:
    """Return the label file and prediction file whose SHA-256 the baseline names.

    An explicit file must have the named digest. Without one, the first regular non-symlink file
    in the state folder with that digest is used; files with equal bytes score the same.

    Args:
        baseline: Scorer evidence that passed `check_baseline_record`.
        search: The state folder and any explicit `--gold` / `--pred` files.

    Returns:
        The two files to re-score.

    Raises:
        ValueError: When an explicit file has another digest, or no file has the named digest.

    Examples:
        >>> import tempfile
        >>> baseline = {"gold_sha256": "d" * 64, "pred_sha256": "e" * 64}
        >>> with tempfile.TemporaryDirectory() as folder:  # doctest: +ELLIPSIS
        ...     find_scored_files(baseline, ScoredSearch(Path(folder)))
        Traceback (most recent call last):
        ...
        ValueError: no regular file in the project's .vision-delivery/ folder has the baseline gold_sha256 ...
    """
    digests: dict[Path, str] = {}
    if search.gold is None or search.pred is None:
        digests = {path: sha256_file(path) for path in _state_files(search.state_dir)}
    found: dict[str, Path] = {}
    for field, option, explicit in (("gold_sha256", "--gold", search.gold), ("pred_sha256", "--pred", search.pred)):
        wanted = str(baseline[field])
        if explicit is not None:
            if sha256_file(explicit) != wanted:
                raise ValueError(f"{option} {explicit} does not have the baseline {field}")
            found[field] = explicit
            continue
        match = next((path for path, digest in digests.items() if digest == wanted), None)
        if match is None:
            raise ValueError(
                f"no regular file in the project's {STATE_DIR}/ folder has the baseline {field} {wanted[:12]};"
                " pass --gold <label file> and --pred <prediction file>"
            )
        found[field] = match
    return ScoredFiles(gold=found["gold_sha256"], pred=found["pred_sha256"])


def rescore(task: Task, target: Target, files: ScoredFiles) -> dict[str, Any]:
    """Score the label and prediction files again with the scorer's own functions.

    Args:
        task: The scorer task.
        target: The frozen target to score against.
        files: The label file and prediction file.

    Returns:
        The re-scored values under the names the scorer's evidence record uses.

    Raises:
        ValueError: When the task does not score the metric, the target is invalid, or a file is
            not a usable label file.

    Examples:
        >>> rescore(Task.TEXT, Target("accuracy", "gte", 0.8), ScoredFiles(Path("g"), Path("p")))
        Traceback (most recent call last):
        ...
        ValueError: metric 'accuracy' is not scored for task text
    """
    allowed, tally = metric_dispatch(task.value)
    if target.metric not in allowed:
        raise ValueError(f"metric {target.metric!r} is not scored for task {task.value}")
    check_target(target)
    gold = load_labels(files.gold, task.value)
    pred = load_labels(files.pred, task.value)
    extra = sorted(set(pred) - set(gold))
    if extra:
        raise ValueError(f"the prediction file names images missing from the label file: {extra[:5]}")
    missing = len(set(gold) - set(pred))
    scored = score_target(task.value, target, tally(gold, pred)[target.metric], missing, len(gold))
    low, high = scored.interval if scored.interval is not None else (None, None)
    return {
        "metric": target.metric,
        "verdict": scored.verdict.value,
        "numerator": scored.tally.numerator,
        "denominator": scored.tally.denominator,
        "observed_value": scored.tally.value,
        "interval_lower": low,
        "interval_upper": high,
        "missing_predictions": scored.missing,
        "images": scored.images,
    }


def _same(recorded: Any, computed: Any) -> bool:
    """Return whether a recorded value equals a computed one, without letting a boolean pass for a number."""
    return recorded == computed and isinstance(recorded, bool) == isinstance(computed, bool)


def check_baseline(
    baseline: dict[str, Any], acceptance: dict[str, Any], acceptance_sha256: str, search: ScoredSearch
) -> ScoredFiles:
    """Check a scorer evidence record and require a re-score of its files to reproduce it.

    The re-score runs the scorer's functions in this process on the files the record names by
    digest, against the frozen acceptance target and the record's task. Metric, verdict, numerator,
    denominator, observed value, both interval bounds, missing predictions, and image count must
    equal the record.

    Args:
        baseline: The scorer evidence record.
        acceptance: The frozen acceptance record.
        acceptance_sha256: SHA-256 of the frozen acceptance file.
        search: Where to find the label file and prediction file.

    Returns:
        The label file and prediction file that reproduced the record.

    Raises:
        ValueError: When `check_baseline_record` refuses the record, a file cannot be found, or a
            re-scored field differs; the message names the field.

    Examples:
        >>> search = ScoredSearch(Path("."))
        >>> check_baseline({"verdict": "pass"}, {"acceptance_id": "a/v1"}, "s" * 64, search)  # doctest: +ELLIPSIS
        Traceback (most recent call last):
        ...
        ValueError: baseline must be scorer evidence with target, task, gold_sha256, and pred_sha256; ...
    """
    task = check_baseline_record(baseline, acceptance, acceptance_sha256)
    files = find_scored_files(baseline, search)
    target = Target(
        str(acceptance["metric"]),
        str(acceptance["comparator"]),
        float(acceptance["threshold"]),
        str(acceptance["acceptance_id"]),
        acceptance_sha256,
    )
    recorded = {**baseline, "metric": baseline["target"].get("metric")}
    for field, value in rescore(task, target, files).items():
        if not _same(recorded.get(field), value):
            raise ValueError(
                f"baseline {field} does not match a re-score of its label and prediction files:"
                f" recorded {recorded.get(field)!r}, re-scored {value!r}"
            )
    return files


def check_handoff_binding(handoff: dict[str, Any], acceptance_id: str, acceptance_sha256: str) -> None:
    """Require the handoff to name the same frozen acceptance as the rest of the chain.

    Args:
        handoff: The validated handoff record.
        acceptance_id: The frozen acceptance ID.
        acceptance_sha256: SHA-256 of the frozen acceptance file.

    Raises:
        ValueError: When the handoff names another acceptance revision.

    Examples:
        >>> check_handoff_binding({"acceptance_id": "a/v2", "acceptance_sha256": "s" * 64}, "a/v1", "s" * 64)
        Traceback (most recent call last):
        ...
        ValueError: delivery handoff does not match the frozen acceptance
    """
    _validate_binding(handoff, "delivery handoff", acceptance_id, acceptance_sha256)


def check_economics(economics: dict[str, Any], acceptance_id: str, acceptance_sha256: str) -> None:
    """Check that the cost model output is bound to this frozen acceptance.

    Args:
        economics: The `cost_model.py --acceptance ... --json` record.
        acceptance_id: The frozen acceptance ID.
        acceptance_sha256: SHA-256 of the frozen acceptance file.

    Raises:
        ValueError: When the economics proof is unbound or names another acceptance.

    Examples:
        >>> check_economics({"proof": {"status": "unbound"}}, "a/v1", "s" * 64)
        Traceback (most recent call last):
        ...
        ValueError: economics result is not bound to frozen acceptance
    """
    proof = economics.get("proof")
    if not isinstance(proof, dict) or proof.get("status") != "bound":
        raise ValueError("economics result is not bound to frozen acceptance")
    _validate_binding(proof, "economics result", acceptance_id, acceptance_sha256)


def load_ledger(path: Path) -> list[dict[str, Any]]:
    """Load a regular JSONL ledger and reject malformed rows.

    Args:
        path: The ledger file.

    Returns:
        The ledger rows in file order.

    Raises:
        ValueError: When the ledger is not a regular file or a row is not a JSON object.

    Examples:
        >>> load_ledger(Path("absent-ledger.jsonl"))
        Traceback (most recent call last):
        ...
        ValueError: ledger must be a regular non-symlink file
    """
    if path.is_symlink() or not path.is_file():
        raise ValueError("ledger must be a regular non-symlink file")
    records: list[dict[str, Any]] = []
    for line_number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        if not line.strip():
            continue
        try:
            record = json.loads(line)
        except json.JSONDecodeError as exc:
            raise ValueError(f"ledger row {line_number} is invalid JSON") from exc
        if not isinstance(record, dict):
            raise ValueError(f"ledger row {line_number} is not an object")
        records.append(record)
    return records


def check_ledger(
    records: list[dict[str, Any]], acceptance_id: str, acceptance_sha256: str, artifact_sha256: str
) -> list[dict[str, Any]]:
    """Require one successful, acceptance-bound ledger row for every proof action.

    Args:
        records: The ledger rows.
        acceptance_id: The frozen acceptance ID.
        acceptance_sha256: SHA-256 of the frozen acceptance file.
        artifact_sha256: The checked artifact tree digest.

    Returns:
        The matched proof rows.

    Raises:
        ValueError: On a conflicting event ID, a wrong digest, or a missing proof action.

    Examples:
        >>> check_ledger([], "a/v1", "s" * 64, "t" * 64)  # doctest: +ELLIPSIS
        Traceback (most recent call last):
        ...
        ValueError: ledger is missing successful proof actions: artifact_verified, baseline_measured, ...
    """
    matched_actions: set[str] = set()
    matched_records: list[dict[str, Any]] = []
    seen_events: dict[str, dict[str, Any]] = {}
    for record in records:
        event_id = record.get("event_id")
        if not isinstance(event_id, str) or not event_id:
            raise ValueError("ledger contains a row without event_id")
        previous = seen_events.get(event_id)
        if previous is not None and previous != record:
            raise ValueError(f"ledger contains conflicting event_id: {event_id}")
        seen_events[event_id] = record
        action = record.get("action")
        if action not in REQUIRED_LEDGER_ACTIONS | {REPORT_ACTION} or record.get("status") != "success":
            continue
        if record.get("acceptance_id") != acceptance_id:
            continue
        _validate_binding(record, f"ledger action {action}", acceptance_id, acceptance_sha256)
        if action in ARTIFACT_LEDGER_ACTIONS and record.get("artifact_sha256") != artifact_sha256:
            raise ValueError(f"ledger action {action} has the wrong artifact digest")
        if action in REQUIRED_LEDGER_ACTIONS:
            matched_actions.add(str(action))
            matched_records.append(record)
    missing_actions = sorted(REQUIRED_LEDGER_ACTIONS - matched_actions)
    if missing_actions:
        raise ValueError(f"ledger is missing successful proof actions: {', '.join(missing_actions)}")
    return matched_records


def recheck_drift(row: dict[str, Any]) -> Drift | None:
    """Return the drift a `recheck_measured` row records, or None when it records none.

    Only the top-level `drift` field counts: the ledger helper reads it from the recheck evidence
    file. Free-form `notes` are never read.

    Examples:
        >>> recheck_drift({"drift": "uncertain", "notes": "drift=holds"}).value
        'uncertain'
        >>> recheck_drift({"notes": "drift=drifted; shifted=worse"}) is None
        True
        >>> recheck_drift({"drift": "pass"}) is None
        True
    """
    try:
        return Drift(row.get("drift"))
    except ValueError:
        return None


def _latest_recheck_caveats(records: list[dict[str, Any]], acceptance_sha256: str) -> tuple[str, ...]:
    """Fail on a latest recheck that drifted; return a caveat for one that was uncertain."""
    rechecks = [
        row
        for row in records
        if row.get("action") == RECHECK_ACTION
        and row.get("status") == "success"
        and row.get("acceptance_sha256") == acceptance_sha256
    ]
    if not rechecks:
        return ()
    drift = recheck_drift(rechecks[-1])
    if drift is None:
        raise ValueError("the latest recheck row for this acceptance records no drift result")
    if drift == Drift.DRIFTED:
        raise ValueError("the latest recheck scored below the target")
    return (UNCERTAIN_RECHECK,) if drift == Drift.UNCERTAIN else ()


def _check_no_later_failure(
    records: list[dict[str, Any]], acceptance_sha256: str, artifact_sha256: str, action: str
) -> None:
    """Fail when the last decided row for one proof action, after a success, is not a success.

    The ledger helper binds a failed row to its acceptance and artifact only when those files are
    passed to it, so a row that names no acceptance or artifact digest is counted; a row that names
    another one is skipped.
    """
    latest: str | None = None
    succeeded = False
    for row in records:
        if row.get("action") != action or row.get("acceptance_sha256", acceptance_sha256) != acceptance_sha256:
            continue
        if row.get("artifact_sha256", artifact_sha256) != artifact_sha256:
            continue
        status = str(row.get("status"))
        if status in OPEN_STATUSES:
            continue
        succeeded = succeeded or status == "success"
        latest = status
    if succeeded and latest != "success":
        raise ValueError(f"a later ledger row records {action} as {latest} after its success")


def check_later_records(
    records: list[dict[str, Any]], acceptance_sha256: str, artifact_sha256: str, actions: Iterable[str]
) -> tuple[str, ...]:
    """Fail when a later ledger row contradicts the chain; return caveats that do not fail it.

    For each proof action, the last decided row that names this acceptance digest and artifact
    digest, or names none, must be a success; rows are read in file order and `attempted` rows
    decide nothing. The latest successful
    `recheck_measured` row for the acceptance digest must not record `drifted`; `uncertain` adds a
    caveat.

    Args:
        records: The ledger rows in file order.
        acceptance_sha256: SHA-256 of the frozen acceptance file.
        artifact_sha256: The checked artifact tree digest.
        actions: The proof actions the chain needs.

    Returns:
        Plain caveat sentences.

    Raises:
        ValueError: When a later row records a failed proof action or a drifted recheck.

    Examples:
        >>> rows = [{"action": "artifact_verified", "acceptance_sha256": "s", "status": "success"},
        ...         {"action": "artifact_verified", "acceptance_sha256": "s", "status": "failed"}]
        >>> check_later_records(rows, "s", "t", ["artifact_verified"])
        Traceback (most recent call last):
        ...
        ValueError: a later ledger row records artifact_verified as failed after its success
        >>> recheck = {"action": "recheck_measured", "acceptance_sha256": "s", "status": "success",
        ...            "drift": "uncertain"}
        >>> check_later_records(rows[:1] + [recheck], "s", "t", ["artifact_verified"])
        ('The latest recheck could not show whether the target still holds; label more fresh images.',)
    """
    for action in sorted(actions):
        _check_no_later_failure(records, acceptance_sha256, artifact_sha256, action)
    return _latest_recheck_caveats(records, acceptance_sha256)


def newer_acceptances(state_dir: Path, bound: Path, acceptance: dict[str, Any]) -> tuple[str, ...]:
    """Return a caveat for each other acceptance file in the state folder frozen after the bound one.

    A project can hold several targets, so a later revision is a caveat, not a failure.

    Args:
        state_dir: The project's `.vision-delivery/` folder.
        bound: The acceptance file the chain is bound to.
        acceptance: The bound acceptance record.

    Returns:
        Plain caveat sentences naming each later or unreadable acceptance file.

    Examples:
        >>> newer_acceptances(Path("absent"), Path("a.json"), {"frozen_at": "2026-01-01T00:00:00Z"})
        ()
    """
    if state_dir.is_symlink() or not state_dir.is_dir():
        return ()
    frozen_at = parse_utc(acceptance["frozen_at"], "acceptance frozen_at")
    caveats: list[str] = []
    for path in sorted(state_dir.glob("acceptance-*.json")):
        if path.resolve() == bound.resolve():
            continue
        try:
            other = load_acceptance(path)
        except (OSError, ValueError):
            caveats.append(f"{STATE_DIR}/{path.name} is not a readable frozen acceptance.")
            continue
        if parse_utc(other["frozen_at"], "acceptance frozen_at") > frozen_at:
            caveats.append(
                f"A later acceptance revision exists: {STATE_DIR}/{path.name} ({other['acceptance_id']},"
                f" frozen at {other['frozen_at']}); these checks cover {acceptance['acceptance_id']} only."
            )
    return tuple(caveats)


def chain_identity(inputs: ChainInputs, acceptance_sha256: str, artifact_sha256: str, proof_rows: list[dict]) -> str:
    """Return the stable chain ID over the acceptance, baseline, artifact, handoff, economics, and proof rows.

    Args:
        inputs: The chain file paths.
        acceptance_sha256: SHA-256 of the frozen acceptance file.
        artifact_sha256: The checked artifact tree digest.
        proof_rows: The ledger rows `check_ledger` matched.

    Returns:
        The lowercase SHA-256 chain ID.

    Examples:
        >>> chain_identity(ChainInputs(*(Path("absent"),) * 6), "s" * 64, "t" * 64, [])
        Traceback (most recent call last):
        ...
        ValueError: proof input must be a regular non-symlink file: absent
    """
    components = {
        "acceptance_sha256": acceptance_sha256,
        "baseline_sha256": sha256_file(inputs.baseline),
        "artifact_sha256": artifact_sha256,
        "handoff_sha256": sha256_file(inputs.handoff),
        "economics_sha256": sha256_file(inputs.economics),
        "ledger_proof_sha256": hashlib.sha256(
            json.dumps(
                sorted(proof_rows, key=lambda record: str(record["event_id"])),
                sort_keys=True,
                separators=(",", ":"),
            ).encode()
        ).hexdigest(),
    }
    return hashlib.sha256(json.dumps(components, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


def check_report(
    report: Path, records: list[dict[str, Any]], acceptance_id: str, acceptance_sha256: str, chain_id: str
) -> str:
    """Check that a decision report carries this chain and that the ledger bound its exact bytes.

    Args:
        report: The decision report file.
        records: The ledger rows.
        acceptance_id: The frozen acceptance ID.
        acceptance_sha256: SHA-256 of the frozen acceptance file.
        chain_id: The ID `chain_identity` returned.

    Returns:
        SHA-256 of the report file.

    Raises:
        ValueError: When the report lacks the binding lines or the ledger binds other report bytes.

    Examples:
        >>> check_report(Path("absent-report.md"), [], "a/v1", "s" * 64, "c" * 64)
        Traceback (most recent call last):
        ...
        ValueError: decision report must be a regular non-symlink file
    """
    if report.is_symlink() or not report.is_file():
        raise ValueError("decision report must be a regular non-symlink file")
    text = report.read_text(encoding="utf-8")
    report_digest = sha256_file(report)
    if f"Acceptance: {acceptance_id} / {acceptance_sha256}" not in text or f"Proof chain: {chain_id}" not in text:
        raise ValueError("decision report does not carry the validated proof binding")
    report_records = [
        record
        for record in records
        if record.get("action") == REPORT_ACTION
        and record.get("status") == "success"
        and record.get("acceptance_id") == acceptance_id
    ]
    if not report_records:
        raise ValueError("ledger is missing successful decision_report_emitted")
    for record in report_records:
        _validate_binding(record, "ledger action decision_report_emitted", acceptance_id, acceptance_sha256)
    if not any(record.get("report_sha256") == report_digest for record in report_records):
        raise ValueError("decision_report_emitted does not bind this report digest")
    return report_digest


def proof_actions(report: Path | None) -> set[str]:
    """Return the ledger proof actions a chain needs, with the report action when a report is checked.

    Examples:
        >>> sorted(proof_actions(Path("report.md")) - proof_actions(None))
        ['decision_report_emitted']
    """
    return REQUIRED_LEDGER_ACTIONS | ({REPORT_ACTION} if report is not None else set())


def validate_chain(inputs: ChainInputs) -> dict[str, Any]:
    """Validate all local proof boundaries and return the stable chain identity.

    Args:
        inputs: The chain file paths.

    Returns:
        The acceptance ID and digest, artifact digest, chain ID, caveats, and the report digest when
        a report is given.

    Raises:
        ValueError: On the first check that fails.

    Examples:
        >>> validate_chain(ChainInputs(*(Path("absent"),) * 6))
        Traceback (most recent call last):
        ...
        ValueError: acceptance artifact must be a regular non-symlink file
    """
    acceptance = load_acceptance(inputs.acceptance)
    acceptance_digest = sha256_file(inputs.acceptance)
    acceptance_id = str(acceptance["acceptance_id"])
    state_dir = inputs.project_root / STATE_DIR
    search = ScoredSearch(state_dir, inputs.gold, inputs.pred)
    check_baseline(load_json(inputs.baseline, "baseline result"), acceptance, acceptance_digest, search)
    handoff = validate_handoff(inputs.handoff, inputs.project_root)
    check_handoff_binding(handoff, acceptance_id, acceptance_digest)
    artifact_digest = str(handoff["artifact_sha256"])
    check_economics(load_json(inputs.economics, "economics result"), acceptance_id, acceptance_digest)
    records = load_ledger(inputs.ledger)
    proof_rows = check_ledger(records, acceptance_id, acceptance_digest, artifact_digest)
    caveats = check_later_records(records, acceptance_digest, artifact_digest, proof_actions(inputs.report))
    caveats += newer_acceptances(state_dir, inputs.acceptance, acceptance)
    chain_id = chain_identity(inputs, acceptance_digest, artifact_digest, proof_rows)
    result: dict[str, Any] = {
        "acceptance_id": acceptance_id,
        "acceptance_sha256": acceptance_digest,
        "artifact_sha256": artifact_digest,
        "chain_id": chain_id,
        "caveats": list(caveats),
    }
    if inputs.report is not None:
        result["report_sha256"] = check_report(inputs.report, records, acceptance_id, acceptance_digest, chain_id)
    return result


def parse_args() -> ChainInputs:
    """Parse project proof components, the optional scored files, and the optional terminal report."""
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--project-root", required=True, type=Path)
    parser.add_argument("--acceptance", required=True, type=Path)
    parser.add_argument("--baseline", required=True, type=Path)
    parser.add_argument("--handoff", required=True, type=Path)
    parser.add_argument("--ledger", required=True, type=Path)
    parser.add_argument("--economics", required=True, type=Path)
    parser.add_argument("--report", type=Path)
    parser.add_argument("--gold", type=Path, help=f"default: the {STATE_DIR}/ file with the baseline gold_sha256")
    parser.add_argument("--pred", type=Path, help=f"default: the {STATE_DIR}/ file with the baseline pred_sha256")
    return ChainInputs(**vars(parser.parse_args()))


def main() -> int:
    """Emit a machine-readable local-integrity verdict."""
    try:
        result = validate_chain(parse_args())
    except (OSError, ValueError) as exc:
        print(json.dumps({"status": "failed", "reason": str(exc)}), file=sys.stderr)
        return 1
    print(json.dumps({"status": "passed", "trust": "local-same-user", **result}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
