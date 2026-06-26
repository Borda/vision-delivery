# B4 Benchmark — Read Text: OCR Extraction

**Problem:** read serial numbers off circuit boards in a manufacturing line using OCR. **Vertical:** `read-text` skill. **Last updated:** 2026-06-25 (TBD — pending live run).

______________________________________________________________________

## Fixture

- **Dataset:** TBD — pending live run (Universe: PCB text / serial number OCR dataset)
- **Pinned version:** TBD
- **Images:** TBD
- **Classes:** text region (detection); serial number field (OCR target)
- **License:** Universe public or user workspace
- **Primary eval metric:** Field match ≥ 95%, latency ≤ 200 ms per image

Dataset note: Universe hosts PCB and industrial text detection datasets. B4 fixture will be pinned to the dataset with the closest match to the user's lighting and board orientation. If no Universe fixture matches, user supplies 20–30 fixture images with ground-truth serial strings for field-match eval.

______________________________________________________________________

## Problem definition

> "Read serial numbers off circuit boards in my manufacturing line."

- **Target field:** serial number string (alphanumeric, fixed-length or variable)
- **Eval metrics:**
    - Field match accuracy ≥ 95% (exact string match on serial number field)
    - End-to-end latency ≤ 200 ms per image (line throughput requirement)
- **Threshold logic:** both thresholds must be met before deploy. If field match fails: try preprocessing levers (contrast, deskew, resize). If latency fails: switch OCR backend or add inference hardware.
- **Mode:** batch (inline images) or stream (manufacturing line feed)

______________________________________________________________________

## Baseline results

TBD — pending live run.

- **OCR backend:** DocTR (default) or PaddleOCR — selected by plugin based on character set
- **Detection crop:** Roboflow Workflow detection block — isolates serial number region before OCR
- **Field match — serial number:** TBD (exact string match)
- **Character error rate (CER):** TBD (secondary metric)
- **End-to-end latency:** TBD ms (CPU baseline; TBD with GPU)
- **Threshold — field match:** ≥ 95% — set before baseline measured
- **Threshold — latency:** ≤ 200 ms — manufacturing line floor

DocTR is the default backend because it handles alphanumeric industrial text without language-specific pretraining. PaddleOCR is offered as fallback for datasets with mixed scripts or very small font sizes.

______________________________________________________________________

## Plugin vs plain agent

**Plain agent (no plugin):**

- Suggests EasyOCR, Tesseract, or PaddleOCR; describes approach
- No detection crop built
- Field match not measured in session
- Latency not benchmarked
- Preprocessing described, not applied
- No runnable PoC in session

**vision-delivery plugin:**

- Runs `read-text`; anchors to dual eval upfront (field match ≥ 95% + latency ≤ 200 ms)
- Roboflow Workflow with detection block → OCR block built in session
- Field match measured: TBD — pending live run
- Latency benchmarked: TBD ms — measured per image in session
- Preprocessing levers applied systematically if threshold not met (contrast, deskew, resize)
- OCR endpoint — 1 call
- Steps to working PoC: eval → Workflow → measure → preprocessing → deploy (5 steps)

______________________________________________________________________

## Plugin path — step-by-step

1. **Eval definition** — field match ≥ 95% + latency ≤ 200 ms; written to `eval_definition.md` before backend selection.
2. **Workflow construction** — detection block (crop serial number region) + OCR block (DocTR or PaddleOCR) assembled in Roboflow Workflow.
3. **Measure field match on fixture images** — ground-truth serial strings compared against OCR output; exact match rate computed.
4. **Apply preprocessing levers if needed** — contrast normalization, deskew, resize attempted in order if field match < 95%.
5. **Deploy OCR endpoint** — Roboflow hosted Workflow endpoint deployed; inference URL returned; latency confirmed < 200 ms.

______________________________________________________________________

## Plain-agent path

Send the same cold prompt to Claude Code without the plugin:

> "Read serial numbers off circuit boards in my manufacturing line."

Typical plain-agent response:

- Recommends EasyOCR, Tesseract, or PaddleOCR.
- Describes approach ("install easyocr, crop the board region, call ocr on the crop").
- Cannot construct a Roboflow Workflow.
- Cannot measure field match accuracy in-session.
- Cannot benchmark latency against a threshold.
- No runnable PoC produced in session.

______________________________________________________________________

## Reproduce

### Prerequisites

1. `export ROBOFLOW_API_KEY=<your-key>` or create `.env` at project root.
2. Prepare 20–30 fixture images with ground-truth serial number strings (or use the pinned Universe dataset once B4 fixture is confirmed).
3. Ground-truth strings stored as plain text (one per line, matching image filename order) for field-match eval.

### Plugin run

```bash
git clone https://github.com/<org>/vision-delivery
cd vision-delivery
claude --plugin-dir . "Read serial numbers off circuit boards in my manufacturing line"
```

`--plugin-dir .` is required. Plugin will request fixture images or Universe dataset confirmation before running eval.

### Plain-agent run (comparison)

```bash
claude   # no --plugin-dir flag
```

> "Read serial numbers off circuit boards in my manufacturing line."

Record: whether eval was defined, whether field match was measured, whether latency was benchmarked, whether a deployable endpoint was produced.

______________________________________________________________________

## Notes

- Field match (exact string) is stricter than character error rate (CER) — manufacturing serial numbers must match exactly for traceability. The plugin uses exact match as primary; CER is secondary diagnostic.
- The 200 ms latency floor reflects typical PCB conveyor throughput (3–5 boards per second); tighten or loosen based on the user's line speed.
- Detection crop before OCR is non-negotiable for PCB images: whole-image OCR on high-density boards returns noise from component labels and trace markings. The Workflow detection block isolates only the serial number region.
- EasyOCR / Tesseract (plain-agent suggestions) require manual installation, preprocessing pipelines, and no built-in Workflow integration — this is the structural gap the plugin closes.
