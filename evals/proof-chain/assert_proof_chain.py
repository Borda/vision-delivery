#!/usr/bin/env python3
"""Exercise the complete local acceptance-to-decision proof chain."""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import subprocess
import sys
import tempfile
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SCRIPTS = ROOT / "resources" / "scripts"
ARTIFACT_FIXTURE = ROOT / "evals" / "artifacts" / "fixtures" / "hosted-client"
MODEL_ID = "committed deterministic fixture v1"
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


def run(command: list[str], *, cwd: Path) -> subprocess.CompletedProcess[str]:
    """Run one bounded proof helper and capture its diagnostic output."""
    return subprocess.run(
        command,
        cwd=cwd,
        text=True,
        capture_output=True,
        timeout=30,
        check=False,
        env={**os.environ, "SENTINEL_FIXTURE_TOKEN": "fixture-only"},
    )


def require_pass(process: subprocess.CompletedProcess[str], label: str) -> dict[str, object]:
    """Return JSON stdout from a successful helper invocation."""
    if process.returncode != 0:
        raise AssertionError(f"{label} failed: {process.stdout} {process.stderr}")
    value = json.loads(process.stdout)
    if not isinstance(value, dict) or value.get("status") not in {
        "passed",
        "frozen",
    }:
        raise AssertionError(f"{label} returned an invalid verdict: {value}")
    return value


def append_ledger(
    root: Path,
    acceptance: Path,
    artifact: Path,
    action: str,
    ordinal: int,
    report: Path | None = None,
) -> None:
    """Append one proof-bound successful action through the public helper."""
    command = [
        sys.executable,
        str(ROOT / "scripts" / "ledger_append.py"),
        "--ledger",
        str(root / "ledger.jsonl"),
        "--session",
        "proof-fixture",
        "--skill",
        "fixture",
        "--action",
        action,
        "--event-id",
        f"manual:proof-fixture:{action}:{ordinal}",
        "--status",
        "success",
        "--acceptance",
        str(acceptance),
    ]
    if action in {"artifact_verified", "delivery_handoff_emitted"}:
        command.extend(("--artifact-dir", str(artifact)))
    if report is not None:
        command.extend(("--report", str(report)))
    result = run(command, cwd=root)
    if result.returncode != 0:
        raise AssertionError(f"ledger append {action} failed: {result.stderr}")


def main() -> int:
    """Build a valid chain, then prove a failed baseline cannot pass it."""
    with tempfile.TemporaryDirectory() as directory:
        root = Path(directory).resolve()
        artifact = root / "artifact"
        shutil.copytree(ARTIFACT_FIXTURE, artifact)
        frozen_at = datetime.now(timezone.utc) - timedelta(minutes=1)
        acceptance = root / "acceptance.json"
        acceptance.write_text(
            json.dumps(
                {
                    "schema_version": "1",
                    "acceptance_id": "artifact-fixture/v1",
                    "frozen_at": frozen_at.isoformat().replace("+00:00", "Z"),
                    "metric": "mAP@50",
                    "comparator": "gte",
                    "threshold": 0.5,
                    "unit": "fraction",
                    "dataset_sha256": "a" * 64,
                    "model_or_pipeline": MODEL_ID,
                    "confirmed_by": "fixture owner",
                },
                indent=2,
            )
            + "\n",
            encoding="utf-8",
        )
        acceptance_digest = hashlib.sha256(acceptance.read_bytes()).hexdigest()

        self_evidence = root / "self-evidence.json"
        require_pass(
            run(
                [
                    sys.executable,
                    str(SCRIPTS / "artifact_smoke.py"),
                    str(artifact / "inference.py"),
                    "--expect-json",
                    str(artifact / "expected-self-test.json"),
                    "--acceptance",
                    str(acceptance),
                    "--evidence-out",
                    str(self_evidence),
                    "--execute-reviewed",
                ],
                cwd=root,
            ),
            "artifact smoke",
        )
        self_record = json.loads(self_evidence.read_text(encoding="utf-8"))
        artifact_digest = self_record["artifact_sha256"]

        live_evidence = root / "live-evidence.json"
        live_command = [sys.executable, "inference.py"]
        expected_stdout_digest = hashlib.sha256(LIVE_OUTPUT).hexdigest()
        check_contract = root / "live-check-contract.json"
        require_pass(
            run(
                [
                    sys.executable,
                    str(SCRIPTS / "freeze_delivery_check.py"),
                    "--out",
                    str(check_contract),
                    "--acceptance",
                    str(acceptance),
                    "--artifact-dir",
                    str(artifact),
                    "--check",
                    "live",
                    "--expected-stdout-sha256",
                    expected_stdout_digest,
                    "--confirmed-by",
                    "fixture owner",
                    "--data-consent-id",
                    "fixture-consent",
                    "--",
                    *live_command,
                ],
                cwd=root,
            ),
            "freeze delivery check",
        )
        require_pass(
            run(
                [
                    sys.executable,
                    str(SCRIPTS / "record_delivery_check.py"),
                    "--acceptance",
                    str(acceptance),
                    "--artifact-dir",
                    str(artifact),
                    "--check-contract",
                    str(check_contract),
                    "--evidence-out",
                    str(live_evidence),
                    "--execute-reviewed",
                    "--",
                    *live_command,
                ],
                cwd=root,
            ),
            "live delivery check",
        )

        handoff = root / "handoff.json"
        handoff.write_text(
            json.dumps(
                {
                    "schema_version": "2",
                    "acceptance_id": "artifact-fixture/v1",
                    "acceptance_path": acceptance.name,
                    "acceptance_sha256": acceptance_digest,
                    "model_or_pipeline": MODEL_ID,
                    "artifact_kind": "hosted-client",
                    "artifact_path": artifact.name,
                    "artifact_sha256": artifact_digest,
                    "input_schema": {},
                    "output_schema": {},
                    "provider_dependency": "simulated provider",
                    "data_boundary": "fixture only",
                    "commands": {
                        "self_test": [
                            "<current-python>",
                            "inference.py",
                            "--self-test",
                        ],
                        "live": live_command,
                    },
                    "expected_stdout_sha256": expected_stdout_digest,
                    "check_contract_path": check_contract.name,
                    "check_contract_sha256": hashlib.sha256(check_contract.read_bytes()).hexdigest(),
                    "checks": {"self_test": "passed", "live_or_offline": "passed"},
                    "evidence": {
                        "self_test": self_evidence.name,
                        "live_or_offline": live_evidence.name,
                    },
                    "rollback": {"target": "fixture/v0", "owner": "fixture owner"},
                    "monitoring": {"status": "not-configured"},
                    "remaining_external_checks": [],
                },
                indent=2,
            )
            + "\n",
            encoding="utf-8",
        )

        baseline = root / "baseline.json"
        baseline_record = {
            "model": MODEL_ID,
            "measured_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
            "metric": "mAP@50",
            "comparator": "gte",
            "threshold": 0.5,
            "observed_value": 0.6,
            "map50": 0.6,
            "acceptance_id": "artifact-fixture/v1",
            "acceptance_sha256": acceptance_digest,
            "dataset_sha256": "a" * 64,
            "passes_acceptance": True,
        }
        baseline.write_text(json.dumps(baseline_record), encoding="utf-8")

        economics = root / "economics.json"
        cost = run(
            [
                sys.executable,
                str(ROOT / "scripts" / "cost_model.py"),
                "--streams",
                "1",
                "--acceptance",
                str(acceptance),
                "--json",
            ],
            cwd=root,
        )
        if cost.returncode != 0:
            raise AssertionError(f"cost model failed: {cost.stderr}")
        economics.write_text(cost.stdout, encoding="utf-8")

        for ordinal, action in enumerate(
            (
                "baseline_measured",
                "artifact_verified",
                "delivery_handoff_emitted",
                "crossover_delivered",
            ),
            1,
        ):
            append_ledger(root, acceptance, artifact, action, ordinal)

        other_acceptance = root / "other-acceptance.json"
        other_payload = json.loads(acceptance.read_text(encoding="utf-8"))
        other_payload["acceptance_id"] = "other-session/v1"
        other_acceptance.write_text(json.dumps(other_payload), encoding="utf-8")
        append_ledger(root, other_acceptance, artifact, "baseline_measured", 99)

        validator = [
            sys.executable,
            str(SCRIPTS / "validate_proof_chain.py"),
            "--project-root",
            str(root),
            "--acceptance",
            str(acceptance),
            "--baseline",
            str(baseline),
            "--handoff",
            str(handoff),
            "--ledger",
            str(root / "ledger.jsonl"),
            "--economics",
            str(economics),
        ]
        other_only_ledger = root / "other-only-ledger.jsonl"
        ledger_rows = [json.loads(line) for line in (root / "ledger.jsonl").read_text(encoding="utf-8").splitlines()]
        other_only_ledger.write_text(
            "\n".join(
                json.dumps(row)
                for row in ledger_rows
                if not (row.get("action") == "baseline_measured" and row.get("acceptance_id") == "artifact-fixture/v1")
            )
            + "\n",
            encoding="utf-8",
        )
        other_only_validator = list(validator)
        ledger_index = other_only_validator.index(str(root / "ledger.jsonl"))
        other_only_validator[ledger_index] = str(other_only_ledger)
        wrong_acceptance = run(other_only_validator, cwd=root)
        if wrong_acceptance.returncode == 0 or "baseline_measured" not in wrong_acceptance.stderr:
            raise AssertionError("another acceptance satisfied a missing target ledger action")
        verdict = require_pass(run(validator, cwd=root), "terminal proof chain")
        report = root / "decision-report.md"
        report.write_text(
            f"Acceptance: artifact-fixture/v1 / {acceptance_digest}\nProof chain: {verdict['chain_id']}\n",
            encoding="utf-8",
        )
        append_ledger(
            root,
            acceptance,
            artifact,
            "decision_report_emitted",
            5,
            report=report,
        )
        require_pass(run([*validator, "--report", str(report)], cwd=root), "report proof chain")
        report.write_text(report.read_text(encoding="utf-8") + "Decision: go\n", encoding="utf-8")
        tampered_report = run([*validator, "--report", str(report)], cwd=root)
        if tampered_report.returncode == 0 or "report digest" not in tampered_report.stderr:
            raise AssertionError("changed decision report retained a passing receipt")

        baseline_record["map50"] = 0.4
        baseline_record["observed_value"] = 0.4
        baseline_record["passes_acceptance"] = False
        baseline.write_text(json.dumps(baseline_record), encoding="utf-8")
        rejected = run(validator, cwd=root)
        if rejected.returncode == 0 or "does not pass" not in rejected.stderr:
            raise AssertionError(f"failed baseline entered a passing chain: {rejected}")
        baseline_record["map50"] = 0.6
        baseline_record["observed_value"] = 0.6
        baseline_record["passes_acceptance"] = True
        baseline_record["measured_at"] = "2999-01-01T00:00:00Z"
        baseline.write_text(json.dumps(baseline_record), encoding="utf-8")
        future = run(validator, cwd=root)
        if future.returncode == 0 or "future" not in future.stderr:
            raise AssertionError("future-dated baseline entered a passing chain")

    print("proof-chain assertions passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
