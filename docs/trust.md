---
description: Sentinel credentials, data flow, permissions, paid-action consent, ledger semantics, sensitive-use gates, and evidence limits.
title: Trust And Safety
---

# Trust And Safety

Sentinel is an agent workflow with project tools and a third-party MCP service. It is not a security boundary, authorization system, or autonomous production approver.

## Authentication and data flow

- Plugin installation uses a URL-only MCP configuration; no credential environment variable is required.
- Codex metadata requests authorization on use. Verify the actual host-managed sign-in, account, and authorization scope before live work.
- Never paste authentication tokens or other credentials into chat or commit them.
- MCP calls can send task data to Roboflow. Confirm the allowed purpose before using private or sensitive media.
- Credentials for a generated standalone client are separate from plugin installation and must follow current official Roboflow guidance.

## Permissions

Skills can request project reads, writes, edits, searches, and shell commands. The shared Codex and Claude hook can read host event payloads, append a local ledger, and read that ledger for event deduplication. Codex requires review and trust for changed plugin hooks; use `/hooks` to inspect the exact definition. A bounded diagnostic may be written under the host-managed plugin-data directory on malformed hook input; it records only a timestamp and fixed error code, never the payload, credentials, or raw error text. Review host permission prompts and generated commands; installing the plugin does not confine those capabilities to a separate sandbox.

## Paid actions

Sentinel stops before uploads, dataset mutation, paid training, deployment, deletion, and other state-changing provider actions. It states the action, rationale, expected cost/data movement, target, and evidence, then hands execution to a host/provider control that can enforce approval. Conversational approval does not authorize Sentinel itself to invoke the action.

On Claude Code part of that control is Sentinel's own `PreToolUse` gate (`hooks/gate.js`):

- It checks each Roboflow MCP call against a policy generated from Roboflow's published tool catalog (`hooks/gate-policy.json`). Tools Roboflow marks read-only pass, except two that are billed per call (`models_infer`, `media_analyze`).
- Every other tool, and any tool the policy does not list, is denied until a structured action brief is recorded in the project ledger: scope, an upper cost estimate with its source and a date no more than 90 days old, data movement, and rollback. The call then goes to the host permission prompt, which shows those fields in quotes. The gate never returns `allow`.
- One brief covers one execution. A call the host reports as failed or cancelled leaves the brief open, and the next prompt warns that the provider may already have started the work.
- Two single-image tools are the exception (`models_infer`, `autolabel_preview`): one brief states a call budget. You see the prompt until one call has run; later calls inside the budget follow your normal host permission rules. Every attempt that reaches the gate takes one unit of the budget, whether or not it ran, and a call past the budget is denied. Video analysis, batch jobs, and Workflow or endpoint runs never run under a budget.
- In `bypassPermissions` and `dontAsk` modes gated calls are denied, because the host shows no prompt there. In `auto` mode the gate returns `ask` for every gated call, including each call inside a budget.

**What the gate does not cover.**

- Anything that is not an MCP tool call. A Roboflow SDK, CLI, or REST call made from a shell command or a generated script never reaches the gate, and neither does any other provider. Those calls are governed only by the host's shell permission prompt, your credentials, and your account budget.
- A Roboflow server under another name. The hooks match any MCP server whose name contains `roboflow` in any letter case: the bare server, one provided by a plugin, or a connector. The same server registered under a name without `roboflow` (for example `rf`) is not gated at all.
- The truth of the brief. The agent that wants to make the call writes the brief. The gate checks that every field is present and well formed, not that the estimate is right. Read the prompt before you approve.
- Spend. The gate does not cap or meter credits. A call budget counts calls, not credits.
- Later calls inside a budget, outside `auto` mode. Once one call under a budget brief has run, the gate gives no decision for the rest of that budget. If your host rules allow the tool, those calls run without a prompt.
- Tampering. The gate reads a ledger file and a policy file that any local process can write. An edit that only marks a tool open stays gated, and the repository checks catch a changed read-only flag, but an edit that rewrites the policy and its recorded digest together is caught only when the policy is compared with Roboflow's catalog at release time.
- Tool names it has never seen. The policy is generated from the catalog Roboflow publishes for another host surface. A tool that reaches Claude Code under a name the policy does not list is treated as gated, which is safe but may block a harmless read until the policy is regenerated.

Use host approvals, least-privilege account authorization or sessions, account budgets, and non-production targets as the real control. A separately generated standalone client may require a provider key; follow current provider guidance and scope it to the minimum permissions. Read-only discovery still depends on host and upstream behavior; inspect permission prompts.

## Ledger semantics

Selected Roboflow tool lifecycle events can be appended to:

```text
.vision-delivery/ledger.jsonl
```

Where the host exposes a lifecycle result, records can distinguish successful, failed, cancelled, or unknown outcomes and use stable event IDs for deduplication. This remains best-effort: hosts may omit events, disable hooks, or change payloads, and skill-side writes are not guaranteed.

A ledger row is not proof from Roboflow, complete telemetry, an authorization receipt, or evidence that a generated artifact works. Project/workspace slugs and notes can still be sensitive. Ignore the directory in version control, minimize identifiers, inspect before sharing, and apply a retention policy.

## Sensitive-use gate

Before faces, license plates, people tracking, forms, medical images, worker monitoring, minors, or location-linked media are uploaded or analyzed, require:

1. documented authority and allowed purpose,
2. minimum necessary data and retention,
3. controlled access and incident ownership,
4. representative evaluation and relevant subgroup checks,
5. explicit false-positive/false-negative consequences,
6. named human review and appeal/override,
7. appropriate legal, privacy, security, and domain review.

Do not use Sentinel alone for medical, employment, law-enforcement, access-control, or physical-safety decisions.

## Evidence and generated outputs

- B1 is a small private detection fixture; B2-B5 live results are pending.
- The process A/B is mocked, `N=1` per cell, and directional.
- Routing evidence is one Claude Sonnet run, not task completion or Codex evidence.
- No independent novice usability study exists.
- Generated files, scripts, IDs, and ledger entries require inspection and execution before reliance.
- Pricing snapshots are dated; annotation and training inputs may remain assumptions.

Read [Support & Evidence](support-and-scope.md) for the full claim register and the repository [security policy](https://github.com/Borda/vision-delivery/blob/main/.github/SECURITY.md) for private reporting.
