---
description: How vision-delivery estimates annotation, training, deployment, and managed-vs-DIY computer-vision economics without hiding assumptions.
title: CV Economics
---

# CV Economics

`estimate-economics` answers the business question behind the proof:

```text
Is this computer-vision workflow worth labeling, training, deploying, or self-hosting?
```

It is deliberately not a sales flow. It can recommend managed deployment, DIY self-hosting, more measurement, or no further spend.

## When To Invoke

Use a host-independent prompt:

```text
Estimate the annotation, training, and deployment economics for this CV project.
Separate measured inputs from assumptions and show the managed-vs-DIY crossover.
```

This avoids relying on host-specific slash-command namespaces. The installed `estimate-economics` skill should route the request.

Where the host exposes skill commands directly, `/sentinel:estimate-economics` (Claude Code) or `$estimate-economics` (Codex) invoke the same skill without prompt routing.

Use it when:

- the eval has passed,
- the build scope is clear,
- the user wants annotation or training cost,
- the user wants managed-vs-DIY deployment economics,
- the user explicitly accepts a rough estimate before proof is complete.

## What It Reads

The economics recipe should inspect:

- sample count,
- labeled/unlabeled split,
- class count,
- annotation format,
- model architecture and size,
- training history,
- stream or request count,
- input resolution,
- uptime requirement,
- existing GPU hardware,
- region preference.

## What It Prices

| Cost area           | Source of truth                                           |
| ------------------- | --------------------------------------------------------- |
| Annotation and QA   | project evidence or user-provided assumption              |
| Training iterations | project evidence, previous run history, or explicit input |
| Deployment run-rate | `scripts/cost_model.py` and pricing snapshot              |
| Managed option      | cost model output or explicit override                    |
| DIY option          | GPU, setup, ops, drift, retraining, scaling cliff         |

## Deployment Run-Rate Command

```bash
python scripts/cost_model.py --streams 5 --fps 10 --model-size medium --uptime 24x7 --region us-east-1

# Roboflow credit use known (from the user or current Roboflow guidance):
python scripts/cost_model.py --streams 5 --fps 10 --model-size medium --uptime 24x7 --region us-east-1 \
    --managed-credits-mo 120 --credits-source "Roboflow usage page, workspace X" --credits-as-of 2026-10-01

# A batch of images per day instead of always-on streams:
python scripts/cost_model.py --images-per-day 20000 --model-size medium --region us-east-1

# Value at stake, from your own numbers (cost of one wrong decision, both error rates, their sources):
python scripts/cost_model.py --images-per-day 20000 --model-size medium --region us-east-1 \
    --error-cost-usd 40 --error-cost-source "returns ledger, Q3" --error-cost-as-of 2026-10-01 \
    --current-error-rate 0.08 --model-error-rate 0.03 --model-error-rate-upper 0.05 \
    --error-rates-source "current: QA audit log, Q3; model: scorer evidence file, 400 labeled images"
```

`--images-per-day` prices a batch workload: GPU time is billed in whole hours per day from the same screening capacity table, and `--fps` and `--uptime` do not apply. Exactly one of `--streams` and `--images-per-day` is given.

The value options are optional and never change the cost recommendation. The model multiplies decisions per month by the gap between the two error rates and by the cost of one wrong decision, and prints the result against each cost option. `--current-error-rate` is how often the process in place today is wrong, from your own records; `--model-error-rate` is the model's measured error rate (1 minus a success rate such as accuracy), and `--model-error-rate-upper` is the upper end of its 95% interval. The error cost and both rates are yours and carry your source and date; the model invents none of them. In batch mode it counts one decision per image unless you pass `--decisions-per-day`, and the output says which it used. In stream mode, `--decisions-per-day` is required. Without these options the output says "Value at stake: not computed".

Roboflow bills managed usage in credits. With `--managed-credits-mo`, the model prices that usage against the public plan anchors in the snapshot (Free, Core floor and ceiling, on-demand extra credits) and compares it with DIY. The result is tagged `basis: public-credit-plan`. It is an upper bound that excludes Enterprise scope (SLA, priority GPU, managed GPU cluster). Above 500 credits/month the model abstains, because pricing there is Enterprise-only. A dated `--managed-usd-mo` quote always takes precedence.

The script uses the committed `scripts/PRICING_SNAPSHOT.json`. It opens no network connection by default. With `--check-sources` it fetches each source URL once and reports whether it still answers; it never scrapes live pricing pages into the result.

## Output Rules

Every material number should be one of:

- sourced and dated,
- derived from the cost model,
- supplied by the user,
- marked as unknown.

The result should say which assumption changes the recommendation. If labeling is the bottleneck, say that. If self-hosting wins, say that. If managed wins only until a stream-count crossover, state the crossover.

## Decision Report

After the crossover, the recipe can emit a stakeholder decision report. The report should include:

- recommendation — or an explicit abstention (`insufficient-data`) when neither a dated managed quote nor sourced monthly credit use was provided; the model never turns the public Core plan floor alone into a verdict,
- do-nothing baseline,
- managed option,
- DIY option,
- assumptions register,
- source list,
- risk analysis,
- next steps.
