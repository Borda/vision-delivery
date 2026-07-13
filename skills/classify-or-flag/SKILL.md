---
name: classify-or-flag
description: |
  Produce one whole-image verdict: pass/fail, category, compliance, or anomaly. TRIGGER when: user asks whether an image is defective/compliant; to flag bad parts, classify product images, run image-level quality control, detect an anomaly, or build binary/multi-class classification. SKIP when: user asks how many boxes/pallets or for other object counts or per-person PPE (detect-and-analyze); masks/area (segment-and-analyze); identity across video (track-and-count); OCR/codes (read-text); to compare self-hosting vs managed or cost only (estimate-economics); or delivery/export of a working classifier (deliver-cv-project).
allowed-tools: Bash, Read, Write, Edit, Glob, Grep, AskUserQuestion
---

<objective>

Produce one verdict for the whole image that supports a named business action and passes independent acceptance. This covers binary or multi-class labels, image-level compliance, and anomaly flagging. It does not localize individual objects.

</objective>

<methodology>

**Platform execution boundary.** Read `../../resources/roboflow-platform-lookup.md` before any provider-specific search, dataset, training, inference, or deployment action. Delegate exact execution to the installed official Roboflow skill or current MCP resource. Keep volatile model names, IDs, request shapes, and platform sequences out of Sentinel.

Follow `../../resources/fde-methodology.md`; apply these classification-specific rules.

## 1. Resolve the output unit

Inspect existing images, labels, code, and operating procedure. Confirm that the required output is one verdict for the whole image. If the action must identify which worker lacks equipment, route per-person PPE to `detect-and-analyze`. If it needs the defective region, route to detection or segmentation.

Ask only missing operational questions:

- What exact action follows each class or flag?
- Which error costs more: a missed positive or a false alarm?
- What class balance and operating conditions occur in production?

Freeze before candidate search:

```text
Acceptance ID: <session/revision>
Business decision: <action enabled by each image verdict>
Gold set: <independent labels, split, class counts, adjudicator>
Primary metric and threshold: <F1/recall/precision/exact accuracy>
Secondary guardrails: <per-class floor, false alarms, latency>
Frozen before baseline: <timestamp and confirmation>
Baseline result (diagnostic only): <not run yet>
```

## 2. Define labels and abstention

Write a mutually understandable class dictionary with positive/negative examples and ambiguous-case handling. Define whether the system may abstain or send low-confidence cases to a human. Prevent data leakage by grouping near-duplicates, bursts, products, sites, or subjects before splitting.

## 3. Measure current candidates

Ask upstream for current no-training and trainable candidate categories with provenance and license. Prefer the least costly candidate that clears the same gold-set gate. Do not encode named architectures, model IDs, search syntax, or platform commands locally.

Report:

- confusion matrix and class counts;
- primary metric with numerator/denominator;
- per-class recall and precision;
- false-positive and false-negative examples by operating slice;
- calibration/abstention behavior when confidence drives action;
- target-runtime latency when the decision is time-sensitive.

Unlabeled visual review may identify errors but cannot generate F1, accuracy, or recall.

## 4. Diagnose before more data

Check label ambiguity, leakage, imbalance, domain shift, visually indistinguishable classes, background shortcuts, crop policy, and threshold calibration. Test one falsifiable lever at a time. New labels should target demonstrated failure slices, not an arbitrary image count. Delegate any current training/data action upstream, then remeasure on the unchanged gold set.

## 5. Decide and deliver

Return `go`, `revise`, or `stop`. State the frozen gate, measured result, class/slice limitations, and effect on the business action. Follow `../../resources/artifact-contract.md`; emit a verified `hosted-client`, offline-tested `local-runtime`, or candid `scaffold`. A passing classifier routes to `deliver-cv-project` for integration.

</methodology>

<safety>

- Pseudo-labels may bootstrap training data but never own acceptance.
- Do not collapse high-stakes per-person compliance into an unexplained scene label.
- State data movement and obtain explicit consent before upload.
- Show sourced impact and obtain explicit consent before paid work.
- Do not invent current provider capabilities or model identifiers.

</safety>

<ledger>

Follow `../../resources/ledger-protocol.md`. Record acceptance, evaluation, artifact, and decision events once with non-empty IDs and explicit status; do not duplicate hook-owned MCP rows.

</ledger>

\<stop_rules>

- Labels are undefined or contradictory → adjudicate examples before training.
- No independent labeled split → do not claim a metric.
- Required output is per-object, localized, temporal, or textual → route to the owning skill.
- Paid/data-moving action lacks current-turn consent → stop.
- Live/offline artifact check is absent → retain `scaffold` status.

\</stop_rules>
