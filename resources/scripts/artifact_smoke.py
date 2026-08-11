#!/usr/bin/env python3
"""Validate a generated artifact from an unrelated working directory."""

from __future__ import annotations

import argparse
import ast
import hashlib
import json
import os
import py_compile
import re
import subprocess
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from proof_chain import load_acceptance, sha256_file, sha256_tree, write_json_exclusive

SECRET_NAME = re.compile(r"(?i)(?:^|[_-])(?:api[_-]?key|token|secret|password|credentials?)(?:$|[_-])")
SECRET_URL = re.compile(
    r"(?i)[?&](?:api[_-]?key|key|signature|sig|token|secret|password)="
    r"(?!<|\$\{|\{)[^&\s'\"`]+"
)
TEXT_SUFFIXES = {".py", ".json", ".md", ".txt", ".toml", ".yaml", ".yml"}
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


class ReviewRequired(ValueError):
    """Raised when static checks pass but reviewed execution was not authorized."""


def parse_args() -> argparse.Namespace:
    """Parse the artifact and expected-output paths."""
    parser = argparse.ArgumentParser(description="Run secret, syntax, help, and deterministic self-test checks.")
    parser.add_argument("artifact", type=Path)
    parser.add_argument("--expect-json", required=True, type=Path)
    parser.add_argument("--acceptance", required=True, type=Path)
    parser.add_argument("--evidence-out", required=True, type=Path)
    parser.add_argument("--timeout", type=float, default=15.0)
    parser.add_argument(
        "--execute-reviewed",
        action="store_true",
        help="Confirm a human reviewed the generated code and host privileges.",
    )
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
        if any(marker in normalized for marker in ("key", "token", "secret", "credential", "password", "auth")):
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


def _literal_secret(value: ast.AST) -> bool:
    """Return whether an AST value is a non-placeholder string literal."""
    if not isinstance(value, ast.Constant) or not isinstance(value.value, str):
        return False
    stripped = value.value.strip()
    return bool(stripped) and not stripped.startswith(("<", "${", "{"))


def _target_names(target: ast.AST) -> list[str]:
    """Return assignment identifiers represented by one AST target."""
    if isinstance(target, ast.Name):
        return [target.id]
    if isinstance(target, ast.Attribute):
        return [target.attr]
    if isinstance(target, (ast.Tuple, ast.List)):
        return [name for child in target.elts for name in _target_names(child)]
    return []


def _scan_python_secrets(path: Path, text: str) -> None:
    """Reject Python literal secrets in assignments and dictionary values."""
    try:
        tree = ast.parse(text, filename=str(path))
    except SyntaxError:
        return
    for node in ast.walk(tree):
        if isinstance(node, (ast.Assign, ast.AnnAssign)):
            targets = node.targets if isinstance(node, ast.Assign) else [node.target]
            value = node.value
            if (
                any(SECRET_NAME.search(name) for target in targets for name in _target_names(target))
                and value is not None
                and _literal_secret(value)
            ):
                raise ValueError(f"artifact contains a literal secret assignment: {path.name}")
        if isinstance(node, ast.Dict):
            for key, value in zip(node.keys, node.values, strict=True):
                if (
                    isinstance(key, ast.Constant)
                    and isinstance(key.value, str)
                    and SECRET_NAME.search(key.value)
                    and _literal_secret(value)
                ):
                    raise ValueError(f"artifact contains a literal secret mapping: {path.name}")


def scan_artifact_secrets(artifact_dir: Path) -> None:
    """Scan the full artifact tree for common embedded secret forms."""
    for path in sorted(artifact_dir.rglob("*")):
        if path.is_symlink():
            raise ValueError(f"artifact tree contains a symlink: {path.name}")
        if not path.is_file() or path.suffix.casefold() not in TEXT_SUFFIXES:
            continue
        text = path.read_text(encoding="utf-8")
        if SECRET_URL.search(text):
            raise ValueError(f"artifact contains a query-string secret: {path.name}")
        if path.suffix.casefold() == ".py":
            _scan_python_secrets(path, text)


def validate_artifact(
    artifact: Path,
    expected_path: Path,
    acceptance_path: Path,
    evidence_out: Path,
    timeout: float,
    *,
    execute_reviewed: bool,
) -> dict[str, Any]:
    """Validate static safety, then run only explicitly reviewed generated code."""
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
    acceptance_path = acceptance_path.resolve()
    evidence_out = evidence_out.absolute()
    acceptance = load_acceptance(acceptance_path)
    if evidence_out.exists() or evidence_out.is_symlink():
        raise ValueError("evidence output already exists")
    if evidence_out.is_relative_to(artifact.parent):
        raise ValueError("evidence output must be outside the artifact directory")
    if not (artifact.parent / "requirements.txt").is_file():
        raise ValueError("artifact directory must include requirements.txt")
    run_path = artifact.parent / "RUN.md"
    if not run_path.is_file():
        raise ValueError("artifact directory must include RUN.md")
    run_text = run_path.read_text(encoding="utf-8").casefold()
    missing_fields = [field for field in RUN_MD_FIELDS if field not in run_text]
    if missing_fields:
        raise ValueError(f"RUN.md is missing fields: {', '.join(missing_fields)}")

    scan_artifact_secrets(artifact.parent)
    source = artifact.read_text(encoding="utf-8")
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
    if not isinstance(expected, dict) or expected.get("artifact_kind") != source_kind.group(1):
        raise ValueError("expected JSON and artifact header disagree on artifact kind")
    if not execute_reviewed:
        raise ReviewRequired("static checks passed; review generated code, then rerun with --execute-reviewed")
    artifact_digest = sha256_tree(artifact.parent)
    acceptance_digest = sha256_file(acceptance_path)
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
        raise ValueError(f"self-test mismatch: expected={expected!r}, actual={actual!r}")
    evidence = {
        "schema_version": "2",
        "producer": "sentinel-artifact-smoke",
        "status": "passed",
        "check": "self_test",
        "checked_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "acceptance_id": acceptance["acceptance_id"],
        "acceptance_sha256": acceptance_digest,
        "artifact_sha256": artifact_digest,
        "artifact_kind": source_kind.group(1),
        "command": ["<current-python>", "inference.py", "--self-test"],
        "command_sha256": hashlib.sha256(
            json.dumps(
                ["<current-python>", "inference.py", "--self-test"],
                separators=(",", ":"),
            ).encode()
        ).hexdigest(),
        "expected_output_sha256": hashlib.sha256(expected_path.read_bytes()).hexdigest(),
        "checks": {
            "secret_scan": "passed",
            "syntax": "passed",
            "help": "passed",
            "self_test": "passed",
        },
    }
    write_json_exclusive(evidence_out, evidence)
    return evidence


def main() -> int:
    """Validate one artifact and print a machine-readable verdict."""
    args = parse_args()
    try:
        evidence = validate_artifact(
            args.artifact,
            args.expect_json,
            args.acceptance,
            args.evidence_out,
            args.timeout,
            execute_reviewed=args.execute_reviewed,
        )
    except ReviewRequired as exc:
        print(json.dumps({"status": "review-required", "reason": str(exc)}))
        return 2
    except (
        OSError,
        ValueError,
        subprocess.SubprocessError,
        py_compile.PyCompileError,
    ) as exc:
        print(json.dumps({"status": "failed", "reason": str(exc)}), file=sys.stderr)
        return 1
    print(
        json.dumps(
            {
                "status": "passed",
                "artifact": str(args.artifact.resolve()),
                "artifact_sha256": evidence["artifact_sha256"],
                "acceptance_sha256": evidence["acceptance_sha256"],
                "evidence": str(args.evidence_out),
            }
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
