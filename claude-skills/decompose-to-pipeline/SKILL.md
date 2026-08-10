---
name: decompose-to-pipeline
description: |
  Decompose a complex vision-and-reasoning requirement into the cheapest measurable pipeline. TRIGGER when: user asks to monitor/alert, analyze footage over time, combine perception with aggregation/reporting, determine whether something is feasible to detect (including sensor limits or smoldering), or replace repeated vision-language calls with a cheaper system. SKIP when: the request is single-frame detection/counting (detect-and-analyze), whole-image classification (classify-or-flag), deployment cost only (estimate-economics), or the pipeline is already working and needs delivery (deliver-cv-project).
allowed-tools: Bash, Read, Write, Edit, Glob, Grep, AskUserQuestion
---

<objective>

Translate a broad operational outcome into the smallest pipeline whose end-to-end decision clears independent acceptance. Optimize complexity or cost only after the end-to-end gate exists.

</objective>

<methodology>

**Platform execution boundary.** Read `../../resources/roboflow-platform-lookup.md` before any provider-specific lookup or action. Delegate exact models, datasets, training, inference, workflows, and deployment execution to an installed official Roboflow skill or current MCP resource. Sentinel owns decomposition, contracts, evidence, and the go/revise/stop decision.

Follow `../../resources/fde-methodology.md` for feasibility, frozen acceptance, consent, artifacts, and provenance.

## 1. Freeze the end-to-end decision

Inspect data, code, operating procedure, existing outputs, and cost/latency constraints. Describe one observable business decision, its input window, required output, action owner, and cost of a miss/false alarm. Create an acceptance ID before testing candidate components.

The gold set must be produced independently by a blinded human, sensor, or documented adjudication process. Candidate output and pseudo-label output are never ground truth. A pseudo-label model may bootstrap training examples only; measure/correct those examples on a blinded human-reviewed slice and exclude them from acceptance ownership.

## 2. Draw contracts, not brand names

Split the path into only necessary stages, for example:

```text
capture -> perception -> deterministic transformation -> temporal aggregation -> business action
```

For each stage record input/output schema, units, error behavior, latency budget, data boundary, and owner. Keep deterministic arithmetic, geometry, filtering, validation, and business rules outside an expensive model when they are sufficient.

## 3. Establish the simplest baseline

Use recorded representative input and a replayable end-to-end harness. A baseline can combine current upstream candidates with local deterministic code, but exact upstream execution stays upstream. Record stage outputs so errors can be attributed. Measure the final business metric, not merely component accuracy.

## 4. Diagnose and simplify

For every failed case, locate the first stage whose contract broke. Test stage removal, rule simplification, capture improvement, lower-frequency sampling, batching, or a narrower candidate before adding complexity. Reject changes that improve a component metric but worsen the frozen end-to-end decision.

## 5. Compare viable alternatives

Only candidates clearing the same gate enter cost/latency comparison. Report quality, p50/p95 latency, processed volume, estimated unit cost, operational dependencies, and uncertainty from measured workload. Route material managed-vs-DIY decisions to `estimate-economics`.

## 6. Deliver

Return a pipeline diagram, stage contracts, replay command, measured result, failed slices, and `go`, `revise`, or `stop`. Follow `../../resources/artifact-contract.md` for generated code. Route a passing pipeline to `deliver-cv-project`.

</methodology>

<safety>

- A general vision model is not a physical oracle; separate unverified visibility from independently proven acquisition failure.
- Never let pseudo-label agreement become independent acceptance.
- Obtain explicit consent for data movement and paid actions.
- Do not guess current provider APIs, tools, model IDs, or deployment paths.

</safety>

<ledger>

Follow `../../resources/ledger-protocol.md`. Record the frozen end-to-end gate, component evaluations, selected pipeline, artifact, and decision once with non-empty IDs and status.

</ledger>

\<stop_rules>

- The business decision or end-to-end metric is undefined → freeze it before optimizing.
- No independent gold evidence → build the evidence plan, not a pass claim.
- A component is not replayable → mark its contribution unverified.
- A more complex design lacks measured gain → reject it.

\</stop_rules>
