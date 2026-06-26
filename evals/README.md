# evals/

Automated quality gates for the vision-delivery plugin.

## Run all

```bash
make eval
```

## Targets

| Target                 | What it checks                                                          | Speed   |
| ---------------------- | ----------------------------------------------------------------------- | ------- |
| `make eval-trigger`    | Skill SKILL.md descriptions declare correct TRIGGER/SKIP surface        | ~1 s    |
| `make eval-cost-model` | Cost model math + recommendation direction on fixture inputs            | ~2 s    |
| `make eval-e2e`        | End-to-end cold-prompt → passing eval flow (spec only — no harness yet) | instant |

## Sub-folders

- `trigger/` — structural trigger coverage; one `.cases.json` per skill
- `cost-model/` — cost model assertions + fixture inputs
- `e2e/` — reproducible end-to-end specs (manual until M-later harness)

## What is NOT tested here

- Live LLM firing (does the model actually route to the right skill?) — deferred to M-later live-judged trigger eval
- Training / inference credit-spending paths — run manually against a real session
