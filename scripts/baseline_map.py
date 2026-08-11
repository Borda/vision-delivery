#!/usr/bin/env python3
# ruff: noqa: E402
"""Baseline mAP@50 for B1 fixture: sandbox-ibs0b/cars-jnnoy-mmrcu/1.

Computes zero-shot COCO pretrained FasterRCNN baseline on the test split.
Results written to .temp/baseline-result.json by default. The acceptance target
is declared before inference and remains independent of the measured baseline.

Requirements: torch, torchvision, pillow, requests
    pip install torch torchvision pillow requests

Weights: ~160 MB, downloaded once to ~/.cache/torch on first run.

Set ROBOFLOW_EXPORT_URL in the environment, or point --export-file at a protected
file containing the URL. Treat export URLs as secrets: do not paste them into
reports or commit them.
"""

import argparse
import hashlib
import io
import json
import math
import os
import stat
import sys
import zipfile
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import requests

torch: Any = None
Image: Any = None
FasterRCNN_ResNet50_FPN_Weights: Any = None
fasterrcnn_resnet50_fpn: Any = None
try:
    import torch as _torch
    from PIL import Image as _Image
    from torchvision.models.detection import (
        FasterRCNN_ResNet50_FPN_Weights as _FasterRCNN_ResNet50_FPN_Weights,
    )
    from torchvision.models.detection import (
        fasterrcnn_resnet50_fpn as _fasterrcnn_resnet50_fpn,
    )
except (ImportError, RuntimeError):
    pass
else:
    torch = _torch
    Image = _Image
    FasterRCNN_ResNet50_FPN_Weights = _FasterRCNN_ResNet50_FPN_Weights
    fasterrcnn_resnet50_fpn = _fasterrcnn_resnet50_fpn

# Read from env; never hardcode credentials in source.
_export_url_env = os.environ.get("ROBOFLOW_EXPORT_URL", "")
DEFAULT_OUTPUT = Path(".temp/baseline-result.json")
CONF_THRESH = 0.3
IOU_THRESH = 0.5
MODEL_ID = "fasterrcnn_resnet50_fpn (COCO pretrained, zero-shot)"

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
    return (
        sum(
            max(
                (p for r, p in zip(recalls, precisions, strict=True) if r >= t),
                default=0.0,
            )
            for t in (i / 10 for i in range(11))
        )
        / 11
    )


def match_predictions(
    predictions: list[tuple[float, Any, list[float]]],
    gt_by_image: dict[Any, list[dict[str, Any]]],
) -> tuple[list[float], list[float], int]:
    """Match scored predictions to the best still-unmatched ground truth.

    Predictions are already sorted by descending score. A prediction may match
    only one ground-truth box, and a ground-truth box may be matched once.
    """
    true_positive = [0.0] * len(predictions)
    false_positive = [0.0] * len(predictions)
    ground_truth_count = sum(len(boxes) for boxes in gt_by_image.values())

    for index, (_, image_id, predicted_box) in enumerate(predictions):
        candidates = [
            (gt_index, ground_truth)
            for gt_index, ground_truth in enumerate(gt_by_image.get(image_id, []))
            if not ground_truth["matched"]
        ]
        if not candidates:
            false_positive[index] = 1.0
            continue

        _, ground_truth = max(
            candidates,
            key=lambda candidate: iou(predicted_box, candidate[1]["box"]),
        )
        if iou(predicted_box, ground_truth["box"]) >= IOU_THRESH:
            true_positive[index] = 1.0
            ground_truth["matched"] = True
        else:
            false_positive[index] = 1.0

    return true_positive, false_positive, ground_truth_count


def compute_map50(all_gt: list, all_pred: list) -> float:
    aps = {}
    for cid in COCO_TO_LABEL:
        preds = sorted(
            [
                (s, p["img_id"], b)
                for p in all_pred
                for b, lbl, s in zip(p["boxes"], p["labels"], p["scores"], strict=True)
                if lbl == cid
            ],
            key=lambda x: -x[0],
        )
        gt_by_img: dict = defaultdict(list)
        n_gt = 0
        for g in all_gt:
            for box, label in zip(g["boxes"], g["labels"], strict=True):
                if label == cid:
                    gt_by_img[g["img_id"]].append({"box": box, "matched": False})
                    n_gt += 1
        if not n_gt:
            continue
        tp, fp, _ = match_predictions(preds, gt_by_img)
        cumulative_tp = 0.0
        cumulative_fp = 0.0
        recalls, precisions = [], []
        for true_positive, false_positive in zip(tp, fp, strict=True):
            cumulative_tp += true_positive
            cumulative_fp += false_positive
            recalls.append(cumulative_tp / n_gt)
            precisions.append(cumulative_tp / (cumulative_tp + cumulative_fp))
        aps[cid] = compute_ap(recalls, precisions)
    return sum(aps.values()) / len(aps) if aps else 0.0


def parse_args() -> argparse.Namespace:
    """Parse protected export-file input and the pre-registered target."""
    parser = argparse.ArgumentParser(description="Measure a fixed detector baseline against a pre-set target.")
    parser.add_argument(
        "--export-file",
        type=Path,
        help="Protected file containing the private COCO export URL.",
    )
    parser.add_argument(
        "--acceptance",
        required=True,
        type=Path,
        help="Frozen Sentinel acceptance JSON created before baseline inference.",
    )
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    return parser.parse_args()


def _load_acceptance(path: Path) -> tuple[dict[str, Any], str]:
    """Load the frozen B1 acceptance artifact and return its digest."""
    if path.is_symlink() or not path.is_file():
        raise RuntimeError("ERROR: acceptance must be a regular non-symlink file.")
    try:
        raw = path.read_bytes()
        data = json.loads(raw)
    except (OSError, json.JSONDecodeError):
        raise RuntimeError("ERROR: acceptance artifact is invalid.") from None
    required = {
        "schema_version",
        "acceptance_id",
        "frozen_at",
        "metric",
        "comparator",
        "threshold",
        "dataset_sha256",
        "model_or_pipeline",
    }
    if not isinstance(data, dict) or required - data.keys():
        raise RuntimeError("ERROR: acceptance artifact is invalid.")
    try:
        frozen_at = datetime.fromisoformat(str(data["frozen_at"]).replace("Z", "+00:00"))
    except ValueError:
        raise RuntimeError("ERROR: acceptance frozen_at is invalid.") from None
    if frozen_at.tzinfo is None:
        raise RuntimeError("ERROR: acceptance frozen_at must include a timezone.")
    if str(data["metric"]).casefold().replace("@", "").replace("_", "") != "map50":
        raise RuntimeError("ERROR: acceptance metric must be mAP@50.")
    if data["comparator"] != "gte":
        raise RuntimeError("ERROR: mAP@50 acceptance comparator must be gte.")
    threshold = data["threshold"]
    if (
        isinstance(threshold, bool)
        or not isinstance(threshold, int | float)
        or not math.isfinite(threshold)
        or not 0.0 <= threshold <= 1.0
    ):
        raise RuntimeError("ERROR: acceptance threshold must be in [0.0, 1.0].")
    digest = str(data["dataset_sha256"])
    if len(digest) != 64 or any(char not in "0123456789abcdef" for char in digest):
        raise RuntimeError("ERROR: acceptance dataset_sha256 is invalid.")
    if data["model_or_pipeline"] != MODEL_ID:
        raise RuntimeError("ERROR: acceptance model_or_pipeline does not match B1.")
    return data, hashlib.sha256(raw).hexdigest()


def _protected_export_url(export_file: Path | None) -> str:
    """Read the private export URL from a protected file or environment."""
    path_value = export_file or os.environ.get("ROBOFLOW_EXPORT_URL_FILE", "")
    if path_value:
        path = Path(path_value)
        try:
            if path.is_symlink() or not path.is_file():
                return ""
            if os.name == "posix" and stat.S_IMODE(path.stat().st_mode) & 0o077:
                return ""
            return path.read_text(encoding="utf-8").strip()
        except OSError:
            return ""
    return _export_url_env


def _load_export(export_url: str, expected_dataset_sha256: str | None = None) -> tuple:
    """Download the COCO export and index the test split.

    Args:
        export_url: Private export URL; treated as a secret.

    Returns:
        Tuple of (zip file, member names, images by id, category names by id,
        ground-truth annotations by image id, annotation count).
    """
    print("Downloading COCO export...")
    try:
        response = requests.get(export_url, timeout=90)
        response.raise_for_status()
        dataset_digest = hashlib.sha256(response.content).hexdigest()
        if expected_dataset_sha256 and dataset_digest != expected_dataset_sha256:
            raise ValueError("dataset digest mismatch")
        zf = zipfile.ZipFile(io.BytesIO(response.content))
        names = zf.namelist()
        test_ann = next((n for n in names if "test" in n.lower() and n.endswith(".json")), None)
        if not test_ann:
            raise ValueError("missing test annotations")

        ann_data = json.loads(zf.read(test_ann))
        images_meta = {img["id"]: img for img in ann_data["images"]}
        categories = {cat["id"]: cat["name"].lower() for cat in ann_data["categories"]}
        gt_by_image: dict = defaultdict(list)
        for ann in ann_data["annotations"]:
            gt_by_image[ann["image_id"]].append(ann)
    except Exception:
        raise RuntimeError("ERROR: protected dataset export failed; URL redacted.") from None

    print(f"  Images: {len(images_meta)}, annotations: {len(ann_data['annotations'])}\n")
    return zf, names, images_meta, categories, gt_by_image, len(ann_data["annotations"])


def _collect_detections(
    zf: zipfile.ZipFile,
    names: list,
    images_meta: dict,
    categories: dict,
    gt_by_image: dict,
) -> tuple:
    """Run zero-shot inference over the test split and accumulate records.

    Args:
        zf: Opened export archive.
        names: Archive member names.
        images_meta: Image metadata by image id.
        categories: Category names by category id.
        gt_by_image: Ground-truth annotations by image id.

    Returns:
        Tuple of (ground-truth records, prediction records, per-class count errors).
    """
    if torch is None or Image is None or fasterrcnn_resnet50_fpn is None:
        raise RuntimeError("ERROR: install the baseline inference dependencies.")
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
        for box, label, score in zip(preds["boxes"], preds["labels"], preds["scores"], strict=True):
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
        all_pred.append(
            {
                "img_id": img_id,
                "boxes": pred_boxes,
                "labels": pred_labels,
                "scores": pred_scores,
            }
        )

        gt_cnt: dict = defaultdict(int)
        for lbl in gt_labels:
            gt_cnt[COCO_TO_LABEL[lbl]] += 1
        pred_cnt: dict = defaultdict(int)
        for lbl in pred_labels:
            pred_cnt[COCO_TO_LABEL[lbl]] += 1
        for cls in COCO_TO_LABEL.values():
            count_errors[cls].append(abs(gt_cnt[cls] - pred_cnt[cls]))

        print(f"  {fname.split('/')[-1]}: gt={len(gt_boxes)} pred={len(pred_boxes)}")

    return all_gt, all_pred, count_errors


def _report_and_write(
    args: argparse.Namespace,
    acceptance: dict[str, Any],
    acceptance_sha256: str,
    all_gt: list,
    all_pred: list,
    count_errors: dict,
    n_images: int,
    n_annotations: int,
) -> None:
    """Compute metrics against the pre-registered target and persist the result.

    Args:
        args: Parsed CLI namespace containing the output path.
        acceptance: Frozen acceptance artifact.
        acceptance_sha256: Digest of the frozen acceptance artifact.
        all_gt: Ground-truth records per image.
        all_pred: Prediction records per image.
        count_errors: Absolute per-class count errors per image.
        n_images: Number of test images.
        n_annotations: Number of ground-truth annotations.
    """
    map50 = compute_map50(all_gt, all_pred)
    all_errs = [e for errs in count_errors.values() for e in errs]
    count_mae = sum(all_errs) / len(all_errs) if all_errs else 0.0
    per_class_mae = {cls: round(sum(errs) / len(errs), 2) for cls, errs in count_errors.items()}
    acceptance_map50 = float(acceptance["threshold"])
    baseline_gap = map50 - acceptance_map50

    print(f"\n{'=' * 50}")
    print(f"mAP@50:    {map50:.1%}")
    print(f"Count MAE: {count_mae:.2f} per class per image")
    for cls, mae in sorted(per_class_mae.items()):
        print(f"  {cls}: MAE = {mae}")
    print(f"\nAcceptance target (pre-registered): {acceptance_map50:.1%}")
    print(f"Baseline gap: {baseline_gap:+.1%}")

    result = {
        "fixture": "sandbox-ibs0b/cars-jnnoy-mmrcu/1",
        "problem": "Vehicle detection (car/motorcycle/truck) — aerial/overhead view",
        "model": MODEL_ID,
        "measured_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "metric": acceptance["metric"],
        "comparator": acceptance["comparator"],
        "threshold": acceptance_map50,
        "observed_value": round(map50, 4),
        "test_images": n_images,
        "annotations": n_annotations,
        "conf_threshold": CONF_THRESH,
        "iou_threshold": IOU_THRESH,
        "map50": round(map50, 4),
        "count_mae": round(count_mae, 3),
        "count_mae_per_class": per_class_mae,
        "classes": sorted(COCO_TO_LABEL.values()),
        "acceptance_id": acceptance["acceptance_id"],
        "acceptance_sha256": acceptance_sha256,
        "dataset_sha256": acceptance["dataset_sha256"],
        "acceptance_map50": acceptance_map50,
        "acceptance_source": "frozen Sentinel acceptance artifact",
        "baseline_gap": round(baseline_gap, 4),
        "passes_acceptance": map50 >= acceptance_map50,
        "notes": ["Aerial view — poor zero-shot COCO performance expected; training required to reach 65%"],
    }

    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, indent=2), encoding="utf-8")
    print(f"\nWritten → {args.output}")


def main() -> None:
    """Measure the zero-shot baseline without changing the acceptance target."""
    args = parse_args()
    print("=== B1 Baseline: FasterRCNN COCO zero-shot on Cars test split ===\n")

    try:
        acceptance, acceptance_sha256 = _load_acceptance(args.acceptance)
    except RuntimeError as exc:
        sys.exit(str(exc))

    export_url = _protected_export_url(args.export_file)
    if not export_url:
        sys.exit("ERROR: provide a protected export file or ROBOFLOW_EXPORT_URL; URL redacted.")

    try:
        zf, names, images_meta, categories, gt_by_image, n_annotations = _load_export(
            export_url, str(acceptance["dataset_sha256"])
        )
    except RuntimeError as exc:
        sys.exit(str(exc))
    all_gt, all_pred, count_errors = _collect_detections(zf, names, images_meta, categories, gt_by_image)
    _report_and_write(
        args,
        acceptance,
        acceptance_sha256,
        all_gt,
        all_pred,
        count_errors,
        len(images_meta),
        n_annotations,
    )


if __name__ == "__main__":
    main()
