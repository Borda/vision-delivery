.PHONY: ci lint js-lint format types eval eval-version eval-install eval-doctor eval-trigger eval-entrypoints eval-cost-model eval-platform-routing eval-hooks eval-ledger eval-methodology eval-artifacts eval-decision-report eval-trigger-live eval-ab-smoke

ci: lint js-lint format types eval

lint:
	ruff check .

js-lint:
	npm run lint:js

format:
	ruff format --check .

types:
	python3 -m mypy scripts evals resources/scripts

eval: eval-version eval-install eval-doctor eval-trigger eval-entrypoints eval-cost-model eval-platform-routing eval-hooks eval-ledger eval-methodology eval-artifacts eval-decision-report

eval-version:
	python3 scripts/check_versions.py

eval-install:
	python3 evals/install/assert_distribution.py

eval-doctor:
	python3 evals/install/assert_doctor.py

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

eval-ledger:
	python3 evals/ledger/assert_ledger.py

eval-methodology:
	python3 evals/methodology/assert_methodology_contracts.py

eval-artifacts:
	python3 evals/artifacts/assert_artifact_contracts.py

eval-decision-report:
	python3 evals/decision-report/assert_contract.py
