---
description: Pending B2 classification/flagging benchmark specification and the evidence required before claims are made.
title: B2 Classification Fixture — Pending
---

# B2 classification/flagging fixture — pending

**Prompt:** “Flag workers not wearing hard hats on this construction-site footage.” **Route:** `classify-or-flag`. **Status:** specification only; no live measurement is committed.

## Intended business gate

The draft fixture proposes recall for the `no-hardhat` condition as the primary measure, with precision/F1 and subgroup/site slices as diagnostics. The earlier `0.90` threshold is a fixture hypothesis, not a safety standard or stakeholder-approved requirement.

## Required evidence

1. Document authority and purpose for worker footage and define the human review process.
2. Pin a representative, licensed dataset and site/camera splits.
3. Define whether the output is per-frame classification or per-person detection; the wording is currently ambiguous.
4. Commit the threshold and business consequence before model selection.
5. Measure an existing/pretrained baseline and all relevant subgroups.
6. Run any paid improvement only after explicit confirmation.
7. Execute the generated artifact and record failures, latency, and error cases.
8. Run a clean, repeated comparator before claiming plugin advantage.

## Current claim boundary

The route can guide eval-first classification work. This page does not establish that CLIP is appropriate, that zero-shot PPE recall is sufficient, that a Roboflow Workflow was built, that an endpoint was deployed, or that a plain agent would fail. Worker-compliance use remains expert-required because errors can affect safety or employment.

```bash
claude --plugin-dir . "Flag workers not wearing hard hats on this construction-site footage."
```

Running the command is only the start of the study; it is not a benchmark result.
