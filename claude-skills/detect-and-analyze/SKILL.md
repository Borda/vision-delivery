---
name: detect-and-analyze
description: |
  Detect instances and analyze boxes, counts, crops, regions, or metadata. TRIGGER when: user asks to count/detect objects, report the number of defects, build a model that counts trucks, tally boxes/pallets on a conveyor, find workers lacking PPE, crop detections, extract an ROI, estimate box-relative size, or report per-object confidence/zone metadata. SKIP when: user needs one whole-image verdict (classify-or-flag); identity/path/dwell/line crossing (track-and-count); masks/contours/calibrated area/crack width (segment-and-analyze); OCR/serials (read-text); to compare self-hosting vs managed or cost only (estimate-economics); active learning/export/delivery of a working model (deliver-cv-project).
allowed-tools: Bash, Read, Write, Edit, Glob, Grep, AskUserQuestion
---

<objective>

Turn an object-level business question into a detector that passes independent acceptance and produces actionable per-instance output. Counts, crops, relative dimensions, class breakdowns, and zone membership may be derived from boxes. Physical units and pixel-precise outlines are outside a box-only claim.

</objective>

<methodology>

**Platform execution boundary.** Read `../../resources/roboflow-platform-lookup.md` before any provider-specific search, dataset, training, inference, or deployment action. Delegate exact execution to the installed official Roboflow skill or current MCP resource. Sentinel owns the problem contract, independent evidence, failure diagnosis, artifact verification, and decision.

Follow `../../resources/fde-methodology.md`; the domain-specific requirements below refine its generic sequence.

## 1. Frame the operational decision

Inspect available images, clips, annotations, code, and camera constraints first. Ask at most three missing business questions:

- Which object instances matter, and what action follows a detection?
- Which is worse: a missed instance or a false alarm?
- Is this per-image inventory, per-frame monitoring, or an identity-linked video event?

Route one verdict for the whole image to `classify-or-flag`. Route per-person PPE to this skill; whole-image compliance belongs in classification. Route identity-linked counts to `track-and-count`.

Freeze the acceptance record before any candidate or baseline result:

```text
Acceptance ID: <session/revision>
Business decision: <action enabled by a passing result>
Gold set: <independent label source, split, sample size, adjudicator>
Primary metric and threshold: <recall/precision/count error/etc.>
Secondary guardrails: <latency, false alarms, size or scene slices>
Frozen before baseline: <timestamp and confirmation>
Baseline result (diagnostic only): <not run yet>
```

## 2. Define the output contract

Require a box list with class, confidence, coordinates, image identity, and explicit empty-result behavior. Record coordinate units and whether boxes are clipped to the frame. For derived outputs:

- spatial count: count only instances passing the frozen class/region policy;
- crops: preserve source identity and box coordinates;
- zone membership: define boundary behavior before evaluation;
- relative size: label it a proxy unless camera calibration supports physical units.

## 3. Choose and measure candidates

Ask upstream for current no-training and trainable candidate categories with provenance, license, and input contract. Do not preserve model IDs, query syntax, checkpoint payloads, or tool names here. Test candidates on the same blinded gold set.

Use metrics that match the decision:

- safety/rare-event detection: recall plus false alarms per image or hour;
- balanced instance detection: precision, recall, and an agreed box-overlap metric;
- inventory/counting: count MAE and exact-count rate;
- zone logic: event precision/recall after the box-to-zone rule;
- operations: p50/p95 latency and empty/error rate on the target runtime.

Do not calculate accuracy from visual inspection. Unlabeled images can reveal failure modes, but cannot produce acceptance metrics.

## 4. Diagnose a failed gate

Break errors down by class, object size, occlusion, lighting, camera, scene, and label quality. Separate localization errors, class confusion, missed objects, duplicates, and downstream rule errors. Then test the cheapest plausible lever: confidence policy, crop/tile strategy, capture improvement, label correction, relevant transfer, or targeted new data. Delegate any current platform action upstream and re-evaluate on the frozen gold set.

Never move the threshold to make a result pass. A changed business requirement creates a new acceptance revision.

## 5. Deliver evidence and artifact

Report the result as `go`, `revise`, or `stop`, with the exact numerator/denominator, confidence limits when meaningful, failed slices, and remaining external checks. Follow `../../resources/artifact-contract.md`; output a verified `hosted-client`, offline-tested `local-runtime`, or candid `scaffold`. Route a passing capability to `deliver-cv-project` for integration and handoff.

</methodology>

<safety>

- Independent human/sensor labels—not candidate output or pseudo-labels—own acceptance.
- State data movement and obtain current-turn consent before uploads.
- Show a sourced cost/credit estimate and obtain current-turn consent before paid work.
- Delegate exact provider operations to current upstream guidance; never guess them.
- Bounding boxes do not justify calibrated millimeters, area, or contours.

</safety>

<ledger>

Follow `../../resources/ledger-protocol.md`. Record frozen acceptance, measured evaluation, artifact verification, and the decision once, with non-empty event IDs and status. Do not duplicate hook-covered MCP actions.

</ledger>

\<stop_rules>

- No independently labeled acceptance set → help create one; do not claim a metric.
- Target signal is not observable in representative input → document the acquisition blocker.
- Physical measurement is requested without calibration/mask ownership → route to `segment-and-analyze`.
- Paid/data-moving action lacks explicit consent → stop before it.
- Live/offline artifact path is untested → label it `scaffold`, not delivered.

\</stop_rules>
