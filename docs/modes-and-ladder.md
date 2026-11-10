---
description: Sentinel's explore and deliver modes, the four-rung baseline ladder that starts with no account, and how to read the scorer's four verdicts.
title: Modes And The Baseline Ladder
---

# Modes And The Baseline Ladder

Sentinel works in two modes and climbs one ladder. Explore mode gives a plain answer fast. Deliver mode adds a proof chain when the result leaves your desk. The ladder makes sure the cheapest baseline is measured before anything is paid for.

## Two modes

| Mode                  | Use it for                                                                                                 | What you see                                                                                          | What it never says                |
| --------------------- | ---------------------------------------------------------------------------------------------------------- | ----------------------------------------------------------------------------------------------------- | --------------------------------- |
| **Explore** (default) | Feasibility, a first baseline, "is this worth pursuing?"                                                   | Plain-language numbers and a verdict. No digests, schema versions, or helper commands unless you ask. | "Production-ready"                |
| **Deliver**           | A result that will run in production, feed an automated action, reach a third party, or back a paid action | The same plain numbers, plus frozen acceptance files, digest-bound evidence, and validated handoffs   | That an unverified artifact works |

In both modes the target is locked before any result is read. Explore mode records it in plain words; deliver mode freezes it in a file with a digest. Moving to deliver mode carries the explore target forward unchanged. Sentinel tells you once when the mode changes and why.

Sentinel switches to deliver mode when any of these is true:

- the result will run in production, feed an automated action, or reach a customer or third party;
- you ask for a delivery handoff, a packaged artifact, a decision report, or a binding economics decision;
- a paid or state-changing provider action is about to be briefed;
- you ask for an auditable record.

## The baseline ladder

Climb one rung at a time and stop at the first rung that clears the locked target. Every rung is scored on the same labeled images with the same target, so the rungs can be compared.

| Rung | What is tried                                       | Account or cost                                                      | Typical first use                                                |
| ---- | --------------------------------------------------- | -------------------------------------------------------------------- | ---------------------------------------------------------------- |
| 0    | The host model's own vision, asked about each image | None beyond your current session                                     | Whole-image flags, small counts, "is the signal visible at all?" |
| 1    | An open-vocabulary detector or segmenter            | Sourced from Roboflow; a hosted run is a gated action on Claude Code | Common objects you can name in plain words                       |
| 2    | A public pretrained model or dataset for the domain | Sourced from Roboflow; license review required                       | Domain objects that public work already covers                   |
| 3    | Fine-tuning on your labeled images                  | Paid or compute cost; needs an action brief and your approval        | Custom or fine-grained targets the lower rungs miss              |

Rung 0 needs no Roboflow sign-in, upload to Roboflow, or Roboflow spend. The images do go to your host model, like any image you attach to a chat, so do not use private or sensitive media until its allowed purpose is settled. You label a small set of representative images yourself (10 or more for a yes/no flag; 20 or more with objects for a count, because the count metrics refuse a verdict below 20), the host model answers the business question for each image without seeing your labels, and a small stdlib script compares the two. It tells you whether the task is easy, borderline, or hard. It gives no boxes or masks, no latency number, and no production path, and its output is never used as a label.

## Reading the verdict

The scorer prints the count behind the number, a 95% interval, and one of four verdicts. It compares the whole interval with the target, not the point estimate.

| Verdict        | Meaning                                                                                                                                                                                                     | What happens next                                                                                              |
| -------------- | ----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | -------------------------------------------------------------------------------------------------------------- |
| `PASS`         | The whole interval meets the target.                                                                                                                                                                        | On a small sample this means "worth a deliver-mode proof", not "production-ready".                             |
| `BELOW-TARGET` | The whole interval misses the target.                                                                                                                                                                       | Climb one rung, or fix capture or labels.                                                                      |
| `INCONCLUSIVE` | The interval includes the target.                                                                                                                                                                           | Label more images and score the same rung again. It is not a pass.                                             |
| `NO VERDICT`   | The scorer refused: an image has no prediction, there are no cases to measure, too few cases stand behind the number, or every image gave the same result on a count metric, so the sample shows no spread. | Supply the missing predictions or more images; for a small all-correct count sample, score `exact_count_rate`. |

The scorer also refuses a target that every result would meet, such as a minimum of 0%. See [Sample Output](sample-output.md) for lines the shipped tools print on fixtures, and the [first-baseline example](https://github.com/Borda/vision-delivery/tree/main/examples/first-baseline) to run it yourself.

## Where the spend gate fits

Rungs 1 to 3 can call Roboflow. On Claude Code, a Sentinel `PreToolUse` hook holds each paid, data-moving, or state-changing Roboflow MCP call for a recorded action brief and your approval at the host permission prompt; single-image inference is approved once, as a call budget. On Codex there is no such gate: Sentinel writes the brief and stops. [Trust and Safety](trust.md#paid-actions) describes the gate and its limits.

The agent-facing rules behind this page live in the repository, in `resources/delivery-modes.md` and `resources/baseline-ladder.md`.
