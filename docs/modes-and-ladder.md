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

### Labels first, then frozen predictions

No labels yet? Ask Sentinel to help you label, or run the helper yourself: `python3 resources/scripts/label_gold.py --images <your image folder> --labels <project>/.vision-delivery/gold.jsonl --task count` (or `--task flag`, or `--task text`). It shows each image path, you type the count, yes or no, or the text, and every answer is saved at once; press `q` to stop (`:quit` for text, where `q` is a valid label) and run it again to continue. It never suggests a label, and after each answer it tells you whether you have enough images for a verdict. Run it in a terminal: it refuses piped input, so the answers come from a person at the keyboard. Keep the label file outside the image folder and inside the project folder. When it is not inside `.vision-delivery/`, add `--ledger <project>/.vision-delivery/ledger.jsonl`.

The helper records every write in the project ledger, with how the labels were entered. Labels you give Sentinel in chat are recorded with the helper's `--record` option, and the scorer's line says so, because an agent typed them in for you.

The rung 0 answers are then written by a separate subagent that is given the image paths and the question; your labels are not given to it. Sentinel freezes the answer file and your label file in the ledger before scoring: it records a digest of each file and a short digest of each label. The scorer refuses a file that was never frozen or that changed afterwards. A freeze is refused when a label differs from an earlier freeze of the same image, or when the labels were written after the answer file; it can be forced, and the scorer then says the result is not an independent measurement. Once predictions are frozen for a label file, that file can no longer change; to add images, start a new label file. On a host with no subagent tool the run is marked "independence not enforced".

> Limits: a freeze shows that the prediction file and the label file were fixed before this scoring run, and the scorer's line says whether labels changed after an earlier freeze or after the prediction file was written. It does not show that the labels are independent of the predictions. The helpers, the predictor, and the scorer run under one account on the user's machine, so a predictor that opens the label file is not detected. A ledger row written by hand is not detected. An earlier scoring run without the freeze leaves no trace. Renaming image files defeats the per-image label check, and file times can be changed. An agent can call `label_gold.py --record`, so labels entered that way are marked, not blocked, and a pseudo-terminal defeats the helper's terminal check. The isolated-subagent step has not yet been recorded in a live session.

## Reading the verdict

The scorer prints the count behind the number, a 95% interval, and one of four verdicts. It compares the whole interval with the target, not the point estimate.

| Verdict        | Meaning                                                                                                                                                                                                     | What happens next                                                                                              |
| -------------- | ----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | -------------------------------------------------------------------------------------------------------------- |
| `PASS`         | The whole interval meets the target.                                                                                                                                                                        | On a small sample this means "worth a deliver-mode proof", not "production-ready".                             |
| `BELOW-TARGET` | The whole interval misses the target.                                                                                                                                                                       | Climb one rung, or fix capture or labels.                                                                      |
| `INCONCLUSIVE` | The interval includes the target.                                                                                                                                                                           | Label more images and score the same rung again. It is not a pass.                                             |
| `NO VERDICT`   | The scorer refused: an image has no prediction, there are no cases to measure, too few cases stand behind the number, or every image gave the same result on a count metric, so the sample shows no spread. | Supply the missing predictions or more images; for a small all-correct count sample, score `exact_count_rate`. |

The scorer measures three kinds of answer: a count per image, a yes/no flag per image, and one text value per image (`--task text`: the share of images read exactly right, and the character error rate). Text is compared exactly, so decide the normalization first, such as upper case and no spaces, and use it for labels and answers alike. Rungs 1 to 3 return detections; `resources/scripts/detections_to_counts.py` turns them into counts or flags with a class list, a minimum confidence, and an optional region that you fix before the run.

The scorer also refuses a target that every result would meet, such as a minimum of 0%. See [Sample Output](sample-output.md) for lines the shipped tools print on fixtures, and the [first-baseline example](https://github.com/Borda/vision-delivery/tree/main/examples/first-baseline) to run it yourself.

## After delivery

Two commands answer the two questions that come after a deliver-mode handoff.

- **Do the delivery checks pass?** `python3 resources/scripts/check_delivery.py --project-root <project>` reads the project's files, runs the proof-chain checks in order, and scores the baseline's label and prediction files again. It prints `DELIVERY CHECKS PASSED for acceptance <acceptance_id>.` followed by `Every record agrees with the frozen target and with the artifact on disk; it is not shown that the scored predictions came from this artifact, and nothing is signed.`, or `DELIVERY CHECKS FAILED: <step>: <reason>`. It runs no artifact code. A later failed proof step or a drifted recheck fails the checks. Nothing is signed, so it guards against a skipped or misreported step, not against someone who edits the files on purpose. `resources/threat-model.md` in the repository says which step defends against what.
- **Does it still hold?** Label fresh images that the baseline did not use, let the delivered model answer them, and run `python3 resources/scripts/recheck.py` with the same frozen acceptance file and the original baseline evidence file. It prints `HOLDS`, `DRIFTED`, or `UNCERTAIN`, says where the new 95% interval lies relative to the baseline's single value (this is not a test of change), and records the result in the ledger. It refuses the baseline's own label file. When it can find the baseline label file, it also refuses fresh labels that repeat a baseline image name; when it cannot, it says overlap was not checked. Renamed image files defeat that check, so choose new images.

## Where the spend gate fits

Rungs 1 to 3 can call Roboflow. On Claude Code, a Sentinel `PreToolUse` hook holds each paid, data-moving, or state-changing Roboflow MCP call for a recorded action brief and your approval at the host permission prompt; single-image inference is approved once, as a call budget. On Codex there is no such gate: Sentinel writes the brief and stops. [Trust and Safety](trust.md#paid-actions) describes the gate and its limits.

The agent-facing rules behind this page live in the repository, in `resources/delivery-modes.md` and `resources/baseline-ladder.md`.
