# evals/cost-model/

Assertions for `scripts/cost_model.py` — verifies math correctness and recommendation direction on fixture inputs.

## Run

```bash
make eval-cost-model
# or directly:
python3 evals/cost-model/assert_cost_model.py
```

## Files

- `assert_cost_model.py` — runs cost model against each fixture; asserts recommendation + source citations present, plus staleness, monotonicity, quote/credits provenance, abstention, acceptance binding, and numeric-boundary checks
- `fixtures/diy-wins.json` — input where self-hosting should win
- `fixtures/managed-wins.json` — input where managed deployment should win
- `fixtures/abstain-default.json` — no managed figure: must abstain (`insufficient-data`)
- `fixtures/credit-plan-diy-wins.json` / `credit-plan-managed-wins.json` — sourced credits/month within the public Core range: comparison runs on a `public-credit-plan` basis
- `fixtures/credit-plan-beyond-ceiling.json` — credits above the stated 500-credit Core ceiling: pricing would need extrapolation, so it abstains
- `fixtures/credit-plan-quote-overrides.json` — a dated `--managed-usd-mo` quote takes precedence over credits

## Add a fixture

Add a JSON file to `fixtures/` with the cost model CLI inputs and an `expect_recommendation` field (`"diy"`, `"managed"`, or `"insufficient-data"`). Optional keys check the JSON `managed` block: `expect_managed_basis` (`"user-quote"`, `"public-credit-plan"`, or `null`), `expect_managed_total_mo`, and `expect_credit_plan_status` (`"priced"`, `"unpriced"`, or `"superseded-by-quote"`). The assert script picks up all `*.json` files in `fixtures/`.
