---
description: Ownership boundary between Sentinel delivery workflow, Roboflow MCP operations, and official Roboflow skills and documentation.
title: Roboflow Skills Integration
---

# Roboflow Skills Integration

Sentinel and official [`roboflow/computer-vision-skills`](https://github.com/roboflow/computer-vision-skills) solve different parts of the job. Sentinel should not become a drifting copy of Roboflow's product reference.

## Ownership boundary

| Question                                                                            | Owner                                      |
| ----------------------------------------------------------------------------------- | ------------------------------------------ |
| What business outcome and visual output are needed?                                 | Sentinel                                   |
| What evidence would be enough and which error matters?                              | Sentinel + user                            |
| Is training justified by the baseline gap?                                          | Sentinel + user                            |
| Which exact model ID, MCP tool, Workflow block, plan, price, or UI path is current? | Official Roboflow skills/docs/live service |
| Did the result pass the committed gate?                                             | Sentinel + user                            |
| Is production use lawful, secure, reliable, and accepted?                           | User's domain/governance owners            |

Roboflow MCP is the upstream live-operation surface. It is operated by Roboflow, requires authentication, can change independently of this repository, and can send data outside the local machine. Sentinel's bundled MCP configuration does not make the plugin the authority on the service.

## Lookup order

For platform-specific guidance:

1. Read the installed official Roboflow plugin skill.
2. If the host exposes authenticated MCP resources, read the related `skill://roboflow/<name>/SKILL.md` resource.
3. Consult current official Roboflow documentation.
4. If none is available, stop before a paid/state-changing action or mark the exact platform guidance unverified.

MCP-hosted skill resources may lag the source repository. Exact resource names, tool names, schemas, model identifiers, plan limits, and pricing must be verified in the active authenticated environment.

## Official skills

Sentinel delegates to these skills from the official `roboflow` plugin. Claude Code runs each one as `roboflow:<name>`; the MCP entrypoint is `skill://roboflow/<name>/SKILL.md`. `make eval-platform-routing` keeps this list and Sentinel's delegation map aligned with a committed roster of upstream skill names.

- `roboflow-training-and-evaluation`: training models, evaluating them, diagnosing why a model underperforms, and setting up a production feedback loop.
- `roboflow-model-journey`: choosing and trying a model without training first, then putting it on a project's live endpoint.
- `roboflow-inference`: image and video previews, deployment option comparison, Workflow publishing, device management, and Vision Events.
- `workflow-from-eval`: building or improving a Workflow by eval-driven search, for open-ended problems or when comparing alternatives. When it is installed, Sentinel hands it the candidate search only after locking the target and the gold set and measuring rung 0, keeps every paid step behind the action brief and gate, and scores the result again on its held-out gold set before reporting a pass.
- `roboflow-batch-processing`: running a Workflow over many images or videos as a batch job, monitoring jobs, and downloading results.
- `roboflow-data-management`: uploading images or videos, labeling, creating projects, tags, splits, versions, and dataset search.
- `roboflow-cloud-storage`: connecting S3 or GCS buckets to mirror images into a workspace.
- `roboflow-custom-weights-upload`: uploading locally trained model weights with the Python SDK and verifying the upload.
- `roboflow-api-reference`: REST and Inference API URL patterns, auth, parameters, error codes, and SDK quick-start.
- `roboflow-universe`: searching for and using public datasets and models on Roboflow Universe.
- `roboflow-plans-and-pricing`: plans, credit usage, and cost estimation from current official pricing.
- `roboflow-product-navigation`: where features live in the Roboflow web app.
- `draw-vision`: drawing annotations, labels, and predictions over images and videos with Supervision.

## Thin delegation pattern

Sentinel should preserve context and hand only the platform question upstream:

```text
The baseline misses the agreed recall gate. Training may now be justified.
I will verify the current model/training choices from the installed official
Roboflow skill, use the authenticated MCP surface only after your confirmation,
then return to the eval gate.
```

| Need                 | Sentinel retains                                           | Delegate upstream                                 |
| -------------------- | ---------------------------------------------------------- | ------------------------------------------------- |
| Training             | evidence gap, success gate, cost confirmation              | current model/training options and live operation |
| Inference/deployment | workload, latency/eval need, human approval                | current hosting/Workflow/tool semantics           |
| Data management      | purpose, minimum necessary data, eval split                | current upload/project/version mechanics          |
| Universe search      | relevance, license review, measurement on user samples     | current search/fork/navigation behavior           |
| Pricing              | reproducible workload assumptions and dated local estimate | current plans, billing, credits, and prices       |

Do not hard-code remembered platform recipes into Sentinel documentation. A stable delivery principle may live here; a current product instruction should remain upstream.

## Example

Request:

```text
Count hard hats in these authorized site images. If the baseline fails, tell me
which Roboflow option is appropriate.
```

Safe flow:

1. Sentinel confirms purpose/authority, routes to detection, and defines recall/count gates.
2. Sentinel measures a baseline on representative images.
3. If the gate fails, the agent reads the official current Roboflow training guidance.
4. The agent states the target, action, and expected cost, then waits for confirmation.
5. Authenticated MCP performs the approved live action.
6. Sentinel compares the observed result with the gate and verifies local artifacts.

Unsafe flow:

```text
Pick a model ID from memory, upload private media, start training, and decide
afterward whether the result was useful.
```

## When Sentinel alone is enough

Sentinel alone can help frame a public-safe task, define an eval, plan a local baseline, review existing project evidence, and structure economics assumptions. It is not enough for authenticated Roboflow operations or exact platform choices unless the live upstream sources are available.

Specialist routes other than the narrow B1 fixture remain guided, not broadly live-proven. See [Support & Evidence](support-and-scope.md).

## Combining plugins

Sentinel complements the official Roboflow plugin; it does not replace it. One install topology is supported for using both, on Claude Code.

### Supported topology on Claude Code

Install both plugins from their marketplaces:

```bash
claude plugin marketplace add Borda/vision-delivery
claude plugin install sentinel@sentinel
claude plugin marketplace add roboflow/computer-vision-skills
claude plugin install roboflow@roboflow
```

Each plugin declares one MCP server named `roboflow` at the same Roboflow MCP URL: Sentinel in its `.mcp.json`, and the official plugin in its own `.mcp.json` at the upstream commit the skill roster was taken from. The upstream marketplace name, plugin name, and server name are recorded in `evals/platform-routing/upstream-skills.json`, and `make eval-upstream` compares them with a current clone before a release. A plugin's server reaches the session under a name that includes the plugin, so the same Roboflow tool can arrive under more than one name:

| Where the server comes from                                     | Tool name the hooks see                       |
| --------------------------------------------------------------- | --------------------------------------------- |
| Sentinel installed as a plugin                                  | `mcp__plugin_sentinel_roboflow__<tool>`       |
| Official Roboflow plugin                                        | `mcp__plugin_roboflow_roboflow__<tool>`       |
| A server named `roboflow` in your own user or project MCP setup | `mcp__roboflow__<tool>`                       |
| A connector whose name contains Roboflow                        | for example `mcp__claude_ai_Roboflow__<tool>` |

**The gate covers every name above.** Sentinel's three Claude Code hook events (`PreToolUse`, `PostToolUse`, `PostToolUseFailure`) share one matcher that accepts any MCP server whose name contains `roboflow` in any letter case. The gate keys the action brief on the operation name without the server prefix, so a brief recorded for an operation opens the gate for that operation through either server, and one call through either server uses it up. A Roboflow server registered under a name without `roboflow` (for example `rf`) is not gated at all.

**Duplicate servers.** With both plugins enabled, the session can hold two servers for the same Roboflow service and offer every Roboflow tool twice. Neither copy bypasses the gate. Each server can run its own sign-in, so the two can end up connected to different accounts or workspaces. After installing both, inspect the host's resolved MCP server list, confirm which account each server uses before the first paid action, and read the server name in every permission prompt.

### What the repository proves, and what it does not

Deterministic checks in this repository prove:

- `evals/hooks/matcher_topology.mjs` reads every matcher in `hooks/claude-hooks.json`, compiles it as a JavaScript regular expression, and applies it to the tool names in the table above and to names that must not match (another server whose tool mentions roboflow, a server named without roboflow). The matcher and the hook's own rule agree on every name, and all three hook events use the same matcher.
- `evals/hooks/gate_smoke.mjs` runs the gate itself on bare, plugin-prefixed, connector, and mixed-case server names.

No live dual-install run is recorded, so these remain unverified:

- the server names Claude Code actually assigns to the two plugins' servers; the table follows the naming the hooks are written for;
- that the host applies a hook matcher exactly as the test compiles it;
- whether the host merges or deduplicates two servers with the same URL, which one the agent calls, and whether one sign-in covers both;
- how the official plugin's skills and Sentinel's skills route the same prompt in one live session.

Treat the combined install as supported by design and checked offline, not as live-verified.

## Agent rule

1. Start with Sentinel for business framing, route choice, eval definition, proof verification, and economics.
2. Use official Roboflow skills/resources/docs for current platform guidance.
3. Use authenticated MCP only for authorized live operations.
4. Return to Sentinel and the user to judge the evidence and next decision.

This split keeps the value proposition durable: Sentinel is the business-to-proof layer; Roboflow remains the platform authority.
