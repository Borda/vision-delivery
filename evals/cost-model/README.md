# evals/cost-model/

Assertions for `scripts/cost_model.py` — verifies math correctness and recommendation direction on fixture inputs.

## Run

```bash
make eval-cost-model
# or directly:
python3 evals/cost-model/assert_cost_model.py
```

## Files

- `assert_cost_model.py` — runs cost model against each fixture; asserts recommendation + source citations present
- `fixtures/diy-wins.json` — input where self-hosting should win
- `fixtures/managed-wins.json` — input where managed deployment should win

## Add a fixture

Add a JSON file to `fixtures/` with the cost model CLI inputs and an `expected_recommendation` field (`"diy"` or `"managed"`). The assert script picks up all `*.json` files in `fixtures/`.
