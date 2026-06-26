.PHONY: eval eval-trigger eval-cost-model eval-e2e

eval: eval-trigger eval-cost-model eval-e2e

eval-trigger:
	python3 evals/trigger/run.py

eval-cost-model:
	python3 evals/cost-model/assert_cost_model.py

eval-e2e:
	@echo "eval-e2e: no executable harness yet — see evals/e2e/*.e2e.md for manual steps (M-later)"
