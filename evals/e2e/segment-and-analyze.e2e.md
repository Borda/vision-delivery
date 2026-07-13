# Manual E2E — Segmentation and Measurement

**Status:** specification only; no current v0.2 live result.

## Preconditions

- Sentinel is loaded; live MCP is host-authorized when used.
- Representative images have independently produced masks or sensor measurements.
- Any physical-unit claim has a documented calibration design and qualified owner.

## Sequence

1. Cold prompt: “Measure defect area from these images; report pixels unless calibration supports physical units.”
2. Assert routing to `segment-and-analyze`.
3. Freeze acceptance ID, geometry/mask contract, gold split, overlap/business-measurement metric, boundary guardrail, and calibration uncertainty.
4. Delegate current candidate discovery/execution upstream; reject copied model IDs, queries, or provider operations.
5. Measure overlap/boundary and business measurement error on independent gold data. Visual inspection may diagnose but must not produce overlap scores.
6. Attribute failures to missing/merged/split masks, boundary bias, topology, resolution, calibration, or labels.
7. After a pass, verify artifact, applicable hosted/offline path, consumer smoke, handoff, units, and uncertainty disclosure.
8. Check unique status-bearing ledger events.

## Accept only when

The frozen independent mask/measurement gate and all artifact/delivery checks pass with a versioned run record. Without verified calibration, physical-unit output must not be accepted.
