---
description: How Sentinel's Claude Code paid-action gate separates tool policy, action briefs, and host permission prompts, with Roboflow-specific boundaries.
title: Paid-Action Gate Pattern
---

# Paid-Action Gate Pattern

Sentinel's paid-action gate is a host `PreToolUse` hook in Claude Code (`hooks/gate.js`). It asks before a paid or state-changing Roboflow MCP tool call, and only after a structured action brief has been recorded in the project ledger. Without a valid brief it denies the call. The pattern separates tool classification, a recorded explanation of the proposed action, and the host's permission prompt. Read-only calls and an explicit call-budget exception have different handling, described below.

## Policy from tool annotations

`scripts/build_gate_policy.py` generates `hooks/gate-policy.json` from a published tool catalog and reviewed rules in `scripts/gate_policy_rules.json`. It treats only `readOnlyHint: true` as read-only; false or missing annotations produce the fail-closed `brief` class. The builder does not use `destructiveHint` to classify tools. It does not infer safety from a tool's name or treat a non-destructive hint as evidence that a call is free.

The policy file format is provider-neutral. `schema_version` identifies the format, `provider` names the provider, `default_class` records `brief`, `overrides` records tool-specific classes and written reasons, and `source` records catalog provenance. The `tools` table holds each operation's class, read-only flag, and reporting category. Categories do not decide whether a call is gated.

`hooks/roboflow-ops.js` looks up the exact operation name. An unknown tool name or unknown class is treated as `brief`. An `open` entry also needs `read_only: true`; changing the class alone does not open a write tool. Explicit overrides cover read-only tools that bill. The generator refuses an override that opens a tool without the provider's read-only flag.

| Class    | Gate behavior                                                                                                  |
| -------- | -------------------------------------------------------------------------------------------------------------- |
| `open`   | No brief required; the gate emits no permission decision.                                                      |
| `brief`  | One recorded brief per execution; a valid brief leads to `ask`.                                                |
| `budget` | A recorded brief includes a call budget; the first call is asked, with later calls handled as described below. |

## Briefs and ledger

`scripts/ledger_append.py` records a successful `action_brief_emitted` row for an exact operation, without the MCP server prefix. Its structured brief contains `scope`, `cost_amount` (a finite, nonnegative upper estimate), `cost_unit`, `cost_source`, `cost_as_of` (the price-source date), `data_movement`, and `rollback`. A budget operation also requires `call_budget`. Notes alone do not satisfy the gate.

`hooks/gate.js` accepts a complete brief for up to 24 hours and requires a cost-source date no more than 90 days old. For a `brief` operation, one recorded execution uses it up; an unknown outcome also consumes it. A host-reported failed or cancelled call leaves it open, but the next prompt warns that the provider may already have started work. This depends on recorded lifecycle events, not independent provider receipts.

The project ledger is `.vision-delivery/ledger.jsonl`. It holds briefs, selected host-reported call outcomes, and budget reservations. `scripts/ledger_report.py` reads it to report metrics and brief states; its status view is read-only. As `docs/trust.md` explains, coverage is best-effort: missing host events can leave an incomplete history. A row is neither an authorization receipt nor proof that an action succeeded.

For budget operations, every attempt reaching the budget reservation step takes a unit, including attempts with no recorded outcome. After one call has run, later calls inside the budget receive no gate decision and follow normal host permission rules. In `auto` mode every gated call is asked. In `bypassPermissions` and `dontAsk`, gated calls are denied. The gate never returns `allow`: its explicit decisions are only `ask` or `deny`, and some paths emit no decision. A call budget counts calls, not credits, and does not cap spend.

## Roboflow-specific choices

`hooks/roboflow-ops.js` and the matcher in `hooks/claude-hooks.json` recognize MCP server names containing `roboflow`, case-insensitively. The prefixes documented in `docs/roboflow-skills.md` are `mcp__roboflow__`, `mcp__plugin_sentinel_roboflow__`, `mcp__plugin_roboflow_roboflow__`, and connector names such as `mcp__claude_ai_Roboflow__`. The operation after the prefix keys the brief across these names. A server registered under a name without `roboflow` is outside the gate.

The three overrides in `hooks/gate-policy.json` are provider-specific judgments:

- `media_analyze` is read-only upstream but its description says calls cost workspace credits, and it accepts video as well as images. It needs one brief per execution.
- `models_infer` is read-only upstream but the upstream inference skill lists serverless inference as billed per inference. Its single-image calls use a brief with a stated call budget.
- `autolabel_preview` is a single-image preview that upstream describes as spending no credits but being rate-limited per workspace. A call-budget brief keeps the preview loop usable.

These are the policy's recorded reasons, not a fresh pricing verification. Video analysis, batch jobs, Workflow runs, and endpoint runs do not use the budget exception.

The policy records catalog `roboflow-cowork-tools.json`, release `cowork-catalog-2c8dbbd`, as of `2026-11-10`, with 306 tools and pinned catalog SHA-256 `2d83db464b2af5e85b70e72e11a76a3b46628f4b17d22d31c276d0705a43347d`. A separate `source.flags_sha256` detects changes to recorded read-only flags. These digests do not authenticate local files.

`docs/release-policy.md` requires downloading the current published catalog, regenerating with `scripts/build_gate_policy.py` using `--catalog`, `--release`, `--as-of`, and `--expect-sha256`, reviewing changed tools, flags, and override reasons, then running `make eval-upstream` with the catalog and upstream skill clone supplied. Reapplying rules to recorded flags alone does not refresh the catalog.

## Adapting it

The repository suggests four pieces a developer would need to produce for another annotated MCP server. This is a description of the existing design, not a tested porting procedure.

1. A catalog with exact operation names and tool annotations. `scripts/build_gate_policy.py` reads those names and `readOnlyHint`, defaults missing hints to gated, and records a catalog digest.
2. A policy file and reviewed override reasons. `hooks/gate-policy.json` separates provider identity and source provenance from classes; `scripts/gate_policy_rules.json` supplies the current provider's exceptions and reporting categories.
3. A host matcher and operation-name extraction rule. `hooks/claude-hooks.json` and `hooks/roboflow-ops.js` currently agree on Roboflow server names, including plugin and connector prefixes.
4. A brief schema and ledger lifecycle. `scripts/ledger_append.py`, `hooks/gate.js`, and `scripts/ledger_report.py` share the structured fields, per-execution consumption, budget exception, and outcome interpretation.

## Limits and status

Only the Roboflow server has been used; no second server has been tried. The gate covers MCP tool calls in Claude Code only. SDK, CLI, or REST calls made from scripts do not reach it, and Codex has no corresponding spend gate.

The offline contracts in `evals/hooks/assert_gate_policy.py` check policy generation, defaults, overrides, digest checks, and drift. `evals/hooks/gate_smoke.mjs` exercises gate decisions with fixture briefs and outcomes, including unknown tools, consumed briefs, permission modes, and concurrent budget reservations. `evals/hooks/matcher_topology.mjs` checks matcher agreement on supplied tool names; `evals/hooks/cta_smoke.mjs` checks ledger-hook handling of supplied host events. These checks do not prove live host naming, matcher behavior, or another server's integration.

Hooks are not signed or authenticated. The agent writes the brief, and local processes can alter the hook, policy, or ledger. This guards against agent drift and overclaiming, not a malicious local user. The gate checks field structure, not the truth of a cost estimate. Host approvals, account permissions, and provider budgets remain necessary controls.

This page explains a pattern. It is not packaged or supported as a reusable component, and reuse as a product remains parked. The provider-neutral policy format is not evidence that the implementation works for other servers.
