.PHONY: ci lint format lint-js typecheck docs-setup docs-build docs-serve eval-setup pre-commit-coverage eval eval-version eval-install eval-package eval-release eval-doctor eval-trigger eval-entrypoints eval-parity eval-cost-model eval-platform-routing eval-hooks eval-ledger eval-methodology eval-artifacts eval-baseline eval-proof-chain eval-decision-report probe-codex probe-claude eval-trigger-live eval-e2e-self-test eval-ab-smoke eval-ab-metrics

ci: eval-setup lint format lint-js typecheck eval

lint:
	pre-commit run ruff --all-files

format:
	pre-commit run ruff-format --all-files

lint-js:
	pre-commit run eslint --all-files

typecheck:
	pre-commit run mypy --all-files

docs-setup:
	python -m pip install -q --requirement docs/requirements.txt

docs-build: docs-setup
	python -m mkdocs build --strict

docs-serve: docs-setup
	@port="$(PORT)"; \
	if [ -z "$$port" ]; then \
		port=$$(python -c "import socket; sock = socket.socket(); sock.bind(('127.0.0.1', 0)); print(sock.getsockname()[1]); sock.close()"); \
	fi; \
	echo "Serving on http://127.0.0.1:$$port/vision-delivery/"; \
	python -m mkdocs serve --dev-addr 127.0.0.1:$$port

eval-setup:
	npm ci --ignore-scripts --audit=false
	python -m pip install -q --requirement evals/requirements.txt

pre-commit-coverage:
	@echo "make ci runs the Ruff, Ruff format, ESLint, and mypy pre-commit hooks plus repository evals."

eval: eval-version eval-install eval-package eval-release eval-doctor eval-trigger eval-entrypoints eval-parity eval-cost-model eval-platform-routing eval-hooks eval-ledger eval-methodology eval-artifacts eval-baseline eval-proof-chain eval-decision-report eval-e2e-self-test eval-ab-metrics

eval-version:
	python scripts/check_versions.py

eval-install:
	python evals/install/assert_distribution.py

eval-package:
	python evals/install/assert_package.py

eval-release:
	python evals/install/assert_release_surface.py

probe-codex:
	@candidate="$$(mktemp -d)/sentinel"; \
	python scripts/build_package.py --out "$$candidate"; \
	python scripts/validate_package.py --package "$$candidate"; \
	python scripts/probe_codex_install.py --candidate "$$candidate"

probe-claude:
	@candidate="$$(mktemp -d)/sentinel"; \
	python scripts/build_package.py --out "$$candidate"; \
	python scripts/validate_package.py --package "$$candidate"; \
	python scripts/probe_claude_install.py --candidate "$$candidate"

eval-doctor:
	python evals/install/assert_doctor.py

eval-trigger:  # description lint (vocabulary coverage) — real routing = eval-trigger-live
	python evals/trigger/run.py

eval-entrypoints:
	python evals/trigger/assert_entrypoint_adapters.py

eval-parity:
	python scripts/sync_codex_skills.py --check
	python evals/parity/assert_skill_parity.py

eval-trigger-live:  # live routing accuracy — one model call per case; on-demand, not per-PR
	python evals/trigger-live/run_live.py

eval-e2e-self-test:  # deterministic mock-smoke parser check; host run needs authenticated disposable homes
	python evals/e2e/run_dual_host_smoke.py --self-test

eval-ab-smoke:  # one S1 cell, both arms, vs mock MCP — on-demand, not per-PR
	python evals/ab/runner.py --scenario s1-conveyor-detect --arm P --runs 1
	python evals/ab/runner.py --scenario s1-conveyor-detect --arm B --runs 1
	python evals/ab/analyze.py $$(ls -td evals/ab/runs/*s1* | head -2)

eval-ab-metrics:  # deterministic A/B analyzer + verdict-rule checks on synthetic run fixtures — no live calls
	python evals/ab/assert_metrics.py

eval-cost-model:
	python evals/cost-model/assert_cost_model.py

eval-platform-routing:
	python evals/platform-routing/assert_platform_routing.py

eval-hooks:
	node evals/hooks/cta_smoke.mjs
	node evals/hooks/gate_smoke.mjs

eval-ledger:
	python evals/ledger/assert_ledger.py

eval-methodology:
	python evals/methodology/assert_methodology_contracts.py

eval-artifacts:
	python evals/artifacts/assert_artifact_contracts.py

eval-baseline:
	python evals/baseline/assert_score_baseline.py

eval-proof-chain:
	python evals/proof-chain/assert_proof_chain.py

eval-decision-report:
	python evals/decision-report/assert_contract.py
