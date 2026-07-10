# E2E Spec — solve-cv-task router

**Fixture:** none required for routing assertions; Steps 4+ reuse the `detect-and-analyze` fixture (`sandbox-ibs0b/cars-jnnoy-mmrcu/1`). **Harness:** manual acceptance; routing steps are covered automatically by the live trigger eval (`evals/trigger-live/`) when run.

______________________________________________________________________

## Prerequisites

- Claude Code launched with `claude --plugin-dir .` from this repo.
- `ROBOFLOW_API_KEY` set only for Steps 4+ (routing itself must work keyless).

## Sequence

### Step 1 — Ambiguous cold prompt (discriminator)

> "Count the defective items coming off this line — here are sample images."

**Expected:** `solve-cv-task` fires (not a modality skill directly), applies the detect-vs-classify discriminator (object-level count → detection), and dispatches into `detect-and-analyze` methodology. The discriminator question is asked ONLY if the object-vs-image-level answer is not inferable from the prompt.

### Step 2 — Multi-skill prompt (pipeline detection)

> "Detect forklifts in my footage, track how long each stays in the loading zone, and read the pallet labels."

**Expected:** router recognizes a multi-modality pipeline (detect + track + read-text), states the decomposition explicitly, and sequences skills with typed artifacts between them — it does NOT silently run only the first modality. If the prompt includes ongoing monitoring/alerting language, route to `decompose-to-pipeline` instead.

### Step 3 — Economics deflection

> "What would it cost to run this at 10 streams?"

**Expected:** router does NOT answer pricing; routes to `estimate-economics` (or names `/sentinel:estimate-economics`). No cost numbers appear in router output.

### Step 4 — Keyless behavior

**Expected:** with no `ROBOFLOW_API_KEY`, router still does partial work (eval definition, approach) and only surfaces `auth-setup` at the first Universe-dependent action.

### Step 5 — Ledger write

**Expected:** routing itself writes no ledger rows; the dispatched skill owns ledger writes per `skills/_shared/ledger-protocol.md`.

## Done When

- Ambiguous prompts route through the discriminator, not straight to a modality skill.
- Multi-skill prompts produce an explicit pipeline plan.
- No cost talk from the router; keyless partial work confirmed.
