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

Skills can request project reads, writes, edits, searches, and shell commands. The Claude hook can read host event payloads, append a local ledger, and read that ledger for event deduplication. Review host permission prompts and generated commands; installing the plugin does not confine those capabilities to a separate sandbox.

## Paid actions

The workflow instructs the agent to state the action, rationale, expected cost, and target, then wait for confirmation before training or deployment-class spend. That instruction is not a machine-enforced block.

Use host approvals, least-privilege account authorization or sessions, account budgets, and non-production targets as the real control. A separately generated standalone client may require a provider key; follow current provider guidance and scope it to the minimum permissions. Prompt injection, reasoning errors, or upstream changes can bypass prose guidance.

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

Read [Support, Scope, and Evidence](support-and-scope.md) for the full claim register and the repository [security policy](https://github.com/Borda/vision-delivery/blob/main/.github/SECURITY.md) for private reporting.
