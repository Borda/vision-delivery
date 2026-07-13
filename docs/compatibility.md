# Compatibility

This matrix records what the repository currently demonstrates. It is not a promise about future host or upstream behavior.

| Surface                  | Status                              | Verified path                                                                                                 | Limitation                                                                            |
| ------------------------ | ----------------------------------- | ------------------------------------------------------------------------------------------------------------- | ------------------------------------------------------------------------------------- |
| Codex plugin             | Release candidate; locally verified | Clean-home local marketplace install with the v0.2 manifests                                                  | Public `main` install/retest and current-route live evidence remain pending.           |
| Claude Code plugin       | Release candidate; locally verified | Clean-home local marketplace install plus strict manifest/marketplace validation                              | Public `main` install/retest remains pending; `--plugin-dir` is development-only.      |
| Claude Code hooks        | Supported by repository smoke tests | Hook lifecycle configuration under `hooks/`                                                                   | Host hook coverage remains best-effort and is not complete telemetry.                 |
| Cursor                   | Unverified                          | None                                                                                                          | Do not claim support until a manifest, install path, and acceptance test exist.       |
| Roboflow MCP             | Upstream dependency                 | URL-only `.mcp.json`; Codex marketplace policy requests authorization on use                                  | Actual sign-in, account scope, tools, billing, and service behavior are unverified upstream state. |
| Official Roboflow skills | Compatible by delegation            | Prefer installed local skills, then exposed `roboflow://skills/...` resources                                 | Installing two plugins may duplicate MCP configuration on some hosts.                 |

## Runtime expectations

- Python 3.10 or newer for repository scripts and evals.
- Node.js for the Claude Code hook.
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
