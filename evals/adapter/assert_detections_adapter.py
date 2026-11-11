#!/usr/bin/env python3
"""Exercise detection conversion, refusal safety, doctests, and the real baseline scorer."""

from __future__ import annotations

import errno
import json
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Any
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[2]
SCRIPTS = ROOT / "resources" / "scripts"
ADAPTER = SCRIPTS / "detections_to_counts.py"
sys.path.insert(0, str(SCRIPTS))

import detections_to_counts  # noqa: E402
import score_baseline  # noqa: E402


def _run(*args: str) -> subprocess.CompletedProcess[str]:
    """Run the adapter in a fresh interpreter."""
    return subprocess.run([sys.executable, str(ADAPTER), *args], capture_output=True, text=True, check=False)


def _write(path: Path, rows: list[Any]) -> None:
    """Write fixture rows, including deliberately nonstandard JSON numbers."""
    path.write_text("".join(json.dumps(row) + "\n" for row in rows), encoding="utf-8", newline="\n")


def _prediction(name: Any = "cat", confidence: Any = 0.5, **fields: Any) -> dict[str, Any]:
    """Construct a detection with explicit overrides for validation checks."""
    return {"class": name, "confidence": confidence, **fields}


def _convert(tmp: Path, name: str, task: str, *policy: str) -> tuple[Path, dict[str, Any]]:
    """Convert the shared fixture and validate the successful summary contract."""
    output = tmp / f"{name}.jsonl"
    result = _run(
        "--detections",
        str(tmp / "detections.jsonl"),
        "--out",
        str(output),
        "--task",
        task,
        "--class",
        "cat",
        "--min-confidence",
        "0.5",
        *policy,
    )
    assert result.returncode == 0, (result.returncode, result.stderr)
    assert result.stderr == "", result.stderr
    assert len(result.stdout.splitlines()) == 1, result.stdout
    summary = json.loads(result.stdout)
    assert summary["images"] == 2 and summary["detections_read"] == 6, summary
    return output, summary


def _assert_success(tmp: Path) -> None:
    """Check exact classes, threshold equality, multiple classes, empty frames, and determinism."""
    _write(
        tmp / "detections.jsonl",
        [
            {
                "image": "z.jpg",
                "predictions": [
                    _prediction(x=0, y=0),
                    _prediction(confidence=0.499999, x=5, y=5),
                    _prediction("dog", 1, x=10, y=10),
                    _prediction("Cat", 1, x=5, y=5),
                    _prediction(confidence=1, x=10, y=10),
                    _prediction(confidence=1, x=10.000001, y=5),
                ],
            },
            {"image": "a.jpg", "predictions": []},
        ],
    )
    count, summary = _convert(tmp, "count", "count")
    assert score_baseline.load_labels(count, "count") == {"z.jpg": 3, "a.jpg": 0}
    assert list(score_baseline.load_labels(count, "count")) == ["z.jpg", "a.jpg"]
    assert summary["detections_counted"] == 3 and summary["dropped_by_class"] == 2, summary
    assert summary["dropped_by_confidence"] == 1 and summary["dropped_by_region"] == 0, summary
    assert summary["policy"] == {"classes": ["cat"], "min_confidence": 0.5, "region": None, "task": "count"}
    repeated, _ = _convert(tmp, "count-again", "count")
    assert repeated.read_bytes() == count.read_bytes()
    flag, summary = _convert(tmp, "flag", "flag", "--class", "dog")
    assert score_baseline.load_labels(flag, "flag") == {"z.jpg": True, "a.jpg": False}
    assert summary["detections_counted"] == 4 and summary["dropped_by_class"] == 1, summary
    region, summary = _convert(tmp, "region", "count", "--region", "0,0,10,10")
    assert score_baseline.load_labels(region, "count") == {"z.jpg": 2, "a.jpg": 0}
    assert summary["dropped_by_region"] == 1 and summary["detections_counted"] == 2, summary
    assert summary["policy"]["region"] == [0, 0, 10, 10], summary
    negative_region, _ = _convert(tmp, "negative-region", "count", "--region", "-1,-1,10,10")
    assert score_baseline.load_labels(negative_region, "count") == {"z.jpg": 2, "a.jpg": 0}
    zero_threshold, _ = _convert(tmp, "zero-threshold", "count", "--min-confidence", "0")
    assert score_baseline.load_labels(zero_threshold, "count") == {"z.jpg": 4, "a.jpg": 0}
    one_threshold, _ = _convert(tmp, "one-threshold", "count", "--min-confidence", "1")
    assert score_baseline.load_labels(one_threshold, "count") == {"z.jpg": 2, "a.jpg": 0}
    _assert_scorer(tmp, count)


def _assert_scorer(tmp: Path, count: Path) -> None:
    """Run the actual scorer CLI against independently specified gold labels."""
    gold = tmp / "gold.jsonl"
    _write(gold, [{"image": "z.jpg", "count": 3}, {"image": "a.jpg", "count": 0}])
    result = subprocess.run(
        [
            sys.executable,
            str(SCRIPTS / "score_baseline.py"),
            "--gold",
            str(gold),
            "--pred",
            str(count),
            "--task",
            "count",
            "--metric",
            "exact_count_rate",
            "--comparator",
            "gte",
            "--threshold",
            "0.5",
        ],
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, (result.returncode, result.stderr)
    record = json.loads(result.stdout.splitlines()[-1])
    assert record["missing_predictions"] == 0 and record["numerator"] == 2 and record["denominator"] == 2


def _refuse(tmp: Path, text: str, *options: str) -> None:
    """Assert a refusal has one diagnostic and leaves neither output nor temporary files."""
    source, output = tmp / "bad.jsonl", tmp / "refused.jsonl"
    source.write_text(text, encoding="utf-8")
    before = set(tmp.iterdir())
    result = _run(
        "--detections",
        str(source),
        "--out",
        str(output),
        "--task",
        "count",
        "--class",
        "cat",
        "--min-confidence",
        "0.5",
        *options,
    )
    assert result.returncode == 2, (text, options, result.returncode, result.stderr)
    assert result.stderr.startswith("detections-to-counts-error: "), result.stderr
    assert len(result.stderr.splitlines()) == 1 and result.stdout == "", result
    assert not output.exists() and set(tmp.iterdir()) == before, list(tmp.iterdir())


def _assert_refusals(tmp: Path) -> None:
    """Check each malformed row, prediction, numeric value, and command-line policy."""
    valid: dict[str, Any] = {"image": "one", "predictions": []}
    bad_predictions: tuple[Any, ...] = (
        None,
        [],
        {},
        {"confidence": 0.5},
        _prediction(None),
        _prediction(7),
        {"class": "cat"},
        *(_prediction(confidence=value) for value in (None, "0.5", True, -0.1, 1.1)),
        _prediction("ignored", False),
    )
    invalid_rows: list[Any] = [
        None,
        [],
        "text",
        1,
        {},
        {"image": "one"},
        {"image": "one", "predictions": {}},
        *({"image": image, "predictions": []} for image in (None, "", 7, True)),
        *({"image": "one", "predictions": [pred]} for pred in bad_predictions),
        *({**valid, "extra": {"nested": [value]}} for value in (float("nan"), float("inf"), -float("inf"))),
        *(
            {"image": "one", "predictions": [_prediction(confidence=value)]}
            for value in (float("nan"), float("inf"), -float("inf"))
        ),
    ]
    for row in invalid_rows:
        _refuse(tmp, json.dumps(row) + "\n")
    for text in (
        "",
        "\n \n",
        "{broken}\n",
        json.dumps(valid) + "\n" + json.dumps(valid),
        json.dumps(valid) + "\n[]\n",
        '{"image":"one","predictions":[],"extra":1e999}',
    ):
        _refuse(tmp, text)
    for region in ("", "0,0,1", "a,0,1,1", "0,0,0,1", "0,1,1,0", "0,0,1,1,2", "0,0,inf,1"):
        _refuse(tmp, json.dumps(valid), "--region", region)
    for confidence in ("-0.1", "1.1", "nan", "inf", "bad", "1e999"):
        _refuse(tmp, json.dumps(valid), "--min-confidence", confidence)
    for fields in ({}, {"x": 1}, {"x": "1", "y": 1}, {"x": 1, "y": True}, {"x": None, "y": 1}):
        row = {"image": "one", "predictions": [_prediction(confidence=0.1, **fields)]}
        _refuse(tmp, json.dumps(row), "--region", "0,0,10,10")
    _refuse(tmp, json.dumps(valid), "--task", "other")


def _assert_existing_and_required(tmp: Path) -> None:
    """Check existing output preservation and mandatory policy options."""
    source, output = tmp / "existing-input.jsonl", tmp / "existing-output.jsonl"
    _write(source, [{"image": "one", "predictions": []}])
    original = b"existing output\x00\r\n"
    output.write_bytes(original)
    args = ["--detections", str(source), "--out", str(output), "--task", "count"]
    result = _run(*args, "--class", "cat", "--min-confidence", "0.5")
    assert result.returncode == 2 and result.stderr.startswith("detections-to-counts-error: "), result
    assert output.read_bytes() == original
    for policy in (("--class", "cat"), ("--min-confidence", "0.5")):
        fresh = tmp / "missing-policy.jsonl"
        result = _run("--detections", str(source), "--out", str(fresh), "--task", "count", *policy)
        assert result.returncode == 2 and result.stderr.startswith("detections-to-counts-error: "), result
        assert not fresh.exists()


def _assert_policy_refusals(tmp: Path) -> None:
    """Reject duplicate JSON keys and policy options with ambiguous or empty values."""
    _refuse(tmp, '{"image":"one","predictions":[],"predictions":[]}')
    _refuse(tmp, '{"image":"one","predictions":[{"class":"cat","class":"dog","confidence":0.5}]}')
    valid = json.dumps({"image": "one", "predictions": []})
    _refuse(tmp, valid, "--region", "0,0,1,1", "--region", "0,0,2,2")
    _refuse(tmp, valid, "--region=0,0,1,1", "--region=0,0,2,2")
    _refuse(tmp, valid, "--region=0,0,1,1", "--region", "0,0,2,2")
    _refuse(tmp, valid, "--class", "")
    _refuse(tmp, valid, "--class", " \t ")


def _assert_publish(tmp: Path) -> None:
    """Publishing never replaces an existing destination, including on the copy fallback."""
    temporary, output = tmp / "publish.tmp", tmp / "publish.jsonl"
    original = b"another writer\x00\r\n"
    content = b'{"image":"one","count":0}\n'
    temporary.write_bytes(content)
    output.write_bytes(original)
    try:
        detections_to_counts._publish(temporary, output)
    except FileExistsError:
        pass
    else:
        raise AssertionError("publish replaced an existing destination")
    assert output.read_bytes() == original and temporary.read_bytes() == content
    with patch.object(detections_to_counts.os, "link", side_effect=OSError(errno.ENOTSUP, "unsupported")):
        try:
            detections_to_counts._publish(temporary, output)
        except FileExistsError:
            pass
        else:
            raise AssertionError("copy publish replaced an existing destination")
        assert output.read_bytes() == original and temporary.read_bytes() == content
        output.unlink()
        detections_to_counts._publish(temporary, output)
    assert output.read_bytes() == content and not temporary.exists()
    temporary.write_bytes(content)
    output.unlink()
    detections_to_counts._publish(temporary, output)
    assert output.read_bytes() == content and not temporary.exists()


def _main() -> None:
    """Run all assertions in a disposable directory and report completion."""
    with tempfile.TemporaryDirectory() as directory:
        tmp = Path(directory)
        _assert_success(tmp)
        _assert_refusals(tmp)
        _assert_existing_and_required(tmp)
        _assert_policy_refusals(tmp)
        _assert_publish(tmp)
    result = subprocess.run(
        [sys.executable, "-m", "doctest", str(ADAPTER)],
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, (result.stdout, result.stderr)
    print("detections adapter assertions passed")


if __name__ == "__main__":
    _main()
