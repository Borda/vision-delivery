#!/usr/bin/env python3
"""Assert that both plugin hosts expose one consistent installable package."""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
MCP_URL = "https://mcp.roboflow.com/mcp"


def canonical_version() -> str:
    """Read the release version from the canonical Claude manifest.

    Examples:
        >>> isinstance(canonical_version(), str)
        True
    """
    version = read_object(".claude-plugin/plugin.json").get("version")
    if not isinstance(version, str) or not re.fullmatch(r"\d+\.\d+\.\d+", version):
        raise DistributionError(".claude-plugin/plugin.json version must be semver")
    return version


class DistributionError(RuntimeError):
    """Report an invalid cross-host distribution contract."""


def read_object(relative_path: str) -> dict[str, Any]:
    """Read a required JSON object relative to the plugin root."""
    path = ROOT / relative_path
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise DistributionError(f"could not read {relative_path}: {exc}") from exc
    if not isinstance(payload, dict):
        raise DistributionError(f"{relative_path} must contain a JSON object")
    return payload


def require(condition: bool, message: str) -> None:
    """Raise a distribution error when a package invariant is false."""
    if not condition:
        raise DistributionError(message)


def validate_distribution() -> None:
    """Validate synchronized manifests, marketplaces, and OAuth-only MCP config."""
    version = canonical_version()
    codex = read_object(".codex-plugin/plugin.json")
    claude = read_object(".claude-plugin/plugin.json")
    codex_marketplace = read_object(".agents/plugins/marketplace.json")
    claude_marketplace = read_object(".claude-plugin/marketplace.json")
    mcp = read_object(".mcp.json")
    hooks = read_object("hooks/hooks.json")

    for host, manifest in (("Codex", codex), ("Claude", claude)):
        require(
            manifest.get("name") == "sentinel", f"{host} plugin name must be sentinel"
        )
        require(manifest.get("version") == version, f"{host} version must be {version}")
        require(manifest.get("skills") == "./skills/", f"{host} skills path drifted")
        require(manifest.get("mcpServers") == "./.mcp.json", f"{host} MCP path drifted")

    require("hooks" not in codex, "Codex manifest must omit unsupported hooks")
    require(
        "hooks" not in claude, "Claude standard hooks must rely on automatic discovery"
    )
    require(
        (ROOT / "hooks" / "hooks.json").is_file(), "Claude hook manifest is missing"
    )
    require(
        "PostToolUseFailure" in hooks.get("hooks", {}), "Claude failure hook is missing"
    )

    claude_entries = claude_marketplace.get("plugins")
    require(
        claude_marketplace.get("name") == "sentinel",
        "Claude marketplace must be sentinel",
    )
    if not isinstance(claude_entries, list) or len(claude_entries) != 1:
        raise DistributionError("Claude marketplace must contain one plugin")
    claude_entry = claude_entries[0]
    require(
        isinstance(claude_entry, dict), "Claude marketplace entry must be an object"
    )
    require(
        claude_entry.get("name") == "sentinel",
        "Claude selector must be sentinel@sentinel",
    )
    require(claude_entry.get("source") == "./", "Claude marketplace source must be ./")
    require(
        claude_entry.get("version") == version, "Claude marketplace version drifted"
    )

    codex_entries = codex_marketplace.get("plugins")
    if not isinstance(codex_entries, list) or len(codex_entries) != 1:
        raise DistributionError("Codex marketplace must contain one plugin")
    codex_entry = codex_entries[0]
    require(isinstance(codex_entry, dict), "Codex marketplace entry must be an object")
    require(
        codex_entry.get("name") == "sentinel",
        "Codex selector must be sentinel@sentinel",
    )
    require(
        codex_entry.get("source") == {"source": "local", "path": "."},
        "Codex marketplace source drifted",
    )

    servers = mcp.get("mcpServers")
    if not isinstance(servers, dict):
        raise DistributionError("MCP manifest must contain mcpServers")
    roboflow = servers.get("roboflow")
    require(isinstance(roboflow, dict), "Roboflow MCP server is missing")
    require(
        roboflow == {"type": "http", "url": MCP_URL},
        "Roboflow MCP must use URL-only OAuth discovery",
    )

    front_door = ROOT / "skills" / "solve-cv-task" / "SKILL.md"
    require(front_door.is_file(), "front-door skill is missing")
    doctor = ROOT / "skills" / "check-sentinel-setup" / "SKILL.md"
    require(doctor.is_file(), "setup doctor skill is missing")

    resource_references = 0
    for skill_path in sorted((ROOT / "skills").glob("*/SKILL.md")):
        skill_text = skill_path.read_text(encoding="utf-8")
        bare_references = []
        for match in re.finditer(r"resources/[A-Za-z0-9_./-]+", skill_text):
            prefix = skill_text[max(0, match.start() - 20) : match.start()]
            if prefix.endswith("../../") or prefix.endswith("<plugin-root>/"):
                continue
            bare_references.append(match.group(0))
        require(
            not bare_references,
            f"{skill_path.parent.name} has plugin-root-relative resources: {', '.join(bare_references)}",
        )
        for relative_path in re.findall(
            r"\.\./\.\./resources/[A-Za-z0-9_./-]+", skill_text
        ):
            resource_references += 1
            target = (skill_path.parent / relative_path).resolve()
            require(
                target.is_relative_to(ROOT),
                f"resource escapes plugin root: {relative_path}",
            )
            require(
                target.is_file(),
                f"missing resource from {skill_path.parent.name}: {relative_path}",
            )
    require(resource_references > 0, "skills must reference packaged root resources")


def main() -> int:
    """Run the distribution assertions and return a shell-friendly status."""
    try:
        validate_distribution()
    except DistributionError as exc:
        print(f"distribution assertion failed: {exc}", file=sys.stderr)
        return 1
    print(
        "distribution assertions passed: sentinel@sentinel, version 0.2.0, URL-only Roboflow MCP"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
