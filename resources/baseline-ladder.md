# Baseline Ladder

"Measure a baseline before training" needs a baseline the user can actually run. This ladder gives each rung a stable candidate category, what it costs, and how its output reaches the scorer. It names categories, not model IDs. Current IDs, licenses, and provider operations still come from upstream (`roboflow-platform-lookup.md`).

Climb one rung at a time. Stop at the first rung that clears the frozen acceptance target.

| Rung | Candidate category                                           | Accounts / cost                                    | Typical first use                                         |
| ---- | ------------------------------------------------------------ | -------------------------------------------------- | --------------------------------------------------------- |
| 0    | The host model's own vision, prompted per image              | none beyond the current session                    | whole-image flags, small counts, "is the signal visible?" |
| 1    | Open-vocabulary detector or segmenter, run hosted or locally | upstream-sourced; local run needs a pinned install | common objects named in plain words                       |
| 2    | Public pretrained model or dataset relevant to the domain    | upstream-sourced; license review required          | domain objects already covered by public work             |
| 3    | Fine-tune a relevant checkpoint on the user's labeled images | paid or compute cost; host-gated action brief      | custom or fine-grained targets the lower rungs miss       |

## Rung 0 — zero accounts, first number in minutes

Rung 0 gives a novice a measured number before any sign-in, upload, or spend.

1. Take the frozen acceptance target and the independently labeled gold images (10–40 is enough for a first look; say how small it is).
2. Look at each gold image with the host model's vision. Answer only the business question: a count, or a yes/no flag. Do not look at the gold label first.
3. Write one JSON line per image to `.vision-delivery/pred-rung0-<session>.jsonl`, for example `{"image": "frame_014.jpg", "count": 3}` or `{"image": "frame_014.jpg", "flag": true}`.
4. Score it with `resources/scripts/score_baseline.py` (below) and report the plain-language line it prints.

Rung 0 limits: no boxes or masks, no latency claim, and no production path. It is a diagnostic baseline. It answers "is this easy, borderline, or hard?" and "is the signal visible at all?". A rung 0 pass still needs a runnable artifact before delivery. Rung 0 output is never gold and never a pseudo-label for the acceptance split.

## Rungs 1–3

- **Rung 1.** Ask upstream for current open-vocabulary candidates and their input contract. Run on the same gold images and convert detections to the same count/flag JSONL with the frozen class/region/confidence policy.
- **Rung 2.** Ask upstream for relevant public models or datasets. Review license and domain relevance before use, then score on the same gold images.
- **Rung 3.** Only when rungs 0–2 miss the target and the misses look learnable. Training is a paid, state-changing action: record the action brief and follow the host execution gate in `roboflow-platform-lookup.md`.

Every rung is scored on the same gold file with the same frozen target. A higher rung must beat the lower one by enough to justify its added cost, and the report must say so.

## Scoring

```bash
python3 "/absolute/plugin/root/resources/scripts/score_baseline.py" \
    --gold "/absolute/project/.vision-delivery/gold-<session>.jsonl" \
    --pred "/absolute/project/.vision-delivery/pred-rung0-<session>.jsonl" \
    --task count \
    --metric count_mae --comparator lte --threshold 0.5 \
    [--acceptance "/absolute/project/.vision-delivery/acceptance-<revision>.json"] \
    [--evidence-out "/absolute/project/.vision-delivery/baseline-rung0-<session>.json"]
```

- `--task count` reports `count_mae`, `exact_count_rate`, `catch_rate` (share of real objects counted, capped per image), and `over_count_rate`.
- `--task flag` reports `catch_rate` (recall), `false_alarm_rate`, `precision`, and `accuracy`.
- In explore mode, pass the target inline with `--metric/--comparator/--threshold`. In deliver mode, pass `--acceptance`; the file's metric, comparator, and threshold win and the evidence records its SHA-256.
- Images missing from the predictions count as wrong (count 0 or flag false). Predictions for images not in the gold file fail the run.
