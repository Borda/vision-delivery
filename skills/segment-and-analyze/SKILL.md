---
name: segment-and-analyze
description: |
  Produce pixel-precise instance masks and area/shape measurements from images. Covers: instance segmentation (one mask per object), area measurement (mask pixel count → physical area), shape analysis (perimeter, aspect ratio, compactness), crack width measurement via skeleton cross-section, defect area quantification, and calibration (known reference object → px/mm conversion). Builds a segmentation pipeline: define eval → SAM zero-shot → measure IoU → fine-tune if needed → working PoC.
  TRIGGER when: user needs pixel-precise outlines or area measurements ("segment the X", "measure exact area of", "measure crack width", "measure corrosion area", "pixel-precise outline", "instance mask", "measure in millimeters from image", "calibrated measurement", "defect area in mm²", "contour of", "shape analysis", "count pixels", "tumor area", "lesion boundary", "bridge inspection measurement", "corrosion patch", "crack segment", "segment tumor", "mask defect", "outline corrosion", "measure lesion", "segment corrosion", "hull corrosion", "solar panel defect area", "assembly part dimensions", "defect outline", "precise contour", "area measurement", "pixel mask").
  SKIP when: user wants a simple per-instance count without area measurement (→ detect-and-analyze); user wants image-level verdict with no masks ("is this image defective?", "flag as pass/fail", "classify whole image" → classify-or-flag); user wants text extraction ("read serial number", "extract text", "OCR" → read-text); user wants identity-linked tracking across frames ("track worker", "follow person", "track object" → track-and-count); cost/scale question, self-hosting vs managed comparison ("deployment cost", "managed endpoint cost" → deployment-consultant); user already has masks and asks only about post-processing.
allowed-tools: Bash, Read, Write, Edit, Glob, Grep, AskUserQuestion
---

<objective>

Produce pixel-precise instance masks and area/shape measurements that pass the user's eval. The exit criterion is a segmentation model meeting the user's IoU threshold on their own images, plus a calibrated measurement pipeline if physical units (mm, cm²) are needed.

**What this skill covers:**

- **Instance segmentation** — one mask per object instance; polygon contour per detection
- **Area measurement** — mask pixel count converted to physical area (requires calibration reference)
- **Shape analysis** — perimeter, aspect ratio, compactness derived from mask contour
- **Crack width measurement** — skeleton extraction + perpendicular cross-section through mask
- **Defect area quantification** — bridge inspection, corrosion assessment, medical imaging (tumor/lesion)
- **Calibration** — known-dimension reference object in frame → px/mm conversion factor

**What this skill does NOT cover:**

- Simple bounding-box count without area → `detect-and-analyze`
- Image-level pass/fail verdict → `classify-or-flag` (M4)
- Text or label extraction → `read-text` (M4)
- Object tracking across frames → `track-and-count` (M4)

**Important precision limit.** Pixel measurements are proxies. Physical units (mm, cm²) require a calibration reference (an object of known dimensions) visible in the same frame as the target. Always state this limit before reporting a physical measurement.

</objective>

<methodology>

Steps 1, 2, 5, 7, and 8 follow the generic sequence in `skills/_shared/fde-methodology.md`. Read that file first. This section documents only the segmentation-specific additions.

**Step 3 — Foundation-model-first (segmentation-specific).**

Try SAM zero-shot before any labeling or fine-tuning:

- **SAM (Segment Anything Model)** — zero-shot instance segmentation; available via Roboflow Workflows. No labeled masks required for initial evaluation.
- Run SAM zero-shot on 20 user images → measure mean IoU against any available ground-truth masks (or user visual inspection for unlabeled sets).

Universe search when SAM zero-shot IoU < threshold:

```
universe_search: "<object> segmentation masks>200 sort:stars"
```

Present 2–3 results with image count, license, a one-line relevance note. Let user pick before fetching.

**Step 4 — Measure against the eval (segmentation metrics).**

Report all applicable metrics:

- **mAP@50 (mask)** — standard segmentation quality metric on validation set
- **Mean IoU** — for single-class problems or when ground-truth masks are available
- **Area error (%)** — when physical measurement is the goal: `|predicted_area - gt_area| / gt_area`

Non-negotiable format:

> "SAM zero-shot on 20 of your crack images: mean IoU = 0.71, area error = 18%. Your threshold is IoU ≥ 0.85 — missed by 14 points."

Never soften. Numbers only.

**Step 5 — Levers (segmentation-specific ordering).**

Same generic order as `fde-methodology.md` (threshold sweep → fine-tune → full train), plus:

1. **SAM prompt tuning** (zero label cost) — point prompts, box prompts. Often closes 10–20 IoU points before any labeling. Try box-prompt mode first; report delta.
2. **Fine-tune on SAM checkpoint** — `versions_generate` → `models_train` with segmentation dataset. Always show credit estimate; wait for explicit yes before calling `models_train`.
3. **Full custom train from scratch** — only if SAM transfer fails after prompt tuning + fine-tune. Use `rfdetr-seg-medium` (verify model_id from `roboflow://skills/training-and-evaluation` before use — see `skills/_shared/model-selection.md`, Instance Segmentation section, placeholder IDs).

**Step 6 — Measurement from mask.**

After obtaining masks, compute area and shape measurements. Include this helper in the PoC script:

```python
import cv2
import numpy as np


def mask_measurements(mask_array: np.ndarray, px_per_mm: float | None = None) -> dict:
    """
    mask_array: binary uint8 array (H×W), 1 = object pixel.
    px_per_mm:  calibration factor (pixels per mm). None → report px only.
    """
    area_px = int(mask_array.sum())
    contours, _ = cv2.findContours(
        mask_array, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE
    )
    if not contours:
        return {"area_px": area_px, "area_mm2": None, "perimeter_px": None}
    c = max(contours, key=cv2.contourArea)
    perimeter_px = float(cv2.arcLength(c, closed=True))
    x, y, w, h = cv2.boundingRect(c)
    aspect_ratio = round(w / h, 3) if h > 0 else None
    compactness = (
        round(4 * np.pi * area_px / (perimeter_px**2), 4) if perimeter_px > 0 else None
    )
    area_mm2 = round(area_px / (px_per_mm**2), 3) if px_per_mm else None
    return {
        "area_px": area_px,
        "area_mm2": area_mm2,  # None when px_per_mm not provided
        "perimeter_px": round(perimeter_px, 1),
        "aspect_ratio": aspect_ratio,
        "compactness": compactness,  # 1.0 = circle; lower = elongated/irregular
    }
```

Always state the calibration limit when reporting area_mm2:

> "area_mm2 requires a known-dimension reference object visible in the same frame."

**Crack width measurement (when requested):** Skeletonize the mask (`skimage.morphology.skeletonize`), sample perpendicular cross-sections along the centerline, measure cross-section width in pixels. Convert to mm via px_per_mm if calibration reference is present.

**Step 6 — Artifact: `segment_measure.py`** — inference + mask measurement script; `eval_definition.md` with IoU threshold and calibration method.

</methodology>

<artifact>

Produce these two user-owned, portable files at Step 6.

**`segment_measure.py`** — inference + measurement script:

```python
import requests, json, base64, sys, numpy as np, cv2
from pathlib import Path

# ponytail: no SDK — stdlib + requests + numpy + opencv only
WORKSPACE = "<workspace>"
PROJECT = "<project>"
VERSION = "<version>"
API_KEY = "<from ROBOFLOW_API_KEY env>"
PX_PER_MM = None  # set from calibration reference; None = pixel output only


def segment_image(image_path: str) -> dict:
    with open(image_path, "rb") as f:
        img_b64 = base64.b64encode(f.read()).decode()
    resp = requests.post(
        f"https://outline.roboflow.com/{WORKSPACE}/{PROJECT}/{VERSION}",
        params={"api_key": API_KEY},
        json={"image": img_b64},
    )
    resp.raise_for_status()
    preds = resp.json().get("predictions", [])
    results = []
    for p in preds:
        # Build binary mask from polygon points
        pts = np.array(
            [[pt["x"], pt["y"]] for pt in p.get("points", [])], dtype=np.int32
        )
        h = resp.json().get("image", {}).get("height", 1000)
        w = resp.json().get("image", {}).get("width", 1000)
        mask = np.zeros((h, w), dtype=np.uint8)
        if len(pts):
            cv2.fillPoly(mask, [pts], 1)
        measurements = mask_measurements(mask, PX_PER_MM)
        results.append(
            {"class": p.get("class"), "confidence": p.get("confidence"), **measurements}
        )
    return {"path": image_path, "predictions": results}


def mask_measurements(mask_array, px_per_mm=None):
    area_px = int(mask_array.sum())
    contours, _ = cv2.findContours(
        mask_array, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE
    )
    if not contours:
        return {"area_px": area_px, "area_mm2": None, "perimeter_px": None}
    c = max(contours, key=cv2.contourArea)
    perimeter_px = float(cv2.arcLength(c, closed=True))
    area_mm2 = round(area_px / (px_per_mm**2), 3) if px_per_mm else None
    return {
        "area_px": area_px,
        "area_mm2": area_mm2,
        "perimeter_px": round(perimeter_px, 1),
    }


if __name__ == "__main__":
    for path in sys.argv[1:]:
        print(json.dumps(segment_image(path)))
```

**`eval_definition.md`**:

```markdown
# Eval — <problem-title>
Date: <ISO8601>
Target class(es): <class list>
IoU threshold (mean): ≥ <N>
mAP@50 (mask) threshold: <N>%
Area error ceiling: ≤ <N>%   # when physical measurement is the goal
Calibration method: <reference object size in mm, or "pixel output only">
Dataset split: <N> images, source: <fixture or user data>
Threshold logic: max(SAM zero-shot baseline, business floor)
```

Also write `.vision-delivery/detections.jsonl` (one JSON line per image) — downstream skills consume this.

</artifact>

\<model_pick>

See `skills/_shared/model-selection.md` for the full decision tree and exact model_id values.

Quick reference for segmentation:

- First attempt: SAM zero-shot (no labels needed) via Roboflow Workflows
- Fine-tune on SAM checkpoint when zero-shot IoU < threshold
- Custom train from scratch: `rfdetr-seg-medium` (verify model_id from `roboflow://skills/training-and-evaluation` before first use — Instance Segmentation section in `skills/_shared/model-selection.md` uses placeholder IDs)

\</model_pick>

\<safe_actions>

Follow the safe-action gates in `skills/_shared/fde-methodology.md` exactly. Quick reference:

- `models_train` → credit estimate + explicit yes required, same turn
- `versions_generate` → free but irreversible; state augmentation config before calling
- Image upload → state destination; offer local path if user declines
- `project_deployment_launch` → not in this skill; seam offer hands to deployment-consultant

\</safe_actions>

<ledger>

Follow the write protocol in `skills/_shared/ledger-protocol.md`. Write one record per action, append-only to `.vision-delivery/ledger.jsonl`.

Action triggers for this skill:

| Trigger                                                      | `action` value              | What to put in `notes`                            |
| ------------------------------------------------------------ | --------------------------- | ------------------------------------------------- |
| `eval_definition.md` written and user confirmed              | `eval_definition`           | target classes, IoU threshold, calibration method |
| First SAM zero-shot or `models_infer` returns IoU result     | `baseline_measured`         | `mean_IoU=X, area_error=Y%`                       |
| `models_train` MCP call submitted                            | `models_train`              | model name, checkpoint, dataset version           |
| Deployment launched (via seam offer → deployment-consultant) | `project_deployment_launch` | deployment_id, endpoint URL                       |

`entity_id` format: `<workspace>/<project>` for projects; `<workspace>/<project>/<version>` when version is known.

</ledger>

<voice>

Follow voice rules from `skills/_shared/fde-methodology.md`. Short reference:

**Do:**

- "SAM zero-shot on 20 images: mean IoU = 0.71 — threshold is 0.85. Missed by 14 points. Fastest lever: SAM box-prompt tuning first."
- "Fine-tuned model passes: mean IoU = 0.87, area error = 9%. Threshold was IoU ≥ 0.85."
- "Calibration reference detected: 50 mm ruler = 312 px → px/mm = 6.24. Area outputs now in mm²."

**Do not:**

- "Looks great!" / "This should work!" / "Great use case!"
- Report passing when threshold not cleared.
- Claim physical measurements (mm, cm²) without a confirmed calibration reference in frame.
- Mention managed deployment, pricing, or cost in Phase 1 (seam offer fires once at eval-pass only).

</voice>
