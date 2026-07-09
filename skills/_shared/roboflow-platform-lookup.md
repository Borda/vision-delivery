# Roboflow Platform Lookup

`vision-delivery` owns problem framing, eval gates, proof artifacts, ledger records, and economics. It does not own Roboflow platform reference material.

Use this lookup order whenever exact Roboflow behavior matters:

1. **Local Roboflow skill** from `roboflow/computer-vision-skills`, when installed.
2. **Roboflow MCP skill resource** such as `roboflow://skills/inference/...`, when the client exposes MCP resources and the user is authenticated.
3. **Minimal `vision-delivery` fallback**, marked unverified for volatile details before paid actions.

## Thin Adapter Recipes

| Platform need                                                                    | First-choice local skill           | MCP resource fallback                           | Live MCP tools usually involved                                                                                             | `vision-delivery` responsibility                                                                         |
| -------------------------------------------------------------------------------- | ---------------------------------- | ----------------------------------------------- | --------------------------------------------------------------------------------------------------------------------------- | -------------------------------------------------------------------------------------------------------- |
| Exact model IDs, training architecture, checkpoints, post-train evaluation       | `roboflow:training-and-evaluation` | `roboflow://skills/training-and-evaluation/...` | `trainings_create`, `trainings_get`, `models_get`, `models_list`, `versions_generate`                                       | Decide whether training is justified by the eval gap; ask before spend; record ledger rows.              |
| Inference, deployment option comparison, Workflows, batch processing, live video | `roboflow:inference`               | `roboflow://skills/inference/...`               | `models_infer`, `workflows_run`, `workflow_specs_validate`, `workflow_specs_run`, batch/data-staging tools                  | Choose based on eval, latency, proof needs, and economics; write local PoC artifacts.                    |
| Project creation, uploads, annotation organization, versions, exports, RoboQL    | `roboflow:data-management`         | `roboflow://skills/data-management/...`         | `projects_create`, `projects_list`, `projects_get`, `image_upload`, `images_search`, `versions_generate`, `versions_export` | Keep the dataset action tied to the eval plan; avoid guessing project type or destructive class changes. |
| REST/API hosts, auth methods, SDK snippets, request/response shapes              | `roboflow:api-reference`           | `roboflow://skills/api-reference/...`           | Prefer typed MCP tools where available; raw REST only when MCP is insufficient.                                             | Keep secrets out of chat; prefer MCP over raw HTTP; mark unverified protocol details.                    |
| Universe dataset/model search, fork/download decisions, public model use         | `roboflow:universe`                | `roboflow://skills/universe/...`                | `universe_search`, Universe app/resource flows when exposed                                                                 | Evaluate relevance to the user's data and license needs; measure on user samples before trusting.        |
| Plans, credits, plan limits, billing paths, current pricing references           | `roboflow:plans-and-pricing`       | `roboflow://skills/plans-and-pricing/...`       | Usage/billing tools if exposed; otherwise source pages and user-provided plan data.                                         | Run `scripts/cost_model.py`; separate one-time effort from run-rate; label assumptions and fetch dates.  |
| Roboflow UI paths and handoff links                                              | `roboflow:product-navigation`      | `roboflow://skills/product-navigation/...`      | Usually none; links and app navigation.                                                                                     | Give only the exact path needed for the next delivery step.                                              |

## Adapter Response Pattern

When routing to Roboflow platform knowledge, keep the response short and return to the delivery workflow:

```text
This is platform-specific. I will verify it from <local skill or MCP resource>, use MCP tools only for live operations, then return to the eval gate.
```

If neither local skills nor MCP resources are available:

```text
I can continue with the delivery workflow, but the exact Roboflow platform detail is unverified in this session. Install the official Roboflow skills or expose the Roboflow MCP skill resources before we spend credits or commit to a platform-specific model/workflow choice.
```

## Hard Rules

- Do not copy large Roboflow platform recipes into `vision-delivery`.
- Do not guess exact model IDs, MCP tool schemas, plan limits, UI paths, or current prices.
- Do not call paid training or deployment tools from fallback guidance alone.
- Prefer MCP tools over raw REST when both are available.
- Return to the `vision-delivery` eval gate after the platform lookup.

> **Tool-name caution (verified 2026-07-09):** the live Roboflow MCP surface exposes `trainings_create` / `trainings_get` / `trainings_list` / `trainings_cancel` / `trainings_stop`. Roboflow's own `training-and-evaluation` doc references `models_get_training_status` — that tool does NOT exist on the live surface; use `trainings_get` for status polling.
