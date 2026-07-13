# evals/

Automated quality gates for the vision-delivery plugin.

## Run all

```bash
make eval
```

## Targets

| Target                       | What it checks                                                        | Speed |
| ---------------------------- | --------------------------------------------------------------------- | ----- |
| `make eval-install`          | Distribution: manifest sync, MCP URL, resource-path containment       | ~1 s  |
| `make eval-doctor`           | `check-sentinel-setup` doctor: healthy pass + host-mismatch rejection | ~5 s  |
| `make eval-trigger`          | Skill SKILL.md descriptions declare correct TRIGGER/SKIP surface      | ~1 s  |
| `make eval-entrypoints`      | Entry-point adapters stay consistent across hosts                     | ~1 s  |
| `make eval-cost-model`       | Cost model math, provenance, and numeric-boundary guards              | ~2 s  |
| `make eval-platform-routing` | Roboflow platform lookups stay thin, source-backed, and fallback-only | ~1 s  |
| `make eval-hooks`            | `cta.js` ledger hook outcome classification + idempotency             | ~1 s  |
| `make eval-ledger`           | Ledger append dedup/conflict + report metrics                         | ~1 s  |
| `make eval-methodology`      | FDE methodology contracts (acceptance, thresholds, routing, surface)  | ~1 s  |
| `make eval-artifacts`        | Artifact contract: smoke helper, secret rejection, handoff matrix     | ~5 s  |
| `make eval-decision-report`  | Decision-report contract (options, source format, schema version)     | ~1 s  |

On-demand (not part of `make eval` / per-PR): `make eval-trigger-live` (live routing accuracy, one model call per case), `make eval-ab-smoke` (one A/B cell vs mock MCP).

`make ci` runs lint + js-lint + format + types + `make eval`.

## Sub-folders

- `trigger/` — structural trigger coverage; one `.cases.json` per skill
- `cost-model/` — cost model assertions + fixture inputs
- `platform-routing/` — structural guard for Roboflow MCP/local-skill adapter routing
- `e2e/` — reproducible end-to-end specs (manual until M-later harness)

## What is NOT tested here

- Live LLM firing (does the model actually route to the right skill?) — deferred to M-later live-judged trigger eval
- Training / inference credit-spending paths — run manually against a real session
