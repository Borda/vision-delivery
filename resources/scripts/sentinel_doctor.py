#!/usr/bin/env python3
"""Check the installed Sentinel package without network or account access."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

EXPECTED_NAME = "sentinel"
EXPECTED_MCP = {"type": "http", "url": "https://mcp.roboflow.com/mcp"}
REQUIRED_RESOURCES = (
    "artifact-contract.md",
    "fde-methodology.md",
    "ledger-protocol.md",
    "model-selection.md",
    "roboflow-platform-lookup.md",
)


def codex_release_version(version: str) -> str:
    """Remove the plugin-creator Codex cache-buster from a release version."""
    release, marker, cachebuster = version.partition("+codex.")
    if marker and release and cachebuster and "+" not in cachebuster:
        return release
    return version


def read_object(path: Path) -> dict[str, Any]:
    """Read one JSON object or raise a concise validation error."""
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError("must contain a JSON object")
    return payload


def inspect_package(root: Path) -> dict[str, Any]:
    """Return deterministic package health evidence for a plugin root."""
    errors: list[str] = []
    manifests: dict[str, dict[str, Any]] = {}
    for host, relative in (
        ("codex", ".codex-plugin/plugin.json"),
        ("claude", ".claude-plugin/plugin.json"),
    ):
        path = root / relative
        try:
            manifests[host] = read_object(path)
        except (OSError, json.JSONDecodeError, ValueError) as exc:
            errors.append(f"{relative}: {exc}")

    for host, manifest in manifests.items():
        if manifest.get("name") != EXPECTED_NAME:
            errors.append(f"{host} manifest name is not {EXPECTED_NAME}")
        if manifest.get("skills") != "./skills/":
            errors.append(f"{host} manifest skills path is not ./skills/")
        if manifest.get("mcpServers") != "./.mcp.json":
            errors.append(f"{host} manifest MCP path is not ./.mcp.json")

    codex_version = str(manifests.get("codex", {}).get("version", ""))
    claude_version = str(manifests.get("claude", {}).get("version", ""))
    version = claude_version or codex_release_version(codex_version) or None
    if (
        not codex_version
        or not claude_version
        or codex_release_version(codex_version) != claude_version
    ):
        errors.append("Codex and Claude release versions are missing or different")

    try:
        mcp = read_object(root / ".mcp.json")
        servers = mcp.get("mcpServers")
        if not isinstance(servers, dict) or servers.get("roboflow") != EXPECTED_MCP:
            errors.append(
                ".mcp.json is not the expected URL-only Roboflow configuration"
            )
    except (OSError, json.JSONDecodeError, ValueError) as exc:
        errors.append(f".mcp.json: {exc}")

    skills_dir = root / "skills"
    skills = sorted(path.parent.name for path in skills_dir.glob("*/SKILL.md"))
    if "solve-cv-task" not in skills or "check-sentinel-setup" not in skills:
        errors.append("required front-door or setup-check skill is missing")

    missing_resources = [
        name for name in REQUIRED_RESOURCES if not (root / "resources" / name).is_file()
    ]
    if missing_resources:
        errors.append(f"missing resources: {', '.join(missing_resources)}")

    return {
        "status": "failed" if errors else "passed",
        "plugin_root": str(root),
        "version": version,
        "skill_count": len(skills),
        "mcp_url": EXPECTED_MCP["url"],
        "errors": errors,
        "external_checks": [
            "host plugin installed and enabled",
            "Roboflow sign-in completed",
            "authenticated Roboflow read succeeded",
        ],
    }


def main() -> int:
    """Parse CLI arguments, print package evidence, and return its status."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--plugin-root",
        type=Path,
        default=Path(__file__).resolve().parents[2],
        help="Sentinel plugin root; defaults to the package containing this script.",
    )
    parser.add_argument("--json", action="store_true", help="Emit compact JSON.")
    args = parser.parse_args()

    result = inspect_package(args.plugin_root.resolve())
    if args.json:
        print(json.dumps(result, sort_keys=True, allow_nan=False))
    else:
        print(f"Sentinel package: {result['status']}")
        print(f"Version: {result['version'] or 'unknown'}")
        print(f"Skills: {result['skill_count']}")
        for error in result["errors"]:
            print(f"- {error}", file=sys.stderr)
        print("Host enablement and Roboflow authorization: unverified")
    return 0 if result["status"] == "passed" else 1


if __name__ == "__main__":
    raise SystemExit(main())
