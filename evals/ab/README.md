# A/B Benchmark — plugin vs plain agent (deterministic mock tier)

Does the sentinel plugin beat a plain agent given identical tools, prompts, and a simulated user? Zero Roboflow credits, no network egress, minutes per run.

## Layout

| Path                                 | What                                                                                                                                                                                                       |
| ------------------------------------ | ---------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `mock_mcp/server.py`                 | Mock Roboflow MCP (stdio, FastMCP) — real tool names, scripted training state machine (first model mAP 0.42 → augmentation unlocks 0.85), simulated credit ledger, `tools.jsonl` ground-truth log          |
| `mock_mcp/fixtures/live_traces.json` | Trimmed recordings of live read-only MCP calls (recorded 2026-07-10)                                                                                                                                       |
| `personas/u0_novice.yaml`            | U0 scripted user sim — keyword rules + "I don't know — you decide." fallback; zero LLM                                                                                                                     |
| `scenarios/s1..s4`                   | Cold prompt + caps per scenario (full path, improve loop, fresh deploy, blind-spend trap)                                                                                                                  |
| `runner.py`                          | One run = scenario × arm; drives multi-turn headless sessions (`claude -p --resume`) with the mock substituted via `--mcp-config + --strict-mcp-config` (server named `roboflow` so tool names match live) |
| `analyze.py`                         | Deterministic metrics from `tools.jsonl` + transcript — progress score, blind spend, burden, glossary transfers, overclaims. No LLM judge in the verdict path                                              |
| `runs/<run-id>/`                     | `mcp.json`, `transcript.jsonl`, `tools.jsonl`, `meta.json` per run                                                                                                                                         |

## Arms

- **P** — `--plugin-dir .` (sentinel plugin loaded)
- **B** — same model, same mock MCP, no plugin

## Run

```bash
python3 evals/ab/runner.py --scenario s1-conveyor-detect --arm P   # one run (default)
python3 evals/ab/runner.py --scenario s1-conveyor-detect --arm B --persona roleplay
python3 evals/ab/analyze.py evals/ab/runs/<run-id>   # per-run metrics
python3 evals/ab/aggregate.py --all --out delta.md   # per-cell delta table + verdicts
```

Schema v3 (2026-07-10, affordability + realism): no local-exec tools (Skill,Read,MCP only), 3 small (320x240) fixture images — the realistic "user has a few snapshots" case, making similar-dataset discovery (Universe) the viable path, measured by the universe_searched metric; effective caps min(5 persona user turns, scenario max_agent_turns) x 15 inner agent turns. Default N=1 per cell — determinism comes from the U0 scripted persona, seeded fixtures, and the deterministic mock world; residual LLM sampling variance means N=1 results are directional. `--runs N` raises repeats; the pre-registered verdict rule (medians + IQR, non-inferiority margins) applies at N>=3. Every run's meta.json carries `harness_git` so heterogeneous matrices are detectable (matrix-taint lesson).

## What this tier cannot show

Real model quality (mocked metrics). Capability parity needs the one-off live B1 confirmation — run only after this tier shows a process delta. Mock drift vs the live surface is bounded by re-recording fixtures via the scheduled freshness smoke.

## Fixture hardening (smoke-5 lesson)

The first fixture generator drew high-contrast dark blobs as defects — a ~30-line threshold script solved the task and both arms legitimately skipped the platform path the milestones measure. Current fixtures resist that shortcut: defects are low-contrast cracks in the item's own shade, the belt carries dark stain distractors with the old defect signature, and per-frame lighting varies — a naive dark-blob counter reports ~2x the true defect count (verified: 103 vs 51 ground truth). Ground truth stays analyzer-side (the simulated user has no labels), so an arm that ships an unvalidated heuristic and declares success is scored: overclaim + claimed-count error vs truth.

## Known local-run limitation

`--setting-sources project` does not fully exclude user-level CLAUDE.md/plugin rules on a developer machine (verified 2026-07-10: style rules still reach the session; config-dir isolation breaks keychain auth). Contamination is identical across both arms, and the verdict metrics are behavioral (tool log + milestones), so smoke runs remain comparable — but run the full N=5 matrix in a clean environment (CI runner or fresh machine) for publishable numbers.
