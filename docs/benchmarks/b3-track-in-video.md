---
description: Pending B3 tracking benchmark specification covering dwell-time evidence, privacy, streaming, and comparison requirements.
title: B3 Tracking Fixture — Pending
---

# B3 tracking fixture — pending

**Prompt:** “Track how long shoppers spend in each aisle; I have RTSP streams.” **Route:** `track-and-count`. **Status:** specification only; no live RTSP or dwell result is committed.

## Intended business gate

The draft fixture proposes per-zone dwell-time mean absolute error, identity errors, event-count error, latency, and stream recovery. The earlier 30-second threshold is a fixture hypothesis, not a generally valid retail requirement.

## Required evidence

1. Establish lawful purpose, minimization, retention, signage/notice where applicable, and a non-identifying output design.
2. Pin consented or synthetic video, zone definitions, and ground-truth dwell intervals.
3. Define stream loss, restart, occlusion, camera handoff, and identity-reset behavior.
4. Measure detection, tracking, dwell error, throughput, and failure recovery on target hardware.
5. Verify current Workflow and RTSP capabilities through official Roboflow sources.
6. Execute the deployed or local artifact; record downtime and false event behavior.
7. Run a repeated clean comparator before claiming reduced calls or integration effort.

## Current claim boundary

The route can guide tracking evaluation. This page does not establish a particular tracker choice, one-call RTSP deployment, production endpoint, privacy compliance, or superiority to a plain agent. Production streaming architecture and people analytics are expert-required.

```bash
claude --plugin-dir . "Track anonymous object dwell time in these authorized RTSP test streams."
```

Running the command is only the start of the study; it is not a benchmark result.
