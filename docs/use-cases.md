---
description: Choose a Sentinel CV route and understand its evidence, safety, and expert-review boundary.
title: Use Cases
---

# Use Cases

Sentinel routes a business request by required output before model search. A route describes a methodology; unless marked proven for the exact claim, it does not imply a live end-to-end result.

## Route matrix

| Business outcome                          | Route                       | Eval examples                               | Support boundary                                                           |
| ----------------------------------------- | --------------------------- | ------------------------------------------- | -------------------------------------------------------------------------- |
| Count objects or defects                  | `detect-and-analyze`        | recall, box overlap, count MAE              | Guided; B1 is historical private evidence, not reproducible support proof. |
| Flag a whole image/frame                  | `classify-or-flag`          | precision, recall, F1                       | Guided; B2 live run pending.                                               |
| Count crossings or dwell time             | `track-and-count`           | identity metrics, dwell error, event counts | Guided; B3 pending and privacy/streaming expertise required.               |
| Read serials, labels, or fields           | `read-text`                 | exact field match, CER, latency             | Guided; B4 pending.                                                        |
| Extract shape, area, or width             | `segment-and-analyze`       | IoU, mask metrics, measurement error        | Guided; calibration/domain expert required for physical units.             |
| Recognize posture or gesture              | `recognize-pose-or-gesture` | keypoint metrics, action recall             | Guided; expert review for consequential use.                               |
| Combine visual stages                     | `decompose-to-pipeline`     | route metrics plus interface contracts      | Guided; production architecture remains expert-owned.                      |
| Compare project economics                 | `estimate-economics`        | one-time and run-rate assumptions           | Guided; current product pricing delegated upstream.                        |
| Package or integrate a passing capability | `deliver-cv-project`        | artifact smoke, consumer smoke, rollback    | Guided; live/offline proof is required before delivery status.             |

## Plain-language route selection

- **One box for every visible thing:** detection.
- **One verdict for the whole image:** classification.
- **The same thing must keep its identity over time:** tracking.
- **The answer is characters or structured fields:** OCR.
- **The exact outline or area matters:** segmentation.
- **Body or object landmarks matter:** pose/keypoints.
- **Several of these must pass outputs between stages:** pipeline decomposition.
- **A measured capability must become runnable for a consumer:** delivery and integration.

Ambiguous requests need one decision before proceeding. “How many defective items?” is detection; “is this item defective?” is classification.

## Examples and limits

### Detection and counting

Good fits include vehicle, pallet, package, or visible-defect counts. Count error can matter more than general detection mAP, so define both the business count measure and the object-level failure pattern.

### Classification and flagging

Good fits include pass/fail, category, or anomaly flags for an entire image. Compliance labels affecting people or employment require expert policy, fairness, and human-review controls.

### Tracking and events

Good fits include anonymous object flow, line crossing, and dwell estimates. RTSP reliability, state recovery, identity switches, latency, retention, and privacy are production concerns outside the route recipe.

### OCR

Good fits include serials, lot codes, dates, and meter readings. License plates, forms, and identifiers are sensitive; establish purpose, access, and retention before use.

### Segmentation and measurement

Good fits include contours, pixel area, or relative change. Millimeters, volume, medical boundaries, and maintenance decisions require calibration, uncertainty analysis, and a qualified domain reviewer.

### Pose, gesture, and action

Good fits include interface gestures or descriptive motion analysis. Worker safety, fall detection, access, or disciplinary uses must not become autonomous decisions without representative evaluation and human oversight.

### Delivery and integration

Good fits start with an already accepted model or pipeline and package it as a hosted client, offline local runtime, or candid scaffold. The route verifies dependencies, deterministic self-test, applicable live/offline execution, consumer contract, monitoring status, and rollback. It does not turn an unmeasured model into production.

## Stop conditions

Do not continue from exploration to upload, training, deployment, or operational decision when data authority is unclear, representative samples are absent, the consequence of error is unknown, paid-action approval is missing, or no qualified human can review a consequential result.

See [Support & Evidence](support-and-scope.md) for route status and [Trust and Safety](trust.md) for the sensitive-use gate.
