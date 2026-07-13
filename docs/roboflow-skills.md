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
2. If the host exposes authenticated MCP resources, read the related `roboflow://skills/...` resource.
3. Consult current official Roboflow documentation.
4. If none is available, stop before a paid/state-changing action or mark the exact platform guidance unverified.

MCP-hosted skill resources may lag the source repository. Exact resource names, tool names, schemas, model identifiers, plan limits, and pricing must be verified in the active authenticated environment.

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

Specialist routes other than the narrow B1 fixture remain guided, not broadly live-proven. See [Support, Scope, and Evidence](support-and-scope.md).

## Combining plugins

Both plugins may define a Roboflow MCP server. Hosts that do not deduplicate configuration can show duplicate or conflicting server entries. Prefer selective official skills when the host supports them, or inspect the resolved host configuration before enabling both full bundles.

Never assume duplicate configuration is harmless. Confirm which server, credentials, and permissions the active host will use.

## Agent rule

1. Start with Sentinel for business framing, route choice, eval definition, proof verification, and economics.
2. Use official Roboflow skills/resources/docs for current platform guidance.
3. Use authenticated MCP only for authorized live operations.
4. Return to Sentinel and the user to judge the evidence and next decision.

This split keeps the value proposition durable: Sentinel is the business-to-proof layer; Roboflow remains the platform authority.
