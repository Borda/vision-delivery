# E2E Spec — detect-and-analyze vertical

**Fixture:** `sandbox-ibs0b/cars-jnnoy-mmrcu`, version 1 (100 images · car/motorcycle/truck · aerial/overhead · object-detection) **Note:** original fixture `boxes-jdugd/boxes-on-conveyor` v7 is Universe-workspace-gated (inaccessible cross-workspace via API); this fixture is equivalent in scope (counting objects from overhead view). **Harness:** manual acceptance (executable runner = TODO(M-later))

______________________________________________________________________

## Prerequisites

- `ROBOFLOW_API_KEY` set in env or `.env` at project root.
- Claude Code launched with `claude --plugin-dir .` from this repo.
- `scripts/baseline_map.py` available for local mAP computation.

______________________________________________________________________

## Sequence

### Step 1 — Cold prompt (user-initiated)

> "I have a parking lot camera. I need to count how many cars and motorcycles are in view."

**Expected:** `detect-and-analyze` skill fires (description-match routing). No `auth-setup` flow if key is present.

______________________________________________________________________

### Step 2 — Eval definition (skill-led)

Skill asks at most 3 targeted questions:

1. What is the acceptable count error? (MAE per frame)
2. Real-time (latency < 100 ms) or batch?
3. Target class(es)?

**Expected response for this fixture:**

- Target: car, motorcycle, truck
- Count MAE ceiling: ≤ 2 per image (negotiable)
- Mode: batch (overhead images)

Skill writes `eval_definition.md` to the working directory.

**[Live step — no credits]**

______________________________________________________________________

### Step 3 — Foundation-model-first

car, motorcycle, truck are COCO 80 classes → skill skips Universe search, selects `rfdetr-medium` (non-real-time) or `rfdetr-nano` (real-time) directly per SKILL.md decision tree.

**Expected:** skill mentions COCO coverage, proposes RF-DETR variant, no Universe search performed.

**[Live step — read-only MCP, no credits]**

______________________________________________________________________

### Step 4 — Measure against eval

Skill calls `models_infer` on a sample of test images using the fixture's existing pretrained model.

Reports (measured baseline 2026-06-25):

- mAP@50: **3%** zero-shot (aerial view, COCO distribution mismatch — training needed)
- Count MAE: **1.39** per class per image
- Threshold: **65%** (floor; measured well below floor)

Compares against threshold. Reports pass or fail with exact numbers.

**[Live step — inference credits may apply for large batches; test on ≤20 images first]**

______________________________________________________________________

### Step 5 — Eval result branch

#### 5a — Passes (mAP ≥ threshold)

Skill produces `count_inference.py` and `eval_definition.md`. Proceeds to Step 7 (seam offer).

#### 5b — Fails (mAP < threshold)

Skill offers fastest lever first:

1. Confidence threshold sweep via `model_evals_get_confidence_sweep`
2. Fine-tune with RF-DETR + Universe checkpoint (requires explicit credit confirm before `trainings_create`)

> **Credit gate — Step 2 of 5b:** MUST show credit estimate and wait for explicit "yes" before calling `trainings_create`.

After fine-tune:

- Skill re-measures and reports updated mAP.
- If passes → Step 6. If still fails → offer data collection guidance.

______________________________________________________________________

### Step 6 — PoC artifact delivery

Skill produces:

- `count_inference.py` — runnable script with API key from env, target class parameterized
- `eval_definition.md` — threshold, dataset source, logic used

Both files must be runnable on a fresh machine with only `requests` installed (stdlib otherwise).

______________________________________________________________________

### Step 7 — Seam offer (once, declinable)

Skill checks `.vision-delivery/session-<id>.offered`. If absent: fires offer once.

```
"Model passes eval. Next step:
 (a) Export and run locally (ONNX/TensorRT, free, runs on your machine)
 (b) Deploy to a managed Roboflow endpoint
 (c) Skip for now"
```

**Asserts:** offer fires exactly once across a session (sentinel written after first offer; not re-offered on second pass).

______________________________________________________________________

### Step 8 — Ledger write

After any solve action, `.vision-delivery/ledger.jsonl` is updated. Check: file exists, last line is valid JSON with `skill: "detect-and-analyze"` and `action` matching the completed step.

______________________________________________________________________

### Step 9 — [Acceptance — live deploy, not part of this automated spec]

If user selected (b) in Step 7: economics-consultant is invoked. `project_deployment_launch` NOT called without explicit credit confirmation. This step is a manual acceptance test only — a Roboflow deployment is created and the URL is returned.

**[Credit-spending step — requires explicit user confirmation in session]**

______________________________________________________________________

## Done When

- Steps 1–8 complete end-to-end with the pinned fixture.
- `count_inference.py` runs on a fresh machine and returns a count dict.
- `eval_definition.md` contains the agreed threshold.
- `.vision-delivery/ledger.jsonl` has entries for each completed action.
- Seam offer fired exactly once (sentinel file present).
- Step 9 (live deploy) verified manually by user as acceptance.

## TODO(M-later): executable e2e runner

Convert this spec to an automated harness that drives the above sequence via the Claude Code SDK or a test driver. Not in this pass — see trigger eval runner note in `evals/trigger/run.py`.
