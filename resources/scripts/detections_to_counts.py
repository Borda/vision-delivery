#!/usr/bin/env python3
"""Convert per-image detections into scorer-compatible count or flag JSON Lines.

Purpose: Apply an explicit, frozen class, confidence, and optional centre-region policy.
Scope: Standard-library-only conversion; no model inference, image discovery, or label filling.
Usage: Run this module with --detections, --out, --task, repeatable --class, and
    --min-confidence. Optionally supply --region x_min,y_min,x_max,y_max.
Outputs: One count or boolean flag per input image in input order, published without
    replacing an existing output by linking a complete sibling temporary file. Filesystems
    without hard links use an exclusive-create copy, visible while copying. One JSON summary
    goes to stdout; drop totals are exclusive, in class, confidence, then region order.
Failure: Invalid input, policy, or file operations return 2 with one prefixed stderr line.
    Existing output paths are refused; failed conversions remove their temporary file.
Used by: Detection-based baseline ladder rungs and resources/scripts/score_baseline.py.
"""

from __future__ import annotations

import argparse
import errno
import json
import math
import os
import shutil
import sys
import tempfile
from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from typing import Any, NoReturn


class Task(str, Enum):
    """Select the count or flag output schema."""

    COUNT = "count"
    FLAG = "flag"


@dataclass(frozen=True)
class Policy:
    """Hold the immutable class, confidence, and optional inclusive region policy."""

    classes: frozenset[str]
    min_confidence: float
    region: tuple[float, float, float, float] | None


class _Parser(argparse.ArgumentParser):
    """Route argument failures through the same single-line error contract as input failures."""

    def error(self, message: str) -> NoReturn:
        """Raise a validation error instead of printing argparse usage.

        Args:
            message: Diagnostic supplied by argparse.

        Raises:
            ValueError: Always, for the CLI boundary to report.

        Examples:
            >>> _Parser().error("missing policy")
            Traceback (most recent call last):
                ...
            ValueError: missing policy
        """
        raise ValueError(message)


def _finite_number(value: Any) -> bool:
    """Recognize finite JSON numbers without treating booleans as numbers."""
    return (isinstance(value, int) and not isinstance(value, bool)) or (
        isinstance(value, float) and math.isfinite(value)
    )


def _finite_float(text: str) -> float:
    """Parse a finite float, also rejecting JSON exponent overflow."""
    value = float(text)
    if not math.isfinite(value):
        raise ValueError("all numeric values must be finite")
    return value


def _reject_constant(text: str) -> Any:
    """Reject Python's nonstandard JSON NaN and Infinity literals."""
    raise ValueError(f"non-finite JSON number {text}")


def _region(text: str) -> tuple[float, float, float, float]:
    """Parse a finite rectangle with strictly increasing bounds."""
    values = tuple(_finite_float(part) for part in text.split(","))
    if len(values) != 4:
        raise ValueError("region needs x_min,y_min,x_max,y_max")
    x_min, y_min, x_max, y_max = values
    if x_min >= x_max or y_min >= y_max:
        raise ValueError("region minima must be below maxima")
    return x_min, y_min, x_max, y_max


def _arguments(argv: list[str] | None) -> tuple[Path, Path, Task, Policy]:
    """Validate command-line policy and convert the closed task choice once."""
    parser = _Parser(description=__doc__.splitlines()[0])
    parser.add_argument("--detections", required=True, type=Path)
    parser.add_argument("--out", required=True, type=Path)
    parser.add_argument("--task", required=True, choices=[task.value for task in Task])
    parser.add_argument("--class", required=True, action="append", dest="classes")
    parser.add_argument("--min-confidence", required=True, type=_finite_float)
    parser.add_argument("--region", type=_region, action="append")
    arguments = list(sys.argv[1:] if argv is None else argv)
    # Bind rectangle values so argparse accepts negative first coordinates in split syntax.
    for index in range(len(arguments) - 2, -1, -1):
        if arguments[index] == "--region":
            arguments[index : index + 2] = [f"--region={arguments[index + 1]}"]
    args = parser.parse_args(arguments)
    if not 0 <= args.min_confidence <= 1:
        raise ValueError("min-confidence must be from 0 to 1")
    if any(not name.strip() for name in args.classes):
        raise ValueError("class must not be empty or whitespace-only")
    if args.region is not None and len(args.region) > 1:
        raise ValueError("region must be supplied at most once")
    policy = Policy(frozenset(args.classes), args.min_confidence, args.region[0] if args.region else None)
    return args.detections, args.out, Task(args.task), policy


def _unique_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    """Reject repeated JSON keys instead of silently selecting their final values."""
    value: dict[str, Any] = {}
    for key, item in pairs:
        if key in value:
            raise ValueError(f"JSON object repeats key: {key!r}")
        value[key] = item
    return value


def _row(raw: str, seen: set[str]) -> tuple[str, list[Any]]:
    """Validate an image record and track unique identities."""
    row = json.loads(raw, parse_float=_finite_float, parse_constant=_reject_constant, object_pairs_hook=_unique_object)
    if not isinstance(row, dict):
        raise ValueError("each line must be a JSON object")
    image = row.get("image")
    if not isinstance(image, str) or not image:
        raise ValueError("image must be a non-empty string")
    if image in seen:
        raise ValueError(f"image repeats: {image!r}")
    predictions = row.get("predictions")
    if not isinstance(predictions, list):
        raise ValueError("predictions must be a list")
    seen.add(image)
    return image, predictions


def _drop_reason(prediction: Any, policy: Policy) -> str | None:
    """Validate a detection, then return its first failing filter, if any."""
    if not isinstance(prediction, dict) or not isinstance(prediction.get("class"), str):
        raise ValueError("each prediction needs a string class")
    confidence: Any = prediction.get("confidence")
    x: Any = prediction.get("x")
    y: Any = prediction.get("y")
    if not _finite_number(confidence) or not 0 <= confidence <= 1:
        raise ValueError("prediction confidence must be a finite number from 0 to 1")
    if prediction["class"] not in policy.classes:
        return "class"
    # Selected classes need usable centres even when confidence would drop the detection.
    if policy.region is not None:
        if not _finite_number(x) or not _finite_number(y):
            raise ValueError("selected-class predictions need finite numeric x and y with --region")
    if confidence < policy.min_confidence:
        return "confidence"
    if policy.region is not None:
        x_min, y_min, x_max, y_max = policy.region
        if not (x_min <= x <= x_max and y_min <= y <= y_max):
            return "region"
    return None


def _refuse_existing(path: Path) -> None:
    """Protect existing entries, including dangling symlinks, from replacement."""
    if os.path.lexists(path):
        raise ValueError("out already exists")


def _publish(temporary: Path, output: Path) -> None:
    """Publish a complete temporary file without replacing a concurrently created output.

    An unsupported hard link falls back to exclusive creation and copying. The fallback
    preserves existing targets but allows readers to see the copy before it is complete.
    Failed copies remove only the output created by this call; the temporary file remains.
    """
    try:
        os.link(temporary, output)
    except (OSError, NotImplementedError) as exc:
        if isinstance(exc, OSError) and exc.errno not in {errno.ENOSYS, errno.ENOTSUP, errno.EOPNOTSUPP}:
            raise
        created = False
        complete = False
        try:
            with temporary.open("rb") as incoming, output.open("xb") as outgoing:
                created = True
                shutil.copyfileobj(incoming, outgoing)
            complete = True
        finally:
            if created and not complete:
                output.unlink()
    temporary.unlink()


def _convert(source: Path, output: Path, task: Task, policy: Policy) -> dict[str, Any]:
    """Stream validated rows to a sibling temporary file, then publish the complete output."""
    _refuse_existing(output)
    seen: set[str] = set()
    summary: dict[str, Any] = {
        "images": 0,
        "detections_read": 0,
        "detections_counted": 0,
        "dropped_by_class": 0,
        "dropped_by_confidence": 0,
        "dropped_by_region": 0,
        "policy": {
            "classes": sorted(policy.classes),
            "min_confidence": policy.min_confidence,
            "region": policy.region,
            "task": task.value,
        },
    }
    temporary: Path | None = None
    try:
        with (
            source.open(encoding="utf-8") as incoming,
            tempfile.NamedTemporaryFile(
                mode="w",
                encoding="utf-8",
                newline="\n",
                dir=output.parent,
                prefix=f".{output.name}.",
                suffix=".tmp",
                delete=False,
            ) as outgoing,
        ):
            temporary = Path(outgoing.name)
            for number, raw in enumerate(incoming, 1):
                try:
                    image, predictions = _row(raw, seen)
                    count = 0
                    for prediction in predictions:
                        reason = _drop_reason(prediction, policy)
                        summary["detections_read"] += 1
                        if reason is None:
                            count += 1
                        else:
                            summary[f"dropped_by_{reason}"] += 1
                except (ValueError, RecursionError) as exc:
                    raise ValueError(f"line {number}: {exc}") from exc
                value = count if task is Task.COUNT else count > 0
                outgoing.write(json.dumps({"image": image, task.value: value}) + "\n")
                summary["images"] += 1
                summary["detections_counted"] += count
            if not seen:
                raise ValueError("detections file has no image lines")
        _publish(temporary, output)
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)
    return summary


def main(argv: list[str] | None = None) -> int:
    """Convert detections using explicit CLI policy and report a summary or one diagnostic.

    Args:
        argv: Command-line arguments; None reads the process arguments.

    Returns:
        Zero on success, or two when input, policy, or file operations are invalid.

    Examples:
        >>> import contextlib, io
        >>> errors = io.StringIO()
        >>> with contextlib.redirect_stderr(errors):
        ...     status = main([])
        >>> status, errors.getvalue().startswith("detections-to-counts-error: ")
        (2, True)
        >>> _region("0,1,2,3")
        (0.0, 1.0, 2.0, 3.0)
        >>> _drop_reason({"class": "cat", "confidence": 0.5}, Policy(frozenset({"cat"}), 0.5, None))
    """
    try:
        source, output, task, policy = _arguments(argv)
        summary = _convert(source, output, task, policy)
    except (OSError, ValueError, RecursionError) as exc:
        diagnostic = " ".join(str(exc).splitlines())
        print(f"detections-to-counts-error: {diagnostic}", file=sys.stderr)
        return 2
    print(json.dumps(summary, allow_nan=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
