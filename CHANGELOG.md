# Changelog

All notable changes to Sentinel are recorded here. This project uses semantic versioning; see the [release policy](docs/release-policy.md).

## 0.4.0 (unreleased)

The repository manifests, package metadata, citation metadata, runtime ledger records, and documentation examples target version `0.4.0`. This entry does not assert that a remote tag, marketplace release, or GitHub release has been published.

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
