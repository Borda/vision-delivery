---
description: Install Sentinel in Claude Code or Codex, get a first measured number with no Roboflow account, then connect Roboflow only when a later step needs it.
title: Quick Start
---

# Quick Start

The order is: install, get a first measured number with no account, then connect Roboflow only if that number says you need more. Sentinel supplies CV methodology; it cannot supply data authority or decide what failure your organization can accept.

## Before you start

You need:

- Claude Code or Codex,
- permission to use the images or video,
- representative images that you label yourself: 10 or more for a yes/no per image, 20 or more with objects for a count per image (the count metrics give no verdict below 20, and a small sample often reads `INCONCLUSIVE`),
- a concrete output such as a count or a flag, and which error is worse,
- a human owner for the result.

You do not need a Roboflow account for the first number. You need one later, for anything that runs on Roboflow.

!!! warning "Your images leave your machine at the first step"

    The first number needs no Roboflow account, but the host model looks at your images, so they go to your host model provider like any image you attach to a chat. Do not use private or sensitive media (faces, license plates, medical images, people at work) until its allowed purpose and handling are established. See [Trust and Safety](trust.md#sensitive-use-gate).

## 1. Install

=== "Claude Code"

    ```bash
    claude plugin marketplace add Borda/vision-delivery
    claude plugin install sentinel@sentinel
    ```

=== "Codex"

    ```bash
    codex plugin marketplace add https://github.com/Borda/vision-delivery
    codex plugin add sentinel@sentinel
    ```

Claude Code gets the methodology and the spend gate. Codex is the methodology tier: the locked target, the baseline ladder, and the scorer are the same there (no recorded live run on either host yet), but it has no gate.

The v0.5 release candidate has passed local clean-home marketplace simulations. Manual public-GitHub marketplace installation was recorded for v0.3; the v0.5 public-install path remains unverified. The Codex commands match the current Codex CLI help and repository marketplace manifest.

For local plugin development from a checkout, run `claude plugin validate .` and then `claude --plugin-dir .`. If setup is unclear, invoke `$check-sentinel-setup` in Codex or `/sentinel:check-sentinel-setup` in Claude Code. Its offline doctor verifies the installed package first and reports host enablement and Roboflow authorization separately.

## 2. Get a first number with no Roboflow account

1. Put your representative images in a folder you are allowed to use.

2. Label them yourself, without looking at any model output: one line per image in a `gold.jsonl` file kept outside the image folder. Each line is either `{"image": "<file>", "count": <n>}`, or `{"image": "<file>", "flag": true}` or `{"image": "<file>", "flag": false}`. Every image needs a line.

3. Start with the job, not a model name:

    ```text
    Count pallets in the images in ./frames. My counts are in ./labels/gold.jsonl.
    A missed pallet is worse than a duplicate count. Explore mode, please.
    ```

    Useful details are the input (images, video, stream, folder, or dataset), the target (object, defect, text field, region, or event), the output you need, which miss or false alarm matters more, and any latency or environment limit. If you do not know a metric or threshold, say what the error costs in plain language. Sentinel translates that into a proposed target and asks you to confirm it.

4. Sentinel locks the target before it reads any result. It then looks at each image with the host model's own vision, writes its answers to a file, and scores them against your labels with `score_baseline.py`. Nothing goes to Roboflow and no Roboflow credit is spent; the images go to your host model, as the warning above says.

5. Read the line it prints. For a count task on 24 images with an 85% target it looks like this:

    ```text
    Per-image count agreement: 42 of 47 labeled objects (89%, 95% interval 81% to 96%); target >= 85%: INCONCLUSIVE. The 95% interval includes the target: label more images to settle it, or treat the result as not yet proven. This number does not penalize over-counting: the predictions hold 2 counts beyond the labels (see over_count_rate). Missing predictions: 0.
    ```

    The verdict is `PASS` only when the whole 95% interval meets the target. `INCONCLUSIVE` means label more images; `BELOW-TARGET` means the next rung of the ladder; `NO VERDICT` means the scorer refused, for example because an image has no prediction. [Modes and the baseline ladder](modes-and-ladder.md) explains each one, and [Sample Output](sample-output.md) shows more lines the shipped tools print on fixtures.

You can run the scorer yourself on placeholder files first: see the [first-baseline example](https://github.com/Borda/vision-delivery/tree/main/examples/first-baseline).

## 3. Connect Roboflow when a rung needs it

A rung 0 pass is a reason to go on, not a production result, and a rung 0 miss sends Sentinel up the ladder. Both paths can need Roboflow: an open-vocabulary or public model, a dataset, training, or deployment.

Use a read-only Roboflow MCP action first. Verify whether the host opens its managed sign-in flow, then review the requested account and authorization scope. Credentials for a generated standalone hosted client, if needed later, are separate from plugin installation and must follow current official Roboflow guidance.

!!! warning "Authentication and data"

    Plugin installation does not require a credential environment variable. Codex metadata requests authorization on use; verify the actual host-managed sign-in, account, and scope in your live host. Never paste credentials into chat or commit them. MCP operations can send task data to Roboflow; do not use private or sensitive media until its allowed purpose and handling are established. Roboflow account authorization and service behavior remain host-managed upstream checks.

## 4. Approve paid actions

Before any Roboflow action that spends credits, moves data, or changes provider state, Sentinel writes an action brief: scope, an upper cost estimate with its source and date, data movement, and rollback.

- **Claude Code:** a Sentinel hook denies the call until the brief is recorded, then hands it to the host permission prompt, where you approve or reject it. Single-image inference is approved once, as a call budget; later calls inside the budget follow your own host permission rules. [Trust and Safety](trust.md#paid-actions) describes the gate and what it does not cover.
- **Codex:** there is no gate. Sentinel shows you the brief and stops; you run the action yourself.

## Expected first response

A useful first response should:

1. restate the business outcome and check data authority,
2. classify the required output,
3. ask only for missing business facts,
4. propose a metric, threshold, and representative eval slice,
5. measure the cheapest baseline before recommending training,
6. stop before a paid or state-changing action and hand it to the approval path above.

If it skips the target, assumes permission, promises production accuracy, or starts a paid action without that approval, stop the session and report the behavior.

## What success looks like

A first proof is complete only when the expected artifacts were inspected or executed, the measured result is compared with the agreed target, failures are visible, and a human accepts the next step. A chat statement or ledger row alone is not proof.

Continue with [Use Cases](use-cases.md), [Workflow](workflow.md), [Support & Evidence](support-and-scope.md), and [Trust and Safety](trust.md).
