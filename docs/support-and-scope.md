---
description: Sentinel support tiers, evidence register, user responsibilities, sensitive-use gates, and the limits that remain before broad go-to CV claims are justified.
title: Support & Evidence
---

# Support & Evidence

This is the one page that states what Sentinel's evidence shows and where it stops. Other pages give one line and link here. Three kinds of page still carry detail on purpose: the benchmark pages, which are the source records; the `llms.txt` summaries, which an agent reads alone; and the README and [Trust and Safety](trust.md), which describe the spend gate in full.

Sentinel is a delivery copilot, not a model and not an autonomous production owner. It is designed to let a user begin with an operational outcome while the plugin supplies CV task framing, evaluation discipline, improvement order, and decision structure.

The entry barrier is intentionally low, but it is not zero. A safe first session still needs:

- authority to use the images, video, annotations, and account,
- a concrete business outcome,
- representative examples or a plan to collect them,
- the consequence of misses and false alarms,
- a human who owns the final decision.

## Support tiers

| Tier                    | What you may infer                                                               | What you may not infer                                                                            |
| ----------------------- | -------------------------------------------------------------------------------- | ------------------------------------------------------------------------------------------------- |
| **Historical evidence** | A result was recorded under its listed conditions and caveats.                   | Current-route support, independent reproducibility, production readiness, or domain transfer.     |
| **Guided**              | A specialist workflow can frame the task, define an eval, and request artifacts. | That the route has been authenticated and completed end to end on a representative live workload. |
| **Delegated upstream**  | Sentinel can decide when current platform truth is needed and defer to it.       | That copied or remembered Roboflow API/model/pricing details are current.                         |
| **Expert required**     | Sentinel may help structure questions and evidence.                              | That the plugin alone can authorize, validate, or sign off the work.                              |

## Route status

| Route                           | Support                                                      | Evidence status                                        | Material limit                                                                                       |
| ------------------------------- | ------------------------------------------------------------ | ------------------------------------------------------ | ---------------------------------------------------------------------------------------------------- |
| Object detection and counting   | Flagship; guided                                             | B1 records one small private historical vehicle result | Private data prevents independent reproduction; current-route and domain transfer remain unverified. |
| Classification and flagging     | Flagship; guided                                             | B2 fixture defined                                     | No equivalent live result committed.                                                                 |
| Tracking and counting over time | Preview; guided                                              | B3 fixture defined                                     | RTSP, identity, latency, privacy, and production state handling are not live-proven.                 |
| OCR and structured text         | Preview; guided                                              | B4 fixture defined                                     | No equivalent live field-accuracy result committed.                                                  |
| Segmentation and measurement    | Preview; guided; expert required for physical claims         | B5 fixture defined                                     | Pixel-to-physical calibration and domain validation are not supplied by the plugin.                  |
| Pose, gesture, and action       | Preview; guided; expert required for consequential use       | Skill route exists                                     | No equivalent live benchmark; safety and fairness review remain external.                            |
| Multi-step pipelines            | Preview; guided; expert required for production architecture | Decomposition route exists                             | Cross-stage error propagation and operations are not broadly benchmarked.                            |
| Economics                       | Guided                                                       | Reproducible deployment calculator and dated snapshots | Annotation/training inputs may be assumptions; prices can become stale.                              |
| Roboflow platform operations    | Delegated upstream                                           | MCP configuration exists                               | Exact tools, models, Workflows, plans, pricing, and account behavior are upstream.                   |
| Delivery and integration        | Guided                                                       | Artifact and handoff validators exist                  | Real hosted/offline consumer smokes and production operations remain environment-specific.           |

Flagship routes are the first to be taken to live end-to-end proof on public, licensed data. Preview routes keep the full workflow but should be used with more caution until they have comparable evidence.

## Claim register

| Evidence           | What it tests                                                                                                                                 | Result                                                                                                        | What it does not prove                                                                                          |
| ------------------ | --------------------------------------------------------------------------------------------------------------------------------------------- | ------------------------------------------------------------------------------------------------------------- | --------------------------------------------------------------------------------------------------------------- |
| Live trigger suite | Whether a skill fires for a labeled prompt                                                                                                    | One Claude Sonnet run: 143 prompts, precision `0.94`, recall `0.85`; 4 false positives and 11 false negatives | Correct task completion, Codex parity, repeat stability, or user outcomes                                       |
| Synthetic A/B      | Workflow behavior with mocked Roboflow tools                                                                                                  | 16 runs at `N=1` per cell: 1 supported, 6 mixed/parity, 1 loss                                                | Live model quality, market advantage, or production behavior                                                    |
| B1 CV fixture      | One detection/counting workflow record                                                                                                        | Post-training result on 11 private test images                                                                | Conveyor equivalence, broad transfer, production readiness, or a controlled plugin advantage                    |
| Spend gate         | The Claude Code hook's decision for every tool in the policy with no brief recorded, plus named brief, call-budget, and permission-mode cases | Deterministic repository tests pass                                                                           | How the host renders the prompt, which tool names a live Claude Code session receives, or any behavior on Codex |
| Baseline scorer    | Verdicts on built fixtures, including the refusal cases                                                                                       | Deterministic repository tests pass                                                                           | That a host model's rung 0 answers are good on your images; no recorded real run exists                         |
| Novice use         | Whether a non-expert completes a safe first session                                                                                           | No study                                                                                                      | Any entry-barrier claim                                                                                         |

The sections below give each claim's detail.

### Live routing

One Claude Sonnet run used 143 labeled prompts: 74 positive and 69 negative. It reported 63 true positives, 4 false positives, and 11 false negatives, for micro precision `0.94` and recall `0.85`. Tolerating two direct specialist routes raises positive coverage to 65/74 (`0.88`).

This pre-v0.2 run does not include `deliver-cv-project` or `check-sentinel-setup`. It does not show current-route coverage, zero misrouting, Codex parity, repeat-run stability, correct task completion, or novice outcomes.

### Synthetic process comparison

The plugin-vs-plain comparison contains 16 mocked runs at one repeat per cell. The preregistered result was one supported cell, six parity/mixed cells, and one loss. It tests workflow behavior in a mocked Roboflow world, not live model quality. Developer-machine contamination and the missing live capability confirmation remain disclosed limitations.

### CV task result

B1 reports a post-training result on 11 private test images. It has no controlled plain-agent comparator, no post-training count error, and no public independent reproduction, and the equivalence of its aerial-vehicle data to the intended conveyor domain is unverified. The fixture is useful evidence that the detection path can produce a measured record; it is not evidence for broad domains, production deployment, or a plugin advantage over a controlled plain-agent run. B2-B5 remain pending.

### Spend gate and scorer

The Claude Code spend gate and the baseline scorer are covered by deterministic tests in the repository: the gate's decision is checked for every tool in its policy, and the scorer's verdicts are checked on built fixtures. Neither has a recorded live session. The gate policy is generated from the tool catalog Roboflow publishes for another host surface, so the tool names a Claude Code session receives are unconfirmed; an unlisted name is treated as gated. The mocked A/B has not been re-run with the gate's approval prompt answered, so it says nothing about the gate. [Trust and Safety](trust.md#paid-actions) lists what the gate does not cover, and [Sample Output](sample-output.md) shows what the tools print.

### Entry-barrier claim

No independent novice study has measured task completion, time to first valid eval, error recovery, or safe production decisions. Say “designed to lower the methodology burden,” not “no knowledge required” or “proven for novices.”

## Sensitive-use gate

Stop before uploading, analyzing, training on, or deploying with sensitive data unless the user can establish all of the following:

1. authority to process the data and a documented allowed purpose,
2. data minimization, access, retention, and deletion rules,
3. a representative evaluation set and relevant subgroup analysis,
4. the cost of false positives and false negatives,
5. a named human reviewer, override path, and incident owner,
6. legal, privacy, security, and domain review appropriate to the consequences.

This gate applies especially to faces, license plates, people tracking, forms, medical imagery, worker monitoring, minors, private property, and location-linked media. Sentinel is not a sole decision-maker for medical, employment, law-enforcement, access-control, or physical-safety decisions.

## Generated-output boundary

A workflow instruction to create `eval_definition.md`, a local script, JSONL, model/workflow IDs, or a ledger row is not evidence that the artifact exists, is runnable, or is correct. Before calling a result complete:

- inspect the file,
- run its syntax and dependency checks,
- execute it on a representative fixture,
- compare outputs with the committed eval gate,
- record failures and unknowns,
- obtain human production acceptance.

## What would close the major gaps

Sentinel can make a stronger “go-to plugin” claim only after objective evidence closes these gaps:

- clean-environment Codex and Claude installation tests with versioned host matrices,
- repeated live routing runs on both supported hosts,
- authenticated end-to-end B2-B5 runs with representative datasets,
- a controlled plain-agent comparator for live work,
- independent novice usability studies with safety and recovery measures,
- a recorded live session showing the Claude Code gate's prompt and a rung 0 baseline on public, licensed images,
- a host-enforced approval path for paid actions on Codex,
- artifact execution tests rather than instruction-presence checks,
- threat modeling and sensitive-use evaluation,
- verified release integrity and remote repository controls.

Until then, the defensible value proposition is: **Sentinel gives non-experts a structured, evidence-first way to explore CV problems and gives experts an auditable starting point; it does not replace domain expertise, platform truth, or production governance.**

See [Benchmarks](benchmarks/index.md), [Trust and Safety](trust.md), [Roboflow Skills Integration](roboflow-skills.md), and the repository [support policy](https://github.com/Borda/vision-delivery/blob/main/.github/SUPPORT.md).
