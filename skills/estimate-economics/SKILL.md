---
name: estimate-economics
description: |
  Estimate CV annotation, training, deployment, and operations economics. TRIGGER when: user invokes `$estimate-economics` or `/sentinel:estimate-economics`, asks labeling/training cost, managed vs self-hosted, build-vs-buy, scale economics, deployment crossover, or selects managed-at-scale after a passing proof. SKIP when: user asks to build/test a detector/classifier/OCR/tracker/pose/mask, count objects, finish the PoC, or keep improving because the eval has not passed yet (solve-cv-task); asks only a current platform how-to; or lacks passing evidence unless explicitly accepting a rough estimate.
allowed-tools: Read, Write, Edit, Bash, Glob, Grep
---

<objective>

Give a sourced, editable economic view of the CV decision: one-time effort, monthly run-rate, scaling cliffs, uncertainty, and a managed-vs-DIY recommendation only when comparable inputs exist. This is a decision aid, not a provider sales argument.

</objective>

<methodology>

**Platform execution boundary.** Read `../../resources/roboflow-platform-lookup.md` before any provider-specific plan, credit, quote, deployment, or runtime lookup. Delegate exact current pricing and product capabilities to the installed official Roboflow skill or current MCP resource. Sentinel owns normalization, provenance, sensitivity, and the recommendation.

## 1. Establish decision readiness

Read acceptance evidence, workload, existing hardware/staff, data volume, and deployment constraints. A measured proof is the preferred basis. If it is absent and the user still wants a rough estimate, label every model/runtime figure as an assumption and do not imply technical feasibility.

Collect only missing inputs:

- cameras/streams, FPS per stream, hours/month, region, and retention;
- measured model/runtime class and throughput on representative hardware;
- existing hardware and staff ownership;
- annotation/review volume and loaded hourly rates;
- managed quote amount, scope, currency, taxes, and quote date;
- cost of downtime, misses, false alarms, and review labor.

Do not infer architecture, parameter count, or throughput from the task description. Ask upstream for current product facts and use user benchmarks for capacity.

## 2. Separate costs and sources

Report at least:

- one-time: data preparation/annotation, engineering, integration, validation;
- recurring: compute/service, monitoring/on-call, review labor, storage/egress, drift/retraining;
- scaling cliffs: added instance/service tier, operator load, and availability needs;
- excluded costs and uncertainty ranges.

Every price gets a source and `as_of` date. A user-supplied quote keeps its own quote date; never stamp it with the repository snapshot date. Do not compare a public plan floor or credit bundle to a fully loaded production quote as if scopes were equivalent.

## 3. Run the local estimator honestly

Resolve the helper from the absolute plugin root, not the user's working directory:

```bash
python /absolute/plugin/root/scripts/cost_model.py \
    --streams <N> --fps <FPS> --model-size <nano|medium|large> \
    --uptime <24x7|business> --region us-east-1 \
    [--existing-gpu] [--on-demand] \
    [--managed-usd-mo <quote> --managed-quote-as-of <YYYY-MM-DD>] \
    [--override-gpu-spot <usd-hour>] [--override-engineer <usd-hour>]
```

The committed capacity table is a screening assumption calibrated at 10 FPS and scaled linearly by requested FPS. It is not a hardware benchmark. Re-run with measured throughput before a purchase or binding recommendation.

Without a dated, scope-comparable managed quote, the tool must return `insufficient-data`; provide the DIY estimate and quote request instead of inventing a winner.

## 4. Stress-test the decision

Vary workload/FPS, compute rate, engineering rate, monitoring effort, failure-review volume, quote scope, and growth. Show the crossover and whether the recommendation changes under plausible high/low cases. Flag old snapshots and validate quote currency/scope separately.

## 5. Emit the decision

Write `.vision-delivery/economics-<session>.md` with assumptions, sources/dates, one-time and recurring tables, sensitivity, excluded costs, recommended path, and re-evaluation trigger. Use `go`, `revise`, or `insufficient-data`; do not force a binary answer.

If the selected path requires integration or deployment, route to `deliver-cv-project`. Any paid/deployment action still needs current upstream impact plus explicit current-turn confirmation.

</methodology>

<safety>

- Never invent or silently update prices, credits, throughput, discounts, or labor rates.
- Preserve user-supplied quote provenance and scope.
- Reject non-finite/negative numeric inputs and future/invalid quote dates.
- Keep technical feasibility and economic desirability as separate gates.
- Delegate exact provider execution and product truth upstream.

</safety>

<ledger>

Follow `../../resources/ledger-protocol.md`. Record the sourced economics result and decision once with non-empty event ID, status, workload, dated quote provenance, and material assumptions. Do not duplicate hook-covered MCP actions.

</ledger>

\<stop_rules>

- Comparable managed scope/quote is absent → return `insufficient-data`, not a winner.
- Capacity is unbenchmarked and the decision is binding → require measurement or state the unresolved risk.
- Price source/date is missing → exclude that figure from the verdict.
- Paid action lacks current-turn consent → stop before execution.

\</stop_rules>
