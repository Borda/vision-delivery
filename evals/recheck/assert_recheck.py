#!/usr/bin/env python3
"""Exercise rechecking through real acceptance, scorer, and ledger command-line tools."""

from __future__ import annotations

import doctest
import hashlib
import io
import json
import subprocess
import sys
import tempfile
from contextlib import redirect_stderr, redirect_stdout
from dataclasses import dataclass, replace
from pathlib import Path
from types import ModuleType
from typing import Any
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[2]
SCRIPTS = ROOT / "resources" / "scripts"
RECHECK = SCRIPTS / "recheck.py"


@dataclass(frozen=True)
class Fixture:
    """Paths belonging to one real, scored baseline and its frozen acceptance."""

    folder: Path
    acceptance: Path
    baseline: Path
    gold: Path
    pred: Path
    ledger: Path


def _run(script: Path, *arguments: str) -> subprocess.CompletedProcess[str]:
    """Capture one real CLI invocation using this script's interpreter."""
    return subprocess.run(
        [sys.executable, str(script), *arguments], capture_output=True, text=True, encoding="utf-8", check=False
    )


def _write_json(path: Path, value: Any) -> None:
    """Write fixture JSON with deterministic text encoding and newlines."""
    path.write_text(json.dumps(value) + "\n", encoding="utf-8", newline="\n")


def _sample(folder: Path, name: str, flagged: int, total: int = 200, truth: bool = True) -> tuple[Path, Path]:
    """Create distinct labeled samples with an explicit number of flagged predictions."""
    gold, pred = folder / f"{name}-gold.jsonl", folder / f"{name}-pred.jsonl"
    rows = [{"image": f"{name}-{index}", "flag": truth} for index in range(total)]
    guesses = [{"image": row["image"], "flag": index < flagged} for index, row in enumerate(rows)]
    gold.write_text("".join(json.dumps(row) + "\n" for row in rows), encoding="utf-8", newline="\n")
    pred.write_text("".join(json.dumps(row) + "\n" for row in guesses), encoding="utf-8", newline="\n")
    return gold, pred


def _fixture(folder: Path, comparator: str = "gte") -> Fixture:
    """Freeze a target and score its baseline with the real tools."""
    folder.mkdir()
    ledger = folder / ".vision-delivery" / "ledger.jsonl"
    ledger.parent.mkdir()
    truth = comparator == "gte"
    gold, pred = _sample(ledger.parent, "baseline", 160 if truth else 40, truth=truth)
    acceptance, baseline = folder / "acceptance.json", folder / "baseline.json"
    metric = "catch_rate" if comparator == "gte" else "false_alarm_rate"
    frozen = _run(
        SCRIPTS / "freeze_acceptance.py",
        "--out",
        str(acceptance),
        "--acceptance-id",
        folder.name,
        "--metric",
        metric,
        "--comparator",
        comparator,
        "--threshold",
        "0.7" if truth else "0.3",
        "--unit",
        "fraction",
        "--dataset-sha256",
        hashlib.sha256(gold.read_bytes()).hexdigest(),
        "--model-or-pipeline",
        "fixture-pipeline",
        "--confirmed-by",
        "fixture-owner",
    )
    assert frozen.returncode == 0, frozen.stderr
    scored = _run(
        SCRIPTS / "score_baseline.py",
        "--acceptance",
        str(acceptance),
        "--gold",
        str(gold),
        "--pred",
        str(pred),
        "--task",
        "flag",
        "--evidence-out",
        str(baseline),
    )
    assert scored.returncode == 0, scored.stderr
    ledger.write_text("", encoding="utf-8", newline="\n")
    return Fixture(folder, acceptance, baseline, gold, pred, ledger)


def _recheck(fixture: Fixture, gold: Path, pred: Path, output: Path, *extra: str) -> subprocess.CompletedProcess[str]:
    """Run the wrapper with stable session identity and optional boundary overrides."""
    return _run(RECHECK, *_arguments(fixture, gold, pred, output), *extra)


def _arguments(fixture: Fixture, gold: Path, pred: Path, output: Path) -> list[str]:
    """Build the real CLI arguments also used for controlled child-failure checks."""
    return [
        "--acceptance",
        str(fixture.acceptance),
        "--baseline-evidence",
        str(fixture.baseline),
        "--gold",
        str(gold),
        "--pred",
        str(pred),
        "--task",
        "flag",
        "--ledger",
        str(fixture.ledger),
        "--session",
        "monitor",
        "--evidence-out",
        str(output),
    ]


def _measured(
    fixture: Fixture,
    name: str,
    flagged: int,
    drift: str,
    shift: str,
    *,
    total: int = 200,
    truth: bool = True,
) -> dict[str, Any]:
    """Assert CLI, evidence, summary, and ledger agree on an independently expected result."""
    gold, pred = _sample(fixture.folder, name, flagged, total, truth)
    output = fixture.folder / f"{name}-evidence.json"
    done = _recheck(fixture, gold, pred, output)
    assert done.returncode == 0, (name, done.stderr, done.stdout)
    record = json.loads(output.read_text(encoding="utf-8"))
    lines = done.stdout.splitlines()
    assert len(lines) == 3 and json.loads(lines[-1]) == record, done.stdout
    assert f"Recheck against acceptance {fixture.folder.name}: {drift.upper()}." in lines[1], lines[1]
    baseline = json.loads(fixture.baseline.read_text(encoding="utf-8"))
    expected = {
        "baseline_evidence_sha256": hashlib.sha256(fixture.baseline.read_bytes()).hexdigest(),
        "baseline_measured_at": baseline["measured_at"],
        "baseline_observed_value": baseline["observed_value"],
        "baseline_gold_sha256": baseline["gold_sha256"],
        "drift": drift,
        "shifted_from_baseline": shift,
        "image_overlap_checked": True,
        "predictions_frozen": "not-frozen",
    }
    assert record["recheck"] == expected, record
    assert f"Baseline {baseline['observed_value'] if baseline['observed_value'] is not None else 'none'} " in lines[1]
    assert f"on {baseline['measured_at']}; now " in lines[1], lines[1]
    sentences = {
        "no": "The fresh interval includes the baseline value.",
        "unknown": "No interval to compare with the baseline value.",
        "better": "The fresh interval lies wholly above the baseline value.",
        "worse": "The fresh interval lies wholly below the baseline value.",
    }
    sentence = sentences[shift]
    if record["target"]["comparator"] == "lte":
        sentence = sentence.replace("above", "BELOW").replace("below", "above").replace("BELOW", "below")
    assert sentence in lines[1], lines[1]
    caveat = "This compares the fresh interval with the baseline's single value; it is not a test of change."
    assert lines[1].count(caveat) == (0 if shift == "unknown" else 1), lines[1]
    assert lines[1].endswith("The fresh predictions were not frozen before scoring."), lines[1]
    rows = [json.loads(line) for line in fixture.ledger.read_text(encoding="utf-8").splitlines()]
    row = rows[-1]
    assert row["action"] == "recheck_measured" and row["status"] == "success", row
    assert row["source"] == "skill" and row["skill"] == "deliver-cv-project", row
    assert row["acceptance_id"] == fixture.folder.name, row
    assert row["acceptance_sha256"] == hashlib.sha256(fixture.acceptance.read_bytes()).hexdigest(), row
    identities = (
        row["acceptance_sha256"],
        expected["baseline_evidence_sha256"],
        record["pred_sha256"],
        record["gold_sha256"],
    )
    suffix = "-".join(digest[:12] for digest in identities)
    assert row["event_id"] == f"manual:monitor:recheck_measured:{suffix}", row
    assert row["notes"] == lines[1], row
    assert row["evidence_sha256"] == hashlib.sha256(output.read_bytes()).hexdigest(), row
    assert (row["drift"], row["shifted"], row["predictions_frozen"]) == (drift, shift, "not-frozen"), row
    assert not list(fixture.folder.glob(".recheck-*"))
    return record


def _refused(fixture: Fixture, name: str, gold: Path, pred: Path, *extra: str) -> str:
    """Assert a refusal preserves ledger bytes, existing output, and temporary-file state."""
    output = fixture.folder / f"refused-{name}.json"
    before = fixture.ledger.read_bytes() if fixture.ledger.exists() else None
    existing = output.read_bytes() if output.exists() else None
    done = _recheck(fixture, gold, pred, output, *extra)
    assert done.returncode == 2, (name, done.returncode, done.stdout, done.stderr)
    assert not done.stdout and len(done.stderr.splitlines()) == 1, done
    assert done.stderr.startswith("recheck-error: "), done.stderr
    assert fixture.ledger.read_bytes() == before if before is not None else not fixture.ledger.exists(), name
    assert output.read_bytes() == existing if existing is not None else not output.exists(), name
    assert not list(fixture.folder.glob(".recheck-*")), name
    return done.stderr


def _assert_statuses_and_shifts(fixture: Fixture, lower: Fixture) -> None:
    """Cover every drift status and both directions of interval-to-baseline comparison."""
    _measured(fixture, "holds", 200, "holds", "better")
    assert len(fixture.ledger.read_text(encoding="utf-8").splitlines()) == 1
    _measured(fixture, "drift", 100, "drifted", "worse")
    _measured(fixture, "same", 160, "holds", "no")
    _measured(fixture, "borderline", 140, "uncertain", "worse")
    _measured(fixture, "small", 3, "uncertain", "no", total=3)
    _measured(fixture, "no-interval", 0, "uncertain", "unknown", truth=False)
    _measured(lower, "lte-worse", 100, "drifted", "worse", truth=False)
    _measured(lower, "lte-better", 0, "holds", "better", truth=False)
    _measured(lower, "lte-same", 40, "holds", "no", truth=False)


def _assert_idempotence(fixture: Fixture) -> None:
    """Reusing scored files with a new evidence path leaves the ledger byte-identical."""
    before = fixture.ledger.read_bytes()
    done = _recheck(
        fixture,
        fixture.folder / "holds-gold.jsonl",
        fixture.folder / "holds-pred.jsonl",
        fixture.folder / "holds-again.json",
    )
    assert done.returncode == 0, done.stderr
    assert fixture.ledger.read_bytes() == before
    assert (fixture.folder / "holds-again.json").read_bytes() == (fixture.folder / "holds-evidence.json").read_bytes()
    assert json.loads((fixture.folder / "holds-again.json").read_text(encoding="utf-8"))["recheck"]["drift"] == "holds"


def _altered_baseline(fixture: Fixture, name: str, record: dict[str, Any], gold: Path, pred: Path) -> str:
    """Check a single provenance mutation without modifying the real baseline."""
    altered = fixture.folder / f"altered-{name}.json"
    _write_json(altered, record)
    return _refused(replace(fixture, baseline=altered), name, gold, pred)


def _assert_baseline_integrity(fixture: Fixture) -> None:
    """Refuse rechecks, forged provenance, nonpassing baselines, and concealed original labels."""
    gold, pred = _sample(fixture.folder, "integrity", 200)
    baseline = json.loads(fixture.baseline.read_text(encoding="utf-8"))
    _refused(
        replace(fixture, baseline=fixture.folder / "holds-evidence.json"), "prior-recheck", fixture.gold, fixture.pred
    )
    _altered_baseline(fixture, "gold-digest", {**baseline, "gold_sha256": "0" * 64}, gold, pred)
    target = {**baseline["target"], "acceptance_id": "another-target"}
    _altered_baseline(fixture, "target-id", {**baseline, "target": target}, gold, pred)
    _altered_baseline(fixture, "verdict", {**baseline, "verdict": "below-target"}, gold, pred)
    _altered_baseline(fixture, "missing-verdict", {k: v for k, v in baseline.items() if k != "verdict"}, gold, pred)
    _altered_baseline(fixture, "hidden-original", {**baseline, "gold_sha256": "0" * 64}, fixture.gold, fixture.pred)


def _assert_semantic_freshness(fixture: Fixture) -> None:
    """Refuse byte-distinct copies and report only the count of shared image identities."""
    original = fixture.gold.read_text(encoding="utf-8").splitlines()
    reordered = fixture.folder / "reordered.jsonl"
    reordered.write_text("\n".join(reversed(original)) + "\n", encoding="utf-8", newline="\n")
    reason = _refused(fixture, "reordered", reordered, fixture.pred)
    assert "label maps match" in reason, reason
    spaced = fixture.folder / "whitespace.jsonl"
    spaced.write_text("\n".join("  " + line + "  " for line in original) + "\n", encoding="utf-8", newline="\n")
    reason = _refused(fixture, "whitespace", spaced, fixture.pred)
    assert "label maps match" in reason, reason
    gold, pred = _sample(fixture.folder, "overlap", 200)
    rows = [json.loads(line) for line in gold.read_text(encoding="utf-8").splitlines()]
    rows[0]["image"] = "baseline-0"
    gold.write_text("".join(json.dumps(row) + "\n" for row in rows), encoding="utf-8", newline="\n")
    reason = _refused(fixture, "overlap", gold, pred)
    assert "shares 1 image" in reason and "baseline-0" not in reason, reason


def _assert_overlap_unavailable(fixture: Fixture) -> None:
    """Distinguish automatic discovery, absent originals, and explicit baseline labels."""
    original = fixture.folder / "original-labels.jsonl"
    fixture.gold.rename(original)
    gold, pred = _sample(fixture.folder, "no-original", 200)
    output = fixture.folder / "unchecked.json"
    done = _recheck(fixture, gold, pred, output)
    assert done.returncode == 0, done.stderr
    assert json.loads(output.read_text(encoding="utf-8"))["recheck"]["image_overlap_checked"] is False
    assert done.stdout.splitlines()[1].count("Overlap with the baseline images was not checked.") == 1
    gold, pred = _sample(fixture.folder, "explicit-original", 200)
    output = fixture.folder / "checked.json"
    done = _recheck(fixture, gold, pred, output, "--baseline-gold", str(original))
    assert done.returncode == 0, done.stderr
    assert json.loads(output.read_text(encoding="utf-8"))["recheck"]["image_overlap_checked"] is True
    assert "Overlap with the baseline images was not checked." not in done.stdout
    _refused(fixture, "wrong-baseline-gold", gold, pred, "--baseline-gold", str(gold))


def _assert_new_acceptance(fixture: Fixture) -> None:
    """The same fresh files can measure a new acceptance without event-ID collision."""
    gold, pred = _sample(fixture.folder, "new-target", 200)
    first = _recheck(fixture, gold, pred, fixture.folder / "old-target-evidence.json")
    assert first.returncode == 0, first.stderr
    acceptance = json.loads(fixture.acceptance.read_text(encoding="utf-8"))
    new_acceptance, new_baseline = fixture.folder / "new-acceptance.json", fixture.folder / "new-baseline.json"
    _write_json(new_acceptance, {**acceptance, "acceptance_id": "new-target"})
    scored = _run(
        SCRIPTS / "score_baseline.py",
        "--acceptance",
        str(new_acceptance),
        "--gold",
        str(fixture.gold),
        "--pred",
        str(fixture.pred),
        "--task",
        "flag",
        "--evidence-out",
        str(new_baseline),
    )
    assert scored.returncode == 0, scored.stderr
    second = _recheck(
        replace(fixture, acceptance=new_acceptance, baseline=new_baseline),
        gold,
        pred,
        fixture.folder / "new-target-evidence.json",
    )
    assert second.returncode == 0, second.stderr
    rows = [json.loads(line) for line in fixture.ledger.read_text(encoding="utf-8").splitlines()]
    assert len(rows) == 2 and rows[0]["event_id"] != rows[1]["event_id"], rows
    assert rows[0]["acceptance_sha256"] != rows[1]["acceptance_sha256"], rows


def _assert_refusals(fixture: Fixture, other: Fixture) -> None:
    """Exercise all preflight refusals and scorer failure against an already populated ledger."""
    gold, pred = _sample(fixture.folder, "refusals", 200)
    invalid = fixture.folder / "not-scorer.json"
    _write_json(invalid, {})
    _refused(replace(fixture, baseline=invalid), "not-scorer", gold, pred)
    baseline = json.loads(fixture.baseline.read_text(encoding="utf-8"))
    for field in ("observed_value", "gold_sha256", "measured_at", "task"):
        _write_json(invalid, {key: value for key, value in baseline.items() if key != field})
        _refused(replace(fixture, baseline=invalid), f"missing-{field}", gold, pred)
    for field in ("acceptance_id", "acceptance_sha256", "metric"):
        broken = {**baseline, "target": {key: value for key, value in baseline["target"].items() if key != field}}
        _write_json(invalid, broken)
        _refused(replace(fixture, baseline=invalid), f"missing-{field}", gold, pred)
    _refused(replace(fixture, acceptance=other.acceptance), "acceptance", gold, pred)
    _refused(fixture, "task", gold, pred, "--task", "count")
    _refused(fixture, "same-gold", fixture.gold, fixture.pred)
    existing = fixture.folder / "refused-existing.json"
    existing.write_text("keep me\n", encoding="utf-8", newline="\n")
    _refused(fixture, "existing", gold, pred)
    linked_output = fixture.folder / "refused-linked-output.json"
    linked_output.symlink_to(existing)
    _refused(fixture, "linked-output", gold, pred)
    malformed = fixture.folder / "malformed.jsonl"
    malformed.write_text("not json\n", encoding="utf-8", newline="\n")
    reason = _refused(fixture, "scorer", gold, malformed)
    direct = _run(
        SCRIPTS / "score_baseline.py",
        "--gold",
        str(gold),
        "--pred",
        str(malformed),
        "--task",
        "flag",
        "--acceptance",
        str(fixture.acceptance),
    )
    assert direct.stderr.strip().splitlines()[-1] in reason, reason
    _write_json(invalid, {**baseline, "task": "future-task"})
    reason = _refused(replace(fixture, baseline=invalid), "future-task", gold, pred, "--task", "future-task")
    assert "future-task" in reason, reason


def _assert_symlinks(fixture: Fixture) -> None:
    """Reject symlinks for every input path, including an optional frozen ledger."""
    gold, pred = _sample(fixture.folder, "links", 200)
    for field in ("acceptance", "baseline", "ledger"):
        link = fixture.folder / f"link-{field}"
        link.symlink_to(getattr(fixture, field))
        _refused(replace(fixture, **{field: link}), f"link-{field}", gold, pred)
    for name, target in (("gold", gold), ("pred", pred)):
        link = fixture.folder / f"link-{name}"
        link.symlink_to(target)
        _refused(fixture, f"link-{name}", link if name == "gold" else gold, link if name == "pred" else pred)
    link = fixture.folder / "link-frozen-ledger"
    link.symlink_to(fixture.ledger)
    _refused(fixture, "link-frozen-ledger", gold, pred, "--frozen-ledger", str(link))
    _refused(fixture, "link-baseline-gold", gold, pred, "--baseline-gold", str(link))
    parent = fixture.folder / "linked-parent"
    parent.symlink_to(fixture.folder, target_is_directory=True)
    _refused(fixture, "linked-parent", parent / gold.name, pred)


def _assert_ledger_rollback(fixture: Fixture) -> None:
    """A real helper refusal after scoring removes newly written evidence."""
    gold, pred = fixture.folder / "holds-gold.jsonl", fixture.folder / "holds-pred.jsonl"
    reason = _refused(fixture, "ledger", gold, pred, "--skill", "different-skill")
    assert "ledger helper refused" in reason, reason


def _assert_scorer_folder_cleanup(fixture: Fixture) -> None:
    """A scorer refusal creates neither the evidence file nor its missing parent folders."""
    gold, _ = _sample(fixture.folder, "folder-refusal", 200)
    pred = fixture.folder / "invalid-pred.jsonl"
    pred.write_text("not JSON\n", encoding="utf-8", newline="\n")
    parent = fixture.folder / "never-created" / "nested"
    before = fixture.ledger.read_bytes()
    done = _recheck(fixture, gold, pred, parent / "evidence.json")
    assert done.returncode == 2 and not done.stdout, done
    assert not parent.parent.exists(), done.stderr
    assert fixture.ledger.read_bytes() == before


def _assert_timeout(module: ModuleType, fixture: Fixture) -> None:
    """A bounded scorer timeout is a refusal with no output folders or ledger changes."""
    gold, pred = _sample(fixture.folder, "timeout", 200)
    output = fixture.folder / "timeout-folder" / "evidence.json"
    argv = [str(RECHECK), *_arguments(fixture, gold, pred, output)]
    before, stderr, stdout = fixture.ledger.read_bytes(), io.StringIO(), io.StringIO()
    with (
        patch.object(sys, "argv", argv),
        patch.object(subprocess, "run", autospec=True, side_effect=subprocess.TimeoutExpired("scorer", 900)) as child,
        redirect_stderr(stderr),
        redirect_stdout(stdout),
    ):
        result = module.main()
    assert result == 2 and "timed out after 900 seconds" in stderr.getvalue(), stderr.getvalue()
    assert child.call_count == 1 and child.call_args.kwargs["timeout"] == 900, child.call_args
    assert not output.parent.exists() and not stdout.getvalue()
    assert fixture.ledger.read_bytes() == before


def _assert_interrupted_append(module: ModuleType, fixture: Fixture) -> None:
    """An interrupt at the ledger child removes evidence and preserves the original ledger."""
    gold, pred = _sample(fixture.folder, "interrupt", 200)
    scored = _run(
        SCRIPTS / "score_baseline.py",
        "--gold",
        str(gold),
        "--pred",
        str(pred),
        "--acceptance",
        str(fixture.acceptance),
        "--task",
        "flag",
    )
    assert scored.returncode == 0, scored.stderr
    output = fixture.folder / "interrupted.json"
    argv = [str(RECHECK), *_arguments(fixture, gold, pred, output)]
    before = fixture.ledger.read_bytes()
    with (
        patch.object(sys, "argv", argv),
        patch.object(subprocess, "run", autospec=True, side_effect=[scored, KeyboardInterrupt()]),
    ):
        try:
            module.main()
        except KeyboardInterrupt:
            pass
        else:
            raise AssertionError("append interrupt was swallowed")
    assert not output.exists() and fixture.ledger.read_bytes() == before


def _assert_evidence_boundary_interrupt(module: ModuleType, fixture: Fixture) -> None:
    """An interrupt immediately after evidence writing still removes the owned file."""
    output = fixture.folder / "boundary-interrupted.json"
    try:
        with module._write_exclusive(output, {"written": True}):
            assert output.is_file()
            raise KeyboardInterrupt()
    except KeyboardInterrupt:
        pass
    else:
        raise AssertionError("evidence boundary interrupt was swallowed")
    assert not output.exists()
    existing = fixture.folder / "existing-evidence.json"
    existing.write_text("preserve\n", encoding="utf-8", newline="\n")
    try:
        with module._write_exclusive(existing, {}):
            raise AssertionError("existing evidence was replaced")
    except FileExistsError:
        pass
    assert existing.read_text(encoding="utf-8") == "preserve\n"


def _assert_evidence_binding(fixture: Fixture) -> None:
    """The ledger helper refuses absent evidence and evidence bound to another acceptance."""
    before = fixture.ledger.read_bytes()
    command = (
        "--ledger",
        str(fixture.ledger),
        "--session",
        "hand-call",
        "--skill",
        "deliver-cv-project",
        "--action",
        "recheck_measured",
        "--status",
        "success",
        "--acceptance",
        str(fixture.acceptance),
        "--event-id",
        "manual:hand-call:recheck_measured:evidence-binding",
    )
    missing = _run(ROOT / "scripts" / "ledger_append.py", *command)
    assert missing.returncode == 2 and "a successful recheck_measured needs --evidence" in missing.stderr, missing
    evidence = fixture.folder / "foreign-evidence.json"
    _write_json(
        evidence,
        {
            "target": {"acceptance_sha256": "0" * 64},
            "recheck": {"drift": "holds", "shifted_from_baseline": "no"},
        },
    )
    foreign = _run(ROOT / "scripts" / "ledger_append.py", *command, "--evidence", str(evidence))
    assert foreign.returncode == 2 and "recheck evidence is bound to a different acceptance" in foreign.stderr, foreign
    assert fixture.ledger.read_bytes() == before


def _assert_output_ledger_collision(fixture: Fixture) -> None:
    """A new ledger cannot append into the exclusively created evidence JSON."""
    gold, pred = _sample(fixture.folder, "collision", 200)
    collision = fixture.folder / "refused-collision.json"
    reason = _refused(replace(fixture, ledger=collision), "collision", gold, pred)
    assert "evidence output and ledger must use different paths" in reason, reason
    alias = fixture.folder / ".." / fixture.folder.name / collision.name
    _refused(replace(fixture, ledger=alias), "collision", gold, pred)


def _assert_frozen_ledger(fixture: Fixture, predictor: str, state: str) -> None:
    """Forward optional freeze enforcement and retain the scorer's freeze evidence and plain line."""
    gold, pred = _sample(fixture.ledger.parent, "frozen", 200)
    reason = _refused(fixture, "unfrozen", gold, pred, "--frozen-ledger", str(fixture.ledger))
    assert "not frozen before scoring" in reason, reason
    frozen = _run(
        SCRIPTS / "freeze_predictions.py",
        "--gold",
        str(gold),
        "--pred",
        str(pred),
        "--task",
        "flag",
        "--predictor",
        predictor,
        "--ledger",
        str(fixture.ledger),
        "--session",
        "monitor",
        "--skill",
        "fixture",
    )
    assert frozen.returncode == 0, frozen.stderr
    output = fixture.folder / "frozen-evidence.json"
    done = _recheck(fixture, gold, pred, output, "--frozen-ledger", str(fixture.ledger), "--skill", "custom-monitor")
    direct = _run(
        SCRIPTS / "score_baseline.py",
        "--gold",
        str(gold),
        "--pred",
        str(pred),
        "--task",
        "flag",
        "--acceptance",
        str(fixture.acceptance),
        "--frozen-ledger",
        str(fixture.ledger),
    )
    assert done.returncode == direct.returncode == 0, (done.stderr, direct.stderr)
    assert done.stdout.splitlines()[0] == direct.stdout.splitlines()[0]
    record = json.loads(output.read_text(encoding="utf-8"))
    original = json.loads(direct.stdout.splitlines()[-1])
    assert {key: value for key, value in record.items() if key not in {"recheck", "measured_at"}} == {
        key: value for key, value in original.items() if key != "measured_at"
    }
    assert record["predictions_frozen"]["pred_sha256"] == record["pred_sha256"]
    assert record["recheck"]["predictions_frozen"] == state, record
    warning = "The freeze says this is not an independent measurement."
    assert done.stdout.splitlines()[1].count(warning) == (0 if state == "independent" else 1), done.stdout
    row = json.loads(fixture.ledger.read_text(encoding="utf-8").splitlines()[-1])
    assert row["skill"] == "custom-monitor" and row["action"] == "recheck_measured", row
    assert row["predictions_frozen"] == state, row
    assert not list(fixture.folder.glob(".recheck-*"))


def main() -> int:
    """Run isolated CLI acceptance checks and module doctests.

    Examples:
        Run ``python3 evals/recheck/assert_recheck.py`` to print the passing assertion message.
    """
    with tempfile.TemporaryDirectory() as raw:
        folder = Path(raw).resolve()
        fixture, lower = _fixture(folder / "gte"), _fixture(folder / "lte", "lte")
        _assert_statuses_and_shifts(fixture, lower)
        _assert_idempotence(fixture)
        _assert_refusals(fixture, lower)
        _assert_baseline_integrity(fixture)
        _assert_semantic_freshness(fixture)
        _assert_symlinks(fixture)
        _assert_ledger_rollback(fixture)
        _assert_scorer_folder_cleanup(fixture)
        _assert_evidence_binding(fixture)
        _assert_output_ledger_collision(fixture)
        _assert_overlap_unavailable(_fixture(folder / "overlap-unavailable"))
        _assert_new_acceptance(_fixture(folder / "new-acceptance"))
        _assert_frozen_ledger(_fixture(folder / "frozen-ledger"), "same-session", "not-independent")
        _assert_frozen_ledger(_fixture(folder / "independent"), "isolated-subagent", "independent")
        sys.path.insert(0, str(SCRIPTS))
        import recheck  # noqa: PLC0415

        _assert_timeout(recheck, fixture)
        _assert_interrupted_append(recheck, fixture)
        _assert_evidence_boundary_interrupt(recheck, fixture)

    result = doctest.testmod(recheck)
    assert result.attempted > 0 and result.failed == 0, result
    print("recheck assertions passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
