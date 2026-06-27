---
description: Frequently asked questions about vision-delivery, eval-first CV delivery, Codex and Claude Code installation, Roboflow MCP usage, prose-enforced paid-action gates, and benchmark evidence.
title: FAQ
---

# FAQ

## What Is vision-delivery?

`vision-delivery` is a Codex and Claude Code plugin for eval-first computer-vision delivery. It turns vague image, video, or camera requests into scoped Roboflow proofs of concept with eval gates, local artifacts, paid-action guardrails, and CV economics decisions.

## Is This A Model?

No. It is a plugin and workflow layer around Roboflow MCP tools and local scripts. Its value is process discipline: classify the task, define the eval, measure a baseline, improve in cost order, and record provenance.

## Does This Replace Roboflow MCP Or computer-vision-skills?

No for MCP, partially for skills. `vision-delivery` bundles Roboflow MCP configuration because it needs live Roboflow operations. It can replace generic "what should we build and how do we prove it?" guidance because it owns task framing, eval gates, local artifacts, ledger records, and economics. It should not replace Roboflow's product-reference guidance for model IDs, Workflows, platform navigation, pricing pages, or exact MCP tool behavior.

Read [Roboflow Skills Integration](roboflow-skills.md) for the recommended split.

## Should This Repository Port Roboflow's Skills?

No, not wholesale. Porting Roboflow's platform recipes would create stale duplicate guidance. Prefer this order for platform-specific questions: installed [`roboflow/computer-vision-skills`](https://github.com/roboflow/computer-vision-skills) skills, then MCP skill resources such as `roboflow://skills/inference/...` when the client exposes them, then ask the user to install Roboflow's official plugin or mark the answer unverified. Return to `vision-delivery` for eval-gated proof and economics decisions.

## Does It Guarantee Better Model Accuracy?

No. The docs intentionally do not claim a model-quality advantage. A plain agent with the same Roboflow MCP tools can reach comparable model metrics if it performs the same sequence. The plugin makes that careful sequence the default.

## Which Hosts Are Supported?

The plugin is structured for both Codex and Claude Code:

- Codex uses `.codex-plugin/plugin.json` and `skills/`.
- Claude Code uses `.claude-plugin/plugin.json` plus thin adapters in `agents/`.

## What Should My First Prompt Look Like?

Use an operational task:

```text
Count vehicles in these parking-lot camera frames and report the count per image.
```

Avoid starting with a model name unless you already know the model is the right abstraction.

## Does It Spend Roboflow Credits Automatically?

The skills instruct the agent to ask before training or deployment-class spend. Correct behavior is to state what will happen, why the evidence justifies it, and what the cost impact may be. This is not a hard runtime-enforced block; check the ledger afterward for selected train and deploy events.

## Where Does The API Key Go?

Set `ROBOFLOW_API_KEY` in the host environment or `.env`. Do not paste API keys into chat. Restart Codex or Claude Code after changing the key because MCP servers read environment variables at startup.

## What Files Does It Write?

Depending on the route, expected local files include:

- `eval_definition.md`,
- local inference scripts,
- `.vision-delivery/detections.jsonl`,
- `.vision-delivery/ledger.jsonl`.

## What Is Measured Today?

B1 has measured evidence. B2-B5 are fixture-defined and pending live measurements. Read [Benchmarks](benchmarks/index.md) for the exact status and caveats.

## What Is llms.txt?

`llms.txt` is an emerging Markdown convention for giving LLMs and coding agents a compact map of a site. It is not a formal ranking standard. This project publishes [`llms.txt`](llms.txt) and a longer [`llms-full.txt`](llms-full.txt) as agent-friendly discovery aids.
