# Runnable Artifact Contract

Every generated delivery artifact must identify what it actually is, keep secrets out of source, and prove its execution contract before it is called complete.

Every executable claim is bound to a frozen acceptance artifact. Create a new acceptance revision before measurement with `resources/scripts/freeze_acceptance.py`; declare `--comparator gte` for minimum metrics such as recall/mAP or `--comparator lte` for maximum metrics such as latency/MAE. Never edit or replace an existing revision. Carry its `acceptance_id` and `acceptance_sha256` through smoke evidence, live/offline evidence, handoff, ledger, economics, and the terminal decision report.

## Artifact Kinds

- **`hosted-client`** — sends data to a provider endpoint. It is user-owned client code, but it is not local inference and is not provider-independent.
- **`local-runtime`** — loads model weights and performs inference on the user's machine without a provider network call. Exporting weights alone does not satisfy this label; the offline inference path must run.
- **`scaffold`** — has an output schema and test fixture but lacks a verified live transport, model, or dependency. Never call a scaffold a runnable PoC.

Write the kind as an `ARTIFACT_KIND` constant in the artifact header, in `RUN.md`, in `expected-self-test.json`, and in `.vision-delivery/delivery-handoff-<session>.json`. These values and the provider dependency must agree across files. If a hosted transport is generated from current platform guidance, label it `hosted-client`. Use `local-runtime` only after an offline smoke test succeeds with networking unavailable.

## Generation Boundary

Do not preserve raw REST hosts, request shapes, SDK calls, model IDs, or deployment recipes in Sentinel templates. Read `roboflow-platform-lookup.md` and use installed official skills or current MCP skill resources for read-only discovery only. For provider execution, emit a sourced action brief and stop; Sentinel never invokes data-moving, paid, or state-changing provider actions. Harden any externally returned starter against this contract. If no authoritative upstream source is available, emit a `scaffold` and state that the live transport is unverified.

## Required Files

Generate a small artifact directory rather than a context-free snippet:

```text
<artifact>/
  inference.py
  requirements.txt
  expected-self-test.json
  RUN.md
```

`RUN.md` records:

- artifact kind and provider dependency;
- Python 3.10+ requirement and installation command;
- exact live command and expected output schema;
- input/data movement boundary;
- required environment variables;
- acceptance ID and the evaluated model/data version;
- whether live-path and offline-path smokes passed.

The smoke validator greps `RUN.md` for these literal field labels (case-insensitive): `artifact kind`, `provider dependency`, `python`, `install`, `live command`, `output schema`, `data movement`, `environment variables`, `acceptance id`, `model/data version`, `smoke status`. Each label must appear verbatim; a `RUN.md` that paraphrases them fails `artifact_smoke.py`.

## Secret And Path Rules

- Read each secret named by current upstream guidance with `os.environ`; never freeze a provider-specific credential name or put a key, token, placeholder key, or query-secret literal in source, examples, output, or exception messages.
- Fail before network activity when a required variable is absent. Name the missing variable, never its value.
- Accept sources and output paths as CLI arguments. Do not depend on the user's current working directory.
- Resolve packaged fixtures relative to `Path(__file__).resolve().parent`; resolve user paths from explicit arguments.
- Write structured inference results to the requested destination and diagnostic logs to stderr.

## Executable Acceptance

Every generated `inference.py` must support:

```bash
python /absolute/path/to/inference.py --help
python /absolute/path/to/inference.py --self-test
```

`--self-test` must avoid network and credentials, exercise the normalization and modality-specific post-processing path with a committed fixture, and emit exact expected JSON. A syntax-only check is insufficient.

Before claiming completion:

1. Install the documented dependencies in a clean environment.

2. Run the helper from the absolute path derived from this loaded file. The first run performs static checks and exits `review-required`; it never executes generated code. Inspect the full artifact tree, then return this exact command for a human or external host control to run with the explicit `--execute-reviewed` acknowledgement and an evidence path outside the artifact directory:

   ```bash
   python /absolute/plugin/root/resources/scripts/artifact_smoke.py \
       /absolute/path/to/inference.py \
       --expect-json /absolute/path/to/expected-self-test.json \
       --acceptance /absolute/path/to/acceptance-<revision>.json \
       --evidence-out /absolute/path/to/.vision-delivery/self-test-evidence.json \
       --execute-reviewed
   ```

3. After review, a human or external host control may run the supplied command. The helper runs `--help` and `--self-test` from an arbitrary fresh working directory, scans the complete artifact tree for common embedded-secret forms, compares exact expected JSON, and writes helper-produced local evidence bound to the acceptance and artifact SHA-256 digests.

4. Before execution, exclusively create a delivery-check contract with `freeze_delivery_check.py`. It binds the frozen acceptance, current artifact tree, canonical Python/inference argv, check kind, consent reference, and `--expected-stdout-sha256` oracle. A human or external host control then runs the exact argv through `record_delivery_check.py --check-contract <path> --execute-reviewed`; Sentinel only supplies these commands and later validates the evidence. For `local-runtime`, freeze `--check offline` only inside a verified network-isolation boundary. The contract and evidence paths remain outside the artifact tree.

5. Record dependency versions, command, exit status, and output location in `RUN.md` and the delivery handoff.

6. Record handoff schema `2`, `acceptance_path`, `acceptance_sha256`, `artifact_sha256`, canonical command argv arrays, `check_contract_path`, `check_contract_sha256`, `expected_stdout_sha256`, and project-relative helper-evidence paths. The self-test argv uses the fixed portable marker `["<current-python>", "inference.py", "--self-test"]`; resolve `<current-python>` to the helper environment's interpreter only for replay. Validate the final handoff before reporting delivery:

   ```bash
   python /absolute/plugin/root/resources/scripts/validate_delivery_handoff.py \
       /absolute/path/to/.vision-delivery/delivery-handoff-<session>.json \
       --project-root /absolute/path/to/project
   ```

The artifact helper injects a Python network guard and strips credential-shaped environment variables after explicit review. A self-test that attempts Python DNS or socket access fails. This is not an operating-system sandbox. Generated code retains host-user filesystem and subprocess privileges, so Sentinel must never add `--execute-reviewed` on the user's behalf or describe it as isolation. Use an organizational OS sandbox/container when generated code is not trusted after review.

The handoff validator consumes helper-produced local evidence rather than trusting `"passed"` strings. It rejects an altered acceptance record, an artifact changed after verification, future/predating evidence, command or output-oracle mismatch, or mismatched artifact/model/kind fields. Evidence is still unsigned same-user local consistency evidence: a same-user adversary can forge it. Do not describe it as provenance, authorization, a provider receipt, or cryptographic identity proof.

If the self-test passes but the live-path smoke cannot run, retain `artifact_kind: scaffold` and list the missing external check. If the live path fails, do not report the artifact as delivered.
