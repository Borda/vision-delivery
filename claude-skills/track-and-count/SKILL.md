---
name: track-and-count
description: |
  Track identity across video and produce paths, dwell, crossings, zones, or linked counts. TRIGGER when: user asks to follow a person/vehicle/object across frames, track shoppers/forklifts, count entries/line crossings, ask how many vehicles crossed an intersection, analyze video with identity, measure dwell/path, monitor RTSP, or alert on zone entry. SKIP when: user asks to count cars in a parking lot now or other per-image/per-frame counts (detect-and-analyze); masks/area (segment-and-analyze), one image verdict (classify-or-flag), OCR (read-text), cost only (estimate-economics), or export/delivery of a working tracker (deliver-cv-project).
allowed-tools: Bash, Read, Write, Edit, Glob, Grep, AskUserQuestion
---

<objective>

Produce identity-linked video events—paths, dwell, crossings, or counts—that pass an independently annotated clip-level gate. A detector that works on isolated frames is necessary evidence, not proof that tracking works.

</objective>

<methodology>

**Platform execution boundary.** Read `../../resources/roboflow-platform-lookup.md` before any provider-specific search, dataset, training, inference, workflow, device, or deployment action. Delegate exact execution to the installed official Roboflow skill or current MCP resource. Sentinel owns event semantics and measured delivery evidence.

Follow `../../resources/fde-methodology.md`; apply these video-specific rules.

## 1. Define the event, source, and action

Inspect representative clips, stream configuration, zones/lines, annotations, and code. Ask only what is missing:

- Is the decision about occupancy, unique identity, crossing direction, dwell, or a path?
- What event/action follows, and which miss/false event is worse?
- Is the source recorded video or live stream, and may frames leave the site?

Route instantaneous “how many are visible?” to `detect-and-analyze`. For live streams, explain the stable delivery choices—local processing, hosted client, or provider-managed runtime—without claiming current availability or commands; exact setup comes from upstream and final integration from `deliver-cv-project`.

Freeze before tuning:

```text
Acceptance ID: <session/revision>
Business decision: <action enabled by the video event>
Gold set: <independent clip/event labels, sites/times, adjudicator>
Primary metric and threshold: <event recall/precision/count error/dwell MAE>
Secondary guardrails: <identity switches, false events/hour, latency>
Frozen before baseline: <timestamp and confirmation>
Baseline result (diagnostic only): <not run yet>
```

## 2. Freeze event semantics

Record coordinate conventions, line direction, polygon boundary behavior, track start/end, minimum dwell, cooldown, re-entry policy, dropped-frame behavior, and source timestamps. Define whether returning objects count again. These rules must not change after inspecting failures without a new acceptance revision.

## 3. Select and measure a pipeline

Ask upstream for current detection and association/tracking candidates with provenance, license, and runtime requirements. Do not retain named algorithms, model IDs, workflow blocks, parameter recipes, or device commands here.

Evaluate the complete detector → association → event-rule pipeline on independently annotated clips. Report:

- event precision/recall and exact numerator/denominator;
- count absolute error and directional error for crossing tasks;
- dwell-time MAE for dwell tasks;
- identity switches/fragmentation when identity matters;
- false events per hour and missed events by occlusion/crowding/site;
- p50/p95 end-to-end latency and effective processed FPS.

Frame-level detections or visual review alone cannot establish event accuracy.

## 4. Diagnose a failed gate

Separate detector misses/duplicates from association breaks, timestamp/drop issues, and event-rule mistakes. Slice by density, occlusion, speed, direction, lighting, source, and camera motion. Test the cheapest falsifiable lever at the responsible stage; do not retrain the detector when the failure is purely temporal logic. Delegate current platform changes upstream, then replay the same clips.

## 5. Decide and deliver

Return `go`, `revise`, or `stop` with event counts, failed clips/slices, replay command, and data boundary. Follow `../../resources/artifact-contract.md`; produce a verified `hosted-client`, offline-tested `local-runtime`, or candid `scaffold`. A passing replay routes to `deliver-cv-project` for stream integration, monitoring, and rollback.

</methodology>

<safety>

- Do not infer personal identity or intent from a track ID.
- State retention/privacy boundaries for video and derived trajectories.
- Obtain explicit consent before data movement or paid work.
- Keep detector, association, and event-rule evidence separate.
- Delegate exact provider execution; never guess current workflow/device details.

</safety>

<ledger>

Follow `../../resources/ledger-protocol.md`. Record acceptance, replay evaluation, artifact, and decision once with non-empty event IDs and explicit status.

</ledger>

\<stop_rules>

- Event semantics or line/zone geometry are undefined → freeze them first.
- No independently annotated representative clips → do not claim event accuracy.
- Required events occur between captured frames or outside view → state the acquisition blocker.
- Paid/data-moving action lacks current-turn consent → stop.
- No replay plus applicable live/offline smoke → artifact remains a `scaffold`.

\</stop_rules>
