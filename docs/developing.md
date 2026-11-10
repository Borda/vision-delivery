---
description: How the Sentinel repository is laid out, how to run one check or all of them, and how a change reaches both hosts.
title: Developing
---

# Developing

This page is for someone changing the repository. It covers the layout, how to run the checks, and how a change reaches Claude Code and Codex. The [contributing guide](https://github.com/Borda/vision-delivery/blob/main/.github/CONTRIBUTING.md) says which changes are open to pull requests.

## Layout

| Path             | What it holds                                                                                                                                                                | Who edits it                                        |
| ---------------- | ---------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | --------------------------------------------------- |
| `claude-skills/` | The skills, one folder per route. This is the source of truth for both hosts.                                                                                                | Maintainers                                         |
| `codex-skills/`  | The Codex copy of the skills. Generated; never edit it by hand.                                                                                                              | The generator                                       |
| `resources/`     | Methodology and contracts the skills load (`*.md`), and the helper scripts that ship to users (`resources/scripts/`), such as the scorer.                                    | Maintainers; the scorer is a pull request lane      |
| `hooks/`         | The Claude Code spend gate (`gate.js`), the ledger hook (`cta.js`), their shared helpers, the generated gate policy, and the hook manifests for each host.                   | Maintainers; policy entries are a pull request lane |
| `scripts/`       | Repository tooling: the gate-policy generator and its rules, the ledger helper and report, the cost model, the package builder and validator, and the Codex skill generator. | Maintainers                                         |
| `shared/`        | Text and settings shared by both hosts: the skill roster (`skill-roster.json`), the capability contract, and the Codex overrides the generator applies.                      | Maintainers                                         |
| `templates/`     | The skeleton a new route is created from.                                                                                                                                    | Maintainers                                         |
| `evals/`         | The checks. One folder per concern.                                                                                                                                          | Anyone, with the change they test                   |
| `examples/`      | Small runnable examples with synthetic or public data.                                                                                                                       | A pull request lane                                 |
| `docs/`          | This site.                                                                                                                                                                   | A pull request lane                                 |

## Set up

You need Python 3.10 or newer and Node.js.

```bash
python -m venv .venv
source .venv/bin/activate
make eval-setup
```

`make eval-setup` installs the Node and Python packages the checks need. The lint tools are pinned in `.pre-commit-config.yaml`; run them through `pre-commit`, not directly, so your versions match CI.

## Run the checks

```bash
make eval          # every deterministic check; no network, no account, no spend
make ci            # lint, format, types, and make eval, as CI runs them
make eval-hooks    # one concern: the spend gate, the ledger hook, and the gate policy
```

Each concern has its own target; `evals/README.md` lists them. A check is a plain script that exits non-zero on failure, so you can also run one file directly, for example `python evals/baseline/assert_score_baseline.py`.

Two kinds of check are not part of `make eval`, because they cost money or need an account:

- `make eval-trigger-live` asks a live model which skill it would pick for each prompt.
- `make eval-ab-smoke` runs one cell of the plugin-versus-plain comparison against a mock Roboflow server.

Run those only on purpose. A number from them is published only with its run artifacts committed; `evals/ab/README.md` explains how.

To build this site:

```bash
make docs-build
```

## How a change reaches both hosts

1. Edit the skill under `claude-skills/`, or the shared text under `resources/`.
2. Run `python scripts/sync_codex_skills.py`. It rewrites `codex-skills/` from `claude-skills/`, removing the parts Codex does not use and applying `shared/codex-overrides.json`.
3. Run `make eval-parity`. It fails when the two trees have drifted.
4. Run `make eval`.

The hooks differ by host and are not generated. Claude Code loads `hooks/claude-hooks.json`, which registers the spend gate and the ledger hook. Codex loads `hooks/hooks.json`, which registers the ledger hook only, because Codex has no pre-action hook. That is why the spend gate exists on Claude Code only.

## Common changes

### Change how a Roboflow tool is gated

The gate never guesses from a tool name. It looks the tool up in `hooks/gate-policy.json`, which is generated from Roboflow's tool catalog and the rules in `scripts/gate_policy_rules.json`.

1. Edit `scripts/gate_policy_rules.json`. An override needs a written reason. No override can open a tool that Roboflow does not mark read-only.
2. Run `python scripts/build_gate_policy.py` to re-apply the rules to the recorded catalog flags, or pass `--catalog` with a freshly downloaded catalog to pick up new tools.
3. Run `make eval-hooks`.

### Add a route

`shared/skill-roster.json` names every skill once, with its kind and the listings it must appear in. Do not create the skill folder by hand.

1. Run `python scripts/new_route.py <name> --kind <kind> --use "<one line>"`. It creates `claude-skills/<name>/SKILL.md` and `evals/trigger/<name>.cases.json` from `templates/route/`, registers the route in the roster, and prints the listing files the route must appear in.
2. Fill in the `TODO(template)` lines and the trigger cases, and add the route to each listing it printed.
3. Run `python scripts/sync_codex_skills.py`, then `make eval`. `make eval-release` fails while a listing disagrees with the roster, and `make eval-roster` checks the roster, the scaffold, and the router's route table.

A flagship or preview route must also appear in the route table of `claude-skills/solve-cv-task/SKILL.md`, and the methodology and artifact contracts apply to it as soon as the roster names it. A utility skill, such as `status`, is not a route: it is listed in the README, `docs/llms.txt`, and the capability contract only, and stays out of the use-cases matrix and the outcome form's route list. The scaffold is a repository tool and is not part of the installed plugin.

### Publish a run behind a number

A number from a paid or live run is published only with its run folder committed. `python scripts/publish_run.py pack` copies the allowed files of one run into `evals/ab/published/` or `evals/trigger-live/published/`, decodes every JSON value, masks local paths, the login name, and the host name, refuses anything that looks like a credential, an email address, or an IPv4 address (in a file or in a set or run name), and writes a manifest of digests; `verify` checks a published folder against its manifest and its folder names. `make eval` verifies every folder under both `published/` roots and fails on any other file there. The helper is a denylist: it cannot tell that text names a customer, a site, or a person, so read the diff before committing. The README in each `published/` folder gives the commands.

### Add a scorer metric

The scorer is `resources/scripts/score_baseline.py`, and its tests are `evals/baseline/assert_score_baseline.py`. A new metric needs an interval method, a place in the refusal rules, plain wording for its printed line, and tests that include the cases where it must refuse.

### Change a doc sample

The blocks on the [Sample Output](sample-output.md) page are checked against the real tools by `make eval-docs-samples`. Print fresh output with `python evals/docs/assert_sample_output.py --print` and paste it in.

### Change the pitch

One sentence describes the project on every public surface. `make eval-release` fails when any of them drifts, so change them together: the description in each plugin manifest is the reference.

## Before a release

The [release policy](release-policy.md) lists the release gate. Two of its steps compare the repository with Roboflow's current catalog and skill roster, and `make eval-upstream` fails unless both are supplied and still match.
