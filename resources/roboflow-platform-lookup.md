# Roboflow Platform Delegation

Sentinel owns problem framing, independent acceptance, proof artifacts, delivery decisions, and economics. It does not own Roboflow's current APIs, model catalog, tool schemas, product navigation, plans, or deployment recipes.

Use this order whenever exact Roboflow behavior matters:

1. an installed official `roboflow/computer-vision-skills` skill;
2. the matching `roboflow://skills/...` MCP resource, when the host exposes it;
3. a local provider-neutral scaffold that stops before any volatile platform action.

## Platform action handshake

For every platform-specific read or write:

1. Name the delivery intent and evidence needed on return.
2. Select the first available upstream source above.
3. Read that official skill/resource for the current schema, confirmation requirements, and operation sequence.
4. Delegate exact execution to that source and the live MCP surface. Sentinel retains the frozen acceptance gate plus data-movement and spend confirmation.
5. Return only the relevant entity/version identity, outcome status, measured evidence, and upstream source to the active Sentinel workflow.

If no upstream source is available, fallback is scaffold-only. It must not authorize uploads, paid actions, training, deployment, destructive changes, or guessed configuration.

## Delegation map

| Platform need                                        | First official skill               | MCP resource fallback                           | Sentinel retains                                                          |
| ---------------------------------------------------- | ---------------------------------- | ----------------------------------------------- | ------------------------------------------------------------------------- |
| Training candidates, checkpoints, evaluation         | `roboflow:training-and-evaluation` | `roboflow://skills/training-and-evaluation/...` | Whether training is justified by the independent eval gap.                |
| Inference, Workflows, deployment options, live video | `roboflow:inference`               | `roboflow://skills/inference/...`               | Evidence, latency/data constraints, artifact kind, and delivery decision. |
| Projects, uploads, annotation, versions, exports     | `roboflow:data-management`         | `roboflow://skills/data-management/...`         | Dataset purpose, consent, eval linkage, and provenance.                   |
| Current API/auth/SDK shapes                          | `roboflow:api-reference`           | `roboflow://skills/api-reference/...`           | Secret handling, provider boundary, and executable artifact checks.       |
| Universe datasets and public models                  | `roboflow:universe`                | `roboflow://skills/universe/...`                | Relevance, license review, and measurement on user samples.               |
| Plans, credits, and pricing                          | `roboflow:plans-and-pricing`       | `roboflow://skills/plans-and-pricing/...`       | Sourced economics, assumptions, and spend confirmation.                   |
| Product navigation                                   | `roboflow:product-navigation`      | `roboflow://skills/product-navigation/...`      | Only the next delivery step and return to the eval gate.                  |

## Response pattern

```text
This step is platform-specific. I will verify and execute it through <official skill or MCP resource>, then return the resulting evidence to the Sentinel delivery gate.
```

If neither upstream source is available:

```text
The delivery plan can continue, but this exact Roboflow operation is unverified. I will stop at a scaffold until the official Roboflow skill or MCP resource is available.
```

## Hard rules

- Do not copy Roboflow platform recipes into Sentinel.
- Do not guess model IDs, tool names/schemas, hosts, plan limits, UI paths, or current prices.
- Do not perform a volatile platform action from remembered or local fallback guidance.
- Prefer typed MCP operations over raw HTTP when current upstream guidance offers both.
- Return to the Sentinel acceptance/delivery workflow after the delegated operation.
