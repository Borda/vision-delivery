---
name: recognize-pose-or-gesture
description: |
  Build keypoint-based pose, gesture, action, ergonomics, posture, or fall analysis. TRIGGER when: user asks for body/hand pose, gestures, action recognition, skeletons, keypoints, joint angles, raised hands, bending, squats, falls, sign language, or posture compliance. SKIP when: user needs an exact body contour/mask (segment-and-analyze), per-person PPE without keypoints (detect-and-analyze), whole-image compliance (classify-or-flag), identity/path tracking without pose (track-and-count), OCR (read-text), to compare cloud-hosted vs self-hosted or cost only (estimate-economics), or integration/delivery of a working pose model (deliver-cv-project).
allowed-tools: Bash, Read, Write, Edit, Glob, Grep, AskUserQuestion
---

<objective>

Turn keypoints or temporal keypoint sequences into a pose/gesture decision that clears independent acceptance. Keep pose estimation, identity association, and business-rule classification as separately measured stages.

</objective>

<methodology>

**Platform execution boundary.** Read `../../resources/roboflow-platform-lookup.md` before any provider-specific search, dataset, training, inference, workflow, or deployment action. Delegate exact execution to the installed official Roboflow skill or current MCP resource. Do not freeze model families, IDs, or platform recipes in Sentinel.

Follow `../../resources/fde-methodology.md`; apply these keypoint-specific rules.

## 1. Define the action and time window

Inspect footage, annotations, rules, code, and camera placement. Clarify whether the output is a per-frame posture, a hand/body gesture, a timed action, an ergonomics measurement, or a safety alert. Ask:

- Which joints/keypoints and time window determine the action?
- Must identity persist across frames?
- Which error is worse for the operator: a miss or false alert?

If the task only needs identity/path/dwell, route to `track-and-count`. Per-person PPE without a keypoint requirement routes to `detect-and-analyze`.

Freeze the evidence gate:

```text
Acceptance ID: <session/revision>
Business decision: <alert/action enabled by pose or gesture>
Gold set: <independent keypoints/events, subject/site split, adjudicator>
Primary metric and threshold: <keypoint quality/event recall/F1/angle error>
Secondary guardrails: <false alerts/hour, latency, subject/site floors>
Frozen before baseline: <timestamp and confirmation>
Baseline result (diagnostic only): <not run yet>
```

## 2. Freeze the keypoint contract

Record keypoint names/order, coordinate convention, confidence/missing-point semantics, left/right definition, person association, frame timestamps, and rule thresholds. For temporal events, define start/end, minimum duration, cooldown, and partial-visibility behavior before evaluation.

## 3. Select and measure candidates

Ask upstream for current keypoint/pose candidates with provenance, license, skeleton compatibility, and runtime requirements. Do not store exact model IDs or invocation syntax here. If a transparent geometric rule can map stable keypoints to the desired label, compare it with learned sequence classification on the same gate.

Report stage-specific evidence:

- keypoint localization/visibility quality on independently labeled frames;
- event recall, precision/F1, and false alerts per hour;
- joint-angle error when angles drive the decision;
- subject/site/camera and occlusion slices;
- p50/p95 end-to-end latency on the target runtime.

An event label inferred from candidate keypoints is not independent gold.

## 4. Diagnose a failed gate

Separate keypoint localization failures, left/right swaps, missing joints, identity switches, temporal-window errors, and rule/classifier errors. Check camera viewpoint, occlusion, motion blur, subject diversity, and annotation consistency. Test capture or deterministic rule improvements before more expensive training. Delegate current platform operations upstream and remeasure against the frozen split.

## 5. Decide and deliver

Return `go`, `revise`, or `stop`, with exact event counts, failure slices, rule thresholds, and human-review boundary. Follow `../../resources/artifact-contract.md`; produce a verified `hosted-client`, offline-tested `local-runtime`, or candid `scaffold`. Route a passing capability to `deliver-cv-project`.

</methodology>

<safety>

- Pose output alone does not prove intent, identity, medical condition, or safety compliance.
- Safety alerts require a documented human/operational fallback.
- Pseudo-labels cannot own acceptance.
- Obtain explicit consent for data movement and paid work.
- Delegate exact provider actions to current upstream guidance.

</safety>

<ledger>

Follow `../../resources/ledger-protocol.md`. Record acceptance, stage evaluations, artifact verification, and decision events once with non-empty IDs and status.

</ledger>

\<stop_rules>

- Required joints/action are not defined → define the contract before candidate work.
- No independent subject/site split → do not claim generalization.
- Capture does not expose required keypoints → state the camera/acquisition blocker.
- Paid/data-moving action lacks current-turn consent → stop.
- Applicable live/offline check is absent → retain `scaffold` status.

\</stop_rules>
