# Published live-routing run artifacts

Every live-routing number (accuracy, precision, recall, misroutes) points to a folder here. Scratch results under `evals/trigger-live/runs/` stay gitignored; only folders written by `scripts/publish_run.py` are committed.

## Rule

No published number without a committed artifact folder. A docs page, README, or changelog line that reports a routing number names its set folder, `evals/trigger-live/published/<set-id>/`, and that folder holds every run the number counts. The number is quoted with the manifest SHA-256 that `pack` prints for each run it cites. The routing numbers published before this folder existed, including the single Claude Sonnet run summarized in `docs/support-and-scope.md`, predate the rule: their results were never committed and cannot be re-scored.

## Layout

```text
evals/trigger-live/published/<set-id>/<results-file-stem>/
    results.jsonl
    publish-manifest.json
```

## Committed from each run

| File                    | Content                                                                                                                                            |
| ----------------------- | -------------------------------------------------------------------------------------------------------------------------------------------------- |
| `results.jsonl`         | The results file `run_live.py` wrote, one row per case: `expected`, `should_fire`, `fired`, `exact`, `router_tolerant`, `prompt`, `model`, `host`. |
| `publish-manifest.json` | Written by the helper: suite, set, run, the file's byte size and SHA-256, and whether path masking changed it.                                     |

## Never committed

- Credentials, tokens, keys, and raw host or provider responses. `run_live.py` parses each host transcript in memory and writes only the row fields above; the prompts come from the committed `evals/trigger/*.cases.json`.
- The helper decodes every row before it judges or masks anything, so a JSON escape cannot hide a secret or a path. It refuses the run, writing nothing, when a decoded string, a key, or a key read together with its value matches a secret-like pattern from `scripts/redaction.py` (the patterns of `scripts/validate_package.py` plus API keys, bearer tokens, signed URL parameters, and key or password assignments), when an email or IPv4 address remains after masking, or when the set name, the run name, the target path, or the manifest matches a secret-like pattern. Files over 250 KB are refused, matching the repository's large-file hook.
- Inside every decoded string value the helper masks the run location, the repository, and the publisher's home folder; the owner name of any other home folder (`/Users/`, `/home/` in any letter case, spaces included, or `X:\Users\`); `/root`; macOS and Linux temporary roots; the publisher's login name as a path segment; and the publisher's host name. Rows are re-serialized one per line in their original key order.

## Publish, verify, re-score

```bash
python3 scripts/publish_run.py pack --suite trigger-live --run evals/trigger-live/runs/<results-file>.jsonl --set <set-id>
python3 scripts/publish_run.py verify evals/trigger-live/published/<set-id>/<results-file-stem>
```

`verify` fails when any committed byte no longer matches the manifest, when the manifest's set or run differs from the folder names, or when the decoded content holds secret-like material, an email or IPv4 address, or an unmasked home folder owner or temporary root. It catches accidental edits, not a coordinated edit of a file and its manifest entry: git history is the record of that. `make eval` runs `verify` on every committed `<set>/<run>/` folder and fails on any other file under `published/` except this README.

The helper is a denylist over decoded text. It cannot judge whether a prompt or a row names a customer, a site, a product, or a person. It masks only this machine's host name, not other host names, and it does not detect IPv6 addresses or passwords shorter than 16 characters or without a digit. Read the diff before committing.

Re-score by recounting the rows the way `run_live.py` does: positives are rows with `should_fire` true, counted exact when `exact` is true and router-tolerant when `router_tolerant` is true; per skill, a true positive is a positive row whose `fired` equals `expected`, a false negative is a positive row where it does not, and a false positive is a negative row whose `fired` equals `expected`.
