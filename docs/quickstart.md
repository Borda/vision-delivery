---
description: Install vision-delivery in Codex or Claude Code, configure the Roboflow API key, and run the first eval-first computer-vision task.
title: Quick Start
---

# Quick Start

Install the `sentinel` plugin from the `vision-delivery` repository, expose your Roboflow API key to the host process, restart the host, then start with a concrete operational CV task.

## Before You Start

You need:

- Codex or Claude Code.
- A Roboflow account and API key from [app.roboflow.com/settings/api](https://app.roboflow.com/settings/api).
- A real CV task: camera, image/video source, target object or field, and the output you need.

!!! warning "Key handling"

    Keep `ROBOFLOW_API_KEY` in the shell environment or `.env`. Do not paste API keys into chat.

## Install In Codex

```bash
codex plugin marketplace add https://github.com/Borda/vision-delivery
codex plugin add sentinel@sentinel
export ROBOFLOW_API_KEY=your_key_here
```

Restart Codex after setting the key so the Roboflow MCP server starts with the right environment.

## Install In Claude Code

```bash
claude plugin install https://github.com/Borda/vision-delivery
echo "ROBOFLOW_API_KEY=your_key_here" >> .env
echo ".env" >> .gitignore
```

Restart Claude Code after writing `.env`.

## First Prompt

Start with the operational job, not the model name:

```text
I have an overhead camera above a parking lot. I need to count vehicles in view.
```

Better prompts include:

- input source: images, video, RTSP, camera, folder, dataset
- target: object, defect, text field, person, pose, area
- output: count, pass/fail, CSV, alert, endpoint, local script
- success check: what must be caught, how many misses are acceptable, which false alarms matter, and how fast it needs to run

## What The Plugin Should Do First

The first useful response should not be a model shopping list. It should:

1. classify the CV task,
2. clarify ambiguity if needed,
3. define or ask for the success check,
4. measure a baseline before training,
5. confirm before any paid training or deployment action.

## Good Starter Prompts

```text
Count pallets on a conveyor from these 60 sample frames.
```

```text
Detect cracks in product photos and report the count per image.
```

```text
Read serial numbers from circuit board images and write a local inference script.
```

```text
Track shoppers through aisle zones and estimate dwell time from RTSP footage.
```

## Next Steps

- Read [Use Cases](use-cases.md) to choose the right CV route.
- Read [Workflow](workflow.md) to understand the eval-first sequence.
- Read [CV Economics](economics.md) when the proof is good enough to price.
- Read [Trust And Safety](trust.md) for key handling, prose-enforced paid-action gates, and ledger behavior.
