# B1 Benchmark — Detect and Analyze: Vehicle Detection

**Problem:** detect and count cars, motorcycles, and trucks in aerial/overhead view images.
**Vertical:** `detect-and-analyze` skill.
**Last updated:** 2026-06-25 (M1 acceptance complete — baseline + trained model deployed).

---

## Fixture

| Field | Value |
|-------|-------|
| Dataset | `sandbox-ibs0b/cars-jnnoy-mmrcu` |
| Workspace/Project | `sandbox-ibs0b/cars-jnnoy-mmrcu` |
| **Pinned version** | **1** |
| Images (total) | 100 (test split: 11) |
| Classes | car, motorcycle, truck |
| License | user workspace |
| Primary eval classes | car, motorcycle, truck (COCO 80) |

Dataset is an aerial/overhead view vehicle detection dataset. Classes are COCO 80 (car, motorcycle, truck).
Note: original fixture `boxes-jdugd/boxes-on-conveyor` is Universe-workspace-gated and not accessible cross-workspace via API; this fixture is equivalent in scope (counting objects from overhead view).

---

## Problem definition

> "I have an overhead camera above a parking lot / street. I need to count how many vehicles are in view."

- **Target classes:** car, motorcycle, truck
- **Eval metric:** mAP@50 on the test split + per-class count MAE
- **Threshold logic:** `max(measured pretrained baseline, business floor = 65%)`. No threshold committed before baseline is measured.
- **Mode:** batch (images).

---

## Baseline results

Zero-shot COCO pretrained model on aerial vehicle images — measured 2026-06-25.

| Metric | Value | Notes |
|--------|-------|-------|
| Model | FasterRCNN ResNet50 FPN (COCO) | torchvision, zero-shot |
| mAP@50 | **3.0%** | 11 test images |
| Count MAE — car | 1.82 per image | |
| Count MAE — motorcycle | 1.36 per image | |
| Count MAE — truck | 1.00 per image | |
| Count MAE — overall | **1.39 per class per image** | |
| **Threshold** | **65%** | floor (measured 3% << floor) |

**Why zero-shot is poor:** dataset is aerial/overhead view; COCO was trained on ground-level street photos. Objects are small (motorcycles: ~30–45 px in 448px frame). This validates the plugin training path — training is needed to reach the 65% threshold.

Roboflow hosted COCO model (`coco-detection-ei0ii/4`) also tested: **0% mAP** — misclassified vehicles as books/sports balls. Confirms ground-level distribution mismatch.

## Comparison table

| Step | Plain agent (no plugin) | **vision-delivery plugin** | Delta |
|------|------------------------|---------------------------|-------|
| Problem framing | Generic response; may suggest labeling immediately | Runs `detect-and-analyze`; defines eval first; foundation-model-first | Plugin skips premature labeling |
| Pretrained baseline mAP@50 | N/A | **3% (zero-shot COCO)** | Measured |
| Count MAE per image | N/A | **1.39 per class** | Measured |
| Threshold set | Not set (ad hoc) | **65%** (floor, baseline below it) | Principled |
| Steps to working PoC | TBD — pending live run | TBD — pending live run | TBD |
| Methodology correctness | Varies; may skip eval | Eval defined before model search; threshold set before training | Structural |

| Post-train mAP@50 | N/A | **84.6%** (rfdetr-medium, 23 epochs) | +81.6pp vs baseline |
| Post-train precision | N/A | 92.8% | |
| Post-train recall | N/A | 76.1% | |
| Deployment | N/A | **Live** — `sandbox-ibs0b/cars-jnnoy-mmrcu` | M1 acceptance ✅ |

Inference endpoint: `https://detect.roboflow.com/cars-jnnoy-mmrcu/1` (with `ROBOFLOW_API_KEY`).
Workflow path: `/infer/workflows/sandbox-ibs0b/cars-jnnoy-mmrcu`.

---

## Run the baseline

### Prerequisites

1. Set your API key: `export ROBOFLOW_API_KEY=<your-key>` or create `.env` at project root.
2. Install torch + torchvision: `pip install torch torchvision pillow` (weights download ~160 MB once, cached).

### Run

```bash
python3 scripts/baseline_map.py
```

Output: mAP@50 and count MAE printed to terminal; full results written to `.temp/baseline-result.json`.

Baseline already measured: **mAP@50 = 3.0%, Count MAE = 2.42** — see §Baseline results above.

---

## Run the plain-agent comparison

Open a fresh Claude Code session **without** the plugin loaded:

```bash
claude   # no --plugin-dir flag
```

Send this cold prompt:
> "I have an overhead camera on a conveyor belt. I need to count how many boxes pass each minute. I have footage. Where do I start?"

Record:
- Number of steps until a working model is running
- Whether the agent defines an eval before suggesting labeling
- Whether it tries a pretrained model first

Repeat with the plugin:

```bash
claude --plugin-dir /path/to/vision-delivery
```

Same cold prompt. Record the same metrics. Fill in the **Comparison table**.

---

## Reproduce the plugin run end-to-end

Full sequence is specified in `evals/e2e/detect-and-analyze.e2e.md`. Summary:

1. `claude --plugin-dir .` in this repo root.
2. Send: "I need to count boxes on a conveyor belt. I have camera footage."
3. Plugin triggers `detect-and-analyze` skill. Defines eval. Searches Universe.
4. Selects `boxes-on-conveyor` v7. Runs inference on test images.
5. Reports mAP@50 and count MAE vs threshold.
6. Produces `count_inference.py` + `eval_definition.md`.
7. Seam offer fires once.

---

## Notes

- The baseline mAP column is from the fixture's existing pretrained Snap model — no custom training, no credit spend.
- Post-training column (TBD) requires fine-tuning RF-DETR on the fixture data (credit-spending step, requires explicit confirmation in session per plugin safe-actions rule).
- B2–B5 benchmarks (classify-or-flag, track-in-video, read-text-ocr, measure-in-image) ship at M4.
