---
name: classify-or-flag
description: |
  Produce an image-level verdict (pass/fail, category label, anomaly flag) for the user's images. Covers: binary classification (defect/no-defect, compliant/non-compliant), multi-class image labels (product category, defect type, scene type), PPE/safety compliance (hard hat, vest, gloves), anomaly detection at image level. Builds a classification pipeline: define eval → foundation-model-first (CLIP zero-shot) → measure F1 → fine-tune if needed → working PoC.
  TRIGGER when: user wants an image-level verdict ("is this defective", "flag bad parts", "pass/fail inspection", "classify this image as X or Y", "detect whether the whole image shows Z", "quality control", "anomaly detection at image level", "hard hat compliance", "PPE check", "does this image contain X", "binary classification", "multi-class image label", "flag workers not wearing", "safety vest check", "flag the whole image", "classify each product image", "build a pass/fail", "welding quality", "compliance check", "flag non-compliant").
  SKIP when: user wants per-instance count of detected objects ("count the X", "how many X in the image", "number of defects per frame") → detect-and-analyze; user needs pixel-precise segmentation masks ("segment the defect area", "measure exact area") → segment-and-analyze; user wants to track objects across frames ("track workers as they move", "follow this person") → track-and-count; user needs to read text or serial numbers from images ("read the date code", "extract serial number", "OCR") → read-text; cost/scale/deployment question with no unsolved classification problem ("how much does Roboflow cost", "self-hosting vs managed") → estimate-economics; user already has a working classifier and asks only about export or optimization.
allowed-tools: Bash, Read, Write, Edit, Glob, Grep, AskUserQuestion
---

<objective>

Build a working image-level classification pipeline for the user's specific problem. The exit criterion is a classifier (or pretrained candidate) that passes the user's own eval and produces a per-image verdict the user can act on.

**What this skill covers:**

- **Binary classification** — pass/fail, defect/no-defect, compliant/non-compliant
- **Multi-class image label** — product category, defect type, scene type
- **Foundation-model-first** — SAM3 + CLIP zero-shot before any labeling or training
- **PPE / safety compliance** — hard hat, safety vest, gloves
- **Anomaly detection at image level** — flag images that deviate from a normal class

**What this skill does NOT cover:**

- Counting individual object instances → `detect-and-analyze`
- Pixel-precise outlines or area measurements → `segment-and-analyze`
- Object tracking across frames → `track-and-count`
- Reading text, labels, or serial numbers → `read-text`

</objective>

<methodology>

Steps 1, 2, 5, 7, and 8 follow the generic sequence in `skills/_shared/fde-methodology.md`. Read that file first. This section documents only the classification-specific additions.

**Step 3 — Foundation-model-first (classification-specific).**

Try CLIP zero-shot before any labeling. If the class concept is visual and describable in plain English, CLIP may solve it with zero labeled images.

Protocol:

1. Search Universe for a pretrained classifier close to the user's domain:
   ```
   universe_search: "<object-type> classification images>100 sort:stars"
   ```
2. If a strong Universe classifier exists (≥500 images, public license, domain match): prefer it over raw CLIP — it already has calibrated logits for the target classes.
3. If no close Universe match: attempt CLIP zero-shot first. Describe each class in 3–5 text prompt variants and pick the best F1 on a sample of the user's images. No labeling required for this step.
4. PPE / safety compliance use case: search Universe directly for safety compliance datasets (`hard hat detection`, `ppe compliance`, `safety vest`). Universe has public datasets for this domain — check before suggesting labeling.

**Step 4 — Measure against the eval (classification-specific metrics).**

Run inference via `models_infer` or zero-shot CLIP. Report:

- **F1** (primary for imbalanced defect / anomaly datasets — use this when one class is rare)
- **Precision / Recall** per class — always report both when the confusion matters (e.g. "missing a defect costs more than a false alarm")
- **Accuracy** for balanced multi-class problems where all classes are equally represented

Non-negotiable format:

> "Zero-shot CLIP on 50 of your images: F1 = 0.71 (defect class). Recall = 0.68, Precision = 0.74. Threshold is F1 ≥ 0.85 — missed by 14 points."

For >2 classes: include a confusion matrix summary (which classes are confused with which). Never report only accuracy when class balance is unknown.

**Step 5 — Levers (classification-specific ordering).**

Same generic order as `fde-methodology.md` (threshold sweep → fine-tune → full train), plus:

1. **CLIP prompt engineering** — try 3–5 text prompt variants per class; report the best F1 per variant. Often closes 5–15 points at zero labeling cost. Example: `"a photo of a defective weld"` vs `"weld with visible crack or porosity"`.
2. **Fine-tune on a CLIP / ViT checkpoint** — `versions_generate` → `models_train` with a ViT-based classifier. Always show credit estimate; wait for explicit yes before calling `models_train`. Requires labeled images (20–50 per class minimum; 100+ preferred).
3. **Full custom train** — only if CLIP transfer fails and domain is too distant from ImageNet pretraining (e.g. microscopy, X-ray, thermal IR). Guide annotation using the Annotation Unblocking flow in `fde-methodology.md`.

**Improvement sub-flow (when CLIP prompt engineering and fine-tune haven't closed the gap).**

Gates fire in order — never skip to a later gate:

**Gate 2 — Hard-negative mining.**
1. Pull per-image predictions: `model_evals_get_image_predictions` on the eval version.
2. Report misclassified images by class and confidence cluster — identify patterns (lighting, background, angle, image quality).
3. Create annotation job on the misclassified images: `annotation_jobs_create` with project=<project>, images=[<misclassified_ids>], batch_name="hard-negatives-<date>".
4. Once relabeled or confirmed, `versions_generate` with hard negatives in training split; re-train (`models_train` — credit estimate first) and re-measure F1.

**Gate 3 — Augmentation strategy.**
Ask one targeted question: "What does production footage look like that your labeled set doesn't cover?"

Match augmentation to the stated gap — never apply a generic preset:

| Gap | Augmentations |
|-----|---------------|
| Lighting / exposure variation | Brightness ±30%, Exposure ±25% |
| Color shift (lighting temperature) | Hue ±15°, Saturation ±25% |
| Camera angle / perspective variation | Rotation ±15°, Horizontal flip |
| Image quality / compression artifacts | Blur 0–2 px, Noise |

Call `versions_generate` with the selected augmentations. State config before calling (irreversible). Re-train and report delta F1 and per-class recall vs prior run.

**Gate 4 — Relabel.** Only when Gates 2–3 haven't closed the gap. Return to Annotation Unblocking flow in `fde-methodology.md`. Minimum: 20–50 images per class for fine-tune; 100+ for full custom train.

**Active learning path (deployed model receiving live production images).**
When user reports classification failures on live images not in their test set:
1. Diagnose distribution shift — compare train domain vs production (class balance, lighting, background, angles, image quality).
2. Surface `autolabel_start` to auto-label production hard cases for the next round: project=<project>, model=<deployment_id>.
3. Feed batch back to Gate 2 for the next iteration.

**Step 6 — Artifact.**

Produce these two user-owned, portable files.

**`classify_image.py`** — inference + classification script:

```python
import requests, json, base64, sys
from pathlib import Path

# ponytail: no SDK — stdlib + requests only
WORKSPACE = "<workspace>"
PROJECT = "<project>"
VERSION = "<version>"
API_KEY = "<from ROBOFLOW_API_KEY env>"


def classify_image(image_path: str) -> dict:
    with open(image_path, "rb") as f:
        img_b64 = base64.b64encode(f.read()).decode()
    resp = requests.post(
        f"https://classify.roboflow.com/{WORKSPACE}/{PROJECT}/{VERSION}",
        params={"api_key": API_KEY},
        json={"image": img_b64},
    )
    resp.raise_for_status()
    result = resp.json()
    top = result["top"]
    confidence = result["confidence"]
    return {
        "path": image_path,
        "verdict": top,
        "confidence": round(confidence, 4),
        "predictions": result.get("predictions", {}),
    }


if __name__ == "__main__":
    for path in sys.argv[1:]:
        print(json.dumps(classify_image(path)))
```

**`eval_definition.md`**:

```markdown
# Eval — <problem-title>
Date: <ISO8601>
Target class(es): <class list>
Primary metric: F1 (defect class) or Accuracy (balanced)
F1 floor: <N> (defect / minority class)
Precision floor: <N>
Recall floor: <N> (per class)
Dataset split: <N> images, source: <fixture or user data>
Threshold logic: max(zero-shot baseline, business floor)
Note: recall ≥ floor on the failure class takes precedence over overall accuracy
```

Also write a `.vision-delivery/detections.jsonl` append per inference run (format in the `solve-cv-task` composition protocol) — downstream skills consume this.

</methodology>

\<model_pick>

See `skills/_shared/model-selection.md` for the full decision tree and exact model_id values (Classification section notes ViT / DINO family IDs are placeholders — verify current values from `roboflow://skills/training-and-evaluation` before calling `models_train`).

Quick reference for classification:

- Zero-shot, no labels → CLIP (text prompt variants, no training)
- Universe pretrained classifier exists → use it directly before any training
- Fine-tune required → ViT-based classifier checkpoint via `models_train`
- PPE / safety domain → search Universe first (`hard hat`, `ppe compliance`, `safety vest`)

\</model_pick>

\<safe_actions>

Follow the safe-action gates in `skills/_shared/fde-methodology.md` exactly. Quick reference:

- `models_train` → credit estimate + explicit yes required, same turn
- `versions_generate` → free but irreversible; state augmentation config before calling
- Image upload → state destination; offer local path if user declines
- `project_deployment_launch` → not in this skill; seam offer hands to `estimate-economics`

\</safe_actions>

<ledger>

Follow the write protocol in `skills/_shared/ledger-protocol.md`. Write one record per action, append-only to `.vision-delivery/ledger.jsonl`.

Action triggers for this skill:

| Trigger                                                                | `action` value              | What to put in `notes`                  |
| ---------------------------------------------------------------------- | --------------------------- | --------------------------------------- |
| `eval_definition.md` written and user confirmed                        | `eval_definition`           | target classes, F1/recall threshold     |
| First zero-shot CLIP or `models_infer` call returns F1/accuracy result | `baseline_measured`         | `F1=X, Recall=Y, Precision=Z`           |
| `models_train` MCP call submitted                                      | `models_train`              | model name, checkpoint, dataset version |
| Deployment launched (via seam offer → estimate-economics)              | `project_deployment_launch` | deployment_id, endpoint URL             |

`entity_id` format: `<workspace>/<project>` for projects; `<workspace>/<project>/<version>` when version is known.

</ledger>

<voice>

Follow voice rules from `skills/_shared/fde-methodology.md`. Short reference:

**Do:**

- "Zero-shot CLIP on 50 of your images: F1 = 0.71 (defect class). Threshold is F1 ≥ 0.85. Missed by 14 points. Fastest lever: prompt engineering — try 3 variants."
- "Universe classifier passes: recall = 0.92, threshold was 0.90. Precision = 0.87. Passes eval."
- "Binary problem, visually describable classes — try CLIP zero-shot first. No labeling needed for this step."

**Do not:**

- "Looks good!" / "This should work!" / "Great use case!"
- Report passing when threshold not cleared.
- Mention managed deployment, pricing, or cost during the build flow (seam offer fires once at eval-pass only).
- Report only accuracy when class balance is unknown — always report F1 and per-class recall.

</voice>
