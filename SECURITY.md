# Security

## API Key Handling

The Roboflow API key is passed exclusively via the `ROBOFLOW_API_KEY` environment variable.

- **Never paste the key in chat.** Claude Code reads it from the environment; pasting it leaks it into session logs.
- **Never commit it.** Add `.env` to `.gitignore` before any other file. The key must not appear in any tracked file.
- **Never logged.** The hook script (`hooks/cta.js`) reads no environment variables. The MCP server receives the key via the `x-api-key` request header declared in `.mcp.json` — that substitution happens at runtime inside Claude Code and the raw value is never written anywhere by this plugin.
- **Rotation.** Update `ROBOFLOW_API_KEY` in your shell profile and `source ~/.zshrc` (or equivalent). Old keys are invalidated immediately by Roboflow; no other plugin state needs updating.

## Hook Scope

One hook is registered: `PostToolUse` → `hooks/cta.js`.

**What it reads:** stdin JSON supplied by the Claude Code runtime — `tool_name` and `tool_input` fields only. No environment variables, no arbitrary file reads.

**What it writes:** one JSON line appended to `.vision-delivery/ledger.jsonl` for deploy, train, and eval events. Directory is created if absent.

**What it never does:**

- No network calls of any kind.
- No access to `ROBOFLOW_API_KEY` or any credential env var.
- No subprocess spawning.
- No reads from outside the project directory.

The script is fail-safe: all error paths call `process.exit(0)` so a hook crash never blocks Claude Code.

## Ledger — Local Only, No Telemetry

`.vision-delivery/ledger.jsonl` is a local append-only file. It is never sent to Roboflow or any remote endpoint.

**Fields written per record:**

| Field       | Example                | Notes                                   |
| ----------- | ---------------------- | --------------------------------------- |
| `ts`        | `2026-06-25T17:00:00Z` | Wall-clock at write time                |
| `session`   | `m1-acceptance`        | Short slug identifying the work session |
| `skill`     | `detect-and-analyze`   | Skill or agent that triggered the write |
| `action`    | `models_train`         | Canonical action name                   |
| `entity_id` | `workspace/project/v1` | Roboflow path — not a key or credential |
| `version`   | `0.1.0`                | Plugin version                          |
| `notes`     | `mAP 0.72, YOLOv8n`    | Free-form; metrics and rationale only   |

No API keys, no credentials, no personally identifiable information are ever written.

You can inspect, truncate, or delete the ledger at any time with no effect on plugin operation. To exclude it from version control, add `.vision-delivery/` to `.gitignore`.

## MCP Server Scope

The Roboflow MCP server at `https://mcp.roboflow.com/mcp` is operated by Roboflow, not by this plugin.

- This plugin does not control what the MCP server can access. Its scope equals whatever your Roboflow API key permits.
- Credit-spending calls (train, deploy, autolabel) are gated by explicit user confirmation inside each skill before any MCP tool is invoked. See the individual `SKILL.md` files for details.
- The plugin declares the MCP server in `.mcp.json`; all HTTP communication is handled by Claude Code.

## Permissions Model

- The plugin uses only MCP tools listed in `.mcp.json` and the single Node.js hook script.
- No shell commands are executed beyond `node hooks/cta.js`.
- The hook has append-only access to `.vision-delivery/ledger.jsonl` and read-only access to stdin.
- No filesystem access outside the project directory.
- No network access from the hook.

## Known Limitations

**Consent gate is prose-enforced, not machine-enforced.** Skills instruct the LLM to show a credit estimate and wait for explicit user confirmation before calling `models_train` or `project_deployment_launch`. This is an LLM instruction, not a hard runtime block. An LLM reasoning error or prompt injection via a malicious MCP response could bypass it. There is no pre-tool hook that prevents execution if consent was not recorded. Mitigation: the `cta.js` hook writes a ledger entry after every deploy/train event, creating an audit trail of what ran; and `scripts/ledger_report.py` surfaces sessions that reached deploy.

## Vulnerability Reporting

**Do not open public GitHub issues for security findings.**

Report vulnerabilities to Roboflow directly:

- **Email:** security@roboflow.com
- **GitHub:** use [Security Advisories](https://github.com/roboflow/vision-delivery/security/advisories) (private disclosure)

We aim to acknowledge all reports within **5 business days**.
