# vision-delivery

Claude Code plugin — solve a CV problem end-to-end, then get an honest build-vs-buy estimate.

## What it does

Two modes:

- **Problem-solver** (`@cv-problem-solver`) — cold prompt → eval-passing model → deployable Roboflow Workflow
- **Deployment consultant** (`@deployment-consultant`) — fully-loaded DIY cost vs managed, with cited sources

## Skills

| Skill                       | Trigger                                | Eval metric             |
| --------------------------- | -------------------------------------- | ----------------------- |
| `detect-and-analyze`        | count / detect objects                 | mAP@50, count-MAE       |
| `classify-or-flag`          | pass/fail, image-level verdict         | F1, precision, recall   |
| `track-and-count`           | track identity, dwell time, line-cross | MOTA, dwell MAE         |
| `read-text`                 | OCR, serial numbers, barcodes          | CER, field match rate   |
| `segment-and-analyze`       | pixel masks, area measurement          | mAP@50(mask), IoU       |
| `recognize-pose-or-gesture` | keypoints, gesture, posture            | OKS mAP, gesture recall |

## Benchmarks

Plugin vs plain-agent comparison across 5 problems — same cold prompt, measurable delta.

| #   | Problem                 | Skill                 | Eval defined | Deploy ready |
| --- | ----------------------- | --------------------- | :----------: | :----------: |
| B1  | Conveyor count          | `detect-and-analyze`  |      ✅      |      ✅      |
| B2  | PPE compliance          | `classify-or-flag`    |      ⬜      |      ⬜      |
| B3  | Shopper tracking (RTSP) | `track-and-count`     |      ⬜      |      ⬜      |
| B4  | Serial number OCR       | `read-text`           |      ⬜      |      ⬜      |
| B5  | Crack width measurement | `segment-and-analyze` |      ⬜      |      ⬜      |

→ [Full benchmark docs](benchmarks/index.md)

## Install

```bash
claude plugin install vision-delivery
export ROBOFLOW_API_KEY=<your-key>
```

Get your key at [app.roboflow.com/settings/api](https://app.roboflow.com/settings/api). Never paste it in chat.
