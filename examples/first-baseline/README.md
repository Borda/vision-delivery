# First baseline in five minutes

This example walks through Sentinel's explore mode on a counting task: lock a target, score a rung 0 baseline, read the verdict. It needs no Roboflow account.

> **The label files here are synthetic placeholders.** They show the file format and let you run the scorer immediately. They are not a benchmark result, and no transcript in this folder comes from a real session. A recorded end-to-end run on public, licensed images is still pending; see "Contributing a real run" below.

## 1. Try the scorer on the placeholder files

From the repository root:

```bash
python3 resources/scripts/score_baseline.py \
    --gold examples/first-baseline/gold.example.jsonl \
    --pred examples/first-baseline/pred-rung0.example.jsonl \
    --task count --metric catch_rate --comparator gte --threshold 0.85
```

Expected first line:

```text
Per-image count agreement: 42 of 47 labeled objects (89%, 95% interval 81% to 96%); target >= 85%: INCONCLUSIVE. The 95% interval includes the target: label more images to settle it, or treat the result as not yet proven. This number does not penalize over-counting: the predictions hold 2 counts beyond the labels (see over_count_rate). Missing predictions: 0.
```

The point estimate is above 85%, but 24 images cannot rule out a true rate below 85%, so the verdict is `INCONCLUSIVE`, not `PASS`. "Per-image count agreement" compares each image's count with its label, capped at the label. It does not check which object was found, so it is not object-level recall.

Every gold image needs a prediction. Delete the last line of the prediction file and run again: the scorer refuses instead of scoring the gap as a miss.

```text
Per-image count agreement: 40 of 47 labeled objects (85.1%, 95% interval 70.3% to 95.9%); target >= 85.0%: NO VERDICT. No verdict because 1 of 24 gold images has no prediction. This number does not penalize over-counting: the predictions hold 2 counts beyond the labels (see over_count_rate). Missing predictions: 1.
```

The per-object count metrics (`catch_rate`, `over_count_rate`, `count_mae`) need at least 20 images, because their interval comes from resampling images. With fewer, or when every image gives the same result, score `exact_count_rate` ("images counted exactly right"), which needs 5.

## 2. Do it on your own images with Sentinel

1. Put your representative images in a folder you are allowed to use: 10 or more for a yes/no flag, 20 or more with objects for a count. The images go to your host model, like any image you attach to a chat.

2. Label them yourself, independently of any model. The labeling helper asks for one label per image, saves each answer at once, and never suggests a label; stop with `q` and rerun to continue. From the repository root:

   ```bash
   python3 resources/scripts/label_gold.py \
       --images /path/to/frames --labels /path/to/project/.vision-delivery/gold.jsonl --task count
   ```

   Run it in a terminal: it refuses piped input. Because the label file sits in the project's `.vision-delivery` folder, every write is recorded in that folder's `ledger.jsonl`, whatever folder you run the command from; for a label file elsewhere in the project, add `--ledger /path/to/project/.vision-delivery/ledger.jsonl`. After each answer it says whether the set is large enough for a verdict yet. You can also tell Sentinel each label in chat and it records them with the same helper's `--record` option; the scorer then says the labels were entered that way. Keep the label file outside the image folder. It holds one line per image, `{"image": "<file>", "count": <n>}` or `{"image": "<file>", "flag": true|false}`.

3. Start a session and describe the job, for example:

   ```text
   Count pallets in the images in ./frames. My counts are in ./.vision-delivery/gold.jsonl.
   A missed pallet is worse than a double count. Explore mode, please.
   ```

4. Sentinel locks the target (for example "per-image counts agree on at least 80% of labeled pallets") before looking at any result. A separate subagent that is never given your labels looks at each image and writes `pred-rung0-<session>.jsonl`. Sentinel freezes that file in the project ledger before it opens your labels, then runs the same scorer, which refuses predictions or labels that changed after the freeze. Limits: a freeze shows that the prediction file and the label file were fixed before this scoring run, and the scorer's line says whether labels changed after an earlier freeze or after the prediction file was written. It does not show that the labels are independent of the predictions. The helpers, the predictor, and the scorer run under one account on the user's machine, so a predictor that opens the label file is not detected. A ledger row written by hand is not detected. An earlier scoring run without the freeze leaves no trace. Renaming image files defeats the per-image label check, and file times can be changed. An agent can call `label_gold.py --record`, so labels entered that way are marked, not blocked, and a pseudo-terminal defeats the helper's terminal check. The isolated-subagent step has not yet been recorded in a live session.

5. Read the verdict. The scorer compares the whole 95% interval with the target, not the point estimate.

   - `PASS`: the whole interval meets the target. On a small sample it means "worth a deliver-mode proof", not "production-ready".
   - `INCONCLUSIVE`: the interval includes the target. Label more images, or treat the result as not yet proven.
   - `BELOW-TARGET`: the whole interval misses the target. Sentinel climbs the [baseline ladder](../../resources/baseline-ladder.md) or tells you what capture or labels would help.
   - `NO VERDICT`: the scorer refused, because an image has no prediction or too few cases stand behind the number (5 for most metrics, 20 images for the per-object count metrics).

## Contributing a real run

A recorded run is the most useful evidence this project can get. If you run this flow on images you may publish under an open license, open an [outcome report](https://github.com/Borda/vision-delivery/issues/new?template=outcome-report.yml) with the image source and license, `gold.jsonl`, the prediction file, the scorer output, and the session transcript with private details removed.
