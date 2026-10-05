# First baseline in five minutes

This example walks through Sentinel's explore mode on a counting task: lock a target, score a rung 0 baseline, read the verdict. It needs no Roboflow account.

> **The label files here are synthetic placeholders.** They show the file format and let you run the scorer immediately. They are not a benchmark result, and no transcript in this folder comes from a real session. A recorded end-to-end run on public, licensed images is still pending; see "Contributing a real run" below.

## 1. Try the scorer on the placeholder files

From the repository root:

```bash
python3 resources/scripts/score_baseline.py \
    --gold examples/first-baseline/gold.example.jsonl \
    --pred examples/first-baseline/pred-rung0.example.jsonl \
    --task count --metric catch_rate --comparator gte --threshold 0.8
```

Expected first line:

```text
Real cases caught: 62% on 5 images (target >= 80%): BELOW-TARGET. Missing predictions: 1.
```

`frame_005.jpg` has no prediction, so it counts as zero found. That is deliberate: a missing answer is a miss.

## 2. Do it on your own images with Sentinel

1. Put 10–40 representative images in a folder you are allowed to use.

2. Label them yourself, independently of any model: one line per image in `gold.jsonl`, `{"image": "<file>", "count": <n>}` or `{"image": "<file>", "flag": true|false}`.

3. Start a session and describe the job, for example:

   ```text
   Count pallets in the images in ./frames. My counts are in ./frames/gold.jsonl.
   A missed pallet is worse than a double count. Explore mode, please.
   ```

4. Sentinel locks the target (for example "catch at least 80% of pallets") before looking at any result. It then looks at each image itself, writes `pred-rung0-<session>.jsonl`, and runs the same scorer.

5. Read the verdict. `PASS` on a small sample means "worth a deliver-mode proof", not "production-ready". `BELOW-TARGET` means Sentinel climbs the [baseline ladder](../../resources/baseline-ladder.md) or tells you what capture or labels would help.

## Contributing a real run

A recorded run is the most useful evidence this project can get. If you run this flow on images you may publish under an open license, open an [outcome report](https://github.com/Borda/vision-delivery/issues/new?template=outcome-report.yml) with the image source and license, `gold.jsonl`, the prediction file, the scorer output, and the session transcript with private details removed.
