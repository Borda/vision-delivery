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
```

The script uses the committed `scripts/PRICING_SNAPSHOT.json`. It probes source URL reachability but does not scrape live pricing pages into the result.

## Output Rules

Every material number should be one of:

- sourced and dated,
- derived from the cost model,
- supplied by the user,
- marked as unknown.

The result should say which assumption changes the recommendation. If labeling is the bottleneck, say that. If self-hosting wins, say that. If managed wins only until a stream-count crossover, state the crossover.

## Decision Report

After the crossover, the recipe can emit a stakeholder decision report. The report should include:

- recommendation — or an explicit abstention (`insufficient-data`) when no real managed quote was provided; the model never converts the public Core plan floor into a verdict,
- do-nothing baseline,
- managed option,
- DIY option,
- assumptions register,
- source list,
- risk analysis,
- next steps.
