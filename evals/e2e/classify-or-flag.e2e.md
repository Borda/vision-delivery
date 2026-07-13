# Manual E2E — Whole-Image Classification

**Status:** specification only; no current v0.2 live result.

## Preconditions

- Sentinel is loaded and the host reports the Roboflow MCP connection authorized for live steps.
- A representative image set has independent whole-image labels and grouped train/eval separation.
- The test has a named human owner and approved data boundary.

## Sequence

1. Cold prompt: “Flag each product image pass/fail. Missing a defect is worse than review.”
2. Assert routing to `classify-or-flag`; a per-person compliance request must instead route to detection.
3. Freeze acceptance ID, class dictionary, gold split, primary metric/per-class floors, and abstention rule before baseline output.
4. Delegate current candidate discovery and execution upstream. Assert no copied platform recipe appears in the response.
5. Measure confusion matrix, per-class recall/precision, primary metric, abstention/error counts, slices, and target-runtime latency on the independent split.
6. If failing, diagnose ambiguity, leakage, imbalance, domain shift, and background shortcuts before any paid/data action.
7. If passing, create and verify the artifact directory, applicable live/offline path, consumer smoke, and delivery handoff.
8. Check unique status-bearing ledger events and no duplicate hook/manual rows.

## Accept only when

The frozen independent gate, artifact helper, handoff validator, applicable execution smoke, and consumer check all pass with a versioned run record. Otherwise retain `guided`/`scaffold` status and record the failed condition.
