#!/usr/bin/env python3
"""Assert proof-bound artifact safety and delivery handoff contracts."""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import stat
import subprocess
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SKILL_ROOTS = (ROOT / "codex-skills", ROOT / "claude-skills")
RESOURCES = ROOT / "resources"
ARTIFACT_CONTRACT = RESOURCES / "artifact-contract.md"
SMOKE_HELPER = RESOURCES / "scripts" / "artifact_smoke.py"
HANDOFF_HELPER = RESOURCES / "scripts" / "validate_delivery_handoff.py"
DELIVERY_CHECK_HELPER = RESOURCES / "scripts" / "record_delivery_check.py"
FREEZE_CHECK_HELPER = RESOURCES / "scripts" / "freeze_delivery_check.py"
FREEZE_ACCEPTANCE_HELPER = RESOURCES / "scripts" / "freeze_acceptance.py"
MODALITY_SKILLS = (
    "classify-or-flag",
    "detect-and-analyze",
    "read-text",
    "recognize-pose-or-gesture",
    "segment-and-analyze",
    "track-and-count",
)
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


def read(path: Path) -> str:
    """Read one required repository file as UTF-8."""
    if not path.is_file():
        raise AssertionError(f"Missing required file: {path.relative_to(ROOT)}")
    return path.read_text(encoding="utf-8")


def require(text: str, needle: str, path: Path) -> None:
    """Require one exact phrase in an artifact contract."""
    if needle not in text:
        raise AssertionError(f"{path.relative_to(ROOT)} is missing {needle!r}")


def run(command: list[str], *, cwd: Path, env: dict[str, str] | None = None) -> subprocess.CompletedProcess[str]:
    """Run one bounded fixture command without raising on its exit status."""
    return subprocess.run(
        command,
        cwd=cwd,
        env=env,
        text=True,
        capture_output=True,
        timeout=20,
        check=False,
    )


def acceptance_payload() -> dict[str, object]:
    """Return the frozen acceptance fixture shared by proof tests."""
    return {
        "schema_version": "1",
        "acceptance_id": "artifact-fixture/v1",
        "frozen_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "metric": "exact_self_test",
        "comparator": "gte",
        "threshold": 1.0,
        "unit": "pass fraction",
        "dataset_sha256": "a" * 64,
        "model_or_pipeline": MODEL_ID,
        "confirmed_by": "fixture owner",
    }


def sha256_file(path: Path) -> str:
    """Return a fixture file digest."""
    return hashlib.sha256(path.read_bytes()).hexdigest()


def sha256_tree(root: Path) -> str:
    """Return the artifact-tree digest used by the public helpers."""
    digest = hashlib.sha256(b"SENTINEL-TREE-V2\0")
    for path in sorted(root.rglob("*")):
        if path.is_symlink():
            raise ValueError(f"artifact tree contains a symlink: {path}")
        relative = path.relative_to(root).as_posix().encode()
        mode = path.lstat().st_mode
        if stat.S_ISDIR(mode):
            entry_type = b"D"
            content = b""
        elif stat.S_ISREG(mode):
            entry_type = b"F"
            content = path.read_bytes()
        else:
            raise ValueError(f"artifact tree contains a special file: {path}")
        digest.update(entry_type)
        digest.update(len(relative).to_bytes(8, "big"))
        digest.update(relative)
        digest.update(stat.S_IMODE(mode).to_bytes(4, "big"))
        digest.update(len(content).to_bytes(8, "big"))
        digest.update(content)
    return digest.hexdigest()


def assert_static_contracts() -> None:
    """Reject embedded secrets and automatic generated-code execution claims."""
    contract = read(ARTIFACT_CONTRACT)
    for phrase in (
        "hosted-client",
        "local-runtime",
        "current upstream guidance",
        "--self-test",
        "--execute-reviewed",
        "freeze_delivery_check.py",
        "--check-contract",
        "check_contract_sha256",
        "acceptance_sha256",
        "helper-produced local evidence",
        "scaffold",
    ):
        require(contract, phrase, ARTIFACT_CONTRACT)

    for skills_root in SKILL_ROOTS:
        for name in MODALITY_SKILLS:
            path = skills_root / name / "SKILL.md"
            text = read(path)
            require(text, "artifact-contract.md", path)
            require(text, "hosted-client", path)
            if "ROBOFLOW_API_KEY" in text:
                raise AssertionError(f"{path.relative_to(ROOT)} freezes an upstream credential contract")


def _copy_fixture(root: Path) -> tuple[Path, Path, Path]:
    """Copy the hosted fixture and write its frozen acceptance record."""
    artifact_dir = root / "artifact"
    shutil.copytree(Path(__file__).with_name("fixtures") / "hosted-client", artifact_dir)
    acceptance = root / "acceptance.json"
    acceptance.write_text(json.dumps(acceptance_payload(), indent=2) + "\n", encoding="utf-8")
    return artifact_dir, acceptance, root / "self-test-evidence.json"


def assert_smoke_helper() -> None:
    """Require review before execution and proof-bound evidence after success."""
    with tempfile.TemporaryDirectory() as tmp:
        project_root = Path(tmp)
        invalid_acceptance = project_root / "invalid-acceptance.json"
        invalid_freeze = run(
            [
                sys.executable,
                str(FREEZE_ACCEPTANCE_HELPER),
                "--out",
                str(invalid_acceptance),
                "--acceptance-id",
                "invalid/v1",
                "--metric",
                "latency",
                "--comparator",
                "lte",
                "--threshold",
                "nan",
                "--unit",
                "ms",
                "--dataset-sha256",
                "a" * 64,
                "--model-or-pipeline",
                MODEL_ID,
                "--confirmed-by",
                "fixture owner",
            ],
            cwd=project_root,
        )
        if invalid_freeze.returncode == 0 or invalid_acceptance.exists():
            raise AssertionError("invalid acceptance left an immutable output file")
        artifact_dir, acceptance, evidence = _copy_fixture(project_root)
        artifact = artifact_dir / "inference.py"
        expected = artifact_dir / "expected-self-test.json"
        outside_marker = project_root / "outside-marker"
        original_source = artifact.read_text(encoding="utf-8")
        artifact.write_text(
            original_source + f"\nfrom pathlib import Path\nPath({str(outside_marker)!r}).write_text('bad')\n",
            encoding="utf-8",
        )
        base = [
            sys.executable,
            str(SMOKE_HELPER),
            str(artifact),
            "--expect-json",
            str(expected),
            "--acceptance",
            str(acceptance),
            "--evidence-out",
            str(evidence),
        ]
        unreviewed = run(base, cwd=project_root)
        if unreviewed.returncode != 2 or "review-required" not in unreviewed.stdout:
            raise AssertionError(f"unreviewed generated code was not stopped: {unreviewed}")
        if outside_marker.exists() or evidence.exists():
            raise AssertionError("unreviewed generated code produced side effects or evidence")
        artifact.write_text(original_source, encoding="utf-8")
        reviewed = run([*base, "--execute-reviewed"], cwd=project_root)
        if reviewed.returncode != 0:
            raise AssertionError(f"reviewed artifact smoke failed: {reviewed.stdout} {reviewed.stderr}")
        record = json.loads(evidence.read_text(encoding="utf-8"))
        if record.get("producer") != "sentinel-artifact-smoke":
            raise AssertionError(f"unexpected smoke evidence: {record}")
        if record.get("acceptance_sha256") != sha256_file(acceptance):
            raise AssertionError("smoke evidence is not bound to acceptance")

    secret_cases = {
        "mapping": 'SETTINGS = {"api_key": "literal"}\n',
        "query": 'URL = "https://example.invalid/x?token=literal"\n',
        "parenthesized": 'PASSWORD = ("literal")\n',
    }
    for case, source in secret_cases.items():
        with tempfile.TemporaryDirectory() as tmp:
            project_root = Path(tmp)
            artifact_dir, acceptance, evidence = _copy_fixture(project_root)
            (artifact_dir / f"unsafe-{case}.py").write_text(source, encoding="utf-8")
            proc = run(
                [
                    sys.executable,
                    str(SMOKE_HELPER),
                    str(artifact_dir / "inference.py"),
                    "--expect-json",
                    str(artifact_dir / "expected-self-test.json"),
                    "--acceptance",
                    str(acceptance),
                    "--evidence-out",
                    str(evidence),
                    "--execute-reviewed",
                ],
                cwd=project_root,
            )
            if proc.returncode == 0 or "secret" not in proc.stderr:
                raise AssertionError(f"secret case {case} was accepted: {proc}")


def assert_tree_digest_framing() -> None:
    """Reject the prior one-file/two-file ambiguous tree serialization."""
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        one_file = root / "one"
        two_files = root / "two"
        one_file.mkdir()
        two_files.mkdir()
        payload = b"payload"
        (one_file / "a").write_bytes((1).to_bytes(8, "big") + b"b" + payload)
        (two_files / "a").write_bytes(b"")
        (two_files / "b").write_bytes(payload)
        if sha256_tree(one_file) == sha256_tree(two_files):
            raise AssertionError("structurally different artifact trees collided")


def _handoff(
    *,
    artifact_kind: str,
    artifact_digest: str,
    acceptance_digest: str,
    self_evidence: str,
    live_evidence: str,
    live_status: str,
    live_command: list[str],
    expected_stdout_sha256: str,
    check_contract: str,
    check_contract_sha256: str,
) -> dict[str, object]:
    """Build one digest-bound handoff fixture."""
    return {
        "schema_version": "2",
        "acceptance_id": "artifact-fixture/v1",
        "acceptance_path": "acceptance.json",
        "acceptance_sha256": acceptance_digest,
        "model_or_pipeline": MODEL_ID,
        "artifact_kind": artifact_kind,
        "artifact_path": "artifact",
        "artifact_sha256": artifact_digest,
        "input_schema": {},
        "output_schema": {},
        "provider_dependency": "simulated provider",
        "data_boundary": "fixture only",
        "commands": {
            "self_test": ["<current-python>", "inference.py", "--self-test"],
            "live": live_command if live_status == "passed" else [],
        },
        "expected_stdout_sha256": expected_stdout_sha256,
        "check_contract_path": check_contract,
        "check_contract_sha256": check_contract_sha256,
        "checks": {"self_test": "passed", "live_or_offline": live_status},
        "evidence": {
            "self_test": self_evidence,
            "live_or_offline": live_evidence,
        },
        "rollback": {"target": "fixture/v0", "owner": "fixture owner"},
        "monitoring": {"status": "not-configured"},
        "remaining_external_checks": ([] if live_status == "passed" else ["run a representative live request"]),
    }


def assert_handoff_helper() -> None:
    """Reject self-declared, stale, and altered-artifact delivery claims."""
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        artifact_dir, acceptance, self_evidence = _copy_fixture(root)
        smoke = run(
            [
                sys.executable,
                str(SMOKE_HELPER),
                str(artifact_dir / "inference.py"),
                "--expect-json",
                str(artifact_dir / "expected-self-test.json"),
                "--acceptance",
                str(acceptance),
                "--evidence-out",
                str(self_evidence),
                "--execute-reviewed",
            ],
            cwd=root,
        )
        if smoke.returncode != 0:
            raise AssertionError(f"fixture smoke failed: {smoke.stderr}")
        live_evidence = root / "live-evidence.json"
        live_command = [sys.executable, "inference.py"]
        expected_stdout_sha256 = hashlib.sha256(LIVE_OUTPUT).hexdigest()
        check_contract = root / "live-check-contract.json"
        invalid_contract = root / "invalid-check-contract.json"
        invalid_freeze = run(
            [
                sys.executable,
                str(FREEZE_CHECK_HELPER),
                "--out",
                str(invalid_contract),
                "--acceptance",
                str(acceptance),
                "--artifact-dir",
                str(artifact_dir),
                "--check",
                "live",
                "--expected-stdout-sha256",
                "not-a-digest",
                "--confirmed-by",
                "fixture owner",
                "--data-consent-id",
                "fixture-consent",
                "--",
                *live_command,
            ],
            cwd=root,
        )
        if invalid_freeze.returncode == 0 or invalid_contract.exists():
            raise AssertionError("invalid delivery contract left an immutable output")
        unused_entrypoint = root / "unused-entrypoint-contract.json"
        bypass_freeze = run(
            [
                sys.executable,
                str(FREEZE_CHECK_HELPER),
                "--out",
                str(unused_entrypoint),
                "--acceptance",
                str(acceptance),
                "--artifact-dir",
                str(artifact_dir),
                "--check",
                "live",
                "--expected-stdout-sha256",
                hashlib.sha256(b"bypass\n").hexdigest(),
                "--confirmed-by",
                "fixture owner",
                "--data-consent-id",
                "fixture-consent",
                "--",
                sys.executable,
                "-c",
                "print('bypass')",
                "inference.py",
            ],
            cwd=root,
        )
        if bypass_freeze.returncode == 0 or unused_entrypoint.exists():
            raise AssertionError("unused inference.py argv token bypassed command grammar")
        fake_python = root / "python"
        fake_python.write_text(
            "#!/bin/sh\nprintf 'bypass\\n'\n",
            encoding="utf-8",
        )
        fake_python.chmod(0o700)
        spoofed_contract = root / "spoofed-python-contract.json"
        spoofed_freeze = run(
            [
                sys.executable,
                str(FREEZE_CHECK_HELPER),
                "--out",
                str(spoofed_contract),
                "--acceptance",
                str(acceptance),
                "--artifact-dir",
                str(artifact_dir),
                "--check",
                "live",
                "--expected-stdout-sha256",
                hashlib.sha256(b"bypass\n").hexdigest(),
                "--confirmed-by",
                "fixture owner",
                "--data-consent-id",
                "fixture-consent",
                "--",
                str(fake_python),
                "inference.py",
            ],
            cwd=root,
        )
        if spoofed_freeze.returncode == 0 or spoofed_contract.exists():
            raise AssertionError("attacker-controlled Python executable bypassed command binding")
        frozen = run(
            [
                sys.executable,
                str(FREEZE_CHECK_HELPER),
                "--out",
                str(check_contract),
                "--acceptance",
                str(acceptance),
                "--artifact-dir",
                str(artifact_dir),
                "--check",
                "live",
                "--expected-stdout-sha256",
                expected_stdout_sha256,
                "--confirmed-by",
                "fixture owner",
                "--data-consent-id",
                "fixture-consent",
                "--",
                *live_command,
            ],
            cwd=root,
        )
        if frozen.returncode != 0:
            raise AssertionError(f"delivery-check contract failed: {frozen.stderr}")
        self_test_as_live = run(
            [
                sys.executable,
                str(DELIVERY_CHECK_HELPER),
                "--acceptance",
                str(acceptance),
                "--artifact-dir",
                str(artifact_dir),
                "--check-contract",
                str(check_contract),
                "--evidence-out",
                str(root / "false-live-evidence.json"),
                "--execute-reviewed",
                "--",
                sys.executable,
                "inference.py",
                "--self-test",
            ],
            cwd=root,
        )
        if self_test_as_live.returncode == 0:
            raise AssertionError("artifact self-test was accepted as live evidence")
        live = run(
            [
                sys.executable,
                str(DELIVERY_CHECK_HELPER),
                "--acceptance",
                str(acceptance),
                "--artifact-dir",
                str(artifact_dir),
                "--check-contract",
                str(check_contract),
                "--evidence-out",
                str(live_evidence),
                "--execute-reviewed",
                "--",
                *live_command,
            ],
            cwd=root,
            env={**os.environ, "SENTINEL_FIXTURE_TOKEN": "fixture-only"},
        )
        if live.returncode != 0:
            raise AssertionError(f"fixture live record failed: {live.stderr}")
        handoff = root / "handoff.json"
        payload = _handoff(
            artifact_kind="hosted-client",
            artifact_digest=sha256_tree(artifact_dir),
            acceptance_digest=sha256_file(acceptance),
            self_evidence=self_evidence.name,
            live_evidence=live_evidence.name,
            live_status="passed",
            live_command=live_command,
            expected_stdout_sha256=expected_stdout_sha256,
            check_contract=check_contract.name,
            check_contract_sha256=sha256_file(check_contract),
        )
        handoff.write_text(json.dumps(payload), encoding="utf-8")
        passed = run(
            [
                sys.executable,
                str(HANDOFF_HELPER),
                str(handoff),
                "--project-root",
                str(root),
            ],
            cwd=root,
        )
        if passed.returncode != 0:
            raise AssertionError(f"valid proof chain failed: {passed.stderr}")

        commands = payload["commands"]
        if not isinstance(commands, dict):
            raise AssertionError("fixture commands is not an object")
        commands["live"] = [sys.executable, "inference.py", "--self-test"]
        handoff.write_text(json.dumps(payload), encoding="utf-8")
        unrelated = run(
            [
                sys.executable,
                str(HANDOFF_HELPER),
                str(handoff),
                "--project-root",
                str(root),
            ],
            cwd=root,
        )
        if unrelated.returncode == 0:
            raise AssertionError("evidence for a different command was accepted")
        commands["live"] = live_command

        commands["self_test"] = [sys.executable, "inference.py", "--self-test"]
        handoff.write_text(json.dumps(payload), encoding="utf-8")
        false_self_test = run(
            [
                sys.executable,
                str(HANDOFF_HELPER),
                str(handoff),
                "--project-root",
                str(root),
            ],
            cwd=root,
        )
        if false_self_test.returncode == 0:
            raise AssertionError("handoff claimed an unverified self-test executable")
        commands["self_test"] = ["<current-python>", "inference.py", "--self-test"]

        outside = root / "outside"
        outside.mkdir()
        (outside / "payload.py").write_text("PAYLOAD = True\n", encoding="utf-8")
        (artifact_dir / "modules").symlink_to(outside, target_is_directory=True)
        handoff.write_text(json.dumps(payload), encoding="utf-8")
        symlinked = run(
            [
                sys.executable,
                str(HANDOFF_HELPER),
                str(handoff),
                "--project-root",
                str(root),
            ],
            cwd=root,
        )
        if symlinked.returncode == 0:
            raise AssertionError("directory symlink added after smoke was accepted")
        (artifact_dir / "modules").unlink()

        live_record = json.loads(live_evidence.read_text(encoding="utf-8"))
        original_checked_at = live_record["checked_at"]
        live_record["checked_at"] = "2999-01-01T00:00:00Z"
        live_evidence.write_text(json.dumps(live_record), encoding="utf-8")
        future = run(
            [
                sys.executable,
                str(HANDOFF_HELPER),
                str(handoff),
                "--project-root",
                str(root),
            ],
            cwd=root,
        )
        if future.returncode == 0:
            raise AssertionError("future-dated local evidence was accepted")
        live_record["checked_at"] = original_checked_at
        live_evidence.write_text(json.dumps(live_record), encoding="utf-8")

        payload["acceptance_sha256"] = "0" * 64
        handoff.write_text(json.dumps(payload), encoding="utf-8")
        forged = run(
            [
                sys.executable,
                str(HANDOFF_HELPER),
                str(handoff),
                "--project-root",
                str(root),
            ],
            cwd=root,
        )
        if forged.returncode == 0:
            raise AssertionError("forged acceptance digest was accepted")
        payload["acceptance_sha256"] = sha256_file(acceptance)

        (artifact_dir / "inference.py").write_text('ARTIFACT_KIND = "hosted-client"\n', encoding="utf-8")
        payload["artifact_sha256"] = sha256_tree(artifact_dir)
        handoff.write_text(json.dumps(payload), encoding="utf-8")
        altered = run(
            [
                sys.executable,
                str(HANDOFF_HELPER),
                str(handoff),
                "--project-root",
                str(root),
            ],
            cwd=root,
        )
        if altered.returncode == 0:
            raise AssertionError("artifact altered after verification was accepted")


def main() -> int:
    """Run artifact contract assertions and return a shell status."""
    assert_static_contracts()
    print("PASS assert_static_contracts")
    assert_smoke_helper()
    print("PASS assert_smoke_helper")
    assert_tree_digest_framing()
    print("PASS assert_tree_digest_framing")
    assert_handoff_helper()
    print("PASS assert_handoff_helper")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except AssertionError as exc:
        print(f"artifact contract failed: {exc}", file=sys.stderr)
        raise SystemExit(1) from exc
