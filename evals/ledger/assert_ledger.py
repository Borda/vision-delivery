#!/usr/bin/env python3
"""Regression checks for outcome-grade, idempotent delivery metrics."""

from __future__ import annotations

import importlib.util
import json
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
    ]
    metrics = module.compute_metrics(records)

    assert metrics["raw_records"] == 5
    assert metrics["total_events"] == 4
    assert metrics["duplicates_ignored"] == 1
    assert metrics["verified_success_events"] == 2
    assert metrics["sessions"] == 4
    assert metrics["sessions_reaching_deploy"] == 1
    assert metrics["sessions_reaching_deploy_pct"] == 25.0
    assert metrics["solved_no_deploy"] == 1
    assert metrics["outcome_breakdown"] == {
        "success": 2,
        "failed": 1,
        "legacy-unknown": 1,
    }

    with tempfile.TemporaryDirectory() as temp_dir:
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

    print("ledger assertions passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
