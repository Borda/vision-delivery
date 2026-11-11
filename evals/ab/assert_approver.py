#!/usr/bin/env python3
"""Deterministic checks for the A/B harness simulated approver and the runner's permission flags.

No live model calls, no network, no ``claude`` binary. Covers the persona
``approver:`` blocks, every decision path of ``approver.decide`` (approve, deny by
persona rule, spend cap, missing brief, non-Roboflow passthrough, real-provider
safety rail), the ``approvals.jsonl`` line shape, both mechanisms end-to-end as
subprocesses (``PermissionRequest`` hook on stdin, permission-prompt MCP server over
stdio), and the exact ``claude -p`` argv the runner builds for each arm.

Usage:
    python3 evals/ab/assert_approver.py
"""

from __future__ import annotations

import doctest
import json
import os
import subprocess
import sys
import tempfile
from dataclasses import replace
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import approver
import runner
import yaml
from approver import Decision, Mechanism, PersonaRule, PromptRequest

AB = Path(__file__).resolve().parent
ROOT = AB.parents[1]
MOCK = approver.MOCK_TOOL_PREFIX
#: Fixed key set of one approvals.jsonl line.
LOG_KEYS = {
    "turn",
    "persona",
    "mechanism",
    "tool",
    "operation",
    "decision",
    "reason",
    "brief_event_id",
    "cost_amount",
    "cost_unit",
    "spent_credits",
}
#: Synthetic persona exercising every deny path (the shipped personas approve everything).
CAUTIOUS = PersonaRule(
    persona="cautious",
    approve_operations=("trainings_*", "versions_*", "projects_*"),
    deny_operations=("*delete*",),
    spend_cap_credits=8.0,
    unstated_cost=Decision.DENY,
)
#: Like CAUTIOUS but approving every operation, to show a read is not answered by `unstated_cost`.
CAUTIOUS_READS = replace(CAUTIOUS, approve_operations=("*",))
DENY_READS = replace(CAUTIOUS_READS, deny_operations=("projects_*",))
#: Clock for brief-freshness checks: two hours after the `ts` that `brief_row` writes.
NOW = datetime(2026, 11, 10, 12, 0, tzinfo=timezone.utc)
NO_PROMPT_MODES = {"bypassPermissions", "dontAsk"}


def check(label: str, got: object, want: object) -> None:
    """Raise with a readable diff when ``got != want`` (survives ``python -O``)."""
    if got != want:
        raise AssertionError(f"{label}: got {got!r}, want {want!r}")


def brief_row(operation: str, event_id: str, cost: float | None = 5, unit: str = "credits") -> dict[str, Any]:
    """Ledger row in the gate's brief shape."""
    fields: dict[str, Any] = {
        "scope": "train on 3 photos",
        "cost_unit": unit,
        "cost_source": "mock price list",
        "cost_as_of": "2026-11-10",
        "data_movement": "none",
        "rollback": "delete the model",
    }
    if cost is not None:
        fields["cost_amount"] = cost
    return {
        "action": "action_brief_emitted",
        "status": "success",
        "operation": operation,
        "event_id": event_id,
        "ts": "2026-11-10T10:00:00Z",
        "brief": fields,
    }


def approved_row(event_id: str, cost: float, unit: str = "credits") -> dict[str, Any]:
    """Earlier approvals.jsonl line that approved a brief."""
    return {"decision": "allow", "brief_event_id": event_id, "cost_amount": cost, "cost_unit": unit}


def shipped_rule(name: str) -> PersonaRule:
    """Load a shipped persona's approver rule."""
    return PersonaRule.from_persona(yaml.safe_load((AB / "personas" / f"{name}.yaml").read_text()))


def check_doctests() -> None:
    """Run the Examples sections of approver.py."""
    result = doctest.testmod(approver)
    check("approver doctest failures", result.failed, 0)
    check("approver has doctests", result.attempted > 0, True)


def check_persona_blocks() -> None:
    """Both shipped personas encode 'approve when asked' with no cap (their text names no number)."""
    for name in ("scripted", "roleplay"):
        rule = shipped_rule(name)
        check(f"{name} approve_operations", rule.approve_operations, ("*",))
        check(f"{name} deny_operations", rule.deny_operations, ())
        check(f"{name} spend cap", rule.spend_cap_credits, None)
        check(f"{name} unstated_cost", rule.unstated_cost, Decision.ALLOW)
        check(f"{name} round-trip", PersonaRule.from_persona(rule.to_json()), rule)
    for bad, label in (
        ({"name": "x"}, "missing block"),
        ({"name": "x", "approver": {**CAUTIOUS.to_json()["approver"], "unstated_cost": "maybe"}}, "bad unstated"),
        ({"name": "x", "approver": {**CAUTIOUS.to_json()["approver"], "spend_cap_credits": -1}}, "negative cap"),
        ({"name": "x", "approver": {**CAUTIOUS.to_json()["approver"], "approve_operations": "*"}}, "patterns str"),
    ):
        try:
            PersonaRule.from_persona(bad)
        except ValueError:
            continue
        raise AssertionError(f"PersonaRule.from_persona accepted {label}")


def verdict(tool: str, rule: PersonaRule, ledger: list[dict], log: list[dict], **kw: Any) -> approver.Verdict:
    """Decide one prompt with an empty tool input, two hours after `brief_row` rows were written."""
    return approver.decide(PromptRequest(tool, {"project_id": "p"}, **kw), rule, ledger, log, now=NOW)


def check_approve_and_deny_paths() -> None:
    """Persona operation rules and the stated-cost approve path."""
    ledger = [brief_row("trainings_create", "e1", 5)]
    got = verdict(f"{MOCK}trainings_create", CAUTIOUS, ledger, [])
    check("approve: decision", got.decision, Decision.ALLOW)
    check("approve: brief id", got.brief.event_id if got.brief else None, "e1")
    check("approve: spent after", got.spent_credits, 5.0)
    got = verdict(f"{MOCK}projects_delete", CAUTIOUS, [brief_row("projects_delete", "d1", 0)], [])
    check("deny_operations: decision", got.decision, Decision.DENY)
    check("deny_operations: reason", "deny_operations" in got.reason, True)
    got = verdict(f"{MOCK}image_upload", CAUTIOUS, [brief_row("image_upload", "u1", 0)], [])
    check("not approved: decision", got.decision, Decision.DENY)
    check("not approved: reason", "approve_operations" in got.reason, True)
    # the shipped personas approve a large stated cost: their text sets no cap
    for name in ("scripted", "roleplay"):
        big = [brief_row("trainings_create", "big", 500)]
        check(
            f"{name}: approves 500 credits",
            verdict(f"{MOCK}trainings_create", shipped_rule(name), big, []).decision,
            Decision.ALLOW,
        )
    # the latest brief for the exact operation is the one the prompt shows
    ledger = [
        brief_row("trainings_create", "old", 1),
        brief_row("trainings_create", "new", 7),
        brief_row("versions_generate", "other", 2),
        {**brief_row("trainings_create", "failed", 3), "status": "failed"},
    ]
    got = verdict(f"{MOCK}trainings_create", CAUTIOUS, ledger, [])
    check("latest brief wins", (got.brief.event_id if got.brief else None, got.spent_credits), ("new", 7.0))
    # as in the gate, a later brief without a cost never displaces an earlier one with a cost
    ledger = [brief_row("trainings_create", "complete", 4), brief_row("trainings_create", "no-cost", None)]
    got = verdict(f"{MOCK}trainings_create", CAUTIOUS, ledger, [])
    check(
        "incomplete later brief ignored",
        (got.decision, got.brief.event_id if got.brief else None),
        (Decision.ALLOW, "complete"),
    )


def check_brief_matches_gate() -> None:
    """The approver weighs the brief the gate shows: a cheaper row the gate rejects never replaces it."""
    shown = brief_row("trainings_create", "shown", 100)
    cheap = brief_row("trainings_create", "cheap", 1)
    incomplete = {**cheap, "brief": {**cheap["brief"], "rollback": ""}}
    stale = {**cheap, "ts": "2026-11-08T10:00:00Z"}
    ahead = {**cheap, "ts": "2026-11-10T13:00:00Z"}
    old_price = {**cheap, "brief": {**cheap["brief"], "cost_as_of": "2026-01-01"}}
    for label, later in (("incomplete", incomplete), ("stale", stale), ("future", ahead), ("old price", old_price)):
        got = verdict(f"{MOCK}trainings_create", CAUTIOUS, [shown, later], [])
        check(
            f"{label} later cheap brief: cap applies to the shown brief",
            (got.decision, got.brief.event_id if got.brief else None),
            (Decision.DENY, "shown"),
        )
        alone = verdict(f"{MOCK}trainings_create", CAUTIOUS, [later], [])
        check(f"{label} brief alone: no brief to weigh", (alone.decision, alone.brief), (Decision.DENY, None))
    # a budget operation's brief needs a call budget, as in the gate
    infer = brief_row("models_infer", "infer", 2)
    check("budget brief without call_budget", verdict(f"{MOCK}models_infer", CAUTIOUS_READS, [infer], []).brief, None)
    budgeted = {**infer, "brief": {**infer["brief"], "call_budget": 40}}
    got = verdict(f"{MOCK}models_infer", CAUTIOUS_READS, [budgeted], [])
    check("budget brief with call_budget", (got.decision, got.spent_credits), (Decision.ALLOW, 2.0))
    # a read-only operation is approved without a brief, even by a persona that denies an unstated cost
    got = verdict(f"{MOCK}projects_list", CAUTIOUS_READS, [], [])
    check("read-only: allowed without a brief", (got.decision, "read-only" in got.reason), (Decision.ALLOW, True))
    check(
        "read-only: persona deny_operations still wins",
        verdict(f"{MOCK}projects_list", DENY_READS, [], []).decision,
        Decision.DENY,
    )


def check_spend_cap() -> None:
    """Cumulative cap over distinct approved briefs; a repeat of an approved brief adds nothing."""
    ledger = [brief_row("trainings_create", "e2", 5)]
    over = verdict(f"{MOCK}trainings_create", CAUTIOUS, ledger, [approved_row("e1", 5)])
    check("cap: 5 + 5 > 8 denied", over.decision, Decision.DENY)
    check("cap: reason names cap", "cap 8" in over.reason, True)
    check("cap: spent unchanged", over.spent_credits, 5.0)
    at_cap = verdict(
        f"{MOCK}trainings_create", CAUTIOUS, [brief_row("trainings_create", "e3", 3)], [approved_row("e1", 5)]
    )
    check("cap: 5 + 3 == 8 allowed", (at_cap.decision, at_cap.spent_credits), (Decision.ALLOW, 8.0))
    repeat = verdict(f"{MOCK}trainings_create", CAUTIOUS, ledger, [approved_row("e1", 5), approved_row("e2", 5)])
    check("cap: repeat of approved brief allowed", repeat.decision, Decision.ALLOW)
    check("cap: repeat adds no spend", repeat.spent_credits, 10.0)
    denied_before = verdict(
        f"{MOCK}trainings_create",
        CAUTIOUS,
        [brief_row("trainings_create", "e4", 2)],
        [approved_row("e1", 5), {**approved_row("e9", 50), "decision": "deny"}],
    )
    check(
        "cap: denied briefs do not count", (denied_before.decision, denied_before.spent_credits), (Decision.ALLOW, 7.0)
    )


def check_missing_brief() -> None:
    """No brief, or a cost not in credits, gets the persona's unstated_cost answer."""
    got = verdict(f"{MOCK}versions_generate", CAUTIOUS, [], [])
    check("no brief: cautious denies", (got.decision, got.brief), (Decision.DENY, None))
    check("no brief: reason", "no action brief" in got.reason, True)
    check(
        "no brief: scripted allows",
        verdict(f"{MOCK}versions_generate", shipped_rule("scripted"), [], []).decision,
        Decision.ALLOW,
    )
    usd = [brief_row("trainings_create", "usd", 2, unit="USD")]
    got = verdict(f"{MOCK}trainings_create", CAUTIOUS, usd, [])
    check("USD cost: unstated rule", (got.decision, got.brief.event_id if got.brief else None), (Decision.DENY, "usd"))
    no_amount = [brief_row("trainings_create", "blank", None)]
    check(
        "no cost_amount: unstated rule",
        verdict(f"{MOCK}trainings_create", CAUTIOUS, no_amount, []).decision,
        Decision.DENY,
    )


def check_passthrough_and_safety() -> None:
    """Non-Roboflow tools pass through; a non-mock Roboflow server is never approved."""
    scripted = shipped_rule("scripted")
    for tool in ("Read", "Skill", "mcp__github__get_issue", "mcp__approver__approve"):
        got = verdict(tool, scripted, [], [])
        check(f"{tool}: passthrough", got.decision, Decision.PASSTHROUGH)
        check(f"{tool}: hook gives no decision", approver.hook_output(got), None)
        check(f"{tool}: prompt-tool denies", approver.prompt_tool_output(got, {})["behavior"], "deny")
    ledger = [brief_row("trainings_create", "e1", 1)]
    real = verdict("mcp__plugin_sentinel_roboflow__trainings_create", scripted, ledger, [])
    check("plugin-namespaced tool: denied", real.decision, Decision.DENY)
    check("plugin-namespaced tool: reason", real.reason.startswith("harness safety"), True)
    plugin_source = verdict(f"{MOCK}trainings_create", scripted, ledger, [], mcp_source="plugin")
    check("plugin-sourced server: denied", plugin_source.decision, Decision.DENY)


def check_outputs_and_log_shape() -> None:
    """Hook / prompt-tool output shapes and the fixed log-line key set."""
    allow = approver.Verdict(
        f"{MOCK}trainings_create", "trainings_create", Decision.ALLOW, "ok", approver.Brief("e1", 5.0, "credits"), 5.0
    )
    deny = approver.Verdict(f"{MOCK}projects_delete", "projects_delete", Decision.DENY, "no")
    check(
        "hook allow",
        approver.hook_output(allow),
        {"hookSpecificOutput": {"hookEventName": "PermissionRequest", "decision": {"behavior": "allow"}}},
    )
    check(
        "hook deny",
        approver.hook_output(deny),
        {
            "hookSpecificOutput": {
                "hookEventName": "PermissionRequest",
                "decision": {"behavior": "deny", "message": "no"},
            }
        },
    )
    check(
        "prompt-tool allow",
        approver.prompt_tool_output(allow, {"a": 1}),
        {"behavior": "allow", "updatedInput": {"a": 1}},
    )
    check("prompt-tool deny", approver.prompt_tool_output(deny, {}), {"behavior": "deny", "message": "no"})
    row = allow.as_log_row("scripted", Mechanism.HOOK, 2)
    check("log keys", set(row), LOG_KEYS)
    check(
        "log values", (row["brief_event_id"], row["cost_amount"], row["decision"], row["turn"]), ("e1", 5.0, "allow", 2)
    )
    no_brief = deny.as_log_row("scripted", Mechanism.HOOK, 0)
    check("log keys without brief", set(no_brief), LOG_KEYS)
    check("log brief fields null", (no_brief["brief_event_id"], no_brief["cost_amount"]), (None, None))


def check_project_resolution() -> None:
    """Ledger lookup mirrors the gate: CLAUDE_PROJECT_DIR, then hook cwd, then the workspace; never walks up."""
    workspace, cwd, declared = Path("/w"), "/c", "/declared"
    check("env first", approver.resolve_project_dir({"CLAUDE_PROJECT_DIR": declared}, cwd, workspace), Path(declared))
    check("cwd second", approver.resolve_project_dir({}, cwd, workspace), Path(cwd))
    check("workspace last", approver.resolve_project_dir({}, None, workspace), workspace)
    check(
        "relative env ignored", approver.resolve_project_dir({"CLAUDE_PROJECT_DIR": "rel"}, None, workspace), workspace
    )


def make_run(root: Path, rule: PersonaRule, mechanism: Mechanism) -> tuple[Path, Path, Path]:
    """Synthetic run dir + workspace with one brief; return (config path, run dir, workspace)."""
    run_dir, workspace = root / "run", root / "run" / "workspace"
    (workspace / ".vision-delivery").mkdir(parents=True)
    # The subprocess approver judges freshness against the real clock, so the brief is dated now; a fixed date goes
    # stale (24 h brief age, 90 d price age) and flips the decision.
    now = datetime.now(timezone.utc)
    row = brief_row("trainings_create", "evt-7", 5)
    row["ts"] = now.strftime("%Y-%m-%dT%H:%M:%SZ")
    row["brief"]["cost_as_of"] = now.date().isoformat()
    rows = [row]
    (workspace / ".vision-delivery" / "ledger.jsonl").write_text("".join(json.dumps(r) + "\n" for r in rows))
    (run_dir / "current_turn.txt").write_text("3")
    config = approver.ApproverConfig(rule, mechanism, workspace, run_dir)
    path = run_dir / approver.CONFIG_FILE
    path.write_text(json.dumps(config.to_json()))
    check("config round-trip", approver.ApproverConfig.load(path), config)
    return path, run_dir, workspace


def child_env(project: Path | None) -> dict[str, str]:
    """Environment for an approver subprocess, with CLAUDE_PROJECT_DIR controlled by the test."""
    env = {k: v for k, v in os.environ.items() if k != "CLAUDE_PROJECT_DIR"}
    if project is not None:
        env["CLAUDE_PROJECT_DIR"] = str(project)
    return env


def run_approver(args: list[str], stdin: str, env: dict[str, str]) -> str:
    """Run approver.py as the host would; return stdout."""
    res = subprocess.run(
        [sys.executable, str(AB / "approver.py"), *args],
        input=stdin,
        capture_output=True,
        text=True,
        timeout=30,
        env=env,
        check=True,
    )
    return res.stdout


def check_hook_subprocess(root: Path) -> None:
    """``PermissionRequest`` hook end-to-end: stdin payload in, decision JSON out, one log line per call."""
    config, run_dir, workspace = make_run(root / "hook", shipped_rule("scripted"), Mechanism.HOOK)
    payload = {
        "session_id": "s",
        "cwd": str(workspace),
        "permission_mode": "default",
        "hook_event_name": "PermissionRequest",
        "tool_name": f"{MOCK}trainings_create",
        "tool_input": {"project_id": "p", "version_number": 1},
        "mcp_server": {"name": "roboflow", "source": "dynamic"},
    }
    out = json.loads(run_approver(["hook", "--config", str(config)], json.dumps(payload), child_env(workspace)))
    check(
        "hook stdout",
        out,
        {"hookSpecificOutput": {"hookEventName": "PermissionRequest", "decision": {"behavior": "allow"}}},
    )
    passthrough = run_approver(
        ["hook", "--config", str(config)], json.dumps({**payload, "tool_name": "Read"}), child_env(None)
    )
    check("hook non-Roboflow stdout", passthrough, "")
    unreadable = json.loads(run_approver(["hook", "--config", str(config)], "not json", child_env(None)))
    check("hook unreadable input", unreadable["hookSpecificOutput"]["decision"]["behavior"], "deny")
    rows = approver.read_jsonl(run_dir / approver.LOG_FILE)
    check("hook log line count", len(rows), 3)
    check("hook log keys", [set(r) for r in rows], [LOG_KEYS] * 3)
    check("hook log unreadable deny", (rows[2]["tool"], rows[2]["decision"]), ("", "deny"))
    first = rows[0]
    check(
        "hook log first line",
        {k: first[k] for k in ("turn", "persona", "mechanism", "tool", "operation", "decision", "brief_event_id")},
        {
            "turn": 3,
            "persona": "scripted",
            "mechanism": "hook",
            "tool": f"{MOCK}trainings_create",
            "operation": "trainings_create",
            "decision": "allow",
            "brief_event_id": "evt-7",
        },
    )
    check("hook log passthrough", (rows[1]["tool"], rows[1]["decision"]), ("Read", "passthrough"))


def check_mcp_subprocess(root: Path) -> None:
    """Permission-prompt MCP server end-to-end over stdio (contract unverified against a live host)."""
    config, run_dir, workspace = make_run(root / "mcp", CAUTIOUS, Mechanism.PROMPT_TOOL)
    call = {"name": approver.PROMPT_TOOL_NAME, "arguments": {"tool_name": f"{MOCK}trainings_create", "input": {"x": 1}}}
    messages = [
        {"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {"protocolVersion": "2025-06-18"}},
        {"jsonrpc": "2.0", "method": "notifications/initialized"},
        {"jsonrpc": "2.0", "id": 2, "method": "tools/list"},
        {"jsonrpc": "2.0", "id": 3, "method": "tools/call", "params": call},
        {
            "jsonrpc": "2.0",
            "id": 4,
            "method": "tools/call",
            "params": {**call, "arguments": {"tool_name": "Bash", "input": {}}},
        },
        {"jsonrpc": "2.0", "id": 5, "method": "resources/list"},
    ]
    stdin = "".join(json.dumps(m) + "\n" for m in messages)
    responses = {
        r["id"]: r
        for r in map(
            json.loads, run_approver(["mcp", "--config", str(config)], stdin, child_env(workspace)).splitlines()
        )
    }
    check("mcp response ids (notification unanswered)", sorted(responses), [1, 2, 3, 4, 5])
    check("mcp initialize echoes protocol", responses[1]["result"]["protocolVersion"], "2025-06-18")
    check("mcp tools/list", [t["name"] for t in responses[2]["result"]["tools"]], [approver.PROMPT_TOOL_NAME])
    body = json.loads(responses[3]["result"]["content"][0]["text"])
    check("mcp allow body", body, {"behavior": "allow", "updatedInput": {"x": 1}})
    check("mcp non-Roboflow denied", json.loads(responses[4]["result"]["content"][0]["text"])["behavior"], "deny")
    check("mcp unknown method", responses[5]["error"]["code"], -32601)
    rows = approver.read_jsonl(run_dir / approver.LOG_FILE)
    check(
        "mcp log",
        [(r["mechanism"], r["decision"]) for r in rows],
        [("prompt-tool", "allow"), ("prompt-tool", "passthrough")],
    )


def setup_for(arm: str, mechanism: Mechanism, settings: Path | None = None) -> runner.TurnSetup:
    """Turn setup with fixed paths."""
    return runner.TurnSetup(arm, "sonnet", Path("/run/mcp.json"), Path("/run/workspace"), mechanism, settings)


def check_runner_commands() -> None:
    """Exact argv per arm and mechanism: Manual mode in both arms, arms differ only by --plugin-dir."""
    settings = Path("/run/approver-settings.json")
    expected_hook_p = [
        "claude",
        "--model",
        "sonnet",
        "--setting-sources",
        "project",
        "--output-format",
        "json",
        "--mcp-config",
        "/run/mcp.json",
        "--strict-mcp-config",
        "--permission-mode",
        "default",
        "--allowedTools",
        "Skill,Read",
        "--max-turns",
        "15",
        "--settings",
        str(settings),
        "--plugin-dir",
        str(ROOT),
        "-p",
        "hi",
    ]
    check("hook P argv", runner.build_claude_cmd("hi", setup_for("P", Mechanism.HOOK, settings), None), expected_hook_p)
    expected_hook_b = [a for a in expected_hook_p if a not in ("--plugin-dir", str(ROOT))]
    check("hook B argv", runner.build_claude_cmd("hi", setup_for("B", Mechanism.HOOK, settings), None), expected_hook_b)
    resumed = runner.build_claude_cmd("hi", setup_for("B", Mechanism.HOOK, settings), "sess-1")
    check("resume flag", resumed[-4:], ["--resume", "sess-1", "-p", "hi"])
    for mechanism in Mechanism:
        cmds = {arm: runner.build_claude_cmd("hi", setup_for(arm, mechanism, settings), None) for arm in ("P", "B")}
        for arm, cmd in cmds.items():
            mode = cmd[cmd.index("--permission-mode") + 1]
            check(f"{mechanism.value} {arm}: permission mode", mode, "default")
            check(f"{mechanism.value} {arm}: no prompt-less mode", NO_PROMPT_MODES & set(cmd), set())
            check(f"{mechanism.value} {arm}: no skip flag", "--dangerously-skip-permissions" in cmd, False)
            check(f"{mechanism.value} {arm}: --settings", "--settings" in cmd, mechanism == Mechanism.HOOK)
            check(
                f"{mechanism.value} {arm}: prompt tool",
                "--permission-prompt-tool" in cmd,
                mechanism == Mechanism.PROMPT_TOOL,
            )
            roboflow_allowed = "mcp__roboflow__*" in cmd[cmd.index("--allowedTools") + 1]
            check(f"{mechanism.value} {arm}: Roboflow allow rule", roboflow_allowed, mechanism == Mechanism.OFF)
        p_only = [a for a in cmds["P"] if a not in cmds["B"]]
        check(f"{mechanism.value}: arms differ only by plugin dir", p_only, ["--plugin-dir", str(ROOT)])
    prompt_tool = runner.build_claude_cmd("hi", setup_for("P", Mechanism.PROMPT_TOOL), None)
    check("prompt-tool name", prompt_tool[prompt_tool.index("--permission-prompt-tool") + 1], "mcp__approver__approve")


def check_runner_files(root: Path) -> None:
    """Files the runner writes per mechanism: approver.json, the hook settings, the MCP server entry."""
    persona = yaml.safe_load((AB / "personas" / "scripted.yaml").read_text())
    gate_hooks = json.loads((ROOT / "hooks" / "claude-hooks.json").read_text())
    gate_matcher = gate_hooks["hooks"]["PreToolUse"][0]["matcher"]
    for mechanism in Mechanism:
        run_dir = root / f"files-{mechanism.value}"
        run_dir.mkdir()
        settings = runner.prepare_approver(run_dir, run_dir / "workspace", persona, mechanism)
        config_path = run_dir / approver.CONFIG_FILE
        check(f"{mechanism.value}: approver.json written", config_path.exists(), mechanism != Mechanism.OFF)
        check(f"{mechanism.value}: settings path", settings is not None, mechanism == Mechanism.HOOK)
        servers = runner.mcp_servers(run_dir, mechanism)["mcpServers"]
        check(
            f"{mechanism.value}: mcp servers",
            sorted(servers),
            sorted(["roboflow", "approver"] if mechanism == Mechanism.PROMPT_TOOL else ["roboflow"]),
        )
        if mechanism == Mechanism.OFF:
            continue
        config = approver.ApproverConfig.load(config_path)
        check(
            f"{mechanism.value}: config",
            (config.rule, config.mechanism, config.project_dir),
            (shipped_rule("scripted"), mechanism, run_dir / "workspace"),
        )
    hook_settings = json.loads((root / "files-hook" / runner.APPROVER_SETTINGS_FILE).read_text())
    (entry,) = hook_settings["hooks"]["PermissionRequest"]
    check("settings matcher equals gate matcher", entry["matcher"], gate_matcher)
    (hook,) = entry["hooks"]
    check("settings hook exec form", (hook["type"], hook["command"]), ("command", sys.executable))
    check(
        "settings hook args",
        hook["args"],
        [str(AB / "approver.py"), "hook", "--config", str(root / "files-hook" / approver.CONFIG_FILE)],
    )
    try:
        runner.prepare_approver(root / "files-off", root, {"name": "bare"}, Mechanism.HOOK)
    except ValueError:
        return
    raise AssertionError("prepare_approver accepted a persona without an approver: block")


def main() -> int:
    """Run every approver check; raise AssertionError on the first mismatch."""
    check_doctests()
    check_persona_blocks()
    check_approve_and_deny_paths()
    check_brief_matches_gate()
    check_spend_cap()
    check_missing_brief()
    check_passthrough_and_safety()
    check_outputs_and_log_shape()
    check_project_resolution()
    check_runner_commands()
    with tempfile.TemporaryDirectory() as tmp:
        check_hook_subprocess(Path(tmp))
        check_mcp_subprocess(Path(tmp))
        check_runner_files(Path(tmp))
    print("A/B approver assertions passed (decision paths, log shape, hook + prompt-tool subprocesses, runner argv)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
