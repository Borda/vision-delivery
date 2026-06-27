---
description: Choose the right vision-delivery route for detection, classification, tracking, OCR, segmentation, pose, pipelines, and CV economics.
title: Use Cases
---

# Use Cases

`vision-delivery` routes a vague request to a concrete computer-vision task before model search starts. The route matters because each output type has a different eval metric and a different cheapest first baseline.

## Route Matrix

| User asks for                         | Route                       | Output shape                   | Primary measurements                    |
| ------------------------------------- | --------------------------- | ------------------------------ | --------------------------------------- |
| Count objects, defects, vehicles      | `detect-and-analyze`        | boxes and counts               | mAP@50, per-class count MAE             |
| Pass/fail or compliance flag          | `classify-or-flag`          | image-level label              | precision, recall, F1                   |
| Track people, dwell time, line-cross  | `track-and-count`           | identities and trajectories    | MOTA, dwell time MAE, line-cross counts |
| Read serials, labels, dates, barcodes | `read-text`                 | text fields                    | field match rate, CER, latency          |
| Segment cracks, lesions, corrosion    | `segment-and-analyze`       | masks and measurements         | mask mAP, IoU, area or width error      |
| Recognize posture, gesture, action    | `recognize-pose-or-gesture` | keypoints or gesture labels    | OKS mAP, gesture recall                 |
| Monitor a multi-step visual process   | `decompose-to-pipeline`     | typed handoffs between routes  | route-specific metrics                  |
| Price a project decision              | `estimate-economics`        | recommendation and assumptions | one-time assumptions and run-rate costs |

## Detection And Counting

Use `detect-and-analyze` when the output is one box per visible thing:

- count vehicles in a parking lot,
- count boxes on a conveyor,
- count visible defects,
- crop each detected part for downstream inspection.

Good evals include `mAP@50`, recall floor, and count mean absolute error.

## Classification And Flagging

Use `classify-or-flag` when the whole image or frame gets a verdict:

- compliant vs non-compliant,
- good vs defective,
- pass vs fail,
- anomaly vs normal.

Do not use this route when the user needs a count per instance. "How many defective items?" is detection; "Is this item defective?" is classification.

## Tracking And Counting Over Time

Use `track-and-count` when identity or time matters:

- dwell time,
- line crossing,
- zone entry and exit,
- following a person or object through frames.

Tracking usually needs detection first, then a tracker and zone or line logic.

## OCR And Text Extraction

Use `read-text` when the user needs characters:

- serial numbers,
- lot codes,
- expiry dates,
- license plates,
- meter readings.

Good evals include exact field match, character error rate, and latency.

## Segmentation And Measurement

Use `segment-and-analyze` when the user needs shape, area, contour, or pixel-level precision:

- crack width,
- corrosion area,
- lesion outline,
- object area.

Measurement claims require calibration when the user wants physical units such as millimeters.

## Pose And Gesture

Use `recognize-pose-or-gesture` when posture, skeleton, gesture, or action is the important signal:

- worker posture,
- fall detection,
- hand raises,
- form checking,
- gesture control.

Good evals include OKS mAP for keypoints and recall for safety-critical actions.

## Economics

Use `estimate-economics` after the build scope is clear or the eval passes. It should not interrupt early build work with pricing guesses. It separates:

- annotation and QA assumptions,
- training/eval iteration assumptions,
- deployment run-rate,
- managed-vs-DIY crossover.
