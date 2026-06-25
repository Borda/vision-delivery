# Ledger Protocol — Shared Fragment

Every skill and agent writes to `.vision-delivery/ledger.jsonl` after any action that creates, trains, or deploys a Roboflow entity. This is the plugin-side provenance record (M2).

## Schema

Required fields on every record (stored as JSON Lines; present as YAML to user and in report files):

```json
{"ts": "2026-06-25T16:59:00Z", "session": "m1-acceptance", "skill": "detect-and-analyze", "action": "models_train", "entity_id": "workspace/project/version", "version": "0.1.0", "notes": "free-form; include key numbers (mAP, model name, etc.)"}
```

When displaying to user or writing to a report file, render as YAML:

```yaml
ts:        "2026-06-25T16:59:00Z"
session:   "m1-acceptance"
skill:     "detect-and-analyze"
action:    "models_train"
entity_id: "workspace/project/version"
version:   "0.1.0"
notes:     "free-form; include key numbers (mAP, model name, etc.)"
```

| Field | Format | Notes |
|-------|--------|-------|
| `ts` | ISO 8601 UTC (`YYYY-MM-DDTHH:MM:SSZ`) | Current wall-clock at write time |
| `session` | Short slug | Descriptive name for the work session; `YYYY-MM-DD-<topic>` convention |
| `skill` | Skill or agent name | e.g. `detect-and-analyze`, `deployment-consultant` |
| `action` | Action name (see below) | Lowercase snake_case |
| `entity_id` | Roboflow path | `workspace/project` or `workspace/project/version` |
| `version` | Plugin version | `0.1.0` until major release |
| `notes` | String | Key metrics, model name, decision rationale — whatever future-self needs |

Skills may add **skill-specific optional fields** (e.g. `streams`, `decision` for deployment-consultant). Required fields must always be present.

## Canonical action names

| Action | When to write |
|--------|--------------|
| `eval_definition` | `eval_definition.md` written and agreed |
| `baseline_measured` | First inference run on test images; note mAP in `notes` |
| `models_train` | `models_train` MCP call submitted; note model + checkpoint in `notes` |
| `project_deployment_launch` | Deployment confirmed and launched |
| `crossover_delivered` | Deployment-consultant crossover computed and shown to user |
| `decision_report_emitted` | `decision-report-*.md` file written |

## Write instructions

```bash
# Ensure directory exists
mkdir -p .vision-delivery

# Append one JSON line — never overwrite, always append
echo '{"ts":"...","session":"...","skill":"...","action":"...","entity_id":"...","version":"0.1.0","notes":"..."}' >> .vision-delivery/ledger.jsonl
```

- **Never omit the write.** If the action completed, write the record — even if later steps fail.
- **Never overwrite.** Always append (`>>`). The ledger is append-only.
- **Never log field values** that could leak API keys or personal data. `entity_id` is a workspace/project path, not a key.

## Report

`python3 scripts/ledger_report.py` reads `.vision-delivery/ledger.jsonl` and prints sessions-reaching-deploy metric + per-action breakdown.
