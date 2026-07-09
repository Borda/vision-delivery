# E2E Spec — track-and-count vertical

**Fixture:** `sandbox-ibs0b/cars-jnnoy-mmrcu`, version 1 (100 images · car/motorcycle/truck · aerial/overhead · object-detection) used as the detection backbone fixture. car, motorcycle, truck are COCO 80 classes → RF-DETR Nano selected as backbone. **Note:** RTSP deploy is a manual acceptance step — no live RTSP stream is pinned in this fixture. The sequence simulates a shopper-tracking use case using the aerial car footage as a stand-in for frame sequences; true RTSP end-to-end requires a live stream URL provided by the user. **Harness:** manual acceptance (executable runner = TODO(M-later))

______________________________________________________________________

## Prerequisites

- `ROBOFLOW_API_KEY` set in env or `.env` at project root.
- Claude Code launched with `claude --plugin-dir .` from this repo.
- A Roboflow workspace with access to `workflows_create` and `project_deployment_launch` MCP tools.

______________________________________________________________________

## Sequence

### Step 1 — Cold prompt (user-initiated)

> "I run a retail store. I want to track how long shoppers spend in each aisle and count how many people cross the entrance line per hour. I have RTSP cameras."

**Expected:** `track-and-count` skill fires (description-match routing). No `auth-setup` flow if key is present. Skill identifies: dwell time + line-cross counting + RTSP → RTSP one-call deploy path is the primary offer.

______________________________________________________________________

### Step 2 — Eval definition (skill-led)

Skill asks at most 3 targeted questions:

1. What is the acceptable line-cross count error? (absolute difference vs ground-truth per hour)
2. What is the acceptable dwell time error? (MAE in seconds vs observed ground-truth)
3. Target class(es) and real-time latency requirement?

**Expected response for this fixture:**

- Target: person
- Line-cross count error ceiling: ≤ 5 entries/hour
- Dwell time MAE ceiling: ≤ 30 seconds
- Mode: real-time RTSP (latency budget: < 100 ms per frame)

Skill writes `eval_definition.md` to the working directory.

**[Live step — no credits]**

______________________________________________________________________

### Step 3 — Foundation-model-first

person is a COCO 80 class → skill skips Universe search, selects `rfdetr-nano` (real-time, < 100 ms) as detection backbone per `skills/_shared/model-selection.md` decision tree. ByteTrack is layered on top via Roboflow Workflows — no separate tracking model.

**Expected:** skill states COCO 80 coverage, proposes `rfdetr-nano` + ByteTrack Workflow, no Universe search performed. Skill explains: "ByteTrack is a Workflows block, not a model — backbone is RF-DETR Nano."

**[Live step — read-only, no credits]**

______________________________________________________________________

### Step 4 — ByteTrack Workflow construction

Skill builds a Roboflow Workflow spec combining:

1. Detection block: `rfdetr-nano` (or `rfdetr-medium` if real-time not required)
2. ByteTrack block: `track_thresh=0.5`, `match_thresh=0.8`, `track_buffer=30` (defaults)
3. Zone polygon block: user-defined aisle polygon coordinates
4. Line-cross block: user-defined entrance line coordinates + direction flag

Skill validates the spec via `workflow_specs_validate` or `workflow_specs_run` on sample frames from the fixture before offering deployment.

**Expected:** Workflow spec printed as JSON; `workflow_specs_run` result shown with sample track IDs and zone assignments.

**[Live step — workflow_specs_run may consume minor credits; validate on ≤5 frames first]**

______________________________________________________________________

### Step 5 — Measure against eval

Skill runs the Workflow on a sample sequence from the fixture (aerial car footage as stand-in for frame sequence; note: MOTA on this fixture is approximate — true eval requires user's own footage with ground-truth tracks).

Reports metrics vs defined thresholds:

- Line-cross count error: predicted vs ground-truth
- Dwell time MAE: mean absolute error in seconds

Non-negotiable format:

> "ByteTrack on 60 s of footage: line-cross error = 3 vehicles/min, dwell MAE = 18 s. Thresholds: error ≤ 5/hr, MAE ≤ 30 s — passes."

Compares against eval definition thresholds. Reports pass or fail with exact numbers.

**[Live step — inference credits may apply; test on ≤20 frames first]**

______________________________________________________________________

### Step 6 — Eval result branch

#### 6a — Passes both thresholds

Skill produces `track_count.py` and `eval_definition.md`. Proceeds to Step 7 (seam offer / RTSP deploy offer).

#### 6b — Fails one or more thresholds

Skill offers fastest lever first:

1. ByteTrack parameter tuning: adjust `track_thresh`, `match_thresh`, `track_buffer` — free, no retraining
2. Confidence threshold sweep on detection backbone via `model_evals_get_confidence_sweep`
3. Fine-tune detection backbone with RF-DETR + labeled data (requires explicit credit confirm before `trainings_create`)

> **Credit gate — Step 3 of 6b:** MUST show credit estimate and wait for explicit "yes" before calling `trainings_create`.

After tuning/fine-tune:

- Skill re-runs Workflow and reports updated metrics.
- If passes → Step 7. If still fails → offer data collection guidance for detection backbone.

______________________________________________________________________

### Step 7 — RTSP one-call deploy offer (seam offer + deploy path combined)

Skill checks `.vision-delivery/session-<id>.offered`. If absent: fires offer once:

```
"Workflow passes eval. RTSP deploy options:
 (a) Deploy to a managed Roboflow endpoint — provide your RTSP URL and I build the live endpoint (credits apply; estimate shown before deploy)
 (b) Export Workflow spec and run locally (self-hosted inference server)
 (c) Skip for now"
```

> **Credit gate — RTSP deploy (manual acceptance only):** `project_deployment_launch` MUST NOT be called without explicit credit confirmation in-session. Manual acceptance test — do not automate it in the runner.

If user picks (a): skill shows credit estimate, waits for explicit yes, then calls `workflows_create` + `project_deployment_launch` and returns the endpoint URL. User points RTSP consumer at the endpoint.

If user picks (b): skill hands off to economics-consultant.

**Asserts:** offer fires exactly once across a session (sentinel written after first offer; not re-offered on second pass).

______________________________________________________________________

### Step 8 — PoC artifact delivery

Skill produces:

- `track_count.py` — runnable script for recorded video (RTSP uses the deployed Workflow endpoint; script uses frame-by-frame inference via detect.roboflow.com)
- `eval_definition.md` — threshold, metric type, dataset source, logic used

Both files must be runnable on a fresh machine with only `requests` installed (stdlib otherwise).

______________________________________________________________________

### Step 9 — Ledger write

After any solve action, `.vision-delivery/ledger.jsonl` is updated. Check: file exists, last line is valid JSON with `skill: "track-and-count"` and `action` matching the completed step.

______________________________________________________________________

### Step 10 — [Acceptance — live RTSP deploy, manual only]

If user selected (a) in Step 7: `project_deployment_launch` is called, endpoint URL is returned. **Credit-spending step — requires explicit user confirmation in session.** This step is a manual acceptance test only — a live Roboflow managed endpoint is created pointing at the RTSP Workflow. Not part of any automated runner.

______________________________________________________________________

## Done When

- Steps 1–9 complete end-to-end with the pinned fixture.
- `track_count.py` runs on a fresh machine and returns frame-level tracking output.
- `eval_definition.md` contains the agreed thresholds (line-cross error ceiling, dwell MAE ceiling).
- `.vision-delivery/ledger.jsonl` has entries for each completed action (`eval_definition`, `baseline_measured`, and `project_deployment_launch` if RTSP deploy accepted).
- Seam offer fired exactly once (sentinel file present).
- Step 10 (live RTSP deploy) verified manually by user as acceptance.

## TODO(M-later): executable e2e runner

Convert this spec to an automated harness that drives the above sequence via the Claude Code SDK or a test driver. RTSP deploy step (Step 10) must remain manual-acceptance-only regardless — it creates a live paid endpoint. See trigger eval runner note in `evals/trigger/run.mjs`.
