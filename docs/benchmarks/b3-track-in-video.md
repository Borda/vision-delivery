---
description: Fixture-defined B3 benchmark for vision-delivery track-and-count, covering shopper dwell time, RTSP tracking, and pending live measurement status.
title: B3 Track And Count Benchmark
---

# B3 Benchmark — Track and Count: Shopper Dwell Time

**Problem:** track shoppers across RTSP streams and measure dwell time per aisle zone. **Vertical:** `track-and-count` skill. **Evidence:** benchmark fixture defined; live measurements pending. **Last updated:** 2026-06-25.

> This page defines the benchmark fixture and acceptance criteria for the `track-and-count` route.

______________________________________________________________________

## Fixture

- **Dataset:** TBD — pending live run (Universe: person detection, retail/indoor video)
- **Pinned version:** TBD
- **Images:** TBD
- **Classes:** person
- **License:** Universe public
- **Primary eval metric:** Dwell time MAE ≤ 30 s per zone

Dataset note: Retail-environment person detection datasets on Universe (e.g. `person-detection-retail`) are the closest proxy. RTSP stream acceptance testing requires a live stream or RTSP simulator; B3 fixture covers detection/tracking eval on recorded frames; the RTSP deploy step is an acceptance gate requiring API key + credits.

______________________________________________________________________

## Problem definition

> "Track how long shoppers spend in each aisle — I have RTSP streams."

- **Target class:** `person`
- **Eval metric:** Dwell time MAE ≤ 30 s per zone (compare plugin-measured dwell vs ground-truth annotated clips)
- **Threshold:** MAE ≤ 30 s per zone is the business floor. Sub-threshold after backbone selection → zone polygon tuning. Still failing → re-annotate clips or adjust FPS.
- **Mode:** live RTSP stream (real-time); batch video frames for offline eval

______________________________________________________________________

## Baseline results

TBD — pending live run.

- **Detection backbone:** RF-DETR Nano — real-time throughput; TBD fps
- **Tracker:** ByteTrack via Roboflow Workflow
- **Dwell MAE — zone A:** TBD
- **Dwell MAE — zone B:** TBD
- **Dwell MAE — overall:** TBD
- **Threshold:** ≤ 30 s MAE per zone — set before baseline measured
- **RTSP deploy:** TBD — 1-call path once API key + credits are confirmed

ByteTrack is selected over DeepSORT because it is natively supported in Roboflow Workflows and requires no separate Re-ID model — reducing latency for real-time RTSP streams.

______________________________________________________________________

## Plugin vs plain agent

**Expected plain-agent behavior (not yet measured):**

- Suggests ByteTrack or DeepSORT; describes integration steps
- Detection backbone described, not measured
- Workflow not constructed
- Zone polygon definition described manually
- RTSP endpoint deploy requires manual integration work
- No dwell metric produced
- Runnable PoC not guaranteed in-session

**vision-delivery behavior to measure:**

- Route to `track-and-count`; anchor to dwell MAE ≤ 30 s threshold first
- RF-DETR Nano selected; fps measured on target hardware
- ByteTrack Workflow built in session
- Zone polygons defined interactively in Workflow
- **RTSP endpoint deploy: 1 call** (`project_deployment_launch`) after eval passes and credit spend is confirmed
- Dwell time per zone exported (JSON / CSV)
- Steps to working PoC: eval → backbone → Workflow → zones → RTSP deploy → metric reporting (8 steps)

**RTSP one-call deploy** is the differentiator for B3. The controlled comparison must verify whether the plugin reduces the manual Workflow and RTSP setup to a single `project_deployment_launch` call.

______________________________________________________________________

## Plugin path — step-by-step

1. **Eval definition** — dwell time MAE ≤ 30 s per zone; written to `eval_definition.md` before any model or tracker selection.
2. **Detection backbone selection** — RF-DETR Nano chosen for real-time throughput; fps measured on user's hardware.
3. **ByteTrack Workflow construction** — Roboflow Workflow assembled: detect → ByteTrack → zone dwell accumulator.
4. **Zone polygon definition** — aisle zones defined as polygons in the Workflow (user annotates zones or plugin derives from store map).
5. **RTSP endpoint deploy** — `project_deployment_launch` call; endpoint URL returned; stream connect confirmed.
6. **Dwell metric reporting** — per-zone dwell time exported as JSON/CSV; threshold comparison logged.

______________________________________________________________________

## Plain-agent path

Send the same cold prompt to Claude Code without the plugin:

> "Track how long shoppers spend in each aisle — I have RTSP streams."

Typical plain-agent response:

- Describes ByteTrack or DeepSORT and how they work.
- Outlines integration steps (install ultralytics, configure RTSP pull, write zone logic).
- Cannot construct a Roboflow Workflow.
- Cannot deploy an RTSP endpoint in-session.
- Cannot measure dwell MAE against a threshold.
- No runnable PoC produced in session.

______________________________________________________________________

## Reproduce

### Prerequisites

1. `export ROBOFLOW_API_KEY=<your-key>` or create `.env` at project root.
2. RTSP deploy is the acceptance step — requires API key + credits. Zone polygon definition requires either a store map or interactive annotation.
3. For offline eval: record a short aisle clip with ground-truth dwell annotations.

### Plugin run

```bash
git clone https://github.com/Borda/vision-delivery
cd vision-delivery
claude --plugin-dir . "Track how long shoppers spend in each aisle — I have RTSP streams"
```

`--plugin-dir .` is required. Without it, the session falls back to the plain-agent path.

### Plain-agent run (comparison)

```bash
claude   # no --plugin-dir flag
```

> "Track how long shoppers spend in each aisle — I have RTSP streams."

Record: whether a Workflow was constructed, whether RTSP was deployed, whether dwell MAE was measured, whether a runnable endpoint was produced.

______________________________________________________________________

## Notes

- ByteTrack over DeepSORT: ByteTrack requires no Re-ID model; it runs in-Workflow natively; lower latency for real-time RTSP.
- Zone polygons must match physical store layout — the plugin offers a seam to upload a store map and auto-derive polygon coordinates, but this requires `[Together]` collaboration for the first run.
- RTSP one-call deploy is the differentiator vs plain agents for this use case; acceptance must validate the actual turn count and deploy path.
- Dwell MAE threshold (30 s) is a business floor, not a hard CV metric. It encodes the business requirement: 30 s resolution is sufficient for aisle optimization decisions.
