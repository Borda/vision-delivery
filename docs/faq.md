---
description: Frequently asked questions about vision-delivery, eval-first CV delivery, Codex and Claude Code installation, Roboflow MCP usage, prose-enforced paid-action gates, and benchmark evidence.
title: FAQ
---

# FAQ

## What Is vision-delivery?

`vision-delivery` is a Codex and Claude Code plugin for eval-first computer-vision delivery. It turns vague image, video, or camera requests into scoped Roboflow proofs of concept with eval gates, local artifacts, paid-action guardrails, and CV economics decisions.

## Is This A Model?

No. It is a plugin and workflow layer around Roboflow MCP tools and local scripts. Its value is process discipline: classify the task, define the eval, measure a baseline, improve in cost order, and record provenance.

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
