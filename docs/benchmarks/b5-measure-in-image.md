# B5 Benchmark — Segment and Analyze: Crack Width Measurement

**Problem:** measure crack width in bridge inspection photos for engineering maintenance reports.
**Vertical:** `segment-and-analyze` skill.
**Last updated:** 2026-06-25 (TBD — pending live run).

---

## Fixture

| Field | Value |
|-------|-------|
| Dataset | TBD — pending live run (Universe: crack segmentation dataset) |
| Workspace/Project | TBD |
| **Pinned version** | TBD |
| Images (total) | TBD |
| Classes | crack (instance segmentation mask) |
| License | Universe public |
| Primary eval metric | IoU ≥ 0.80 (mask quality), area error ≤ 15% |

Dataset note: Universe hosts multiple concrete/asphalt crack segmentation datasets. B5 fixture will be pinned to a dataset with known-width ground-truth annotations. A calibration reference object (known physical dimension in frame) is required for px/mm conversion — see Calibration caveat below.

---

## Problem definition

> "Measure crack width in these bridge inspection photos for our maintenance report."

- **Target class:** `crack` (instance segmentation)
- **Eval metrics:**
  - IoU ≥ 0.80 on crack mask vs ground-truth polygon
  - Area error ≤ 15% (derived: crack area in px vs annotated area)
  - Width in mm with ± uncertainty (after px/mm calibration)
- **Threshold logic:** IoU ≥ 0.80 must be met before width measurement is trusted. If IoU fails: adjust SAM prompt, increase image resolution, or switch to fine-tuned segmentation model.
- **Mode:** batch (uploaded inspection photos).

---

## Baseline results

TBD — pending live run.

| Metric | Value | Notes |
|--------|-------|-------|
| Model | SAM 2 zero-shot (ViT-H) | Segment Anything Model; no custom training |
| IoU — crack mask | TBD | TBD test images |
| Area error | TBD % | vs annotated ground-truth polygon |
| Width (mm) | TBD ± TBD mm | after px/mm calibration |
| **Threshold — IoU** | **≥ 0.80** | set before baseline measured |
| **Threshold — area error** | **≤ 15%** | engineering tolerance floor |
| Calibration reference | Required — known-dimension object in frame | px/mm conversion; see Notes |

SAM 2 zero-shot is attempted first because cracks are visually salient, high-contrast targets in inspection photos. If IoU falls below 0.80, the plugin triggers the fine-tune path on the user's labeled inspection frames.

---

## Comparison table

| Step | Plain agent (no plugin) | **vision-delivery plugin** | Delta |
|------|------------------------|---------------------------|-------|
| Problem framing | Describes pixel-to-mm math, edge detection (Canny), or Sobel filter | Runs `segment-and-analyze`; defines IoU ≥ 0.80 + area error ≤ 15% before any model search | Plugin anchors to measurable eval upfront |
| Segmentation model | Described ("use U-Net or SAM") | SAM zero-shot run; IoU measured on fixture images | Measured vs described |
| IoU on crack mask | N/A | TBD — measured in session | Measured vs described |
| Calibration step | Described ("convert pixels to mm using a ruler in the photo") | Calibration workflow: reference object → px/mm ratio → width in mm with uncertainty | Automated calibration |
| Width output | Conceptual (no number) | mm with ± uncertainty bound | Calibrated output |
| Steps to working PoC | 0 — no runnable result | 5 steps (eval → SAM zero-shot → measure IoU → calibrate → report) | 5 steps saved |
| Eval defined | No | Yes | ✅ |
| Deploy ready | No | Yes (segmentation endpoint) | ✅ |
| Calibrated measurement output | Conceptual | mm with uncertainty | ✅ |

---

## Plugin path — step-by-step

1. **Eval definition** — IoU ≥ 0.80, area error ≤ 15%; written to `eval_definition.md` before any model or approach selection.
2. **SAM zero-shot segmentation** — SAM 2 (ViT-H) run on fixture images; crack masks generated.
3. **Measure IoU on fixture images** — predicted masks vs ground-truth polygons; IoU and area error computed and compared against thresholds.
4. **Calibration step** — user provides reference object with known physical dimension (e.g. 100 mm reference scale in frame); plugin computes px/mm ratio; applies to crack width measurement.
5. **Report crack width in mm with uncertainty** — width extracted from mask skeleton; converted to mm; ± uncertainty from calibration error propagated; output written to inspection report format.

---

## Plain-agent path

Send the same cold prompt to Claude Code without the plugin:

> "Measure crack width in these bridge inspection photos for our maintenance report."

Typical plain-agent response:
- Describes the pixel-to-mm conversion approach ("measure pixel width, divide by px/mm ratio").
- Suggests Canny edge detection, Sobel filter, or U-Net segmentation.
- Cannot run SAM zero-shot or measure IoU in-session.
- Cannot define or enforce the IoU ≥ 0.80 threshold.
- Cannot perform the calibration workflow or output mm with uncertainty.
- No runnable PoC produced in session.

---

## Calibration caveat

**Physical units require a known-dimension reference in the frame.**

To convert pixel measurements to millimetres, every inspection photo must include:
- A reference object with a known physical dimension (e.g. a 100 mm calibration scale, a coin of known diameter, a surveying rod).
- The reference object must be in the same focal plane as the crack (or the photogrammetric correction must be applied).

Without a calibration reference, the plugin reports crack width in pixels only. Engineering reports typically require mm; the plugin makes this explicit before measurement rather than silently reporting uncalibrated pixel values.

---

## Reproduce

### Prerequisites

1. `export ROBOFLOW_API_KEY=<your-key>` or create `.env` at project root.
2. Prepare fixture images with: (a) ground-truth crack polygon annotations, (b) a known-dimension reference object visible in the frame.
3. Universe crack segmentation datasets can serve as proxy fixtures if user inspection photos are unavailable.

### Plugin run

```bash
git clone https://github.com/<org>/vision-delivery
cd vision-delivery
claude --plugin-dir . "Measure crack width in these bridge inspection photos for our maintenance report"
```

`--plugin-dir .` is required. Plugin will prompt for fixture images and calibration reference before running eval.

### Plain-agent run (comparison)

```bash
claude   # no --plugin-dir flag
```

> "Measure crack width in these bridge inspection photos for our maintenance report."

Record: whether eval was defined, whether IoU was measured, whether calibration was performed, whether crack width in mm with uncertainty was produced.

---

## Notes

- SAM zero-shot works well for bridge crack inspection because cracks are high-contrast, thin structures against uniform concrete backgrounds — a strong prior for SAM's segment-anything capability.
- IoU ≥ 0.80 is the engineering-grade threshold for structural inspection; lower IoU means mask boundary error contributes > 20% to width measurement uncertainty.
- Area error ≤ 15% is the secondary metric: it catches cases where IoU is acceptable but the mask shape is systematically biased (e.g., connected cracks counted as one).
- Calibration error propagation: px/mm uncertainty (from reference object measurement precision) is added in quadrature to width measurement uncertainty; the plugin reports both components.
- Fine-tune path: if SAM zero-shot IoU < 0.80 on the user's inspection photos (e.g., photos taken at low contrast, with glare, or on weathered concrete), the plugin proposes a labeling session for fine-tuning on domain-specific crack images.
