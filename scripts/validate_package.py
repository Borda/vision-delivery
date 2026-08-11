#!/usr/bin/env python3
"""Validate a built Sentinel candidate for closure, portability, and hygiene."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import sys
from pathlib import Path, PurePosixPath
from typing import Any

MANIFEST_NAME = "package-manifest.json"
EXPECTED_SKILL_COUNT = 13
REQUIRED_FILES = (".mcp.json", "CHANGELOG.md", "LICENSE", "NOTICE", "README.md")
REQUIRED_PATHS = (
    ".agents/plugins/marketplace.json",
    ".claude-plugin/marketplace.json",
    ".claude-plugin/plugin.json",
    ".codex-plugin/plugin.json",
    "hooks/claude-hooks.json",
    "hooks/cta.js",
    "hooks/hooks.json",
    "assets/icon.png",
    "assets/logo.png",
    "resources/scripts/sentinel_doctor.py",
    "resources/scripts/artifact_smoke.py",
    "resources/scripts/freeze_acceptance.py",
    "resources/scripts/freeze_delivery_check.py",
    "resources/scripts/proof_chain.py",
    "resources/scripts/record_delivery_check.py",
    "resources/scripts/validate_delivery_handoff.py",
    "resources/scripts/validate_proof_chain.py",
    "scripts/cost_model.py",
    "scripts/ledger_append.py",
    "shared/capability-contract.md",
)
SECRET_PATTERNS = (
    re.compile(rb"-----BEGIN [A-Z ]*PRIVATE KEY-----"),
    re.compile(rb"AKIA[0-9A-Z]{16}"),
    re.compile(rb"gh[pousr]_[A-Za-z0-9]{20,}"),
    re.compile(rb"github_pat_[A-Za-z0-9_]{20,}"),
    re.compile(rb"xox[baprs]-[A-Za-z0-9-]{10,}"),
)


def read_json(path: Path) -> dict[str, Any]:
    """Read one required JSON object from a package path."""
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError(f"{path.name} is not a JSON object")
    return payload


def safe_relative(value: object) -> str | None:
    """Return a normalized safe package-relative path, or `None` when unsafe."""
    if not isinstance(value, str) or not value:
        return None
    path = PurePosixPath(value)
    if path.is_absolute() or ".." in path.parts or "\\" in value:
        return None
    return path.as_posix()


def skill_roster(package: Path, root_name: str) -> list[str]:
    """Return sorted discoverable skills below one package root."""
    root = package / root_name
    if not root.is_dir():
        return []
    return sorted(child.name for child in root.iterdir() if (child / "SKILL.md").is_file())


def inventory_findings(package: Path, manifest: dict[str, Any]) -> list[str]:
    """Return inventory, hash, path, and executable-mode violations."""
    findings: list[str] = []
    records = manifest.get("files")
    if not isinstance(records, list):
        return ["package manifest files must be an array"]

    seen: set[str] = set()
    for record in records:
        if not isinstance(record, dict):
            findings.append("package manifest contains a non-object file record")
            continue
        relative = safe_relative(record.get("path"))
        if relative is None:
            findings.append(f"unsafe manifest path: {record.get('path')!r}")
            continue
        if relative in seen:
            findings.append(f"duplicate manifest path: {relative}")
        seen.add(relative)
        path = package / relative
        if not path.is_file():
            findings.append(f"missing payload file: {relative}")
            continue
        expected_hash = record.get("sha256")
        actual_hash = hashlib.sha256(path.read_bytes()).hexdigest()
        if expected_hash != actual_hash:
            findings.append(f"payload hash mismatch: {relative}")
        if os.name == "posix" and bool(record.get("executable")) != bool(path.stat().st_mode & 0o111):
            findings.append(f"payload executable mode mismatch: {relative}")

    actual = {
        path.relative_to(package).as_posix()
        for path in package.rglob("*")
        if path.is_file() and path.name != MANIFEST_NAME
    }
    for relative in sorted(actual - seen):
        findings.append(f"extra unmanifested payload file: {relative}")
    return findings


def portability_findings(package: Path) -> list[str]:
    """Return symlink and case-collision findings for every candidate path."""
    findings: list[str] = []
    seen: dict[str, str] = {}
    for path in sorted(package.rglob("*")):
        relative = path.relative_to(package).as_posix()
        if path.is_symlink():
            findings.append(f"symlink in package: {relative}")
        if path.is_file():
            folded = relative.casefold()
            if folded in seen:
                findings.append(f"case collision: {seen[folded]} vs {relative}")
            seen[folded] = relative
    return findings


def hygiene_findings(package: Path, manifest: dict[str, Any]) -> list[str]:
    """Return personal-path and secret-material findings from inventoried bytes."""
    findings: list[str] = []
    home = str(Path.home()).encode("utf-8")
    for record in manifest.get("files", []):
        if not isinstance(record, dict):
            continue
        relative = safe_relative(record.get("path"))
        if relative is None:
            continue
        path = package / relative
        if not path.is_file():
            continue
        data = path.read_bytes()
        if home and home in data:
            findings.append(f"personal-path leak: {relative}")
        if any(pattern.search(data) for pattern in SECRET_PATTERNS):
            findings.append(f"secret-like material: {relative}")
    return findings


def component_findings(package: Path, manifest: dict[str, Any]) -> list[str]:
    """Return manifest-pointer, roster, metadata, and runtime closure findings."""
    findings = [
        f"missing required package path: {path}"
        for path in (*REQUIRED_FILES, *REQUIRED_PATHS)
        if not (package / path).is_file()
    ]
    if (package / "skills").exists():
        findings.append("retired default skills directory is present")
    if findings:
        return findings

    try:
        codex = read_json(package / ".codex-plugin/plugin.json")
        claude = read_json(package / ".claude-plugin/plugin.json")
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        return [f"manifest read failure: {exc}"]

    if codex.get("skills") != "./codex-skills/":
        findings.append("Codex manifest does not point to ./codex-skills/")
    if claude.get("skills") != "./claude-skills/":
        findings.append("Claude manifest does not point to ./claude-skills/")
    if codex.get("name") != claude.get("name") or codex.get("version") != claude.get("version"):
        findings.append("host manifests have different identity or version")

    codex_roster = skill_roster(package, "codex-skills")
    claude_roster = skill_roster(package, "claude-skills")
    declared_skills = manifest.get("skills", {})
    if not isinstance(declared_skills, dict):
        findings.append("package manifest skills must be an object")
    elif declared_skills.get("codex") != codex_roster or declared_skills.get("claude") != claude_roster:
        findings.append("package manifest skill roster does not match package contents")
    if codex_roster != claude_roster:
        findings.append("Codex and Claude skill rosters differ")
    if len(codex_roster) != EXPECTED_SKILL_COUNT:
        findings.append(f"expected {EXPECTED_SKILL_COUNT} skills, found {len(codex_roster)}")

    auth_metadata = package / "codex-skills/auth-setup/agents/openai.yaml"
    setup_metadata = package / "codex-skills/check-sentinel-setup/agents/openai.yaml"
    if "dependencies" not in auth_metadata.read_text(encoding="utf-8"):
        findings.append("Codex auth skill lacks MCP dependency metadata")
    if "dependencies" in setup_metadata.read_text(encoding="utf-8"):
        findings.append("offline setup skill declares an MCP dependency")
    return findings


def validate_package(package: Path) -> list[str]:
    """Return all closure findings for a deterministic candidate directory."""
    manifest_path = package / MANIFEST_NAME
    if not manifest_path.is_file():
        return [f"missing {MANIFEST_NAME}"]
    try:
        manifest = read_json(manifest_path)
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        return [f"invalid package manifest: {exc}"]
    if manifest.get("schema_version") != 1:
        return ["unsupported package manifest schema"]
    return [
        *inventory_findings(package, manifest),
        *portability_findings(package),
        *hygiene_findings(package, manifest),
        *component_findings(package, manifest),
    ]


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    """Parse package validator command-line options."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--package", required=True, type=Path, help="candidate directory")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    """Validate one candidate and return a shell-friendly status."""
    args = parse_args(argv)
    findings = validate_package(args.package.resolve())
    if findings:
        print("package validation failed:", file=sys.stderr)
        print("\n".join(f"- {finding}" for finding in findings), file=sys.stderr)
        return 1
    print(f"package validation passed: {args.package.resolve()}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
