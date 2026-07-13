---
name: check-sentinel-setup
description: |
  Run an offline Sentinel package doctor and separate local installation defects from host enablement or Roboflow sign-in problems. TRIGGER when: the user asks to check, verify, diagnose, or troubleshoot a Sentinel plugin installation; run the setup doctor; find missing skills, packaged files, or Roboflow tools; or confirm Sentinel installed correctly. SKIP when: Sentinel and Roboflow work and the user wants to count boxes or solve a CV task; the package is healthy but OAuth/sign-in alone failed (auth-setup); or the request is deployment economics/crossover only (estimate-economics).
---

# Check Sentinel Setup

Diagnose setup in layers without guessing host state or copying upstream Roboflow authentication recipes.

## Run the offline package check

Resolve the plugin root from this loaded skill file, then run from any working directory:

```bash
python <plugin-root>/resources/scripts/sentinel_doctor.py --json
```

Do not assume the current project is the plugin checkout. The doctor checks synchronized manifests, the URL-only MCP entry, packaged resources, and discoverable skills. It performs no network or account operation.

If the doctor fails, report every failed check and recommend reinstalling with the two host-specific commands in the repository quick start. Do not edit host settings automatically.

## Check the host layer

After the offline status is `passed`:

1. Verify `sentinel@sentinel` is installed and enabled using host-visible plugin state when available.
2. Verify the host exposes the bundled skills and a `roboflow` MCP server configured at the expected URL. Never infer this from repository files alone.
3. Report Roboflow authorization as `unverified` unless an authenticated read actually succeeds in the active host.
4. When connection recovery is needed, load sibling `../auth-setup/SKILL.md` and follow it. Do not restate a provider credential, API, or UI recipe here.

## Report

Return three separate results:

- `package`: `passed|failed`, with doctor evidence;
- `host`: `passed|failed|unverified`, with installed/enabled evidence;
- `roboflow_auth`: `passed|failed|unverified`, only from an observed host result.

Never collapse a healthy package into “fully working” while the host or authenticated service remains unverified.
