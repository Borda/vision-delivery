#!/usr/bin/env python3
"""Read .vision-delivery/ledger.jsonl and report delivery metrics or project status.

Usage:
    python3 scripts/ledger_report.py                   # human-readable metrics
    python3 scripts/ledger_report.py --json            # machine-readable metrics
    python3 scripts/ledger_report.py --status          # where the project stands, and the next action
    python3 scripts/ledger_report.py --status --json   # the same status as JSON
    python3 scripts/ledger_report.py --ledger path/to/other.jsonl

The status view is read-only. It reads the ledger, the gate policy, and the eval files that
sit beside the ledger (frozen `acceptance-*.json`, scorer evidence `*.json`, `eval-*.md`,
`economics-*.md`, `delivery-handoff-*.json`). It never writes a file and never calls a provider.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import re
import sys
from collections import Counter
from dataclasses import asdict, dataclass
from datetime import date, datetime, timedelta, timezone
from enum import Enum
from pathlib import Path
from typing import Any

_PRE_DEPLOY_ACTIONS = {
    "baseline_measured",
    "models_train",
}  # models_train: legacy pre-2026-07-09 rows
_GATE_POLICY = Path(__file__).resolve().parents[1] / "hooks" / "gate-policy.json"
_PROGRESS_CATEGORIES = {"evaluation", "inference", "training"}


def _load_policy(policy_path: Path = _GATE_POLICY) -> dict[str, Any]:
    """Return the generated gate policy, or an empty object when it is missing or malformed.

    Examples:
        >>> _load_policy(Path("missing-policy.json"))
        {}
    """
    try:
        policy = json.loads(policy_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    if not isinstance(policy, dict) or not isinstance(policy.get("tools"), dict):
        return {}
    return policy


def _category_operations(tools: dict[str, Any], categories: set[str]) -> frozenset[str]:
    """Return gated operations whose policy category is one of ``categories``.

    Examples:
        >>> sorted(_category_operations({"a": {"class": "brief", "category": "training"}}, {"training"}))
        ['a']
    """
    return frozenset(
        name
        for name, entry in tools.items()
        if isinstance(entry, dict) and entry.get("class") != "open" and entry.get("category") in categories
    )


def _policy_operations(policy_path: Path = _GATE_POLICY) -> tuple[frozenset[str], frozenset[str]]:
    """Return the deployment and build-progress operation names from the gate policy.

    Operation names are never guessed here: both sets come from the policy generated from
    the provider's tool catalog. A missing or unreadable policy yields two empty sets, so
    the report counts no provider call rather than counting a guessed one.

    Args:
        policy_path: Location of the generated gate policy.

    Returns:
        Operations that launch a deployment, and gated operations that train, evaluate,
        or run inference.

    Examples:
        >>> deployment, progress = _policy_operations(Path("missing-policy.json"))
        >>> (len(deployment), len(progress))
        (0, 0)
    """
    policy = _load_policy(policy_path)
    tools = policy.get("tools", {})
    deployment = frozenset(name for name in policy.get("deployment_operations", []) if name in tools)
    return deployment, _category_operations(tools, _PROGRESS_CATEGORIES)


#: Gate-policy tool table read once at import; empty when the policy is missing.
_POLICY_TOOLS: dict[str, Any] = _load_policy().get("tools", {})
_DEPLOYMENT_OPERATIONS, _PROGRESS_OPERATIONS = _policy_operations()


def _is_deployment(record: dict) -> bool:
    """Return whether a record is a verified deployment outcome."""
    return record.get("action") == "roboflow_mcp_call" and record.get("operation") in _DEPLOYMENT_OPERATIONS


def _is_pre_deployment(record: dict) -> bool:
    """Return whether a successful record proves measured/build progress."""
    if record.get("action") in _PRE_DEPLOY_ACTIONS:
        return True
    return record.get("action") == "roboflow_mcp_call" and record.get("operation") in _PROGRESS_OPERATIONS


def _default_ledger() -> Path:
    """Return the ledger in the user's current project, not the plugin cache."""
    declared = os.environ.get("CLAUDE_PROJECT_DIR", "")
    if declared and Path(declared).is_absolute():
        return Path(declared) / ".vision-delivery" / "ledger.jsonl"
    start = Path.cwd()
    for candidate in (start, *start.parents):
        if (candidate / ".vision-delivery").exists() or (candidate / ".git").exists():
            return candidate / ".vision-delivery" / "ledger.jsonl"
    return start / ".vision-delivery" / "ledger.jsonl"


def load_records(ledger: Path) -> list[dict]:
    """Load JSONL records, skipping blank lines and malformed entries."""
    if not ledger.exists():
        return []
    records: list[dict] = []
    for i, raw in enumerate(ledger.read_text(encoding="utf-8").splitlines(), 1):
        line = raw.strip()
        if not line:
            continue
        try:
            records.append(json.loads(line))
        except json.JSONDecodeError as exc:
            print(f"# warn: line {i} invalid JSON — {exc}", file=sys.stderr)
    return records


def _comparable_record(record: dict) -> dict:
    """Return a record identity without its generated timestamp."""
    return {key: value for key, value in record.items() if key != "ts"}


def deduplicate_records(records: list[dict]) -> tuple[list[dict], int, int]:
    """Deduplicate records that carry a stable host tool-use identifier.

    Records without an ``event_id`` are retained because there is no reliable
    evidence that two otherwise-identical manual records describe one event.

    Args:
        records: Ledger records in append order.

    Returns:
        Deduplicated records, duplicate rows ignored, and integrity conflicts.
    """
    positions: dict[str, int] = {}
    deduplicated: list[dict] = []
    duplicates = 0
    integrity_conflicts = 0
    for record in records:
        event_id = record.get("event_id")
        if not isinstance(event_id, str) or not event_id:
            deduplicated.append(record)
            continue
        if event_id in positions:
            duplicates += 1
            position = positions[event_id]
            if _comparable_record(deduplicated[position]) != _comparable_record(record):
                integrity_conflicts += 1
                conflicted = dict(deduplicated[position])
                conflicted["status"] = "unknown"
                conflicted["integrity_conflict"] = True
                deduplicated[position] = conflicted
            continue
        positions[event_id] = len(deduplicated)
        deduplicated.append(record)
    return deduplicated, duplicates, integrity_conflicts


def compute_metrics(records: list[dict]) -> dict:
    """Derive all report metrics from a list of ledger records."""
    raw_records = len(records)
    records, duplicates_ignored, integrity_conflicts = deduplicate_records(records)
    total_events = len(records)
    successful_records = [r for r in records if r.get("status") == "success"]
    sessions = len({r.get("session", "unknown") for r in records})

    deployed = {r.get("session", "unknown") for r in successful_records if _is_deployment(r)}
    progressed = {r.get("session", "unknown") for r in successful_records if _is_pre_deployment(r)}
    deploy_sessions = len(deployed)
    deploy_pct = round(deploy_sessions / sessions * 100, 1) if sessions else 0.0

    solved_no_deploy = len(progressed - deployed)

    workload_mix = dict(Counter(r.get("skill", "unknown") for r in successful_records).most_common())
    action_breakdown = dict(
        Counter(r.get("operation") or r.get("action", "unknown") for r in successful_records).most_common()
    )
    outcome_breakdown = dict(Counter(r.get("status", "legacy-unknown") for r in records).most_common())

    return {
        "raw_records": raw_records,
        "total_events": total_events,
        "duplicates_ignored": duplicates_ignored,
        "integrity_conflicts": integrity_conflicts,
        "verified_success_events": len(successful_records),
        "sessions": sessions,
        "sessions_reaching_deploy": deploy_sessions,
        "sessions_reaching_deploy_pct": deploy_pct,
        "solved_no_deploy": solved_no_deploy,
        "workload_mix": workload_mix,
        "action_breakdown": action_breakdown,
        "outcome_breakdown": outcome_breakdown,
        "coverage_note": (
            "verified-success metrics only; legacy rows without status are retained as unknown, "
            "conflicting event IDs retain their first record, and host hook coverage still depends on hook trust"
        ),
    }


def print_text(m: dict) -> None:
    """Render metrics as human-readable text."""
    deploy_pct = int(m["sessions_reaching_deploy_pct"])
    print("vision-delivery ledger report")
    print("(verified successes only; legacy status-less rows remain unknown)")
    print("─" * 33)
    print(f"Ledger rows:              {m['raw_records']}")
    print(f"Unique events:            {m['total_events']}")
    print(f"Verified successes:       {m['verified_success_events']}")
    print(f"Duplicates ignored:       {m['duplicates_ignored']}")
    print(f"Integrity conflicts:      {m['integrity_conflicts']}")
    print(f"Sessions:                 {m['sessions']}")
    print(f"Sessions reaching deploy: {m['sessions_reaching_deploy']} ({deploy_pct}%)")
    print(f"Solved-no-deploy:         {m['solved_no_deploy']}")

    print("\nWorkload mix (by skill):")
    if m["workload_mix"]:
        for skill, count in m["workload_mix"].items():
            print(f"  {skill:<26} {count}")
    else:
        print("  (none)")

    print("\nOutcome breakdown:")
    if m["outcome_breakdown"]:
        for status, count in m["outcome_breakdown"].items():
            print(f"  {status:<26} {count}")
    else:
        print("  (none)")

    print("\nAction breakdown:")
    if m["action_breakdown"]:
        for action, count in m["action_breakdown"].items():
            print(f"  {action:<26} {count}")
    else:
        print("  (none)")


# --- Project status -------------------------------------------------------------------------
# The brief rules below mirror `briefState` in hooks/gate.js, so status says "open" exactly
# when the Claude Code gate would let the next call of that operation reach the prompt.

BRIEF_ACTION = "action_brief_emitted"
CALL_ACTION = "roboflow_mcp_call"
RESERVE_ACTION = "roboflow_mcp_call_reserved"
BRIEF_MAX_AGE = timedelta(hours=24)
#: A cost estimate dated further back than this is not a current price.
COST_MAX_AGE = timedelta(days=90)
#: A brief dated further ahead than this is ignored, so a wrong clock cannot extend its life.
CLOCK_SKEW = timedelta(minutes=5)
MAX_CALL_BUDGET = 1000
#: Call outcomes the host reported as not completed; they leave the brief open.
NOT_EXECUTED = frozenset({"failed", "cancelled"})
BRIEF_TEXT_FIELDS = ("scope", "cost_unit", "cost_source", "cost_as_of", "data_movement", "rollback")
ISO_DATE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
#: Largest eval file the status reader opens; larger files are skipped, never parsed.
MAX_EVAL_FILE_BYTES = 1_000_000
PROOF_ACTIONS = frozenset({"artifact_verified", "delivery_handoff_emitted"})
_EVAL_FIELD = re.compile(
    r"^[\s>*_|-]*`?(acceptance_id|metric|comparator|threshold|unit|frozen_at)`?[\s*_]*[:=|]\s*(.+?)[\s|]*$",
    re.IGNORECASE,
)
_RUNG = re.compile(r"rung[-_]?(\d+)", re.IGNORECASE)
_COMPARATOR_SYMBOL = {"gte": ">=", "lte": "<="}
#: The only predictor a prediction freeze can record as independent of the labels.
ISOLATED_PREDICTOR = "isolated-subagent"
#: Why a brief is ``unknown``: its own time, or another brief time of the same operation, is unreadable.
_UNREADABLE_TIME = "timestamp the status reader cannot read"
_OTHER_UNREADABLE = "another brief of this operation has a timestamp the status reader cannot read"
#: Characters JavaScript's ``String.prototype.trim`` removes. Python's ``str.strip`` removes a
#: different set (it keeps U+FEFF and drops U+001C to U+001F and U+0085), so a brief field the
#: gate reads as blank must be judged with this set.
_JS_WHITESPACE = "\t\n\v\f\r \xa0                　﻿"
#: Integer literals longer than this are read as floats, as JavaScript reads every JSON number.
_JS_INT_DIGITS = 300
#: The timestamp forms Node's ``Date.parse`` reads in the gate: the ECMAScript date-time format,
#: plus a space for ``T``, a lower-case ``z``, a ``+HHMM`` offset, and ``24:00`` as the end of a day.
#: A date-time without an offset is local time; a date alone is UTC.
_GATE_TIME = re.compile(
    r"(?P<year>[+-]\d{6}|\d{4})(?:-(?P<month>\d{2})(?:-(?P<day>\d{2})"
    r"(?:[T ](?P<hour>\d{2}):(?P<minute>\d{2})(?::(?P<second>\d{2})(?:\.(?P<fraction>\d+))?)?"
    r"(?P<zone>[Zz]|[+-]\d{2}:?\d{2})?)?)?)?"
)


class OperationClass(str, Enum):
    """How the gate policy treats a provider operation."""

    OPEN = "open"
    BRIEF = "brief"
    BUDGET = "budget"


class BriefState(str, Enum):
    """Where one recorded action brief stands right now."""

    OPEN = "open"
    USED = "used"
    REPLACED = "replaced"
    EXPIRED = "expired"
    INVALID = "invalid"
    UNKNOWN = "unknown"


class Verdict(str, Enum):
    """Scorer verdict of a measured result; ``unknown`` when only a ledger row records it."""

    PASS = "pass"
    BELOW_TARGET = "below-target"
    INCONCLUSIVE = "inconclusive"
    NO_VERDICT = "no-verdict"
    UNKNOWN = "unknown"

    @property
    def label(self) -> str:
        """Return the verdict as the scorer prints it.

        Examples:
            >>> Verdict.NO_VERDICT.label, Verdict.BELOW_TARGET.label
            ('NO VERDICT', 'BELOW-TARGET')
        """
        return "NO VERDICT" if self == Verdict.NO_VERDICT else self.value.upper()


class Milestone(str, Enum):
    """A point of the delivery loop that the ledger or eval files prove was reached."""

    TARGET_LOCKED = "target-locked"
    MEASURED = "measured"
    MEASURED_HIGHER_RUNG = "measured-higher-rung"
    PASSED = "passed"
    TRAINED = "trained"
    PROOF = "proof"
    ECONOMICS = "economics"
    DECISION_REPORT = "decision-report"


class DeliveryStep(str, Enum):
    """The step of the delivery loop the project is in now."""

    SCOPE = "scope"
    BASELINE = "baseline"
    IMPROVE = "improve"
    PROOF = "proof"
    ECONOMICS = "economics"
    DECISION = "decision"
    DONE = "done"

    @property
    def number(self) -> int:
        """Return the 1-based position of this step in the loop.

        Examples:
            >>> DeliveryStep.SCOPE.number, DeliveryStep.DONE.number
            (1, 7)
        """
        return list(DeliveryStep).index(self) + 1


STEP_TITLES = {
    DeliveryStep.SCOPE: "lock the success target",
    DeliveryStep.BASELINE: "measure the cheapest baseline",
    DeliveryStep.IMPROVE: "diagnose the result, improve, and re-measure",
    DeliveryStep.PROOF: "produce inspectable proof",
    DeliveryStep.ECONOMICS: "estimate economics",
    DeliveryStep.DECISION: "record the human decision",
    DeliveryStep.DONE: "decision recorded",
}
STEP_ACTIONS = {
    DeliveryStep.SCOPE: (
        "Lock the success target before any result: answer the target questions and record them in "
        ".vision-delivery/eval-<session>.md (solve-cv-task starts this)."
    ),
    DeliveryStep.BASELINE: (
        "Measure the cheapest baseline first: score rung 0 against the locked target with score_baseline.py."
    ),
    DeliveryStep.PROOF: (
        "The target passed on this sample: decide whether to go to deliver mode, which needs a verified "
        "runnable artifact (deliver-cv-project) before any delivery claim."
    ),
    DeliveryStep.ECONOMICS: "Estimate one-time and run-rate economics for the passing result (estimate-economics).",
    DeliveryStep.DECISION: "Write the decision report for the human owner (decision-report).",
    DeliveryStep.DONE: (
        "Hand the decision report to its owner; if Sentinel helped or got in the way, draft an outcome "
        "report (report-outcome)."
    ),
}
VERDICT_ACTIONS = {
    Verdict.BELOW_TARGET: (
        "The whole interval misses the target: investigate the misses, then try the cheapest justified "
        "improvement (the next baseline rung or a targeted fix) and re-score on the same gold set."
    ),
    Verdict.INCONCLUSIVE: (
        "The interval includes the target: label more gold images and re-score the same rung; do not "
        "climb a rung or report a pass yet."
    ),
    Verdict.NO_VERDICT: (
        "The scorer refused a verdict: supply the missing predictions or more gold cases and re-score "
        "the same rung; this result is not a pass."
    ),
}
RESCORE_ACTION = (
    "The last result was scored against a different target than the one locked now: re-score the same "
    "predictions against the locked target."
)
CANNOT_COMPARE_ACTION = (
    "The last result cannot be compared with the locked target, so it is not a pass of it: write the locked "
    "target as metric, comparator, and threshold lines in .vision-delivery/eval-<session>.md (or freeze an "
    "acceptance file), then re-score the same predictions against it."
)
UNRECORDED_VERDICT_ACTION = (
    "A baseline_measured row exists but no scorer evidence file: re-run score_baseline.py with "
    "--evidence-out so the verdict is on file."
)


@dataclass(frozen=True)
class BriefStatus:
    """One successful action-brief row and the gate's view of it now."""

    event_id: str
    operation: str
    operation_class: OperationClass
    state: BriefState
    recorded_at: str
    expires_at: str
    limit: int | None
    used: int
    interrupted: int
    scope: str
    cost: str
    problems: tuple[str, ...] = ()

    @property
    def remaining(self) -> int | None:
        """Return the calls this brief still covers, or ``None`` when it covers none.

        Examples:
            >>> brief = BriefStatus("b", "op", OperationClass.BUDGET, BriefState.OPEN, "", "", 5, 2, 0, "", "")
            >>> brief.remaining
            3
        """
        if self.state != BriefState.OPEN or self.limit is None:
            return None
        return max(self.limit - self.used, 0)


@dataclass(frozen=True)
class TargetInfo:
    """A success target: frozen acceptance file, eval notes, or the target a scorer run used."""

    source: str
    metric: str = ""
    comparator: str = ""
    threshold: float | None = None
    unit: str = ""
    acceptance_id: str = ""
    frozen_at: str = ""
    acceptance_sha256: str = ""

    def rule(self) -> str:
        """Return the pass rule in plain symbols, or an empty string when it is not machine-readable.

        Examples:
            >>> TargetInfo("x", "catch_rate", "gte", 0.8).rule()
            'catch_rate >= 0.8'
            >>> TargetInfo("eval-x.md").rule()
            ''
        """
        if not self.metric or self.comparator not in _COMPARATOR_SYMBOL or self.threshold is None:
            return ""
        return f"{self.metric} {_COMPARATOR_SYMBOL[self.comparator]} {self.threshold:g}"

    def same_rule(self, other: TargetInfo) -> bool | None:
        """Return whether two targets share metric, direction, and threshold; ``None`` when unknown.

        Examples:
            >>> TargetInfo("a", "catch_rate", "gte", 0.8).same_rule(TargetInfo("b", "catch_rate", "gte", 0.8))
            True
            >>> TargetInfo("a").same_rule(TargetInfo("b", "catch_rate", "gte", 0.8)) is None
            True
        """
        if not self.rule() or not other.rule():
            return None
        assert self.threshold is not None and other.threshold is not None
        return (
            self.metric == other.metric
            and self.comparator == other.comparator
            and math.isclose(self.threshold, other.threshold, rel_tol=0.0, abs_tol=1e-9)
        )

    def same_target(self, other: TargetInfo) -> bool | None:
        """Return whether a result's target is this target: the same acceptance and the same rule.

        When both targets carry an acceptance ID, or both an acceptance digest, a difference in
        either makes them different targets whatever their rule. Otherwise the answer is
        ``same_rule``, which is ``None`` when either rule is not machine-readable.

        Args:
            other: The target a scorer run used.

        Returns:
            ``True`` for the same target, ``False`` for a different one, ``None`` when it cannot be told.

        Examples:
            >>> locked = TargetInfo("a", "catch_rate", "gte", 0.8, acceptance_id="x/v2")
            >>> locked.same_target(TargetInfo("b", "catch_rate", "gte", 0.8, acceptance_id="x/v1"))
            False
            >>> locked.same_target(TargetInfo("b", "catch_rate", "gte", 0.8))
            True
            >>> TargetInfo("eval-s.md").same_target(TargetInfo("b", "accuracy", "gte", 0.5)) is None
            True
        """
        pairs = ((self.acceptance_id, other.acceptance_id), (self.acceptance_sha256, other.acceptance_sha256))
        if any(mine and theirs and mine != theirs for mine, theirs in pairs):
            return False
        return self.same_rule(other)


@dataclass(frozen=True)
class FreezeRecord:
    """What scorer evidence records about the prediction freeze it checked before scoring."""

    predictor: str
    independent: bool | None

    def describe(self) -> str:
        """Return the freeze in plain words for the status text.

        Examples:
            >>> FreezeRecord("same-session", False).describe()
            'predictions frozen, predictor same-session, not independent'
            >>> FreezeRecord("isolated-subagent", True).describe()
            'predictions frozen, predictor isolated-subagent'
            >>> FreezeRecord("isolated-subagent", None).describe()
            'predictions frozen, predictor isolated-subagent, label-change checks not on file'
        """
        text = f"predictions frozen, predictor {self.predictor or 'not recorded'}"
        if self.independent is None:
            return f"{text}, label-change checks not on file"
        return text if self.independent else f"{text}, not independent"


def _freeze_from(block: object) -> FreezeRecord | None:
    """Read scorer evidence's ``predictions_frozen`` block; ``None`` when the predictions were not frozen.

    Older evidence names the predictor ``predictor`` and records no label-change checks, so its
    independence stays unknown. A predictor other than an isolated subagent, or a recorded label
    change, makes the result not independent whatever the block's own ``independent`` says.

    Examples:
        >>> _freeze_from(None) is None
        True
        >>> _freeze_from({"predictor": "isolated-subagent", "independence_enforced_by_isolation": True})
        FreezeRecord(predictor='isolated-subagent', independent=None)
        >>> _freeze_from({"predictor_declared": "isolated-subagent", "labels_changed_after_freeze": 2,
        ...               "labels_changed_after_predictions": False, "independent": True}).independent
        False
    """
    if not isinstance(block, dict):
        return None
    declared = block.get("predictor_declared", block.get("predictor"))
    predictor = declared if isinstance(declared, str) else ""
    changed = _whole(block.get("labels_changed_after_freeze")) not in (None, 0)
    if predictor != ISOLATED_PREDICTOR or changed or block.get("labels_changed_after_predictions") is True:
        return FreezeRecord(predictor, False)
    claimed = block.get("independent")
    return FreezeRecord(predictor, claimed if isinstance(claimed, bool) else None)


@dataclass(frozen=True)
class Measurement:
    """The last measured result: scorer evidence, or a ledger row when no evidence file exists."""

    source: str
    measured_at: str
    verdict: Verdict
    metric: str = ""
    observed_value: float | None = None
    numerator: int | None = None
    denominator: int | None = None
    interval_lower: float | None = None
    interval_upper: float | None = None
    rung: int | None = None
    target: TargetInfo | None = None
    notes: str = ""
    freeze: FreezeRecord | None = None


@dataclass(frozen=True)
class EvalFiles:
    """Eval files found beside the ledger, each list oldest first."""

    acceptances: tuple[TargetInfo, ...] = ()
    evidence: tuple[Measurement, ...] = ()
    eval_targets: tuple[TargetInfo, ...] = ()
    economics: tuple[str, ...] = ()
    handoffs: tuple[str, ...] = ()


@dataclass(frozen=True)
class ProjectStatus:
    """Where a project stands: step, target, last result, action briefs, and the next action."""

    ledger: str
    ledger_rows: int
    session: str
    session_source: str
    step: DeliveryStep
    milestones: frozenset[Milestone]
    target: TargetInfo | None
    measurement: Measurement | None
    target_matches: bool | None
    briefs: tuple[BriefStatus, ...]
    next_action: str
    warnings: tuple[str, ...]

    def open_briefs(self) -> tuple[BriefStatus, ...]:
        """Return the briefs the next call of their operation can still use.

        Examples:
            >>> empty = ProjectStatus("l", 0, "", "", DeliveryStep.SCOPE, frozenset(), None, None, None, (), "", ())
            >>> empty.open_briefs()
            ()
        """
        return tuple(brief for brief in self.briefs if brief.state == BriefState.OPEN)

    def to_json(self) -> dict[str, Any]:
        """Return the status as plain JSON-ready data.

        Examples:
            >>> empty = ProjectStatus("l", 0, "", "", DeliveryStep.SCOPE, frozenset(), None, None, None, (), "", ())
            >>> empty.to_json()["step_number"]
            1
        """
        payload = json.loads(json.dumps(asdict(self), default=_json_default))
        payload["step_number"] = self.step.number
        payload["step_title"] = STEP_TITLES[self.step]
        for brief, raw in zip(self.briefs, payload["briefs"], strict=True):
            raw["remaining"] = brief.remaining
        return payload


def _json_default(value: object) -> object:
    """Serialize sets as sorted lists for JSON output."""
    if isinstance(value, (set, frozenset)):
        return sorted(str(item.value if isinstance(item, Enum) else item) for item in value)
    raise TypeError(f"not JSON serializable: {type(value).__name__}")


def parse_time(value: object) -> datetime | None:
    """Parse an ISO 8601 timestamp, treating a missing zone as UTC; ``None`` when unreadable.

    Examples:
        >>> parse_time("2026-11-10T10:00:00Z").isoformat()
        '2026-11-10T10:00:00+00:00'
        >>> parse_time("yesterday") is None
        True
    """
    if not isinstance(value, str) or not value.strip():
        return None
    text = value.strip()
    if text[-1] in "Zz":
        text = text[:-1] + "+00:00"
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError:
        return None
    return parsed if parsed.tzinfo is not None else parsed.replace(tzinfo=timezone.utc)


def _iso(moment: datetime | None) -> str:
    """Render a UTC moment as ``YYYY-MM-DDTHH:MM:SSZ``, or an empty string."""
    if moment is None:
        return ""
    return moment.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _gate_moment(match: re.Match[str]) -> datetime:
    """Build the moment a matched gate timestamp names; raise ``ValueError`` for an impossible one."""
    year, month, day = int(match["year"]), int(match["month"] or 1), int(match["day"] or 1)
    if match["hour"] is None:
        return datetime(year, month, day, tzinfo=timezone.utc)
    hour, minute, second = int(match["hour"]), int(match["minute"]), int(match["second"] or 0)
    millisecond = int((match["fraction"] or "0")[:3].ljust(3, "0"))
    end_of_day = hour == 24
    if end_of_day and (minute or second or millisecond):
        raise ValueError("24:00 only names the end of a day")
    moment = datetime(year, month, day, 0 if end_of_day else hour, minute, second, millisecond * 1000)
    moment += timedelta(days=1 if end_of_day else 0)
    zone = match["zone"]
    if zone is None:
        return moment.astimezone()
    if zone in ("Z", "z"):
        return moment.replace(tzinfo=timezone.utc)
    digits = zone[1:].replace(":", "")
    if int(digits[:2]) > 23 or int(digits[2:]) > 59:
        raise ValueError("offset out of range")
    offset = timedelta(hours=int(digits[:2]), minutes=int(digits[2:]))
    return moment.replace(tzinfo=timezone(-offset if zone[0] == "-" else offset))


def gate_time(value: object) -> datetime | None:
    """Read a ledger timestamp the way the gate's ``Date.parse`` reads it; ``None`` when the gate cannot.

    Python's ``datetime.fromisoformat`` accepts forms ``Date.parse`` rejects (basic format such as
    ``20261110T100000Z``, week dates, an hour-only time, a ``+00`` offset), and it reads a time
    without an offset as UTC where ``Date.parse`` reads local time. A brief dated in such a form
    must not look open when the gate ignores it, so only the forms Node reads are accepted here.
    Node also reads some forms this function refuses, through its legacy parser (RFC 2822 dates)
    or past the years ``datetime`` holds, so a refused time does not mean the gate ignores the
    brief: ``brief_states`` reports every brief of that operation as ``unknown`` instead.

    Args:
        value: The row's ``ts`` value.

    Returns:
        The moment, timezone-aware, or ``None`` when the gate would read no time.

    Examples:
        >>> gate_time("2026-11-10T10:00:00Z").isoformat()
        '2026-11-10T10:00:00+00:00'
        >>> gate_time("2026-11-10T10:00:00+0130").isoformat()
        '2026-11-10T10:00:00+01:30'
        >>> gate_time("20261110T100000Z") is None, gate_time("2026-11-10T10Z") is None
        (True, True)
    """
    if not isinstance(value, str):
        return None
    match = _GATE_TIME.fullmatch(value)
    if match is None:
        return None
    try:
        return _gate_moment(match)
    except (ValueError, OverflowError, OSError):
        return None


def _js_int(text: str) -> int | float:
    """Read a JSON integer literal; a huge one becomes a float, ``inf`` past the float range, as in JavaScript."""
    return int(text) if len(text) <= _JS_INT_DIGITS else float(text)


def _reject_constant(name: str) -> object:
    """Refuse ``NaN`` and ``Infinity``: Python's JSON reader accepts them and ``JSON.parse`` does not."""
    raise ValueError(f"{name} is not JSON")


def read_gate_records(ledger: Path) -> tuple[list[dict[str, Any]], int]:
    """Read ledger rows exactly as the gate's ``readRecords`` reads them.

    The file is decoded as UTF-8 with replacement characters, split on ``\\n`` only (a row may
    hold U+2028 or U+0085, which ``str.splitlines`` would split on), and each non-blank row is
    parsed as strict JSON. A row ``JSON.parse`` refuses, such as one holding ``NaN``, is skipped,
    as the gate skips it; so is a row that is not a JSON object.

    Args:
        ledger: The ledger file.

    Returns:
        The object rows in file order, and the number of non-blank rows skipped.

    Raises:
        OSError: When the ledger exists but cannot be read; the gate then refuses every gated call.

    Examples:
        >>> read_gate_records(Path("no-such-ledger.jsonl"))
        ([], 0)
    """
    try:
        text = ledger.read_bytes().decode("utf-8", errors="replace")
    except FileNotFoundError:
        return [], 0
    records: list[dict[str, Any]] = []
    skipped = 0
    for row in text.split("\n"):
        if not row.strip(_JS_WHITESPACE):
            continue
        try:
            record = json.loads(row, parse_int=_js_int, parse_constant=_reject_constant)
        except (ValueError, RecursionError):
            record = None
        if isinstance(record, dict):
            records.append(record)
        else:
            skipped += 1
    return records, skipped


def operation_class(operation: str, tools: dict[str, Any]) -> OperationClass:
    """Return the gate class of an operation, as the gate reads it.

    An unlisted operation is gated with a per-execution brief. A tool is ``open`` only when the
    policy also records the provider's read-only flag.

    Examples:
        >>> operation_class("anything", {}).value
        'brief'
        >>> operation_class("t", {"t": {"class": "open", "read_only": False}}).value
        'brief'
        >>> operation_class("t", {"t": {"class": "budget"}}).value
        'budget'
    """
    entry = tools.get(operation)
    if not isinstance(entry, dict) or entry.get("class") not in {member.value for member in OperationClass}:
        return OperationClass.BRIEF
    found = OperationClass(entry["class"])
    if found == OperationClass.OPEN and entry.get("read_only") is not True:
        return OperationClass.BRIEF
    return found


def _valid_cost_date(value: object, now: datetime) -> bool:
    """Return whether a brief's price date is a real day, not in the future, and at most 90 days old."""
    if not isinstance(value, str) or not ISO_DATE.match(value):
        return False
    try:
        day = date.fromisoformat(value)
    except ValueError:
        return False
    moment = datetime(day.year, day.month, day.day, tzinfo=timezone.utc)
    return now - COST_MAX_AGE <= moment <= now + BRIEF_MAX_AGE


def _call_budget(value: object) -> int | None:
    """Return a whole call budget from 1 to 1000, or ``None`` when the value is not one."""
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    if isinstance(value, float) and not value.is_integer():
        return None
    budget = int(value)
    return budget if 1 <= budget <= MAX_CALL_BUDGET else None


def brief_problems(record: dict[str, Any], op_class: OperationClass, now: datetime) -> tuple[str, ...]:
    """Name the structured brief fields the gate would reject, in the gate's order.

    Examples:
        >>> brief_problems({}, OperationClass.BRIEF, datetime.now(timezone.utc))
        ('structured brief fields',)
    """
    brief = record.get("brief")
    if not isinstance(brief, dict):
        return ("structured brief fields",)
    problems = [
        name
        for name in BRIEF_TEXT_FIELDS
        if not isinstance(brief.get(name), str) or not brief[name].strip(_JS_WHITESPACE)
    ]
    amount = _number(brief.get("cost_amount"))
    if amount is None or amount < 0:
        problems.append("cost_amount")
    if "cost_as_of" not in problems and not _valid_cost_date(brief.get("cost_as_of"), now):
        problems.append("cost_as_of")
    if op_class == OperationClass.BUDGET and _call_budget(brief.get("call_budget")) is None:
        problems.append("call_budget")
    return tuple(problems)


def _brief_rejection(
    record: dict[str, Any], op_class: OperationClass, now: datetime
) -> tuple[BriefState, tuple[str, ...]] | None:
    """Return why the gate ignores a brief row now, or ``None`` when the row can be the open brief."""
    if op_class == OperationClass.OPEN:
        return BriefState.INVALID, ("the gate policy marks this operation read-only, so no brief is read",)
    recorded = gate_time(record.get("ts"))
    if recorded is None:
        return BriefState.UNKNOWN, (_UNREADABLE_TIME,)
    if now - recorded > BRIEF_MAX_AGE:
        return BriefState.EXPIRED, ("recorded more than 24 hours ago",)
    if recorded - now > CLOCK_SKEW:
        return BriefState.INVALID, ("dated in the future",)
    problems = brief_problems(record, op_class, now)
    return (BriefState.INVALID, problems) if problems else None


@dataclass
class _Candidate:
    """The brief the gate would use for an operation, and the calls counted against it so far."""

    record: dict[str, Any]
    limit: int
    executed: int = 0
    reserved: int = 0
    interrupted: int = 0

    @property
    def used(self) -> int:
        """Return the units used: recorded calls that may have run, or reserved units, whichever is more."""
        return max(self.executed, self.reserved)

    def count(self, record: dict[str, Any]) -> None:
        """Count one later call or reservation row against this brief, as the gate does."""
        if record.get("action") == RESERVE_ACTION:
            self.reserved += 1
        elif record.get("status") in NOT_EXECUTED:
            self.interrupted += 1
        else:
            self.executed += 1


def _brief_status(
    record: dict[str, Any],
    op_class: OperationClass,
    state: BriefState,
    candidate: _Candidate | None = None,
    problems: tuple[str, ...] = (),
) -> BriefStatus:
    """Build the reported view of one brief row."""
    raw_brief = record.get("brief")
    brief: dict[str, Any] = raw_brief if isinstance(raw_brief, dict) else {}
    recorded = gate_time(record.get("ts"))
    amount, unit = _number(brief.get("cost_amount")), brief.get("cost_unit")
    cost = f"{amount:g} {unit}" if amount is not None and isinstance(unit, str) else ""
    return BriefStatus(
        event_id=str(record.get("event_id") or ""),
        operation=str(record.get("operation") or ""),
        operation_class=op_class,
        state=state,
        recorded_at=_iso(recorded),
        expires_at=_iso(recorded + BRIEF_MAX_AGE) if recorded is not None else "",
        limit=candidate.limit if candidate is not None else None,
        used=candidate.used if candidate is not None else 0,
        interrupted=candidate.interrupted if candidate is not None else 0,
        scope=str(brief.get("scope") or ""),
        cost=cost,
        problems=problems,
    )


def _operation_briefs(
    records: list[dict[str, Any]], operation: str, op_class: OperationClass, now: datetime
) -> dict[int, BriefStatus]:
    """Walk the ledger like the gate for one operation and label every brief row it holds."""
    found: dict[int, BriefStatus] = {}
    candidate: _Candidate | None = None
    candidate_index = -1
    for index, record in enumerate(records):
        if record.get("operation") != operation:
            continue
        action = record.get("action")
        if action == BRIEF_ACTION and record.get("status") == "success":
            rejection = _brief_rejection(record, op_class, now)
            if rejection is not None:
                found[index] = _brief_status(record, op_class, rejection[0], problems=rejection[1])
                continue
            if candidate is not None:
                found[candidate_index] = _brief_status(candidate.record, op_class, BriefState.REPLACED, candidate)
            limit = _call_budget(record["brief"].get("call_budget")) if op_class == OperationClass.BUDGET else 1
            candidate, candidate_index = _Candidate(record, limit or 1), index
        elif candidate is not None and action in (CALL_ACTION, RESERVE_ACTION):
            candidate.count(record)
            if candidate.used >= candidate.limit:
                found[candidate_index] = _brief_status(candidate.record, op_class, BriefState.USED, candidate)
                candidate = None
    if candidate is not None:
        found[candidate_index] = _brief_status(candidate.record, op_class, BriefState.OPEN, candidate)
    return found


def _unknown_briefs(records: list[dict[str, Any]], operation: str, op_class: OperationClass) -> dict[int, BriefStatus]:
    """Mark every brief of an operation ``unknown`` when one of its brief times cannot be read; else nothing.

    Only successful brief rows count: the gate reads no other row's time. An operation the policy
    marks read-only reads no brief, so its times do not matter.
    """
    if op_class == OperationClass.OPEN:
        return {}
    indexes = [
        index
        for index, record in enumerate(records)
        if record.get("operation") == operation
        and record.get("action") == BRIEF_ACTION
        and record.get("status") == "success"
    ]
    unreadable = {index for index in indexes if gate_time(records[index].get("ts")) is None}
    if not unreadable:
        return {}
    return {
        index: _brief_status(
            records[index],
            op_class,
            BriefState.UNKNOWN,
            problems=(_UNREADABLE_TIME if index in unreadable else _OTHER_UNREADABLE,),
        )
        for index in indexes
    }


def brief_states(records: list[dict[str, Any]], tools: dict[str, Any], now: datetime) -> tuple[BriefStatus, ...]:
    """Label every successful action-brief row the way the gate sees it at ``now``, in ledger order.

    A brief is ``open`` while the gate would accept it: fresh (under 24 hours), complete, and with
    calls left. Each later call or reservation row of its operation uses it; a failed or
    cancelled call leaves it open. A later valid brief for the same operation ``replaced`` it.
    When one brief row of an operation has a time this reader cannot read, every brief of that
    operation is ``unknown``: the gate may still read that time (``gate_time``), so which brief it
    uses, and whether any is open, cannot be told here.

    Args:
        records: Ledger rows in append order.
        tools: The gate policy's tool table.
        now: The moment to judge freshness at.

    Returns:
        One status per successful brief row.

    Examples:
        >>> now = datetime(2026, 11, 10, 12, tzinfo=timezone.utc)
        >>> brief = {"scope": "s", "cost_amount": 1, "cost_unit": "credits", "cost_source": "src",
        ...          "cost_as_of": "2026-11-10", "data_movement": "none", "rollback": "none"}
        >>> rows = [{"ts": "2026-11-10T11:00:00Z", "action": BRIEF_ACTION, "status": "success",
        ...          "operation": "op", "event_id": "b1", "brief": brief}]
        >>> [item.state.value for item in brief_states(rows, {}, now)]
        ['open']
        >>> rows.append({"action": CALL_ACTION, "operation": "op", "status": "success"})
        >>> [item.state.value for item in brief_states(rows, {}, now)]
        ['used']
        >>> rows.append({**rows[0], "event_id": "b2", "ts": "Tue, 10 Nov 2026 11:30:00 GMT"})
        >>> [item.state.value for item in brief_states(rows, {}, now)]
        ['unknown', 'unknown']
    """
    found: dict[int, BriefStatus] = {}
    operations: list[str] = []
    for index, record in enumerate(records):
        if record.get("action") != BRIEF_ACTION or record.get("status") != "success":
            continue
        operation = record.get("operation")
        if not isinstance(operation, str) or not operation:
            found[index] = _brief_status(
                record, OperationClass.BRIEF, BriefState.INVALID, problems=("names no operation",)
            )
        elif operation not in operations:
            operations.append(operation)
    for operation in operations:
        op_class = operation_class(operation, tools)
        found.update(
            _unknown_briefs(records, operation, op_class) or _operation_briefs(records, operation, op_class, now)
        )
    return tuple(found[index] for index in sorted(found))


def _read_json_object(path: Path) -> tuple[dict[str, Any], str] | None:
    """Read one small regular JSON object file and the SHA-256 of its bytes; ``None`` for anything else."""
    try:
        if path.is_symlink() or not path.is_file() or path.stat().st_size > MAX_EVAL_FILE_BYTES:
            return None
        raw = path.read_bytes()
        payload = json.loads(raw.decode("utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError):
        return None
    return (payload, hashlib.sha256(raw).hexdigest()) if isinstance(payload, dict) else None


def _number(value: object) -> float | None:
    """Return a finite JSON number as a float, or ``None``; an integer past the float range is not finite.

    Examples:
        >>> _number(10), _number(True), _number(10**400)
        (10.0, None, None)
    """
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    try:
        number = float(value)
    except OverflowError:
        return None
    return number if math.isfinite(number) else None


def _whole(value: object) -> int | None:
    """Return a JSON whole number, or ``None``."""
    return value if isinstance(value, int) and not isinstance(value, bool) else None


def _target_from(source: str, data: dict[str, Any], digest: str = "") -> TargetInfo:
    """Read the target fields of an acceptance file or a scorer evidence ``target`` object.

    ``digest`` is the SHA-256 of an acceptance file's own bytes; scorer evidence records the
    digest of the acceptance file it was scored against as ``acceptance_sha256``.
    """
    return TargetInfo(
        source=source,
        metric=str(data.get("metric") or ""),
        comparator=str(data.get("comparator") or ""),
        threshold=_number(data.get("threshold")),
        unit=str(data.get("unit") or ""),
        acceptance_id=str(data.get("acceptance_id") or ""),
        frozen_at=str(data.get("frozen_at") or ""),
        acceptance_sha256=digest or str(data.get("acceptance_sha256") or ""),
    )


def _acceptance(path: Path, data: dict[str, Any], digest: str) -> TargetInfo | None:
    """Return the target of a frozen acceptance file, or ``None`` when the file is not one."""
    required = ("acceptance_id", "frozen_at", "metric", "comparator", "threshold")
    if data.get("schema_version") != "1" or any(key not in data for key in required):
        return None
    return _target_from(path.name, data, digest)


def _evidence(path: Path, data: dict[str, Any]) -> Measurement | None:
    """Return the result held in a scorer evidence file, or ``None`` when the file is not one."""
    verdicts = {member.value for member in Verdict} - {Verdict.UNKNOWN.value}
    target = data.get("target")
    if data.get("schema_version") != "1" or data.get("verdict") not in verdicts or not isinstance(target, dict):
        return None
    rung = _RUNG.search(path.name)
    return Measurement(
        source=path.name,
        measured_at=str(data.get("measured_at") or ""),
        verdict=Verdict(data["verdict"]),
        metric=str(target.get("metric") or ""),
        observed_value=_number(data.get("observed_value")),
        numerator=_whole(data.get("numerator")),
        denominator=_whole(data.get("denominator")),
        interval_lower=_number(data.get("interval_lower")),
        interval_upper=_number(data.get("interval_upper")),
        rung=int(rung.group(1)) if rung else None,
        target=_target_from(path.name, target),
        freeze=_freeze_from(data.get("predictions_frozen")),
    )


def _eval_notes_target(path: Path) -> TargetInfo:
    """Read ``key: value`` target lines from an ``eval-<session>.md`` file; plain words stay unparsed."""
    fields: dict[str, str] = {}
    try:
        if not path.is_symlink() and path.stat().st_size <= MAX_EVAL_FILE_BYTES:
            for line in path.read_text(encoding="utf-8").splitlines():
                match = _EVAL_FIELD.match(line)
                if match and match.group(1).lower() not in fields:
                    fields[match.group(1).lower()] = match.group(2).strip("`*_ ")
    except (OSError, UnicodeDecodeError):
        return TargetInfo(source=path.name)
    try:
        threshold: float | None = float(fields["threshold"].rstrip("%")) if "threshold" in fields else None
    except ValueError:
        threshold = None
    return TargetInfo(
        source=path.name,
        metric=fields.get("metric", ""),
        comparator=fields.get("comparator", "").lower(),
        threshold=threshold if threshold is not None and math.isfinite(threshold) else None,
        unit=fields.get("unit", ""),
        acceptance_id=fields.get("acceptance_id", ""),
        frozen_at=fields.get("frozen_at", ""),
    )


def _by_modified(paths: list[Path]) -> list[Path]:
    """Return regular files oldest first by modification time, then by name."""
    stamped: list[tuple[float, str, Path]] = []
    for path in paths:
        try:
            if path.is_file() and not path.is_symlink():
                stamped.append((path.stat().st_mtime, path.name, path))
        except OSError:
            continue
    return [path for _, _, path in sorted(stamped)]


def scan_eval_files(vision_dir: Path) -> EvalFiles:
    """Find the eval files Sentinel writes beside the ledger, without writing anything.

    JSON files are recognised by shape: a frozen acceptance has schema ``"1"`` and its
    acceptance fields; scorer evidence has schema ``"1"``, a ``verdict``, and a ``target``.

    Args:
        vision_dir: The project's ``.vision-delivery`` directory.

    Returns:
        Acceptance targets oldest frozen first, scorer results oldest measured first, eval-note
        targets oldest first, and the names of economics and delivery-handoff files.

    Examples:
        >>> scan_eval_files(Path("no-such-directory")).evidence
        ()
    """
    if not vision_dir.is_dir() or vision_dir.is_symlink():
        return EvalFiles()
    acceptances: list[TargetInfo] = []
    evidence: list[Measurement] = []
    for path in sorted(vision_dir.glob("*.json")):
        loaded = _read_json_object(path)
        if loaded is None:
            continue
        data, digest = loaded
        target = _acceptance(path, data, digest)
        result = _evidence(path, data) if target is None else None
        acceptances.extend([target] if target is not None else [])
        evidence.extend([result] if result is not None else [])
    epoch = datetime.min.replace(tzinfo=timezone.utc)
    return EvalFiles(
        acceptances=tuple(sorted(acceptances, key=lambda item: (parse_time(item.frozen_at) or epoch, item.source))),
        evidence=tuple(sorted(evidence, key=lambda item: (parse_time(item.measured_at) or epoch, item.source))),
        eval_targets=tuple(_eval_notes_target(path) for path in _by_modified(list(vision_dir.glob("eval-*.md")))),
        economics=tuple(path.name for path in _by_modified(list(vision_dir.glob("economics-*.md")))),
        handoffs=tuple(path.name for path in _by_modified(list(vision_dir.glob("delivery-handoff-*.json")))),
    )


def locked_target(files: EvalFiles) -> TargetInfo | None:
    """Return the target in force: the latest frozen acceptance, else the latest eval notes.

    Examples:
        >>> locked_target(EvalFiles()) is None
        True
    """
    if files.acceptances:
        return files.acceptances[-1]
    return files.eval_targets[-1] if files.eval_targets else None


def last_measurement(files: EvalFiles, records: list[dict[str, Any]]) -> Measurement | None:
    """Return the latest scorer result, or the latest ``baseline_measured`` row when no evidence exists.

    A ledger row carries no verdict, so that fallback reports the verdict as ``unknown``.

    Examples:
        >>> rows = [{"action": "baseline_measured", "status": "success", "ts": "2026-11-10T10:00:00Z"}]
        >>> last_measurement(EvalFiles(), rows).verdict.value
        'unknown'
    """
    if files.evidence:
        return files.evidence[-1]
    rows = [r for r in records if r.get("action") == "baseline_measured" and r.get("status") == "success"]
    if not rows:
        return None
    row = rows[-1]
    return Measurement(
        source="ledger",
        measured_at=str(row.get("ts") or ""),
        verdict=Verdict.UNKNOWN,
        notes=str(row.get("notes") or ""),
    )


def resume_session(files: EvalFiles, records: list[dict[str, Any]]) -> tuple[str, str]:
    """Return the session slug to reuse on resume and where it came from.

    The latest ``eval-<session>.md`` names it; otherwise the latest skill-written ledger row
    does. Hook rows carry the host's own session id, so they are not used.

    Examples:
        >>> resume_session(EvalFiles(eval_targets=(TargetInfo("eval-factory-counter.md"),)), [])
        ('factory-counter', 'eval-factory-counter.md')
        >>> resume_session(EvalFiles(), [{"source": "skill", "session": "s1"}])
        ('s1', 'ledger')
    """
    if files.eval_targets:
        source = files.eval_targets[-1].source
        return source.removeprefix("eval-").removesuffix(".md"), source
    for record in reversed(records):
        session = record.get("session")
        if record.get("source") == "skill" and isinstance(session, str) and session:
            return session, "ledger"
    return "", ""


def reached_milestones(
    records: list[dict[str, Any]],
    files: EvalFiles,
    measurement: Measurement | None,
    target_matches: bool | None,
    training_operations: frozenset[str],
) -> frozenset[Milestone]:
    """Return the delivery-loop points the ledger and eval files prove were reached.

    Only ``success`` rows count. A pass counts only when the result is known to have been scored
    against the locked target (``target_matches`` is ``True``). A training milestone needs a
    successful provider call that the gate policy files under training.

    Examples:
        >>> sorted(m.value for m in reached_milestones([{"action": "eval_definition", "status": "success"}],
        ...                                             EvalFiles(), None, None, frozenset()))
        ['target-locked']
    """
    success = [record for record in records if record.get("status") == "success"]
    actions = {record.get("action") for record in success}
    checks = {
        Milestone.TARGET_LOCKED: bool(files.acceptances or files.eval_targets) or "eval_definition" in actions,
        Milestone.MEASURED: measurement is not None,
        Milestone.MEASURED_HIGHER_RUNG: any((item.rung or 0) >= 1 for item in files.evidence),
        Milestone.PASSED: measurement is not None and measurement.verdict == Verdict.PASS and target_matches is True,
        Milestone.TRAINED: any(
            record.get("action") == CALL_ACTION and record.get("operation") in training_operations for record in success
        ),
        Milestone.PROOF: bool(PROOF_ACTIONS & actions) or bool(files.handoffs),
        Milestone.ECONOMICS: "crossover_delivered" in actions or bool(files.economics),
        Milestone.DECISION_REPORT: "decision_report_emitted" in actions,
    }
    return frozenset(milestone for milestone, reached in checks.items() if reached)


#: Later steps win: the furthest milestone reached decides what comes next.
_LATE_STEPS = (
    (Milestone.DECISION_REPORT, DeliveryStep.DONE),
    (Milestone.ECONOMICS, DeliveryStep.DECISION),
    (Milestone.PROOF, DeliveryStep.ECONOMICS),
)


def delivery_step(
    milestones: frozenset[Milestone], measurement: Measurement | None, target_matches: bool | None
) -> DeliveryStep:
    """Return the step the project is in now.

    A result scored against a different target, or one that cannot be compared with the locked
    target, leaves the project at the baseline step whatever its verdict.

    Examples:
        >>> delivery_step(frozenset(), None, None).value
        'scope'
        >>> delivery_step(frozenset({Milestone.TARGET_LOCKED}), None, None).value
        'baseline'
        >>> passed = Measurement("e.json", "", Verdict.PASS)
        >>> delivery_step(frozenset({Milestone.TARGET_LOCKED, Milestone.MEASURED}), passed, True).value
        'proof'
        >>> delivery_step(frozenset({Milestone.TARGET_LOCKED, Milestone.MEASURED}), passed, None).value
        'baseline'
    """
    for milestone, step in _LATE_STEPS:
        if milestone in milestones:
            return step
    if Milestone.TARGET_LOCKED not in milestones:
        return DeliveryStep.SCOPE
    if measurement is None or target_matches is not True or measurement.verdict == Verdict.UNKNOWN:
        return DeliveryStep.BASELINE
    return DeliveryStep.PROOF if measurement.verdict == Verdict.PASS else DeliveryStep.IMPROVE


def _brief_action(open_briefs: tuple[BriefStatus, ...]) -> str:
    """Describe the waiting action brief as the one next action."""
    brief = open_briefs[-1]
    others = f" ({len(open_briefs)} briefs are open; this is the latest.)" if len(open_briefs) > 1 else ""
    return (
        f"Action brief {brief.event_id or '(no event id)'} for {brief.operation} is open "
        f"({brief.used} of {brief.limit} calls used). The next {brief.operation} call can use it: on Claude "
        "Code the gate shows the brief at your permission prompt; on Codex there is no gate, so run the action "
        f"yourself or not at all. Unused, it expires at {brief.expires_at}.{others}"
    )


def _baseline_action(measurement: Measurement, target_matches: bool | None) -> str:
    """Return why a measured result leaves the project at the baseline step, as the next action."""
    if measurement.verdict == Verdict.UNKNOWN:
        return UNRECORDED_VERDICT_ACTION
    if target_matches is None:
        return CANNOT_COMPARE_ACTION
    return RESCORE_ACTION if target_matches is False else STEP_ACTIONS[DeliveryStep.BASELINE]


def next_action(
    step: DeliveryStep,
    measurement: Measurement | None,
    target_matches: bool | None,
    briefs: tuple[BriefStatus, ...],
) -> str:
    """Return the one next action: an open action brief first, else the step's own action.

    Examples:
        >>> next_action(DeliveryStep.SCOPE, None, None, ()).startswith("Lock the success target")
        True
        >>> below = Measurement("e.json", "", Verdict.BELOW_TARGET)
        >>> next_action(DeliveryStep.IMPROVE, below, True, ()).startswith("The whole interval misses")
        True
        >>> passed = Measurement("e.json", "", Verdict.PASS)
        >>> next_action(DeliveryStep.BASELINE, passed, None, ()).startswith("The last result cannot be compared")
        True
    """
    open_briefs = tuple(brief for brief in briefs if brief.state == BriefState.OPEN)
    if open_briefs:
        return _brief_action(open_briefs)
    if step == DeliveryStep.BASELINE and measurement is not None:
        return _baseline_action(measurement, target_matches)
    if step == DeliveryStep.IMPROVE and measurement is not None:
        return VERDICT_ACTIONS[measurement.verdict]
    return STEP_ACTIONS[step]


def _has_eval_files(files: EvalFiles) -> bool:
    """Return whether any eval file Sentinel writes sits beside the ledger."""
    return any((files.acceptances, files.evidence, files.eval_targets, files.economics, files.handoffs))


def _unknown_brief_warnings(briefs: tuple[BriefStatus, ...]) -> list[str]:
    """Return one warning per operation whose briefs are ``unknown``, in ledger order."""
    operations = dict.fromkeys(brief.operation for brief in briefs if brief.state == BriefState.UNKNOWN)
    return [
        f"An action brief for {operation} has a timestamp the status reader cannot read, and the gate may "
        f"still read it: no {operation} brief is shown as open, and the gate decides at the next {operation} call."
        for operation in operations
    ]


#: Ledger action a skill records when it hands the candidate search to an upstream search skill.
UPSTREAM_SEARCH_ACTION = "upstream_search_started"
#: Rows that show a result was measured on the gold labels: a recorded baseline (deliver mode needs an
#: acceptance file for it) or a prediction freeze (the explore-mode record of a rung 0 run).
_MEASURED_ACTIONS = frozenset({"baseline_measured", "predictions_frozen"})


def _upstream_search_warnings(records: list[dict[str, Any]], target_locked: bool) -> list[str]:
    """Warn when an upstream candidate search ran out of order or reused the held-out labels.

    The search belongs after the target is locked and the cheapest baseline is measured, and its
    result is scored once on labels the search never saw. A search recorded earlier, or a second
    search after the first one's score, is reported: the reader cannot undo it, only say so.

    Examples:
        >>> search = {"action": "upstream_search_started", "status": "success"}
        >>> measured = {"action": "baseline_measured", "status": "success"}
        >>> len(_upstream_search_warnings([search], True))
        1
        >>> _upstream_search_warnings([measured, search], True)
        []
        >>> "held-out" in _upstream_search_warnings([measured, search, measured, search], True)[0]
        True
    """
    warnings: list[str] = []
    measured = scored_after_search = searched = False
    for record in records:
        if record.get("status") != "success":
            continue
        if record.get("action") in _MEASURED_ACTIONS:
            measured, scored_after_search = True, searched
        elif record.get("action") == UPSTREAM_SEARCH_ACTION:
            if not (measured and target_locked) and not warnings:
                warnings.append(
                    "An upstream candidate search was recorded before the target was locked and a baseline was "
                    "measured: its result was chosen outside the locked acceptance, so score it on labels the "
                    "search never used before calling it a pass."
                )
            if scored_after_search:
                warnings.append(
                    "Another upstream candidate search started after an earlier search result was scored on the "
                    "held-out labels: those labels have now steered the search, so the next score on them is not "
                    "a held-out result. Use a fresh labeled set for the final score."
                )
                scored_after_search = False
            searched = True
    return warnings


def _status_warnings(
    ledger: Path,
    records: list[dict[str, Any]],
    tools: dict[str, Any],
    briefs: tuple[BriefStatus, ...],
    files: EvalFiles,
) -> tuple[str, ...]:
    """Collect the caveats a reader of the status must see."""
    warnings: list[str] = []
    if not ledger.exists() and _has_eval_files(files):
        warnings.append(
            "Eval files exist in the ledger's folder, but there is no ledger file: no action brief, provider "
            "call, or prediction freeze is recorded in it."
        )
    elif not ledger.exists():
        warnings.append("No ledger file yet: nothing has been recorded in this project.")
    if not tools:
        warnings.append("The gate policy is missing or unreadable, so action-brief states may be wrong.")
    conflicts = deduplicate_records(records)[2]
    if conflicts:
        warnings.append(f"{conflicts} ledger event id(s) were reused with different content; those rows are unknown.")
    for brief in briefs:
        if brief.state == BriefState.OPEN and brief.interrupted:
            warnings.append(
                f"{brief.interrupted} call(s) under brief {brief.event_id} ended failed or cancelled; the provider "
                "may already have started that work, so its cost may already be spent."
            )
    warnings.extend(_unknown_brief_warnings(briefs))
    warnings.extend(_upstream_search_warnings(records, locked_target(files) is not None))
    return tuple(warnings)


def _status_records(ledger: Path) -> tuple[list[dict[str, Any]], tuple[str, ...]]:
    """Read the ledger as the gate reads it, and name what the reader had to skip."""
    try:
        records, skipped = read_gate_records(ledger)
    except OSError as exc:
        reason = exc.strerror or type(exc).__name__
        return [], (f"The ledger could not be read ({reason}); the gate refuses every gated call until it can.",)
    if skipped:
        return records, (f"{skipped} ledger line(s) are not valid JSON objects; the gate ignores them too.",)
    return records, ()


def project_status(ledger: Path, now: datetime | None = None, tools: dict[str, Any] | None = None) -> ProjectStatus:
    """Read the ledger and the eval files beside it and say where the project stands.

    Read-only: nothing is written and no provider is called.

    Args:
        ledger: The project's ``.vision-delivery/ledger.jsonl``; eval files are read from its folder.
        now: The moment to judge brief freshness at; defaults to the current UTC time.
        tools: The gate policy's tool table; defaults to the policy shipped with this plugin.

    Returns:
        The project status.

    Examples:
        >>> status = project_status(Path("no-such-project") / ".vision-delivery" / "ledger.jsonl")
        >>> (status.step.value, status.next_action.startswith("Lock the success target"))
        ('scope', True)
    """
    moment = now or datetime.now(timezone.utc)
    policy_tools = _POLICY_TOOLS if tools is None else tools
    records, read_problems = _status_records(ledger)
    files = scan_eval_files(ledger.parent)
    target = locked_target(files)
    measurement = last_measurement(files, records)
    matches = target.same_target(measurement.target) if target and measurement and measurement.target else None
    training = _category_operations(policy_tools, {"training"})
    milestones = reached_milestones(records, files, measurement, matches, training)
    step = delivery_step(milestones, measurement, matches)
    briefs = brief_states(records, policy_tools, moment)
    session, session_source = resume_session(files, records)
    return ProjectStatus(
        ledger=str(ledger),
        ledger_rows=len(records),
        session=session,
        session_source=session_source,
        step=step,
        milestones=milestones,
        target=target,
        measurement=measurement,
        target_matches=matches,
        briefs=briefs,
        next_action=next_action(step, measurement, matches, briefs),
        warnings=(*read_problems, *_status_warnings(ledger, records, policy_tools, briefs, files)),
    )


def _target_line(target: TargetInfo | None) -> str:
    """Render the locked target for the status text."""
    if target is None:
        return "not locked yet"
    rule = target.rule() or "recorded in plain words; read the file"
    details = [f"acceptance {target.acceptance_id}" if target.acceptance_id else ""]
    details.append(f"frozen {target.frozen_at}" if target.frozen_at else "")
    details.append(f"from {target.source}")
    return f"{rule} ({'; '.join(part for part in details if part)})"


def _comparison_note(measurement: Measurement, matches: bool | None, target_locked: bool) -> str:
    """Name the rule a result was scored against when it is not known to be the locked target."""
    if matches is True or measurement.target is None:
        return ""
    target = measurement.target
    acceptance = f" (acceptance {target.acceptance_id})" if target.acceptance_id else ""
    rule = target.rule() or "a target that is not written as a rule"
    if matches is False:
        relation = "a different target than the locked one"
    else:
        relation = "cannot compare with the locked target" if target_locked else "no locked target to compare with"
    return f"; scored against {rule}{acceptance}, {relation}"


def _result_line(measurement: Measurement | None, matches: bool | None, target_locked: bool = True) -> str:
    """Render the last measured result, its verdict, its prediction freeze, and its target for the status text."""
    if measurement is None:
        return "nothing measured yet"
    if measurement.verdict == Verdict.UNKNOWN:
        notes = f"; notes: {measurement.notes}" if measurement.notes else ""
        return f"baseline_measured row at {measurement.measured_at}, verdict not on file{notes}"
    value = f"{measurement.metric} {measurement.observed_value:g}" if measurement.observed_value is not None else ""
    counts = f" ({measurement.numerator} of {measurement.denominator})" if measurement.denominator is not None else ""
    interval = ""
    if measurement.interval_lower is not None and measurement.interval_upper is not None:
        interval = f", 95% interval {measurement.interval_lower:.3g} to {measurement.interval_upper:.3g}"
    rung = f", rung {measurement.rung}" if measurement.rung is not None else ""
    freeze = measurement.freeze.describe() if measurement.freeze is not None else "predictions not frozen"
    target = _comparison_note(measurement, matches, target_locked)
    when = f"measured {measurement.measured_at}{rung}; from {measurement.source}; {freeze}{target}"
    return f"{value}{counts}{interval}: {measurement.verdict.label} ({when})"


def _brief_line(brief: BriefStatus) -> str:
    """Render one brief for the status text."""
    name = brief.event_id or "(no event id)"
    head = f"{brief.state.value:<9}{name} for {brief.operation} ({brief.operation_class.value})"
    if brief.state == BriefState.OPEN:
        return f"{head}: {brief.used} of {brief.limit} calls used, {brief.remaining} left; expires {brief.expires_at}"
    if brief.state in (BriefState.USED, BriefState.REPLACED):
        return f"{head}: {brief.used} of {brief.limit} calls used"
    return f"{head}: {', '.join(brief.problems)}"


def status_lines(status: ProjectStatus) -> list[str]:
    """Render the project status as plain text lines.

    Examples:
        >>> lines = status_lines(project_status(Path("no-such-project") / "ledger.jsonl"))
        >>> lines[0]
        'Sentinel project status (read-only)'
    """
    session = f"{status.session} (from {status.session_source}; reuse it)" if status.session else "none recorded yet"
    lines = [
        "Sentinel project status (read-only)",
        f"Ledger:       {status.ledger} ({status.ledger_rows} rows)",
        f"Session:      {session}",
        f"Step:         {status.step.number} of {len(DeliveryStep)}, {STEP_TITLES[status.step]}",
        f"Target:       {_target_line(status.target)}",
        f"Last result:  {_result_line(status.measurement, status.target_matches, status.target is not None)}",
    ]
    open_briefs = status.open_briefs()
    unknown = [brief for brief in status.briefs if brief.state == BriefState.UNKNOWN]
    earlier = [brief for brief in status.briefs if brief.state not in (BriefState.OPEN, BriefState.UNKNOWN)]
    unknown_count = f"{len(unknown)} unknown, " if unknown else ""
    lines.append(f"Briefs:       {len(open_briefs)} open, {unknown_count}{len(earlier)} earlier")
    lines.extend(f"  {_brief_line(brief)}" for brief in (*open_briefs, *unknown, *earlier[-3:]))
    lines.append(f"Next action:  {status.next_action}")
    lines.extend(f"Warning:      {warning}" for warning in status.warnings)
    return lines


def main() -> None:
    """Entry point — parse args, load ledger, emit the metrics report or the project status."""
    parser = argparse.ArgumentParser(description="vision-delivery ledger report")
    parser.add_argument("--json", action="store_true", help="emit JSON output")
    parser.add_argument("--ledger", type=Path, default=None, help="path to ledger.jsonl")
    parser.add_argument(
        "--status",
        action="store_true",
        help="show where the project stands: step, locked target, last result, open action briefs, next action",
    )
    args = parser.parse_args()

    ledger = args.ledger if args.ledger else _default_ledger()
    if args.status:
        status = project_status(ledger)
        print(json.dumps(status.to_json(), indent=2) if args.json else "\n".join(status_lines(status)))
        return
    records = load_records(ledger)
    m = compute_metrics(records)

    if args.json:
        print(json.dumps(m, indent=2))
    else:
        print_text(m)


if __name__ == "__main__":
    main()
