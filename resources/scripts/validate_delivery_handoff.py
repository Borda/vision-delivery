#!/usr/bin/env python3
"""Validate a Sentinel delivery handoff and its artifact directory."""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path
from typing import Any

ARTIFACT_KINDS = {"hosted-client", "local-runtime", "scaffold"}
REQUIRED_FILES = {
    "inference.py",
    "requirements.txt",
    "expected-self-test.json",
    "RUN.md",
}
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
RUN_PROVIDER_RE = re.compile(
    r"(?im)^\s*[-*]?\s*Provider dependency\s*:\s*`?([^`\n]+)`?\s*$"
)


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


def _reject_secrets(value: Any, path: str = "handoff") -> None:
    """Reject credential-shaped keys and values from nested handoff data."""
    if isinstance(value, dict):
        for key, child in value.items():
            if any(
                marker in key.casefold()
                for marker in ("password", "api_key", "token", "secret")
            ):
                raise ValueError(f"{path}.{key} must not contain credentials")
            _reject_secrets(child, f"{path}.{key}")
    elif isinstance(value, list):
        for index, child in enumerate(value):
            _reject_secrets(child, f"{path}[{index}]")
    elif isinstance(value, str) and SECRET_TEXT.search(value):
        raise ValueError(f"{path} contains credential-shaped text")


def validate_handoff(path: Path, project_root: Path) -> dict[str, Any]:
    """Validate handoff semantics and required artifact files."""
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ValueError(f"cannot read handoff JSON: {exc}") from exc
    data = _require_mapping(data, "handoff")
    _reject_secrets(data)

    for field in (
        "schema_version",
        "acceptance_id",
        "model_or_pipeline",
        "artifact_kind",
        "artifact_path",
        "provider_dependency",
        "data_boundary",
    ):
        _require_text(data, field)

    kind = data["artifact_kind"]
    if kind not in ARTIFACT_KINDS:
        raise ValueError(f"artifact_kind must be one of {sorted(ARTIFACT_KINDS)}")

    artifact_path = Path(data["artifact_path"])
    if artifact_path.is_absolute() or ".." in artifact_path.parts:
        raise ValueError("artifact_path must be project-relative and contained")
    root = project_root.resolve()
    artifact_dir = (root / artifact_path).resolve()
    if not artifact_dir.is_relative_to(root):
        raise ValueError("artifact_path escapes project root")
    missing = sorted(
        name for name in REQUIRED_FILES if not (artifact_dir / name).is_file()
    )
    if missing:
        raise ValueError(f"artifact directory is missing: {', '.join(missing)}")

    source = (artifact_dir / "inference.py").read_text(encoding="utf-8")
    run_text = (artifact_dir / "RUN.md").read_text(encoding="utf-8")
    source_kind = ARTIFACT_KIND_RE.search(source)
    run_kind = RUN_KIND_RE.search(run_text)
    if source_kind is None or run_kind is None:
        raise ValueError("artifact header and RUN.md must declare artifact kind")
    if source_kind.group(1) != run_kind.group(1) or source_kind.group(1) != kind:
        raise ValueError(
            "handoff, artifact header, and RUN.md disagree on artifact kind"
        )
    run_provider = RUN_PROVIDER_RE.search(run_text)
    if run_provider is None:
        raise ValueError("RUN.md must declare Provider dependency")
    handoff_provider = data["provider_dependency"].strip().casefold()
    if run_provider.group(1).strip().casefold() != handoff_provider:
        raise ValueError("handoff and RUN.md disagree on provider dependency")

    commands = _require_mapping(data.get("commands"), "commands")
    _require_text(commands, "self_test")
    live_command = commands.get("live")
    if not isinstance(live_command, str):
        raise ValueError("commands.live must be text")

    checks = _require_mapping(data.get("checks"), "checks")
    if checks.get("self_test") != "passed":
        raise ValueError("checks.self_test must be passed")
    live_status = checks.get("live_or_offline")
    if live_status not in {"passed", "not-run", "failed"}:
        raise ValueError("checks.live_or_offline has an invalid status")

    remaining = data.get("remaining_external_checks")
    if not isinstance(remaining, list):
        raise ValueError("remaining_external_checks must be a list")
    if kind in {"hosted-client", "local-runtime"}:
        if live_status != "passed":
            raise ValueError(f"{kind} requires a passed live_or_offline check")
        if not live_command.strip():
            raise ValueError(f"{kind} requires commands.live")
    elif live_status == "passed":
        raise ValueError("a scaffold cannot claim a passed live_or_offline check")
    elif not remaining:
        raise ValueError("a scaffold must list its remaining external checks")

    _require_mapping(data.get("input_schema"), "input_schema")
    _require_mapping(data.get("output_schema"), "output_schema")
    rollback = _require_mapping(data.get("rollback"), "rollback")
    _require_text(rollback, "target")
    _require_text(rollback, "owner")
    monitoring = _require_mapping(data.get("monitoring"), "monitoring")
    if monitoring.get("status") not in {"verified", "external", "not-configured"}:
        raise ValueError("monitoring.status has an invalid value")
    return data


def main() -> int:
    """Run the handoff validator and emit a JSON verdict."""
    parser = argparse.ArgumentParser(description=__doc__)
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
