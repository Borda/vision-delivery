.PHONY: eval eval-trigger eval-cost-model eval-platform-routing eval-hooks eval-e2e

eval: eval-trigger eval-cost-model eval-platform-routing eval-hooks eval-e2e

eval-trigger:
	python3 evals/trigger/run.py

eval-cost-model:
	python3 evals/cost-model/assert_cost_model.py

eval-platform-routing:
	python3 evals/platform-routing/assert_platform_routing.py

eval-hooks:
	node evals/hooks/cta_smoke.mjs

eval-e2e:
	@echo "eval-e2e: no executable harness yet — see evals/e2e/*.e2e.md for manual steps (M-later)"
