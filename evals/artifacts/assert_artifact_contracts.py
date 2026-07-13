#!/usr/bin/env python3
"""Assert generated-artifact safety and arbitrary-CWD smoke contracts."""

from __future__ import annotations

import json
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SKILLS = ROOT / "skills"
RESOURCES = ROOT / "resources"
ARTIFACT_CONTRACT = RESOURCES / "artifact-contract.md"
SMOKE_HELPER = RESOURCES / "scripts" / "artifact_smoke.py"
HANDOFF_HELPER = RESOURCES / "scripts" / "validate_delivery_handoff.py"
MODALITY_SKILLS = (
    "classify-or-flag",
    "detect-and-analyze",
    "read-text",
    "recognize-pose-or-gesture",
    "segment-and-analyze",
    "track-and-count",
)


def read(path: Path) -> str:
    """Read one required repository file as UTF-8."""
    if not path.is_file():
        raise AssertionError(f"Missing required file: {path.relative_to(ROOT)}")
    return path.read_text(encoding="utf-8")


def require(text: str, needle: str, path: Path) -> None:
    """Require one exact phrase in an artifact contract."""
    if needle not in text:
        raise AssertionError(f"{path.relative_to(ROOT)} is missing {needle!r}")


def assert_static_contracts() -> None:
    """Reject embedded secrets and misleading portability claims."""
    contract = read(ARTIFACT_CONTRACT)
    for phrase in (
        "hosted-client",
        "local-runtime",
        "current upstream guidance",
        "--self-test",
        "arbitrary fresh working directory",
        "exact expected JSON",
        "scaffold",
        "live-path smoke",
    ):
        require(contract, phrase, ARTIFACT_CONTRACT)

    for name in MODALITY_SKILLS:
        path = SKILLS / name / "SKILL.md"
        text = read(path)
        require(text, "artifact-contract.md", path)
        require(text, "hosted-client", path)
        if "ROBOFLOW_API_KEY" in text:
            raise AssertionError(
                f"{path.relative_to(ROOT)} freezes an upstream credential contract"
            )
        if 'API_KEY = "<from environment>"' in text:
            raise AssertionError(f"{path.relative_to(ROOT)} embeds a fake API key")


def assert_smoke_helper() -> None:
    """Execute the artifact checker against a deterministic hosted-client fixture."""
    if not SMOKE_HELPER.is_file():
        raise AssertionError(f"Missing required file: {SMOKE_HELPER.relative_to(ROOT)}")

    fixture_dir = Path(__file__).with_name("fixtures") / "hosted-client"
    artifact = fixture_dir / "inference.py"
    expected = fixture_dir / "expected-self-test.json"
    with tempfile.TemporaryDirectory() as cwd:
        proc = subprocess.run(
            [
                sys.executable,
                str(SMOKE_HELPER),
                str(artifact),
                "--expect-json",
                str(expected),
            ],
            cwd=cwd,
            text=True,
            capture_output=True,
            timeout=20,
            check=False,
        )
    if proc.returncode != 0:
        raise AssertionError(
            "artifact smoke helper failed from arbitrary CWD:\n"
            f"stdout={proc.stdout}\nstderr={proc.stderr}"
        )
    result = json.loads(proc.stdout)
    if result.get("status") != "passed":
        raise AssertionError(f"unexpected artifact smoke result: {result}")

    with tempfile.TemporaryDirectory() as tmp:
        unsafe_dir = Path(tmp) / "unsafe"
        shutil.copytree(fixture_dir, unsafe_dir)
        unsafe_artifact = unsafe_dir / "inference.py"
        unsafe_artifact.write_text(
            unsafe_artifact.read_text(encoding="utf-8")
            + '\nROBOFLOW_API_KEY = "literal-secret"\n',
            encoding="utf-8",
        )
        unsafe = subprocess.run(
            [
                sys.executable,
                str(SMOKE_HELPER),
                str(unsafe_artifact),
                "--expect-json",
                str(unsafe_dir / "expected-self-test.json"),
            ],
            cwd=tmp,
            text=True,
            capture_output=True,
            timeout=20,
            check=False,
        )
    if unsafe.returncode == 0 or "literal secret assignment" not in unsafe.stderr:
        raise AssertionError(
            "artifact smoke helper did not reject a prefixed literal secret"
        )


def _handoff(
    artifact_kind: str, live_status: str, artifact_path: str = "artifact"
) -> dict:
    """Build a minimal handoff fixture for semantic validation."""
    return {
        "schema_version": "1",
        "acceptance_id": "artifact-fixture/v1",
        "model_or_pipeline": "deterministic-fixture/v1",
        "artifact_kind": artifact_kind,
        "artifact_path": artifact_path,
        "input_schema": {},
        "output_schema": {},
        "provider_dependency": "simulated provider",
        "data_boundary": "fixture only",
        "commands": {
            "self_test": "python inference.py --self-test",
            "live": "python inference.py" if live_status == "passed" else "",
        },
        "checks": {"self_test": "passed", "live_or_offline": live_status},
        "rollback": {"target": "fixture/v0", "owner": "fixture owner"},
        "monitoring": {"status": "not-configured"},
        "remaining_external_checks": (
            [] if live_status == "passed" else ["run a representative live request"]
        ),
    }


def assert_handoff_helper() -> None:
    """Require delivery claims to match live/offline proof status."""
    if not HANDOFF_HELPER.is_file():
        raise AssertionError(
            f"Missing required file: {HANDOFF_HELPER.relative_to(ROOT)}"
        )
    with tempfile.TemporaryDirectory() as tmp:
        project_root = Path(tmp)
        handoff = project_root / "handoff.json"
        artifact_dir = project_root / "artifact"
        artifact_dir.mkdir()
        (artifact_dir / "requirements.txt").write_text(
            "# standard library\n", encoding="utf-8"
        )
        (artifact_dir / "expected-self-test.json").write_text("{}\n", encoding="utf-8")
        for kind, file_kind, provider, live_status, expected_code in (
            ("hosted-client", "hosted-client", "simulated provider", "passed", 0),
            (
                "hosted-client",
                "hosted-client",
                "simulated provider",
                "not-run",
                1,
            ),
            ("local-runtime", "local-runtime", "simulated provider", "passed", 0),
            ("scaffold", "scaffold", "simulated provider", "not-run", 0),
            ("local-runtime", "hosted-client", "simulated provider", "passed", 1),
            ("hosted-client", "hosted-client", "different provider", "passed", 1),
        ):
            (artifact_dir / "inference.py").write_text(
                f'ARTIFACT_KIND = "{file_kind}"\n', encoding="utf-8"
            )
            (artifact_dir / "RUN.md").write_text(
                f"- Artifact kind: `{file_kind}`\n"
                f"- Provider dependency: `{provider}`\n",
                encoding="utf-8",
            )
            handoff.write_text(
                json.dumps(_handoff(kind, live_status)), encoding="utf-8"
            )
            proc = subprocess.run(
                [
                    sys.executable,
                    str(HANDOFF_HELPER),
                    str(handoff),
                    "--project-root",
                    str(project_root),
                ],
                text=True,
                capture_output=True,
                timeout=20,
                check=False,
            )
            if proc.returncode != expected_code:
                raise AssertionError(
                    f"handoff {kind}/{live_status} returned {proc.returncode}: "
                    f"stdout={proc.stdout} stderr={proc.stderr}"
                )


def main() -> int:
    """Run artifact contract assertions and return a shell status."""
    assert_static_contracts()
    print("PASS assert_static_contracts")
    assert_smoke_helper()
    print("PASS assert_smoke_helper")
    assert_handoff_helper()
    print("PASS assert_handoff_helper")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except AssertionError as exc:
        print(f"artifact contract failed: {exc}", file=sys.stderr)
        raise SystemExit(1) from exc
