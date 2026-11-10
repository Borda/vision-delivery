# Contributing

Thank you for looking. Sentinel takes two kinds of contribution: issue reports from anyone, and pull requests in four narrow lanes that are cheap to review and hard to get dangerously wrong.

## Issues

Use the [issue chooser](https://github.com/Borda/vision-delivery/issues/new/choose) for:

- reproducible bug reports,
- actionable product, documentation, or workflow suggestions,
- outcome reports: how a real session went, good or bad. These are the most useful thing you can send.

Describe the problem clearly and include only information you are authorized to make public.

## Pull request lanes

> **Status: not open yet.** These lanes open when required checks are enforced on `main`. That is a repository setting the maintainer has not confirmed. Until this notice is removed, open an issue first and wait for a maintainer to ask for the pull request.

Once the lanes are open, a pull request will be welcome without a prior invitation when it stays inside one of them:

| Lane                              | What you may change                                                                                                                                                  | What the pull request must contain                                                                                                                                                                                                                         |
| --------------------------------- | -------------------------------------------------------------------------------------------------------------------------------------------------------------------- | ---------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| Public fixtures and recorded runs | `examples/`, benchmark fixtures, and the committed run folders under `evals/ab/published/` and `evals/trigger-live/published/`, packed with `scripts/publish_run.py` | Only media and data you may publish, with its source and license stated; no credentials, private media, or raw provider responses                                                                                                                          |
| Gate policy entries               | `scripts/gate_policy_rules.json` and the regenerated `hooks/gate-policy.json`                                                                                        | The written reason for each override, the catalog release it was checked against, and a passing `make eval-hooks`. A change may make the gate stricter. A change that opens a tool needs the provider's read-only flag; the generator refuses it otherwise |
| Scorer task types                 | `resources/scripts/score_baseline.py` and `evals/baseline/`                                                                                                          | Tests for the new metric, including the refusal cases (missing predictions, zero denominator, too few cases), and the interval method with its source                                                                                                      |
| Documentation                     | `docs/`, `README.md`, and example READMEs                                                                                                                            | No new claim without committed evidence; `mkdocs build --strict` passes                                                                                                                                                                                    |

Every lane pull request must also:

- change one lane only,
- pass `make ci` locally (see the [developing guide](../docs/developing.md)),
- contain no credentials, private customer data, faces, license plates, medical data, or media you are not authorized to share,
- state in its description what was run and what was not.

## Maintainer-only areas

These stay closed to uninvited pull requests, because a small wording change can alter what the agent does with a user's data or money, and review needs a live session:

- the skills (`claude-skills/`, and `codex-skills/`, which is generated),
- the methodology and contracts under `resources/` (the Markdown files),
- the hook code (`hooks/gate.js`, `hooks/cta.js`, `hooks/roboflow-ops.js`) and hook manifests,
- release, packaging, and CI configuration.

If you see a problem there, open an issue with a reproducer. A maintainer may then ask for a pull request.

## Reporting safely

For a bug report, include the Sentinel version or commit, host and version, steps to reproduce, expected and actual behavior, and a minimal public-safe reproducer. For a suggestion, state the problem it solves, the affected user, and the outcome you expect.

Never include credentials, private customer data, sensitive media, or personal data. Report suspected vulnerabilities through the [security policy](SECURITY.md), not a public issue.

By participating, you agree to follow the [Code of Conduct](CODE_OF_CONDUCT.md).
