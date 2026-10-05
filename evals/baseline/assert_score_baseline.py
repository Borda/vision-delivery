#!/usr/bin/env python3
"""Assert the rung 0 baseline scorer measures counts and flags against a frozen target."""

from __future__ import annotations

import doctest
import json
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SCRIPTS = ROOT / "resources" / "scripts"
SCORER = SCRIPTS / "score_baseline.py"
FREEZE = SCRIPTS / "freeze_acceptance.py"
sys.path.insert(0, str(SCRIPTS))

import score_baseline  # noqa: E402


def write_jsonl(path: Path, rows: list[dict[str, object]]) -> Path:
    """Write label rows as JSON Lines."""
    path.write_text("".join(json.dumps(row) + "\n" for row in rows), encoding="utf-8", newline="\n")
    return path


def run(*args: str) -> subprocess.CompletedProcess[str]:
    """Run the scorer CLI and capture its output."""
    return subprocess.run([sys.executable, str(SCORER), *args], capture_output=True, text=True, check=False)


def last_json(stdout: str) -> dict[str, object]:
    """Return the machine-readable record the scorer prints last."""
    record = json.loads(stdout.strip().splitlines()[-1])
    assert isinstance(record, dict)
    return record


def assert_count_explore(tmp: Path) -> None:
    """Inline explore-mode target: missing prediction counts as zero and fails the gate."""
    gold = write_jsonl(tmp / "gold.jsonl", [{"image": "a", "count": 2}, {"image": "b", "count": 1}])
    pred = write_jsonl(tmp / "pred.jsonl", [{"image": "a", "count": 2}])
    res = run(
        "--gold",
        str(gold),
        "--pred",
        str(pred),
        "--task",
        "count",
        "--metric",
        "count_mae",
        "--comparator",
        "lte",
        "--threshold",
        "0.25",
    )
    assert res.returncode == 0, res.stderr
    assert "BELOW-TARGET" in res.stdout and "Missing predictions: 1" in res.stdout, res.stdout
    assert last_json(res.stdout)["observed_value"] == 0.5


def assert_flag_deliver(tmp: Path) -> None:
    """Deliver mode: the frozen acceptance file sets the target and its digest is recorded."""
    acceptance = tmp / "acceptance.json"
    frozen = subprocess.run(
        [
            sys.executable,
            str(FREEZE),
            "--out",
            str(acceptance),
            "--acceptance-id",
            "flag-v1",
            "--metric",
            "catch_rate",
            "--comparator",
            "gte",
            "--threshold",
            "0.5",
            "--unit",
            "ratio",
            "--dataset-sha256",
            "0" * 64,
            "--model-or-pipeline",
            "rung0-host-vision",
            "--confirmed-by",
            "eval",
        ],
        capture_output=True,
        text=True,
        check=False,
    )
    assert frozen.returncode == 0, frozen.stderr
    gold = write_jsonl(tmp / "gold-flag.jsonl", [{"image": "a", "flag": True}, {"image": "b", "flag": False}])
    pred = write_jsonl(tmp / "pred-flag.jsonl", [{"image": "a", "flag": True}, {"image": "b", "flag": True}])
    evidence = tmp / "evidence.json"
    res = run(
        "--gold",
        str(gold),
        "--pred",
        str(pred),
        "--task",
        "flag",
        "--acceptance",
        str(acceptance),
        "--evidence-out",
        str(evidence),
    )
    assert res.returncode == 0, res.stderr
    record = json.loads(evidence.read_text(encoding="utf-8"))
    assert record["verdict"] == "pass" and record["metrics"]["false_alarm_rate"] == 1.0
    assert record["target"]["acceptance_id"] == "flag-v1" and len(record["target"]["acceptance_sha256"]) == 64


def assert_rejections(tmp: Path) -> None:
    """Unknown images, wrong metrics, and malformed labels fail instead of scoring."""
    gold = write_jsonl(tmp / "gold-r.jsonl", [{"image": "a", "count": 1}])
    extra = write_jsonl(tmp / "pred-extra.jsonl", [{"image": "z", "count": 1}])
    bad = write_jsonl(tmp / "pred-bad.jsonl", [{"image": "a", "count": -1}])
    inline = ("--task", "count", "--metric", "count_mae", "--comparator", "lte", "--threshold", "1")
    assert run("--gold", str(gold), "--pred", str(extra), *inline).returncode == 2
    assert run("--gold", str(gold), "--pred", str(bad), *inline).returncode == 2
    wrong_metric = ("--task", "count", "--metric", "precision", "--comparator", "gte", "--threshold", "0.5")
    assert run("--gold", str(gold), "--pred", str(gold), *wrong_metric).returncode == 2
    assert run("--gold", str(gold), "--pred", str(gold), "--task", "count").returncode == 2


def main() -> int:
    """Run doctests and CLI cases."""
    failures, _ = doctest.testmod(score_baseline)
    assert failures == 0, f"{failures} doctest failure(s) in score_baseline"
    with tempfile.TemporaryDirectory() as raw:
        tmp = Path(raw)
        assert_count_explore(tmp)
        assert_flag_deliver(tmp)
        assert_rejections(tmp)
    print("baseline scorer assertions passed")
    return 0


if __name__ == "__main__":
    sys.exit(main())
