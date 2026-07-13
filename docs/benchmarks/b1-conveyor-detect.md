---
description: B1 historical detection fixture with recorded results, provenance boundaries, and missing controlled evidence.
title: B1 Detection Fixture
---

# B1 detection fixture

**Recorded:** 2026-06-25. **Route:** `detect-and-analyze`. **Status:** narrow measured fixture, not a controlled plugin comparison.

## Fixture

- Private Roboflow workspace dataset: `sandbox-ibs0b/cars-jnnoy-mmrcu`, version 1.
- 100 aerial/overhead images; 11-image test split.
- Classes: car, motorcycle, truck.
- Used as a proxy after the intended conveyor-box fixture was inaccessible across workspaces.

The dataset is not distributed by this repository. Independent reproduction, licensing, annotation quality, split integrity, and conveyor-domain equivalence cannot be verified from the public files.

## Recorded results

| Stage                | Model                                       | mAP@50 |         Precision |            Recall |                    Count MAE |
| -------------------- | ------------------------------------------- | -----: | ----------------: | ----------------: | ---------------------------: |
| Zero-shot baseline   | torchvision Faster R-CNN ResNet50 FPN, COCO |   3.0% | not recorded here | not recorded here | 1.39 per class/image overall |
| Post-training record | RF-DETR medium, 23 epochs                   |  84.6% |             92.8% |             76.1% |            not recorded here |

The fixture document records a 65% mAP@50 gate. That value is a benchmark assumption, not a generally valid business threshold. Count MAE was not recorded for the post-training result, so the count objective cannot be declared passed from mAP alone.

A Roboflow deployment path was recorded at the time of the run. Current endpoint availability, credentials, service behavior, and deployment status have not been reverified for this page.

## What the result supports

- A baseline and post-training metric record exists for one private aerial detection fixture.
- The recorded post-training mAP@50 exceeded the fixture's documented mAP gate.
- The pretrained baseline was materially below that gate on the recorded run.

## What remains unproven

- That Sentinel, rather than the model/data/training path, caused the metric improvement.
- That the gate reflected a real stakeholder requirement.
- That the final model passed the count-error objective.
- That the path transfers to conveyor boxes or other domains.
- That a plain agent would perform worse; no controlled plain-agent arm was run.
- That generated scripts were executed successfully; the end-to-end file is a manual procedure, not an automated acceptance harness.
- That the small private test split supports production generalization.

## Reproduction work still required

Use a public or redistributable versioned fixture, freeze the train/validation/test split, verify annotations, define stakeholder-backed mAP and count gates, run both arms in a clean environment with repeats, publish raw outputs and failures, and execute generated artifacts. Do not publish private images or credentials.

Repository entry points:

```bash
python3 scripts/baseline_map.py
claude --plugin-dir . "Count vehicles in this overhead camera view."
```

These commands do not by themselves reproduce the historical private post-training result.
