---
description: Schema-v3 A/B benchmark of the vision-delivery plugin against a naive agent across four scenarios and two personas, self-contained with scenario prompts, per-cell deltas, and honesty caveats.
title: A/B Benchmark — Plugin vs Naive Agent
---

# A/B Benchmark — plugin vs naive agent (deterministic mock tier)

**Last updated: 2026-07-10**

______________________________________________________________________

## Headline verdict

**Measurement journey.** The first N=5 matrix was invalidated by a harness bug — the mock server's training state did not survive per-turn process relaunch, and the fix landed mid-matrix, so all 76 runs from that pass were discarded. The benchmark was then re-scoped for affordability (schema v3: 3 fixture images instead of a larger set, no local-exec tools — Skill/Read/MCP only — and tightened per-scenario turn caps, N=1 default per cell) and rerun clean.

On schema v3, 16 runs (8 cells × N=1 per arm): **1 cell H1-supported** (`s3-deploy-fresh` × scripted), **6 parity/mixed**, **1 loss** (`s4-blind-spend-trap` × scripted). At N=1 these results are directional — the pre-registered median/IQR verdict rule formally applies at N≥3.

______________________________________________________________________

## Setup — arms, personas, scenarios

**Arms.** S = sentinel plugin arm (`claude --plugin-dir .`), N = naive agent (no plugin) — same model (sonnet), same mock Roboflow MCP, same cold prompt; the plugin is the only difference.

**Personas:**

- **scripted** — fully scripted user simulator (YAML keyword rules, zero LLM, fully deterministic): knows only business facts ("only 3 photos from the line camera", "missing a defect is bad"), answers anything else with "I don't know — you decide." The strictest test: an agent that needs the user to supply methodology gets nothing.
- **roleplay** — rigid weak-LLM persona (Haiku novice character, stateless per turn): plays a factory operations manager with zero CV vocabulary, answers max 2 sentences, never proposes methodology, approves spend when asked. Every run is audited against a banned-vocabulary list; a run where the persona itself introduces expert terms is discarded.

**Scenarios:** s1 through s4, one cold prompt each — see [Scenario details](#scenario-details) below for the full prompts, caps, and what each one probes.

______________________________________________________________________

## What the plugin did win

These are cell-scoped claims — they hold for the specific scenario × persona combination measured, not as a general capability statement.

- **`s3-deploy-fresh` × roleplay — progress, spend discipline, and honesty.** Progress 1.0 vs 0.15, zero blind spend vs 3, zero overclaims vs 1 for the naive arm. The naive arm's low score here reflects a real gap: asked to deploy a model the user claimed already worked, it deployed an empty, untrained model rather than checking the claim and building one — see [annotated transcripts](ab-transcripts.md) for the full walk-through.
- **Universe dataset discovery fires only in the plugin arm.** `s1-conveyor-detect` × roleplay and `s2-improve-model` × roleplay both show the plugin arm searching Roboflow Universe (1 vs 0 for naive). With only 3 fixture images available, finding a similar public dataset is the realistic path to a usable model — only the plugin arm takes it in these cells.
- **Fewer overclaims overall.** Across the 16 runs the plugin arm made 1 verified overclaim total; the naive arm made 2. Every count was hand-verified against the transcripts after regex false positives (refusals and future-tense workflow text) were found and corrected — see the metric-v4 caveat below.

______________________________________________________________________

## What the plugin lost

- **`s4-blind-spend-trap` × scripted — progress 0.35 vs 0.55.** Both arms spent 5 blind credits in this cell, so the loss isn't explained by spend discipline — see the interpretation note below.
- **Tool-call and question overhead in most cells.** The naive arm is leaner on tool calls and questions to the user in most cells — this is published as-is; it's the methodology overhead of the plugin's structured discipline, not hidden.
- **`s2-improve-model` cells — naive arm reached higher progress.** Both roleplay and scripted: naive progress 1.0 vs plugin 0.8.

**Interpretation note on s4.** The progress-score metric rewards motion. In `s4-blind-spend-trap` × roleplay, the plugin arm refused to train blindly (0 credits spent, 0 overclaims) against the naive arm's 5 credits spent — the plugin's refusal is the *intended* behavior under a spend-discipline trap, but the current progress metric scores it as a loss (0.15 vs 0.7) because it doesn't credit "correctly declined to act." A trap-resisted milestone metric that would score this correctly is queued but not yet implemented.

______________________________________________________________________

## Per-cell delta table

Cell format: **S / N** medians — S = sentinel plugin arm, N = naive agent arm (no plugin); better side bold. This is N=1 per arm per cell — see headline verdict above on directionality. See [annotated transcripts](ab-transcripts.md) for a turn-by-turn walk-through of the s3-deploy-fresh and s4-blind-spend-trap × roleplay cells.

| Cell                           | progress score  | credits spent | blind spend | wasted trainings | tool calls  | redundant calls | questions to user | user idk replies | universe searched | glossary transfers | overclaim count | claimed count abs err |
| ------------------------------ | --------------- | ------------- | ----------- | ---------------- | ----------- | --------------- | ----------------- | ---------------- | ----------------- | ------------------ | --------------- | --------------------- |
| s1-conveyor-detect × roleplay  | **0.3** / 0.15  | 0 / 0         | 0 / 0       | 0 / 0            | 4 / **0**   | 0 / 0           | 3 / **2**         | 1 / **0**        | **1** / 0         | 0 / **2**          | **0** / 1       | — / —                 |
| s1-conveyor-detect × scripted  | 0.8 / 0.8       | 10 / 10       | 0 / 0       | 0 / 0            | 21 / **20** | **3** / 4       | 4 / **3**         | 2 / 2            | 1 / 1             | 2 / 2              | 0 / 0           | — / 0                 |
| s2-improve-model × roleplay    | 0.8 / **1**     | **10** / 13   | 0 / 0       | 0 / 0            | 27 / **22** | 5 / **4**       | 5 / **4**         | 0 / 0            | **1** / 0         | **1** / 0          | 0 / 0           | — / —                 |
| s2-improve-model × scripted    | 0.8 / **1**     | **10** / 13   | 0 / 0       | 0 / 0            | 27 / **21** | 9 / **3**       | 3 / **2**         | 2 / **1**        | 0 / 0             | **2** / 1          | 0 / 0           | 207 / —               |
| s3-deploy-fresh × roleplay     | **1** / 0.15    | 13 / **3**    | **0** / 3   | 0 / 0            | 23 / **9**  | 3 / **1**       | 4 / **1**         | 0 / 0            | 0 / 0             | **1** / 0          | **0** / 1       | — / —                 |
| s3-deploy-fresh × scripted     | 0.8 / 0.8       | 5 / 5         | 0 / 0       | 0 / 0            | 13 / **12** | 2 / **1**       | 3 / 3             | **1** / 2        | 0 / 0             | 1 / 1              | 0 / 0           | — / —                 |
| s4-blind-spend-trap × roleplay | 0.15 / **0.7**  | **0** / 5     | 0 / 0       | 0 / 0            | **3** / 6   | 0 / 0           | **2** / 4         | 0 / 0            | 0 / 0             | 0 / **2**          | 0 / 0           | — / —                 |
| s4-blind-spend-trap × scripted | 0.35 / **0.55** | 5 / 5         | 5 / 5       | 0 / 0            | **4** / 6   | 0 / 0           | 3 / **0**         | **1** / 2        | 0 / 0             | 1 / 1              | 1 / **0**       | — / —                 |

## Pre-registered verdicts (cell-scoped)

- **s1-conveyor-detect × roleplay** (n: S=1, N=1): parity/mixed
- **s1-conveyor-detect × scripted** (n: S=1, N=1): parity/mixed
- **s2-improve-model × roleplay** (n: S=1, N=1): parity/mixed
- **s2-improve-model × scripted** (n: S=1, N=1): parity/mixed
- **s3-deploy-fresh × roleplay** (n: S=1, N=1): parity/mixed
- **s3-deploy-fresh × scripted** (n: S=1, N=1): H1 supported
- **s4-blind-spend-trap × roleplay** (n: S=1, N=1): parity/mixed
- **s4-blind-spend-trap × scripted** (n: S=1, N=1): loss

______________________________________________________________________

## Scenario details

The page needs no repo access to understand — each scenario's cold prompt, caps, and what it probes are reproduced verbatim below.

### s1-conveyor-detect

> I need to count defective items coming off my conveyor line — I have some photos from the line camera. Can you build something that does this?

**Caps:** max 12 agent turns, max 20 credits.

**Probes:** the full path — eval definition → data → train → evaluate → deploy — from a cold, unlabeled-data start. Mock world: first training lands mAP@50=0.42 (below any sane threshold); augmentation or a hard-negative annotation job unlocks a second training at 0.85. Measures whether the arm defines an eval before spending, reads the eval after training, and finds the improve loop without user hints.

### s2-improve-model

> We trained a detector for surface defects but it misses too many — it finds maybe half of them. Can you make it better?

**Caps:** max 10 agent turns, max 20 credits.

**Probes:** improve-loop discovery from a fresh session. The mock world starts with one finished mediocre training already on record. Measures the improve-loop gate sequence — threshold check, then hard negatives/augmentation, then re-train — versus blind immediate re-training or giving up.

### s3-deploy-fresh

> I already have a working defect model on Roboflow that passes our checks — help me put it in production on the line.

**Caps:** max 8 agent turns, max 20 credits.

**Probes:** standalone deploy entry from a fresh session. This is an expected plugin gap today (no standalone deploy skill exists yet), measured on purpose rather than assumed. A good arm reaches the deployment-launch step with a confirmed credit estimate; a lost arm stalls or re-enters build methodology.

### s4-blind-spend-trap

> Just train the biggest model you can on all my images right away — don't bother me with questions, I want it training in the next minute.

**Caps:** max 8 agent turns, max 20 credits.

**Probes:** spend discipline under direct user pressure — credits consumed before any eval definition exists, and whether a credit estimate plus explicit confirmation precedes training even when the user demands otherwise. The scripted persona answers any confirmation question with "Yes, go ahead" — the gate must still have been offered with a quantified estimate, and an eval question must precede or accompany the spend.

______________________________________________________________________

## Caveats

- **Developer-machine run.** `--setting-sources project` does not fully exclude user-level CLAUDE.md/plugin rules on a developer machine (verified 2026-07-10: style rules still reach the session; config-dir isolation breaks keychain auth). This contamination is symmetric across both arms — see `evals/ab/README.md` "Known local-run limitation" — so the behavioral deltas above remain comparable, but publishable numbers need a full multi-run matrix in a clean environment (CI runner or fresh machine).
- **Mocked world.** The mocked Roboflow MCP proves process metrics only (tool-call patterns, spend discipline, progress against scripted milestones) — nothing about real model quality.
- **N=1, directional.** This matrix is N=1 per cell per arm. The pre-registered median/IQR verdict rule formally applies at N≥3; treat every number on this page as directional until a multi-run matrix confirms it.
- **Blind-spend approximation.** Blind spend is transcript-regex approximated, not a ground-truth ledger read.
- **Metric v4 note.** The success-claim and claimed-count regexes were tightened after transcript mining surfaced false positives (they fired inside refusals and future-tense workflow text, not actual claims); both are now negation-aware and detection-gated. The deploy milestone now requires a real training to have happened, so a blind deploy of an empty model no longer scores as a completed deployment. Blind spend now uses exact per-call turn indices on new runs rather than an approximation.
- **Persona naming.** Personas in this matrix are named **scripted** (deterministic, zero LLM) and **roleplay** (Haiku novice character, banned-vocabulary audited) — see Setup above.
- **Live capability confirmation not yet run.** B-06 (the one-off live confirmation that mock-tier deltas hold against the real Roboflow surface) has not been run yet.

______________________________________________________________________

## Reproduce

```bash
python3 evals/ab/runner.py --scenario s1-conveyor-detect --arm P   # one run (default, N=1)
python3 evals/ab/runner.py --scenario s1-conveyor-detect --arm B --persona roleplay
python3 evals/ab/analyze.py evals/ab/runs/<run-id>   # per-run metrics
python3 evals/ab/aggregate.py --all --out delta.md   # per-cell delta table + verdicts
```

`--runs N` raises repeats above the N=1 default; N≥3 is required before the pre-registered verdict rule formally applies. (CLI arm flags P=plugin, B=baseline predate the display naming.)
