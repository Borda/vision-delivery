#!/usr/bin/env python3
"""Assert that check_delivery.py passes a complete delivery and names the first broken step.

The script builds one delivery project in a temporary folder with the real helpers, then copies
it once per case and breaks one thing. It stops at the first failed case and exits non-zero.
Pass case names as arguments to run only those cases.
"""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import subprocess
import sys
import tempfile
from collections.abc import Callable
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
SCRIPTS = ROOT / "resources" / "scripts"
CHECK = SCRIPTS / "check_delivery.py"
RECHECK = SCRIPTS / "recheck.py"
FIXTURE = ROOT / "evals" / "artifacts" / "fixtures" / "hosted-client"
STATE = ".vision-delivery"
ACCEPTANCE_ID = "artifact-fixture/v1"
MODEL_ID = "committed deterministic fixture v1"
IMAGES = 40
LIVE_COMMAND = [sys.executable, "inference.py"]
LIVE_OUTPUT = (
    json.dumps(
        {
            "artifact_kind": "hosted-client",
            "count": 1,
            "predictions": [{"class": "fixture", "confidence": 0.9}],
        },
        sort_keys=True,
    )
    + "\n"
).encode()
LEDGER_ACTIONS = ("baseline_measured", "artifact_verified", "delivery_handoff_emitted", "crossover_delivered")
PASSED_LINE = (
    f"DELIVERY CHECKS PASSED for acceptance {ACCEPTANCE_ID}. Every record agrees with the frozen target and with the"
    " artifact on disk; it is not shown that the scored predictions came from this artifact, and nothing is signed."
)
FAILED_PREFIX = "DELIVERY CHECKS FAILED: "
STEPS = (
    "acceptance",
    "baseline",
    "handoff",
    "self-test",
    "check-contract",
    "live-check",
    "economics",
    "ledger",
    "later-records",
)


def run(command: list[str], *, cwd: Path, env: dict[str, str] | None = None) -> subprocess.CompletedProcess[str]:
    """Run one bounded helper and capture its output without raising on its exit status."""
    return subprocess.run(
        command,
        cwd=cwd,
        text=True,
        capture_output=True,
        timeout=60,
        check=False,
        env=env if env is not None else {**os.environ, "SENTINEL_FIXTURE_TOKEN": "fixture-only"},
    )


def must(process: subprocess.CompletedProcess[str], label: str) -> None:
    """Fail the eval when a fixture-building helper fails."""
    if process.returncode != 0:
        raise AssertionError(f"{label} failed ({process.returncode}): {process.stdout} {process.stderr}")


def sha256(path: Path) -> str:
    """Return the SHA-256 of one fixture file."""
    return hashlib.sha256(path.read_bytes()).hexdigest()


def read_json(path: Path) -> dict[str, Any]:
    """Read one JSON object from a fixture file."""
    return json.loads(path.read_text(encoding="utf-8"))


def write_json(path: Path, value: dict[str, Any]) -> None:
    """Write one JSON object to a fixture file."""
    path.write_text(json.dumps(value, indent=2) + "\n", encoding="utf-8", newline="\n")


def write_labels(path: Path, flags: list[bool], prefix: str = "img") -> None:
    """Write one flag label file with one row per image."""
    rows = "".join(
        json.dumps({"image": f"{prefix}_{index:02d}.jpg", "flag": flag}) + "\n" for index, flag in enumerate(flags)
    )
    path.write_text(rows, encoding="utf-8", newline="\n")


def freeze_acceptance(root: Path, out: Path, threshold: str, dataset_sha256: str) -> None:
    """Freeze one acceptance revision through the real helper."""
    command = [sys.executable, str(SCRIPTS / "freeze_acceptance.py"), "--out", str(out)]
    command += ["--acceptance-id", ACCEPTANCE_ID, "--metric", "accuracy", "--comparator", "gte"]
    command += ["--threshold", threshold, "--unit", "fraction", "--dataset-sha256", dataset_sha256]
    command += ["--model-or-pipeline", MODEL_ID, "--confirmed-by", "fixture owner"]
    must(run(command, cwd=root), "freeze acceptance")


def score(root: Path, acceptance: Path, out: Path) -> None:
    """Score the fixture predictions against one acceptance revision through the real scorer."""
    state = root / STATE
    command = [sys.executable, str(SCRIPTS / "score_baseline.py"), "--gold", str(state / "gold.jsonl")]
    command += ["--pred", str(state / "pred.jsonl"), "--task", "flag", "--acceptance", str(acceptance)]
    must(run([*command, "--evidence-out", str(out)], cwd=root), "score baseline")


def smoke(root: Path, out: Path) -> None:
    """Record the artifact self-test through the real smoke helper."""
    artifact = root / "artifact"
    command = [sys.executable, str(SCRIPTS / "artifact_smoke.py"), str(artifact / "inference.py")]
    command += ["--expect-json", str(artifact / "expected-self-test.json")]
    command += ["--acceptance", str(root / STATE / "acceptance-v1.json"), "--evidence-out", str(out)]
    must(run([*command, "--execute-reviewed"], cwd=root), "artifact smoke")


def append_ledger(root: Path, action: str, ordinal: int, report: Path | None = None, status: str = "success") -> None:
    """Append one proof row through the real ledger helper."""
    state = root / STATE
    command = [sys.executable, str(ROOT / "scripts" / "ledger_append.py"), "--ledger", str(state / "ledger.jsonl")]
    command += ["--session", "delivery-fixture", "--skill", "fixture", "--action", action]
    command += ["--event-id", f"manual:delivery-fixture:{action}:{ordinal}", "--status", status]
    command += ["--acceptance", str(state / "acceptance-v1.json")]
    if action in {"artifact_verified", "delivery_handoff_emitted"}:
        command += ["--artifact-dir", str(root / "artifact")]
    if report is not None:
        command += ["--report", str(report)]
    must(run(command, cwd=root), f"ledger append {action} {status}")


def record_live_check(root: Path) -> str:
    """Freeze the live check contract, record its reviewed run, and return the output oracle."""
    state, artifact = root / STATE, root / "artifact"
    acceptance = state / "acceptance-v1.json"
    oracle = hashlib.sha256(LIVE_OUTPUT).hexdigest()
    contract = state / "delivery-check-contract.json"
    command = [sys.executable, str(SCRIPTS / "freeze_delivery_check.py"), "--out", str(contract)]
    command += ["--acceptance", str(acceptance), "--artifact-dir", str(artifact), "--check", "live"]
    command += ["--expected-stdout-sha256", oracle, "--confirmed-by", "fixture owner"]
    must(run([*command, "--data-consent-id", "fixture-consent", "--", *LIVE_COMMAND], cwd=root), "freeze check")
    command = [sys.executable, str(SCRIPTS / "record_delivery_check.py"), "--acceptance", str(acceptance)]
    command += ["--artifact-dir", str(artifact), "--check-contract", str(contract)]
    command += ["--evidence-out", str(state / "live-evidence.json"), "--execute-reviewed", "--", *LIVE_COMMAND]
    must(run(command, cwd=root), "record live check")
    return oracle


def handoff_payload(root: Path, oracle: str) -> dict[str, Any]:
    """Return the digest-bound handoff record for the built project."""
    state = root / STATE
    self_test = read_json(state / "self-test-evidence.json")
    return {
        "schema_version": "2",
        "acceptance_id": ACCEPTANCE_ID,
        "acceptance_path": f"{STATE}/acceptance-v1.json",
        "acceptance_sha256": sha256(state / "acceptance-v1.json"),
        "model_or_pipeline": MODEL_ID,
        "artifact_kind": "hosted-client",
        "artifact_path": "artifact",
        "artifact_sha256": self_test["artifact_sha256"],
        "input_schema": {},
        "output_schema": {},
        "provider_dependency": "simulated provider",
        "data_boundary": "fixture only",
        "commands": {"self_test": ["<current-python>", "inference.py", "--self-test"], "live": LIVE_COMMAND},
        "expected_stdout_sha256": oracle,
        "check_contract_path": f"{STATE}/delivery-check-contract.json",
        "check_contract_sha256": sha256(state / "delivery-check-contract.json"),
        "checks": {"self_test": "passed", "live_or_offline": "passed"},
        "evidence": {
            "self_test": f"{STATE}/self-test-evidence.json",
            "live_or_offline": f"{STATE}/live-evidence.json",
        },
        "rollback": {"target": "fixture/v0", "owner": "fixture owner"},
        "monitoring": {"status": "not-configured"},
        "remaining_external_checks": [],
    }


def build_project(root: Path) -> None:
    """Build one complete delivery project with the real chain helpers."""
    state = root / STATE
    state.mkdir(parents=True)
    shutil.copytree(FIXTURE, root / "artifact")
    for name in ("gold.jsonl", "pred.jsonl"):
        write_labels(state / name, [index % 2 == 0 for index in range(IMAGES)])
    freeze_acceptance(root, state / "acceptance-v1.json", "0.8", sha256(state / "gold.jsonl"))
    score(root, state / "acceptance-v1.json", state / "baseline-v1.json")
    smoke(root, state / "self-test-evidence.json")
    oracle = record_live_check(root)
    write_json(state / "delivery-handoff-fixture.json", handoff_payload(root, oracle))
    cost = run(
        [sys.executable, str(ROOT / "scripts" / "cost_model.py"), "--streams", "1"]
        + ["--acceptance", str(state / "acceptance-v1.json"), "--json"],
        cwd=root,
    )
    must(cost, "cost model")
    (state / "economics-fixture.json").write_text(cost.stdout, encoding="utf-8", newline="\n")
    for ordinal, action in enumerate(LEDGER_ACTIONS, 1):
        append_ledger(root, action, ordinal)


def check(
    project: Path, *extra: str, cwd: Path | None = None, script: Path = CHECK, env: dict[str, str] | None = None
) -> tuple[int, str, dict[str, Any]]:
    """Run the entry command and return its exit code, verdict line, and JSON record."""
    command = [sys.executable, str(script), "--project-root", str(project), *extra]
    result = run(command, cwd=cwd or project, env=env)
    lines = result.stdout.splitlines()
    if len(lines) != 2:
        raise AssertionError(f"expected a verdict line and a JSON record, got: {result.stdout!r} {result.stderr!r}")
    return result.returncode, lines[0], json.loads(lines[1])


def expect_passed(project: Path, *extra: str, cwd: Path | None = None) -> dict[str, Any]:
    """Require exit 0, the fixed passed line with its limits, and a passed JSON record."""
    code, line, record = check(project, *extra, cwd=cwd)
    if code != 0 or not line.startswith(PASSED_LINE) or record["status"] != "passed":
        raise AssertionError(f"complete chain did not pass: {code} {line} {record.get('reason')}")
    if len(record["not_shown"]) != 2 or record["failed_step"] is not None:
        raise AssertionError(f"passed record lacks its limits: {record}")
    if line != " ".join([PASSED_LINE, *record["caveats"]]):
        raise AssertionError(f"plain line and caveats disagree: {line!r} {record['caveats']}")
    return record


def expect_failed(project: Path, step: str, needle: str, *extra: str) -> dict[str, Any]:
    """Require exit 1 and a verdict line that names the step and the reason."""
    code, line, record = check(project, *extra)
    if code != 1 or not line.startswith(f"{FAILED_PREFIX}{step}: ") or needle not in line:
        raise AssertionError(f"expected DELIVERY CHECKS FAILED at {step} ({needle!r}); got {code}: {line}")
    if record["status"] != "failed" or record["failed_step"] != step:
        raise AssertionError(f"JSON record does not name step {step}: {record}")
    return record


def expect_unusable(project: Path, needle: str, *extra: str, cwd: Path | None = None) -> None:
    """Require exit 2 for unusable input."""
    code, line, record = check(project, *extra, cwd=cwd)
    if code != 2 or not line.startswith(f"{FAILED_PREFIX}input: ") or needle not in line:
        raise AssertionError(f"expected unusable input ({needle!r}); got {code}: {line}")
    if record["status"] != "failed" or record["failed_step"] != "input":
        raise AssertionError(f"JSON record does not say failed at input: {record}")


def snapshot(folder: Path) -> dict[str, tuple[int, bytes]]:
    """Return every path under a folder with its mode and, for files, its bytes."""
    return {
        path.relative_to(folder).as_posix(): (path.lstat().st_mode, path.read_bytes() if path.is_file() else b"")
        for path in sorted(folder.rglob("*"))
    }


def edit_json(path: Path, change: Callable[[dict[str, Any]], None]) -> None:
    """Apply one change to a JSON fixture file."""
    value = read_json(path)
    change(value)
    write_json(path, value)


def handoff_file(project: Path) -> Path:
    """Return the project's handoff file."""
    return project / STATE / "delivery-handoff-fixture.json"


def baseline_file(project: Path) -> Path:
    """Return the project's scorer evidence file."""
    return project / STATE / "baseline-v1.json"


def case_passed(project: Path) -> None:
    """A complete chain passes with its limits stated, and the command changes no file in the project."""
    before = snapshot(project)
    record = expect_passed(project)
    statuses = {item["step"]: item["status"] for item in record["steps"]}
    if statuses.pop("report") != "skipped" or set(statuses.values()) != {"passed"} or tuple(statuses) != STEPS:
        raise AssertionError(f"unexpected step statuses: {record['steps']}")
    if len(record["chain_id"]) != 64 or record["trust"] != "local-same-user" or record["caveats"]:
        raise AssertionError(f"passed record lacks the chain identity or has caveats: {record}")
    if record["inputs"]["gold"] is None or record["inputs"]["pred"] is None:
        raise AssertionError(f"passed record does not name the re-scored files: {record['inputs']}")
    if snapshot(project) != before:
        raise AssertionError("check_delivery.py changed a file in the project folder")


def case_read_only_on_failure(project: Path) -> None:
    """A failing run and an unusable-input run change no file either."""
    (project / STATE / "live-evidence.json").write_text("{}\n", encoding="utf-8", newline="\n")
    before = snapshot(project)
    expect_failed(project, "live-check", "evidence")
    expect_unusable(project, "--baseline", "--baseline", str(project / STATE / "absent.json"))
    if snapshot(project) != before:
        raise AssertionError("check_delivery.py changed a file in the project folder")


def case_no_bytecode(project: Path) -> None:
    """An installed-style copy of the helpers gains no bytecode cache when the command runs."""
    installed = project.parent / f"{project.name}-installed" / "resources" / "scripts"
    installed.mkdir(parents=True)
    for helper in SCRIPTS.glob("*.py"):
        shutil.copy2(helper, installed / helper.name)
    env = {key: value for key, value in os.environ.items() if key != "PYTHONDONTWRITEBYTECODE"}
    code, line, _ = check(project, script=installed / "check_delivery.py", env=env)
    if code != 0 or not line.startswith(PASSED_LINE):
        raise AssertionError(f"installed copy did not pass the complete chain: {code} {line}")
    caches = sorted(path.name for path in installed.parent.rglob("__pycache__"))
    if caches:
        raise AssertionError(f"check_delivery.py wrote a bytecode cache next to its helpers: {caches}")


def case_report(project: Path) -> None:
    """A bound decision report passes; a changed report fails at the report step."""
    _, _, record = check(project)
    report = project / "decision-report.md"
    acceptance_sha256 = sha256(project / STATE / "acceptance-v1.json")
    text = f"Acceptance: {ACCEPTANCE_ID} / {acceptance_sha256}\nProof chain: {record['chain_id']}\n"
    report.write_text(text, encoding="utf-8", newline="\n")
    append_ledger(project, "decision_report_emitted", 5, report=report)
    record = expect_passed(project, "--report", str(report))
    if record.get("report_sha256") != sha256(report):
        raise AssertionError(f"bound decision report digest missing: {record}")
    report.write_text(text + "Decision: go\n", encoding="utf-8", newline="\n")
    expect_failed(project, "report", "report digest", "--report", str(report))


def case_acceptance(project: Path) -> None:
    """An acceptance file that is not a valid frozen target fails at the acceptance step."""
    edit_json(project / STATE / "acceptance-v1.json", lambda value: value.update(comparator="between"))
    expect_failed(project, "acceptance", "comparator must be gte or lte")


def case_baseline_changed_target(project: Path) -> None:
    """A baseline scored against another acceptance revision fails; so does a handoff for another revision."""
    state = project / STATE
    freeze_acceptance(project, state / "acceptance-v2.json", "0.85", sha256(state / "gold.jsonl"))
    score(project, state / "acceptance-v2.json", state / "rescored-v2.json")
    expect_failed(
        project, "baseline", "does not match the frozen acceptance", "--baseline", str(state / "rescored-v2.json")
    )
    extra: tuple[str, ...] = ("--baseline", str(state / "rescored-v2.json"))
    extra += ("--acceptance", str(state / "acceptance-v2.json"))
    expect_unusable(project, "delivery-handoff-*.json bound to this acceptance found; pass --handoff", *extra)
    extra += ("--handoff", str(handoff_file(project)))
    expect_failed(project, "handoff", "delivery handoff does not match the frozen acceptance", *extra)


def case_baseline_inconclusive(project: Path) -> None:
    """Only a pass verdict counts."""
    edit_json(baseline_file(project), lambda value: value.update(verdict="inconclusive"))
    expect_failed(project, "baseline", "only pass counts")


def case_baseline_gold_changed(project: Path) -> None:
    """A baseline scored on other gold labels than the frozen dataset fails."""
    edit_json(baseline_file(project), lambda value: value.update(gold_sha256="0" * 64))
    expect_failed(project, "baseline", "dataset digest does not match")


def _flat_baseline(project: Path) -> dict[str, Any]:
    """Return a hand-written flat baseline record with every field except a verdict."""
    scored = read_json(baseline_file(project))
    return {
        "model": MODEL_ID,
        "measured_at": scored["measured_at"],
        "metric": "accuracy",
        "comparator": "gte",
        "threshold": 0.8,
        "observed_value": 1.0,
        "acceptance_id": ACCEPTANCE_ID,
        "acceptance_sha256": sha256(project / STATE / "acceptance-v1.json"),
        "dataset_sha256": sha256(project / STATE / "gold.jsonl"),
        "passes_acceptance": True,
    }


def _validate_chain(project: Path, baseline: Path, *extra: str) -> subprocess.CompletedProcess[str]:
    """Run validate_proof_chain.py over the project with one baseline file."""
    state = project / STATE
    command = [sys.executable, str(SCRIPTS / "validate_proof_chain.py"), "--project-root", str(project)]
    command += ["--acceptance", str(state / "acceptance-v1.json"), "--baseline", str(baseline)]
    command += ["--handoff", str(handoff_file(project)), "--ledger", str(state / "ledger.jsonl")]
    return run([*command, "--economics", str(state / "economics-fixture.json"), *extra], cwd=project)


def _refused_by_both(project: Path, record: dict[str, Any], needle: str) -> None:
    """Write one baseline record and require both validators to refuse it at the baseline step."""
    write_json(baseline_file(project), record)
    result = _validate_chain(project, baseline_file(project))
    if result.returncode == 0 or needle not in result.stderr:
        raise AssertionError(f"validate_proof_chain.py accepted {needle!r} baseline: {result.stdout} {result.stderr}")
    expect_failed(project, "baseline", needle, "--baseline", str(baseline_file(project)))


def case_flat_record_refused(project: Path) -> None:
    """A flat record is not scorer evidence: refused with or without a verdict, an interval, or a model."""
    flat = _flat_baseline(project)
    passing = {**flat, "verdict": "pass", "interval_lower": 0.9}
    without_model = {key: value for key, value in passing.items() if key != "model"}
    for record in (flat, passing, without_model):
        _refused_by_both(project, record, "baseline must be scorer evidence")


def case_baseline_hand_written(project: Path) -> None:
    """A hand-written record with copied target and gold digest is refused: it is not scorer evidence."""
    scored = read_json(baseline_file(project))
    hand = {
        "target": scored["target"],
        "gold_sha256": scored["gold_sha256"],
        "verdict": "pass",
        "interval_lower": 0.81,
        "observed_value": 0.81,
        "passes_acceptance": True,
        "measured_at": scored["measured_at"],
    }
    _refused_by_both(project, hand, "baseline must be scorer evidence")


def case_baseline_mutated_scorer_record(project: Path) -> None:
    """Scorer evidence with a changed task, missing-prediction count, or numerator fails the re-score."""
    original = read_json(baseline_file(project))
    for change, needle in (
        ({"task": "count"}, "is not scored for task count"),
        ({"missing_predictions": 39}, "baseline missing_predictions does not match a re-score"),
        ({"numerator": 1, "denominator": 1}, "baseline numerator does not match a re-score"),
        ({"images": 41}, "baseline images does not match a re-score"),
        ({"pred_sha256": "0" * 64}, "has the baseline pred_sha256 000000000000"),
    ):
        _refused_by_both(project, {**original, **change}, needle)


def case_baseline_impossible_interval(project: Path) -> None:
    """An interval the files do not produce fails the re-score."""
    original = read_json(baseline_file(project))
    impossible = {**original, "observed_value": 0.81, "interval_lower": 0.99, "interval_upper": 0.5}
    _refused_by_both(project, impossible, "baseline observed_value does not match a re-score")
    _refused_by_both(project, {**original, "interval_lower": 0.95}, "baseline interval_lower does not match a re-score")


def case_baseline_files_missing(project: Path) -> None:
    """Without the scored files on disk the baseline step fails; explicit --gold and --pred restore it."""
    state, kept = project / STATE, project / "labels"
    kept.mkdir()
    for name in ("gold.jsonl", "pred.jsonl"):
        shutil.move(str(state / name), str(kept / name))
    expect_failed(project, "baseline", "pass --gold <label file> and --pred <prediction file>")
    explicit = ("--gold", str(kept / "gold.jsonl"), "--pred", str(kept / "pred.jsonl"))
    record = expect_passed(project, *explicit)
    if record["inputs"]["gold"] != str(kept / "gold.jsonl"):
        raise AssertionError(f"explicit --gold not used: {record['inputs']}")
    result = _validate_chain(project, baseline_file(project), *explicit)
    if result.returncode != 0:
        raise AssertionError(f"validate_proof_chain.py refused explicit scored files: {result.stderr}")
    write_labels(kept / "pred.jsonl", [True] * IMAGES)
    expect_failed(project, "baseline", "--pred", *explicit)


def case_baseline_shadow_threshold(project: Path) -> None:
    """A top-level threshold may not override the threshold the scorer applied."""
    original = read_json(baseline_file(project))
    target = {**original["target"], "threshold": 0.1}
    _refused_by_both(project, {**original, "target": target, "threshold": 0.8}, "top-level threshold disagrees")


def case_baseline_shadow_dataset(project: Path) -> None:
    """A top-level dataset_sha256 may not stand in for the scorer's gold_sha256."""
    original = read_json(baseline_file(project))
    shadowed = {**original, "gold_sha256": "0" * 64, "dataset_sha256": original["gold_sha256"]}
    _refused_by_both(project, shadowed, "top-level dataset_sha256 disagrees")


def case_validator_scorer_record(project: Path) -> None:
    """validate_proof_chain.py accepts the real scorer's evidence and finds its files by digest."""
    result = _validate_chain(project, baseline_file(project))
    if result.returncode != 0:
        raise AssertionError(f"validate_proof_chain.py refused real scorer evidence: {result.stderr}")
    if json.loads(result.stdout)["caveats"] != []:
        raise AssertionError(f"complete chain has caveats: {result.stdout}")


def _recheck(project: Path, flags: list[bool], truth: bool, session: str) -> None:
    """Score a fresh labeled sample through the real recheck helper, which appends a recheck_measured row."""
    state = project / STATE
    gold, pred = state / f"fresh-gold-{session}.jsonl", state / f"fresh-pred-{session}.jsonl"
    write_labels(gold, [truth] * len(flags), prefix=f"fresh_{session}")
    write_labels(pred, flags, prefix=f"fresh_{session}")
    command = [sys.executable, str(RECHECK), "--acceptance", str(state / "acceptance-v1.json")]
    command += ["--baseline-evidence", str(baseline_file(project)), "--gold", str(gold), "--pred", str(pred)]
    command += ["--task", "flag", "--ledger", str(state / "ledger.jsonl"), "--session", session]
    command += ["--evidence-out", str(state / f"recheck-{session}.json")]
    if "--baseline-gold" in RECHECK.read_text(encoding="utf-8"):
        command += ["--baseline-gold", str(state / "gold.jsonl")]
    must(run(command, cwd=project), f"recheck {session}")


def case_later_drifted_recheck(project: Path) -> None:
    """A later recheck that scored below the target fails the later-records step, in both validators."""
    _recheck(project, [False] * IMAGES, True, "drift")
    expect_failed(project, "later-records", "the latest recheck scored below the target")
    result = _validate_chain(project, baseline_file(project))
    if result.returncode == 0 or "the latest recheck scored below the target" not in result.stderr:
        raise AssertionError(f"validate_proof_chain.py issued a chain ID after a drifted recheck: {result.stdout}")


def case_later_uncertain_recheck(project: Path) -> None:
    """A later recheck that could not settle the target passes with a caveat on the line and in the record."""
    _recheck(project, [True] * 3, True, "few")
    record = expect_passed(project)
    if record["caveats"] != [
        "The latest recheck could not show whether the target still holds; label more fresh images."
    ]:
        raise AssertionError(f"uncertain recheck caveat missing: {record['caveats']}")


def case_later_failed_row(project: Path) -> None:
    """A failed proof action after its success fails; a later successful re-run restores the chain."""
    append_ledger(project, "artifact_verified", 6, status="failed")
    expect_failed(project, "later-records", "records artifact_verified as failed after its success")
    append_ledger(project, "artifact_verified", 7)
    expect_passed(project)


def case_newer_acceptance(project: Path) -> None:
    """A later acceptance revision in the project is a caveat that names the file, not a failure."""
    state = project / STATE
    freeze_acceptance(project, state / "acceptance-v2.json", "0.95", sha256(state / "gold.jsonl"))
    record = expect_passed(project)
    if len(record["caveats"]) != 1 or f"{STATE}/acceptance-v2.json" not in record["caveats"][0]:
        raise AssertionError(f"newer acceptance caveat missing: {record['caveats']}")


def case_relative_explicit_path(project: Path) -> None:
    """A relative explicit path starts at --project-root, not at the current folder."""
    expect_passed(project, "--baseline", f"{STATE}/baseline-v1.json", cwd=project.parent)


def case_explicit_outside_root(project: Path) -> None:
    """An explicit input outside the project root is unusable input."""
    outside = project.parent / f"{project.name}-outside-baseline.json"
    shutil.copy(baseline_file(project), outside)
    expect_unusable(project, "is outside the project root", "--baseline", str(outside))
    expect_unusable(project, "is outside the project root", "--baseline", f"../{outside.name}")


def case_discovery_by_binding(project: Path) -> None:
    """Discovery keeps only files bound to the acceptance; explore evidence and other revisions are ignored."""
    state = project / STATE
    command = [sys.executable, str(SCRIPTS / "score_baseline.py"), "--gold", str(state / "gold.jsonl")]
    command += ["--pred", str(state / "pred.jsonl"), "--task", "flag", "--metric", "accuracy"]
    command += ["--comparator", "gte", "--threshold", "0.8", "--evidence-out", str(state / "baseline-rung0-s1.json")]
    must(run(command, cwd=project), "score explore baseline")
    freeze_acceptance(project, state / "acceptance-v0.json", "0.85", sha256(state / "gold.jsonl"))
    edit_json(state / "acceptance-v0.json", lambda value: value.update(frozen_at="2000-01-01T00:00:00Z"))
    score(project, state / "acceptance-v0.json", state / "baseline-v0.json")
    other = read_json(handoff_file(project))
    other.update(acceptance_path=f"{STATE}/acceptance-v0.json", acceptance_sha256=sha256(state / "acceptance-v0.json"))
    write_json(state / "delivery-handoff-other.json", other)
    economics = read_json(state / "economics-fixture.json")
    economics["proof"]["acceptance_sha256"] = sha256(state / "acceptance-v0.json")
    write_json(state / "economics-other.json", economics)
    expect_unusable(project, "pass --handoff")
    bound = ("--acceptance", f"{STATE}/acceptance-v1.json")
    if expect_passed(project, *bound)["caveats"]:
        raise AssertionError("an older acceptance revision produced a caveat")
    shutil.copy(baseline_file(project), state / "baseline-copy.json")
    needle = "2 files match .vision-delivery/baseline-*.json bound to this acceptance; pass --baseline"
    expect_unusable(project, needle, *bound)


def case_handoff_artifact_changed(project: Path) -> None:
    """An artifact changed after its checks fails at the handoff step."""
    with (project / "artifact" / "inference.py").open("a", encoding="utf-8", newline="\n") as stream:
        stream.write("# changed after the checks\n")
    expect_failed(project, "handoff", "artifact_sha256 does not match the artifact tree")


def case_self_test(project: Path) -> None:
    """A self-test record that did not pass fails at the self-test step."""
    edit_json(project / STATE / "self-test-evidence.json", lambda value: value.update(status="failed"))
    expect_failed(project, "self-test", "evidence status does not match")


def case_check_contract_oracle(project: Path) -> None:
    """A contract with a malformed output oracle fails at the check-contract step."""
    contract = project / STATE / "delivery-check-contract.json"
    edit_json(contract, lambda value: value.update(expected_stdout_sha256="not-a-digest"))
    edit_json(handoff_file(project), lambda value: value.update(check_contract_sha256=sha256(contract)))
    expect_failed(project, "check-contract", "output oracle must be lowercase SHA-256")


def case_check_contract_no_live_command(project: Path) -> None:
    """A hosted client with an empty live command fails at the check-contract step."""
    edit_json(handoff_file(project), lambda value: value["commands"].update(live=[]))
    expect_failed(project, "check-contract", "live must be a non-empty argv array")


def case_scaffold(project: Path) -> None:
    """A consistent scaffold passes the handoff validator but never passes the delivery checks."""
    artifact, state = project / "artifact", project / STATE
    for name in ("inference.py", "RUN.md", "expected-self-test.json"):
        path = artifact / name
        path.write_text(path.read_text(encoding="utf-8").replace("hosted-client", "scaffold"), encoding="utf-8")
    (state / "self-test-evidence.json").unlink()
    smoke(project, state / "self-test-evidence.json")

    def to_scaffold(value: dict[str, Any]) -> None:
        value.update(
            artifact_kind="scaffold", artifact_sha256=read_json(state / "self-test-evidence.json")["artifact_sha256"]
        )
        value["commands"]["live"] = []
        value["checks"]["live_or_offline"] = "not-run"
        value["evidence"].pop("live_or_offline")
        value["remaining_external_checks"] = ["run a representative live request"]

    edit_json(handoff_file(project), to_scaffold)
    command = [sys.executable, str(SCRIPTS / "validate_delivery_handoff.py"), str(handoff_file(project))]
    must(run([*command, "--project-root", str(project)], cwd=project), "scaffold handoff validation")
    expect_failed(project, "check-contract", "a scaffold has no frozen live or offline check")


def case_live_check(project: Path) -> None:
    """Live evidence that does not match the oracle, or a check not run, fails at the live-check step."""
    live = project / STATE / "live-evidence.json"
    original = live.read_bytes()
    edit_json(live, lambda value: value.update(stdout_sha256="0" * 64))
    expect_failed(project, "live-check", "does not match the output oracle")
    live.write_bytes(original)
    edit_json(handoff_file(project), lambda value: value["checks"].update(live_or_offline="not-run"))
    expect_failed(project, "live-check", "requires a passed live_or_offline check")


def case_economics(project: Path) -> None:
    """Economics that are not bound to the acceptance fail at the economics step."""
    path = project / STATE / "economics-fixture.json"
    edit_json(path, lambda value: value.update(proof={"status": "unbound"}))
    expect_failed(project, "economics", "not bound to frozen acceptance", "--economics", str(path))


def case_ledger(project: Path) -> None:
    """A ledger without a proof action fails at the ledger step."""
    ledger = project / STATE / "ledger.jsonl"
    rows = [line for line in ledger.read_text(encoding="utf-8").splitlines() if "crossover_delivered" not in line]
    ledger.write_text("\n".join(rows) + "\n", encoding="utf-8", newline="\n")
    expect_failed(project, "ledger", "missing successful proof actions: crossover_delivered")


def case_unusable_input(project: Path) -> None:
    """Missing or ambiguous inputs exit 2 and name the option to pass."""
    expect_unusable(project, "--baseline", "--baseline", str(project / STATE / "absent.json"))
    shutil.copy(handoff_file(project), project / STATE / "delivery-handoff-other.json")
    expect_unusable(project, "pass --handoff")
    (project / STATE / "delivery-handoff-other.json").unlink()
    edit_json(handoff_file(project), lambda value: value.update(acceptance_path=f"{STATE}/absent.json"))
    expect_unusable(project, "pass --acceptance")
    handoff_file(project).unlink()
    expect_unusable(project, "pass --handoff")


CASES: dict[str, Callable[[Path], None]] = {
    name.removeprefix("case_"): value for name, value in globals().items() if name.startswith("case_")
}


def main() -> int:
    """Build the project once, then run each selected case on its own copy."""
    selected = sys.argv[1:] or list(CASES)
    unknown = sorted(set(selected) - set(CASES))
    if unknown:
        raise AssertionError(f"unknown cases: {unknown}; known: {sorted(CASES)}")
    with tempfile.TemporaryDirectory() as folder:
        base = Path(folder).resolve() / "base"
        build_project(base)
        for name in selected:
            project = Path(folder).resolve() / name
            shutil.copytree(base, project, symlinks=True)
            CASES[name](project)
            print(f"PASS {name}")
    print("delivery-check assertions passed")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except AssertionError as exc:
        print(f"delivery check failed: {exc}", file=sys.stderr)
        raise SystemExit(1) from exc
