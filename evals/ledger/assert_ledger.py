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


def main() -> int:
    """Assert failed/unknown events are excluded and stable IDs deduplicate."""
    module = load_module()
    records = [
        {
            "session": "ok",
            "skill": "hook",
            "action": "roboflow_mcp_call",
            "operation": "deployment_create",
            "category": "deployment",
            "status": "success",
            "event_id": "deploy-1",
        },
        {
            "session": "ok",
            "skill": "hook",
            "action": "roboflow_mcp_call",
            "operation": "deployment_create",
            "category": "deployment",
            "status": "success",
            "event_id": "deploy-1",
        },
        {
            "session": "failed",
            "skill": "hook",
            "action": "roboflow_mcp_call",
            "operation": "deployment_create",
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
            "operation": "deployments_list",
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
