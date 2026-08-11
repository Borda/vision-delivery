---
name: deliver-cv-project
description: |
  Turn an independently evaluated CV model or pipeline into a verified delivery handoff without copying volatile platform recipes. TRIGGER when: user has a working model, Workflow, OCR pipeline, or tracker and asks to export it, run locally, integrate an app/camera/RTSP source, deploy, productionize, monitor drift, add active learning, or make a runnable package. SKIP when: user asks to build a detector/model from sample images, the capability is unsolved, or measured acceptance is absent (solve-cv-task or modality skill); the request is cost/crossover only (estimate-economics); it asks only for a current Roboflow API field, UI path, model ID, or platform how-to (official Roboflow resource); or it only post-processes existing masks/data.
allowed-tools: Bash, Read, Write, Edit, Glob, Grep, AskUserQuestion
---

<objective>

Deliver a previously evaluated CV capability as a replayable artifact and an explicit engineering handoff. The exit criterion is not “deployment requested.” It is a completed delivery contract whose artifact kind, acceptance evidence, commands, dependencies, data boundary, rollback, and remaining external checks are truthful and tested.

</objective>

\<entry_gate>

Read existing code, model metadata, `.vision-delivery/eval-*.md`, ledger rows, generated artifacts, and sample outputs before asking questions.

Require:

1. a model/pipeline identity and output schema;
2. a machine-readable acceptance artifact frozen before the candidate result, with its `acceptance_id`, project-relative path, and SHA-256 digest;
3. independent acceptance evidence for the selected version;
4. the intended consumer and runtime environment.

When the user says a hosted model works, verify its current entity/version and evaluation through the upstream platform resources. When the model is local, inspect its weights/config and rerun the recorded acceptance command. If acceptance evidence is absent or stale for the selected version, route back to the owning modality skill; do not turn an unmeasured model into production merely because it exists.

For a novice request such as “make this useful in my factory,” ask at most three plain questions:

- “What should happen when the model finds something?”
- “Where do the images come from: files, an application, or a live camera?”
- “Must data stay on this machine, or may it go to a hosted service?”

\</entry_gate>

<methodology>

**Platform execution boundary.** Read `../../resources/roboflow-platform-lookup.md`. Use installed official Roboflow skills or current MCP skill resources only for read-only discovery. For every platform-specific export, Workflow mutation, endpoint, device, deployment, telemetry mutation, active-learning action, paid action, or data movement, emit a sourced action brief and stop for execution through an external host/provider approval control. Sentinel never invokes those actions. Sentinel owns delivery selection, acceptance, artifact hardening, and the handoff record. If no upstream source is available, stop at a `scaffold`; do not guess an API, model ID, container tag, endpoint, or UI path.

## Step 1 — Select the delivery contract

Classify the requested outcome:

| Outcome                                     | Artifact kind                             | Required proof                                                            |
| ------------------------------------------- | ----------------------------------------- | ------------------------------------------------------------------------- |
| Calls a hosted provider endpoint            | `hosted-client`                           | current upstream client shape, approved data movement, live request smoke |
| Runs exported weights on the user's machine | `local-runtime`                           | current upstream export, dependency lock, offline inference smoke         |
| Contract only; transport/model unavailable  | `scaffold`                                | deterministic self-test plus explicit missing live check                  |
| Managed service/device configuration        | provider-managed handoff plus client kind | economic/spend consent, upstream status evidence, consumer smoke          |

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

For RTSP or camera work, keep capture, inference, and business action as separate interfaces. Use read-only upstream facts to prepare any platform/runtime setup action brief and stop before provider execution; Sentinel tests externally configured boundaries with a recorded clip before live cutover.

## Step 3 — Generate and verify the artifact

Follow `../../resources/artifact-contract.md`. Generate the modality artifact through the current upstream inference/export guidance, then harden it with environment-only secrets, explicit CLI paths, deterministic `--self-test`, structured output, requirements, and `RUN.md`.

Run:

1. dependency installation in a clean Python 3.10+ environment;
2. the shared artifact smoke helper without execution, inspect the generated tree, then return the exact `--execute-reviewed` command for a human or external host control to run with an evidence output outside the artifact tree;
3. one representative consumer integration test;
4. an exclusively frozen `freeze_delivery_check.py` contract created before execution, then helper-produced evidence from a human/external-host execution of the exact `record_delivery_check.py --check-contract <path> --execute-reviewed` command; hosted execution remains outside Sentinel, and offline execution requires a verified network-isolation boundary;
5. a negative test for missing credentials/input and an empty-result case.

A self-test without the applicable live/offline path leaves the artifact a `scaffold`. Never add `--execute-reviewed` without the user's explicit approval in the current turn; the helpers are not OS sandboxes.

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
  "schema_version": "2",
  "acceptance_id": "<id/revision>",
  "acceptance_path": ".vision-delivery/acceptance-<revision>.json",
  "acceptance_sha256": "<sha256>",
  "model_or_pipeline": "<verified identity/version>",
  "artifact_kind": "hosted-client|local-runtime|scaffold",
  "artifact_path": "<project-relative path>",
  "artifact_sha256": "<sha256>",
  "input_schema": {},
  "output_schema": {},
  "provider_dependency": "<name or none>",
  "data_boundary": "<local or approved destination>",
  "commands": {
    "self_test": [
      "<current-python>",
      "inference.py",
      "--self-test"
    ],
    "live": [
      "<python>",
      "inference.py",
      "<args>"
    ]
  },
  "expected_stdout_sha256": "<predeclared lowercase sha256>",
  "check_contract_path": ".vision-delivery/delivery-check-contract-<session>.json",
  "check_contract_sha256": "<sha256>",
  "checks": {
    "self_test": "passed",
    "live_or_offline": "passed|not-run"
  },
  "evidence": {
    "self_test": ".vision-delivery/self-test-evidence-<session>.json",
    "live_or_offline": ".vision-delivery/live-evidence-<session>.json"
  },
  "rollback": {
    "target": "<version>",
    "owner": "<person/team>"
  },
  "monitoring": {
    "status": "verified|external|not-configured"
  },
  "remaining_external_checks": []
}
```

Use project-relative paths in the handoff for portability, but execute verification with resolved absolute paths. Commands are canonical argv arrays, never shell strings. The fixed `<current-python>` self-test token is a portable evidence marker for the interpreter used by `artifact_smoke.py`; resolve it to that environment's Python executable only when replaying the command. Never place secrets or signed URLs in the handoff. The handoff validator must load the frozen acceptance and helper-produced local evidence, recompute both digests, and reject self-declared or stale `passed` states.

</methodology>

<ledger>

Follow `../../resources/ledger-protocol.md`. After the artifact checks pass, manually record `artifact_verified`. After the handoff file exists, manually record `delivery_handoff_emitted`. Include `acceptance_id`, artifact kind, and non-secret artifact digest in notes. Do not manually duplicate hook-covered platform actions. Unknown is never success.

</ledger>

\<stop_rules>

- No independent acceptance for the selected version → return to the modality skill.
- Missing current upstream platform truth → emit only a scaffold and the exact dependency needed.
- Hosted data movement is required → emit a sourced action brief and stop; conversational consent does not authorize Sentinel to send data.
- Provider action is required → emit a sourced action brief and stop; conversational consent does not authorize Sentinel execution.
- Live/offline smoke not run → do not call delivery complete.

\</stop_rules>
