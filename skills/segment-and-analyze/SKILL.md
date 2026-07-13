---
name: segment-and-analyze
description: |
  Produce pixel-precise masks plus area, shape, perimeter, calibration, or physical measurements. TRIGGER when: user asks to segment/outline an object or defect; measure exact area, crack width, corrosion, lesion boundary, contours, millimeters, or calibrated dimensions; or quantify mask shape. SKIP when: user only counts boxes (detect-and-analyze), needs one image verdict (classify-or-flag), reads text (read-text), tracks identity (track-and-count), asks cost only (estimate-economics), already has a working mask model and needs delivery (deliver-cv-project), or only post-processes existing masks locally.
allowed-tools: Bash, Read, Write, Edit, Glob, Grep, AskUserQuestion
---

<objective>

Produce masks and derived measurements that clear an independently labeled acceptance gate. Pixel results are not physical measurements unless calibration, camera geometry, and uncertainty support that claim.

</objective>

<methodology>

**Platform execution boundary.** Read `../../resources/roboflow-platform-lookup.md` before any provider-specific search, dataset, training, inference, workflow, or deployment action. Delegate exact execution to the installed official Roboflow skill or current MCP resource. Sentinel retains the measurement contract and evidence.

Follow `../../resources/fde-methodology.md`; apply these segmentation-specific requirements.

## 1. Define mask ownership and decision

Inspect images, masks, calibration artifacts, code, and intended action. Ask at most three missing questions:

- Is the business action driven by outline, area, maximum width, or presence?
- What independently produced masks or physical reference measurements exist?
- Must the answer be pixels/relative area, or real-world units?

Freeze before measuring a candidate:

```text
Acceptance ID: <session/revision>
Business decision: <action enabled by mask/measurement>
Gold set: <independent masks or sensor measurements, split, adjudicator>
Primary metric and threshold: <IoU/Dice/area error/width error>
Secondary guardrails: <boundary error, false masks, latency, calibration uncertainty>
Frozen before baseline: <timestamp and confirmation>
Baseline result (diagnostic only): <not run yet>
```

Visual inspection without gold masks may guide diagnosis but cannot produce IoU or Dice.

## 2. Define the geometry contract

Record mask encoding, coordinate origin, image dimensions, empty-mask behavior, overlap ownership, and whether holes/disconnected components are retained. For derived values, define:

- area: mask pixel count and any conversion factor;
- perimeter/boundary: contour method and smoothing policy;
- width: the geometric definition, not merely a box width;
- physical units: calibration target, plane, camera setup, distortion correction, and propagated uncertainty.

If perspective or depth changes invalidate a single scale factor, report pixels/relative units or require a better calibration design.

## 3. Choose and evaluate candidates

Ask upstream for current no-training and trainable segmentation categories, provenance, licenses, and input requirements. Do not retain named architectures, model IDs, search syntax, or provider command recipes in this skill.

Evaluate on the same blinded gold set. Report overlap and boundary metrics with sample counts, plus the actual business measurement error when area or width drives the decision. Slice by object size, contrast, topology, camera/site, and occlusion. Measure p50/p95 latency on the target runtime if operationally relevant.

## 4. Diagnose a failed gate

Separate missing objects, merged instances, split instances, boundary bias, holes, small-component noise, calibration error, and label disagreement. Check whether the image contains enough resolution for the requested physical tolerance. Test the cheapest credible lever first: capture/calibration improvement, prompt/input policy, post-processing, label correction, relevant transfer, or targeted data. Delegate current platform actions upstream and remeasure without changing the frozen gate.

## 5. Decide and deliver

Return `go`, `revise`, or `stop`, including units, uncertainty, sample counts, failed slices, and calibration limits. Follow `../../resources/artifact-contract.md`; produce a verified `hosted-client`, offline-tested `local-runtime`, or candid `scaffold`. Route a passing pipeline to `deliver-cv-project`.

</methodology>

<safety>

- Never present pixel output as millimeters or area without verified calibration.
- Candidate/pseudo-label masks cannot serve as the gold masks.
- Medical or safety-critical outputs require qualified human ownership beyond this technical gate.
- Obtain explicit consent for data movement and paid actions.
- Delegate exact provider execution; do not guess current tool/model details.

</safety>

<ledger>

Follow `../../resources/ledger-protocol.md`. Record acceptance, evaluation, calibration evidence, artifact, and decision events once with non-empty event IDs and explicit status.

</ledger>

\<stop_rules>

- No independent masks/reference measurements → do not claim overlap or physical accuracy.
- Requested tolerance exceeds capture resolution/calibration capability → state the acquisition blocker.
- Only boxes/counts are needed → route to `detect-and-analyze`.
- Paid/data-moving action lacks explicit current-turn consent → stop.
- No applicable live/offline smoke → artifact remains a `scaffold`.

\</stop_rules>
