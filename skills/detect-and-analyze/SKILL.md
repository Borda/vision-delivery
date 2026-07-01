---
name: detect-and-analyze
description: |
  Detect object instances and analyze them from bounding boxes. Covers: spatial counts per frame, measurements derived from bbox geometry (size, aspect ratio, relative position), per-object crops and ROI extraction, per-class metadata. Builds a detection pipeline: define eval → find pretrained model → measure → train if needed → working PoC.
  TRIGGER when: user wants to count object instances ("count the X", "how many X in image/frame", "detect and count", "counts trucks/people/items", "tally objects on a conveyor/line/belt", "number of X", "object tally", "build a detection model"); measure objects from their bounding boxes ("how wide are the boxes", "estimate size of items", "relative dimensions of parts", "bbox diagonal"); extract crops or regions of interest per detected object ("crop each detected face", "extract ROI per defect", "save each detected item separately"); get per-object metadata from detection output ("per-box confidence", "class breakdown by region", "which objects are in zone A"); build a detection pipeline for any of the above.
  SKIP when: user wants an image-level verdict with no per-instance count (("is this product defective?", "classify this image as pass/fail", "flag the whole image") → classify-or-flag); tracking object identities across frames ("track X as it moves through the scene", "follow this person", line-cross counting → track-and-count); pixel-precise outlines or area measurements requiring masks ("segment the tumor", "measure exact area of corrosion" → segment-and-analyze); reading or extracting text, labels, serial numbers from images (→ read-text); cost/scale/deployment question, self-hosting vs managed comparison, build-vs-buy analysis with no unsolved detection problem (→ estimate-economics); user already has a working model and asks only about export, optimization, or active learning.
allowed-tools: Bash, Read, Write, Edit, Glob, Grep, AskUserQuestion
---

<objective>

Build a working detection pipeline for the user's specific objects. The exit criterion is a model (or pretrained candidate) that passes the user's own eval and produces per-instance output the user can act on.

**What this skill covers (all derived from bbox output — no second inference pass needed):**

- **Spatial count** — how many instances of class X appear in a single image or frame
- **Measurement from bbox** — size proxies: diagonal, aspect ratio, relative area vs frame, width/height in normalized coordinates
- **Crops and ROI** — slice the image at each predicted bbox to extract one image per detected object
- **Per-class metadata** — confidence distribution, class breakdown, zone membership from bbox centroid

**What this skill does NOT cover:**

- Line-cross counting (object crosses a virtual line in video) → `track-and-count`
- Exact physical measurements in real-world units (cm, mm) → requires calibration data; route to `measure-in-image` if that skill exists, else handle as consulting scope
- Pixel-precise outlines or area → `segment-and-analyze`
- Image-level verdict ("is the whole image defective?") → `classify-or-flag`

</objective>

<methodology>

**RTSP / live-stream pre-check (fires before Step 3 if triggered).**

If the user's prompt mentions RTSP, an IP camera stream, 24/7 live inference, or any live-video source combined with cloud deployment intent — surface three honest options **immediately**, before any model search or eval definition:

```
"RTSP + live inference. Three paths — pick before we build:

 (a) Edge inference server — run an inference container on a local machine
     on the same network as the camera. Lowest latency, no cloud dependency.
     I give you the docker run command and the inference.py wrapper.

 (b) Frame-pull cloud — pull frames from the RTSP stream at an interval
     (e.g. 1 fps) and send each frame to a Roboflow cloud inference endpoint.
     Works today; adds ~100–500 ms round-trip latency per frame.
     Not suitable for real-time video, fine for periodic inspection.

 (c) Roboflow-managed edge device — Roboflow manages an edge device that
     runs inference locally and streams results to the cloud for aggregation
     and monitoring. No local infra ops. Ask me to show live device options.

Which fits your latency, connectivity, and ops constraints?"
```

Do NOT hard-code "cloud RTSP not supported" as a permanent fact — verify current Roboflow platform status before baking in a limitation. After the user picks a path, continue to Step 1.

Steps 1, 2, 5, 7, and 8 follow the generic sequence in `skills/_shared/fde-methodology.md`. Read that file first. This section documents only the detection-specific additions.

**Step 3 — Foundation-model-first (detection-specific).**

Check COCO 80 coverage before searching Universe (full list in `skills/_shared/model-selection.md`).

If the class is in COCO 80:

- Use `rfdetr-medium` (non-real-time, mAP priority) or `rfdetr-nano` (real-time, latency priority).
- No Universe search needed — proceed directly to Step 4.

If NOT in COCO 80:

```
universe_search: "<object-type> detection images>200 sort:stars"
```

Present 2–3 results with image count, license, and a one-line relevance note. Let the user pick before fetching. Then measure on their samples (Step 4).

**Step 4 — Measure against the eval (detection-specific metrics).**

Run inference via `models_infer`. Report all three metrics if ground-truth is available:

- **mAP@50** — detection quality on validation set
- **Per-class recall** vs the user's recall threshold
- **Count MAE per frame** — mean absolute error between predicted count and ground-truth count

Non-negotiable format:

> "Pretrained model on 40 of your images: mAP@50 = 61%, recall = 73%, count MAE = 1.4. Your threshold is 80% recall — missed by 7 points."

**Step 4b — Measurement from bbox (when requested).**

If the user wants size or position measurements from detected objects, derive them from the bbox output without a second inference pass:

```python
def bbox_measurements(pred: dict, frame_w: int, frame_h: int) -> dict:
    w, h = pred["width"], pred["height"]
    x, y = pred["x"], pred["y"]
    return {
        "aspect_ratio": round(w / h, 3) if h > 0 else None,
        "diagonal_px": round((w**2 + h**2) ** 0.5, 1),
        "relative_area": round((w * h) / (frame_w * frame_h), 4),
        "centroid_norm": (round(x / frame_w, 3), round(y / frame_h, 3)),
    }
```

State the precision limit: bbox measurements are size proxies, not calibrated physical measurements. If the user needs mm/cm units, they need calibration data (known reference object in frame).

**Step 5 — Levers (detection-specific ordering).**

Same generic order as `fde-methodology.md` (threshold sweep → fine-tune → full train), plus:

- **Universe checkpoint fine-tune**: use `checkpoint: "universe/<workspace>/<project>/<version>"` when a close Universe model exists. Fewer labeled images needed (50–100 vs 200+ from scratch).
- **Model size trade-off**: if latency fails after mAP passes, try `rfdetr-nano` or `yolov11n` before accepting a mAP drop. Report both latency and mAP impact.

**Improvement sub-flow (when threshold sweep and checkpoint fine-tune haven't closed the gap).**

Gates fire in order — never skip to a later gate:

**Gate 2 — Hard-negative mining.**
1. Pull per-image failure breakdown: `model_evals_get_image_predictions` on the eval version.
2. Report failure clusters by class, object size, lighting, angle — not a raw dump.
3. Create annotation job on the worst-N images: `annotation_jobs_create` with project=<project>, images=[<image_ids_from_eval>], batch_name="hard-negatives-<date>".
4. Once relabeled, `versions_generate` with hard negatives in training split; re-train (`models_train` — credit estimate first) and re-measure against the eval.

**Gate 3 — Augmentation strategy.**
Ask one targeted question: "What does live footage look like that your test set doesn't cover?"

Match augmentation to the stated gap — never apply a generic preset:

| Gap | Augmentations |
|-----|---------------|
| Lighting variation | Brightness ±30%, Exposure ±25% |
| Motion blur / defocus | Blur 0–3 px |
| Camera angle variation | Rotation ±15°, Horizontal flip |
| Scale or distance change | Zoom 0–20% |
| Color / weather variation | Hue ±15°, Saturation ±25% |

Call `versions_generate` with the selected augmentations. State augmentation config before calling (irreversible). Re-train and report delta mAP/recall vs prior run.

**Gate 4 — Relabel.** Only when Gates 2–3 haven't closed the gap. Return to Annotation Unblocking flow in `fde-methodology.md`. Minimum: 50 images per class for fine-tune; 200+ for full train from scratch.

**Active learning path (deployed model receiving live production frames).**
When user reports failures on live footage not in their test set:
1. Diagnose distribution shift — compare train domain vs production (class balance, lighting, angles, scale).
2. Surface `autolabel_start` to auto-label hard cases for the next round: project=<project>, model=<deployment_id>.
3. Feed labeled batch back to Gate 2 for the next iteration.

**Step 6 — Counting and ROI layer.**

**Count**: `len([p for p in predictions if p["class"] == target])` after NMS (applied by default by Roboflow inference). Multi-class: per-class count dict. Single-class: scalar.

**Dedup / NMS tuning**: if count is inflated by overlapping boxes, tune via `overlap` parameter on the inference endpoint (default 0.3). Report any tuning explicitly.

**Crops**: for ROI extraction, slice with `img.crop((x - w/2, y - h/2, x + w/2, y + h/2))` per prediction. Include in PoC script on request.

**Zone membership**: assign each detection to a spatial zone by centroid: `zone = "A" if pred["x"] / frame_w < 0.5 else "B"`.

</methodology>

<artifact>

Produce these two user-owned, portable files at Step 6.

**`detect_analyze.py`** — inference + analysis script:

```python
import requests, json, base64, sys
from pathlib import Path

# ponytail: no SDK — stdlib + requests only
WORKSPACE = "<workspace>"
PROJECT = "<project>"
VERSION = "<version>"
API_KEY = "<from ROBOFLOW_API_KEY env>"
TARGET = sys.argv[1] if len(sys.argv) > 1 else None  # None = all classes


def analyze_image(image_path: str) -> dict:
    with open(image_path, "rb") as f:
        img_b64 = base64.b64encode(f.read()).decode()
    resp = requests.post(
        f"https://detect.roboflow.com/{WORKSPACE}/{PROJECT}/{VERSION}",
        params={"api_key": API_KEY},
        json={"image": img_b64},
    )
    resp.raise_for_status()
    preds = resp.json()["predictions"]
    img_w = resp.json().get("image", {}).get("width", 1)
    img_h = resp.json().get("image", {}).get("height", 1)

    filtered = [p for p in preds if TARGET is None or p["class"] == TARGET]
    counts = {}
    for p in filtered:
        counts[p["class"]] = counts.get(p["class"], 0) + 1

    return {
        "path": image_path,
        "count": counts.get(TARGET, 0) if TARGET else sum(counts.values()),
        "per_class": counts,
        "predictions": filtered,
    }


if __name__ == "__main__":
    for path in sys.argv[2:] or []:
        print(json.dumps(analyze_image(path)))
```

**`eval_definition.md`**:

```markdown
# Eval — <problem-title>
Date: <ISO8601>
Target class(es): <class list>
Recall floor: <N>%
Count MAE ceiling: <N> per frame
mAP@50 threshold: <N>%
Dataset split: <N> images, source: <fixture or user data>
Threshold logic: max(baseline mAP, business floor)
```

Also write a `.vision-delivery/detections.jsonl` append per inference run (format in the `solve-cv-task` composition protocol) — downstream skills consume this.

</artifact>

\<model_pick>

See `skills/_shared/model-selection.md` for the full decision tree and exact model_id values.

Quick reference for detection:

- COCO 80 class + non-RT → `rfdetr-medium`
- COCO 80 class + real-time → `rfdetr-nano`
- Custom class, first PoC → Rapid or `rfdetr-medium` fine-tune
- Edge / latency critical → `yolov11n`
- Max accuracy → `rfdetr-large`

\</model_pick>

\<safe_actions>

Follow the safe-action gates in `skills/_shared/fde-methodology.md` exactly. Quick reference:

- `models_train` → quantified credit estimate + explicit yes required, same turn (format in `fde-methodology.md` Safe Actions)
- `versions_generate` → free but irreversible; state augmentation config before calling
- Image upload → state destination; offer local path if user declines
- `project_deployment_launch` → not in this skill; seam offer hands to `estimate-economics`

\</safe_actions>

<ledger>

Follow the write protocol in `skills/_shared/ledger-protocol.md`. Write one record per action, append-only to `.vision-delivery/ledger.jsonl`.

Action triggers for this skill:

| Trigger                                                   | `action` value              | What to put in `notes`                  |
| --------------------------------------------------------- | --------------------------- | --------------------------------------- |
| `eval_definition.md` written and user confirmed           | `eval_definition`           | target classes, threshold               |
| First `models_infer` call returns mAP result              | `baseline_measured`         | `mAP@50=X%, MAE=Y`                      |
| `models_train` MCP call submitted                         | `models_train`              | model name, checkpoint, dataset version |
| Deployment launched (via seam offer → estimate-economics) | `project_deployment_launch` | deployment_id, endpoint URL             |

`entity_id` format: `<workspace>/<project>` for projects; `<workspace>/<project>/<version>` when version is known.

</ledger>

<voice>

Follow voice rules from `skills/_shared/fde-methodology.md`. Short reference:

**Do:**

- "mAP@50 = 61% — threshold is 80%. Missed by 19 points. Fastest lever: confidence sweep first."
- "Pretrained model passes: 84% recall, threshold was 80%. Count MAE = 0.9 per frame."
- "Non-COCO class, 3 custom targets — use Rapid for the first PoC; no OCR, no fine-grained defects. Go."

**Do not:**

- "Looks good!" / "This should work!" / "Great use case!"
- Report passing when threshold not cleared.
- Mention managed deployment, pricing, or cost during the build flow (seam offer fires once at eval-pass only).

</voice>
