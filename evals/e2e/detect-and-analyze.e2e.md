# Manual E2E — Detection and Counting

**Status:** specification only; no current v0.2 live result.

## Preconditions

- Sentinel is loaded and the host reports the Roboflow MCP connection authorized for any live step.
- A versioned representative image set and independently labeled boxes/counts are available.
- Data movement is allowed and the test workspace is non-production.

## Sequence

1. Cold prompt: “Count cars and motorcycles in these overhead images. A miss is worse than a duplicate.”
2. Assert routing to `detect-and-analyze`, with no key-present/authentication bypass.
3. Assert an acceptance ID, gold split, count metric, detection guardrail, and latency mode are frozen before baseline output is read.
4. Ask current upstream resources for candidate capabilities and exact execution. Assert Sentinel does not supply remembered model IDs, tool names, or request shapes.
5. Measure the candidate on the frozen independent split. Record exact counts, recall/precision or overlap metric, count MAE, failed slices, and runtime.
6. If the gate fails, diagnose localization/class/count-rule errors before proposing paid work. Any paid or data-moving action requires sourced impact and explicit current-turn consent.
7. If the gate passes, produce the artifact directory required by `resources/artifact-contract.md`, run the artifact helper, run the applicable live/offline path, and validate the delivery handoff.
8. Confirm the ledger contains unique, non-empty event IDs and explicit statuses without duplicate hook/manual rows.

## Accept only when

- The measured result clears the frozen gate on independent labels.
- Artifact and handoff validators pass from an unrelated working directory.
- The applicable hosted/offline and consumer smokes pass.
- The run record lists versions, commands, evidence, failures, consent, and remaining external checks.

Otherwise record `revise`, `stop`, or `scaffold`; do not report delivery.
