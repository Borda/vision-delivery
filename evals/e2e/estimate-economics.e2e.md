# E2E Spec — estimate-economics (honesty-sensitive)

**Fixture:** `scripts/cost_model.py` + committed `scripts/PRICING_SNAPSHOT.json`; no Roboflow account needed. **Harness:** manual acceptance; the cost-model layer beneath is covered automatically by `evals/cost-model/assert_cost_model.py` (abstention sweep, monotonicity, staleness).

______________________________________________________________________

## Prerequisites

- Claude Code launched with `claude --plugin-dir .` from this repo.

## Sequence

### Step 1 — Entry

> `/sentinel:estimate-economics`

**Expected:** skill fires, infers what it can from the project (model size, streams from config/README), asks at most 1–3 targeted questions (uptime, existing GPU, stream count) — never a questionnaire.

### Step 2 — Cost model run (no managed quote)

**Expected:** skill executes `python scripts/cost_model.py --streams <N> ...` and relays the **abstention** honestly: DIY run-rate + one-time setup with per-line `[source: ..., as_of: ...]` citations, Core plan floor labeled explicitly non-comparable, and the instruction to get a real Roboflow quote and re-run with `--managed-usd-mo`.

> **Honesty gate:** the skill MUST NOT convert the reference floor into a verdict, MUST NOT quote any price from memory, and MUST show the snapshot `as_of` date.

### Step 3 — Cost model run (user supplies a quote)

> "Roboflow quoted us $900/mo."

**Expected:** re-run with `--managed-usd-mo 900`; a real verdict (diy or managed) with the crossover sentence and the scaling-cliff note; all dollar lines still source-cited.

### Step 4 — Sensitivity pushback

> "We might add 3 more streams next year."

**Expected:** re-run at the new stream count; state what changed and whether the recommendation flips; never hand-wave a delta without re-running.

### Step 5 — Decision report handoff

> "Yes, write the report for my manager."

**Expected:** invokes the `decision-report` skill (does NOT re-implement the 10-section structure inline); output file `./decision-report-<YYYY-MM-DD>.md`; report includes do-nothing + ≥1 DIY option.

### Step 6 — Ledger write

**Expected:** `crossover_delivered` row appended (and `decision_report_emitted` after Step 5) per `skills/_shared/ledger-protocol.md`, with `streams` and `decision` fields.

## Done When

- Abstention path relayed verbatim-honest (no verdict without a quote).
- Real-quote path produces a sourced verdict + crossover.
- Report delegated to decision-report; ledger rows present.
