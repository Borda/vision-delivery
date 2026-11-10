#!/usr/bin/env python3
"""Simulated approver for the A/B harness: answers Roboflow permission prompts the way a persona would.

Why it exists: Sentinel's ``PreToolUse`` gate (``hooks/gate.js``) returns ``ask``
for a paid or state-changing Roboflow call that has a recorded action brief. In a
``claude -p`` run nobody can answer that prompt, so the host denies the call and
the plugin arm can never finish a paid step, for a harness reason rather than a
product reason. This module stands in for the human at that prompt, in BOTH arms,
so both arms face the same human.

What the approver sees is what a human sees at the prompt: the tool name, the tool
input, and the action brief the gate names. The ``PermissionRequest`` hook input
does not carry the gate's ``permissionDecisionReason`` (hooks.md, "PermissionRequest
input"), so the approver reads the brief from the same project ledger the gate reads
(``<project>/.vision-delivery/ledger.jsonl``): the latest ``action_brief_emitted`` row for
the exact operation that the gate itself would accept (see ``find_brief`` and ``gate_accepts``).

How it answers is persona data, not code: the ``approver:`` block of the persona
YAML (operations to approve or deny, a cumulative credit cap, and the answer to a
prompt that states no cost). Code only adds one harness safety rail: a Roboflow tool
that the A/B mock server does not serve is a real provider call and is always denied.

Mechanisms (``Mechanism``; the runner's ``--approver`` flag picks one):

- ``hook`` (default): a ``PermissionRequest`` command hook. Doc basis, Claude Code
  docs fetched 2026-11-10: headless.md "Auto-approve tools" (a Manual-mode ``-p``
  call that needs approval "is denied unless something approves it, such as a
  PermissionRequest hook or a --permission-prompt-tool") and "Turn off permission
  prompts in unattended runs" ("Anything that would prompt is denied unless a
  PermissionRequest hook allows it"); hooks.md "PermissionRequest" (hooks run "when
  Claude Code is about to ask you for permission, or when it would otherwise
  auto-deny a call that can't prompt") and "PreToolUse decision control" (``"ask"``
  prompts the user; for ``"ask"`` in a ``-p`` run "where no one can answer that
  prompt, Claude reads the reason in the tool result instead").
  Unproven: no doc line shows a ``PreToolUse`` ``ask`` flowing into a
  ``PermissionRequest`` hook in a ``-p`` run; it follows from the lines above but no
  live run has exercised it.
- ``prompt-tool``: a stdio MCP server whose ``approve`` tool is passed to
  ``--permission-prompt-tool``. Fallback only. Its request/response contract
  (``{"tool_name", "input"}`` in; ``{"behavior": "allow", "updatedInput"}`` or
  ``{"behavior": "deny", "message"}`` out) is NOT in the fetched docs and is
  unverified. A permission host also makes ``AskUserQuestion`` available to the agent
  (hooks.md "Tools that require user interaction"), which changes the conversation.
- ``off``: no approver; the runner's pre-approver behaviour (blanket Roboflow allow rule).

Usage:
    python3 evals/ab/approver.py hook --config <run_dir>/approver.json < hook-input.json
    python3 evals/ab/approver.py mcp --config <run_dir>/approver.json
"""

from __future__ import annotations

import argparse
import fnmatch
import json
import math
import os
import re
import sys
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from enum import Enum
from pathlib import Path
from typing import Any, TextIO

#: Same tool-name shape as ``ROBOFLOW_TOOL`` in hooks/roboflow-ops.js.
ROBOFLOW_TOOL_RE = re.compile(r"^mcp__(?:(?!__).)*roboflow(?:(?!__).)*__(.+)$", re.IGNORECASE)
#: Hook matcher for the runner's settings file; same regex as hooks/claude-hooks.json.
HOOK_MATCHER = "^mcp__((?!__).)*[Rr][Oo][Bb][Oo][Ff][Ll][Oo][Ww]((?!__).)*__.*$"
#: The gate policy the plugin ships; the approver reads tool classes from it, as the gate does.
GATE_POLICY = Path(__file__).resolve().parents[2] / "hooks" / "gate-policy.json"
#: Limits copied from hooks/gate.js: brief age, clock skew, cost-date age, and the largest call budget.
BRIEF_MAX_AGE = timedelta(hours=24)
CLOCK_SKEW = timedelta(minutes=5)
COST_MAX_AGE = timedelta(days=90)
MAX_CALL_BUDGET = 1000
BRIEF_TEXT_FIELDS = ("scope", "cost_unit", "cost_source", "cost_as_of", "data_movement", "rollback")
ISO_DATE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
#: Tool prefix of the A/B mock server: the runner names it "roboflow" in --mcp-config.
MOCK_TOOL_PREFIX = "mcp__roboflow__"
BRIEF_ACTION = "action_brief_emitted"
CREDIT_UNITS = frozenset({"credit", "credits"})
CONFIG_FILE = "approver.json"
LOG_FILE = "approvals.jsonl"
TURN_FILE = "current_turn.txt"
PROMPT_TOOL_SERVER = "approver"
PROMPT_TOOL_NAME = "approve"
#: Fully qualified name the runner passes to --permission-prompt-tool.
PROMPT_TOOL = f"mcp__{PROMPT_TOOL_SERVER}__{PROMPT_TOOL_NAME}"
MCP_PROTOCOL_FALLBACK = "2025-06-18"
MAX_OPERATION_CHARACTERS = 200


class Mechanism(str, Enum):
    """How the runner connects the approver to Claude Code (``--approver`` flag value)."""

    HOOK = "hook"
    PROMPT_TOOL = "prompt-tool"
    OFF = "off"


class Decision(str, Enum):
    """The approver's answer to one permission prompt."""

    ALLOW = "allow"
    DENY = "deny"
    #: Not a Roboflow tool: the approver leaves the host's permission flow unchanged.
    PASSTHROUGH = "passthrough"


@dataclass(frozen=True)
class PersonaRule:
    """How a persona answers a Roboflow permission prompt (the persona YAML ``approver:`` block).

    Attributes:
        persona: Persona name, copied into every log line.
        approve_operations: ``fnmatch`` patterns of operations the persona approves.
        deny_operations: ``fnmatch`` patterns the persona always denies; checked first.
        spend_cap_credits: Cumulative cap over the credit costs of approved briefs, or
            ``None`` for no cap. Each brief (event id) counts once.
        unstated_cost: Answer when the prompt states no credit cost (no brief, or a
            cost in another unit).
    """

    persona: str
    approve_operations: tuple[str, ...]
    deny_operations: tuple[str, ...]
    spend_cap_credits: float | None
    unstated_cost: Decision

    @classmethod
    def from_persona(cls, persona: Mapping[str, Any]) -> PersonaRule:
        """Parse a loaded persona document; fail fast on a missing or malformed ``approver:`` block.

        Examples:
            >>> rule = PersonaRule.from_persona({"name": "p", "approver": {"approve_operations": ["*"],
            ...     "deny_operations": [], "spend_cap_credits": 10, "unstated_cost": "deny"}})
            >>> rule.spend_cap_credits, rule.unstated_cost.value
            (10.0, 'deny')
        """
        name = str(persona.get("name", "?"))
        block = persona.get("approver")
        if not isinstance(block, Mapping):
            raise ValueError(f"persona {name!r} has no approver: block; add one (see evals/ab/README.md)")
        cap = block.get("spend_cap_credits")
        if cap is not None and (isinstance(cap, bool) or not isinstance(cap, (int, float)) or cap < 0):
            raise ValueError(f"persona {name!r}: spend_cap_credits must be a non-negative number or null")
        unstated = Decision(block.get("unstated_cost"))
        if unstated == Decision.PASSTHROUGH:
            raise ValueError(f"persona {name!r}: unstated_cost must be 'allow' or 'deny'")
        return cls(
            persona=name,
            approve_operations=_patterns(name, block, "approve_operations"),
            deny_operations=_patterns(name, block, "deny_operations"),
            spend_cap_credits=None if cap is None else float(cap),
            unstated_cost=unstated,
        )

    def to_json(self) -> dict[str, Any]:
        """Serialize to the persona-YAML shape (round-trips through ``from_persona``)."""
        return {
            "name": self.persona,
            "approver": {
                "approve_operations": list(self.approve_operations),
                "deny_operations": list(self.deny_operations),
                "spend_cap_credits": self.spend_cap_credits,
                "unstated_cost": self.unstated_cost.value,
            },
        }


def _patterns(name: str, block: Mapping[str, Any], key: str) -> tuple[str, ...]:
    values = block.get(key)
    if not isinstance(values, list) or not all(isinstance(v, str) and v for v in values):
        raise ValueError(f"persona {name!r}: {key} must be a list of operation patterns")
    return tuple(values)


@dataclass(frozen=True)
class ApproverConfig:
    """Everything one approver process needs; the runner writes it as ``<run_dir>/approver.json``.

    Attributes:
        rule: The persona's answering rule.
        mechanism: How the approver is connected (logged with every decision).
        project_dir: Session working directory; the ledger fallback when the host
            gives no ``CLAUDE_PROJECT_DIR`` and no ``cwd``.
        run_dir: Run directory; holds the decision log and the current user-turn index.
    """

    rule: PersonaRule
    mechanism: Mechanism
    project_dir: Path
    run_dir: Path

    @property
    def log_path(self) -> Path:
        """Decision log: one JSON line per answered prompt."""
        return self.run_dir / LOG_FILE

    def to_json(self) -> dict[str, Any]:
        """Serialize for ``approver.json``."""
        return {
            "persona": self.rule.to_json(),
            "mechanism": self.mechanism.value,
            "project_dir": str(self.project_dir),
            "run_dir": str(self.run_dir),
        }

    @classmethod
    def load(cls, path: Path) -> ApproverConfig:
        """Read ``approver.json`` written by the runner."""
        raw = json.loads(path.read_text(encoding="utf-8"))
        return cls(
            rule=PersonaRule.from_persona(raw["persona"]),
            mechanism=Mechanism(raw["mechanism"]),
            project_dir=Path(raw["project_dir"]),
            run_dir=Path(raw["run_dir"]),
        )


@dataclass(frozen=True)
class PromptRequest:
    """One permission prompt as the approver receives it.

    Attributes:
        tool_name: Full tool name, e.g. ``mcp__roboflow__trainings_create``.
        tool_input: The tool's arguments as Claude sent them.
        mcp_source: ``mcp_server.source`` from the hook input when present (``plugin`` marks
            a plugin-provided server).
        cwd: Session working directory from the hook input, when present.
    """

    tool_name: str
    tool_input: dict[str, Any]
    mcp_source: str | None = None
    cwd: str | None = None

    @classmethod
    def from_hook_input(cls, payload: Mapping[str, Any]) -> PromptRequest:
        """Build from ``PermissionRequest`` hook input (hooks.md "PermissionRequest input")."""
        server = payload.get("mcp_server")
        source = server.get("source") if isinstance(server, Mapping) else None
        tool_input = payload.get("tool_input")
        return cls(
            tool_name=str(payload.get("tool_name") or ""),
            tool_input=dict(tool_input) if isinstance(tool_input, Mapping) else {},
            mcp_source=source if isinstance(source, str) else None,
            cwd=payload.get("cwd") if isinstance(payload.get("cwd"), str) else None,
        )


@dataclass(frozen=True)
class Brief:
    """The action brief a gate prompt names: what the human reads about cost."""

    event_id: str | None
    cost_amount: float | None
    cost_unit: str | None

    @property
    def credits(self) -> float | None:
        """Stated cost in credits, or ``None`` when the brief states no credit cost."""
        if self.cost_amount is None or (self.cost_unit or "").strip().lower() not in CREDIT_UNITS:
            return None
        return self.cost_amount


@dataclass(frozen=True)
class Verdict:
    """One answered prompt; ``as_log_row`` is the ``approvals.jsonl`` line."""

    tool: str
    operation: str
    decision: Decision
    reason: str
    brief: Brief | None = None
    spent_credits: float = 0.0

    def as_log_row(self, persona: str, mechanism: Mechanism, turn: int) -> dict[str, Any]:
        """Return the decision-log line (fixed key set; absent values are ``null``)."""
        return {
            "turn": turn,
            "persona": persona,
            "mechanism": mechanism.value,
            "tool": self.tool,
            "operation": self.operation,
            "decision": self.decision.value,
            "reason": self.reason,
            "brief_event_id": self.brief.event_id if self.brief else None,
            "cost_amount": self.brief.cost_amount if self.brief else None,
            "cost_unit": self.brief.cost_unit if self.brief else None,
            "spent_credits": self.spent_credits,
        }


def operation_of(tool_name: str) -> str:
    """Return the Roboflow operation of a tool name, or ``""`` for any other tool.

    Mirrors ``operation()`` in hooks/roboflow-ops.js so the approver and the gate look up
    the same ledger operation.

    Examples:
        >>> operation_of("mcp__roboflow__trainings_create")
        'trainings_create'
        >>> operation_of("mcp__plugin_sentinel_roboflow__projects_list")
        'projects_list'
        >>> operation_of("Read")
        ''
    """
    match = ROBOFLOW_TOOL_RE.match(tool_name)
    if not match:
        return ""
    return re.sub(r"[^a-zA-Z0-9_-]", "", match.group(1))[:MAX_OPERATION_CHARACTERS]


def read_jsonl(path: Path) -> list[dict[str, Any]]:
    """Read JSON-object lines; a missing file is empty and malformed lines are skipped."""
    if not path.exists():
        return []
    rows: list[dict[str, Any]] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        try:
            row = json.loads(line)
        except json.JSONDecodeError:
            continue  # a malformed row cannot state a brief
        if isinstance(row, dict):
            rows.append(row)
    return rows


def resolve_project_dir(env: Mapping[str, str], cwd: str | None, fallback: Path) -> Path:
    """Pick the project directory whose ledger the gate read.

    Order: ``CLAUDE_PROJECT_DIR`` (what hooks/roboflow-ops.js ``projectRoot()`` and
    scripts/ledger_append.py use first), then the hook input ``cwd``, then the runner's
    workspace. Never walks up the tree: the run workspace sits inside this repository,
    so a walk-up would find the repository's own ``.vision-delivery`` ledger.

    Examples:
        >>> resolve_project_dir({}, None, Path("/w")).as_posix()
        '/w'
        >>> resolve_project_dir({"CLAUDE_PROJECT_DIR": "relative"}, "/c", Path("/w")).as_posix()
        '/c'
    """
    declared = env.get("CLAUDE_PROJECT_DIR", "")
    if declared and Path(declared).is_absolute():
        return Path(declared)
    if cwd and Path(cwd).is_absolute():
        return Path(cwd)
    return fallback


def _brief_from_row(row: Mapping[str, Any]) -> Brief:
    fields = _mapping(row.get("brief"))
    amount = fields.get("cost_amount")
    cost = float(amount) if isinstance(amount, (int, float)) and not isinstance(amount, bool) else None
    unit = fields.get("cost_unit")
    event_id = row.get("event_id")
    return Brief(
        event_id=event_id if isinstance(event_id, str) and event_id else None,
        cost_amount=cost if cost is not None and cost >= 0 else None,
        cost_unit=unit if isinstance(unit, str) and unit.strip() else None,
    )


def operation_class(operation: str, policy_path: Path = GATE_POLICY) -> str:
    """Return the gate class of an operation (``open``, ``brief`` or ``budget``), as hooks/roboflow-ops.js does.

    An unlisted operation, an unknown class, an ``open`` entry without the provider's
    read-only flag, and an unreadable policy all report ``brief``: the gated default.

    Examples:
        >>> operation_class("projects_list"), operation_class("trainings_create"), operation_class("not_a_tool")
        ('open', 'brief', 'brief')
        >>> operation_class("projects_list", Path("missing-policy.json"))
        'brief'
    """
    try:
        policy = json.loads(policy_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return "brief"
    entry = _mapping(_mapping(_mapping(policy).get("tools")).get(operation))
    found = entry.get("class")
    if found == "open":
        return "open" if entry.get("read_only") is True else "brief"
    return "budget" if found == "budget" else "brief"


def _parse_time(value: Any) -> datetime | None:
    if not isinstance(value, str):
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)


def _cost_date_ok(value: Any, now: datetime) -> bool:
    if not isinstance(value, str) or not ISO_DATE.match(value):
        return False
    try:
        as_of = date.fromisoformat(value)
    except ValueError:
        return False
    return (now - COST_MAX_AGE).date() <= as_of <= (now + BRIEF_MAX_AGE).date()


def gate_accepts(row: Mapping[str, Any], gate_class: str, now: datetime) -> bool:
    """Return whether hooks/gate.js would take this ledger row as a usable action brief.

    The same rule as ``briefState`` and ``briefProblems`` there: a successful brief row that
    is at most 24 hours old and at most 5 minutes ahead of the clock, with every text field
    filled, a finite non-negative cost, a cost date inside 90 days, and a call budget when the
    operation runs under one.

    Examples:
        >>> now = datetime(2026, 11, 10, 12, tzinfo=timezone.utc)
        >>> fields = {"scope": "s", "cost_unit": "credits", "cost_source": "price page", "cost_as_of": "2026-11-10",
        ...           "data_movement": "none", "rollback": "none", "cost_amount": 5}
        >>> row = {"action": "action_brief_emitted", "status": "success", "ts": "2026-11-10T10:00:00Z", "brief": fields}
        >>> gate_accepts(row, "brief", now), gate_accepts(row, "budget", now)
        (True, False)
        >>> gate_accepts({**row, "ts": "2026-11-08T10:00:00Z"}, "brief", now)
        False
        >>> gate_accepts({**row, "brief": {**fields, "rollback": " "}}, "brief", now)
        False
    """
    if row.get("action") != BRIEF_ACTION or row.get("status") != "success":
        return False
    written = _parse_time(row.get("ts"))
    if written is None or now - written > BRIEF_MAX_AGE or written - now > CLOCK_SKEW:
        return False
    fields = _mapping(row.get("brief"))
    checks = (
        all(isinstance(fields.get(name), str) and fields[name].strip() for name in BRIEF_TEXT_FIELDS),
        _valid_cost(fields.get("cost_amount")),
        _cost_date_ok(fields.get("cost_as_of"), now),
        gate_class != "budget" or _valid_call_budget(fields.get("call_budget")),
    )
    return all(checks)


def _valid_cost(amount: Any) -> bool:
    if isinstance(amount, bool) or not isinstance(amount, (int, float)):
        return False
    return math.isfinite(amount) and amount >= 0


def _valid_call_budget(budget: Any) -> bool:
    return isinstance(budget, int) and not isinstance(budget, bool) and 1 <= budget <= MAX_CALL_BUDGET


def find_brief(ledger_rows: list[dict[str, Any]], operation: str, now: datetime | None = None) -> Brief | None:
    """Return the action brief a gate prompt for ``operation`` shows, or ``None`` when the gate shows none.

    The gate prompts with the latest brief for exactly ``operation`` that it accepts
    (``gate_accepts``). A later stale or incomplete brief never displaces an earlier valid
    one, so a cheap but unusable row cannot stand in for the price the person was shown.

    Examples:
        >>> now = datetime(2026, 11, 10, 12, tzinfo=timezone.utc)
        >>> def row(event_id, cost, **changed):
        ...     fields = {"scope": "s", "cost_unit": "credits", "cost_source": "price page", "data_movement": "none",
        ...               "cost_as_of": "2026-11-10", "rollback": "none", "cost_amount": cost, **changed}
        ...     return {"action": "action_brief_emitted", "status": "success", "operation": "trainings_create",
        ...             "event_id": event_id, "ts": "2026-11-10T10:00:00Z", "brief": fields}
        >>> rows = [row("e1", 100), row("e2", 1, rollback="")]
        >>> find_brief(rows, "trainings_create", now)
        Brief(event_id='e1', cost_amount=100.0, cost_unit='credits')
        >>> find_brief(rows[1:], "trainings_create", now) is None
        True
        >>> find_brief(rows, "versions_generate", now) is None
        True
    """
    moment = now or datetime.now(timezone.utc)
    gate_class = operation_class(operation)
    for row in reversed(ledger_rows):
        if row.get("operation") == operation and gate_accepts(row, gate_class, moment):
            return _brief_from_row(row)
    return None


def approved_spend(log_rows: list[dict[str, Any]]) -> tuple[float, frozenset[str]]:
    """Sum credit costs over approved briefs, counting each brief event id once.

    A ``budget``-class brief covers several calls under one stated cost, so a repeat
    approval of the same event id adds nothing.

    Examples:
        >>> rows = [{"decision": "allow", "brief_event_id": "e1", "cost_amount": 5, "cost_unit": "credits"},
        ...         {"decision": "allow", "brief_event_id": "e1", "cost_amount": 5, "cost_unit": "credits"},
        ...         {"decision": "deny", "brief_event_id": "e2", "cost_amount": 9, "cost_unit": "credits"}]
        >>> approved_spend(rows)
        (5.0, frozenset({'e1'}))
    """
    total = 0.0
    seen: set[str] = set()
    for row in log_rows:
        event_id = row.get("brief_event_id")
        if row.get("decision") != Decision.ALLOW.value or not isinstance(event_id, str) or event_id in seen:
            continue
        seen.add(event_id)
        brief = Brief(event_id, row.get("cost_amount"), row.get("cost_unit"))
        total += brief.credits or 0.0
    return total, frozenset(seen)


def _matches(operation: str, patterns: tuple[str, ...]) -> bool:
    return any(fnmatch.fnmatchcase(operation, pattern) for pattern in patterns)


def _operation_refusal(request: PromptRequest, operation: str, rule: PersonaRule) -> str | None:
    """Reason to deny before reading any brief, or ``None`` when the operation may proceed."""
    if not request.tool_name.startswith(MOCK_TOOL_PREFIX) or request.mcp_source == "plugin":
        return (
            f"harness safety: {request.tool_name} is not served by the A/B mock server, so it would be a real "
            "provider call; the harness never approves one"
        )
    if _matches(operation, rule.deny_operations):
        return f"persona {rule.persona} denies {operation} (deny_operations)"
    if not _matches(operation, rule.approve_operations):
        return f"persona {rule.persona} does not approve {operation} (not in approve_operations)"
    return None


def _cost_verdict(base: Verdict, rule: PersonaRule, brief: Brief | None, log_rows: list[dict[str, Any]]) -> Verdict:
    """Answer on cost: a stated credit cost meets the cap; anything else gets ``unstated_cost``."""
    spent, approved_ids = approved_spend(log_rows)
    if brief is not None and brief.event_id and brief.event_id in approved_ids:
        reason = f"brief {brief.event_id} was already approved; this call adds no new spend"
        return _with(base, Decision.ALLOW, reason, brief, spent)
    if brief is None or brief.credits is None:
        stated = "no action brief" if brief is None else f"brief {brief.event_id} states no credit cost"
        reason = f"{stated}; persona {rule.persona} answers an unstated cost with {rule.unstated_cost.value}"
        return _with(base, rule.unstated_cost, reason, brief, spent)
    credits = brief.credits
    cap = rule.spend_cap_credits
    if cap is not None and spent + credits > cap:
        reason = f"brief {brief.event_id} costs {credits:g} credits; {spent:g} already approved; cap {cap:g}"
        return _with(base, Decision.DENY, reason, brief, spent)
    cap_text = "no cap" if cap is None else f"within cap {cap:g}"
    reason = f"brief {brief.event_id} states {credits:g} credits; {cap_text}"
    return _with(base, Decision.ALLOW, reason, brief, spent + credits)


def _with(base: Verdict, decision: Decision, reason: str, brief: Brief | None, spent: float) -> Verdict:
    return Verdict(base.tool, base.operation, decision, reason, brief, spent)


def decide(
    request: PromptRequest,
    rule: PersonaRule,
    ledger_rows: list[dict[str, Any]],
    log_rows: list[dict[str, Any]],
    now: datetime | None = None,
) -> Verdict:
    """Answer one permission prompt as the persona would; reads only the shipped gate policy.

    A read-only operation (class ``open`` in the gate policy) carries no cost and no brief,
    so it is approved once the persona's operation rules allow it; ``unstated_cost`` applies
    only to operations the gate holds.

    Args:
        request: The prompt (tool name, tool input, server source).
        rule: The persona's answering rule.
        ledger_rows: Rows of the project ledger the gate reads.
        log_rows: This run's earlier decisions (for the cumulative spend cap).
        now: Clock used to judge brief freshness; defaults to the current time.

    Returns:
        The verdict; ``PASSTHROUGH`` for a non-Roboflow tool.

    Examples:
        >>> rule = PersonaRule("p", ("*",), (), None, Decision.ALLOW)
        >>> decide(PromptRequest("Read", {}), rule, [], []).decision.value
        'passthrough'
        >>> decide(PromptRequest("mcp__roboflow__projects_list", {}), rule, [], []).decision.value
        'allow'
    """
    operation = operation_of(request.tool_name)
    spent, _ = approved_spend(log_rows)
    base = Verdict(request.tool_name, operation, Decision.PASSTHROUGH, "not a Roboflow tool", None, spent)
    if not operation:
        return base
    refusal = _operation_refusal(request, operation, rule)
    if refusal:
        return _with(base, Decision.DENY, refusal, None, spent)
    if operation_class(operation) == "open":
        return _with(
            base, Decision.ALLOW, f"{operation} is read-only in the gate policy; no cost to weigh", None, spent
        )
    return _cost_verdict(base, rule, find_brief(ledger_rows, operation, now), log_rows)


def current_turn(run_dir: Path) -> int:
    """User-turn index the runner wrote for this turn (``-1`` when unknown), as the mock server logs it."""
    try:
        return int((run_dir / TURN_FILE).read_text(encoding="utf-8").strip())
    except (OSError, ValueError):
        return -1


def answer(request: PromptRequest, config: ApproverConfig, env: Mapping[str, str]) -> Verdict:
    """Read the ledger and the decision log, decide, and append the decision to the log."""
    project = resolve_project_dir(env, request.cwd, config.project_dir)
    ledger_rows = read_jsonl(project / ".vision-delivery" / "ledger.jsonl")
    verdict = decide(request, config.rule, ledger_rows, read_jsonl(config.log_path))
    append_log(config, verdict)
    return verdict


def append_log(config: ApproverConfig, verdict: Verdict) -> None:
    """Append one decision line to ``approvals.jsonl``."""
    row = verdict.as_log_row(config.rule.persona, config.mechanism, current_turn(config.run_dir))
    with config.log_path.open("a", encoding="utf-8", newline="\n") as fh:
        fh.write(json.dumps(row) + "\n")


def hook_output(verdict: Verdict) -> dict[str, Any] | None:
    """``PermissionRequest`` hook output (hooks.md "PermissionRequest decision control"); ``None`` = no decision.

    Examples:
        >>> hook_output(Verdict("t", "op", Decision.DENY, "over cap"))["hookSpecificOutput"]["decision"]
        {'behavior': 'deny', 'message': 'over cap'}
    """
    if verdict.decision == Decision.PASSTHROUGH:
        return None
    decision: dict[str, Any] = {"behavior": verdict.decision.value}
    if verdict.decision == Decision.DENY:
        decision["message"] = verdict.reason
    return {"hookSpecificOutput": {"hookEventName": "PermissionRequest", "decision": decision}}


def prompt_tool_output(verdict: Verdict, tool_input: dict[str, Any]) -> dict[str, Any]:
    """Permission-prompt-tool answer (UNVERIFIED contract; see the module docstring).

    A non-Roboflow tool is denied: a ``-p`` run without a permission host denies every
    prompt, so this keeps the runner's earlier behaviour for those tools.
    """
    if verdict.decision == Decision.ALLOW:
        return {"behavior": "allow", "updatedInput": tool_input}
    if verdict.decision == Decision.PASSTHROUGH:
        return {"behavior": "deny", "message": "No one answers this prompt in the A/B harness."}
    return {"behavior": "deny", "message": verdict.reason}


def run_hook(config: ApproverConfig, stdin: TextIO, stdout: TextIO, env: Mapping[str, str]) -> int:
    """Answer one ``PermissionRequest`` hook call from stdin; always exit 0 (decisions go in JSON)."""
    try:
        payload = json.loads(stdin.read())
    except json.JSONDecodeError:
        payload = None
    if not isinstance(payload, dict):
        unreadable = Verdict("", "", Decision.DENY, "approver could not read the permission request")
        append_log(config, unreadable)
        stdout.write(json.dumps(hook_output(unreadable)))
        return 0
    output = hook_output(answer(PromptRequest.from_hook_input(payload), config, env))
    if output is not None:
        stdout.write(json.dumps(output))
    return 0


PROMPT_TOOL_SPEC: dict[str, Any] = {
    "name": PROMPT_TOOL_NAME,
    "description": "A/B harness simulated approver for permission prompts. Not for direct use.",
    "inputSchema": {
        "type": "object",
        "properties": {"tool_name": {"type": "string"}, "input": {"type": "object"}},
        "required": ["tool_name"],
    },
}


def _mapping(value: object) -> Mapping[str, Any]:
    return value if isinstance(value, Mapping) else {}


def _mcp_call(params: Mapping[str, Any], config: ApproverConfig, env: Mapping[str, str]) -> dict[str, Any]:
    args = _mapping(params.get("arguments"))
    request = PromptRequest(str(args.get("tool_name") or ""), dict(_mapping(args.get("input"))))
    if params.get("name") != PROMPT_TOOL_NAME:
        body = {"behavior": "deny", "message": f"unknown approver tool {params.get('name')!r}"}
    else:
        body = prompt_tool_output(answer(request, config, env), request.tool_input)
    return {"content": [{"type": "text", "text": json.dumps(body)}]}


def mcp_response(message: Mapping[str, Any], config: ApproverConfig, env: Mapping[str, str]) -> dict[str, Any] | None:
    """Answer one MCP JSON-RPC message; ``None`` for notifications.

    Examples:
        >>> cfg = ApproverConfig(PersonaRule("p", ("*",), (), None, Decision.ALLOW), Mechanism.PROMPT_TOOL,
        ...                      Path("/w"), Path("/r"))
        >>> mcp_response({"jsonrpc": "2.0", "id": 1, "method": "ping"}, cfg, {})
        {'jsonrpc': '2.0', 'id': 1, 'result': {}}
        >>> mcp_response({"jsonrpc": "2.0", "method": "notifications/initialized"}, cfg, {}) is None
        True
    """
    if "id" not in message:
        return None
    params = _mapping(message.get("params"))
    handlers: dict[str, Callable[[], dict[str, Any]]] = {
        "initialize": lambda: {
            "protocolVersion": params.get("protocolVersion") or MCP_PROTOCOL_FALLBACK,
            "capabilities": {"tools": {}},
            "serverInfo": {"name": "ab-approver", "version": "1"},
        },
        "ping": dict,
        "tools/list": lambda: {"tools": [PROMPT_TOOL_SPEC]},
        "tools/call": lambda: _mcp_call(params, config, env),
    }
    handler = handlers.get(str(message.get("method")))
    if handler is None:
        error = {"code": -32601, "message": f"method not found: {message.get('method')}"}
        return {"jsonrpc": "2.0", "id": message["id"], "error": error}
    return {"jsonrpc": "2.0", "id": message["id"], "result": handler()}


def run_mcp(config: ApproverConfig, stdin: TextIO, stdout: TextIO, env: Mapping[str, str]) -> int:
    """Serve the permission-prompt tool over stdio (newline-delimited JSON-RPC) until stdin closes."""
    for line in stdin:
        if not line.strip():
            continue
        try:
            message = json.loads(line)
        except json.JSONDecodeError:
            response: dict[str, Any] | None = {
                "jsonrpc": "2.0",
                "id": None,
                "error": {"code": -32700, "message": "parse error"},
            }
        else:
            response = mcp_response(message, config, env) if isinstance(message, dict) else None
        if response is not None:
            stdout.write(json.dumps(response) + "\n")
            stdout.flush()
    return 0


def main(argv: list[str] | None = None) -> int:
    """CLI entry: ``hook`` answers one hook call, ``mcp`` serves the permission-prompt tool."""
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("mode", choices=["hook", "mcp"])
    parser.add_argument("--config", required=True, type=Path, help="approver.json written by runner.py")
    args = parser.parse_args(argv)
    config = ApproverConfig.load(args.config)
    if args.mode == "hook":
        return run_hook(config, sys.stdin, sys.stdout, os.environ)
    return run_mcp(config, sys.stdin, sys.stdout, os.environ)


if __name__ == "__main__":
    sys.exit(main())
