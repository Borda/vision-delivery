# Model Selection Boundary

Sentinel does not carry a provider catalog. This file is a stable fallback only for deciding what evidence to request from current upstream resources.

## Required Lookup

1. Use an installed official Roboflow modality or training/evaluation skill when available.
2. Otherwise use the matching current MCP skill resource exposed by the host.
3. If neither is available, describe only a provider-neutral candidate category and mark exact platform details unverified. Do not begin paid work from fallback guidance.

Read `roboflow-platform-lookup.md` for the action handshake. Validate every volatile model identifier and paid-training operation through current upstream evidence; never derive an identifier from an architecture name or an old example.

## Candidate Categories

| Need                       | Candidate category                           | Required evidence                                    |
| -------------------------- | -------------------------------------------- | ---------------------------------------------------- |
| common object              | general pretrained detector                  | relevance on user samples, license, latency          |
| custom/fine-grained object | transferable detector                        | baseline gap and label availability                  |
| masks/contours             | no-training or trainable segmenter           | overlap and business measurement error on gold masks |
| pose/gesture               | keypoint model plus explicit rule/classifier | skeleton contract and event metrics                  |
| whole-image verdict        | no-training or trainable classifier          | class balance, confusion matrix, per-class floor     |
| structured text            | text/code reader                             | exact field match, character error, latency          |
| identity over time         | detector plus association stage              | identity/event/count error on clips                  |

## Selection Rules

- Freeze acceptance before candidate lookup.
- Prefer the least expensive candidate that clears the same independent gate.
- Compare on the user's blinded gold split, never catalog metrics or pseudo-label agreement.
- Record upstream-sourced identity/version, timestamp, license, input contract, measured result, latency, and artifact kind.
- Treat size/latency as empirical; benchmark the target runtime.
- Return to the modality skill. Upstream owns current product truth; Sentinel owns the go/revise/stop evidence.
