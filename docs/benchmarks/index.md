---
description: Benchmark overview for vision-delivery, including measured B1 evidence, fixture-defined B2-B5 routes, and process-efficiency claim boundaries.
title: Benchmark Comparisons
---

# Benchmark Comparisons: Plugin vs Plain Agent

These benchmarks compare the `vision-delivery` plugin against a plain Claude Code agent given the same cold prompt and the same Roboflow MCP tool access. A plain agent can reach the same outcomes — but requires the user to know and request each step. The plugin pre-programs the eval-first discipline: threshold committed before model search, baseline measured before training, deploy gated on passing. **Process-efficiency claim, not a capability claim.**

B1 has measured evidence. B2-B5 define benchmark fixtures and acceptance criteria for the other skill routes.

______________________________________________________________________

## Summary table

| #   | Problem                         | Cold prompt                                                                        | Skill                 | Evidence        |
| --- | ------------------------------- | ---------------------------------------------------------------------------------- | --------------------- | --------------- |
| B1  | Conveyor / aerial vehicle count | "Count vehicles in this overhead camera view"                                      | `detect-and-analyze`  | Measured        |
| B2  | PPE compliance                  | "Flag workers not wearing hard hats on this construction site footage"             | `classify-or-flag`    | Fixture defined |
| B3  | Shopper dwell tracking          | "Track how long shoppers spend in each aisle — I have RTSP streams"                | `track-and-count`     | Fixture defined |
| B4  | OCR extraction                  | "Read serial numbers off circuit boards in my manufacturing line"                  | `read-text`           | Fixture defined |
| B5  | Measurement                     | "Measure crack width in these bridge inspection photos for our maintenance report" | `segment-and-analyze` | Fixture defined |

______________________________________________________________________

## Per-benchmark links

- [B1 — Conveyor / aerial vehicle count](b1-conveyor-detect.md)
- [B2 — PPE compliance (hard hat detection)](b2-classify-or-flag.md)
- [B3 — Shopper dwell tracking (RTSP)](b3-track-in-video.md)
- [B4 — Serial number OCR extraction](b4-read-text-ocr.md)
- [B5 — Crack width measurement](b5-measure-in-image.md)
- [A/B — Plugin vs plain agent (deterministic mock tier)](ab-plugin-vs-plain.md)
- [A/B — Annotated transcripts](ab-transcripts.md)

______________________________________________________________________

## Reproduce all

```bash
git clone https://github.com/Borda/vision-delivery
cd vision-delivery
export ROBOFLOW_API_KEY=<your-key>

claude --plugin-dir . "I have an overhead camera above a parking lot. I need to count vehicles in view."
```

`--plugin-dir .` must be set. Without it, the skill does not load and the session falls back to the plain-agent path, which is the intended comparison baseline.

For plain-agent comparison runs:

```bash
claude   # no --plugin-dir flag
```

Send the same cold prompt. Record whether eval was defined, whether a threshold was set, and whether a deployable artifact was produced.

______________________________________________________________________

## What the plugin adds structurally

Three steps the plugin automates without requiring the user to ask:

1. **Eval loop execution** — each skill defines a measurable threshold before model selection, runs the eval in-session, and only advances to deploy if the threshold is met.

2. **Workflow deploy** — deploy-capable paths can produce a Roboflow endpoint after the eval passes and the user confirms any paid action.

3. **Ledger write** — the workflow writes `eval_definition.md` (threshold + rationale) and result records to `.vision-delivery/` before deploy. This auditable trail — threshold committed before training, result committed before production — is produced automatically, not on user request.

**What this is not:** a capability advantage. Both the plugin and a plain agent with the Roboflow MCP can train, eval, and deploy. The plugin's value is that the discipline is automatic. A live controlled experiment measuring turn-count difference has not yet been run.
