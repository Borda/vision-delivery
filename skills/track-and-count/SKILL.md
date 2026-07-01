---
name: track-and-count
description: |
  Track object identity across video frames and produce counts, dwell times, and line-cross events. Covers: identity-linked tracking with ByteTrack, zone dwell time (time an object spends in a defined polygon), line-cross counting (entry/exit direction across a virtual line), RTSP one-call deploy (build a Roboflow Workflow with ByteTrack and deploy to a managed endpoint in one call), managed edge device path (Roboflow manages hardware fleet via devices_list, devices_update_config, devices_get_telemetry). Builds a tracking pipeline: define eval → select detection backbone → add ByteTrack → measure → tune or train if needed → working PoC.
  TRIGGER when: user wants to track object identity across frames ("track X as it moves", "follow this person/vehicle", "how long does X spend in zone Y", "count how many X cross line Z", "dwell time", "line-cross counting", "people counting at entrance", "shopper path", "RTSP tracking", "video analytics with identity", "track the forklift", "follow each detected person across video frames", "measure their path", "alert when vehicle enters zone", "how many vehicles crossed", "track how long shoppers spend")
  SKIP when: per-frame count with no identity needed ("count how many cars are in the parking lot", "how many objects in this image", "number of items per frame" → detect-and-analyze); pixel-precise segmentation or area measurement ("measure the crack area", "segment the lesion" → segment-and-analyze); image-level verdict with no instance tracking ("is this product defective", "classify this image as pass/fail", "flag the whole image" → classify-or-flag); text reading or extraction ("read the serial number", "extract text from label" → read-text); cost/scale/deployment question with no unsolved tracking problem ("how much does managed deployment cost", "self-hosting vs managed comparison" → estimate-economics); user already has working tracker and asks only about export or optimization
allowed-tools: Bash, Read, Write, Edit, Glob, Grep, AskUserQuestion
---

<objective>

Track object identity across video frames and produce identity-linked counts, dwell times, or line-cross events for the user's specific objects and zones. The exit criterion is a working tracker PoC that passes the user's own eval — defined as entry/exit count accuracy, dwell time MAE, or line-cross precision on the user's own footage.

**What this skill covers:**

- **Identity-linked tracking** — ByteTrack algorithm layered on top of a detection backbone via Roboflow Workflows; each detected object gets a persistent track ID across frames
- **Zone dwell time** — time (in seconds) an object with a given track ID spends inside a user-defined polygon zone
- **Line-cross counting** — objects crossing a virtual line; direction-aware (entry vs exit)
- **RTSP one-call deploy** — user provides an RTSP URL → skill builds a Roboflow Workflow (detection + ByteTrack + zone/line logic) and deploys it to a managed endpoint in one call; returns the endpoint URL
- **Managed edge device** — Roboflow manages the edge hardware; `devices_list` shows fleet status, `devices_update_config` pushes model config, `devices_get_telemetry` / `devices_get_logs` provide fleet monitoring; explicitly contrasted with self-hosted inference server

**What this skill does NOT cover:**

- Per-frame count with no identity — "how many cars are in this image" → `detect-and-analyze`
- Pixel-precise outlines or area measurements → `segment-and-analyze`

</objective>

<methodology>

**RTSP / live-stream pre-check (fires before Step 3 if triggered).**

If the user's prompt mentions RTSP, an IP camera stream, 24/7 live inference, or any live-video source combined with cloud deployment intent — surface three honest options **immediately**, before building a Workflow spec or selecting a backbone:

```
"RTSP + live tracking. Three paths — pick before we build:

 (a) Edge inference server — run an inference container on a local machine
     on the same network as the camera. ByteTrack runs locally; lowest latency;
     no cloud inference cost per frame.
     I give you the docker run command and the track_count.py wrapper.

 (b) Frame-pull cloud — pull frames at an interval (e.g. 1 fps) and send
     to a Roboflow Workflow endpoint. Works today; adds round-trip latency.
     Not suitable for real-time counts; fine for periodic zone/dwell checks.

 (c) Roboflow-managed edge device — Roboflow manages the edge device,
     runs ByteTrack locally, streams aggregated events to cloud.
     No local infra ops; fleet monitoring and config push included.
     Ask me to show live device options via the MCP.

Which fits your latency, connectivity, and ops constraints?"
```

Do NOT hard-code "cloud RTSP not supported" as a permanent fact — verify current Roboflow platform status before baking in a limitation. After the user picks a path, continue to Step 1.

Steps 1, 2, 5, 7, and 8 follow the generic sequence in `skills/_shared/fde-methodology.md`. Read that file first. This section documents only the tracking-specific additions.

**Step 3 — Foundation-model-first (tracking-specific).**

Detection backbone selection follows the same COCO 80 / Universe logic as `detect-and-analyze` (see `skills/_shared/model-selection.md`). Quick reference:

- COCO 80 class + non-real-time → `rfdetr-medium`
- COCO 80 class + real-time → `rfdetr-nano` (default for RTSP tracking)

Tracking is ByteTrack layered on top of the detection output via Roboflow Workflows — there is no separate tracking model to select or train. No Universe search for a "tracking model" — search only for the detection backbone if the class is not COCO 80.

Workflow construction: use Roboflow Workflows to combine detection + ByteTrack + zone polygon or line-cross logic. Build the Workflow spec as JSON and deploy via `workflows_create` + `project_deployment_launch`, or use `workflow_specs_run` for a one-shot test before committing to a deployment.

**Step 4 — Measure against the eval (tracking-specific metrics).**

Run inference via `workflow_specs_run` on a sample video clip or image sequence. Report the metric(s) matching the user's stated success condition:

- **MOTA** (Multiple Object Tracking Accuracy) — when ground-truth tracks are available; report as percentage
- **Line-cross count error** — absolute difference between predicted and ground-truth crossing count; express per time unit (e.g. vehicles/min)
- **Dwell time MAE** — mean absolute error in seconds between predicted and observed ground-truth dwell

Non-negotiable format:

> "ByteTrack on 60 s of your footage: MOTA = 81%, line-cross error = 2 vehicles/min. Your threshold is MOTA ≥ 75% — passes."

**Step 5 — Levers (tracking-specific ordering).**

Same generic order as `fde-methodology.md` (confidence-threshold sweep → fine-tune → full train), plus:

- **ByteTrack parameter tuning** — before retraining, tune `track_thresh` (detection confidence floor for track initiation), `match_thresh` (IoU threshold for association), and `track_buffer` (frames to keep a lost track alive). Tuning is free and often closes 5–10 MOTA points. Report the parameter values explicitly.
- If detection backbone mAP is the bottleneck (not association), fine-tune or retrain the detection backbone; ByteTrack parameters do not help a weak detector.

**Step 6 — RTSP deploy path (path selected via pre-check gate above).**

User already picked a path from the RTSP pre-check. Execute the selected path:

**Path (a) — edge inference server:** Provide a docker run command for `roboflow/roboflow-inference-server-cpu` (or GPU variant) and the `track_count.py` script configured for local endpoint (`http://localhost:9001`). No cloud deployment needed.

**Path (b) — frame-pull cloud:** Build a Roboflow Workflow (detection + ByteTrack) and deploy via `workflows_create` + `project_deployment_launch`. User polls the endpoint at their chosen frame interval. State round-trip latency implication explicitly. Show credit estimate and wait for explicit yes before calling `project_deployment_launch`.

**Path (c) — Roboflow-managed edge device (full flow):**

1. **List devices:** `devices_list` — shows id, name, status (online/offline), platform, last heartbeat.

   - If empty: "No devices registered yet. A Roboflow-managed device needs compatible hardware running the Roboflow agent. I can create a device entry via `devices_create` with name=<name>."
   - If devices present: show list and let user pick.

2. **Push model config:** `devices_update_config` with model_id=<workspace>/<project>/<version>. Confirm with user before pushing — replaces current device config.

3. **Verify device running:** `devices_get_telemetry` — show CPU/GPU usage, memory, inference latency on-device.

4. **Tail logs:** `devices_get_logs` — confirm ByteTrack or detection model is running on-device; surface errors.

**Managed-vs-self-managed contrast (state this before user commits to a path):**

|                     | Roboflow-managed edge (c)                   | Self-hosted inference server (a)     |
| ------------------- | ------------------------------------------- | ------------------------------------ |
| Who manages updates | Roboflow                                    | You                                  |
| Config push         | `devices_update_config` (one MCP call)      | Re-deploy container manually         |
| Fleet monitoring    | `devices_get_telemetry`, `devices_get_logs` | Your own logging stack               |
| RTSP ingestion      | On-device, lowest latency                   | On-device, lowest latency            |
| Ops overhead        | Minimal — Roboflow handles agent ops        | Full — container, restarts, upgrades |
| Best for            | Multi-camera fleets, ops-light teams        | Full control, single camera          |

If user arrives at Step 6 without a pre-check path (e.g., described a non-RTSP tracking problem), produce the `track_count.py` local-inference script for recorded video.

Use `workflow_specs_run` or `workflows_run` for one-shot validation before `project_deployment_launch`.

</methodology>

<artifact>

Produce these two user-owned, portable files at Step 6.

**`track_count.py`** — inference script for recorded video (not RTSP; RTSP uses the deployed Workflow endpoint):

```python
import requests, json, base64, sys, time
from pathlib import Path

# ponytail: no SDK — stdlib + requests only
WORKSPACE = "<workspace>"
PROJECT = "<project>"
VERSION = "<version>"
API_KEY = "<from ROBOFLOW_API_KEY env>"
VIDEO_PATH = sys.argv[1] if len(sys.argv) > 1 else None


def track_frame(frame_b64: str, frame_idx: int) -> dict:
    resp = requests.post(
        f"https://detect.roboflow.com/{WORKSPACE}/{PROJECT}/{VERSION}",
        params={"api_key": API_KEY},
        json={"image": frame_b64},
    )
    resp.raise_for_status()
    preds = resp.json().get("predictions", [])
    return {"frame": frame_idx, "predictions": preds, "count": len(preds)}


# NOTE: for RTSP streams use the managed Workflow endpoint returned by project_deployment_launch.
# This script supports recorded video sampled frame-by-frame via cv2 or ffmpeg.
if __name__ == "__main__":
    if not VIDEO_PATH:
        print("Usage: python track_count.py <video_path>")
        sys.exit(1)
    # Frame extraction left to user (cv2 or ffmpeg) — encode each frame as base64 and call track_frame().
    print("Frame-by-frame tracking ready. See track_frame() above.")
```

**`eval_definition.md`**:

```markdown
# Eval — <problem-title>
Date: <ISO8601>
Target class(es): <class list>
Primary metric: <MOTA | line-cross count error | dwell time MAE>
MOTA threshold: <N>% (if applicable)
Line-cross count error ceiling: <N> per <time-unit> (if applicable)
Dwell time MAE ceiling: <N> seconds (if applicable)
Dataset: <N> seconds of footage, source: <fixture or user data>
Threshold logic: max(baseline metric, business floor)
```

Also write a `.vision-delivery/detections.jsonl` append per inference run (format in the `solve-cv-task` composition protocol) — downstream skills consume this.

</artifact>

\<model_pick>

See `skills/_shared/model-selection.md` for the full decision tree and exact model_id values.

Quick reference for tracking (detection backbone only — ByteTrack is added via Roboflow Workflows, not a separate model):

- COCO 80 class + RTSP / real-time → `rfdetr-nano` (default for RTSP tracking)
- COCO 80 class + recorded video / non-real-time → `rfdetr-medium`
- Custom class, first PoC → Rapid or `rfdetr-medium` fine-tune
- Edge hardware, latency critical → `yolov11n`
- Max accuracy, no latency constraint → `rfdetr-large`

ByteTrack has no model_id — it is a Roboflow Workflows block, not a trainable model.

\</model_pick>

\<safe_actions>

Follow the safe-action gates in `skills/_shared/fde-methodology.md` exactly. Quick reference:

- `models_train` → quantified credit estimate + explicit yes required, same turn (format in `fde-methodology.md` Safe Actions)
- `versions_generate` → free but irreversible; state augmentation config before calling
- Image upload → state destination; offer local path if user declines
- `project_deployment_launch` → credit-spending; show estimate, wait for explicit yes; this IS in scope for this skill (RTSP Workflow deploy path) — do not silently defer to `estimate-economics` without offering first

\</safe_actions>

<ledger>

Follow the write protocol in `skills/_shared/ledger-protocol.md`. Write one record per action, append-only to `.vision-delivery/ledger.jsonl`.

Action triggers for this skill:

| Trigger                                                                   | `action` value              | What to put in `notes`                                   |
| ------------------------------------------------------------------------- | --------------------------- | -------------------------------------------------------- |
| `eval_definition.md` written and user confirmed                           | `eval_definition`           | target classes, metric type, threshold                   |
| First `workflow_specs_run` or `models_infer` call returns tracking metric | `baseline_measured`         | `MOTA=X%` or `line-cross error=Y/min` or `dwell MAE=Z s` |
| `models_train` MCP call submitted                                         | `models_train`              | model name, checkpoint, dataset version                  |
| `project_deployment_launch` MCP call submitted for RTSP Workflow          | `project_deployment_launch` | deployment_id, endpoint URL, Workflow spec summary       |
| `devices_update_config` called for managed edge device                    | `edge_device_configured`    | device_id, model_id pushed, telemetry snapshot           |

`entity_id` format: `<workspace>/<project>` for projects; `<workspace>/<project>/<version>` when version is known.

</ledger>

<voice>

Follow voice rules from `skills/_shared/fde-methodology.md`. Short reference:

**Do:**

- "ByteTrack on 60 s of your footage: MOTA = 81%, threshold is 75%. Passes. Fastest next step: tune track_thresh from 0.5 → 0.6."
- "Line-cross error = 3 vehicles/min — threshold is 5/min. Passes."
- "RTSP + Workflow → one-call deploy. I build the Workflow spec now; confirm to deploy (credits apply)."

**Do not:**

- "Looks good!" / "This should work!" / "Great use case!"
- Report passing when threshold not cleared.
- Mention managed deployment, pricing, or cost before eval passes (seam offer fires once at eval-pass only) — exception: RTSP deploy path explicitly surfaces credit warning in-step, as required by `safe_actions`.

</voice>
