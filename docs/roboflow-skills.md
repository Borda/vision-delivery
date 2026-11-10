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
- `workflow-from-eval`: building or improving a Workflow by eval-driven search, for open-ended problems or when comparing alternatives.
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

Both plugins may define a Roboflow MCP server. Hosts that do not deduplicate configuration can show duplicate or conflicting server entries. Prefer selective official skills when the host supports them, or inspect the resolved host configuration before enabling both full bundles.

Never assume duplicate configuration is harmless. Confirm which server, credentials, and permissions the active host will use.

## Agent rule

1. Start with Sentinel for business framing, route choice, eval definition, proof verification, and economics.
2. Use official Roboflow skills/resources/docs for current platform guidance.
3. Use authenticated MCP only for authorized live operations.
4. Return to Sentinel and the user to judge the evidence and next decision.

This split keeps the value proposition durable: Sentinel is the business-to-proof layer; Roboflow remains the platform authority.
