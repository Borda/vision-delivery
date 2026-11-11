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

Rung 0 gives a novice a measured number before any sign-in, upload, or spend. The labels come first, the labels are not given to the predictor, and the prediction file is frozen before this scoring run.

1. Take the frozen acceptance target and the independently labeled gold images (10–40 is enough for a first look; say how small it is). The per-object count metrics need at least 20 images with labeled objects; with fewer, target `exact_count_rate`.
2. If the human has no gold file yet, the human labels with `resources/scripts/label_gold.py` (below): they run it in a terminal (it refuses piped input), or they tell you each label in chat and you record it with `--record <image>=<value>`. Labels recorded with `--record` are marked as such, and the scorer's line says so. Never propose a label and never write the label file by hand. Keep the label file inside the project folder and outside the image folder, for example `.vision-delivery/gold-<session>.jsonl`; for a label file outside `.vision-delivery/`, pass `--ledger` with the project ledger. After each write the helper says whether the set is large enough for a verdict.
3. Get the image list with `label_gold.py --list-images`. It prints the labeled image paths and no label values. Do not open the gold file.
4. Run the prediction in an isolated subagent through the host's subagent tool. Give it only the image paths from step 3, the business question with the frozen class and region policy, the output path `.vision-delivery/pred-rung0-<session>.jsonl`, and the line format. Never give it the gold file path, its contents, any label value, or the folder that holds the gold file. Tell it to open only the listed images, to answer only the business question for each image (a count, or a yes/no flag), and to write one JSON line per image with the file name as the image name, for example `{"image": "frame_014.jpg", "count": 3}`, `{"image": "frame_014.jpg", "flag": true}`, or, for a text task, `{"image": "frame_014.jpg", "text": "SN-4471"}`.
5. As soon as the subagent returns, freeze its file with `resources/scripts/freeze_predictions.py --predictor isolated-subagent` (below), before the scorer or anything else opens the gold file. When the freeze refuses because labels changed after predictions existed, stop and tell the user; do not rerun it with `--acknowledge-label-change` unless the user asks, and then report the result as not independent.
6. Score with `score_baseline.py --frozen-ledger <ledger>` (below) and report the plain-language line it prints, all of it. The scorer refuses a prediction file that was not frozen, or a gold file that changed after the freeze.

No subagent tool on this host: tell the user that rung 0 runs in the same session that holds the labels, so independence is not enforced for this run. Still do not open the gold file before predicting, freeze with `--predictor same-session`, and score with `--frozen-ledger`. The scorer's line then says that independence was not enforced, and the report must say so too.

After a freeze the label file is closed: `label_gold.py` refuses to add or change a label in it, and the freeze helper refuses the same file after a hand edit. To label more images after `INCONCLUSIVE`, start a new label file (copying the frozen lines into it is fine), then run steps 3–6 again on all of its images. A copied label whose value differs from the value an earlier freeze recorded for the same image name is counted at the next freeze, which then refuses.

> Limits: a freeze shows that the prediction file and the label file were fixed before this scoring run, and the scorer's line says whether labels changed after an earlier freeze or after the prediction file was written. It does not show that the labels are independent of the predictions. The helpers, the predictor, and the scorer run under one account on the user's machine, so a predictor that opens the label file is not detected. A ledger row written by hand is not detected. An earlier scoring run without the freeze leaves no trace. Renaming image files defeats the per-image label check, and file times can be changed. An agent can call `label_gold.py --record`, so labels entered that way are marked, not blocked, and a pseudo-terminal defeats the helper's terminal check. The isolated-subagent step has not yet been recorded in a live session.

Rung 0 limits: no boxes or masks, no latency claim, and no production path. It is a diagnostic baseline. It answers "is this easy, borderline, or hard?" and "is the signal visible at all?". A rung 0 pass still needs a runnable artifact before delivery. Rung 0 output is never gold and never a pseudo-label for the acceptance split.

## Rungs 1–3

- **Rung 1.** Ask upstream for current open-vocabulary candidates and their input contract. Run on the same gold images and convert detections to the same count/flag JSONL with the frozen class/region/confidence policy, using `resources/scripts/detections_to_counts.py` (below).
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
    [--evidence-out "/absolute/project/.vision-delivery/baseline-rung0-<session>.json"] \
    [--frozen-ledger "/absolute/project/.vision-delivery/ledger.jsonl"]
```

- `--task count` reports `count_mae`, `exact_count_rate`, `catch_rate` (printed as "per-image count agreement": labeled objects matched by each image's count, capped at the label; it is not object-level recall), and `over_count_rate`.
- `--task flag` reports `catch_rate` (recall), `false_alarm_rate`, `precision`, and `accuracy`.
- `--task text` scores one string per image (`{"image": "<name>", "text": "<string>"}`) and reports `exact_match_rate` (images whose predicted string equals the label) and `char_error_rate` (inserted, deleted, and substituted characters over all labeled characters; it can exceed 100%). Strings are compared exactly: no trimming, no case folding, no Unicode normalization. Enter labels and write predictions in the frozen normalized form. A record with several fields needs one label file per field. A value may hold at most 10,000 code points and no lone surrogate, and a run whose label and prediction lengths multiply to more than 200,000,000 character comparisons in total is refused: split long documents into fields.
- An error metric (`count_mae`, `over_count_rate`, `false_alarm_rate`, `char_error_rate`) takes a maximum (`lte`); every other metric takes a minimum (`gte`). The scorer refuses a target that points the wrong way or that every result would meet (a minimum of 0%, a maximum of 100%).
- Count `catch_rate` does not penalize over-counting; when the predictions exceed the labels the printed line says by how much. Pair it with `over_count_rate`, or target `exact_count_rate`.
- In explore mode, pass the target inline with `--metric/--comparator/--threshold`. In deliver mode, pass `--acceptance`; the file's metric, comparator, and threshold win and the evidence records its SHA-256.
- Every gold image needs a prediction: a missing prediction gives `NO VERDICT`. Predictions for images not in the gold file fail the run (exit 2).
- `--frozen-ledger` makes the scorer require a successful `predictions_frozen` ledger row holding the SHA-256 of both the prediction file and the gold file. Both input files are checked for shape first, so a malformed file is reported as malformed. A prediction file that was never frozen, or a gold file that changed after the freeze, exits 2 before anything is scored. The printed line then adds plain sentences: that both files were fixed before this scoring run and who the freeze declares wrote the predictions; "this is not an independent measurement" when labels changed after an earlier freeze or after the prediction file was written; and how the labels were entered when that was through `--record` or not through the labeling helper. The machine record gains a `predictions_frozen` block with `event_id`, `frozen_at`, `label_set`, `pred_sha256`, `gold_sha256`, `predictor_declared`, `label_entry`, `labels_changed_after_freeze`, `labels_changed_after_predictions`, `ledger_is_project_ledger`, and `independent` (true only for an isolated subagent with no label change). A ledger that is not `.vision-delivery/ledger.jsonl` gets a warning. Without the option the scorer behaves as before.

The printed line gives the target metric's numerator and denominator, its point estimate, and a 95% interval. Rates over a simple count (every flag metric, `exact_count_rate`, and `exact_match_rate`) use the Wilson score interval; the other count metrics and `char_error_rate` use a seeded bootstrap over images, so the same files always print the same line. The verdict compares the whole interval with the target:

| Verdict        | Meaning                                                                                             |
| -------------- | --------------------------------------------------------------------------------------------------- |
| `PASS`         | The whole interval meets the target.                                                                |
| `BELOW-TARGET` | The whole interval misses the target.                                                               |
| `INCONCLUSIVE` | The interval includes the target. Label more images, or treat the result as not yet proven.         |
| `NO VERDICT`   | Refusal: a gold image has no prediction, the denominator is zero, or too few cases stand behind it. |

"Too few" means fewer than 5 cases for a Wilson metric and fewer than 20 images for a bootstrap metric (`count_mae`, count `catch_rate`, `over_count_rate`, and `char_error_rate`, which counts images with a non-empty label). A bootstrap metric also gets `NO VERDICT` when every image gives the same result, because resampling identical images shows no spread; score `exact_count_rate` (text: `exact_match_rate`) on that sample instead.

Only `PASS` counts as a passed acceptance. A refusal still prints its reason and exits 0; unusable input, or an evidence file that cannot be written, exits 2. Example, 34 of 40 real cases caught against a target of at least 80%:

```text
Real cases caught: 34 of 40 real cases (85%, 95% interval 71% to 93%); target >= 80%: INCONCLUSIVE. The 95% interval includes the target: label more images to settle it, or treat the result as not yet proven. Missing predictions: 0.
```

## Detections to counts

Rungs 1 to 3 of a counting or flagging task produce detections, and the scorer reads counts or flags. Convert with the policy written down before the run, never tuned on the gold file afterwards:

```bash
python3 "/absolute/plugin/root/resources/scripts/detections_to_counts.py" \
    --detections "/absolute/project/.vision-delivery/detections-rung1-<session>.jsonl" \
    --out "/absolute/project/.vision-delivery/pred-rung1-<session>.jsonl" \
    --task count \
    --class "pallet" [--class "crate"] \
    --min-confidence 0.5 \
    [--region "x_min,y_min,x_max,y_max"]
```

- Input is one JSON line per image: `{"image": "<name>", "predictions": [{"class": "<name>", "confidence": 0.91, "x": 120.5, "y": 80}, ...]}`, where `x` and `y` are the box centre. An image with no detection still needs its line, with an empty list.
- `--class` and `--min-confidence` have no default. A detection counts when its class equals a given name exactly, its confidence is at least the minimum, and, with `--region`, its centre lies inside the rectangle (edges included).
- `--task flag` writes true when at least one detection counts.
- It writes one line per input image and never a line for an image the input lacks, so the scorer still reports a missing prediction. It refuses malformed input and never replaces an existing output file.
- It prints one JSON summary: images, detections read and counted, how many were dropped by class, confidence, and region, and the policy used. Put that policy in the result report.
- Changing the class list, the confidence, or the region after seeing the score is tuning on the gold set: report every policy tried, and confirm the chosen one on fresh labeled images.

## Labeling and freezing

The person enters every gold label; the labeling helper never proposes one and never reads a model output.

```bash
python3 "/absolute/plugin/root/resources/scripts/label_gold.py" \
    --images "/absolute/project/frames" \
    --labels "/absolute/project/.vision-delivery/gold-<session>.jsonl" \
    --task count \
    --ledger "/absolute/project/.vision-delivery/ledger.jsonl" \
    [--record "frame_014.jpg=3"] [--relabel] [--status] [--list-images]
```

- With no `--record`, `--status`, or `--list-images` it is interactive: it asks for each unlabeled image in name order and saves every answer at once, so rerunning continues where it stopped. `s` skips an image, `q` stops. It needs a terminal and refuses piped input.
- `--record <image>=<value>` records labels the person gave in chat, one write per call (repeat the option for several). The image is its file name in the folder, or its absolute path.
- The ledger is `--ledger`, or `ledger.jsonl` in the `.vision-delivery` folder that holds the label file; any other label file needs `--ledger`. The working directory is never used. The label file must sit inside the project folder.
- Every write appends a `labels_recorded` ledger row with the file's digest, a short digest per label, and how the labels were entered (`interactive-terminal` or `record-option`), never a label value. When that row cannot be written, the label file is put back as it was.
- A count is a whole number of zero or more. A flag is yes or no (`y`/`n`, `true`/`false`, `1`/`0`).
- With `--task text` a label is the text itself, kept exactly as typed (spaces and letter case included), up to 10,000 code points (an accented letter typed as a letter plus a combining mark counts as two). Interactive commands are then `:skip`, `:quit`, and `:empty` (an empty label), because `s` and `q` are valid text; the helper prints each saved value in quotes so a stray space shows. With `--record`, the value is everything after the `=` that follows the image name, so it may hold `=` or be empty; when more than one `=` split names an image in the folder, the record is refused and those images are labeled interactively. For a text task the helper's messages name the image only, never a label value, and the file it writes escapes the Unicode line separators U+2028, U+2029, and U+0085.
- An image must be a regular file directly in the image folder. Subfolders, hidden files, symbolic links, and files outside the folder are refused, as is a malformed value.
- An existing label changes only with `--relabel`; recording the same value again changes nothing.
- The file is written atomically, one line per image in name order, and read back with the scorer's own loader.
- After each write it says, per metric, whether the set is large enough for the scorer to give a verdict, using the scorer's minimums; for a flag task it also gives real cases and clean images.
- `--list-images` prints the labeled image paths and never a label value. `--status` prints the floor report and whether the label file is frozen.
- Once the ledger holds a prediction freeze for this label file, every write is refused with the reason.

Freeze the prediction file before scoring:

```bash
python3 "/absolute/plugin/root/resources/scripts/freeze_predictions.py" \
    --task count \
    --gold "/absolute/project/.vision-delivery/gold-<session>.jsonl" \
    --pred "/absolute/project/.vision-delivery/pred-rung0-<session>.jsonl" \
    --predictor isolated-subagent \
    --session "<session>" --skill "detect-and-analyze" \
    --ledger "/absolute/project/.vision-delivery/ledger.jsonl"
```

- It checks that both files are valid label files for the task and that every prediction names a gold image, then records a `predictions_frozen` row through the ledger helper (`ledger-protocol.md`), which hashes both files itself. It prints one JSON line with both digests, the event ID, and the count of missing predictions.
- Rerunning it on the same files changes nothing. It always refuses a label file that an earlier freeze recorded with other content. It also refuses when an image's label differs from the label an earlier freeze in this ledger recorded for the same image name, or when the labeling helper wrote the label file after the prediction file was written (or the file changed since that write). `--acknowledge-label-change` records the freeze anyway with these facts, and the scorer then says the result is not independent.
- Without `--ledger` it uses `ledger.jsonl` in the `.vision-delivery` folder that holds the gold file, as the labeling helper does.
- `--predictor same-session` is for a host with no subagent tool; the ledger row and the scorer's line then say that independence was not enforced.
