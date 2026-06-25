# E2E Spec — segment-and-analyze vertical

**Fixture:** `universe.roboflow.com` public concrete/bridge crack segmentation dataset with polygon mask annotations — search `crack segmentation masks>200 sort:stars` for a suitable public dataset; confirm license before use. Equivalent scope: any public segmentation dataset with mask annotations for defect-class objects (corrosion, lesion, crack).
**Harness:** manual acceptance (executable runner = TODO(M-later))

---

## Prerequisites

- `ROBOFLOW_API_KEY` set in env or `.env` at project root.
- Claude Code launched with `claude --plugin-dir .` from this repo.
- A public Universe segmentation dataset confirmed accessible via API (cross-workspace Universe datasets accessible read-only).

---

## Sequence

### Step 1 — Cold prompt (user-initiated)

> "I need to measure crack widths on bridge deck photos for our inspection report. The cracks need to be outlined precisely and their width measured in millimeters."

**Expected:** `segment-and-analyze` skill fires (description-match routing on "crack", "measure", "outline", "millimeters"). No `auth-setup` flow if key is present.

---

### Step 2 — Eval definition (skill-led)

Skill asks at most 3 targeted questions:
1. What is the acceptable IoU threshold? (segmentation quality gate)
2. Do you need physical measurements (mm) or pixel counts only? (calibration requirement)
3. Target class(es) and batch vs real-time?

**Expected response for this fixture:**
- Target: crack
- IoU threshold: ≥ 0.80
- Area error ceiling: ≤ 15% (physical measurement goal)
- Calibration: ruler or known reference object present in inspection photos
- Mode: batch (still images from inspection drone/camera)

Skill writes `eval_definition.md` to the working directory.

**[Live step — no credits]**

---

### Step 3 — Foundation-model-first: SAM zero-shot

crack is not in COCO 80 → skill does NOT use RF-DETR detection directly. Instead:

1. Skill proposes SAM zero-shot via Roboflow Workflows as first attempt.
2. Run SAM on 20 sample crack images (box-prompt mode: bbox from image center or user-supplied ROI).
3. Measure mean IoU against any available ground-truth masks.

**Expected:** skill reports SAM zero-shot IoU score; if no GT masks available, requests user visual inspection of 5 sample outputs before proceeding.

**[Live step — Workflows inference credits may apply; test on ≤20 images first]**

---

### Step 4 — Measure against eval

Skill reports exact numbers:
- Mean IoU (from SAM zero-shot on sample set)
- Area error % (if ground-truth mask areas available)
- Compares against eval threshold (IoU ≥ 0.80)

Example measurement (placeholder — actual values depend on fixture and SAM performance):
> "SAM zero-shot on 20 crack images: mean IoU = 0.68, area error = 22%. Threshold is IoU ≥ 0.80 — missed by 12 points."

**[Live step — inference credits may apply for large batches; test on ≤20 images first]**

---

### Step 5 — Eval result branch

#### 5a — SAM zero-shot passes (mean IoU ≥ 0.80)

Skill proceeds directly to Step 6 (PoC artifact).

#### 5b — SAM zero-shot fails (mean IoU < 0.80)

Skill offers fastest lever first:

**5b-i — SAM prompt tuning (zero label cost):**
- Switch from center-point prompt to box-prompt or multi-point prompt.
- Re-measure IoU on same 20 images after prompt change.
- Expected IoU gain: 5–15 points. If passes → Step 6.

**5b-ii — Fine-tune on labeled masks (credit-spending step):**
- Requires labeled segmentation dataset. If user has none: offer annotation via Roboflow UI.
- Show credit estimate for `models_train` before calling.
- Wait for explicit "yes" in current turn before submitting training job.
- After training: re-measure IoU. If passes → Step 6. If still fails → offer data collection guidance.

**[Step 5b-ii is a credit-spending step — MUST show credit estimate and wait for explicit "yes" before calling `models_train`]**

---

### Step 6 — Calibration step (when physical units requested)

When user needs mm measurements (as in this fixture's eval):

1. Skill asks: "Is there a reference object of known size visible in your inspection photos? (e.g. a ruler, a bolt of known diameter, a tile of known width)"
2. User confirms reference object and its known dimension (e.g. "50 mm calibration bar").
3. Skill guides pixel measurement of the reference object → computes `px_per_mm`.
4. PoC script is updated with the computed `px_per_mm` constant.
5. Skill states limit: "This calibration applies only when the same camera distance and zoom are used. Different standoff distances need recalibration."

**[Live step — no credits; requires user to supply calibration measurement]**

---

### Step 7 — PoC artifact delivery

Skill produces:
- `segment_measure.py` — runnable inference + measurement script with `PX_PER_MM` populated from calibration step; mask polygon → area_px, area_mm2, perimeter_px
- `eval_definition.md` — IoU threshold, area error ceiling, calibration method, dataset source

Both files must be runnable on a fresh machine with `requests`, `numpy`, and `opencv-python` installed.

---

### Step 8 — Seam offer (once, declinable)

Skill checks `.vision-delivery/session-<id>.offered`.
If absent: fires offer once.
```
"Model passes eval. Next step:
 (a) Export and run locally (ONNX/TensorRT, free, runs on your machine)
 (b) Deploy to a managed Roboflow endpoint (handles scaling, monitoring)
 (c) Skip for now"
```

**Asserts:** offer fires exactly once across a session (sentinel written after first offer; not re-offered on second pass).

---

### Step 9 — Ledger write

After any solve action, `.vision-delivery/ledger.jsonl` is updated.
Check: file exists, last line is valid JSON with `skill: "segment-and-analyze"` and `action` matching the completed step.

Expected records in order:
1. `eval_definition` — after eval_definition.md written and confirmed
2. `baseline_measured` — after SAM zero-shot IoU measured
3. `models_train` — if fine-tuning was required (credit-confirmed)
4. `project_deployment_launch` — if user selected (b) in seam offer

---

### Step 10 — [Acceptance — live deploy, not part of this automated spec]

If user selected (b) in Step 8: deployment-consultant is invoked.
`project_deployment_launch` NOT called without explicit credit confirmation.
This step is a manual acceptance test only — a Roboflow deployment is created and the URL is returned.

**[Credit-spending step — requires explicit user confirmation in session]**

---

## Done When

- Steps 1–9 complete end-to-end with the pinned fixture.
- `segment_measure.py` runs on a fresh machine and returns area_px per crack instance.
- `eval_definition.md` contains the agreed IoU threshold and calibration method.
- `.vision-delivery/ledger.jsonl` has entries for each completed action.
- Seam offer fired exactly once (sentinel file present).
- Calibration limit stated explicitly in skill output before any mm² figure reported.
- Step 10 (live deploy) verified manually by user as acceptance.

## TODO(M-later): executable e2e runner

Convert this spec to an automated harness that drives the above sequence via the Claude Code SDK or a test driver. Not in this pass — see trigger eval runner note in `evals/trigger/run.mjs`.
