# E2E Spec — read-text vertical

**Fixture:** `universe.roboflow.com` — search `"PCB serial number"` or `"label OCR"` for a public dataset with labeled text fields; Universe has several PCB inspection and product-label datasets with ≥100 images. Alternatively use any public labeled OCR dataset where ground-truth field values are known per image. **Note:** A concrete pinned fixture will be added once a cross-workspace-accessible Universe OCR dataset is confirmed (same constraint as detect-and-analyze conveyor fixture). Use the search path above to find a current candidate. **Harness:** manual acceptance (executable runner = TODO(M-later))

______________________________________________________________________

## Prerequisites

- `ROBOFLOW_API_KEY` set in env or `.env` at project root.
- Claude Code launched with `claude --plugin-dir .` from this repo.
- 20–40 fixture images with known ground-truth field values (e.g. serial number strings) for CER/field-match computation.

______________________________________________________________________

## Sequence

### Step 1 — Cold prompt (user-initiated)

> "I need to read serial numbers off circuit boards coming off the production line. Images are from a fixed overhead camera."

**Expected:** `read-text` skill fires (description-match routing). No `auth-setup` flow if key is present.

______________________________________________________________________

### Step 2 — Eval definition (skill-led)

Skill asks at most 3 targeted questions:

1. What accuracy is needed? (field match floor or CER ceiling)
2. Real-time inline inspection (latency ≤200 ms) or batch?
3. What text fields are being extracted? (serial number only, or multiple fields?)

**Expected response for this fixture:**

- Target field: `serial_number`
- Field match floor: ≥95% (one missed serial = failed traceability)
- Latency: ≤200 ms/image (inline conveyor inspection)

Skill writes `eval_definition.md` to the working directory.

**[Live step — no credits]**

______________________________________________________________________

### Step 3 — Foundation-model-first (OCR Workflow)

Serial numbers on PCB labels are printed text — DocTR or PaddleOCR block handles them without custom training.

**Expected:** skill selects a DocTR OCR Workflow block (or builds a detection + OCR chain if label region detection is needed). No `trainings_create` called at this stage. Skill explains why: general printed text, pre-built OCR block sufficient for first pass.

**[Live step — read-only MCP, no credits]**

______________________________________________________________________

### Step 4 — Measure against eval

Skill runs the Workflow on a sample of fixture images.

Reports (example baseline — actual numbers depend on fixture):

- Field match: **71%** zero-shot (typical starting point for raw OCR without preprocessing)
- CER: **4.8%**
- Latency: **140 ms/image**
- Threshold: **field match ≥ 95%** — missed by 24 points

Compares against threshold. Reports pass or fail with exact numbers.

**[Live step — Workflow inference; minimal credits for small batches]**

______________________________________________________________________

### Step 5 — Eval result branch

#### 5a — Passes (field match ≥ threshold)

Skill produces `extract_text.py` and `eval_definition.md`. Proceeds to Step 7 (seam offer).

#### 5b — Fails (field match < threshold)

Skill offers fastest lever first in this order:

1. **Image preprocessing** — resize image crop to ≥32 px text height, apply Otsu binarization, deskew. No labeling required; often closes 10–20 field-match points.
2. **OCR engine switch** — benchmark PaddleOCR and Tesseract against DocTR baseline on the fixture; report field match and CER for each engine.
3. **Detection crop first** — add a label-region detection step before OCR to isolate the serial number field; Universe search: `"PCB label detection"` or `"serial number region"`.
4. **Fine-tune** — only if all above fail and fonts are highly stylized (e.g. embossed, low-contrast ink). Show credit estimate; wait for explicit yes before calling `trainings_create`.

> **Credit gate — Step 4 fine-tune:** MUST show credit estimate and wait for explicit "yes" before calling `trainings_create`.

After each lever: re-measure and report updated field match and CER. If passes → Step 6. If still fails after all levers → offer data collection guidance (annotate more diverse lighting/angle images).

______________________________________________________________________

### Step 6 — PoC artifact delivery

Skill produces:

- `extract_text.py` — runnable script that calls the OCR Workflow, returns `{"path": ..., "fields": {"serial_number": "SN-XXXXXXXX"}}` per image
- `eval_definition.md` — field match and CER thresholds, dataset source, logic used

Both files must be runnable on a fresh machine with only `requests` installed (stdlib otherwise).

______________________________________________________________________

### Step 7 — Seam offer (once, declinable)

Skill checks `.vision-delivery/session-<id>.offered`. If absent: fires offer once.

```
"OCR pipeline passes eval. Next step:
 (a) Export and run locally (ONNX/TensorRT, free, runs on your machine)
 (b) Deploy to a managed Roboflow Workflow endpoint (handles scaling, monitoring)
 (c) Skip for now"
```

**Asserts:** offer fires exactly once across a session (sentinel written after first offer; not re-offered on second pass).

______________________________________________________________________

### Step 8 — Ledger write

After any solve action, `.vision-delivery/ledger.jsonl` is updated. Check: file exists, last line is valid JSON with `skill: "read-text"` and `action` matching the completed step.

______________________________________________________________________

### Step 9 — [Acceptance — live deploy, not part of this automated spec]

If user selected (b) in Step 7: economics-consultant is invoked. `project_deployment_launch` NOT called without explicit credit confirmation. This step is a manual acceptance test only — a Roboflow Workflow deployment is created and the URL is returned.

**[Credit-spending step — requires explicit user confirmation in session]**

______________________________________________________________________

## Done When

- Steps 1–8 complete end-to-end with the pinned fixture.
- `extract_text.py` runs on a fresh machine and returns a `{"fields": {...}}` dict per image.
- `eval_definition.md` contains the agreed CER and field-match thresholds.
- `.vision-delivery/ledger.jsonl` has entries for each completed action.
- Seam offer fired exactly once (sentinel file present).
- Step 9 (live deploy) verified manually by user as acceptance.

## TODO(M-later): executable e2e runner

Convert this spec to an automated harness that drives the above sequence via the Claude Code SDK or a test driver. Not in this pass — see trigger eval runner note in `evals/trigger/run.py`.
