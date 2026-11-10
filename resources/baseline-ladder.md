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

1. Take the frozen acceptance target and the independently labeled gold images (10–40 is enough for a first look; say how small it is). The per-object count metrics need at least 20 images with labeled objects; with fewer, target `exact_count_rate`.
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

- `--task count` reports `count_mae`, `exact_count_rate`, `catch_rate` (printed as "per-image count agreement": labeled objects matched by each image's count, capped at the label; it is not object-level recall), and `over_count_rate`.
- `--task flag` reports `catch_rate` (recall), `false_alarm_rate`, `precision`, and `accuracy`.
- An error metric (`count_mae`, `over_count_rate`, `false_alarm_rate`) takes a maximum (`lte`); every other metric takes a minimum (`gte`). The scorer refuses a target that points the wrong way or that every result would meet (a minimum of 0%, a maximum of 100%).
- Count `catch_rate` does not penalize over-counting; when the predictions exceed the labels the printed line says by how much. Pair it with `over_count_rate`, or target `exact_count_rate`.
- In explore mode, pass the target inline with `--metric/--comparator/--threshold`. In deliver mode, pass `--acceptance`; the file's metric, comparator, and threshold win and the evidence records its SHA-256.
- Every gold image needs a prediction: a missing prediction gives `NO VERDICT`. Predictions for images not in the gold file fail the run (exit 2).

The printed line gives the target metric's numerator and denominator, its point estimate, and a 95% interval. Rates over a simple count (every flag metric and `exact_count_rate`) use the Wilson score interval; the other count metrics use a seeded bootstrap over images, so the same files always print the same line. The verdict compares the whole interval with the target:

| Verdict        | Meaning                                                                                             |
| -------------- | --------------------------------------------------------------------------------------------------- |
| `PASS`         | The whole interval meets the target.                                                                |
| `BELOW-TARGET` | The whole interval misses the target.                                                               |
| `INCONCLUSIVE` | The interval includes the target. Label more images, or treat the result as not yet proven.         |
| `NO VERDICT`   | Refusal: a gold image has no prediction, the denominator is zero, or too few cases stand behind it. |

"Too few" means fewer than 5 cases for a Wilson metric and fewer than 20 images for a bootstrap metric (`count_mae`, count `catch_rate`, `over_count_rate`). A bootstrap metric also gets `NO VERDICT` when every image gives the same result, because resampling identical images shows no spread; score `exact_count_rate` on that sample instead.

Only `PASS` counts as a passed acceptance. A refusal still prints its reason and exits 0; unusable input, or an evidence file that cannot be written, exits 2. Example, 34 of 40 real cases caught against a target of at least 80%:

```text
Real cases caught: 34 of 40 real cases (85%, 95% interval 71% to 93%); target >= 80%: INCONCLUSIVE. The 95% interval includes the target: label more images to settle it, or treat the result as not yet proven. Missing predictions: 0.
```
