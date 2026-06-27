---
description: Critical comparison between vision-delivery, Roboflow MCP, and Roboflow computer-vision-skills, including when to use local skills, MCP skill resources, and why platform recipes should not be copied.
title: Roboflow Skills Integration
---

# Roboflow Skills Integration

`vision-delivery` overlaps with [`roboflow/computer-vision-skills`](https://github.com/roboflow/computer-vision-skills), but it should not try to become a copy of that project. It also bundles the Roboflow MCP server config, and Roboflow's own skill files say related skill content may be exposed through `roboflow://skills/...` MCP resources as a fallback for clients without the plugin.

The clean split is:

- **Roboflow's source owns product truth:** MCP tool usage, platform navigation, model families, model IDs, Workflows, inference modes, training options, Universe, account plans, and pricing references. The freshest form is the local `roboflow/computer-vision-skills` plugin when installed; the MCP-hosted `roboflow://skills/...` resources are a useful fallback when available.
- **`vision-delivery` owns delivery discipline:** task framing, eval gates, baseline-first proof, local artifacts, consent prompts before spend, ledger records, and project economics.

That boundary matters because product guidance ages quickly. If this repository ports Roboflow's API and platform recipes, it becomes a stale duplicate of the source users should trust.

## What Roboflow MCP Ships

Direct unauthenticated probing of `https://mcp.roboflow.com/mcp` returns an OAuth-protected-resource challenge, so this repository cannot publicly enumerate a live resource list without a Roboflow-authenticated session. The protected-resource metadata confirms the MCP server is scoped for live Roboflow operations across workspaces, projects, folders, images, annotations, versions, training jobs, model inference/deployment/management/evaluation, Workflows, devices, vision events, data staging, batch processing, credentials, and integrations.

Roboflow's official plugin README describes the MCP server as the live tool layer for projects, images, annotations, versions, models, Workflows, Universe, and feedback. The official skill files add an important detail for agents: the canonical skills are local plugin files when installed, while the same content served as `roboflow://skills/<name>/...` MCP resources is a fallback for clients without the plugin and may lag the repository.

So the practical lookup order is:

1. **Local Roboflow plugin skill** such as `roboflow:inference`, `roboflow:training-and-evaluation`, or `roboflow:data-management`, when installed.
2. **Roboflow MCP skill resource** such as `roboflow://skills/inference/...`, when the client exposes MCP resources and the user is authenticated.
3. **Minimal stable fallback** in `vision-delivery`, limited to delivery workflow and clearly marked assumptions.

## Thin Adapter Recipes

Instead of porting Roboflow skills, `vision-delivery` should carry thin adapters that know where to look and when to return to the eval gate.

| Platform-specific need                              | First local skill                  | MCP skill-resource fallback                     | Live MCP tools usually involved                                                 | `vision-delivery` keeps owning                                      |
| --------------------------------------------------- | ---------------------------------- | ----------------------------------------------- | ------------------------------------------------------------------------------- | ------------------------------------------------------------------- |
| Model IDs, architectures, checkpoints, model eval   | `roboflow:training-and-evaluation` | `roboflow://skills/training-and-evaluation/...` | `models_train`, `models_get_training_status`, `models_get`, `versions_generate` | whether training is justified by the eval gap and user confirmation |
| Inference, deployment options, Workflows, batch     | `roboflow:inference`               | `roboflow://skills/inference/...`               | `models_infer`, `workflows_run`, `workflow_specs_validate`, batch/data-staging  | eval fit, latency tradeoff, local PoC artifacts, economics handoff  |
| Uploads, projects, annotation organization, exports | `roboflow:data-management`         | `roboflow://skills/data-management/...`         | `projects_create`, `image_upload`, `images_search`, `versions_generate/export`  | dataset actions tied to the eval plan                               |
| REST/API hosts, auth, SDK snippets, response shapes | `roboflow:api-reference`           | `roboflow://skills/api-reference/...`           | typed MCP tools first; raw REST only for gaps                                   | key safety and avoiding unverifiable protocol claims                |
| Universe datasets, public models, forks             | `roboflow:universe`                | `roboflow://skills/universe/...`                | `universe_search`, Universe app/resource flows                                  | relevance, license risk, and measurement on user samples            |
| Plans, credits, billing, current pricing references | `roboflow:plans-and-pricing`       | `roboflow://skills/plans-and-pricing/...`       | usage/billing tools if exposed                                                  | `scripts/cost_model.py`, assumptions, one-time vs run-rate split    |
| UI paths and handoff links                          | `roboflow:product-navigation`      | `roboflow://skills/product-navigation/...`      | usually none                                                                    | only the next useful handoff path                                   |

The response pattern should be explicit:

```text
This is platform-specific. I will verify it from <local skill or MCP resource>, use MCP tools only for live operations, then return to the eval gate.
```

If neither local skills nor MCP skill resources are available, continue only with delivery workflow and mark exact platform details unverified before paid actions.

## Example Adapter Flow

User request:

```text
Count hard hats in these construction-site images. If the baseline fails, tell me which Roboflow model to train.
```

Correct flow:

1. `vision-delivery` owns the task: route to detection, define the recall/count threshold, and measure a pretrained baseline on the user's images.
2. If training becomes justified, the agent verifies model IDs and training options from `roboflow:training-and-evaluation` or `roboflow://skills/training-and-evaluation/...`.
3. The agent uses live MCP tools such as `versions_generate`, `models_train`, and `models_get_training_status` only after explaining the spend and getting explicit confirmation.
4. `vision-delivery` resumes ownership after the platform action: compare results to the eval gate, write proof artifacts, append ledger rows, and decide whether economics should run.

Incorrect flow:

```text
Pick a model ID from memory, start training, then decide afterward whether it helped.
```

That skips both source-backed platform lookup and the eval-first delivery contract.

## Authenticated MCP Verification

This repository can verify the unauthenticated MCP metadata, but a live Roboflow-authenticated agent session should verify the exact exposed resources and tools before relying on MCP-hosted skill content.

In an authenticated session, check:

- the Roboflow MCP server is connected and authenticated
- live tools cover the operation you need, such as project, image, version, model, Workflow, Universe, data-staging, or batch actions
- MCP resources include the relevant `roboflow://skills/...` entries if local Roboflow skills are not installed
- local Roboflow plugin skills take precedence when both local skills and MCP skill resources exist

If those checks fail, install or consult [`roboflow/computer-vision-skills`](https://github.com/roboflow/computer-vision-skills) before committing to exact platform-specific choices.

## When vision-delivery Is Enough

Use only `vision-delivery` when the user has a concrete operational CV problem and needs the agent to drive a proof:

```text
Count pallets from these 80 warehouse images and tell me whether a pretrained model is enough.
```

This plugin should be enough when the work is mostly:

- clarify the target object, output, and failure consequence
- choose the CV route: detection, classification, OCR, tracking, segmentation, pose, or pipeline
- define the eval gate before model search
- measure a pretrained or Universe baseline
- improve in cost order
- write local proof artifacts
- decide whether annotation, training, deployment, or self-hosting is justified

In this mode, `vision-delivery` can partially replace Roboflow's delivery guidance because the user is not asking for deep platform navigation. The agent needs enough Roboflow MCP access to test the workflow, but the main value is the disciplined sequence.

## When To Use Roboflow's Skills

Use Roboflow's official local skills or MCP skill resources when the user's request is platform-specific:

```text
Which Roboflow model ID should I train for this dataset?
How do I run this as a Roboflow Workflow?
What is the difference between serverless, dedicated, self-hosted, and batch inference?
Where do I find this in the Roboflow UI?
Which pricing or plan limit applies?
```

Those questions belong close to Roboflow's source of truth. The local Roboflow plugin has the strongest claim because it is read fresh from the installed repository. MCP skill resources are the next-best fallback for clients that can read them. `vision-delivery` should not pretend to be the platform reference.

## Replacement Matrix

| Need                                                         | `vision-delivery` | Roboflow MCP tools | Roboflow local/MCP skills |
| ------------------------------------------------------------ | :---------------: | :----------------: | :-----------------------: |
| Turn a vague CV ask into a scoped task                       |        Yes        |      Partial       |          Partial          |
| Define eval metrics and pass/fail gates                      |        Yes        |      Partial       |          Partial          |
| Decide whether a pretrained baseline is enough               |        Yes        |        Yes         |            Yes            |
| Execute live project/image/model/workflow operations         |        No         |        Yes         |          Partial          |
| Pick exact Roboflow model IDs or product paths               |        No         |      Partial       |            Yes            |
| Explain Workflows, Universe, plans, and platform navigation  |        No         |      Partial       |            Yes            |
| Estimate annotation, training, deployment, and DIY crossover |        Yes        |      Partial       |          Partial          |
| Produce local proof artifacts and ledger records             |        Yes        |         No         |            No             |
| Keep current Roboflow platform reference material            |        No         |      Partial       |            Yes            |

The important point is not which package is "bigger." The important point is ownership. `vision-delivery` can replace the parts of Roboflow's skill set that are about delivery judgment, but it should defer on platform reference to local Roboflow skills or MCP skill resources.

## Should We Port Roboflow Skills?

No, not wholesale.

Porting Roboflow's `inference`, `training-and-evaluation`, `plans-and-pricing`, `product-navigation`, `api-reference`, `data-management`, or `universe` skills into this repository would create three problems:

1. **Drift:** model IDs, plans, tool names, and UI paths can change. A copied skill becomes stale faster than a delivery recipe.
2. **Confused authority:** users should not have to decide whether Borda's copy or Roboflow's source is correct.
3. **Diluted value:** this package becomes another product manual instead of the proof-and-economics layer it is good at.

Selective borrowing of stable routing patterns is fine. For example, `vision-delivery` can say "prefer Workflows when hosted replay and observability matter" if that is part of a delivery decision. It should read or defer when the user needs exact Workflow authoring instructions, product navigation, plan limits, model IDs, MCP tool schemas, or current pricing rules.

## Install Guidance

For most users, start with `vision-delivery` if the first problem is unclear, operational, or economics-driven. The bundled Roboflow MCP config is enough to connect the agent to live Roboflow operations once the user authenticates.

When the work shifts into Roboflow-specific implementation detail, prefer this order:

1. Use installed Roboflow skills from [`roboflow/computer-vision-skills`](https://github.com/roboflow/computer-vision-skills), if available.
2. Otherwise read Roboflow MCP skill resources such as `roboflow://skills/inference/...`, if the client exposes them.
3. Otherwise ask the user to install the official Roboflow plugin or mark the platform-specific answer as unverified.

Avoid blindly installing two full plugins if the host merges MCP server definitions by name. Both plugins may define a Roboflow MCP server, so a duplicate `roboflow` server entry can be confusing in clients that do not deduplicate plugin MCP configuration cleanly. If the host can install individual skills, selective Roboflow skills plus this plugin can be cleaner than two full plugin bundles.

## Agent Routing Rule

When `vision-delivery`, Roboflow MCP, and Roboflow skills are available:

1. Start with `vision-delivery` for problem framing, route choice, eval definition, proof artifacts, economics, and ledger records.
2. Use Roboflow MCP tools for live project, image, version, model, Workflow, Universe, and batch operations.
3. Use local Roboflow skills or MCP skill resources for platform-specific implementation guidance.
4. Return to `vision-delivery` to decide whether the result passes the eval gate and what economic decision follows.

This keeps Roboflow as the platform authority while letting `vision-delivery` own the customer-facing delivery workflow.
