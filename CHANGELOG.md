# Changelog

All notable changes to Sentinel are recorded here. This project uses semantic versioning; see the [release policy](docs/release-policy.md).

## 0.5.0 (unreleased)

The repository manifests, package metadata, citation metadata, runtime ledger records, and documentation examples target version `0.5.0`. This entry does not assert that a remote tag, marketplace release, or GitHub release has been published.

### Added

- Claude Code `PreToolUse` gate (`hooks/gate.js`): paid, data-moving, destructive, or state-changing Roboflow MCP calls are denied without a recorded `action_brief_emitted` ledger row and otherwise routed to the host permission prompt; non-interactive permission modes are denied. Codex remains brief-only.
- `ledger_append.py --operation`, required for successful `action_brief_emitted` rows.
- Explore and deliver modes (`resources/delivery-modes.md`); explore is the default and keeps digests and helper commands out of the conversation.
- Baseline ladder (`resources/baseline-ladder.md`) and stdlib scorer `resources/scripts/score_baseline.py` for a rung 0 baseline with no account.
- Credit-plan economics: `cost_model.py --managed-credits-mo/--credits-source/--credits-as-of` prices sourced credit use against public plan anchors instead of always abstaining.
- A/B analyzer metric v5 with `trap_resisted` and `guardrail_score`; correct trap refusal is no longer a progress loss.
- `scripts/sync_codex_skills.py` generates `codex-skills/` from `claude-skills/`; `make eval-parity` fails on drift.
- Outcome-report issue form, first-baseline example with synthetic placeholder labels, flagship/preview route labels.

### Changed

- Ledger hook and helpers resolve the project root (`CLAUDE_PROJECT_DIR`, then the nearest `.vision-delivery` or `.git` ancestor) instead of the working directory.
- README leads with the spend-protection and first-baseline value, with status condensed into one section.

### Known gaps

- The v0.5 public-install path is unverified; local clean-home probes pass.
- On Codex, provider action briefs are advisory; authorization and execution remain external host/provider controls. On Claude Code, the gate guarantees a host prompt but reads a locally writable ledger and does not cap spend.
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
