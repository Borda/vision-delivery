# Compatibility

This matrix records what the repository currently demonstrates. It is not a promise about future host or upstream behavior.

The two supported hosts are not equal. **Claude Code** gets the methodology and the spend gate. **Codex** is the methodology tier: the locked target, the baseline ladder, and the scorer are the same there (no recorded live run on either host yet), but no pre-action hook exists, so there is no gate, and Sentinel only writes the action brief and stops.

| Surface                  | Status                                                               | Verified path                                                                                | Limitation                                                                                                       |
| ------------------------ | -------------------------------------------------------------------- | -------------------------------------------------------------------------------------------- | ---------------------------------------------------------------------------------------------------------------- |
| Codex plugin             | Methodology only, no gate; v0.5 release candidate; local validation  | Clean-home local probe; manual public-GitHub marketplace installation is v0.3-only           | v0.5 public-install path and current-route model/MCP behavior remain unverified.                                 |
| Claude Code plugin       | Methodology and spend gate; v0.5 release candidate; local validation | Clean-home local probe and strict validation; manual public-GitHub installation is v0.3-only | v0.5 public-install path remains unverified; `--plugin-dir` is development-only.                                 |
| Codex and Claude hooks   | Statically validated; Codex active (ledger only, not a gate)         | Host-specific manifests; Codex reports one installed and active `PostToolUse` hook           | Event delivery is host-managed and best-effort, not complete telemetry or an upstream receipt.                   |
| Cursor                   | Unverified                                                           | None                                                                                         | Do not claim support until a manifest, install path, and acceptance test exist.                                  |
| Roboflow MCP             | Upstream dependency                                                  | URL-only `.mcp.json`; Codex marketplace policy requests authorization on use                 | Actual sign-in, account scope, tools, billing, and service behavior are unverified upstream state.               |
| Official Roboflow skills | Compatible by delegation                                             | Prefer installed local skills, then exposed `skill://roboflow/<name>/SKILL.md` resources     | Both plugins register a `roboflow` MCP server; the gate covers both names; no live dual-install run is recorded. |

## Runtime expectations

- Python 3.10 or newer for repository scripts and evals.
- Node.js for the shared Codex and Claude Code hook implementation.
- Codex hook trust after installation or hook changes; use `/hooks` to review the exact hook definition.
- Network access for Roboflow MCP operations.
- A Roboflow account authorized through the host sign-in flow for live MCP operations.

## Compatibility claim gate

A host or integration becomes supported only after the repository contains:

1. a real manifest or configuration path,
2. an exact one- or two-command public-repository installation path,
3. a clean-environment smoke test,
4. a documented capability and permission boundary,
5. a versioned result or CI gate.

Until all five exist, label the surface experimental or unverified.

## v0.4 proof-contract migration

The unreleased v0.4 candidate intentionally replaces the v0.3 artifact verification interface under the documented pre-1.0 policy. Acceptance schema 1 now requires `comparator: gte|lte`. Baseline proof uses `metric`, `comparator`, `threshold`, `observed_value`, and `measured_at`. Smoke and reviewed-check evidence use schema 2 and the domain-separated `SENTINEL-TREE-V2` digest. Delivery handoffs use schema 2, canonical argv arrays, an exclusively frozen `freeze_delivery_check.py` contract, `check_contract_path`/`check_contract_sha256`, and `expected_stdout_sha256`; schema 1 handoffs are rejected rather than silently reinterpreted. `artifact_smoke.py` now requires `--acceptance` and `--evidence-out`, performs static checks by default, and executes only through a human/external-host `--execute-reviewed` invocation. Terminal report receipts require `ledger_append.py --report <path>` and `report_sha256`. Recreate legacy evidence, handoffs, and receipts with the v0.4 helpers; do not edit old records in place.
