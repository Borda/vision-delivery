# Runnable Artifact Contract

Every generated delivery artifact must identify what it actually is, keep secrets out of source, and prove its execution contract before it is called complete.

## Artifact Kinds

- **`hosted-client`** — sends data to a provider endpoint. It is user-owned client code, but it is not local inference and is not provider-independent.
- **`local-runtime`** — loads model weights and performs inference on the user's machine without a provider network call. Exporting weights alone does not satisfy this label; the offline inference path must run.
- **`scaffold`** — has an output schema and test fixture but lacks a verified live transport, model, or dependency. Never call a scaffold a runnable PoC.

Write the kind as an `ARTIFACT_KIND` constant in the artifact header, in `RUN.md`, in `expected-self-test.json`, and in `.vision-delivery/delivery-handoff-<session>.json`. These values and the provider dependency must agree across files. If a hosted transport is generated from current platform guidance, label it `hosted-client`. Use `local-runtime` only after an offline smoke test succeeds with networking unavailable.

## Generation Boundary

Do not preserve raw REST hosts, request shapes, SDK calls, model IDs, or deployment recipes in Sentinel templates. Read `roboflow-platform-lookup.md`, delegate exact execution to an installed official skill or current MCP skill resource, and then harden the returned starter against this contract. If no authoritative upstream source is available, emit a `scaffold` and state that the live transport is unverified.

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

2. Run the helper from the absolute path derived from this loaded file:

   ```bash
   python /absolute/plugin/root/resources/scripts/artifact_smoke.py \
       /absolute/path/to/inference.py \
       --expect-json /absolute/path/to/expected-self-test.json
   ```

3. The helper runs `--help` and `--self-test` from an arbitrary fresh working directory, scans source for embedded secret assignments, and compares output with the exact expected JSON.

4. Run one live-path smoke on representative user media. For `hosted-client`, obtain explicit data-movement approval first. For `local-runtime`, disable network during the acceptance run.

5. Record dependency versions, command, exit status, and output location in `RUN.md` and the delivery handoff.

6. Validate the final handoff before reporting delivery:

   ```bash
   python /absolute/plugin/root/resources/scripts/validate_delivery_handoff.py \
       /absolute/path/to/.vision-delivery/delivery-handoff-<session>.json \
       --project-root /absolute/path/to/project
   ```

The artifact helper injects a Python network guard for both checks and strips credential-shaped environment variables. A self-test that attempts DNS or socket access fails. This is an executable Python boundary, not an operating-system sandbox; non-Python child processes remain outside the helper's guarantee and must not be used by `--self-test`.

If the self-test passes but the live-path smoke cannot run, retain `artifact_kind: scaffold` and list the missing external check. If the live path fails, do not report the artifact as delivered.
