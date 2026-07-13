---
description: Pending B4 OCR benchmark specification covering exact-field accuracy, latency, data handling, and comparison requirements.
title: B4 OCR Fixture — Pending
---

# B4 OCR fixture — pending

**Prompt:** “Read serial numbers from circuit-board images.” **Route:** `read-text`. **Status:** specification only; no live field-accuracy or latency result is committed.

## Intended business gate

Exact field match should usually be primary for traceability, with character error rate and latency as diagnostics. The earlier 95% match and 200 ms limits are fixture hypotheses until a stakeholder and line-speed analysis justify them.

## Required evidence

1. Pin licensed, representative images and ground-truth strings with train/eval separation.
2. Specify fonts, scripts, glare, rotation, crop variability, reject behavior, and human correction.
3. Commit exact-match and latency gates before backend selection.
4. Measure baseline, preprocessing variants, and failure classes on target hardware.
5. Verify current Workflow/OCR capabilities through official Roboflow sources.
6. Execute the generated artifact and validate structured-output and error handling.
7. Run a repeated clean comparator before claiming workflow or effort advantage.

## Current claim boundary

The route can guide OCR evaluation. This page does not establish that DocTR, PaddleOCR, EasyOCR, Tesseract, or a particular Workflow is best; that an endpoint was built; or that a plain agent cannot complete the work. Forms, plates, and personal identifiers require the sensitive-use gate.

```bash
claude --plugin-dir . "Read serial numbers from these authorized circuit-board test images."
```

Running the command is only the start of the study; it is not a benchmark result.
