---
name: estimate-economics
description: |-
  Estimate CV annotation, training, deployment, and operations economics. TRIGGER when: user invokes `$estimate-economics`, asks labeling/training cost, managed vs self-hosted, build-vs-buy, scale economics, deployment crossover, or selects managed-at-scale after a passing proof. SKIP when: user asks to build/test a detector/classifier/OCR/tracker/pose/mask, count objects, finish the PoC, or keep improving because the eval has not passed yet (solve-cv-task); asks only a current platform how-to; or lacks passing evidence unless explicitly accepting a rough estimate.
---

<objective>

Give a sourced, editable economic view of the CV decision: one-time effort, monthly run-rate, scaling cliffs, uncertainty, and a managed-vs-DIY recommendation only when comparable inputs exist. This is a decision aid, not a provider sales argument.

</objective>

<methodology>

**Platform execution boundary.** Read `../../resources/roboflow-platform-lookup.md` before any provider-specific plan, credit, quote, deployment, or runtime lookup. Delegate exact current pricing and product capabilities to the installed official Roboflow skill or current MCP resource. Sentinel owns normalization, provenance, sensitivity, and the recommendation.

## 1. Establish decision readiness

Read the frozen acceptance artifact, its SHA-256 digest, measured evidence, workload, existing hardware/staff, data volume, and deployment constraints. A measured proof is the preferred basis. If it is absent and the user still wants a rough estimate, label every model/runtime figure as an assumption, retain `proof.status: unbound`, and do not imply technical feasibility or emit `go`.

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

```text
python /absolute/plugin/root/scripts/cost_model.py \
    (--streams <N> [--fps <FPS>] [--uptime <24x7|business>] | --images-per-day <N>) \
    --model-size <nano|medium|large> --region us-east-1 \
    [--existing-gpu] [--on-demand] \
    [--managed-usd-mo <quote> --managed-quote-as-of <YYYY-MM-DD>] \
    [--managed-credits-mo <credits> --credits-source <source> --credits-as-of <YYYY-MM-DD>] \
    [--override-gpu-spot <usd-hour>] [--override-engineer <usd-hour>] \
    [--error-cost-usd <usd> --error-cost-source <source> --error-cost-as-of <YYYY-MM-DD> \
     --current-error-rate <0-1> --model-error-rate <0-1> --error-rates-source <source> \
     [--model-error-rate-upper <0-1>] [--decisions-per-day <N>]] \
    [--acceptance /absolute/project/.vision-delivery/acceptance-<revision>.json]
```

Choose the workload the user has. `--streams` is for always-on cameras. `--images-per-day` is for a batch of images, such as photos checked once a day; `--fps` and `--uptime` do not apply to it. Batch capacity uses the same screening table (images per second per instance), with GPU time billed in whole hours per day.

Value at stake is optional and needs the user's own numbers: the cost of one wrong decision with its source and date, the error rate of the process in place today (`--current-error-rate`: how often the people or the system doing the job now get it wrong, from the user's own records, never from Sentinel's baseline evidence), and the model's measured error rate with the evidence it comes from (for example the scorer's evidence file). Both are error rates, the share of wrong decisions: when the scorer reports a success rate such as accuracy or `exact_match_rate`, the error rate is 1 minus that value, and `--model-error-rate-upper` is 1 minus the lower end of its 95% interval. Pass that upper end to get a low bound. In stream mode also pass `--decisions-per-day`; never derive decisions from frames. In batch mode the tool counts one decision per image unless `--decisions-per-day` says otherwise, and its output states which it used. Never invent an error cost or an error rate: without them the tool prints "Value at stake: not computed", and the report says the same. The value never changes the cost recommendation.

The committed capacity table is a screening assumption calibrated at 10 FPS and scaled linearly by requested FPS. It is not a hardware benchmark. Re-run with measured throughput before a purchase or binding recommendation. A decision-grade run requires `proof.status: bound` and the same `acceptance_sha256` used by the baseline, handoff, and ledger.

Roboflow prices managed usage in credits, so most users have no per-month quote. When the user or current upstream guidance supplies monthly credit use (never inferred from FPS), pass `--managed-credits-mo` with its source and date. The tool prices it only against the public plan anchors in the snapshot (`basis: public-credit-plan`, an upper bound that excludes Enterprise scope) and compares that with DIY. A dated `--managed-usd-mo` quote takes precedence. With neither input, or above 500 credits/month (Enterprise volume pricing), the tool returns `insufficient-data`; provide the DIY estimate and a quote request instead of inventing a winner.

## 4. Stress-test the decision

Vary workload/FPS, compute rate, engineering rate, monitoring effort, failure-review volume, quote scope, and growth. Show the crossover and whether the recommendation changes under plausible high/low cases. Flag old snapshots and validate quote currency/scope separately.

## 5. Emit the decision

For a delivery that will be checked with `../../resources/scripts/check_delivery.py`, also save the estimator's `--acceptance <file> --json` output as `.vision-delivery/economics-<session>.json`; the checker reads the one economics file bound to the acceptance.

Write `.vision-delivery/economics-<session>.md` with assumptions, sources/dates, one-time and recurring tables, sensitivity, excluded costs, recommended path, and re-evaluation trigger. Use `go`, `revise`, or `insufficient-data`; do not force a binary answer.

If the selected path requires integration or deployment, route to `deliver-cv-project`. Sentinel emits a sourced action brief and stops before any paid/state-changing provider action.

</methodology>

<safety>

- Never invent or silently update prices, credits, throughput, discounts, or labor rates.
- Preserve user-supplied quote provenance and scope.
- Reject non-finite/negative numeric inputs and future/invalid quote dates.
- Keep technical feasibility and economic desirability as separate gates.
- Use upstream guidance only for current product truth and the action brief; never invoke provider actions outside the host-gated path.

</safety>

<ledger>

Follow `../../resources/ledger-protocol.md`. Record the sourced economics result and decision once with non-empty event ID, status, workload, dated quote provenance, and material assumptions. Do not duplicate hook-covered MCP actions.

</ledger>

\<stop_rules>

- Neither a comparable managed quote nor sourced monthly credit use is available → return `insufficient-data`, not a winner.
- A `public-credit-plan` verdict → state that it is an upper bound on public anchors and excludes Enterprise SLA and managed GPU scope.
- Capacity is unbenchmarked and the decision is binding → require measurement or state the unresolved risk.
- Price source/date is missing → exclude that figure from the verdict.
- Provider action is required → emit a sourced action brief and stop; conversational consent does not authorize Sentinel execution.

\</stop_rules>
