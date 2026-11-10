#!/usr/bin/env python3
"""Assert the rung 0 baseline scorer reports counts, a 95% interval, and an honest four-way verdict."""

from __future__ import annotations

import doctest
import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
SCRIPTS = ROOT / "resources" / "scripts"
SCORER = SCRIPTS / "score_baseline.py"
FREEZE = SCRIPTS / "freeze_acceptance.py"
sys.path.insert(0, str(SCRIPTS))

import score_baseline  # noqa: E402

# Wilson 95% bounds for 34 of 40, computed from the closed form 2k+z^2 +/- z*sqrt(z^2+4k(n-k)/n) over 2(n+z^2),
# independently of the scorer's implementation.
WILSON_34_OF_40 = (0.70928, 0.92939)
INCONCLUSIVE_ADVICE = (
    "The 95% interval includes the target: label more images to settle it, or treat the result as not yet proven."
)


def write_jsonl(path: Path, rows: list[dict[str, Any]]) -> Path:
    """Write label rows as JSON Lines."""
    path.write_text("".join(json.dumps(row) + "\n" for row in rows), encoding="utf-8", newline="\n")
    return path


def flag_rows(positives: int, negatives: int, prefix: str = "img") -> list[dict[str, Any]]:
    """Return gold flag rows: the first `positives` images are real cases, the rest are clean."""
    total = positives + negatives
    return [{"image": f"{prefix}{index:03d}", "flag": index < positives} for index in range(total)]


def caught_rows(gold: list[dict[str, Any]], caught: int) -> list[dict[str, Any]]:
    """Return predictions that flag exactly the first `caught` real cases and no clean image."""
    rows: list[dict[str, Any]] = []
    seen = 0
    for row in gold:
        hit = bool(row["flag"]) and seen < caught
        seen += int(bool(row["flag"]))
        rows.append({"image": row["image"], "flag": hit})
    return rows


def run(*args: str) -> subprocess.CompletedProcess[str]:
    """Run the scorer CLI and capture its output."""
    return subprocess.run([sys.executable, str(SCORER), *args], capture_output=True, text=True, check=False)


def score(
    tmp: Path,
    name: str,
    gold: list[dict[str, Any]],
    pred: list[dict[str, Any]],
    target: tuple[str, str, str, str],
) -> tuple[str, dict[str, Any]]:
    """Score inline-target fixtures and return the plain line and the machine record."""
    task, metric, comparator, threshold = target
    gold_path = write_jsonl(tmp / f"gold-{name}.jsonl", gold)
    pred_path = write_jsonl(tmp / f"pred-{name}.jsonl", pred)
    res = run(
        "--gold",
        str(gold_path),
        "--pred",
        str(pred_path),
        "--task",
        task,
        "--metric",
        metric,
        "--comparator",
        comparator,
        "--threshold",
        threshold,
    )
    assert res.returncode == 0, (name, res.returncode, res.stderr)
    lines = res.stdout.strip().splitlines()
    record = json.loads(lines[-1])
    assert isinstance(record, dict)
    return lines[0], record


def assert_reproduced_overclaims(tmp: Path) -> None:
    """Both reported overclaims now refuse instead of printing PASS."""
    catch = ("flag", "catch_rate", "gte", "0.8")
    neg_gold = [{"image": name, "flag": False} for name in "abc"]
    line, record = score(tmp, "neg", neg_gold, [{"image": "a", "flag": False}], catch)
    assert record["verdict"] == "no-verdict" and ": NO VERDICT." in line and "PASS" not in line, line
    assert "0 of 0 real cases" in line and "there are no real cases to measure" in line, line
    assert "2 of 3 gold images have no prediction" in line and "Missing predictions: 2." in line, line
    assert record["observed_value"] is None and record["passes_acceptance"] is False

    one_gold = [{"image": "a", "flag": True}] + [{"image": name, "flag": False} for name in "bcd"]
    line, record = score(tmp, "1pos", one_gold, [{"image": "a", "flag": True}], catch)
    assert record["verdict"] == "no-verdict" and ": NO VERDICT." in line and "PASS" not in line, line
    assert "1 of 1 real case (100%" in line and "only 1 real case, fewer than the 5 needed" in line, line
    assert "3 of 4 gold images have no prediction" in line and "Missing predictions: 3." in line, line
    assert record["numerator"] == 1 and record["denominator"] == 1 and record["passes_acceptance"] is False


def assert_interval_verdicts(tmp: Path) -> None:
    """The verdict follows the whole 95% interval, not the point estimate."""
    catch = ("flag", "catch_rate", "gte", "0.8")
    gold = flag_rows(40, 10)
    line, record = score(tmp, "34of40", gold, caught_rows(gold, 34), catch)
    assert record["verdict"] == "inconclusive" and record["passes_acceptance"] is False, line
    assert line.startswith("Real cases caught: 34 of 40 real cases (85%, 95% interval 71% to 93%)"), line
    assert line.endswith(f"target >= 80%: INCONCLUSIVE. {INCONCLUSIVE_ADVICE} Missing predictions: 0."), line
    assert (record["numerator"], record["denominator"], record["interval_method"]) == (34, 40, "wilson")

    line, record = score(tmp, "39of40", gold, caught_rows(gold, 39), catch)
    assert record["verdict"] == "pass" and record["passes_acceptance"] is True, line
    assert ": PASS. Missing predictions: 0." in line and "39 of 40 real cases" in line, line

    line, record = score(tmp, "20of40", gold, caught_rows(gold, 20), catch)
    assert record["verdict"] == "below-target" and ": BELOW-TARGET. Missing predictions: 0." in line, line

    false_alarm = ("flag", "false_alarm_rate", "lte", "0.5")
    line, record = score(tmp, "lte-pass", gold, caught_rows(gold, 40), false_alarm)
    assert record["verdict"] == "pass" and "0 of 10 clean images (0%, 95% interval 0% to 28%)" in line, line


def assert_refusals(tmp: Path) -> None:
    """Zero denominator, a denominator under the floor, and any missing prediction refuse a verdict."""
    catch = ("flag", "catch_rate", "gte", "0.8")
    clean = flag_rows(0, 8)
    line, record = score(tmp, "zero", clean, caught_rows(clean, 0), catch)
    assert record["verdict"] == "no-verdict" and record["denominator"] == 0, line
    assert line.endswith(
        "NO VERDICT. No verdict because there are no real cases to measure. Missing predictions: 0."
    ), line

    small = flag_rows(3, 5)
    line, record = score(tmp, "floor", small, caught_rows(small, 3), catch)
    assert record["verdict"] == "no-verdict" and record["denominator"] == 3, line
    assert "No verdict because there are only 3 real cases, fewer than the 5 needed." in line, line
    assert score_baseline.MIN_DENOMINATOR == 5

    gold = flag_rows(40, 10)
    partial = caught_rows(gold, 40)[1:]
    line, record = score(tmp, "missing", gold, partial, catch)
    assert record["verdict"] == "no-verdict" and record["missing_predictions"] == 1, line
    assert "No verdict because 1 of 50 gold images has no prediction." in line, line
    assert "Missing predictions: 1." in line and record["passes_acceptance"] is False, line


def assert_wilson_values() -> None:
    """The Wilson bounds match independently computed reference values."""
    low, high = score_baseline.wilson_interval(34, 40)
    assert abs(low - WILSON_34_OF_40[0]) < 1e-4 and abs(high - WILSON_34_OF_40[1]) < 1e-4, (low, high)
    assert score_baseline.wilson_interval(0, 10)[0] == 0.0 and score_baseline.wilson_interval(10, 10)[1] == 1.0


def count_fixture() -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Return 24 count images (22 with labeled objects) with mixed misses, extras, and empty frames."""
    truth = [2, 0, 3, 1, 2, 4, 1, 0, 2, 3, 1, 2, 2, 3, 1, 2, 4, 2, 1, 3, 2, 1, 2, 3]
    guess = [2, 0, 2, 1, 2, 3, 1, 1, 2, 3, 0, 2, 2, 3, 1, 1, 4, 2, 1, 3, 3, 1, 2, 2]
    gold = [{"image": f"frame_{index:03d}.jpg", "count": value} for index, value in enumerate(truth, 1)]
    pred = [{"image": f"frame_{index:03d}.jpg", "count": value} for index, value in enumerate(guess, 1)]
    return gold, pred


def assert_count_bootstrap(tmp: Path) -> None:
    """Count metrics use a seeded image bootstrap, a plain label, and give identical output on every run."""
    gold, pred = count_fixture()
    agreement = ("count", "catch_rate", "gte", "0.8")
    first_line, first = score(tmp, "boot-a", gold, pred, agreement)
    second_line, second = score(tmp, "boot-b", gold, pred, agreement)
    assert first_line == second_line, (first_line, second_line)
    assert (first["interval_lower"], first["interval_upper"]) == (second["interval_lower"], second["interval_upper"])
    assert first_line.startswith("Per-image count agreement: 42 of 47 labeled objects (89%, 95% interval"), first_line
    assert "Real cases caught" not in first_line and first["interval_method"] == "bootstrap-percentile"
    lower, upper = first["interval_lower"], first["interval_upper"]
    assert isinstance(lower, float) and isinstance(upper, float) and lower < 42 / 47 < upper, (lower, upper)
    assert first["min_denominator"] == score_baseline.MIN_BOOTSTRAP_UNITS == 20
    assert first["bootstrap"] == {
        "resamples": score_baseline.BOOTSTRAP_RESAMPLES,
        "seed": score_baseline.BOOTSTRAP_SEED,
    }

    line, record = score(tmp, "mae", gold, pred, ("count", "count_mae", "lte", "0.25"))
    assert line.startswith("Average count error per image: total count error 7 over 24 images (0.29,"), line
    assert record["verdict"] in {"inconclusive", "below-target"} and record["denominator"] == 24, line

    exact = ("count", "exact_count_rate", "gte", "0.5")
    line, record = score(tmp, "exact", gold, pred, exact)
    assert record["interval_method"] == "wilson" and "17 of 24 images" in line, line
    assert record["min_denominator"] == score_baseline.MIN_DENOMINATOR, record


def assert_bootstrap_refusals(tmp: Path) -> None:
    """A bootstrap metric refuses on few images and on a zero-width interval instead of printing PASS."""
    agreement = ("count", "catch_rate", "gte", "0.8")
    few = [{"image": f"f{index}", "count": 5 if index < 3 else 0} for index in range(8)]
    line, record = score(tmp, "few-units", few, few, agreement)
    assert record["verdict"] == "no-verdict" and record["denominator"] == 15, line
    assert "only 3 images with labeled objects, fewer than the 20 needed" in line, line

    # Twelve near-perfect images: the point estimate and a naive bootstrap both clear 80%.
    near_gold = [{"image": f"n{index}", "count": 4} for index in range(12)]
    near_pred = [{"image": f"n{index}", "count": 3 if index == 0 else 4} for index in range(12)]
    for metric, comparator, threshold in (
        ("catch_rate", "gte", "0.8"),
        ("count_mae", "lte", "0.5"),
        ("over_count_rate", "lte", "0.2"),
    ):
        line, record = score(tmp, f"near-{metric}", near_gold, near_pred, ("count", metric, comparator, threshold))
        assert record["verdict"] == "no-verdict" and "PASS" not in line, line
        assert "fewer than the 20 needed" in line and record["passes_acceptance"] is False, line

    # 24 perfectly counted images: every resample is identical, so the interval has zero width.
    same = [{"image": f"s{index}", "count": 2} for index in range(24)]
    for metric, comparator, threshold in (
        ("catch_rate", "gte", "0.8"),
        ("count_mae", "lte", "0.5"),
        ("over_count_rate", "lte", "0.2"),
    ):
        line, record = score(tmp, f"same-{metric}", same, same, ("count", metric, comparator, threshold))
        assert record["verdict"] == "no-verdict" and "PASS" not in line, line
        assert "every image gave the same result" in line and "exact_count_rate" in line, line
        assert record["interval_lower"] == record["interval_upper"], record

    # A predictor that answers 999 everywhere reaches every labeled object; the line says so.
    truth = [1 + index % 4 for index in range(24)]
    varied = [{"image": f"v{index}", "count": value} for index, value in enumerate(truth)]
    flood = [{"image": f"v{index}", "count": 999 if index else value - 1} for index, value in enumerate(truth)]
    line, record = score(tmp, "flood", varied, flood, ("count", "catch_rate", "gte", "0.9"))
    assert "This number does not penalize over-counting: the predictions hold" in line, line
    assert "counts beyond the labels (see over_count_rate)." in line, line
    line, record = score(tmp, "no-flood", varied, varied[:1] + varied[1:], ("count", "exact_count_rate", "gte", "0.8"))
    assert "over-counting" not in line, line

    line, record = score(tmp, "same-exact", same, same, ("count", "exact_count_rate", "gte", "0.8"))
    assert record["verdict"] == "pass" and "24 of 24 images (100%, 95% interval 86% to 100%)" in line, line


def freeze(tmp: Path, name: str, threshold: str) -> Path:
    """Freeze one flag catch-rate acceptance file through the public helper."""
    acceptance = tmp / f"acceptance-{name}.json"
    frozen = subprocess.run(
        [
            sys.executable,
            str(FREEZE),
            "--out",
            str(acceptance),
            "--acceptance-id",
            f"flag-{name}",
            "--metric",
            "catch_rate",
            "--comparator",
            "gte",
            "--threshold",
            threshold,
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
    return acceptance


def deliver(tmp: Path, name: str, acceptance: Path, caught: int) -> dict[str, Any]:
    """Score 20 real cases and 5 clean images in deliver mode and return the written evidence."""
    gold = flag_rows(20, 5)
    gold_path = write_jsonl(tmp / f"gold-{name}.jsonl", gold)
    pred_path = write_jsonl(tmp / f"pred-{name}.jsonl", caught_rows(gold, caught))
    evidence = tmp / f"evidence-{name}.json"
    res = run(
        "--gold",
        str(gold_path),
        "--pred",
        str(pred_path),
        "--task",
        "flag",
        "--acceptance",
        str(acceptance),
        "--evidence-out",
        str(evidence),
    )
    assert res.returncode == 0, res.stderr
    record = json.loads(evidence.read_text(encoding="utf-8"))
    assert isinstance(record, dict)
    return record


def assert_flag_deliver(tmp: Path) -> None:
    """Deliver mode: frozen target, recorded digest, counts, interval; only PASS counts as passed."""
    passed = deliver(tmp, "pass", freeze(tmp, "pass", "0.5"), 20)
    assert passed["verdict"] == "pass" and passed["passes_acceptance"] is True
    assert passed["target"]["acceptance_id"] == "flag-pass" and len(passed["target"]["acceptance_sha256"]) == 64
    assert (passed["numerator"], passed["denominator"], passed["observed_value"]) == (20, 20, 1.0)
    assert passed["metrics"]["false_alarm_rate"] == 0.0 and passed["metric_counts"]["accuracy"] == {
        "numerator": 25,
        "denominator": 25,
    }
    assert isinstance(passed["interval_lower"], float) and passed["interval_lower"] >= 0.5
    for field in ("measured_at", "observed_value", "gold_sha256", "pred_sha256", "images", "task"):
        assert field in passed, field

    unproven = deliver(tmp, "inconclusive", freeze(tmp, "inconclusive", "0.8"), 17)
    assert unproven["verdict"] == "inconclusive" and unproven["passes_acceptance"] is False
    assert unproven["observed_value"] == 0.85 and unproven["interval_lower"] < 0.8 < unproven["interval_upper"]


def assert_rejections(tmp: Path) -> None:
    """Unknown images, wrong metrics, and malformed labels exit 2 instead of scoring."""
    gold = write_jsonl(tmp / "gold-r.jsonl", [{"image": "a", "count": 1}])
    extra = write_jsonl(tmp / "pred-extra.jsonl", [{"image": "z", "count": 1}])
    bad = write_jsonl(tmp / "pred-bad.jsonl", [{"image": "a", "count": -1}])
    inline = ("--task", "count", "--metric", "count_mae", "--comparator", "lte", "--threshold", "1")
    assert run("--gold", str(gold), "--pred", str(extra), *inline).returncode == 2
    assert run("--gold", str(gold), "--pred", str(bad), *inline).returncode == 2
    wrong_metric = ("--task", "count", "--metric", "precision", "--comparator", "gte", "--threshold", "0.5")
    assert run("--gold", str(gold), "--pred", str(gold), *wrong_metric).returncode == 2
    assert run("--gold", str(gold), "--pred", str(gold), "--task", "count").returncode == 2

    # A target every result would meet, or one that points the wrong way, is refused before scoring.
    flags = write_jsonl(tmp / "gold-flags.jsonl", flag_rows(40, 10))
    for task, labels, metric, comparator, threshold in (
        ("flag", flags, "catch_rate", "gte", "0"),
        ("flag", flags, "catch_rate", "gte", "-1"),
        ("flag", flags, "catch_rate", "gte", "1.5"),
        ("flag", flags, "accuracy", "lte", "1"),
        ("flag", flags, "false_alarm_rate", "lte", "1"),
        ("flag", flags, "false_alarm_rate", "gte", "0.1"),
        ("count", gold, "count_mae", "gte", "1"),
        ("count", gold, "count_mae", "lte", "-0.5"),
        ("count", gold, "over_count_rate", "gte", "0.5"),
    ):
        target = ("--task", task, "--metric", metric, "--comparator", comparator, "--threshold", threshold)
        res = run("--gold", str(labels), "--pred", str(labels), *target)
        assert res.returncode == 2 and "PASS" not in res.stdout, (metric, comparator, threshold, res.stdout)
    for metric, comparator, threshold in (("catch_rate", "gte", "1"), ("false_alarm_rate", "lte", "0")):
        target = ("--task", "flag", "--metric", metric, "--comparator", comparator, "--threshold", threshold)
        assert run("--gold", str(flags), "--pred", str(flags), *target).returncode == 0, (metric, threshold)

    taken = tmp / "evidence-taken.json"
    taken.write_text("{}\n", encoding="utf-8")
    res = run("--gold", str(gold), "--pred", str(gold), *inline, "--evidence-out", str(taken))
    assert res.returncode == 2 and "evidence not written" in res.stderr and "Traceback" not in res.stderr, res.stderr
    assert taken.read_text(encoding="utf-8") == "{}\n"


def freeze_pred(gold: Path, pred: Path, ledger: Path, predictor: str) -> None:
    """Freeze one flag prediction file through the public helper."""
    frozen = subprocess.run(
        [
            sys.executable,
            str(SCRIPTS / "freeze_predictions.py"),
            "--task",
            "flag",
            "--gold",
            str(gold),
            "--pred",
            str(pred),
            "--predictor",
            predictor,
            "--session",
            "baseline-eval",
            "--skill",
            "classify-or-flag",
            "--ledger",
            str(ledger),
        ],
        capture_output=True,
        text=True,
        check=False,
    )
    assert frozen.returncode == 0, frozen.stderr


def assert_frozen_ledger(tmp: Path) -> None:
    """--frozen-ledger scores only a frozen prediction file against the gold file it was frozen with."""
    # The ledger helper refuses a ledger path with a symlinked ancestor (macOS /var is one).
    base = (tmp / "frozen").resolve()
    (base / ".vision-delivery").mkdir(parents=True)
    ledger = base / ".vision-delivery" / "ledger.jsonl"
    gold_rows = flag_rows(8, 4)
    gold = write_jsonl(base / ".vision-delivery" / "gold.jsonl", gold_rows)
    pred = write_jsonl(base / "pred.jsonl", caught_rows(gold_rows, 7))
    target = ("--task", "flag", "--metric", "catch_rate", "--comparator", "gte", "--threshold", "0.5")
    files = ("--gold", str(gold), "--pred", str(pred))

    # Without the option the scorer behaves as before; with it and no freeze, nothing is scored.
    plain = run(*files, *target)
    assert plain.returncode == 0 and "frozen" not in plain.stdout, plain.stdout
    assert "predictions_frozen" not in json.loads(plain.stdout.splitlines()[-1])
    missing = run(*files, *target, "--frozen-ledger", str(ledger))
    assert missing.returncode == 2 and "not frozen before scoring" in missing.stderr, missing.stderr
    assert missing.stdout == "", missing.stdout

    # A malformed prediction file is reported as malformed, not as unfrozen.
    malformed = base / "pred-bad.jsonl"
    malformed.write_text('{"image": "x.jpg", "flag": "yes"}\n', encoding="utf-8")
    bad = run("--gold", str(gold), "--pred", str(malformed), *target, "--frozen-ledger", str(ledger))
    assert bad.returncode == 2 and "flag must be true or false" in bad.stderr and "frozen" not in bad.stderr, bad.stderr

    # Rows the ledger helper would never write are not a freeze: not a success, or no label digests.
    digests = {"pred_sha256": score_baseline.sha256_file(pred), "gold_sha256": score_baseline.sha256_file(gold)}
    attempted = {"action": "predictions_frozen", "status": "attempted", "event_id": "x", "ts": "t"}
    attempted |= {**digests, "label_set": "gold.jsonl", "predictor": "isolated-subagent"}
    hand = {**attempted, "status": "success", "event_id": "hand", "ts": "2026-11-10T00:00:00Z"}
    ledger.write_text(json.dumps(attempted) + "\n" + json.dumps(hand) + "\n", encoding="utf-8")
    assert run(*files, *target, "--frozen-ledger", str(ledger)).returncode == 2

    freeze_pred(gold, pred, ledger, "isolated-subagent")
    frozen = run(*files, *target, "--frozen-ledger", str(ledger))
    assert frozen.returncode == 0, frozen.stderr
    line, record = frozen.stdout.splitlines()[0], json.loads(frozen.stdout.splitlines()[-1])
    note = (
        "Predictions and labels were fixed before this scoring run; the freeze records the predictions as written by "
        "an isolated subagent. The label file was not written by the labeling helper."
    )
    assert line == f"{plain.stdout.splitlines()[0]} {note}", line
    assert "frozen before scoring" not in frozen.stdout, frozen.stdout
    block = record["predictions_frozen"]
    assert set(block) == {
        "event_id",
        "frozen_at",
        "label_set",
        "pred_sha256",
        "gold_sha256",
        "predictor_declared",
        "label_entry",
        "labels_changed_after_freeze",
        "labels_changed_after_predictions",
        "ledger_is_project_ledger",
        "independent",
    }, block
    assert block["predictor_declared"] == "isolated-subagent" and block["label_entry"] == "unrecorded", block
    assert block["independent"] is True and block["ledger_is_project_ledger"] is True, block
    assert (block["pred_sha256"], block["gold_sha256"]) == (digests["pred_sha256"], digests["gold_sha256"]), block
    assert block["event_id"].startswith("manual:baseline-eval:predictions_frozen:"), record

    # Labels changed after the freeze, or predictions changed after it, are refused before scoring.
    original = gold.read_bytes()
    gold.write_bytes(original.replace(b'"flag": false', b'"flag": true', 1))
    changed = run(*files, *target, "--frozen-ledger", str(ledger))
    assert changed.returncode == 2 and "gold labels changed after these predictions were frozen" in changed.stderr
    gold.write_bytes(original)
    pred.write_bytes(pred.read_bytes().replace(b'"flag": false', b'"flag": true', 1))
    tampered = run(*files, *target, "--frozen-ledger", str(ledger))
    assert tampered.returncode == 2 and "not frozen before scoring" in tampered.stderr, tampered.stderr

    # A same-session prediction is scored, and the line says independence was not enforced.
    freeze_pred(gold, pred, ledger, "same-session")
    same = run(*files, *target, "--frozen-ledger", str(ledger))
    assert same.returncode == 0 and "so independence was not enforced." in same.stdout.splitlines()[0], same.stdout
    block = json.loads(same.stdout.splitlines()[-1])["predictions_frozen"]
    assert block["predictor_declared"] == "same-session" and block["independent"] is False, block

    # A ledger that is not the project ledger is still read, with a warning and the fact in the evidence.
    second = base / ".vision-delivery" / "second.jsonl"
    freeze_pred(gold, pred, second, "isolated-subagent")
    other = run(*files, *target, "--frozen-ledger", str(second))
    assert other.returncode == 0 and "is not a project ledger" in other.stderr, other.stderr
    assert json.loads(other.stdout.splitlines()[-1])["predictions_frozen"]["ledger_is_project_ledger"] is False
    if os.name == "posix":
        link = base / "ledger-link.jsonl"
        link.symlink_to(ledger)
        assert run(*files, *target, "--frozen-ledger", str(link)).returncode == 2


def main() -> int:
    """Run doctests and CLI cases."""
    failures, _ = doctest.testmod(score_baseline)
    assert failures == 0, f"{failures} doctest failure(s) in score_baseline"
    assert_wilson_values()
    with tempfile.TemporaryDirectory() as raw:
        tmp = Path(raw)
        assert_reproduced_overclaims(tmp)
        assert_interval_verdicts(tmp)
        assert_refusals(tmp)
        assert_count_bootstrap(tmp)
        assert_bootstrap_refusals(tmp)
        assert_flag_deliver(tmp)
        assert_rejections(tmp)
        assert_frozen_ledger(tmp)
    print("baseline scorer assertions passed")
    return 0


if __name__ == "__main__":
    sys.exit(main())
