# B2 Benchmark — Classify or Flag: PPE Compliance

**Problem:** detect workers not wearing hard hats in construction site images and flag non-compliant frames.
**Vertical:** `classify-or-flag` skill.
**Last updated:** 2026-06-25 (TBD — pending live run).

---

## Fixture

| Field | Value |
|-------|-------|
| Dataset | TBD — pending live run (Universe: hard-hat / PPE detection dataset) |
| Workspace/Project | TBD |
| **Pinned version** | TBD |
| Images (total) | TBD |
| Classes | hardhat, no-hardhat (and optionally: vest, no-vest) |
| License | Universe public |
| Primary eval class | no-hardhat (safety-critical class; recall is primary metric) |

Dataset note: Roboflow Universe hosts multiple public PPE / hard-hat datasets (e.g. `hardhat-detection`, `ppe-dataset`). Select the dataset closest to the user's camera angle and site conditions. B2 fixture will be pinned once a live run confirms the best match.

---

## Problem definition

> "Flag workers not wearing hard hats on this construction site footage."

- **Target class:** `no-hardhat` (binary: compliant / non-compliant)
- **Eval metric:** Recall@0.50 on `no-hardhat` class (safety-critical: missing a non-compliant worker is worse than a false alarm)
- **Threshold logic:** Recall ≥ 0.90 on `no-hardhat`. If CLIP zero-shot meets threshold, stop — no fine-tuning needed. If not, fine-tune on user's labeled frames.
- **Mode:** batch images or video frames.

---

## Baseline results

TBD — pending live run.

| Metric | Value | Notes |
|--------|-------|-------|
| Model | CLIP zero-shot (ViT-L/14) | SAM3 + CLIP; no custom training |
| Recall@0.50 — no-hardhat | TBD | TBD test images |
| Precision@0.50 — no-hardhat | TBD | |
| F1 — no-hardhat | TBD | |
| **Threshold** | **0.90 recall** | safety-floor; set before baseline measured |

CLIP zero-shot is attempted first because PPE classes (hardhat, vest, person) are well-represented in CLIP's pretraining. If recall falls below threshold, the plugin triggers the fine-tune path using labeled frames from the user's site — this is the critical differentiator vs a plain agent.

---

## Comparison table

| Step | Plain agent (no plugin) | **vision-delivery plugin** | Delta |
|------|------------------------|---------------------------|-------|
| Problem framing | Suggests ViT, ResNet, or a pre-trained PPE model; may skip eval definition | Runs `classify-or-flag`; defines recall ≥ 0.90 threshold before any model search | Plugin anchors to safety metric upfront |
| Zero-shot attempt | Not run; no measurement | CLIP zero-shot → measured recall on user's images | Measured vs described |
| Recall on no-hardhat | N/A | TBD — pending live run | TBD |
| Eval defined before training | No | Yes | Structural |
| Fine-tune decision | Ad hoc ("try fine-tuning") | Data-gated: only if measured recall < 0.90 | Principled threshold gate |
| Steps to working PoC | 0 — no runnable result | 5 steps (eval definition → zero-shot → measure → fine-tune if needed → deploy) | 5 steps saved |
| Deployment | N/A (describes endpoint setup) | Roboflow classifier endpoint — 1 call | Deploy ready |
| Eval defined | No | Yes | ✅ |
| Deploy ready | No | Yes | ✅ |

---

## Plugin path — step-by-step

1. **Eval definition** — recall ≥ 0.90 on `no-hardhat`; written to `eval_definition.md` before any model search.
2. **CLIP zero-shot attempt** — SAM3 + CLIP ViT-L/14 run on user's images; recall measured against threshold.
3. **Measure F1 on fixture images** — plugin reports recall, precision, F1 for `no-hardhat` class; compares against 0.90 threshold.
4. **Fine-tune if needed** — if recall < 0.90: plugin proposes labeling session (seam offer) + Roboflow training on user's frames; confirms before credit spend.
5. **Deploy classifier endpoint** — Roboflow hosted classifier (or Workflow with detection crop + classifier) deployed; inference URL returned.

---

## Plain-agent path

Send the same cold prompt to Claude Code without the plugin:

> "Flag workers not wearing hard hats on this construction site footage."

Typical plain-agent response:
- Recommends a ViT or ResNet PPE model from Hugging Face / Roboflow Universe.
- Describes approach ("fine-tune on your images", "use transfer learning").
- Cannot run zero-shot inference or measure recall.
- Cannot define or enforce the 0.90 recall threshold.
- Cannot construct or deploy a Roboflow Workflow.
- No runnable PoC produced in session.

---

## Reproduce

### Prerequisites

1. `export ROBOFLOW_API_KEY=<your-key>` or create `.env` at project root.
2. Universe has public hard-hat/PPE datasets — no labeling required for zero-shot baseline.

### Plugin run

```bash
git clone https://github.com/<org>/vision-delivery
cd vision-delivery
claude --plugin-dir . "Flag workers not wearing hard hats on this construction site footage"
```

`--plugin-dir .` is required; without it, the `classify-or-flag` skill does not load and the agent falls back to the plain-agent path.

### Plain-agent run (comparison)

```bash
claude   # no --plugin-dir flag
```

> "Flag workers not wearing hard hats on this construction site footage."

Record: whether eval was defined, whether zero-shot was attempted, whether recall was measured, whether a deployable endpoint was produced.

---

## Notes

- Recall (not F1) is the primary metric for safety-critical PPE detection: a missed non-compliant worker is a safety incident; a false positive is a nuisance stop.
- CLIP zero-shot works well for PPE because CLIP was trained on safety-equipment imagery at scale. This benchmark tests whether zero-shot is sufficient before incurring fine-tuning cost.
- B2 fixture will be pinned once a live run selects the best-matching Universe PPE dataset for the user's site conditions.
