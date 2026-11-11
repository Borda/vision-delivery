# Release Policy

Sentinel follows semantic versioning for repository-owned public behavior:

- **Patch:** compatible fixes, documentation corrections, and evidence clarifications.
- **Minor:** backward-compatible skills, routes, fields, or integrations.
- **Major:** incompatible plugin interfaces, artifact schemas, commands, or behavior contracts after `1.0.0`.

Before `1.0.0`, a minor release may make an incompatible security or evidence-integrity correction only when the changelog names the exact affected interface, provides a migration, and the compatibility page marks the break. Silent schema reinterpretation is never allowed.

Upstream Roboflow behavior is not versioned by this project. A release must name any tested upstream assumptions rather than imply they are frozen.

## Release gate

Before a human publishes a release:

1. reconcile versions in all plugin manifests and generated records,
2. run strict documentation, link, eval, hook, and pre-commit checks,
3. validate supported host manifests and exact install commands,
4. review permissions, secrets, paid actions, and data-flow disclosures,
5. verify every changed headline claim against committed evidence,
6. list mocked, private, single-run, and pending evidence,
7. update the [changelog](https://github.com/Borda/vision-delivery/blob/main/CHANGELOG.md) and compatibility notes,
8. inspect the built package or plugin from a clean environment,
9. re-run live routing (`make eval-trigger-live`) on the current route set, at least two repeats and on both hosts where available, and record the summary; a release that adds, removes, or rewrites a skill trigger cannot reuse an older run,
10. triage open outcome reports (`outcome-report` label) and note any that change a support tier,
11. refresh the upstream Roboflow skill roster (`evals/platform-routing/upstream-skills.json`: names, source commit, date) from a current `roboflow/computer-vision-skills` clone, then run `SENTINEL_UPSTREAM_SKILLS_DIR=<clone>/skills make eval-platform-routing` and update the delegation map for any drift,
12. download Roboflow's current published tool catalog, regenerate the gate policy with `python scripts/build_gate_policy.py --catalog <file> --release <release tag> --as-of <date> --expect-sha256 <digest>`, review the `hooks/gate-policy.json` diff (new tools, changed read-only flags, every override reason), then run `SENTINEL_TOOL_CATALOG=<file> SENTINEL_UPSTREAM_SKILLS_DIR=<clone>/skills make eval-upstream`, which fails when either source is missing or has drifted,
13. have the maintainer run paid live dual-plugin routing once per release on a clean Claude Code host profile with both plugins installed: `python3 evals/trigger-live/run_live.py --host claude --dual-cases --with-plugin-dir <path to a clone of the official Roboflow plugin> [--model sonnet|opus]`, at least two repeats of the six prompts; record per-group counts, the `front_door_collisions` list and collision count, and pack results from `evals/trigger-live/runs/` with `python3 scripts/publish_run.py pack --suite trigger-live --run <results file> --set <set-id>`; a release changing a skill trigger or the upstream roster cannot reuse an older run; list a missing run as pending evidence in step 6, never claim it,
14. have the maintainer record one paid live session per release climbing the baseline ladder from rung 0 to rung 3 on one public licensed dataset; pack rung 0 with `python3 scripts/package_golden_run.py pack ...` following `examples/golden-run/README.md`, and commit the packed golden run plus a folder containing the redacted project ledger (`.vision-delivery/ledger.jsonl`), per-rung scorer output, and session transcript; rungs 1 to 3 have no packer yet, so assemble that folder by hand and review it; list a missing run as pending evidence in step 6, never claim it.

Remote publication, tags, releases, marketplace changes, and branch protection are human-owned operations. Their existence must not be claimed until verified on the remote service.

GitHub Pages deployment additionally requires a maintainer to select **GitHub Actions** as the Pages source in the repository settings. Required checks and branch protection must be configured on the remote repository before they can be described as enforced.

## Evidence policy

A release note may call a route "proven" only when the exact claim has a versioned fixture or study, reproducible command, result, environment, sample size, and material limitations. A workflow with instructions but without comparable live evidence is "guided." Platform-specific claims remain delegated to current official Roboflow sources.

Security fixes may be prepared privately and disclosed after users have a practical remediation path. See the repository [security policy](https://github.com/Borda/vision-delivery/blob/main/.github/SECURITY.md).
