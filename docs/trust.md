---
description: Security, paid-action guardrails, local ledger behavior, pricing provenance, and evidence boundaries for vision-delivery.
title: Trust And Safety
---

# Trust And Safety

`vision-delivery` touches API keys, paid Roboflow actions, local artifacts, and cost assumptions. The safety model is part of the product.

## API Keys

- Keep `ROBOFLOW_API_KEY` in the host environment or `.env`.
- Do not paste API keys into chat.
- `.mcp.json` passes the key to the Roboflow MCP server through the `x-api-key` header.
- Restart the host after changing the key because MCP servers read environment variables at startup.

## Paid Actions

Training and deployment-class actions are guarded by skill instructions that require explicit user confirmation before spend. This is prose-enforced workflow guidance, not a hard runtime block.

A correct session states:

- what action will happen,
- why the eval evidence justifies it,
- what the cost impact is expected to be,
- what local or hosted artifact will be created.

## Ledger Behavior

The PostToolUse hook writes selected train, eval, and deploy lifecycle records to:

```text
.vision-delivery/ledger.jsonl
```

The ledger supports later reporting and audit reconstruction. It is not a complete telemetry system and should not be described as full observability.

## Consent Gate Limitation

The consent gate is not machine-enforced. The skills tell the agent to show a cost estimate and wait for explicit confirmation before calling credit-spending tools, but there is no runtime pre-tool hook that blocks execution if consent was not recorded.

The mitigation is auditability: the hook writes ledger entries after selected train and deploy events, and reporting can surface sessions that reached deployment.

## Pricing Provenance

Deployment run-rate estimates come from `scripts/cost_model.py` and `scripts/PRICING_SNAPSHOT.json`. The script probes source reachability but uses committed snapshot values unless overridden.

Annotation and training costs must be:

- found in project evidence,
- supplied by the user,
- or clearly marked as assumptions or unknowns.

## Evidence Boundaries

- B1 has measured evidence.
- B2-B5 are fixture-defined and pending live runs.
- The plugin-vs-plain-agent claim is process discipline, not superior model quality.
- A plain agent with the same Roboflow MCP tools can reach comparable model metrics if it follows the same sequence.

## Reporting Vulnerabilities

Use the repository [security policy](https://github.com/Borda/vision-delivery/blob/main/SECURITY.md) for vulnerability reporting.
