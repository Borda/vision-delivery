# Compatibility

This matrix records what the repository currently demonstrates. It is not a promise about future host or upstream behavior.

| Surface                  | Status                             | Verified path                                                                      | Limitation                                                                                         |
| ------------------------ | ---------------------------------- | ---------------------------------------------------------------------------------- | -------------------------------------------------------------------------------------------------- |
| Codex plugin             | v0.3 release candidate; installed  | Clean-home local probe and manual public-GitHub marketplace installation           | Current-route model/MCP behavior remains environment and upstream dependent.                       |
| Claude Code plugin       | v0.3 release candidate; installed  | Clean-home local probe, strict validation, and manual public-GitHub installation   | `--plugin-dir` is development-only; current-route model/MCP behavior remains external.             |
| Codex and Claude hooks   | Statically validated; Codex active | Host-specific manifests; Codex reports one installed and active `PostToolUse` hook | Event delivery is host-managed and best-effort, not complete telemetry or an upstream receipt.     |
| Cursor                   | Unverified                         | None                                                                               | Do not claim support until a manifest, install path, and acceptance test exist.                    |
| Roboflow MCP             | Upstream dependency                | URL-only `.mcp.json`; Codex marketplace policy requests authorization on use       | Actual sign-in, account scope, tools, billing, and service behavior are unverified upstream state. |
| Official Roboflow skills | Compatible by delegation           | Prefer installed local skills, then exposed `roboflow://skills/...` resources      | Installing two plugins may duplicate MCP configuration on some hosts.                              |

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
