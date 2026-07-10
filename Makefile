.PHONY: eval eval-trigger eval-entrypoints eval-cost-model eval-platform-routing eval-hooks eval-trigger-live eval-ab-smoke eval-e2e

eval: eval-trigger eval-entrypoints eval-cost-model eval-platform-routing eval-hooks eval-e2e

eval-trigger:  # description lint (vocabulary coverage) — real routing = eval-trigger-live
	python3 evals/trigger/run.py

eval-entrypoints:
	python3 evals/trigger/assert_entrypoint_adapters.py

eval-trigger-live:  # live routing accuracy — one model call per case; on-demand, not per-PR
	python3 evals/trigger-live/run_live.py

eval-ab-smoke:  # one S1 cell, both arms, vs mock MCP — on-demand, not per-PR
	python3 evals/ab/runner.py --scenario s1-conveyor-detect --arm P --runs 1
	python3 evals/ab/runner.py --scenario s1-conveyor-detect --arm B --runs 1
	python3 evals/ab/analyze.py $$(ls -td evals/ab/runs/*s1* | head -2)

eval-cost-model:
	python3 evals/cost-model/assert_cost_model.py

eval-platform-routing:
	python3 evals/platform-routing/assert_platform_routing.py

eval-hooks:
	node evals/hooks/cta_smoke.mjs

eval-e2e:
	@echo "eval-e2e: no executable harness yet — see evals/e2e/*.e2e.md for manual steps (M-later)"
