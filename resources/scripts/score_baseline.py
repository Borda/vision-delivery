#!/usr/bin/env python3
"""Score count or flag predictions against independent gold labels in plain language.

Stdlib only, so a rung 0 baseline (see `resources/baseline-ladder.md`) can be measured
before any account, install, or upload. Input files are JSON Lines with one object per
image: `{"image": "<id>", "count": <int>}` or `{"image": "<id>", "flag": <bool>}`.
"""

from __future__ import annotations

import argparse
import json
import math
import sys
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from proof_chain import load_acceptance, sha256_file, write_json_exclusive

COUNT_METRICS = ("count_mae", "exact_count_rate", "catch_rate", "over_count_rate")
FLAG_METRICS = ("catch_rate", "false_alarm_rate", "precision", "accuracy")
PLAIN_NAMES = {
    "count_mae": "average count error per image",
    "exact_count_rate": "images counted exactly right",
    "catch_rate": "real cases caught",
    "over_count_rate": "extra counts per real object",
    "false_alarm_rate": "clean images wrongly flagged",
    "precision": "flags that were real",
    "accuracy": "images judged correctly",
}
RATE_METRICS = frozenset(PLAIN_NAMES) - {"count_mae"}


@dataclass(frozen=True)
class Target:
    """Frozen pass rule: metric, direction, and threshold."""

    metric: str
    comparator: str
    threshold: float
    acceptance_id: str = ""
    acceptance_sha256: str = ""


def load_labels(path: Path, field: str) -> dict[str, Any]:
    """Read one JSONL label file keyed by image identity.

    Examples:
        >>> import tempfile, os
        >>> handle = tempfile.NamedTemporaryFile("w", suffix=".jsonl", delete=False)
        >>> _ = handle.write('{"image": "a", "count": 2}\\n'); handle.close()
        >>> load_labels(Path(handle.name), "count")
        {'a': 2}
        >>> os.unlink(handle.name)
    """
    labels: dict[str, Any] = {}
    for number, raw in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        if not raw.strip():
            continue
        row = json.loads(raw)
        image = row.get("image") if isinstance(row, dict) else None
        if not isinstance(image, str) or not image or field not in row:
            raise ValueError(f"{path.name}:{number} needs a non-empty 'image' and '{field}'")
        if image in labels:
            raise ValueError(f"{path.name}:{number} repeats image {image!r}")
        labels[image] = _checked_value(row[field], field, f"{path.name}:{number}")
    if not labels:
        raise ValueError(f"{path.name} has no labeled images")
    return labels


def _checked_value(value: Any, field: str, where: str) -> Any:
    """Validate one count (non-negative int) or flag (bool) value."""
    if field == "flag":
        if not isinstance(value, bool):
            raise ValueError(f"{where} flag must be true or false")
        return value
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise ValueError(f"{where} count must be a non-negative integer")
    return value


def count_metrics(gold: dict[str, int], pred: dict[str, int]) -> dict[str, float]:
    """Compute count error and coverage metrics; missing predictions count as zero.

    Examples:
        >>> count_metrics({"a": 2, "b": 0}, {"a": 1})
        {'count_mae': 0.5, 'exact_count_rate': 0.5, 'catch_rate': 0.5, 'over_count_rate': 0.0}
    """
    errors = [abs(pred.get(image, 0) - truth) for image, truth in gold.items()]
    real = sum(gold.values())
    caught = sum(min(pred.get(image, 0), truth) for image, truth in gold.items())
    extra = sum(max(pred.get(image, 0) - truth, 0) for image, truth in gold.items())
    return {
        "count_mae": sum(errors) / len(gold),
        "exact_count_rate": sum(error == 0 for error in errors) / len(gold),
        "catch_rate": caught / real if real else 1.0,
        "over_count_rate": extra / real if real else float(extra > 0),
    }


def flag_metrics(gold: dict[str, bool], pred: dict[str, bool]) -> dict[str, float]:
    """Compute flag metrics; a missing prediction counts as not flagged.

    Examples:
        >>> flag_metrics({"a": True, "b": False, "c": True}, {"a": True, "b": True})
        {'catch_rate': 0.5, 'false_alarm_rate': 1.0, 'precision': 0.5, 'accuracy': 0.3333333333333333}
    """
    flagged = {image: pred.get(image, False) for image in gold}
    hits = sum(gold[image] and flagged[image] for image in gold)
    positives = sum(gold.values())
    negatives = len(gold) - positives
    false_alarms = sum(flagged[image] and not gold[image] for image in gold)
    raised = hits + false_alarms
    return {
        "catch_rate": hits / positives if positives else 1.0,
        "false_alarm_rate": false_alarms / negatives if negatives else 0.0,
        "precision": hits / raised if raised else 1.0,
        "accuracy": sum(flagged[image] == gold[image] for image in gold) / len(gold),
    }


def passes(value: float, target: Target) -> bool:
    """Apply the frozen comparator.

    Examples:
        >>> passes(0.8, Target("catch_rate", "gte", 0.8))
        True
    """
    return value >= target.threshold if target.comparator == "gte" else value <= target.threshold


def plain_value(metric: str, value: float) -> str:
    """Format a metric value for a non-specialist reader.

    Examples:
        >>> plain_value("catch_rate", 0.85)
        '85%'
    """
    return f"{value:.0%}" if metric in RATE_METRICS else f"{value:.2f}"


def resolve_target(args: argparse.Namespace, allowed: tuple[str, ...]) -> Target:
    """Return the acceptance-file target in deliver mode, or the inline target in explore mode."""
    if args.acceptance is not None:
        data = load_acceptance(args.acceptance)
        target = Target(
            str(data["metric"]),
            str(data["comparator"]),
            float(data["threshold"]),
            str(data["acceptance_id"]),
            sha256_file(args.acceptance),
        )
    elif args.metric and args.comparator and args.threshold is not None:
        target = Target(args.metric, args.comparator, args.threshold)
    else:
        raise ValueError("give --acceptance, or all of --metric, --comparator, and --threshold")
    if target.metric not in allowed:
        raise ValueError(f"metric {target.metric!r} is not scored for this task; choose one of {allowed}")
    if not math.isfinite(target.threshold):
        raise ValueError("threshold must be finite")
    return target


def parse_args() -> argparse.Namespace:
    """Parse scorer inputs."""
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--gold", required=True, type=Path)
    parser.add_argument("--pred", required=True, type=Path)
    parser.add_argument("--task", required=True, choices=("count", "flag"))
    parser.add_argument("--metric")
    parser.add_argument("--comparator", choices=("gte", "lte"))
    parser.add_argument("--threshold", type=float)
    parser.add_argument("--acceptance", type=Path)
    parser.add_argument("--evidence-out", type=Path)
    return parser.parse_args()


def main() -> int:
    """Score predictions, print a plain verdict, and optionally write evidence."""
    args = parse_args()
    field, allowed = ("count", COUNT_METRICS) if args.task == "count" else ("flag", FLAG_METRICS)
    try:
        target = resolve_target(args, allowed)
        gold = load_labels(args.gold, field)
        pred = load_labels(args.pred, field)
        extra = sorted(set(pred) - set(gold))
        if extra:
            raise ValueError(f"predictions name images missing from gold: {extra[:5]}")
    except (ValueError, KeyError, json.JSONDecodeError, OSError) as exc:
        print(f"score-baseline-error: {exc}", file=sys.stderr)
        return 2
    metrics = count_metrics(gold, pred) if field == "count" else flag_metrics(gold, pred)
    value = metrics[target.metric]
    verdict = "pass" if passes(value, target) else "below-target"
    symbol = ">=" if target.comparator == "gte" else "<="
    print(
        f"{PLAIN_NAMES[target.metric].capitalize()}: {plain_value(target.metric, value)} on {len(gold)} images "
        f"(target {symbol} {plain_value(target.metric, target.threshold)}): {verdict.upper()}. "
        f"Missing predictions: {len(set(gold) - set(pred))}."
    )
    record = {
        "schema_version": "1",
        "measured_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "task": args.task,
        "images": len(gold),
        "metrics": metrics,
        "target": asdict(target),
        "observed_value": value,
        "verdict": verdict,
        "gold_sha256": sha256_file(args.gold),
        "pred_sha256": sha256_file(args.pred),
    }
    print(json.dumps(record, sort_keys=True))
    if args.evidence_out is not None:
        write_json_exclusive(args.evidence_out, record)
    return 0


if __name__ == "__main__":
    sys.exit(main())
