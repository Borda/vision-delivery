# vision-delivery

Codex and Claude Code plugin — solve a CV task end-to-end, then get an honest project economics estimate.

`vision-delivery` adds an eval-first workflow around Roboflow MCP tools: it chooses the right CV modality, commits the success threshold before model search, measures a pretrained baseline before training, gates credit-spending actions on explicit confirmation, and keeps annotation, training, and deployment economics visible.

## What it does

Two modes:

- **Problem-solver** (`solve-cv-task`) — cold prompt → eval-passing model → deployable Roboflow Workflow
- **CV economics** (`estimate-economics`) — annotation, training, and deployment cost assumptions with cited deployment sources

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

B1 has measured evidence. B2-B5 define benchmark fixtures and acceptance criteria for the other skill routes.

| #   | Problem                 | Skill                 | Evidence        |
| --- | ----------------------- | --------------------- | --------------- |
| B1  | Conveyor count          | `detect-and-analyze`  | Measured        |
| B2  | PPE compliance          | `classify-or-flag`    | Fixture defined |
| B3  | Shopper tracking (RTSP) | `track-and-count`     | Fixture defined |
| B4  | Serial number OCR       | `read-text`           | Fixture defined |
| B5  | Crack width measurement | `segment-and-analyze` | Fixture defined |

→ [Full benchmark docs](benchmarks/index.md)

## Install

Install in either host, then make `ROBOFLOW_API_KEY` available to the host process that starts the Roboflow MCP server.

### For Codex

```bash
codex plugin marketplace add https://github.com/Borda/vision-delivery
codex plugin add vision-delivery@vision-delivery
export ROBOFLOW_API_KEY=your_key_here
```

### For Claude Code

```bash
claude plugin install https://github.com/Borda/vision-delivery
echo "ROBOFLOW_API_KEY=your_key_here" >> .env
echo ".env" >> .gitignore
```

Get your key at [app.roboflow.com/settings/api](https://app.roboflow.com/settings/api). Never paste it in chat.
