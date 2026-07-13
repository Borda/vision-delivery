#!/usr/bin/env python3
"""Validate a generated artifact from an unrelated working directory."""

from __future__ import annotations

import argparse
import json
import os
import py_compile
import re
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Any

SECRET_ASSIGNMENT = re.compile(
    r"(?im)^\s*(?:[a-z0-9]+_)*(?:api_?key|token|secret|password|credentials?)"
    r"\s*=\s*"
    r"['\"](?!<|\$\{|\{)[^'\"]+['\"]"
)
ARTIFACT_KIND_RE = re.compile(
    r"(?im)^\s*ARTIFACT_KIND\s*=\s*['\"]"
    r"(hosted-client|local-runtime|scaffold)['\"]"
)
RUN_KIND_RE = re.compile(
    r"(?im)^\s*[-*]?\s*Artifact kind\s*:\s*`?"
    r"(hosted-client|local-runtime|scaffold)`?\s*$"
)
NETWORK_GUARD = '''"""Disable network access in Sentinel artifact checks."""
import socket


def _blocked(*_args, **_kwargs):
    raise RuntimeError("network disabled during Sentinel self-test")


class _BlockedSocket(socket.socket):
    def connect(self, *_args, **_kwargs):
        return _blocked()

    def connect_ex(self, *_args, **_kwargs):
        return _blocked()


socket.socket = _BlockedSocket
socket.create_connection = _blocked
socket.getaddrinfo = _blocked
'''
RUN_MD_FIELDS = (
    "artifact kind",
    "provider dependency",
    "python",
    "install",
    "live command",
    "output schema",
    "data movement",
    "environment variables",
    "acceptance id",
    "model/data version",
    "smoke status",
)


def parse_args() -> argparse.Namespace:
    """Parse the artifact and expected-output paths."""
    parser = argparse.ArgumentParser(
        description="Run secret, syntax, help, and deterministic self-test checks."
    )
    parser.add_argument("artifact", type=Path)
    parser.add_argument("--expect-json", required=True, type=Path)
    parser.add_argument("--timeout", type=float, default=15.0)
    return parser.parse_args()


def run_artifact(
    artifact: Path,
    *arguments: str,
    cwd: Path,
    timeout: float,
    network_guard: Path,
) -> subprocess.CompletedProcess[str]:
    """Run the artifact with credentials removed and networking blocked."""
    env = os.environ.copy()
    for name in tuple(env):
        normalized = name.casefold()
        if any(
            marker in normalized
            for marker in ("key", "token", "secret", "credential", "password", "auth")
        ):
            env.pop(name)
    env["PYTHONPATH"] = str(network_guard)
    env["SENTINEL_SELF_TEST"] = "1"
    return subprocess.run(
        [sys.executable, str(artifact), *arguments],
        cwd=cwd,
        env=env,
        text=True,
        capture_output=True,
        timeout=timeout,
        check=False,
    )


def parse_single_json(stdout: str) -> Any:
    """Parse exactly one non-empty JSON value from stdout."""
    lines = [line for line in stdout.splitlines() if line.strip()]
    if len(lines) != 1:
        raise ValueError(f"expected one JSON line, received {len(lines)}")
    return json.loads(lines[0])


def validate_artifact(artifact: Path, expected_path: Path, timeout: float) -> None:
    """Validate source safety and deterministic execution behavior."""
    artifact = artifact.resolve()
    expected_path = expected_path.resolve()
    if not artifact.is_file():
        raise ValueError(f"artifact does not exist: {artifact}")
    if not expected_path.is_file():
        raise ValueError(f"expected JSON does not exist: {expected_path}")
    if expected_path.parent != artifact.parent:
        raise ValueError("expected JSON must be stored beside the artifact")
    if expected_path.name != "expected-self-test.json":
        raise ValueError("expected JSON must be named expected-self-test.json")
    if not (artifact.parent / "requirements.txt").is_file():
        raise ValueError("artifact directory must include requirements.txt")
    run_path = artifact.parent / "RUN.md"
    if not run_path.is_file():
        raise ValueError("artifact directory must include RUN.md")
    run_text = run_path.read_text(encoding="utf-8").casefold()
    missing_fields = [field for field in RUN_MD_FIELDS if field not in run_text]
    if missing_fields:
        raise ValueError(f"RUN.md is missing fields: {', '.join(missing_fields)}")

    source = artifact.read_text(encoding="utf-8")
    if SECRET_ASSIGNMENT.search(source):
        raise ValueError("artifact contains a literal secret assignment")
    source_kind = ARTIFACT_KIND_RE.search(source)
    run_kind = RUN_KIND_RE.search(run_text)
    if source_kind is None:
        raise ValueError("artifact must declare ARTIFACT_KIND in its header")
    if run_kind is None:
        raise ValueError("RUN.md must declare a valid Artifact kind")
    if source_kind.group(1) != run_kind.group(1):
        raise ValueError("artifact header and RUN.md disagree on artifact kind")

    with tempfile.TemporaryDirectory() as compile_dir:
        py_compile.compile(
            str(artifact),
            cfile=str(Path(compile_dir) / "artifact.pyc"),
            doraise=True,
        )

    expected = json.loads(expected_path.read_text(encoding="utf-8"))
    if not isinstance(expected, dict) or expected.get(
        "artifact_kind"
    ) != source_kind.group(1):
        raise ValueError("expected JSON and artifact header disagree on artifact kind")
    with (
        tempfile.TemporaryDirectory() as run_dir,
        tempfile.TemporaryDirectory() as guard_dir,
    ):
        cwd = Path(run_dir)
        network_guard = Path(guard_dir)
        (network_guard / "sitecustomize.py").write_text(NETWORK_GUARD, encoding="utf-8")
        help_run = run_artifact(
            artifact,
            "--help",
            cwd=cwd,
            timeout=timeout,
            network_guard=network_guard,
        )
        if help_run.returncode != 0:
            raise ValueError(f"--help failed: {help_run.stderr.strip()}")
        self_test = run_artifact(
            artifact,
            "--self-test",
            cwd=cwd,
            timeout=timeout,
            network_guard=network_guard,
        )
        if self_test.returncode != 0:
            raise ValueError(f"--self-test failed: {self_test.stderr.strip()}")
        actual = parse_single_json(self_test.stdout)
    if actual != expected:
        raise ValueError(
            f"self-test mismatch: expected={expected!r}, actual={actual!r}"
        )


def main() -> int:
    """Validate one artifact and print a machine-readable verdict."""
    args = parse_args()
    try:
        validate_artifact(args.artifact, args.expect_json, args.timeout)
    except (
        OSError,
        ValueError,
        subprocess.SubprocessError,
        py_compile.PyCompileError,
    ) as exc:
        print(json.dumps({"status": "failed", "reason": str(exc)}), file=sys.stderr)
        return 1
    print(json.dumps({"status": "passed", "artifact": str(args.artifact.resolve())}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
