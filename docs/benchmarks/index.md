---
description: Sentinel benchmark register separating measured routing, synthetic process comparisons, one small CV fixture, and pending route evidence.
title: Benchmarks And Evidence
---

# Benchmarks And Evidence

The repository contains three different evidence types. They answer different questions and must not be merged into one “proven CV” claim.

| Evidence           | What it tests                                | Result                                                                                                        | What it does not prove                                                                       |
| ------------------ | -------------------------------------------- | ------------------------------------------------------------------------------------------------------------- | -------------------------------------------------------------------------------------------- |
| Live trigger suite | Whether a skill fires for a labeled prompt   | One Claude Sonnet run: 143 prompts, precision `0.94`, recall `0.85`; 4 false positives and 11 false negatives | Correct task completion, Codex parity, repeat stability, or user outcomes                    |
| Synthetic A/B      | Workflow behavior with mocked Roboflow tools | 16 runs at `N=1` per cell: 1 supported, 6 mixed/parity, 1 loss                                                | Live model quality, market advantage, or production behavior                                 |
| B1 CV fixture      | One detection/counting workflow record       | Post-training result on 11 private test images                                                                | Conveyor equivalence, broad transfer, production readiness, or a controlled plugin advantage |

The honest current summary is: Sentinel has evidence for routing and a narrow detection/process path; broad live end-to-end coverage remains pending.

## Route fixtures

| ID  | Problem                                                | Route                 | Status             | Material limit                                                                      |
| --- | ------------------------------------------------------ | --------------------- | ------------------ | ----------------------------------------------------------------------------------- |
| B1  | Aerial vehicle counting used as a conveyor-count proxy | `detect-and-analyze`  | Measured fixture   | 11 private test images; proxy equivalence unverified; no controlled plain-agent run |
| B2  | PPE flagging                                           | `classify-or-flag`    | Specification only | Live measurements pending                                                           |
| B3  | Shopper dwell tracking                                 | `track-and-count`     | Specification only | Live RTSP, identity, privacy, and latency evidence pending                          |
| B4  | Serial-number extraction                               | `read-text`           | Specification only | Live field-accuracy evidence pending                                                |
| B5  | Crack-width measurement                                | `segment-and-analyze` | Specification only | Calibration and live physical-error evidence pending                                |

- [B1 — Conveyor / aerial vehicle count](b1-conveyor-detect.md)
- [B2 — PPE compliance](b2-classify-or-flag.md)
- [B3 — Shopper tracking](b3-track-in-video.md)
- [B4 — OCR extraction](b4-read-text-ocr.md)
- [B5 — Measurement](b5-measure-in-image.md)
- [Synthetic A/B](ab-plugin-vs-plain.md)
- [Annotated A/B transcripts](ab-transcripts.md)

## Synthetic A/B interpretation

The A/B compares a plugin arm with a plain Claude Code arm against the same mocked tool surface. It measures process choices such as eval definition, tool calls, spend discipline, and overclaims. The matrix uses one repeat per cell, ran on a developer machine with known configuration contamination, and has no completed live capability confirmation. One cell was a registered win, one was a loss, and most were mixed.

Use it to form hypotheses and regression checks. Do not use it to claim that Sentinel produces better models, universally prevents blind spend, or outperforms a careful human or agent.

## B1 interpretation

B1 is the only committed route fixture with measured CV results. Its private dataset and small test split prevent independent reproduction from repository files alone. The result shows that a measurement record exists for one path; it does not validate all detection domains or any other modality.

## Reproduction entry points

Claude local plugin invocation:

```bash
git clone https://github.com/Borda/vision-delivery
cd vision-delivery
claude --plugin-dir . "Count vehicles in this overhead camera view."
```

The first live Roboflow MCP action may open the host sign-in flow when the host or account requires authorization; an existing authorized session may need no prompt. No credential environment variable is part of plugin setup.

Plain comparison invocation:

```bash
claude "Count vehicles in this overhead camera view."
```

Use the same host/model version, cold prompt, credentials, fixture, tool permissions, and clean configuration. Record failed and refused runs, not only successful transcripts. Never expose private data or keys in published evidence.

## Promotion gate

A pending route becomes “proven” only when its exact claim has:

1. a versioned representative fixture or study,
2. a clean environment and exact command,
3. repeated runs or a justified statistical design,
4. committed raw results and failure cases,
5. an explicit comparator where an advantage is claimed,
6. security, privacy, cost, and domain limitations,
7. executable artifact acceptance rather than instruction-presence checks.

See [Support, Scope, and Evidence](../support-and-scope.md) for the public support tiers.
