# Ledger Protocol — Shared Fragment

Sentinel records provenance in the user's project at `.vision-delivery/ledger.jsonl`. Hook events and skill events have separate ownership so one real action produces one canonical event.

## Schema

Every JSON Lines record contains:

```json
{
  "ts": "2026-07-13T10:00:00Z",
  "session": "factory-counter",
  "skill": "detect-and-analyze",
  "action": "baseline_measured",
  "entity_id": "workspace/project/version",
  "version": "0.2.0",
  "event_id": "manual:factory-counter:baseline_measured:1",
  "status": "success",
  "source": "skill",
  "notes": "recall=0.84; acceptance_id=counter-v1"
}
```

| Field       | Contract                                                                 |
| ----------- | ------------------------------------------------------------------------ |
| `ts`        | ISO 8601 UTC                                                               |
| `session`   | Stable session slug                                                       |
| `skill`     | Owning skill or `hook`                                                    |
| `action`    | Canonical lowercase action                                                |
| `entity_id` | Provider entity path when known; empty for local-only actions             |
| `version`   | Installed plugin version                                                  |
| `event_id`  | Idempotency key; identical real actions must reuse the same value          |
| `status`    | `attempted`, `success`, `failed`, `timeout`, `cancelled`, or `unknown`     |
| `source`    | `hook`, `skill`, or `import`                                              |
| `notes`     | Non-secret evidence; include acceptance ID and measured values when useful |

Unknown is never success. `attempted` and `unknown` prove only that work was requested or could not be classified. Reports must count successful training or deployment only when the canonical event has `status: success`.

## Single-writer Ownership

- The trusted PostToolUse hook records every observed Roboflow MCP call as `action: roboflow_mcp_call`, preserving the runtime-provided operation name and a coarse category without maintaining a copied platform-tool registry. It derives status from the host result and owns those raw call rows.
- Skills must not manually append hook-covered MCP actions. They may record a distinct completed local artifact or measurement produced after interpreting a call, but must not duplicate the raw upstream operation.
- Skills own local actions that have no matching MCP call: `eval_definition`, `feasibility_checked`, `baseline_measured`, `artifact_verified`, `delivery_handoff_emitted`, `crossover_delivered`, and `decision_report_emitted`.
- If hooks are untrusted or unavailable, do not fabricate a successful MCP event. State that MCP provenance is incomplete, direct the user to the host's hook trust/diagnostic flow, and retain tool-result evidence in the session output.
- A local action is `success` only after its file, measurement, or report exists. Record a failed/timeout/cancelled result only when preserving that outcome helps diagnosis.

## Safe Manual Writes

Never assume the user launched the host from the plugin repository. Resolve the helper from the **absolute path of this loaded file**:

1. Locate the loaded `resources/ledger-protocol.md`.
2. Its plugin root is the parent of `resources`.
3. Resolve `<plugin-root>/scripts/ledger_append.py` to an absolute path.
4. Resolve the user's project root separately and pass an absolute `--ledger` path. The helper's installation directory is never the ledger destination.

When invoked by that plugin-relative absolute path, the helper's default ledger is also resolved from the user's current project directory, not from the installed plugin cache. Passing an absolute `--ledger` remains the preferred explicit contract for nested or non-repository working directories.

Example after resolving both absolute paths:

```bash
python3 "/absolute/plugin/root/scripts/ledger_append.py" \
  --ledger "/absolute/user/project/.vision-delivery/ledger.jsonl" \
  --session "SESSION" --skill "SKILL" --action "ACTION" \
  --entity-id "ENTITY" --event-id "manual:SESSION:ACTION:ORDINAL" \
  --status "success" --source "skill" --notes "NON_SECRET_EVIDENCE"
```

Use a monotonically increasing local ordinal, artifact digest, or another stable non-secret discriminator in manual `event_id` values. Reuse the event ID when retrying the same logical append. Never use `echo`, shell interpolation of free-form values, or a repository-relative `python scripts/...` command.

Additional rules:

- Append only; never overwrite or delete prior outcomes.
- Never log API keys, bearer tokens, image contents, personal data, or raw tool responses.
- Every new manual write must supply a non-empty event ID. The helper rejects a conflicting reuse and silently ignores an exact duplicate.
- Keep failed and later-successful retries as separate event IDs unless they are duplicate deliveries of the same host event.
- Present records as YAML only for people; the stored source of truth remains JSON Lines.
