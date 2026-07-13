---
name: deliver-cv-project
description: |
  Turn an independently evaluated CV model or pipeline into a verified delivery handoff without copying volatile platform recipes. TRIGGER when: user has a working model, Workflow, OCR pipeline, or tracker and asks to export it, run locally, integrate an app/camera/RTSP source, deploy, productionize, monitor drift, add active learning, or make a runnable package. SKIP when: user asks to build a detector/model from sample images, the capability is unsolved, or measured acceptance is absent (solve-cv-task or modality skill); the request is cost/crossover only (estimate-economics); it asks only for a current Roboflow API field, UI path, model ID, or platform how-to (official Roboflow resource); or it only post-processes existing masks/data.
allowed-tools: Bash, Read, Write, Edit, Glob, Grep, AskUserQuestion
---

<objective>

Deliver a previously evaluated CV capability as a replayable artifact and an explicit engineering handoff. The exit criterion is not “deployment requested.” It is a completed delivery contract whose artifact kind, acceptance evidence, commands, dependencies, data boundary, rollback, and remaining external checks are truthful and tested.

</objective>

<entry_gate>

Read existing code, model metadata, `.vision-delivery/eval-*.md`, ledger rows, generated artifacts, and sample outputs before asking questions.

Require:

1. a model/pipeline identity and output schema;
2. an `acceptance_id` frozen before the candidate result;
3. independent acceptance evidence for the selected version;
4. the intended consumer and runtime environment.

When the user says a hosted model works, verify its current entity/version and evaluation through the upstream platform resources. When the model is local, inspect its weights/config and rerun the recorded acceptance command. If acceptance evidence is absent or stale for the selected version, route back to the owning modality skill; do not turn an unmeasured model into production merely because it exists.

For a novice request such as “make this useful in my factory,” ask at most three plain questions:

- “What should happen when the model finds something?”
- “Where do the images come from: files, an application, or a live camera?”
- “Must data stay on this machine, or may it go to a hosted service?”

</entry_gate>

<methodology>

**Platform execution boundary.** Read `../../resources/roboflow-platform-lookup.md`. For every platform-specific export, Workflow, endpoint, device, deployment, telemetry, or active-learning action, delegate exact execution to the installed official Roboflow skill or current MCP skill resource. Sentinel owns delivery selection, acceptance, consent, artifact hardening, and the handoff record. If no upstream source is available, stop at a `scaffold`; do not guess an API, model ID, container tag, endpoint, or UI path.

## Step 1 — Select the delivery contract

Classify the requested outcome:

| Outcome | Artifact kind | Required proof |
| --- | --- | --- |
| Calls a hosted provider endpoint | `hosted-client` | current upstream client shape, approved data movement, live request smoke |
| Runs exported weights on the user's machine | `local-runtime` | current upstream export, dependency lock, offline inference smoke |
| Contract only; transport/model unavailable | `scaffold` | deterministic self-test plus explicit missing live check |
| Managed service/device configuration | provider-managed handoff plus client kind | economic/spend consent, upstream status evidence, consumer smoke |

Never call a hosted client local inference. Never call exported weights a local runtime until they load and infer with networking disabled.

## Step 2 — Freeze interfaces

Record before integration:

- input schema, units, color space, shape, dtype, and supported source types;
- output schema and null/empty behavior;
- latency/throughput and acceptance ID;
- error behavior, timeouts, retries, and backpressure ownership;
- privacy/data-movement boundary;
- consumer action and human-review boundary;
- model/version and rollback target.

For RTSP or camera work, keep capture, inference, and business action as separate interfaces. Delegate current platform/runtime setup upstream; Sentinel tests the boundary with a recorded clip before live cutover.

## Step 3 — Generate and verify the artifact

Follow `../../resources/artifact-contract.md`. Generate the modality artifact through the current upstream inference/export guidance, then harden it with environment-only secrets, explicit CLI paths, deterministic `--self-test`, structured output, requirements, and `RUN.md`.

Run:

1. dependency installation in a clean Python 3.10+ environment;
2. the shared artifact smoke helper from an unrelated working directory;
3. one representative consumer integration test;
4. a live hosted request after data consent, or an offline local-runtime inference with network disabled;
5. a negative test for missing credentials/input and an empty-result case.

A self-test without the applicable live/offline path leaves the artifact a `scaffold`.

Run `../../resources/scripts/validate_delivery_handoff.py` against the completed handoff and project root. Do not emit `artifact_verified` or `delivery_handoff_emitted` until both the artifact smoke helper and handoff validator pass.

## Step 4 — Operational handoff

Define the smallest safe operating loop:

- health signal and failure alert;
- latency/error/empty-output counters;
- sampled prediction review against fresh independent labels;
- drift trigger tied to the frozen acceptance metric;
- rollback command/owner;
- retraining or active-learning entry condition, delegated upstream when platform-specific.

Do not claim ongoing monitoring exists because a plan was written. Mark each capability `verified`, `external`, or `not-configured`.

## Step 5 — Emit the delivery handoff

Write `.vision-delivery/delivery-handoff-<session>.json`:

```json
{
  "schema_version": "1",
  "acceptance_id": "<id/revision>",
  "model_or_pipeline": "<verified identity/version>",
  "artifact_kind": "hosted-client|local-runtime|scaffold",
  "artifact_path": "<project-relative path>",
  "input_schema": {},
  "output_schema": {},
  "provider_dependency": "<name or none>",
  "data_boundary": "<local or approved destination>",
  "commands": {"self_test": "<command>", "live": "<command>"},
  "checks": {"self_test": "passed", "live_or_offline": "passed|not-run"},
  "rollback": {"target": "<version>", "owner": "<person/team>"},
  "monitoring": {"status": "verified|external|not-configured"},
  "remaining_external_checks": []
}
```

Use project-relative paths in the handoff for portability, but execute verification with resolved absolute paths. Never place secrets or signed URLs in the handoff.

</methodology>

<ledger>

Follow `../../resources/ledger-protocol.md`. After the artifact checks pass, manually record `artifact_verified`. After the handoff file exists, manually record `delivery_handoff_emitted`. Include `acceptance_id`, artifact kind, and non-secret artifact digest in notes. Do not manually duplicate hook-covered platform actions. Unknown is never success.

</ledger>

<stop_rules>

- No independent acceptance for the selected version → return to the modality skill.
- Missing current upstream platform truth → emit only a scaffold and the exact dependency needed.
- Hosted data movement not approved → offer local-runtime/scaffold; do not send data.
- Paid or destructive action lacks sourced impact and explicit current-turn consent → stop before the action.
- Live/offline smoke not run → do not call delivery complete.

</stop_rules>
