# Model Selection — shared tables

Skills reference these tables instead of duplicating them. Each skill adds only the modality-specific decision rules in its own SKILL.md.

Do not guess or invent `model_id` values — training fails silently on a wrong ID.

Roboflow platform lookup order:

1. Local Roboflow plugin skill `roboflow:training-and-evaluation`, if available.
2. MCP skill resource `roboflow://skills/training-and-evaluation/...`, if the client exposes MCP resources and the user is authenticated.
3. This file as a stable fallback only. Validate volatile model IDs before `models_train` or mark them unverified if validation is unavailable.

See `skills/_shared/roboflow-platform-lookup.md` for the full platform adapter table.

## Object Detection

**Decision tree — start at top, stop at first match:**

| Condition                               | Architecture      | model_id        |
| --------------------------------------- | ----------------- | --------------- |
| Class in COCO 80 + non-real-time        | RF-DETR Medium    | `rfdetr-medium` |
| Class in COCO 80 + real-time (\<100 ms) | RF-DETR Nano      | `rfdetr-nano`   |
| Non-COCO, ≤5 custom classes, first PoC  | Roboflow Rapid    | n/a (UI flow)   |
| Non-COCO, >5 classes or fine-grained    | RF-DETR fine-tune | `rfdetr-medium` |
| Edge hardware, latency critical         | YOLOv11 Nano      | `yolov11n`      |
| Best accuracy, no latency constraint    | RF-DETR Large     | `rfdetr-large`  |

**Exact model_id values — object detection:** `rfdetr-pico`, `rfdetr-nano`, `rfdetr-small`, `rfdetr-base`, `rfdetr-medium`, `rfdetr-large`, `rfdetr-xlarge`, `rfdetr-2xlarge`; `yolov11n`, `yolov11s`, `yolov11m`, `yolov11l`, `yolov11x`; `yolo26n`, `yolo26s`, `yolo26m`, `yolo26l`, `yolo26x`.

## COCO 80 Coverage

Skip Universe search when the class is here — use COCO-pretrained RF-DETR directly:

person, car, truck, bus, bicycle, motorcycle, train, boat, airplane; cat, dog, horse, cow, sheep, elephant, bear, zebra, giraffe; bottle, cup, fork, knife, spoon, bowl; chair, couch, dining table, bed, toilet, tv, laptop, keyboard, mouse, remote, cell phone, clock, vase, book.

## Instance Segmentation

Verify model_id values from `roboflow://skills/training-and-evaluation` when building `segment-and-analyze`: `rfdetr-seg-small`, `rfdetr-seg-medium`, `rfdetr-seg-large` (placeholder — confirm before first use).

## Keypoint / Pose

Verify model_id values when building `recognize-pose-or-gesture`: YOLO26-pose and YOLO11-pose families (placeholder — confirm before first use).

## Classification

Verify model_id values when building `classify-or-flag`: ViT / DINO family (placeholder — confirm before first use).
