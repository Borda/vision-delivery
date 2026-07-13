---
description: Pending B5 segmentation and physical-measurement benchmark specification with calibration and domain-review requirements.
title: B5 Measurement Fixture — Pending
---

# B5 segmentation/measurement fixture — pending

**Prompt:** “Measure crack width in bridge-inspection photos.” **Route:** `segment-and-analyze`. **Status:** specification only; no live mask or physical-measurement result is committed.

## Intended business gate

Mask overlap alone is insufficient for a width decision. A study needs boundary/width error in physical units, calibration uncertainty, repeatability, and a domain-approved maintenance threshold. Earlier IoU `0.80` and area-error `15%` values are fixture hypotheses, not engineering standards.

## Required evidence

1. Use authorized images with verified crack annotations and a calibrated scale in the same focal plane.
2. Record camera geometry, distortion, perspective, resolution, reference uncertainty, and environmental conditions.
3. Define width extraction, uncertainty propagation, reject behavior, and domain acceptance before model selection.
4. Compare candidate segmentation/baseline methods on a held-out representative set.
5. Execute the artifact and validate physical measurements against traceable reference measurements.
6. Obtain qualified structural/maintenance review before an operational decision.
7. Run a repeated clean comparator before claiming plugin advantage.

## Current claim boundary

The route can guide segmentation and calibration questions. This page does not establish that SAM or another model works for cracks, that an endpoint was deployed, that millimeter output is valid, or that any threshold is engineering-grade. Without calibration, report pixels only; with calibration, retain uncertainty and expert review.

```bash
claude --plugin-dir . "Evaluate crack segmentation on these calibrated, authorized test images."
```

Running the command is only the start of the study; it is not a benchmark result.
