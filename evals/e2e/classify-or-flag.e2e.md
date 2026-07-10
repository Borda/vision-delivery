# E2E Spec — classify-or-flag vertical

**Fixture:** construction site hard hat compliance — Universe public safety datasets (e.g. `roboflow-universe-projects/hard-hat-universe` or equivalent PPE compliance dataset with `hard_hat` / `no_hard_hat` classes, ≥200 images, public license). **Harness:** manual acceptance (executable runner = TODO(M-later))

______________________________________________________________________

## Prerequisites

- `ROBOFLOW_API_KEY` set in env or `.env` at project root.
- Claude Code launched with `claude --plugin-dir .` from this repo.
- Access to a Universe PPE / hard hat dataset for zero-shot and fine-tune steps.

______________________________________________________________________

## Sequence

### Step 1 — Cold prompt (user-initiated)

> "I need to flag construction site images where workers are not wearing hard hats. Can you build a classifier for this?"

**Expected:** `classify-or-flag` skill fires (description-match routing on "hard hat", "flag", "classify"). No `auth-setup` flow if key is present.

______________________________________________________________________

### Step 2 — Eval definition (skill-led)

Skill asks at most 3 targeted questions:

1. What is the acceptable false-negative rate? (Recall floor on the `no_hard_hat` class — missing a violation is costly)
2. Real-time (latency < 100 ms per frame) or batch processing?
3. Two classes only (hat / no hat) or additional classes (partial, hard hat + vest)?

**Expected response for this fixture:**

- Target classes: `hard_hat`, `no_hard_hat`
- Recall floor on `no_hard_hat`: ≥ 0.90 (missing a violation is a safety risk)
- Precision floor on `no_hard_hat`: ≥ 0.80 (false alarms acceptable but not excessive)
- Mode: batch (images from site cameras, not real-time streaming)

Skill writes `eval_definition.md` to the working directory.

**[Live step — no credits]**

______________________________________________________________________

### Step 3 — Foundation-model-first (CLIP zero-shot)

`hard_hat` and `no_hard_hat` are visual, describable concepts — CLIP zero-shot is the right first move.

**Expected:**

1. Skill searches Universe for a PPE / hard hat classification dataset:
   ```
   universe_search: "hard hat compliance classification images>100 sort:stars"
   ```
2. Skill presents 2–3 Universe options with image count, license, relevance note. User picks (or skill proceeds with CLIP zero-shot if no strong match).
3. Skill attempts CLIP zero-shot with 3–5 text prompt variants:
   - `"a construction worker wearing a hard hat"`
   - `"a person without a hard hat on a construction site"`
   - `"worker with safety helmet"` / `"worker without safety helmet"`
4. Skill reports best F1 per prompt variant on a sample of ≤20 user images.

**[Live step — read-only MCP calls + inference; minimal credits for small batch]**

______________________________________________________________________

### Step 4 — Measure against eval

Skill measures CLIP zero-shot (or Universe classifier) on a sample of the fixture images.

Expected reported format:

> "Zero-shot CLIP on 50 fixture images: F1 = 0.71 (no_hard_hat class). Recall = 0.68, Precision = 0.74. Threshold is Recall ≥ 0.90 — missed by 22 points."

Compares against threshold. Reports pass or fail with exact numbers. Never softens.

**[Live step — inference credits may apply for large batches; test on ≤20 images first]**

______________________________________________________________________

### Step 5 — Eval result branch

#### 5a — Passes (Recall ≥ 0.90, Precision ≥ 0.80)

Skill produces `classify_image.py` and `eval_definition.md`. Proceeds to Step 7 (seam offer).

#### 5b — Fails (recall or precision below threshold)

Skill offers fastest lever first:

1. CLIP prompt engineering — try 3–5 additional text prompt variants; report best F1 per variant.
2. Fine-tune a ViT-based classifier with labeled images from the Universe fixture or user's own data:
   - `versions_generate` → `trainings_create` with ViT checkpoint.
   - **Credit gate:** MUST show credit estimate and wait for explicit "yes" before calling `trainings_create`.

After fine-tune:

- Skill re-measures Recall and Precision on the held-out split.
- Reports: `"Fine-tuned ViT: Recall = 0.93, Precision = 0.83 — passes eval."` or states still failing and offers data collection guidance.

______________________________________________________________________

### Step 6 — PoC artifact delivery

Skill produces:

- `classify_image.py` — runnable script with API key from env, returns per-image verdict JSON
- `eval_definition.md` — threshold, dataset source, primary metric (F1 / Recall), logic used

Both files must be runnable on a fresh machine with only `requests` installed (stdlib otherwise).

______________________________________________________________________

### Step 7 — Seam offer (once, declinable)

Skill checks `.vision-delivery/session-<id>.offered`. If absent: fires offer once.

```
"Classifier passes eval. Next step:
 (a) Export and run locally (ONNX/TensorRT, free, runs on your machine)
 (b) Deploy to a managed Roboflow endpoint (handles scaling, monitoring)
 (c) Skip for now"
```

**Asserts:** offer fires exactly once across a session (sentinel written after first offer; not re-offered on second pass).

______________________________________________________________________

### Step 8 — Ledger write

After any solve action, `.vision-delivery/ledger.jsonl` is updated. Check: file exists, last line is valid JSON with `skill: "classify-or-flag"` and `action` matching the completed step.

Example entries (YAML render):

```yaml
ts: '2026-06-25T10:00:00Z'
session: 2026-06-25-hard-hat-compliance
skill: classify-or-flag
action: eval_definition
entity_id: <workspace>/<project>
version: 0.1.0
notes: 'classes: hard_hat, no_hard_hat; recall_floor=0.90, precision_floor=0.80'
```

```yaml
ts: '2026-06-25T10:05:00Z'
session: 2026-06-25-hard-hat-compliance
skill: classify-or-flag
action: baseline_measured
entity_id: <workspace>/<project>
version: 0.1.0
notes: 'CLIP zero-shot: F1=0.71, Recall=0.68, Precision=0.74 (no_hard_hat class)'
```

```yaml
ts: '2026-06-25T10:30:00Z'
session: 2026-06-25-hard-hat-compliance
skill: classify-or-flag
action: trainings_create
entity_id: <workspace>/<project>/1
version: 0.1.0
notes: 'ViT classifier fine-tune; checkpoint: universe/<ppe-project>; dataset version
  1'
```

______________________________________________________________________

### Step 9 — [Acceptance — live deploy, not part of this automated spec]

If user selected (b) in Step 7: economics-consultant is invoked. `project_deployment_launch` NOT called without explicit credit confirmation. This step is a manual acceptance test only — a Roboflow deployment is created and the classification endpoint URL is returned.

**[Credit-spending step — requires explicit user confirmation in session]**

______________________________________________________________________

## Done When

- Steps 1–8 complete end-to-end with the pinned fixture.
- `classify_image.py` runs on a fresh machine and returns a verdict dict with `verdict`, `confidence`, and `predictions`.
- `eval_definition.md` contains the agreed F1/Recall/Precision thresholds and dataset source.
- `.vision-delivery/ledger.jsonl` has entries for each completed action.
- Seam offer fired exactly once (sentinel file present).
- Step 9 (live deploy) verified manually by user as acceptance.

## TODO(M-later): executable e2e runner

Convert this spec to an automated harness that drives the above sequence via the Claude Code SDK or a test driver. Not in this pass — see trigger eval runner note in `evals/trigger/run.py`.
