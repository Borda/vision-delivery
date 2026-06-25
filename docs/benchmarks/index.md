# Benchmark Comparisons: Plugin vs Plain Agent

These benchmarks demonstrate the structural gap between the `vision-delivery` plugin and a plain Claude Code agent given the same cold prompt. The plugin defines a measurable eval before any model selection, executes the eval loop in-session, and produces a deployable artifact. A plain agent describes an approach but cannot run the eval, enforce a threshold, or deploy an endpoint. The gap is not capability — it is execution: only the plugin closes the loop from cold prompt to running inference.

---

## Summary table

| # | Problem | Cold prompt | Skill | Steps saved | Eval defined | Deploy ready |
|---|---------|-------------|-------|-------------|--------------|--------------|
| B1 | Conveyor / aerial vehicle count | "Count defective items coming off my conveyor" | `detect-and-analyze` | 5 steps | ✅ | ✅ |
| B2 | PPE compliance | "Flag workers not wearing hard hats on this construction site footage" | `classify-or-flag` | 5 steps | ✅ | ✅ |
| B3 | Shopper dwell tracking | "Track how long shoppers spend in each aisle — I have RTSP streams" | `track-and-count` | 8 steps (RTSP deploy) | ✅ | ✅ |
| B4 | OCR extraction | "Read serial numbers off circuit boards in my manufacturing line" | `read-text` | 5 steps | ✅ | ✅ |
| B5 | Measurement | "Measure crack width in these bridge inspection photos for our maintenance report" | `segment-and-analyze` | 5 steps | ✅ | ✅ |

Steps saved = steps to a runnable, eval-passing result. Plain agent produces 0 runnable steps in all cases.

---

## Per-benchmark links

- [B1 — Conveyor / aerial vehicle count](b1-conveyor-detect.md)
- [B2 — PPE compliance (hard hat detection)](b2-classify-or-flag.md)
- [B3 — Shopper dwell tracking (RTSP)](b3-track-in-video.md)
- [B4 — Serial number OCR extraction](b4-read-text-ocr.md)
- [B5 — Crack width measurement](b5-measure-in-image.md)

---

## Reproduce all

```bash
git clone https://github.com/<org>/vision-delivery
cd vision-delivery
export ROBOFLOW_API_KEY=<your-key>

# Run any benchmark — replace cold prompt with the one listed in the table above
claude --plugin-dir . "<cold-prompt>"
```

`--plugin-dir .` must be set. Without it, the skill does not load and the session falls back to the plain-agent path — which is the intended comparison baseline.

For plain-agent comparison runs:

```bash
claude   # no --plugin-dir flag
```

Send the same cold prompt. Record whether eval was defined, whether a threshold was set, and whether a deployable artifact was produced.

---

## What the plugin adds structurally

Three capabilities absent from plain agents:

1. **Eval loop execution** — the plugin defines a measurable threshold (mAP, recall, IoU, field match, dwell MAE) before any model selection, runs the eval in-session, and only advances to deploy if the threshold is met. Plain agents describe thresholds but cannot enforce them.

2. **Workflow deploy** — the plugin constructs a Roboflow Workflow and deploys a live inference endpoint (or RTSP stream endpoint) in a single call. Plain agents describe endpoint setup as a future manual step; the plugin closes that step in-session.

3. **Ledger write** — each skill writes `eval_definition.md` (threshold + rationale) and a result record to `.notes/` before deploy. This creates an auditable trail — threshold committed before training, result committed before production — that plain agents cannot produce.
