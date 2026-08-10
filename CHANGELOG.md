# Changelog

All notable changes to Sentinel are recorded here. This project uses semantic versioning; see the [release policy](docs/release-policy.md).

## 0.3.0 (unreleased)

The repository manifests, package metadata, citation metadata, runtime ledger records, and documentation examples target version `0.3.0`. This entry does not assert that a remote tag, marketplace release, or GitHub release has been published.

### Changed

- Added host-native Codex MCP wiring, skill instructions, and hook discovery alongside the existing Claude Code integrations.
- Split the thirteen-skill runtime into host-specific trees and enforce semantic parity through shared contracts and evaluations.
- Added deterministic package inventory, closure validation, tamper rejection coverage, and disposable Codex/Claude marketplace install probes.
- Added package presentation assets and clarified local versus public-install support claims.

### Known gaps

- Live routing, installed-host MCP/hook execution, and real Roboflow authorization are not release evidence.
- The manual public-GitHub marketplace installation of Codex and Claude Code is recorded; automated public-install verification is not yet part of CI.
- No novice user-outcome study has been completed.
- Broad live end-to-end evidence exists only for a narrow detection fixture; B2-B5 remain pending.
- Cursor support is not validated.
- The paid-action confirmation remains an agent instruction, not a hard authorization control.

## 0.2.0

Business-first CV delivery workflows, support boundaries, and baseline documentation updates prepared before the native dual-host package work.

## 0.1.0

Initial plugin manifests, CV workflow skills, Roboflow MCP configuration, local ledger tooling, economics tooling, documentation, and evaluation fixtures.
