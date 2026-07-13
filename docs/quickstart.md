---
description: Install Sentinel from its public GitHub marketplace in Codex or Claude Code, connect Roboflow safely, and define a first business-first CV task.
title: Quick Start
---

# Quick Start

Start with an operational outcome, representative samples, and the consequence of a wrong answer. Sentinel supplies CV methodology; it cannot supply data authority or decide what failure your organization can accept.

## Before you start

You need:

- Codex or Claude Code,
- a Roboflow account for the host-managed sign-in flow,
- permission to use the project and media,
- a concrete output such as a count, flag, text field, mask, track, or keypoint,
- a human owner for the result.

!!! warning "Authentication and data"

    Plugin installation does not require a credential environment variable. Codex metadata requests authorization on use; verify the actual host-managed sign-in, account, and scope in your live host. Never paste credentials into chat or commit them. MCP operations can send task data to Roboflow; do not use private or sensitive media until its allowed purpose and handling are established.

## Codex marketplace install

The v0.2 package has passed a local clean-home marketplace simulation. Its public-GitHub path remains unverified until this release is published to `main` and retested from the repository URL.

```bash
codex plugin marketplace add https://github.com/Borda/vision-delivery
codex plugin add sentinel@sentinel
```

These marketplace commands match the current Codex CLI help and repository marketplace manifest.

## Claude Code marketplace install

```bash
claude plugin marketplace add Borda/vision-delivery
claude plugin install sentinel@sentinel
```

For local plugin development from a checkout, run `claude plugin validate .` and then `claude --plugin-dir .`.

If setup is unclear, invoke `$check-sentinel-setup` in Codex or `/sentinel:check-sentinel-setup` in Claude Code. Its offline doctor verifies the installed package first and reports host enablement and Roboflow authorization separately.

## Sign in to Roboflow

Use a read-only Roboflow MCP action after installation. Verify whether the host opens its managed sign-in flow, then review the requested account and authorization scope. Credentials for a generated standalone hosted client, if needed later, are separate from plugin installation and must follow current official Roboflow guidance.

## First prompt

Start with the job, not a model name:

```text
Count pallets crossing this line and report the hourly total. I have 60 sample
frames from the real camera. A missed pallet is worse than a duplicate count.
```

Useful details are:

- input: images, video, stream, folder, or dataset,
- target: object, defect, text field, region, person, pose, or event,
- output: count, CSV, flag, alert, endpoint, or local script,
- consequence: which miss or false alarm matters more,
- operating constraint: latency, throughput, environment, and review process.

If you do not know a metric or threshold, say what the error costs in plain language. The plugin should translate that into a proposed eval and ask you to confirm it.

## Expected first response

A useful first response should:

1. restate the business outcome and check data authority,
2. classify the required output,
3. ask only for missing business facts,
4. propose a metric, threshold, and representative eval slice,
5. measure an existing or pretrained baseline before recommending training,
6. stop for confirmation before a paid or state-changing action.

If it skips the eval, assumes permission, promises production accuracy, or starts a paid action without a clear confirmation, stop the session and report the behavior.

## What success looks like

A first proof is complete only when the expected artifacts were inspected or executed, the measured result is compared with the agreed gate, failures are visible, and a human accepts the next step. A chat statement or ledger row alone is not proof.

Continue with [Use Cases](use-cases.md), [Workflow](workflow.md), [Support, Scope, and Evidence](support-and-scope.md), and [Trust and Safety](trust.md).
