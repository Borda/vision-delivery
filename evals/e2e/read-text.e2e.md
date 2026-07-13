# Manual E2E — Structured Text Extraction

**Status:** specification only; no current v0.2 live result.

## Preconditions

- Sentinel is loaded; any live MCP use is authorized through the host.
- Representative images have independent field transcriptions.
- Field schema, allowed use, and sensitive-data retention are approved.

## Sequence

1. Cold prompt: “Read the lot number and expiry date from each label into JSON.”
2. Assert routing to `read-text`.
3. Freeze acceptance ID, field schema/normalization, gold split, exact-field or character-error gate, critical-field floor, and rejection rule.
4. Delegate current text-reading capability and exact execution upstream; reject copied engine/block/model/tool recipes.
5. Measure the full localization/decode/normalize/validate path: exact field match, character error, invalid/rejected cases, critical-field recall, slices, and latency.
6. Attribute failures to region, decoding, image quality, normalization, or validation before proposing training.
7. After a pass, verify artifact, applicable hosted/offline path, consumer smoke, handoff, and no-secret contract.
8. Check unique status-bearing ledger events.

## Accept only when

The frozen independent transcription gate and all artifact/delivery checks pass with a versioned run record. Visual reading by the candidate/agent cannot own the gold result.
