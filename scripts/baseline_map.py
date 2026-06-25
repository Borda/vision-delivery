#!/usr/bin/env python3
"""Baseline mAP@50 for B1 fixture: sandbox-ibs0b/cars-jnnoy-mmrcu/1.

Computes zero-shot COCO pretrained FasterRCNN baseline on the test split.
Results written to .temp/baseline-result.json.

Requirements: torch, torchvision, pillow, requests, numpy
    pip install torch torchvision pillow requests numpy

Weights: ~160 MB, downloaded once to ~/.cache/torch on first run.
SSL: patches ssl._create_default_https_context for machines with cert issues.
"""
import ssl; ssl._create_default_https_context = ssl._create_unverified_context  # ponytail: local cert workaround
import json, zipfile, io, sys, requests, warnings
from pathlib import Path
from collections import defaultdict

warnings.filterwarnings("ignore")

import numpy as np

try:
    import torch
    from torchvision.models.detection import fasterrcnn_resnet50_fpn, FasterRCNN_ResNet50_FPN_Weights
    from PIL import Image
except ImportError:
    sys.exit("pip install torch torchvision pillow numpy")

EXPORT_URL = "https://app.roboflow.com/ds/KEwFWYdIal?key=GJwuCSp0Sb"
OUTPUT = Path(".temp/baseline-result.json")
CONF_THRESH = 0.3
IOU_THRESH = 0.5

# COCO 80-class IDs for our target classes
COCO_TO_LABEL = {3: "car", 4: "motorcycle", 8: "truck"}
LABEL_TO_COCO = {v: k for k, v in COCO_TO_LABEL.items()}


def iou(a: list, b: list) -> float:
    xi1, yi1 = max(a[0], b[0]), max(a[1], b[1])
    xi2, yi2 = min(a[2], b[2]), min(a[3], b[3])
    inter = max(0, xi2 - xi1) * max(0, yi2 - yi1)
    area_a = (a[2] - a[0]) * (a[3] - a[1])
    area_b = (b[2] - b[0]) * (b[3] - b[1])
    union = area_a + area_b - inter
    return inter / union if union > 0 else 0.0


def compute_ap(recalls: list, precisions: list) -> float:
    """11-point interpolated AP."""
    return sum(
        max((p for r, p in zip(recalls, precisions) if r >= t), default=0.0)
        for t in np.linspace(0, 1, 11)
    ) / 11


def compute_map50(all_gt: list, all_pred: list) -> float:
    aps = {}
    for cid in COCO_TO_LABEL:
        preds = sorted(
            [(s, p["img_id"], b) for p in all_pred for b, l, s in zip(p["boxes"], p["labels"], p["scores"]) if l == cid],
            key=lambda x: -x[0],
        )
        gt_by_img: dict = defaultdict(list)
        n_gt = 0
        for g in all_gt:
            for box, label in zip(g["boxes"], g["labels"]):
                if label == cid:
                    gt_by_img[g["img_id"]].append({"box": box, "matched": False})
                    n_gt += 1
        if not n_gt:
            continue
        tp, fp = np.zeros(len(preds)), np.zeros(len(preds))
        for i, (_, img_id, pred_box) in enumerate(preds):
            gts = gt_by_img.get(img_id, [])
            best_iou, best_j = 0.0, -1
            for j, g in enumerate(gts):
                v = iou(pred_box, g["box"])
                if v > best_iou:
                    best_iou, best_j = v, j
            if best_iou >= IOU_THRESH and best_j >= 0 and not gts[best_j]["matched"]:
                tp[i] = 1
                gts[best_j]["matched"] = True
            else:
                fp[i] = 1
        cum_tp = np.cumsum(tp)
        recalls = list(cum_tp / n_gt)
        precisions = list(cum_tp / (cum_tp + np.cumsum(fp) + 1e-8))
        aps[cid] = compute_ap(recalls, precisions)
    return float(np.mean(list(aps.values()))) if aps else 0.0


def main() -> None:
    print("=== B1 Baseline: FasterRCNN COCO zero-shot on Cars test split ===\n")

    print("Downloading COCO export...")
    r = requests.get(EXPORT_URL, timeout=90, verify=False)
    r.raise_for_status()
    print(f"  {len(r.content)//1024} KB")

    zf = zipfile.ZipFile(io.BytesIO(r.content))
    names = zf.namelist()
    test_ann = next((n for n in names if "test" in n.lower() and n.endswith(".json")), None)
    if not test_ann:
        sys.exit("ERROR: no test annotation JSON in export")

    ann_data = json.loads(zf.read(test_ann))
    images_meta = {img["id"]: img for img in ann_data["images"]}
    categories = {cat["id"]: cat["name"].lower() for cat in ann_data["categories"]}
    gt_by_image: dict = defaultdict(list)
    for ann in ann_data["annotations"]:
        gt_by_image[ann["image_id"]].append(ann)
    print(f"  Images: {len(images_meta)}, annotations: {len(ann_data['annotations'])}\n")

    print("Loading FasterRCNN (COCO pretrained)...")
    weights = FasterRCNN_ResNet50_FPN_Weights.COCO_V1
    model = fasterrcnn_resnet50_fpn(weights=weights)
    model.eval()
    transform = weights.transforms()
    print("  Ready\n")

    all_gt, all_pred = [], []
    count_errors: dict = defaultdict(list)

    for img_id, img_info in sorted(images_meta.items()):
        fname = img_info["file_name"]
        candidates = [n for n in names if fname in n]
        if not candidates:
            print(f"  SKIP {fname}")
            continue

        img = Image.open(io.BytesIO(zf.read(candidates[0]))).convert("RGB")
        with torch.no_grad():
            preds = model([transform(img)])[0]

        pred_boxes, pred_labels, pred_scores = [], [], []
        for box, label, score in zip(preds["boxes"], preds["labels"], preds["scores"]):
            if label.item() in COCO_TO_LABEL and score.item() >= CONF_THRESH:
                pred_boxes.append(box.tolist())
                pred_labels.append(label.item())
                pred_scores.append(score.item())

        gt_boxes, gt_labels = [], []
        for g in gt_by_image[img_id]:
            cat_name = categories.get(g["category_id"], "")
            coco_id = LABEL_TO_COCO.get(cat_name)
            if coco_id is None:
                continue
            bx, by, bw, bh = g["bbox"]
            gt_boxes.append([bx, by, bx + bw, by + bh])
            gt_labels.append(coco_id)

        all_gt.append({"img_id": img_id, "boxes": gt_boxes, "labels": gt_labels})
        all_pred.append({"img_id": img_id, "boxes": pred_boxes, "labels": pred_labels, "scores": pred_scores})

        gt_cnt: dict = defaultdict(int)
        for l in gt_labels:
            gt_cnt[COCO_TO_LABEL[l]] += 1
        pred_cnt: dict = defaultdict(int)
        for l in pred_labels:
            pred_cnt[COCO_TO_LABEL[l]] += 1
        for cls in COCO_TO_LABEL.values():
            count_errors[cls].append(abs(gt_cnt[cls] - pred_cnt[cls]))

        print(f"  {fname.split('/')[-1]}: gt={len(gt_boxes)} pred={len(pred_boxes)}")

    map50 = compute_map50(all_gt, all_pred)
    all_errs = [e for errs in count_errors.values() for e in errs]
    count_mae = float(np.mean(all_errs)) if all_errs else 0.0
    per_class_mae = {cls: round(float(np.mean(errs)), 2) for cls, errs in count_errors.items()}
    threshold = max(round(map50 * 100, 1), 65.0)

    print(f"\n{'='*50}")
    print(f"mAP@50:    {map50:.1%}")
    print(f"Count MAE: {count_mae:.2f} per class per image")
    for cls, mae in sorted(per_class_mae.items()):
        print(f"  {cls}: MAE = {mae}")
    print(f"\nThreshold: max(measured={map50:.0%}, floor=65%) = {threshold:.0f}%")

    result = {
        "fixture": "sandbox-ibs0b/cars-jnnoy-mmrcu/1",
        "problem": "Vehicle detection (car/motorcycle/truck) — aerial/overhead view",
        "model": "fasterrcnn_resnet50_fpn (COCO pretrained, zero-shot)",
        "test_images": len(images_meta),
        "annotations": len(ann_data["annotations"]),
        "conf_threshold": CONF_THRESH,
        "iou_threshold": IOU_THRESH,
        "map50": round(map50, 4),
        "count_mae": round(count_mae, 3),
        "count_mae_per_class": per_class_mae,
        "classes": sorted(COCO_TO_LABEL.values()),
        "threshold": f"max({round(map50*100,1)}%, 65%) = {threshold}%",
        "notes": ["Aerial view — poor zero-shot COCO performance expected; training required to reach 65%"],
    }

    OUTPUT.parent.mkdir(exist_ok=True)
    OUTPUT.write_text(json.dumps(result, indent=2))
    print(f"\nWritten → {OUTPUT}")


if __name__ == "__main__":
    main()
