---
description: Answers about Sentinel's value, evidence, supported hosts, Roboflow delegation, permissions, paid actions, and production limits.
title: FAQ
---

# FAQ

## What is Sentinel?

Sentinel is the plugin shipped by `vision-delivery`. It turns an operational image/video request into a CV task, success gate, cheapest baseline, inspectable proof plan, and economics decision. It is a workflow layer, not a model.

## Is it for people who do not know computer vision?

It is designed for them: a user can describe the outcome and consequences in plain language while Sentinel proposes the methodology. The user must still have authority to use the data, representative examples, and a human owner. No novice outcome study has yet proven an “almost no knowledge” claim.

## What evidence exists?

A pre-v0.2 live routing sample, a directional synthetic process A/B, and one small private detection result exist as historical evidence. The private data is not independently reproducible, and current routes are guided rather than proven end to end. See [Support, Scope, and Evidence](support-and-scope.md).

## Does it guarantee accuracy or production readiness?

No. Accuracy depends on the domain, data, model, threshold, and operating environment. A careful plain agent or human with the same tools can reach comparable metrics. Sentinel's value is making evidence-first process easier to follow.

## Does it replace Roboflow MCP or official Roboflow skills?

No. Sentinel uses MCP for live operations and owns task framing, evaluation, proof artifacts, and economics. Current MCP semantics, model IDs, Workflows, plans, pricing, and platform navigation belong to Roboflow's official skills and documentation. Read [Roboflow Skills Integration](roboflow-skills.md).

## Which hosts are supported?

Codex and Claude Code marketplace installations are documented from the public GitHub repository. Other hosts are outside the supported surface. See the [compatibility policy](compatibility.md).

## How do I authenticate to Roboflow?

Plugin installation does not require a credential environment variable. Codex metadata requests authorization on use; verify the actual host-managed sign-in, account, and scope in the live host. Credentials for a generated standalone hosted client, if current upstream guidance requires them, are a separate deployment concern and must not be pasted into chat or committed.

## Does it spend credits automatically?

Skills instruct the agent to explain and confirm credit-spending actions first, but this is not a hard runtime block. Use host approvals, account budgets, least-privilege account authorization or sessions, and non-production workspaces. If a separately generated standalone client requires a provider key, follow current provider guidance and scope it to the minimum permissions.

## What access does it request?

Routes can request filesystem reads/writes/edits, search, shell commands, and Roboflow MCP operations. Claude Code hooks can append a local activity ledger. Review every host permission prompt.

## Is the ledger proof that an action succeeded?

No. New hook records can classify host-reported outcomes and deduplicate event IDs, but coverage is best-effort. The ledger is not complete telemetry, an authorization receipt, or an independent Roboflow confirmation.

## Are generated scripts ready to run?

Not by default. Inspect dependencies and data flow, run syntax checks, execute a representative fixture, and compare outputs with the agreed gate. An instruction to write a script or a chat statement that it exists is not verification.

## Can it process people, plates, forms, or medical images?

Only after authority, purpose, minimization, retention, representative evaluation, human review, and relevant legal/security/domain checks are established. Do not use Sentinel as the sole decision-maker for consequential outcomes.

## What should the first prompt contain?

State the input, desired output, representative sample availability, and consequence of a wrong result:

```text
Count pallets crossing this line from these 60 frames. Report an hourly total.
A miss is worse than a duplicate. I am authorized to use this footage.
```

## Where do I get help?

Use the repository [support policy](https://github.com/Borda/vision-delivery/blob/main/.github/SUPPORT.md). Keep public reports free of credentials and private or sensitive data.
