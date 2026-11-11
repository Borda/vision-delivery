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
  "version": "0.5.0",
  "event_id": "manual:factory-counter:baseline_measured:1",
  "status": "success",
  "source": "skill",
  "acceptance_id": "counter-v1",
  "acceptance_sha256": "<lowercase sha256>",
  "notes": "recall=0.84; acceptance_id=counter-v1"
}
```

| Field                              | Contract                                                                                                                                            |
| ---------------------------------- | --------------------------------------------------------------------------------------------------------------------------------------------------- |
| `ts`                               | ISO 8601 UTC                                                                                                                                        |
| `session`                          | Stable session slug                                                                                                                                 |
| `skill`                            | Owning skill or `hook`                                                                                                                              |
| `action`                           | Canonical lowercase action                                                                                                                          |
| `entity_id`                        | Provider entity path when known; empty for local-only actions                                                                                       |
| `version`                          | Installed plugin version                                                                                                                            |
| `event_id`                         | Idempotency key; identical real actions must reuse the same value                                                                                   |
| `status`                           | `attempted`, `success`, `failed`, `timeout`, `cancelled`, or `unknown`                                                                              |
| `source`                           | `hook`, `skill`, or `import`                                                                                                                        |
| `acceptance_id`                    | Frozen acceptance revision for proof-chain local actions                                                                                            |
| `acceptance_sha256`                | Digest binding for proof-chain local actions                                                                                                        |
| `artifact_sha256`                  | Artifact-tree digest for artifact/delivery actions                                                                                                  |
| `report_sha256`                    | Decision-report file digest for `decision_report_emitted`                                                                                           |
| `pred_sha256`                      | Frozen prediction-file digest for `predictions_frozen`                                                                                              |
| `gold_sha256`                      | Gold label-file digest at the freeze, for `predictions_frozen`                                                                                      |
| `label_set`                        | Gold label file relative to the ledger folder, for `predictions_frozen` and `labels_recorded`                                                       |
| `label_digests`                    | Image name to the first 16 hex of SHA-256 over the image name, a NUL byte, and the JSON label value, for `predictions_frozen` and `labels_recorded` |
| `label_entry`                      | `interactive-terminal` or `record-option` on `labels_recorded`; on `predictions_frozen` also `mixed` or `unrecorded`                                |
| `labels_changed_after_freeze`      | Images whose label differs from an earlier freeze of the same image name, for `predictions_frozen`                                                  |
| `labels_changed_after_predictions` | The labeling helper wrote the label file after the prediction file was written, or the file changed since, for `predictions_frozen`                 |
| `predictor`                        | `isolated-subagent` or `same-session`, for `predictions_frozen`                                                                                     |
| `notes`                            | Non-secret evidence; include acceptance ID and measured values when useful                                                                          |

Unknown is never success. `attempted` and `unknown` prove only that work was requested or could not be classified. Reports must count successful training or deployment only when the canonical event has `status: success`.

## Single-writer Ownership

- The trusted PostToolUse hook records every observed Roboflow MCP call as `action: roboflow_mcp_call`, preserving the runtime-provided operation name. Its `category` is a reporting label read from the generated gate policy (`hooks/gate-policy.json`); a tool the policy does not list is recorded as `unlisted`. The hook derives status from the host result and owns those raw call rows.
- A successful `action_brief_emitted` row must name the exact provider operation in `operation` and carry a `brief` object with `scope`, `cost_amount`, `cost_unit`, `cost_source`, `cost_as_of`, `data_movement`, and `rollback`, plus `call_budget` for an operation the gate policy runs under a call budget. `ledger_append.py` rejects an incomplete brief, and the Claude Code gate ignores one. Never write a brief with a guessed cost: if no current sourced estimate exists, do not record the brief.
- Write `ts` in UTC as `YYYY-MM-DDTHH:MM:SSZ`. The Claude Code gate ignores a row whose time Node's `Date.parse` cannot read and reads a time without an offset as the machine's local time; `ledger_report.py --status` reads `ts` the same way.
- For an operation that runs under a call budget, the Claude Code gate appends `action: roboflow_mcp_call_reserved` (status `attempted`) before the call goes ahead. The row holds one unit of the brief's budget and names the brief in `brief_event_id`. It is not evidence that the call ran; only the `roboflow_mcp_call` row is. Skills never write or remove reservation rows.
- Skills must not manually append hook-covered MCP actions. They may record a distinct completed local artifact or measurement produced after interpreting a call, but must not duplicate the raw upstream operation.
- Skills own local actions that have no matching MCP call: `eval_definition`, `feasibility_checked`, `labels_recorded`, `predictions_frozen`, `baseline_measured`, `recheck_measured`, `upstream_search_started` (the router hands the candidate search to an upstream search skill; written only after the target is on file and rung 0 is recorded), `artifact_verified`, `delivery_handoff_emitted`, `crossover_delivered`, and `decision_report_emitted`.
- If hooks are untrusted or unavailable, do not fabricate a successful MCP event. State that MCP provenance is incomplete, direct the user to the host's hook trust/diagnostic flow, and retain tool-result evidence in the session output.
- A local action is `success` only after its file, measurement, or report exists. Record a failed/timeout/cancelled result only when preserving that outcome helps diagnosis.

## Prediction Freezes

A successful `predictions_frozen` row freezes a rung 0 prediction file before it is scored (`baseline-ladder.md` rung 0). Write it through `resources/scripts/freeze_predictions.py`, which checks both label files and then calls `scripts/ledger_append.py`; never assemble the row by hand.

- `ledger_append.py` requires `--pred`, `--gold`, and `--predictor` (`isolated-subagent`, or `same-session` when the host has no subagent tool) for a successful row. It computes `pred_sha256`, `gold_sha256`, `label_set` (the gold file's path relative to the ledger folder), and `label_digests` itself; caller-supplied digests are never accepted. The gold file must sit inside the project folder, the folder that holds the ledger's folder.
- Inside the ledger lock it also computes `label_entry` (from this label file's `labels_recorded` rows: one kind, `mixed`, or `unrecorded` when there are none), `labels_changed_after_freeze`, and `labels_changed_after_predictions` (the latest `labels_recorded` row for this label file has a `ts` later than the prediction file's modification time, or its `gold_sha256` differs from the file now). Either check set refuses the row unless `--acknowledge-label-change` is passed; the row then carries the values. A label file that an earlier freeze recorded with other content is always refused.
- Event ID: `manual:<session>:predictions_frozen:<first 12 hex of pred_sha256>-<first 12 hex of gold_sha256>`. The freeze helper derives it, so a retry on the same files reuses it and adds no row.
- Readers count only `status: success` rows with a `ts` in the `YYYY-MM-DDTHH:MM:SSZ` form, a relative `label_set` that stays inside the project folder, and `label_digests`. `score_baseline.py --frozen-ledger` refuses unless one row holds both current digests, recomputes `labels_changed_after_freeze` from the label file and the freezes before that row, and reports the result as not independent when it or `labels_changed_after_predictions` is set; `label_gold.py` refuses any write to a label file that a row names.
- The row needs no `--acceptance`, because explore mode has no acceptance file. In deliver mode the scorer's evidence binds the acceptance digest and both file digests, and the freeze row binds the same two file digests.
- Limits: a freeze shows that the prediction file and the label file were fixed before this scoring run, and the scorer's line says whether labels changed after an earlier freeze or after the prediction file was written. It does not show that the labels are independent of the predictions. The helpers, the predictor, and the scorer run under one account on the user's machine, so a predictor that opens the label file is not detected. A ledger row written by hand is not detected. An earlier scoring run without the freeze leaves no trace. Renaming image files defeats the per-image label check, and file times can be changed. An agent can call `label_gold.py --record`, so labels entered that way are marked, not blocked, and a pseudo-terminal defeats the helper's terminal check. The isolated-subagent step has not yet been recorded in a live session.

## Label Records

`resources/scripts/label_gold.py` appends one successful `labels_recorded` row through `scripts/ledger_append.py` after every write of a gold label file; never write one by hand.

- `ledger_append.py` requires `--gold` and `--label-entry` (`interactive-terminal` for answers typed at a terminal, `record-option` for labels recorded with `--record`). It computes `gold_sha256`, `label_set`, and `label_digests` from the file itself. The row carries counts in `notes` and never a label value.
- A label file written by hand has no `labels_recorded` row; a later freeze records its `label_entry` as `unrecorded`, and the scorer says the label file was not written by the labeling helper.

## Rechecks

`resources/scripts/recheck.py` scores a fresh labeled sample against the frozen acceptance after delivery and appends one successful `recheck_measured` row through `scripts/ledger_append.py`; never write one by hand.

- The helper anchors on the frozen acceptance file, not on what the baseline evidence says about itself. It refuses unless the baseline evidence is a passing scorer record for this acceptance whose label file is the acceptance's dataset, the task matches, and the fresh label file is not that dataset. When it can find the baseline label file (`--baseline-gold`, or a file with the dataset digest in the ledger's folder), it also refuses a fresh file with the same labels in other bytes or with any image name the baseline used. It then runs the scorer and writes a new evidence file with a `recheck` block.
- `ledger_append.py` requires `--acceptance` and `--evidence` for a successful row. It reads the evidence file itself, refuses one bound to another acceptance, and writes `evidence_sha256`, `evidence_measured_at`, `predictions_frozen` (`independent`, `not-independent`, or `not-frozen`), `drift` (`holds`, `drifted`, or `uncertain`), and `shifted` (`worse`, `better`, `no`, or `unknown`: where the fresh 95% interval lies relative to the baseline's single value; it is not a test of change). Readers use these fields and never the `notes`.
- Event ID: `manual:<session>:recheck_measured:` followed by the first 12 hex characters of the acceptance, baseline evidence, prediction, and label file digests, joined with `-`, so a rerun on the same files adds no row and a new acceptance adds its own.
- Save the recheck evidence where you like; the status reader never treats it as the project's last baseline result.
- Limits: when the baseline label file is not on disk, overlap with the baseline images is not checked, and the evidence and the printed line say so. Renamed image files defeat the overlap check. Without `--frozen-ledger` the fresh predictions were not frozen before scoring, and the line says so. A recheck is one sample; `uncertain` means label more images.

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
    --status "success" --source "skill" \
    --acceptance "/absolute/project/.vision-delivery/acceptance-REVISION.json" \
    --artifact-dir "/absolute/project/artifact-when-applicable" \
    --report "/absolute/project/decision-report-when-applicable.md" \
    --notes "NON_SECRET_EVIDENCE"
```

Use a monotonically increasing local ordinal, artifact digest, or another stable non-secret discriminator in manual `event_id` values. Reuse the event ID when retrying the same logical append. Never use `echo`, shell interpolation of free-form values, or a repository-relative `python scripts/...` command.

Additional rules:

- Append only; never overwrite or delete prior outcomes.
- Never log API keys, bearer tokens, image contents, personal data, or raw tool responses.
- Every new manual write must supply a non-empty event ID. The helper rejects a conflicting reuse and silently ignores an exact duplicate.
- Successful `baseline_measured`, `recheck_measured`, `artifact_verified`, `delivery_handoff_emitted`, `crossover_delivered`, and `decision_report_emitted` rows require `--acceptance`; the helper validates the frozen artifact and computes its ID/digest. Artifact and delivery rows additionally require `--artifact-dir`. A successful `decision_report_emitted` row requires `--report`; the helper computes `report_sha256`. Caller-supplied digest strings and free-form notes are never accepted as proof bindings.
- For a proof action, pass `--acceptance` (and `--artifact-dir` for artifact actions) on a failed, timeout, or cancelled row too. The helper then binds the row to its target and artifact. The delivery check counts a failed proof row that names no target against every target, until a later success row for that action.
- Keep failed and later-successful retries as separate event IDs unless they are duplicate deliveries of the same host event.
- Present records as YAML only for people; the stored source of truth remains JSON Lines.
