# Manual E2E — Tracking and Video Events

**Status:** specification only; no current v0.2 live result.

## Preconditions

- Sentinel is loaded; live Roboflow capability is host-authorized when used.
- Representative clips have independent track/event annotations.
- Line/zone geometry, event semantics, privacy, and retention are approved.

## Sequence

1. Cold prompt: “Count vehicles crossing this line by direction from this clip.”
2. Assert routing to `track-and-count`, not per-frame detection.
3. Freeze acceptance ID, event semantics, gold clips, event/count metric, false-events/hour, and latency/FPS guardrail.
4. Delegate current detection/association capability and execution upstream; reject copied model, block, parameter, device, or API recipes.
5. Replay the complete pipeline and measure event precision/recall, count error, identity failures when relevant, false events/hour, dropped-frame behavior, and runtime.
6. Attribute failures to detection, association, timestamps, or event logic before changing a stage.
7. After a pass, verify artifact, replay command, applicable hosted/offline smoke, consumer integration, delivery handoff, monitoring status, and rollback.
8. Check unique ledger ownership and explicit event status.

## Accept only when

The frozen independent clip gate and all artifact/delivery checks pass with a versioned run record. A frame-level demo or visual inspection is not event-accuracy evidence.
