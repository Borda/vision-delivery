# Roboflow Platform Delegation

Sentinel owns problem framing, independent acceptance, proof artifacts, delivery decisions, and economics. It does not own Roboflow's current APIs, model catalog, tool schemas, product navigation, plans, or deployment recipes.

Use this order whenever exact Roboflow behavior matters:

1. an installed official `roboflow/computer-vision-skills` skill;
2. the matching `skill://roboflow/<name>/SKILL.md` MCP resource, when the host exposes it;
3. a local provider-neutral scaffold that stops before any volatile platform action.

## Platform action handshake

For every platform-specific read or write:

1. Name the delivery intent and evidence needed on return.
2. Select the first available upstream source above.
3. Read that official skill/resource for the current schema, confirmation requirements, and operation sequence.
4. Delegate read-only discovery to that source and the live MCP surface. For uploads, dataset mutation, training, deployment, deletion, or any paid/state-changing action, Sentinel first records a sourced action brief, then follows the host execution gate below.
5. Return only the relevant entity/version identity, outcome status, measured evidence, and upstream source to the active Sentinel workflow.

If no upstream source is available, fallback is scaffold-only. It must not authorize uploads, paid actions, training, deployment, destructive changes, or guessed configuration.

## Host execution gate

The approval boundary is enforced by the host, never by conversation. Behavior differs per host because only one host exposes a verified pre-action hook.

**Claude Code: host-gated path.** Sentinel ships a `PreToolUse` hook (`hooks/gate.js`) on every Roboflow MCP tool. The hook classifies each call from a policy generated from Roboflow's published tool catalog (`hooks/gate-policy.json`). A tool the catalog marks read-only passes. Every other tool, and any tool the policy does not list, is gated. For a gated call the hook:

- denies the call unless the project ledger holds a successful, structured `action_brief_emitted` row that names that exact operation, is under 24 hours old, and has not been used by a later call of that operation;
- otherwise returns `ask`, so the host shows its own permission prompt with the brief's scope, cost, data movement, and rollback; the user approves or rejects there;
- denies in `bypassPermissions` and `dontAsk` permission modes, where the host shows no prompt;
- never returns `allow`.

Record the brief with the ledger helper, then make the MCP call:

```bash
python3 "/absolute/plugin/root/scripts/ledger_append.py" \
    --ledger "/absolute/user/project/.vision-delivery/ledger.jsonl" \
    --session "SESSION" --skill "SKILL" --action action_brief_emitted \
    --operation "<exact MCP operation name, without the mcp__ server prefix>" \
    --event-id "manual:SESSION:brief:ORDINAL" --status success \
    --scope "<what is acted on, and where>" \
    --cost-amount "<upper estimate as a number>" --cost-unit "<credits or currency>" \
    --cost-source "<where the estimate comes from>" --cost-as-of "<YYYY-MM-DD>" \
    --data-movement "<what leaves the machine and its destination, or none>" \
    --rollback "<how to undo it, or irreversible>"
```

Rules for the brief:

- Name the exact operation. A category name or a different operation does not open the gate.
- One brief covers one execution. A call whose outcome the ledger could not classify still uses the brief up; only a recorded failure or cancellation leaves it open, and the next prompt then warns the user that the provider may already have started the work. Record a new brief for a retry.
- The cost amount is an upper estimate from a current source, with a `--cost-as-of` date no more than 90 days old. If no sourced estimate exists, do not record the brief.
- The helper rejects a brief for a read-only operation and a brief with a missing or malformed field. It warns when the operation is not in the gate policy: check the spelling before the call.
- Two single-image tools (`models_infer`, `autolabel_preview`) run under a call budget. Add `--call-budget <N>` (1 to 1000) and state the cost for the whole budget. The user sees the host prompt until one call has run; later calls inside the budget follow the user's normal host permission rules, except in `auto` mode, where each call is asked. Every attempt that reaches the gate takes one unit, and calls past the budget are denied.
- Everything else needs a brief for every execution, including billed media analysis (`media_analyze`, which also takes video), batch jobs, and Workflow or endpoint runs (`project_deployment_run`). Never split a batch or a video into single calls to fit a budget.

Conversational consent never replaces the host prompt.

The gate sees MCP tool calls only, from a server whose name contains `roboflow`. Do not use a Roboflow SDK, CLI, or REST call from a shell command or a generated script to perform an action the gate would hold; that path bypasses the gate and is forbidden for paid, data-moving, destructive, or state-changing actions.

**Codex: brief-only.** Current official OpenAI documentation does not establish a Codex plugin `PreToolUse` authorization hook, and the Codex hook is post-action only. On Codex, Sentinel does not invoke the action. It returns the sourced action brief for the user to execute through a host/provider approval control.

Any other host or a Claude Code session with the gate missing or untrusted follows the Codex rule.

## Delegation map

Skill names are the upstream `SKILL.md` names in the `roboflow` plugin. Claude Code namespaces plugin skills, so it runs `roboflow-inference` as `roboflow:roboflow-inference`. Supporting pages sit beside each entrypoint at `skill://roboflow/<name>/<page>.md`.

| Platform need                                                                                    | First official skill               | MCP resource fallback                                        | Sentinel retains                                                                                   |
| ------------------------------------------------------------------------------------------------ | ---------------------------------- | ------------------------------------------------------------ | -------------------------------------------------------------------------------------------------- |
| Training candidates, checkpoints, evaluation                                                     | `roboflow-training-and-evaluation` | `skill://roboflow/roboflow-training-and-evaluation/SKILL.md` | Whether training is justified by the independent eval gap.                                         |
| Choosing and trying a model without training first, then putting it on a project's live endpoint | `roboflow-model-journey`           | `skill://roboflow/roboflow-model-journey/SKILL.md`           | The baseline measurement on the agreed eval before any training or deployment.                     |
| Inference, Workflows, deployment options, live video                                             | `roboflow-inference`               | `skill://roboflow/roboflow-inference/SKILL.md`               | Evidence, latency/data constraints, artifact kind, and delivery decision.                          |
| Building or improving a Workflow by eval-driven search over candidate Workflows                  | `workflow-from-eval`               | `skill://roboflow/workflow-from-eval/SKILL.md`               | The committed acceptance gate; an upstream scorecard does not replace Sentinel's independent eval. |
| Running a Workflow over many images or videos as a batch job, monitoring it, downloading results | `roboflow-batch-processing`        | `skill://roboflow/roboflow-batch-processing/SKILL.md`        | Which data runs, spend confirmation, and how results feed the eval or delivery decision.           |
| Projects, uploads, annotation, versions, exports                                                 | `roboflow-data-management`         | `skill://roboflow/roboflow-data-management/SKILL.md`         | Dataset purpose, consent, eval linkage, and provenance.                                            |
| Connecting S3 or GCS buckets to mirror images into a workspace                                   | `roboflow-cloud-storage`           | `skill://roboflow/roboflow-cloud-storage/SKILL.md`           | Data authority, minimum necessary data, and what leaves the user's storage.                        |
| Uploading locally trained model weights to Roboflow                                              | `roboflow-custom-weights-upload`   | `skill://roboflow/roboflow-custom-weights-upload/SKILL.md`   | Whether the local model passed the gate, weight provenance, and secret handling.                   |
| Current API/auth/SDK shapes                                                                      | `roboflow-api-reference`           | `skill://roboflow/roboflow-api-reference/SKILL.md`           | Secret handling, provider boundary, and executable artifact checks.                                |
| Universe datasets and public models                                                              | `roboflow-universe`                | `skill://roboflow/roboflow-universe/SKILL.md`                | Relevance, license review, and measurement on user samples.                                        |
| Plans, credits, and pricing                                                                      | `roboflow-plans-and-pricing`       | `skill://roboflow/roboflow-plans-and-pricing/SKILL.md`       | Sourced economics, assumptions, and spend confirmation.                                            |
| Product navigation                                                                               | `roboflow-product-navigation`      | `skill://roboflow/roboflow-product-navigation/SKILL.md`      | Only the next delivery step and return to the eval gate.                                           |
| Drawing annotations, labels, and predictions over images and videos                              | `draw-vision`                      | `skill://roboflow/draw-vision/SKILL.md`                      | Which overlays the decision report needs; visuals illustrate, measured results decide.             |

## Eval-driven search hand-off

`workflow-from-eval` and Sentinel's router (`solve-cv-task`) answer the same open-ended business prompt. When that official skill is installed, Sentinel does not run a second search: it hands the candidate search to upstream and stays the spend gate, the independent acceptance check, and the economics around it. When the skill is not installed, the platform action handshake and the delegation map above apply unchanged.

1. **Before the search.** Sentinel locks the target and the independently labeled gold set, then measures rung 0 (no account; `baseline-ladder.md`). No upstream search starts before both; a rung 0 pass ends the work there. Both are on file before the hand-off: the target as `metric:`, `comparator:`, and `threshold:` lines in the eval notes or as a frozen acceptance file, and the rung 0 run as a `predictions_frozen` or `baseline_measured` ledger row. The hand-off itself is recorded as a successful `upstream_search_started` row, and `ledger_report.py --status` warns when that row comes before them. This order is a recorded procedure, not an enforced one: the gate checks briefs, not the order of work.
2. **The hand-off.** Pass upstream the locked metric, the threshold, and the fact that the gold set is held out. Never add gold images to upstream's suite or show them during its search. Upstream's own suite, answer key, and scorecard steer its search only and never replace Sentinel's acceptance. Labels drafted for upstream's suite ("The user reviews; you label") are never gold.
3. **During the search.** Every paid or state-changing step upstream proposes, including scoring runs, uploads, saved or deleted Workflows, and deployments, needs a sourced action brief and the host execution gate above first. Upstream's checkpoints and cost lines inform the brief; they do not replace it. When the search cost is material to the decision, route through `estimate-economics` before the first paid run.
4. **After the search.** Sentinel scores whatever upstream returns again on the held-out gold set, against the same frozen target, before reporting any pass. Running the returned Workflow on the gold set is itself a briefed, gated action when it is paid. Upstream's scorecard numbers are reported as diagnostic only. One search result is scored on the held-out set once. A further search after that score has been steered by the held-out labels: record it as a new `upstream_search_started` row, say so in the result, and use a fresh labeled set for the final score; the status reader warns about it. On Codex there is no host gate, so step 3 is advice and the user decides.

## Response pattern

```text
This step is platform-specific. I will verify it through <official skill or MCP resource>. If it changes state, moves data, or spends credits, I will record a sourced action brief first. On Claude Code the call then goes to your host permission prompt through the Sentinel gate; on Codex I stop and hand you the brief to execute.
```

If neither upstream source is available:

```text
The delivery plan can continue, but this exact Roboflow operation is unverified. I will stop at a scaffold until the official Roboflow skill or MCP resource is available.
```

## Hard rules

- Do not copy Roboflow platform recipes into Sentinel.
- Do not guess model IDs, tool names/schemas, hosts, plan limits, UI paths, or current prices.
- Do not perform a volatile platform action from remembered or local fallback guidance.
- Do not invoke uploads, dataset mutations, paid training, deployment, deletion, or another state-changing provider action from Sentinel outside the host-gated path, even after conversational approval. Produce an action brief first; without an active gate, stop at the external approval boundary.
- Prefer typed MCP operations over raw HTTP when current upstream guidance offers both.
- Return to the Sentinel acceptance/delivery workflow after the delegated operation.
