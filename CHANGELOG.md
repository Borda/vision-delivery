# Changelog

All notable changes to Sentinel are recorded here. This project uses semantic versioning; see the [release policy](docs/release-policy.md).

## 0.5.0 (unreleased)

The repository manifests, package metadata, citation metadata, runtime ledger records, and documentation examples target version `0.5.0`. This entry does not assert that a remote tag, marketplace release, or GitHub release has been published.

### Added

- Claude Code `PreToolUse` gate (`hooks/gate.js`): every Roboflow MCP call is classified from `hooks/gate-policy.json`, a policy generated from Roboflow's published tool catalog by `scripts/build_gate_policy.py`. Tools the catalog marks read-only pass, except two billed ones (`models_infer`, `media_analyze`). Every other tool, and any tool the policy does not list, is denied without a structured `action_brief_emitted` ledger row and otherwise routed to the host permission prompt, which shows the brief's scope, cost, data movement, and rollback. `bypassPermissions` and `dontAsk` modes are denied; `auto` mode gets `ask`. Codex remains brief-only.
- Call budgets: two single-image tools (`models_infer`, `autolabel_preview`) run under one brief that states a call budget, so a rung 1 measurement does not prompt for every image. The gate reserves one unit in the ledger (`roboflow_mcp_call_reserved`) for every attempt, under the ledger lock, so parallel calls and calls with no recorded outcome count. In `auto` mode every call inside a budget is still asked.
- The hooks match any MCP server whose name contains `roboflow` in any letter case (a plugin-provided server or a connector included), not only the server named exactly `roboflow`.
- `make eval-upstream`: a release check that fails unless a current upstream tool catalog and skills directory are supplied and still match the committed policy and roster.
- `ledger_append.py --operation` plus `--scope`, `--cost-amount`, `--cost-unit`, `--cost-source`, `--cost-as-of`, `--data-movement`, `--rollback`, and `--call-budget`; a successful `action_brief_emitted` row requires the structured fields, a price date no more than 90 days old, and a readable gate policy, and is rejected for a read-only operation.
- Delegation map freshness check: `evals/platform-routing/upstream-skills.json` pins the upstream Roboflow skill roster, and `make eval-platform-routing` fails on a mapped name the roster lacks, an unmapped roster skill, or a stale skill address anywhere in the shipped text. The same file records the upstream marketplace name, MCP server name and address, and each upstream phrase Sentinel quotes; the check fails when the shipped text disagrees with them, and compares them with a clone when `SENTINEL_UPSTREAM_SKILLS_DIR` is set.
- Explore and deliver modes (`resources/delivery-modes.md`); explore is the default and keeps digests and helper commands out of the conversation.
- Baseline ladder (`resources/baseline-ladder.md`) and stdlib scorer `resources/scripts/score_baseline.py` for a rung 0 baseline with no account. The scorer prints the numerator, denominator, and a 95% interval (Wilson for binomial rates, seeded image bootstrap for per-object count metrics) and gives a four-way verdict: `PASS` only when the whole interval meets the target, `BELOW-TARGET`, `INCONCLUSIVE`, or `NO VERDICT` when a gold image has no prediction, the denominator is zero, or too few cases back the number. Its record adds `numerator`, `denominator`, `interval_lower`, `interval_upper`, `interval_method`, `verdict_reasons`, `passes_acceptance`, and `metric_counts`.
- `validate_proof_chain.py` rejects a baseline record whose `verdict` is not `pass` or whose interval bound does not clear the threshold.
- Credit-plan economics: `cost_model.py --managed-credits-mo/--credits-source/--credits-as-of` prices sourced credit use against public plan anchors instead of always abstaining.
- A/B analyzer metric v5 with `trap_resisted` and `guardrail_score`; correct trap refusal is no longer a progress loss.
- A/B runner simulated approver (`evals/ab/approver.py`, `runner.py --approver`): answers host permission prompts from persona rules in both arms, pins `--permission-mode default`, and logs each decision to `approvals.jsonl`. It has not been exercised in a live run.
- `scripts/sync_codex_skills.py` generates `codex-skills/` from `claude-skills/`; `make eval-parity` fails on drift.
- Docs pages "Modes and the baseline ladder" and "Sample Output". The sample page shows gate decisions, a refused brief, and scorer lines printed by the shipped tools on fixtures; `make eval-docs-samples` fails when a block stops matching the code. It is not a recorded session.
- `resources/scripts/label_gold.py`: guided gold labeling for count and flag tasks, interactive or one label per call (`--record image=value`). It is resumable, writes atomically, never suggests a label, refuses a change once predictions are frozen for that label file, and reports whether the set is large enough for a verdict. Interactive labeling refuses input that is not a terminal. Every write appends a `labels_recorded` ledger row that says how the labels were entered (`interactive-terminal` or `record-option`) and holds a short digest per image, never a label value. The ledger defaults to the nearest `.vision-delivery` folder above the label file; otherwise `--ledger` is required.
- `resources/scripts/freeze_predictions.py` and the ledger action `predictions_frozen`: record the SHA-256 of the rung 0 prediction file and the gold file before scoring; `score_baseline.py --frozen-ledger` refuses a file that was never frozen or changed afterwards. The freeze also records per-image label digests and how the labels were entered. It refuses, unless `--acknowledge-label-change` is passed, when a label differs from an earlier freeze of the same image name or when the label file was written after the prediction file; the scorer then prints that the result is not an independent measurement. The gold file must sit inside the project folder. Scoring without `--frozen-ledger` is unchanged. The rung 0 procedure runs predictions in an isolated subagent that receives image paths and the question only; a host with no subagent tool is recorded as "independence not enforced". The freeze does not prove the predictor never saw the labels: a hand-written ledger row, an earlier unfrozen scoring run, renamed image files, and changed file times are not detected, and labels entered with `--record` are marked, not blocked. The subagent step has not been recorded in a live session.
- `status` skill: a read-only project status (delivery step, locked target, last result and verdict, open action briefs and call budgets, next action) from `scripts/ledger_report.py --status`. It reads briefs and budgets the way the gate does, reports a brief whose state it cannot read as unknown, says when the last result was scored against a different target or cannot be compared with the locked one, and warns when an upstream search was recorded before the target and rung 0.
- `report-outcome` skill and `scripts/outcome_report.py`: draft a redacted outcome report from the ledger for the user to check and post; identifiers, paths, and notes are withheld unless asked for, and it never posts. Credentials, host names, and email and IPv4 addresses are removed in every mode, a metric is named only when the scorer defines it, and the draft states that it cannot detect a customer, site, or person named in words the ledger does not hold.
- `shared/skill-roster.json` is the one skill roster. The trigger, parity, and package checks read it, `scripts/new_route.py` scaffolds a route from `templates/route/`, and `make eval-release` fails when the README, `docs/llms.txt`, `docs/use-cases.md`, the outcome-report form, or the capability contract disagree with it. `make eval-roster` also fails when the router's route table misses a build route, and the methodology and artifact checks take their route lists from the roster. `scripts/new_route.py` and `scripts/publish_run.py` are repository tools and are not in the installed package.
- Router hand-off: when the official `workflow-from-eval` skill is installed, `solve-cv-task` hands it the candidate search after the target and gold set are locked and rung 0 is measured. Paid steps stay behind the action brief and gate, upstream's suite and labels never become gold, and the result is scored again on the held-out gold set. The hand-off is recorded as an `upstream_search_started` ledger row; one search result is scored on the held-out set once, and a further search after that score needs a fresh labeled set. This order is a recorded procedure, not an enforced one, and on Codex the brief is advice.
- `docs/roboflow-skills.md` names one supported dual-plugin topology on Claude Code with the tool names each server gets and what is unverified; `evals/hooks/matcher_topology.mjs` applies the hook matchers and the tool-name parser to those names. The hook matchers no longer match a Roboflow server name with an empty tool name.
- `scripts/publish_run.py` (`make eval-publish-run`): package, mask, and verify behaviour-eval runs into committed `evals/ab/published/` and `evals/trigger-live/published/` folders. The helper decodes every JSON value before it masks or checks, masks home folders, temporary roots, the login name, and the host name, and refuses a run that still holds a credential, an email address, or an IPv4 address, in a file or in a set or run name. `verify` checks the manifest and the folder names; it catches accidental edits, not a coordinated edit of a file and its manifest entry. `make eval` verifies every committed `published/` folder. Both redaction helpers share `scripts/redaction.py`. A published number now needs a committed artifact folder; earlier A/B and routing numbers predate the rule and cannot be re-scored.
- Contributing guide with four pull request lanes (not open until required checks are enforced on `main`), a developing guide, and a roadmap page.
- Outcome-report issue form, first-baseline example with synthetic placeholder labels, flagship/preview route labels.

### Changed

- `ledger_report.py` takes deployment and progress operations from the gate policy. Progress now counts only gated training, evaluation, and inference calls; a read such as a training status poll no longer counts as progress.
- `cost_model.py` no longer contacts the network by default. `--check-sources` runs the reachability check of the price sources and prints the result to standard error.
- Ledger hook and helpers resolve the project root (`CLAUDE_PROJECT_DIR`, then the nearest `.vision-delivery` or `.git` ancestor) instead of the working directory.
- One pitch sentence, word for word, in the plugin manifests (the Codex display copy opens with it), the docs site description and home page, the README, and both `docs/llms*.txt` files; `make eval-release` checks each of those places. It puts the first answer with no Roboflow account first and names Claude Code as the host with the spend gate.
- Quick start reordered: install, a first measured number with no Roboflow account, then Roboflow sign-in only when a later step needs it.
- "Support & Evidence" is the one page that states evidence and limits; the README, docs home, FAQ, trust page, and benchmarks index now give one line and a link instead of repeating the evidence numbers, and the docs home, FAQ, and workflow page link to the trust page instead of repeating the gate paragraph. The benchmark pages and `docs/llms*.txt` keep their numbers, and the README keeps its gate section.
- Codex is labelled the methodology tier with no gate in the README, FAQ, compatibility page, and quick start. Routes without a Sentinel scorer are labelled "no Sentinel scorer yet" in the README and the use-cases page.
- README leads with the spend-protection and first-baseline value, with status condensed into one section.
- Mermaid diagrams replaced by hand-authored animated SVGs in `docs/assets/diagrams/` (README diagram in `assets/`) (flowing edges, sequential node pulse, `prefers-reduced-motion` aware, theme-neutral colours); the `mkdocs-mermaid2-plugin` dependency and the `check-yaml --unsafe` override are removed.

### Known gaps

- The v0.5 public-install path is unverified; local clean-home probes pass.
- On Codex, provider action briefs are advisory; authorization and execution remain external host/provider controls. On Claude Code, the gate guarantees a host prompt but reads a locally writable ledger and does not cap spend.
- The gate covers Roboflow MCP tool calls only; SDK, CLI, and REST calls from a shell or a generated script do not pass through it, and neither does a Roboflow server registered under a name that does not contain `roboflow`. The agent that wants the call writes the brief, and the gate checks its form, not its truth.
- The gate policy is generated from the catalog Roboflow publishes for another host surface; the tool names Claude Code actually receives have not been checked against it in a live session. Unlisted names fail closed.
- Metric v5 has not been applied to recorded A/B runs; the first-baseline example has no recorded real run yet.
- Live routing has not been re-run on the current route set; the release gate now requires it.

## 0.4.0

Never tagged or published. Its changes ship as part of 0.5.0.

### Changed

- Added frozen acceptance, digest-bound artifact/handoff evidence, a terminal proof-chain validator, and full lint/type/eval CI gates.

### Breaking changes and migration

- Acceptance schema 1 now requires `comparator: gte|lte` and a finite non-boolean threshold. Recreate incomplete acceptance files with `freeze_acceptance.py`; never edit a frozen revision.
- Artifact smoke and reviewed-check evidence now use schema 2 plus the domain-separated `SENTINEL-TREE-V2` digest. Rerun the v0.4 helpers to replace legacy evidence.
- Delivery handoffs now require schema 2, canonical argv arrays, an exclusively frozen `freeze_delivery_check.py` command/output contract, `check_contract_path`/`check_contract_sha256`, `expected_stdout_sha256`, and helper-produced local evidence. Schema 1 handoffs are rejected.
- Baseline proof records use the generic `metric`, `comparator`, `threshold`, `observed_value`, and `measured_at` envelope. Terminal report validation requires `ledger_append.py --report <path>` and a matching `report_sha256` receipt.
- `artifact_smoke.py` now requires `--acceptance` and `--evidence-out`; its default is static review only. A human or external host control must explicitly run the generated `--execute-reviewed` command.
- This pre-1.0 incompatible security/evidence correction follows the documented compatibility exception in `docs/release-policy.md`; v0.3 proof artifacts are not silently reinterpreted.

### Known gaps

- Live routing, installed-host MCP/hook execution, and real Roboflow authorization are not release evidence.
- The manual public-GitHub marketplace installation of Codex and Claude Code is v0.3 evidence; the v0.4 public-install path and automated public-install verification remain pending.
- No novice user-outcome study has been completed.
- Broad live end-to-end evidence exists only for a narrow detection fixture; B2-B5 remain pending.
- Cursor support is not validated.
- Provider action briefs are advisory; authorization and execution remain external host/provider controls.

## 0.3.0

### Changed

- Added host-native Codex MCP wiring, skill instructions, and hook discovery alongside the existing Claude Code integrations.
- Split the thirteen-skill runtime into host-specific trees and enforce semantic parity through shared contracts and evaluations.
- Added deterministic package inventory, closure validation, tamper rejection coverage, and disposable Codex/Claude marketplace install probes.
- Added package presentation assets and clarified local versus public-install support claims.

## 0.2.0

Business-first CV delivery workflows, support boundaries, and baseline documentation updates prepared before the native dual-host package work.

## 0.1.0

Initial plugin manifests, CV workflow skills, Roboflow MCP configuration, local ledger tooling, economics tooling, documentation, and evaluation fixtures.
