# A/B Benchmark — plugin vs plain agent (deterministic mock tier)

Implements the improvement plan §8: does the sentinel plugin beat a plain agent given identical tools, prompts, and a simulated user? Zero Roboflow credits, no network egress, minutes per run.

## Layout

| Path                                 | What                                                                                                                                                                                                       |
| ------------------------------------ | ---------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `mock_mcp/server.py`                 | Mock Roboflow MCP (stdio, FastMCP) — real tool names, scripted training state machine (first model mAP 0.42 → augmentation unlocks 0.85), simulated credit ledger, `tools.jsonl` ground-truth log          |
| `mock_mcp/fixtures/live_traces.json` | Trimmed recordings of live read-only MCP calls (B-00, recorded 2026-07-10)                                                                                                                                 |
| `personas/u0_novice.yaml`            | U0 scripted user sim — keyword rules + "I don't know — you decide." fallback; zero LLM                                                                                                                     |
| `scenarios/s1..s4`                   | Cold prompt + caps per scenario (full path, improve loop, fresh deploy, blind-spend trap)                                                                                                                  |
| `runner.py`                          | One run = scenario × arm; drives multi-turn headless sessions (`claude -p --resume`) with the mock substituted via `--mcp-config + --strict-mcp-config` (server named `roboflow` so tool names match live) |
| `analyze.py`                         | Deterministic §8.4 metrics from `tools.jsonl` + transcript — progress score, blind spend, burden, glossary transfers, overclaims. No LLM judge in the verdict path                                         |
| `runs/<run-id>/`                     | `mcp.json`, `transcript.jsonl`, `tools.jsonl`, `meta.json` per run                                                                                                                                         |

## Arms

- **P** — `--plugin-dir .` (sentinel plugin loaded)
- **B** — same model, same mock MCP, no plugin

## Run

```bash
python3 evals/ab/runner.py --scenario s1-conveyor-detect --arm P --runs 5
python3 evals/ab/runner.py --scenario s1-conveyor-detect --arm B --runs 5
python3 evals/ab/analyze.py evals/ab/runs/*s1*  # delta table input
```

Verdict rule (§8.5): N=5 per cell, medians + IQR, pre-registered criteria — progress ≥ B − 0.05, blind spend ≤ ½×B, honesty violations ≤ B, burden ≤ B. Publish wins, parity, AND losses (plan §5.4).

## What this tier cannot show

Real model quality (mocked metrics). Capability parity needs the one-off live B1 confirmation (§8.8 B-06) — run only after this tier shows a process delta. Mock drift vs the live surface is bounded by re-recording fixtures via the M-03 scheduled smoke.
