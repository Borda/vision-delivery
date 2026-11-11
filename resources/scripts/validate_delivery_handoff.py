#!/usr/bin/env python3
"""Validate a Sentinel delivery handoff and its artifact directory.

The checks run as four steps that `check_delivery.py` reports by name: the handoff record
(`check_handoff_record`), the recorded self-test (`check_self_test`), the frozen delivery-check
contract (`check_delivery_contract`), and the recorded live or offline check
(`check_live_evidence`). `validate_handoff` runs all of them in that order.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from proof_chain import (
    load_acceptance,
    load_check_contract,
    load_json,
    sha256_file,
    sha256_tree,
    validate_artifact_command,
    validate_evidence,
)

ARTIFACT_KINDS = {"hosted-client", "local-runtime", "scaffold"}
#: Artifact kinds that need a live or offline check, mapped to the check kind they need.
LIVE_CHECK_KINDS = {"hosted-client": "live", "local-runtime": "offline"}
LIVE_STATUSES = {"passed", "not-run", "failed"}
CANONICAL_SELF_TEST = ["<current-python>", "inference.py", "--self-test"]
REQUIRED_FILES = {
    "inference.py",
    "requirements.txt",
    "expected-self-test.json",
    "RUN.md",
}
REQUIRED_TEXT_FIELDS = (
    "schema_version",
    "acceptance_id",
    "acceptance_path",
    "acceptance_sha256",
    "model_or_pipeline",
    "artifact_kind",
    "artifact_path",
    "provider_dependency",
    "data_boundary",
)
SECRET_TEXT = re.compile(
    r"(?i)(?:api[_-]?key\s*[=:]|authorization\s*:|bearer\s+|"
    r"password\s*[=:]|token\s*[=:]|[?&](?:signature|sig|token)=)"
)
ARTIFACT_KIND_RE = re.compile(
    r"(?im)^\s*ARTIFACT_KIND\s*=\s*['\"]"
    r"(hosted-client|local-runtime|scaffold)['\"]"
)
RUN_KIND_RE = re.compile(
    r"(?im)^\s*[-*]?\s*Artifact kind\s*:\s*`?"
    r"(hosted-client|local-runtime|scaffold)`?\s*$"
)
RUN_PROVIDER_RE = re.compile(r"(?im)^\s*[-*]?\s*Provider dependency\s*:\s*`?([^`\n]+)`?\s*$")
RUN_ACCEPTANCE_RE = re.compile(r"(?im)^\s*[-*]?\s*Acceptance id\s*:\s*`?([^`\n]+)`?\s*$")
RUN_MODEL_RE = re.compile(r"(?im)^\s*[-*]?\s*Model/data version\s*:\s*`?([^`\n]+)`?\s*$")


@dataclass(frozen=True)
class HandoffContext:
    """A handoff record that passed its own checks, plus the facts the later steps need."""

    data: dict[str, Any]
    root: Path
    acceptance: dict[str, Any]
    acceptance_sha256: str
    artifact_dir: Path
    artifact_sha256: str
    kind: str


def _require_mapping(value: Any, field: str) -> dict[str, Any]:
    """Return a required mapping or raise a field-specific error."""
    if not isinstance(value, dict):
        raise ValueError(f"{field} must be an object")
    return value


def _require_text(data: dict[str, Any], field: str) -> str:
    """Return a required non-empty text field."""
    value = data.get(field)
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{field} must be non-empty text")
    return value.strip()


def _require_argv(data: dict[str, Any], field: str) -> list[str]:
    """Return a required canonical argv array."""
    value = data.get(field)
    if not isinstance(value, list) or not value or any(not isinstance(part, str) or not part for part in value):
        raise ValueError(f"{field} must be a non-empty argv array")
    return value


def _reject_secrets(value: Any, path: str = "handoff") -> None:
    """Reject credential-shaped keys and values from nested handoff data."""
    if isinstance(value, dict):
        for key, child in value.items():
            if any(marker in key.casefold() for marker in ("password", "api_key", "token", "secret")):
                raise ValueError(f"{path}.{key} must not contain credentials")
            _reject_secrets(child, f"{path}.{key}")
    elif isinstance(value, list):
        for index, child in enumerate(value):
            _reject_secrets(child, f"{path}[{index}]")
    elif isinstance(value, str) and SECRET_TEXT.search(value):
        raise ValueError(f"{path} contains credential-shaped text")


def _contained_file(root: Path, value: Any, field: str) -> Path:
    """Resolve a project-relative regular file without accepting symlinks."""
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{field} must be a project-relative path")
    relative = Path(value)
    if relative.is_absolute() or ".." in relative.parts:
        raise ValueError(f"{field} must be project-relative and contained")
    candidate = root / relative
    current = root
    for part in relative.parts:
        current = current / part
        if current.is_symlink():
            raise ValueError(f"{field} may not traverse a symlink")
    if not candidate.is_file():
        raise ValueError(f"{field} does not identify a regular file")
    return candidate


def read_handoff(path: Path) -> dict[str, Any]:
    """Read a handoff record and check its required fields, schema, and artifact kind.

    Args:
        path: The delivery handoff JSON file.

    Returns:
        The handoff record.

    Raises:
        ValueError: When the file is unreadable, holds credentials, or misses a required field.

    Examples:
        >>> import tempfile
        >>> with tempfile.TemporaryDirectory() as folder:
        ...     handoff = Path(folder) / "handoff.json"
        ...     _ = handoff.write_text('{"schema_version": "1"}', encoding="utf-8")
        ...     read_handoff(handoff)
        Traceback (most recent call last):
        ...
        ValueError: acceptance_id must be non-empty text
    """
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ValueError(f"cannot read handoff JSON: {exc}") from exc
    data = _require_mapping(data, "handoff")
    _reject_secrets(data)
    for field in REQUIRED_TEXT_FIELDS:
        _require_text(data, field)
    if data["schema_version"] != "2":
        raise ValueError("handoff schema_version must be 2")
    if data["artifact_kind"] not in ARTIFACT_KINDS:
        raise ValueError(f"artifact_kind must be one of {sorted(ARTIFACT_KINDS)}")
    return data


def _load_artifact(root: Path, data: dict[str, Any]) -> tuple[Path, str]:
    """Return the contained artifact directory and require the handoff digest to match its tree."""
    artifact_path = Path(data["artifact_path"])
    if artifact_path.is_absolute() or ".." in artifact_path.parts:
        raise ValueError("artifact_path must be project-relative and contained")
    artifact_dir = (root / artifact_path).resolve()
    if not artifact_dir.is_relative_to(root):
        raise ValueError("artifact_path escapes project root")
    missing = sorted(name for name in REQUIRED_FILES if not (artifact_dir / name).is_file())
    if missing:
        raise ValueError(f"artifact directory is missing: {', '.join(missing)}")
    artifact_digest = sha256_tree(artifact_dir)
    if data.get("artifact_sha256") != artifact_digest:
        raise ValueError("handoff artifact_sha256 does not match the artifact tree")
    return artifact_dir, artifact_digest


def _check_run_text(artifact_dir: Path, data: dict[str, Any]) -> None:
    """Require the artifact header, RUN.md, and the handoff to agree on kind, provider, acceptance, and model."""
    source = (artifact_dir / "inference.py").read_text(encoding="utf-8")
    run_text = (artifact_dir / "RUN.md").read_text(encoding="utf-8")
    source_kind = ARTIFACT_KIND_RE.search(source)
    run_kind = RUN_KIND_RE.search(run_text)
    if source_kind is None or run_kind is None:
        raise ValueError("artifact header and RUN.md must declare artifact kind")
    if source_kind.group(1) != run_kind.group(1) or source_kind.group(1) != data["artifact_kind"]:
        raise ValueError("handoff, artifact header, and RUN.md disagree on artifact kind")
    run_provider = RUN_PROVIDER_RE.search(run_text)
    if run_provider is None:
        raise ValueError("RUN.md must declare Provider dependency")
    handoff_provider = data["provider_dependency"].strip().casefold()
    if run_provider.group(1).strip().casefold() != handoff_provider:
        raise ValueError("handoff and RUN.md disagree on provider dependency")
    run_acceptance = RUN_ACCEPTANCE_RE.search(run_text)
    if run_acceptance is None or run_acceptance.group(1).strip() != data["acceptance_id"]:
        raise ValueError("RUN.md and handoff disagree on acceptance ID")
    run_model = RUN_MODEL_RE.search(run_text)
    if run_model is None or run_model.group(1).strip() != data["model_or_pipeline"]:
        raise ValueError("RUN.md and handoff disagree on model/data version")


def _check_record_fields(data: dict[str, Any]) -> None:
    """Check commands, status fields, the scaffold claims, and the operating-loop fields."""
    commands = _require_mapping(data.get("commands"), "commands")
    if _require_argv(commands, "self_test") != CANONICAL_SELF_TEST:
        raise ValueError("commands.self_test must use the fixed canonical argv")
    if not isinstance(commands.get("live"), list):
        raise ValueError("commands.live must be an argv array")
    checks = _require_mapping(data.get("checks"), "checks")
    evidence_paths = _require_mapping(data.get("evidence"), "evidence")
    live_status = checks.get("live_or_offline")
    if live_status not in LIVE_STATUSES:
        raise ValueError("checks.live_or_offline has an invalid status")
    remaining = data.get("remaining_external_checks")
    if not isinstance(remaining, list):
        raise ValueError("remaining_external_checks must be a list")
    if data["artifact_kind"] not in LIVE_CHECK_KINDS:
        if live_status == "passed":
            raise ValueError("a scaffold cannot claim a passed live_or_offline check")
        if not remaining:
            raise ValueError("a scaffold must list its remaining external checks")
        if evidence_paths.get("live_or_offline"):
            raise ValueError("a scaffold cannot include passed live/offline evidence")
    _require_mapping(data.get("input_schema"), "input_schema")
    _require_mapping(data.get("output_schema"), "output_schema")
    rollback = _require_mapping(data.get("rollback"), "rollback")
    _require_text(rollback, "target")
    _require_text(rollback, "owner")
    monitoring = _require_mapping(data.get("monitoring"), "monitoring")
    if monitoring.get("status") not in {"verified", "external", "not-configured"}:
        raise ValueError("monitoring.status has an invalid value")


def check_handoff_record(path: Path, project_root: Path) -> HandoffContext:
    """Check the handoff record against its acceptance file, artifact tree, and RUN.md.

    This step proves that the handed-off artifact is the tree the handoff names, byte for byte,
    and that the handoff, the artifact header, and RUN.md describe the same artifact.

    Args:
        path: The delivery handoff JSON file.
        project_root: The folder that the handoff's relative paths start from.

    Returns:
        The checked handoff and the acceptance and artifact facts the later steps need.

    Raises:
        ValueError: When any handoff field, file, or digest does not agree.

    Examples:
        >>> import tempfile
        >>> with tempfile.TemporaryDirectory() as folder:
        ...     check_handoff_record(Path(folder) / "absent.json", Path(folder))  # doctest: +ELLIPSIS
        Traceback (most recent call last):
        ...
        ValueError: cannot read handoff JSON: [Errno 2] No such file or directory: ...
    """
    data = read_handoff(path)
    root = project_root.resolve()
    acceptance_path = _contained_file(root, data["acceptance_path"], "acceptance_path")
    acceptance = load_acceptance(acceptance_path)
    acceptance_digest = sha256_file(acceptance_path)
    if data["acceptance_id"] != acceptance["acceptance_id"]:
        raise ValueError("handoff acceptance_id does not match the acceptance artifact")
    if data["acceptance_sha256"] != acceptance_digest:
        raise ValueError("handoff acceptance_sha256 does not match the acceptance artifact")
    if data["model_or_pipeline"] != acceptance["model_or_pipeline"]:
        raise ValueError("handoff model_or_pipeline does not match acceptance")
    artifact_dir, artifact_digest = _load_artifact(root, data)
    _check_run_text(artifact_dir, data)
    _check_record_fields(data)
    return HandoffContext(
        data=data,
        root=root,
        acceptance=acceptance,
        acceptance_sha256=acceptance_digest,
        artifact_dir=artifact_dir,
        artifact_sha256=artifact_digest,
        kind=data["artifact_kind"],
    )


def check_self_test(context: HandoffContext) -> None:
    """Check the recorded `artifact_smoke.py` self-test against the checked artifact tree.

    Args:
        context: The result of `check_handoff_record`.

    Raises:
        ValueError: When the evidence is missing, failed, stale, or bound to another artifact or acceptance.

    Examples:
        >>> context = HandoffContext({"evidence": {}}, Path("."), {}, "", Path("."), "", "scaffold")
        >>> check_self_test(context)
        Traceback (most recent call last):
        ...
        ValueError: evidence.self_test must be a project-relative path
    """
    data = context.data
    self_test_path = _contained_file(context.root, data["evidence"].get("self_test"), "evidence.self_test")
    self_test_evidence = load_json(self_test_path, "self-test evidence")
    validate_evidence(
        self_test_evidence,
        expected_producer="sentinel-artifact-smoke",
        expected_check="self_test",
        acceptance=context.acceptance,
        acceptance_sha256=context.acceptance_sha256,
        artifact_sha256=context.artifact_sha256,
    )
    if self_test_evidence.get("artifact_kind") != context.kind:
        raise ValueError("self-test evidence and handoff disagree on artifact kind")
    if self_test_evidence.get("command") != CANONICAL_SELF_TEST:
        raise ValueError("self-test evidence command is not canonical")
    self_test_digest = hashlib.sha256(json.dumps(CANONICAL_SELF_TEST, separators=(",", ":")).encode()).hexdigest()
    if self_test_evidence.get("command_sha256") != self_test_digest:
        raise ValueError("self-test evidence command digest is invalid")
    if data["checks"].get("self_test") != "passed":
        raise ValueError("checks.self_test must reflect passed verifier evidence")


def check_delivery_contract(context: HandoffContext) -> dict[str, Any]:
    """Check the delivery-check contract that froze the live command and output oracle before execution.

    Args:
        context: The result of `check_handoff_record` for a `hosted-client` or `local-runtime` artifact.

    Returns:
        The loaded delivery-check contract.

    Raises:
        ValueError: When the artifact is a scaffold, or the contract, its digest, kind, command, or
            oracle does not match the handoff.

    Examples:
        >>> context = HandoffContext({"commands": {"live": []}}, Path("."), {}, "", Path("."), "", "hosted-client")
        >>> check_delivery_contract(context)
        Traceback (most recent call last):
        ...
        ValueError: live must be a non-empty argv array
    """
    if context.kind not in LIVE_CHECK_KINDS:
        raise ValueError(f"a {context.kind} has no frozen live or offline check")
    data = context.data
    live_command = _require_argv(data["commands"], "live")
    validate_artifact_command(live_command, context.artifact_dir, self_test=False)
    check_contract_path = _contained_file(context.root, data.get("check_contract_path"), "check_contract_path")
    check_contract_digest = sha256_file(check_contract_path)
    if data.get("check_contract_sha256") != check_contract_digest:
        raise ValueError("handoff check_contract_sha256 does not match")
    check_contract = load_check_contract(
        check_contract_path,
        acceptance=context.acceptance,
        acceptance_sha256=context.acceptance_sha256,
        artifact_dir=context.artifact_dir,
        artifact_sha256=context.artifact_sha256,
    )
    if check_contract["check"] != LIVE_CHECK_KINDS[context.kind]:
        raise ValueError("delivery-check contract has the wrong check kind")
    if check_contract["command"] != live_command:
        raise ValueError("delivery-check contract command does not match handoff")
    if data.get("expected_stdout_sha256") != check_contract["expected_stdout_sha256"]:
        raise ValueError("handoff output oracle does not match frozen contract")
    return check_contract


def check_live_evidence(context: HandoffContext, check_contract: dict[str, Any]) -> None:
    """Check the recorded `record_delivery_check.py` outcome against the frozen contract.

    Args:
        context: The result of `check_handoff_record`.
        check_contract: The result of `check_delivery_contract`.

    Raises:
        ValueError: When the live or offline check did not pass, or its evidence names another
            command, contract, artifact, acceptance, or output.

    Examples:
        >>> context = HandoffContext({"checks": {}}, Path("."), {}, "", Path("."), "", "hosted-client")
        >>> check_live_evidence(context, {})
        Traceback (most recent call last):
        ...
        ValueError: hosted-client requires a passed live_or_offline check
    """
    data = context.data
    if data["checks"].get("live_or_offline") != "passed":
        raise ValueError(f"{context.kind} requires a passed live_or_offline check")
    live_command = data["commands"]["live"]
    live_path = _contained_file(context.root, data["evidence"].get("live_or_offline"), "evidence.live_or_offline")
    live_evidence = load_json(live_path, "live/offline evidence")
    validate_evidence(
        live_evidence,
        expected_producer="sentinel-reviewed-check",
        expected_check=check_contract["check"],
        acceptance=context.acceptance,
        acceptance_sha256=context.acceptance_sha256,
        artifact_sha256=context.artifact_sha256,
    )
    if live_evidence.get("command") != live_command:
        raise ValueError("live/offline evidence command does not match handoff argv")
    expected_command_digest = hashlib.sha256(json.dumps(live_command, separators=(",", ":")).encode()).hexdigest()
    if live_evidence.get("command_sha256") != expected_command_digest:
        raise ValueError("live/offline evidence command digest is invalid")
    if live_evidence.get("check_contract_sha256") != data.get("check_contract_sha256"):
        raise ValueError("live/offline evidence check contract does not match")
    expected_stdout = check_contract["expected_stdout_sha256"]
    if (
        live_evidence.get("expected_stdout_sha256") != expected_stdout
        or live_evidence.get("stdout_sha256") != expected_stdout
    ):
        raise ValueError("live/offline evidence does not match the output oracle")
    if context.kind == "hosted-client" and not live_evidence.get("data_consent_id"):
        raise ValueError("hosted-client live evidence requires data consent")


def validate_handoff(path: Path, project_root: Path) -> dict[str, Any]:
    """Validate handoff semantics, the artifact tree, and every recorded check outcome.

    A scaffold passes when its record is consistent; it has no live or offline check to verify.

    Args:
        path: The delivery handoff JSON file.
        project_root: The folder that the handoff's relative paths start from.

    Returns:
        The validated handoff record.

    Raises:
        ValueError: On the first check that fails.

    Examples:
        >>> import tempfile
        >>> with tempfile.TemporaryDirectory() as folder:
        ...     validate_handoff(Path(folder) / "absent.json", Path(folder))  # doctest: +ELLIPSIS
        Traceback (most recent call last):
        ...
        ValueError: cannot read handoff JSON: [Errno 2] No such file or directory: ...
    """
    context = check_handoff_record(path, project_root)
    check_self_test(context)
    if context.kind in LIVE_CHECK_KINDS:
        check_live_evidence(context, check_delivery_contract(context))
    return context.data


def main() -> int:
    """Run the handoff validator and emit a JSON verdict."""
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("handoff", type=Path)
    parser.add_argument("--project-root", required=True, type=Path)
    args = parser.parse_args()
    try:
        data = validate_handoff(args.handoff, args.project_root)
    except ValueError as exc:
        print(json.dumps({"status": "failed", "reason": str(exc)}), file=sys.stderr)
        return 1
    print(
        json.dumps(
            {
                "status": "passed",
                "artifact_kind": data["artifact_kind"],
                "acceptance_id": data["acceptance_id"],
            }
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
