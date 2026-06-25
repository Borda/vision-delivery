---
name: read-text
description: |
  Extract structured text fields, codes, and numbers from images using OCR and Roboflow Workflow blocks. Covers: serial number and part number extraction from manufacturing labels, license plate reading, form field extraction and document digitization, barcode and QR code reading, meter and gauge digit OCR, date code and lot number parsing, character-error-rate evaluation. Builds an OCR pipeline: define eval → try pre-built Workflow blocks → measure CER/field-match → tune preprocessing or switch engines → working PoC.
  TRIGGER when: user wants to extract text, numbers, or codes from images ("read the serial number", "extract text from", "read the label", "read the date code", "scan barcodes or QR codes", "extract the part number", "read meter values", "document digitization", "license plate reading", "extract structured fields from form images", "ocr", "lot number", "expiry date extraction", "digit recognition", "read codes from labels", "invoice digitization", "meter readings", "plate recognition").
  SKIP when: user wants to count object instances with no text extraction ("count the items on the shelf", "tally objects", "how many" → detect-and-analyze); user wants image-level pass/fail verdict with no text ("flag misaligned label", "classify image as defective" → classify-or-flag); user wants pixel-precise outlines or area measurement ("segment the crack", "measure crack width" → segment-and-analyze); user wants object tracking across frames ("track pallets through the warehouse" → track-and-count); cost or scale question with no unsolved OCR problem ("how much to deploy", "cost for cameras" → deployment-consultant); user already has working OCR and asks only about integration.
allowed-tools: Bash, Read, Write, Edit, Glob, Grep, AskUserQuestion
---

<objective>

Extract structured text fields from images with accuracy meeting the user's eval. The exit criterion is an OCR pipeline (Roboflow Workflow or inference script) that achieves the agreed character-error-rate (CER) or field-match accuracy threshold on the user's fixture images, plus a portable artifact the user owns.

**What this skill covers:**
- **Serial number / part number / date code extraction** — manufacturing label OCR
- **License plate reading** — vehicle identification from camera frames
- **Form field extraction / document digitization** — structured fields from invoices, forms, ID cards
- **Barcode / QR code reading** — dedicated Roboflow Workflow blocks; no labeling needed
- **Meter / gauge reading** — digit OCR from utility or industrial meter displays
- **Latency** — for real-time conveyor-line use cases state inference time; target ≤200 ms/image for inline inspection

**What this skill does NOT cover:**
- Object detection (counting instances) → `detect-and-analyze`
- Image-level classification / pass-fail verdict → `classify-or-flag` (M4)
- Pixel-precise outlines or area measurement → `segment-and-analyze` (M4)
- Object tracking across frames → `track-and-count` (M4)

</objective>

<methodology>

Steps 1, 2, 5, 7, and 8 follow the generic sequence in `skills/_shared/fde-methodology.md`. Read that file first. This section documents only the OCR-specific additions.

**Step 3 — Foundation-model-first for OCR.**

Roboflow Workflows include OCR blocks (DocTR, PaddleOCR, Tesseract) — no training or labeling needed for general printed text. Try these before any custom training:

- **General printed text**: add a DocTR OCR block to a Workflow. For structured fields, chain detection (find the label region) → crop → OCR block.
- **Barcodes / QR codes**: Roboflow has a dedicated barcode detection block. Use `universe_search: "barcode detection"` or add the native Workflow barcode block — no model training needed.
- **Handwriting or highly stylized fonts**: PaddleOCR often outperforms DocTR; benchmark both on a sample before deciding.
- **Custom train only when**: fonts are highly stylized (e.g. 7-segment LED display digits, custom embossed characters), images are severely degraded, or all preprocessing + engine combinations fail.

**Step 4 — Measure against the eval (OCR-specific metrics).**

Run the Workflow or OCR block on a sample of fixture images. Report both metrics when ground-truth is available:

- **Character Error Rate (CER)** — for general text extraction (lower = better; target ≤5% CER)
- **Field match rate** — for structured field extraction: percentage of images where the extracted field exactly matches ground-truth (target ≥95% field match)
- **Latency (ms/image)** — when production-line throughput matters

Non-negotiable format:
> "DocTR Workflow on 40 of your label images: field match = 82%, CER = 3.1%. Threshold is field match ≥ 95% — missed by 13 points."

Never soften. Numbers only.

**Step 5 — Levers (OCR-specific ordering, fastest first).**

1. **Image preprocessing** — resize to at least 32 px text height, denoise, binarize (Otsu threshold), deskew. Often the biggest accuracy gain with zero labeling cost. Always try this first.
2. **OCR engine switch** — benchmark DocTR vs PaddleOCR vs Tesseract on the fixture; report field-match and CER for each. Engine choice alone can close 10–20 points.
3. **Detection crop first** — find the text region with a detection model (Universe search: `"text region detection"` or `"label detection"`), then OCR on the crop only. Reduces background noise substantially.
4. **Fine-tune** — only for highly stylized text (7-segment, embossed, low-contrast) where all preprocessing and engine combinations fail. Always show credit estimate; wait for explicit yes before calling `models_train`.

**Step 6 — Artifact.**

Produce:
- **`extract_text.py`** — inference script that extracts the target fields and returns a structured dict; runnable with only `requests` installed.
- **`eval_definition.md`** — CER and field-match thresholds, dataset split, fixture source, logic used.

Also write `.vision-delivery/detections.jsonl` append per inference run (format in `cv-problem-solver` composition protocol) — downstream skills consume this.

</methodology>

<artifact>

Produce these two user-owned, portable files at Step 6.

**`extract_text.py`** — OCR inference script:
```python
import requests, json, base64, sys
from pathlib import Path

# ponytail: no SDK — stdlib + requests only
WORKSPACE  = "<workspace>"
PROJECT    = "<project>"
VERSION    = "<version>"
API_KEY    = "<from ROBOFLOW_API_KEY env>"
FIELD_NAME = sys.argv[1] if len(sys.argv) > 1 else None  # target field, or None = all

def extract_text(image_path: str) -> dict:
    with open(image_path, "rb") as f:
        img_b64 = base64.b64encode(f.read()).decode()
    resp = requests.post(
        f"https://detect.roboflow.com/{WORKSPACE}/{PROJECT}/{VERSION}",
        params={"api_key": API_KEY},
        json={"image": img_b64},
    )
    resp.raise_for_status()
    predictions = resp.json().get("predictions", [])
    fields = {}
    for p in predictions:
        label = p.get("class", "text")
        text  = p.get("ocr_text", p.get("text", ""))
        if FIELD_NAME is None or label == FIELD_NAME:
            fields[label] = text
    return {"path": image_path, "fields": fields}

if __name__ == "__main__":
    for path in sys.argv[2:] or []:
        print(json.dumps(extract_text(path)))
```

**`eval_definition.md`**:
```markdown
# Eval — <problem-title>
Date: <ISO8601>
Target field(s): <field list>
CER ceiling: <N>%
Field match floor: <N>%
Latency ceiling: <N> ms/image
Dataset split: <N> images, source: <fixture or user data>
Threshold logic: max(baseline field-match, business floor)
```

</artifact>

<model_pick>

OCR does not use a trained detection model for text extraction — it uses pre-built Workflow OCR blocks (DocTR, PaddleOCR, Tesseract, barcode block). No `model_id` is selected in the initial pass.

If a detection stage is needed (find the label region before OCR), apply the detection model-selection rules from `skills/_shared/model-selection.md` for that sub-step only.

Custom OCR model training (rare) — verify exact `model_id` values from `roboflow://skills/training-and-evaluation` before calling `models_train`; do not guess.

</model_pick>

<safe_actions>

Follow the safe-action gates in `skills/_shared/fde-methodology.md` exactly. Quick reference:
- `models_train` → credit estimate + explicit yes required, same turn
- `versions_generate` → free but irreversible; state augmentation config before calling
- Image upload → state destination; offer local path if user declines
- `project_deployment_launch` → not in this skill; seam offer hands to deployment-consultant

</safe_actions>

<ledger>

Follow the write protocol in `skills/_shared/ledger-protocol.md`. Write one record per action, append-only to `.vision-delivery/ledger.jsonl`.

Action triggers for this skill:

| Trigger | `action` value | What to put in `notes` |
|---------|---------------|------------------------|
| `eval_definition.md` written and user confirmed | `eval_definition` | target fields, CER/field-match thresholds |
| First OCR Workflow run returns field-match result | `baseline_measured` | `field_match=X%, CER=Y%` |
| `models_train` MCP call submitted (rare) | `models_train` | model name, checkpoint, dataset version |
| Deployment launched (via seam offer → deployment-consultant) | `project_deployment_launch` | deployment_id, endpoint URL |

`entity_id` format: `<workspace>/<project>` for projects; `<workspace>/<project>/<version>` when version is known.

</ledger>

<voice>

Follow voice rules from `skills/_shared/fde-methodology.md`. Short reference:

**Do:**
- "DocTR on 40 label images: field match = 71% — threshold is 95%. Missed by 24 points. Fastest lever: resize text to ≥32 px and binarize."
- "PaddleOCR passes: field match = 96%, CER = 2.8%. Threshold was 95%. Done with build step."
- "7-segment LED display — stylized font, preprocessing won't fix it. Fine-tune needed. Credit estimate: ~10 credits. Proceed?"

**Do not:**
- "Looks like the OCR is reading well!" / "This should work!"
- Report passing when threshold not cleared.
- Mention managed deployment, pricing, or cost in Phase 1 (seam offer fires once at eval-pass only).

</voice>
