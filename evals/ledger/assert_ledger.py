#!/usr/bin/env python3
"""Regression checks for outcome-grade, idempotent delivery metrics."""

from __future__ import annotations

import hashlib
import importlib.util
import json
import os
import subprocess
import sys
import tempfile
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import ModuleType

SCRIPT = Path(__file__).parents[2] / "scripts" / "ledger_report.py"
APPEND_SCRIPT = Path(__file__).parents[2] / "scripts" / "ledger_append.py"


def load_module() -> ModuleType:
    """Load the ledger report script without requiring package installation."""
    spec = importlib.util.spec_from_file_location("sentinel_ledger_report", SCRIPT)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"could not load {SCRIPT}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


#: Price date used by brief fixtures: today, because the helper rejects a date over 90 days old.
TODAY = datetime.now(timezone.utc).date()


def run_brief(
    cwd: str, event: str, operation: str, *extra: str, omit: tuple[str, ...] = (), script: Path = APPEND_SCRIPT
) -> subprocess.CompletedProcess[str]:
    """Append one action brief through the helper and return the finished process."""
    fields = {
        "--scope": "train detection model on conveyor v3",
        "--cost-amount": "10",
        "--cost-unit": "credits",
        "--cost-source": "Roboflow plans-and-pricing skill, training table",
        "--cost-as-of": TODAY.isoformat(),
        "--data-movement": "none; the dataset is already in the workspace",
        "--rollback": "cancel the job; spent credits are not refunded",
    }
    structured = [part for flag, value in fields.items() if flag not in omit for part in (flag, value)]
    command = [
        sys.executable,
        str(script),
        "--session",
        "brief",
        "--skill",
        "detect-and-analyze",
        "--action",
        "action_brief_emitted",
        "--operation",
        operation,
        "--event-id",
        f"manual:brief:{event}",
        "--status",
        "success",
        *structured,
        *extra,
    ]
    return subprocess.run(command, cwd=cwd, check=False, capture_output=True, text=True)


def append_brief(cwd: str, event: str, operation: str, *extra: str, omit: tuple[str, ...] = ()) -> int:
    """Append one action brief through the helper and return its exit code."""
    return run_brief(cwd, event, operation, *extra, omit=omit).returncode


def check_action_briefs() -> None:
    """Assert the helper rejects an action brief the gate could not show a person."""
    with tempfile.TemporaryDirectory() as temp_dir:
        ledger = Path(temp_dir) / ".vision-delivery" / "ledger.jsonl"
        assert append_brief(temp_dir, "complete", "trainings_create") == 0
        row = json.loads(ledger.read_text(encoding="utf-8").splitlines()[-1])
        assert row["operation"] == "trainings_create"
        assert row["brief"] == {
            "scope": "train detection model on conveyor v3",
            "cost_amount": 10.0,
            "cost_unit": "credits",
            "cost_source": "Roboflow plans-and-pricing skill, training table",
            "cost_as_of": TODAY.isoformat(),
            "data_movement": "none; the dataset is already in the workspace",
            "rollback": "cancel the job; spent credits are not refunded",
        }
        rows_before = len(ledger.read_text(encoding="utf-8").splitlines())

        for flag in (
            "--scope",
            "--cost-amount",
            "--cost-unit",
            "--cost-source",
            "--cost-as-of",
            "--data-movement",
            "--rollback",
        ):
            assert append_brief(temp_dir, f"no{flag}", "trainings_create", omit=(flag,)) == 2, flag
        assert append_brief(temp_dir, "blank-source", "trainings_create", "--cost-source", "  ") == 2
        assert append_brief(temp_dir, "negative", "trainings_create", "--cost-amount", "-1") == 2
        assert append_brief(temp_dir, "nan", "trainings_create", "--cost-amount", "nan") == 2
        assert append_brief(temp_dir, "bad-date", "trainings_create", "--cost-as-of", "2026-02-31") == 2
        assert append_brief(temp_dir, "future-date", "trainings_create", "--cost-as-of", "2999-01-01") == 2
        # A price looked up long ago is not a current estimate; the gate applies the same 90 days.
        old_price = (TODAY - timedelta(days=120)).isoformat()
        assert append_brief(temp_dir, "old-date", "trainings_create", "--cost-as-of", old_price) == 2
        # Only the YYYY-MM-DD form the gate reads is accepted.
        for loose in (TODAY.strftime("%Y%m%d"), f"{TODAY.isocalendar().year}-W{TODAY.isocalendar().week:02d}-1"):
            assert append_brief(temp_dir, f"loose-{loose}", "trainings_create", "--cost-as-of", loose) == 2, loose
        assert append_brief(temp_dir, "prefixed", "mcp__roboflow__trainings_create") == 2
        # Billed media analysis takes video: a brief per execution, never a call budget.
        assert append_brief(temp_dir, "media-budget", "media_analyze", "--call-budget", "5") == 2
        assert append_brief(temp_dir, "read-only", "trainings_get") == 2
        assert append_brief(temp_dir, "budget-missing", "models_infer") == 2
        assert append_brief(temp_dir, "budget-zero", "models_infer", "--call-budget", "0") == 2
        assert append_brief(temp_dir, "budget-huge", "models_infer", "--call-budget", "100000") == 2
        assert append_brief(temp_dir, "budget-on-brief", "trainings_create", "--call-budget", "5") == 2
        assert len(ledger.read_text(encoding="utf-8").splitlines()) == rows_before

        assert append_brief(temp_dir, "budget", "models_infer", "--call-budget", "40") == 0
        row = json.loads(ledger.read_text(encoding="utf-8").splitlines()[-1])
        assert row["brief"]["call_budget"] == 40
        assert append_brief(temp_dir, "media", "media_analyze") == 0
        aged_price = (TODAY - timedelta(days=60)).isoformat()
        assert append_brief(temp_dir, "aged-date", "trainings_create", "--cost-as-of", aged_price) == 0
        # A tool the policy does not list is gated, so it can carry a brief; the helper warns,
        # because the name may be misspelled.
        unlisted = run_brief(temp_dir, "unlisted", "future_capability_execute")
        assert unlisted.returncode == 0 and "is not in the gate policy" in unlisted.stderr, unlisted.stderr
        listed = run_brief(temp_dir, "listed", "versions_generate")
        assert listed.returncode == 0 and "ledger-append-warning" not in listed.stderr, listed.stderr

        # Without the gate policy the helper cannot check the brief against what the gate
        # enforces, so it records nothing.
        lone = Path(temp_dir) / "lone" / "scripts"
        lone.mkdir(parents=True)
        (lone / "ledger_append.py").write_bytes(APPEND_SCRIPT.read_bytes())
        rows_before = len(ledger.read_text(encoding="utf-8").splitlines())
        orphan = run_brief(temp_dir, "no-policy", "models_infer", script=lone / "ledger_append.py")
        assert orphan.returncode == 2 and "cannot read the gate policy" in orphan.stderr, orphan.stderr
        assert len(ledger.read_text(encoding="utf-8").splitlines()) == rows_before

        failed = subprocess.run(
            [
                sys.executable,
                str(APPEND_SCRIPT),
                "--session",
                "brief",
                "--skill",
                "detect-and-analyze",
                "--action",
                "action_brief_emitted",
                "--event-id",
                "manual:brief:abandoned",
                "--status",
                "cancelled",
            ],
            cwd=temp_dir,
            check=False,
        )
        assert failed.returncode == 0


def check_policy_operations(module: ModuleType) -> None:
    """Assert report operation names come from the gate policy, not from guesses."""
    policy = json.loads((Path(__file__).parents[2] / "hooks" / "gate-policy.json").read_text(encoding="utf-8"))
    deployment, progress = module._policy_operations()
    assert deployment == frozenset(policy["deployment_operations"])
    assert "project_deployment_launch" in deployment
    assert deployment <= policy["tools"].keys()
    assert {"trainings_create", "models_infer", "workflow_evals_runs_start"} <= progress
    assert not {"trainings_get", "model_evals_get", "project_deployment_get"} & progress
    assert all(policy["tools"][name]["class"] != "open" for name in deployment | progress)

    records = [
        {"session": "s", "action": "roboflow_mcp_call", "operation": "models_infer", "status": "success"},
        {"session": "r", "action": "roboflow_mcp_call", "operation": "trainings_get", "status": "success"},
    ]
    metrics = module.compute_metrics(records)
    assert metrics["solved_no_deploy"] == 1
    assert metrics["sessions_reaching_deploy"] == 0


def main() -> int:
    """Assert failed/unknown events are excluded and stable IDs deduplicate."""
    module = load_module()
    check_policy_operations(module)
    check_action_briefs()
    records = [
        {
            "session": "ok",
            "skill": "hook",
            "action": "roboflow_mcp_call",
            "operation": "project_deployment_launch",
            "category": "deployment",
            "status": "success",
            "event_id": "deploy-1",
        },
        {
            "session": "ok",
            "skill": "hook",
            "action": "roboflow_mcp_call",
            "operation": "project_deployment_launch",
            "category": "deployment",
            "status": "success",
            "event_id": "deploy-1",
        },
        {
            "session": "failed",
            "skill": "hook",
            "action": "roboflow_mcp_call",
            "operation": "project_deployment_launch",
            "category": "deployment",
            "status": "failed",
            "event_id": "deploy-2",
        },
        {
            "session": "legacy",
            "skill": "detect-and-analyze",
            "action": "project_deployment_launch",
        },
        {
            "session": "measured",
            "skill": "detect-and-analyze",
            "action": "baseline_measured",
            "status": "success",
        },
        {
            "session": "read-only",
            "skill": "hook",
            "action": "roboflow_mcp_call",
            "operation": "project_deployment_get",
            "category": "deployment",
            "status": "success",
            "event_id": "deploy-read-1",
        },
        {
            "session": "manual-claim",
            "skill": "arbitrary",
            "action": "project_deployment_launch",
            "status": "success",
            "event_id": "manual:fake-deploy:1",
        },
    ]
    metrics = module.compute_metrics(records)

    assert metrics["raw_records"] == 7
    assert metrics["total_events"] == 6
    assert metrics["duplicates_ignored"] == 1
    assert metrics["verified_success_events"] == 4
    assert metrics["sessions"] == 6
    assert metrics["sessions_reaching_deploy"] == 1
    assert metrics["sessions_reaching_deploy_pct"] == 16.7
    assert metrics["solved_no_deploy"] == 1
    assert metrics["outcome_breakdown"] == {
        "success": 4,
        "failed": 1,
        "legacy-unknown": 1,
    }

    conflicting_records = [
        {
            "session": "conflict",
            "skill": "hook",
            "action": "roboflow_mcp_call",
            "status": "success",
            "event_id": "conflict-1",
        },
        {
            "session": "conflict",
            "skill": "hook",
            "action": "roboflow_mcp_call",
            "status": "failed",
            "event_id": "conflict-1",
        },
    ]
    conflicting_metrics = module.compute_metrics(conflicting_records)
    assert conflicting_metrics["total_events"] == 1
    assert conflicting_metrics["verified_success_events"] == 0
    assert conflicting_metrics["integrity_conflicts"] == 1
    assert conflicting_metrics["outcome_breakdown"] == {"unknown": 1}

    with tempfile.TemporaryDirectory() as temp_dir:
        acceptance = Path(temp_dir) / "acceptance.json"
        acceptance.write_text(
            json.dumps(
                {
                    "schema_version": "1",
                    "acceptance_id": "fixture/v1",
                    "frozen_at": "2026-08-11T00:00:00Z",
                    "metric": "mAP@50",
                    "comparator": "gte",
                    "threshold": 0.65,
                    "unit": "fraction",
                    "dataset_sha256": "a" * 64,
                    "model_or_pipeline": "fixture/v1",
                    "confirmed_by": "fixture owner",
                }
            ),
            encoding="utf-8",
        )
        report = Path(temp_dir) / "decision-report.md"
        report.write_text("Decision: fixture\n", encoding="utf-8")
        proof_args = [
            "--acceptance",
            str(acceptance),
            "--report",
            str(report),
        ]
        subprocess.run(
            [
                sys.executable,
                str(APPEND_SCRIPT),
                "--session",
                "arbitrary-cwd",
                "--skill",
                "decision-report",
                "--action",
                "decision_report_emitted",
                *proof_args,
                "--event-id",
                "manual:arbitrary-cwd:report:1",
                "--status",
                "success",
            ],
            cwd=temp_dir,
            check=True,
        )
        ledger = Path(temp_dir) / ".vision-delivery" / "ledger.jsonl"
        appended = json.loads(ledger.read_text(encoding="utf-8"))
        assert appended["status"] == "success"
        assert appended["source"] == "skill"
        assert appended["report_sha256"] == hashlib.sha256(report.read_bytes()).hexdigest()

        duplicate = subprocess.run(
            [
                sys.executable,
                str(APPEND_SCRIPT),
                "--session",
                "arbitrary-cwd",
                "--skill",
                "decision-report",
                "--action",
                "decision_report_emitted",
                *proof_args,
                "--event-id",
                "manual:arbitrary-cwd:report:1",
                "--status",
                "success",
            ],
            cwd=temp_dir,
            check=False,
        )
        assert duplicate.returncode == 0
        assert len(ledger.read_text(encoding="utf-8").splitlines()) == 1

        unbound = subprocess.run(
            [
                sys.executable,
                str(APPEND_SCRIPT),
                "--session",
                "arbitrary-cwd",
                "--skill",
                "decision-report",
                "--action",
                "decision_report_emitted",
                "--event-id",
                "manual:arbitrary-cwd:unbound:1",
                "--status",
                "success",
            ],
            cwd=temp_dir,
            check=False,
        )
        assert unbound.returncode == 2

        conflict = subprocess.run(
            [
                sys.executable,
                str(APPEND_SCRIPT),
                "--session",
                "arbitrary-cwd",
                "--skill",
                "decision-report",
                "--action",
                "different_action",
                "--event-id",
                "manual:arbitrary-cwd:report:1",
                "--status",
                "success",
            ],
            cwd=temp_dir,
            check=False,
        )
        assert conflict.returncode == 2

        concurrent_commands = [
            [
                sys.executable,
                str(APPEND_SCRIPT),
                "--session",
                "concurrent",
                "--skill",
                "decision-report",
                "--action",
                "decision_report_emitted",
                *proof_args,
                "--event-id",
                "manual:concurrent:report:1",
                "--status",
                "success",
            ]
            for _ in range(12)
        ]
        processes = [subprocess.Popen(command, cwd=temp_dir) for command in concurrent_commands]
        assert all(process.wait() == 0 for process in processes)
        assert (
            sum(
                1
                for row in ledger.read_text(encoding="utf-8").splitlines()
                if json.loads(row).get("event_id") == "manual:concurrent:report:1"
            )
            == 1
        )

    if os.name == "posix":
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            victim_dir = root / "victim-dir"
            victim_dir.mkdir()
            ledger_dir = root / ".vision-delivery"
            ledger_dir.symlink_to(victim_dir, target_is_directory=True)
            result = subprocess.run(
                [
                    sys.executable,
                    str(APPEND_SCRIPT),
                    "--session",
                    "symlink",
                    "--skill",
                    "decision-report",
                    "--action",
                    "eval_definition",
                    "--event-id",
                    "symlink-directory",
                    "--status",
                    "success",
                ],
                cwd=root,
                check=False,
            )
            assert result.returncode == 2
            assert not (victim_dir / "ledger.jsonl").exists()

            ledger_dir.unlink()
            ledger_dir.mkdir()
            victim_file = root / "victim.jsonl"
            victim_file.write_text("victim\n", encoding="utf-8")
            (ledger_dir / "ledger.jsonl").symlink_to(victim_file)
            result = subprocess.run(
                [
                    sys.executable,
                    str(APPEND_SCRIPT),
                    "--session",
                    "symlink",
                    "--skill",
                    "decision-report",
                    "--action",
                    "eval_definition",
                    "--event-id",
                    "symlink-file",
                    "--status",
                    "success",
                ],
                cwd=root,
                check=False,
            )
            assert result.returncode == 2
            assert victim_file.read_text(encoding="utf-8") == "victim\n"

    print("ledger assertions passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
