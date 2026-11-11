# Recorded golden runs

This folder is empty until a real run is packed. It will hold one recorded golden run per flagship route: dataset provenance, gold labels, predictions, scorer output and evidence, and a redacted session transcript. The synthetic self-check is a helper test, not a golden run. A packed result can be PASS, INCONCLUSIVE, BELOW-TARGET, or NO VERDICT; packing records evidence rather than certifying success.

Choose a public dataset with an open licence that permits redistribution of the labels you will publish. Check the actual terms, attribution and share-alike obligations, and record the public source, licence URL, SPDX identifier and citation. The packer uses a conservative offline allowlist of Creative Commons attribution/share-alike and CC0 licences, open data licences, MIT, Apache-2.0 and BSD licences; it refuses unknown identifiers and restrictive licences. It does not fetch URLs or decide whether a particular annotation is legally redistributable. Use at least 20 representative images with objects for count, or 10 for flag, as described in [the first baseline](../first-baseline/README.md). Small samples can still produce NO VERDICT. Text labels use the scorer's exact code-point comparison; choose a representative set and record any normalization policy.

Keep images outside this folder. Create a dataset JSON file containing non-empty strings `name`, `source_url`, `license_spdx`, `license_url`, `retrieved_on` and `citation`, a positive integer `image_count`, and `images_committed: false`. Both URLs must use HTTPS. Use a real calendar date in `YYYY-MM-DD` form. Record the image count of the selected sample. Labels and predictions must name the same image files; use names rather than private absolute paths. Each JSON Lines row is `{"image": "frame.png", "count": 2}`, `{"image": "frame.png", "flag": true}`, or `{"image": "frame.png", "text": "visible text"}`.

Follow this order for each route:

1. Before any prediction, label the selected images yourself in a terminal with `python3 resources/scripts/label_gold.py --images /path/to/images --labels /path/to/project/.vision-delivery/gold.jsonl --task count` (use `flag` or `text` for those routes). Keep labels outside the image folder. Record the dataset metadata and retain the project ledger.
2. Run Sentinel in explore mode. State the task and target, then have the predictor inspect the images without access to your gold labels. Preserve the prediction file and session transcript. Follow the first-baseline workflow to freeze predictions before opening the labels.
3. Run `python3 resources/scripts/score_baseline.py --gold /path/to/gold.jsonl --pred /path/to/pred.jsonl --task count --metric catch_rate --comparator gte --threshold 0.85`. Read the first line, including any sample-size limits. When checking the live freeze, also supply `--frozen-ledger /path/to/project/.vision-delivery/ledger.jsonl`.
4. Review the transcript for private names and content, then pack the files with the helper below. The packer runs the scorer itself on a redacted snapshot; it never accepts an earlier scorer output as authoritative. Optional `--ledger` preserves a redacted copy as context; packaging does not validate that ledger's historical freeze claims. Optional `--acceptance` supplies an acceptance JSON file, whose target must agree with the explicit scoring flags.

From the repository root, replace every placeholder with your own route and files:

```bash
python3 scripts/package_golden_run.py pack \
    --route <route-id> \
    --dataset-file /path/to/dataset.json \
    --gold /path/to/gold.jsonl \
    --pred /path/to/pred.jsonl \
    --task count --metric catch_rate --comparator gte --threshold 0.85 \
    --transcript /path/to/session.txt \
    --ledger /path/to/project/.vision-delivery/ledger.jsonl
```

The helper prints the new folder and manifest SHA-256. The default destination is `examples/golden-run/<route-id>/<YYYY-MM-DD>-<n>/`, using the smallest unused positive number. Existing runs are never overwritten. Preparation and scoring happen in temporary folders before publication by rename. A concurrent pack on the same route is refused while its route lock exists; after an interrupted process, inspect the destination before removing a stale `.pack-lock` directory.

Only `dataset.json`, `gold.jsonl`, `pred.jsonl`, `scorer-output.txt`, `scorer-evidence.json`, `transcript.txt` (or `transcript.jsonl`), optional `ledger.jsonl` and `acceptance.json`, and `golden-manifest.json` belong in the reviewable folder. No images or tokens are committed. Rung 0 needs no Roboflow account; an account is needed only if your chosen later rung requires it. Masking replaces local paths, login path segments and the current host using the publisher's Masker. JSON and JSON Lines are decoded before checks, and credentials, surviving email/IPv4 addresses, non-UTF-8 input and files over 250 KB are refused. Review the result yourself: mechanical checks cannot recognize every private name or judge label independence.

Verify the printed folder with `python3 scripts/package_golden_run.py verify examples/golden-run/<route-id>/<YYYY-MM-DD>-<n>`. Verification checks the manifest identity, every file's SHA-256 and byte size, redaction checks, and the absence of unlisted files or directories. It runs the repository scorer again on the packed labels and predictions with the recorded target, compares the printed first line, and compares evidence except for the new scoring timestamp. The manifest hash printed at pack time can be retained separately. Digests detect accidental edits; someone who changes both files and their manifest can create a new internally consistent bundle. Repository review and history record who changed it.

Gold labels and predictions were produced by the user's own session; this folder shows what was scored, not that the labels are independent of the predictions.

The live run, review, commit, and any `gh` write remain user-owned. This helper does not run a paid session, download data, stage files, commit, push, or write to GitHub. No real run is claimed here.
