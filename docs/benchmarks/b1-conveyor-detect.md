---
description: Measured B1 benchmark for vision-delivery detect-and-analyze, covering aerial vehicle counting, pretrained baseline, post-train result, and evidence caveats.
title: B1 Conveyor Detect Benchmark
---

# B1 Benchmark — Detect and Analyze: Vehicle Detection

**Problem:** detect and count cars, motorcycles, and trucks in aerial/overhead view images. **Vertical:** `detect-and-analyze` skill. **Last updated:** 2026-06-25.

______________________________________________________________________

## Fixture

- **Dataset:** `sandbox-ibs0b/cars-jnnoy-mmrcu`
- **Pinned version:** 1
- **Images:** 100 total, test split: 11
- **Classes:** car, motorcycle, truck (COCO 80)
- **License:** user workspace

Dataset is an aerial/overhead view vehicle detection dataset. Note: original fixture `boxes-jdugd/boxes-on-conveyor` is Universe-workspace-gated and not accessible cross-workspace via API; this fixture is an **aerial-vehicle proxy** — equivalence with the conveyor-box task (different object scale, lighting, class distribution) is unverified.

______________________________________________________________________

## Problem definition

> "I have an overhead camera above a parking lot / street. I need to count how many vehicles are in view."

- **Target classes:** car, motorcycle, truck
- **Eval metric:** mAP@50 on the test split + per-class count MAE
- **Threshold:** 65% mAP@50 business floor, committed before model search. The measured pretrained baseline determines whether tuning/training is needed, not what success means.
- **Mode:** batch (images)

______________________________________________________________________

## Baseline results

Zero-shot COCO pretrained model on aerial vehicle images — measured 2026-06-25.

- **Model:** FasterRCNN ResNet50 FPN (COCO), torchvision, zero-shot
- **mAP@50:** 3.0% (11 test images)
- **Count MAE — car:** 1.82 per image
- **Count MAE — motorcycle:** 1.36 per image
- **Count MAE — truck:** 1.00 per image
- **Count MAE — overall:** 1.39 per class per image
- **Threshold set:** 65% floor (measured 3% \<< floor)

**Why zero-shot is poor:** dataset is aerial/overhead view; COCO was trained on ground-level street photos. Objects are small (motorcycles: ~30–45 px in 448px frame). This validates the plugin training path — training is needed to reach the 65% threshold.

Roboflow hosted COCO model (`coco-detection-ei0ii/4`) also tested: **0% mAP** — misclassified vehicles as books/sports balls. Confirms ground-level distribution mismatch.

## Post-train results

- **Model:** RF-DETR medium, 23 epochs
- **mAP@50:** 84.6%
- **Precision:** 92.8%
- **Recall:** 76.1%
- **Deployment:** live — `sandbox-ibs0b/cars-jnnoy-mmrcu` ✅

Inference endpoint: `https://detect.roboflow.com/cars-jnnoy-mmrcu/1` (with `ROBOFLOW_API_KEY`). Workflow path: `/infer/workflows/sandbox-ibs0b/cars-jnnoy-mmrcu`.

______________________________________________________________________

## Plugin vs plain agent

> ⚠️ **Plain-agent arm not yet run.** The plain-agent column below is a hypothesis, not a measured result. See "Run the plain-agent comparison" below to record the real data.

**Hypothesized plain-agent behavior (not yet measured):**

- Generic response; may suggest labeling immediately
- Eval may not be defined before model search
- Pretrained baseline may not be measured explicitly
- Threshold may not be set before training (ad hoc)
- Deployable PoC not guaranteed in-session

**vision-delivery plugin (measured, 2026-06-25):**

- Runs `detect-and-analyze`; defines eval first; foundation-model-first
- Pretrained baseline: **3% mAP (zero-shot COCO)** — measured
- Count MAE: **1.39 per class per image** — measured
- Threshold: **65%** floor, principled, set before model search/training
- Post-train: **84.6% mAP** — eval passes
- Deploy: live endpoint, 1 call

> **Attribution note:** the 84.6% mAP result validates the Roboflow RF-DETR training path on this dataset, not the plugin's marginal orchestration value. A plain agent driving the same Roboflow MCP tools would reach a comparable number after fine-tuning. The plugin's contribution is the automatic eval-first discipline — measuring this requires a controlled run (see below).

______________________________________________________________________

## Run the baseline

### Prerequisites

1. Set your API key: `export ROBOFLOW_API_KEY=<your-key>` or create `.env` at project root.
2. Install torch + torchvision: `pip install torch torchvision pillow` (weights download ~160 MB once, cached).

### Run

```bash
python3 scripts/baseline_map.py
```

Output: mAP@50 and count MAE printed to terminal; full results written to `.temp/baseline-result.json`.

Baseline already measured: **mAP@50 = 3.0%, Count MAE = 1.39 per class per image** — see §Baseline results above.

______________________________________________________________________

## Run the plain-agent comparison

Open a fresh Claude Code session **without** the plugin loaded:

```bash
claude   # no --plugin-dir flag
```

Send this cold prompt:

> "I have an overhead camera above a parking lot. I need to count how many vehicles are in view. Where do I start?"

*(This matches the B1 fixture — aerial vehicle detection. Adjust to your actual use case when running on a different dataset.)*

Record:

- Number of steps until a working model is running
- Whether the agent defines an eval before suggesting labeling
- Whether it tries a pretrained model first

Repeat with the plugin:

```bash
claude --plugin-dir /path/to/vision-delivery
```

Same cold prompt. Record the same metrics. Fill in the **Plugin vs plain agent** section.

______________________________________________________________________

## Reproduce the plugin run end-to-end

Full sequence is specified in `evals/e2e/detect-and-analyze.e2e.md`. Summary:

1. `claude --plugin-dir .` in this repo root.
2. Send: "I have an overhead camera above a parking lot. I need to count vehicles in view."
3. Plugin triggers `detect-and-analyze` skill. Defines eval. Searches Universe.
4. Selects `cars-jnnoy-mmrcu` (or fixture dataset). Runs inference on test images.
5. Reports mAP@50 and count MAE vs threshold.
6. Produces `count_inference.py` + `eval_definition.md`.
7. Seam offer fires once.

______________________________________________________________________

## Notes

- Baseline mAP is from the fixture's existing pretrained Snap model — no custom training, no credit spend.
- Post-training requires fine-tuning RF-DETR on the fixture data. This is a credit-spending step, so the skill instructs the agent to ask for explicit confirmation in session.
- B2-B5 benchmarks (classify-or-flag, track-in-video, read-text-ocr, measure-in-image) define the remaining comparison fixtures.
