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
        state = root / ".vision-delivery"
        state.mkdir()
        labels = "".join(
            json.dumps({"image": f"img_{index:02d}.jpg", "flag": index % 3 == 0}) + "\n" for index in range(40)
        )
        # One wrong prediction keeps a pass (39 of 40) and gives the two files different digests.
        predictions = labels.replace('"img_01.jpg", "flag": false', '"img_01.jpg", "flag": true')
        gold, pred = state / "gold.jsonl", state / "pred.jsonl"
        gold.write_text(labels, encoding="utf-8", newline="\n")
        pred.write_text(predictions, encoding="utf-8", newline="\n")
        frozen_at = datetime.now(timezone.utc) - timedelta(minutes=1)
        acceptance = root / "acceptance.json"
        acceptance.write_text(
            json.dumps(
                {
                    "schema_version": "1",
                    "acceptance_id": "artifact-fixture/v1",
                    "frozen_at": frozen_at.isoformat().replace("+00:00", "Z"),
                    "metric": "accuracy",
                    "comparator": "gte",
                    "threshold": 0.8,
                    "unit": "fraction",
                    "dataset_sha256": hashlib.sha256(gold.read_bytes()).hexdigest(),
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
        scored = run(
            [sys.executable, str(SCRIPTS / "score_baseline.py"), "--gold", str(gold), "--pred", str(pred)]
            + ["--task", "flag", "--acceptance", str(acceptance), "--evidence-out", str(baseline)],
            cwd=root,
        )
        if scored.returncode != 0:
            raise AssertionError(f"score baseline failed: {scored.stderr}")
        baseline_record = json.loads(baseline.read_text(encoding="utf-8"))

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

        explicit = ["--gold", str(gold), "--pred", str(pred)]
        require_pass(run([*validator, *explicit], cwd=root), "explicit scored files")
        for changed, reason in (
            ({"observed_value": 0.4, "passes_acceptance": False}, "does not pass"),
            ({"measured_at": "2999-01-01T00:00:00Z"}, "future"),
            ({"verdict": "inconclusive", "interval_lower": 0.45, "interval_upper": 0.7}, "only pass counts"),
            ({"verdict": "no-verdict", "interval_lower": None, "interval_upper": None}, "only pass counts"),
            ({"verdict": "pass", "interval_lower": 0.45, "interval_upper": 0.7}, "does not clear"),
            ({"numerator": 40}, "numerator does not match a re-score"),
            ({"interval_lower": 0.85}, "interval_lower does not match a re-score"),
            ({"task": "text"}, "is not scored for task text"),
            ({"model": MODEL_ID, "target": None}, "must be scorer evidence"),
        ):
            baseline.write_text(json.dumps({**baseline_record, **changed}), encoding="utf-8")
            refused = run(validator, cwd=root)
            if refused.returncode == 0 or reason not in refused.stderr:
                raise AssertionError(f"self-declared baseline entered a passing chain: {changed} {refused.stderr}")
        baseline.write_text(json.dumps(baseline_record), encoding="utf-8")
        pred.write_text(labels, encoding="utf-8", newline="\n")
        moved = run(validator, cwd=root)
        if moved.returncode == 0 or "pass --gold" not in moved.stderr:
            raise AssertionError(f"baseline passed without its scored prediction file: {moved.stderr}")
        wrong = run([*validator, *explicit], cwd=root)
        if wrong.returncode == 0 or "does not have the baseline pred_sha256" not in wrong.stderr:
            raise AssertionError(f"explicit prediction file with another digest passed: {wrong.stderr}")
        pred.write_text(predictions, encoding="utf-8", newline="\n")
        require_pass(run(validator, cwd=root), "scorer evidence re-scored from its files")

    print("proof-chain assertions passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
