---
name: read-text
description: |-
  Extract structured text, numbers, labels, and codes from images and evaluate by character or field accuracy. TRIGGER when: user asks to read/scan a serial, part/date/lot number, label, license plate, meter, gauge, barcode, QR code, invoice, document, form field, or other image text. SKIP when: user asks to tally/count boxes or other objects on a conveyor (detect-and-analyze), pass/fail without text (classify-or-flag), measure crack width/masks/area (segment-and-analyze), track objects (track-and-count), cost only (estimate-economics), or integrate/deliver working OCR (deliver-cv-project).
---

<objective>

Extract the exact fields needed by the business process and clear an independently transcribed acceptance set. Separate region localization, text decoding, normalization, and field validation so failures have an owner.

</objective>

<methodology>

**Platform execution boundary.** Read `../../resources/roboflow-platform-lookup.md` before any provider-specific capability, dataset, training, inference, workflow, or deployment action. Use installed official Roboflow skills or current MCP resources only for read-only discovery and sourced action-brief inputs; never invoke provider execution outside the host-gated path. Do not preserve current engine names, blocks, IDs, or invocation syntax here.

Follow `../../resources/fde-methodology.md`; apply these text-specific rules.

## 1. Define fields and operational action

Inspect representative images, existing schemas, expected formats, code, and error handling. Ask at most three missing questions:

- Which exact fields must be returned, and what action uses them?
- Are substitutions allowed, or must the whole field match exactly?
- Which capture conditions and scripts/languages occur in production?

Freeze before selecting or tuning a candidate:

```text
Acceptance ID: <session/revision>
Business decision: <action enabled by extracted fields>
Gold set: <independent transcription source, split, adjudicator>
Primary metric and threshold: <exact field match/CER/valid-code rate>
Secondary guardrails: <critical-field recall, rejection rate, latency>
Frozen before baseline: <timestamp and confirmation>
Baseline result (diagnostic only): <not run yet>
```

## 2. Freeze the extraction schema

For each field, record name, type, allowed alphabet, normalization, format/checksum rule, null behavior, confidence/review policy, and whether localization is needed. Preserve raw text separately from normalized output. Never silently “correct” a value unless the correction rule was frozen and both forms are retained.

## 3. Select and evaluate candidates

Rung 0 for one text value per image (a serial number, a meter reading, one form field) comes first and follows `../../resources/baseline-ladder.md` rung 0 with `--task text`. The scorer compares strings exactly, so the person enters each label in the frozen normalized form from step 2 and the predictor is told the same normalization. When no gold file exists, the human labels with `../../resources/scripts/label_gold.py`; never propose a label. Run the rung 0 predictions in an isolated subagent that receives the image paths (from `label_gold.py --list-images`) and the business question only, never the gold path or its contents. Freeze the prediction file with `../../resources/scripts/freeze_predictions.py --skill read-text` before scoring, and score with `--frozen-ledger`. When the freeze refuses because labels changed after predictions existed, stop and tell the user; never add `--acknowledge-label-change` on your own. On a host with no subagent tool, say so, freeze with `--predictor same-session`, and report that independence was not enforced for that run. Report the scorer's whole line. The Sentinel scorer covers `exact_match_rate` and `char_error_rate` for one string per image; records with several fields, critical-field recall, format checks, and latency still need your own or upstream tooling. Limits: a freeze shows that the prediction file and the label file were fixed before this scoring run, and the scorer's line says whether labels changed after an earlier freeze or after the prediction file was written. It does not show that the labels are independent of the predictions. The helpers, the predictor, and the scorer run under one account on the user's machine, so a predictor that opens the label file is not detected. A ledger row written by hand is not detected. An earlier scoring run without the freeze leaves no trace. Renaming image files defeats the per-image label check, and file times can be changed. An agent can call `label_gold.py --record`, so labels entered that way are marked, not blocked, and a pseudo-terminal defeats the helper's terminal check. The isolated-subagent step has not yet been recorded in a live session.

Ask upstream for current text/code-reading capabilities with provenance, license, input constraints, and runtime requirements. Prefer a no-training capability that clears the same independent gate. Do not encode provider model IDs or command sequences in Sentinel.

Measure the full localize → decode → normalize → validate pipeline. Report:

- exact field-match rate with numerator/denominator;
- character error rate where partial correctness matters;
- critical-field recall and false acceptance/rejection rate;
- invalid-format/checksum and abstention counts;
- slices by blur, glare, font, layout, language, crop, and camera;
- p50/p95 latency on the target runtime.

Manual visual review helps diagnose samples but cannot be converted into an accuracy claim without independent transcription.

## 4. Diagnose a failed gate

Separate missing/wrong regions, decoding substitutions/deletions, orientation/quality issues, normalization bugs, and validator errors. Test capture, crop/orientation, deterministic validation, or candidate changes before custom training. Target new labels at demonstrated failure slices. Use read-only upstream facts to prepare any required provider action brief, stop before execution, and remeasure externally supplied results on the frozen set.

## 5. Decide and deliver

Return `go`, `revise`, or `stop`, including field-level errors, rejection policy, privacy boundary, and remaining manual-review cases. Follow `../../resources/artifact-contract.md`; emit a verified `hosted-client`, offline-tested `local-runtime`, or candid `scaffold`. A passing extraction capability routes to `deliver-cv-project`.

</methodology>

<safety>

- Treat extracted personal/document data as sensitive and minimize retention.
- Never invent missing characters or suppress the raw result.
- Pseudo-transcriptions cannot own acceptance.
- Emit a sourced action brief and stop before data movement or paid provider work; Sentinel never invokes either outside the host-gated path.
- Use current upstream guidance only for read-only facts and action-brief inputs; never invoke provider execution outside the host-gated path.

</safety>

<ledger>

Follow `../../resources/ledger-protocol.md`. Record acceptance, field-level evaluation, artifact verification, and decision once with non-empty event IDs and status.

</ledger>

\<stop_rules>

- Field schema/normalization is undefined → freeze it first.
- No independent transcription set → do not claim accuracy.
- Capture quality makes characters unresolvable → state the acquisition requirement.
- Provider action is required → emit a sourced action brief and stop; conversational consent does not authorize Sentinel execution.
- Applicable live/offline smoke is absent → retain `scaffold` status.

\</stop_rules>
