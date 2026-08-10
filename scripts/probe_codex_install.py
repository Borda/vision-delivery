#!/usr/bin/env python3
"""Install and remove a Sentinel candidate through a disposable Codex home."""

from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import tempfile
from pathlib import Path
from typing import Any

MARKETPLACE = "sentinel-phase4-codex"
PLUGIN = "sentinel"
EXPECTED_SKILLS = 13


def run_command(command: list[str], home: Path) -> subprocess.CompletedProcess[str]:
    """Run one Codex CLI command isolated from the user's configured home."""
    environment = {**os.environ, "CODEX_HOME": str(home)}
    return subprocess.run(
        command,
        capture_output=True,
        check=False,
        env=environment,
        text=True,
        timeout=120,
    )


def codex_marketplace() -> dict[str, Any]:
    """Return the one-entry local marketplace contract for the copied candidate."""
    return {
        "name": MARKETPLACE,
        "interface": {"displayName": "Sentinel Phase 4 probe"},
        "plugins": [
            {
                "name": PLUGIN,
                "source": {"source": "local", "path": "./plugins/sentinel"},
                "policy": {"installation": "AVAILABLE", "authentication": "ON_USE"},
                "category": "Developer Tools",
            }
        ],
    }


def installed_path(payload: str, home: Path) -> Path | None:
    """Resolve Codex's installed path from JSON output or its disposable cache."""
    try:
        result = json.loads(payload)
    except json.JSONDecodeError:
        result = {}
    if isinstance(result, dict) and isinstance(result.get("installedPath"), str):
        return Path(result["installedPath"])

    candidates = [
        path.parent
        for path in home.rglob("plugin.json")
        if path.parent.name == ".codex-plugin"
        and path.read_text(encoding="utf-8").find(f'"name": "{PLUGIN}"') >= 0
    ]
    return candidates[0] if len(candidates) == 1 else None


def verify_install(path: Path | None) -> dict[str, Any]:
    """Verify the installed manifest and Codex skill roster without model execution."""
    if path is None:
        return {"ok": False, "issues": ["installed candidate path was not found"]}
    manifest_path = path / ".codex-plugin" / "plugin.json"
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        return {"ok": False, "issues": [f"installed manifest is unreadable: {exc}"]}
    roster = (
        sorted(
            child.name
            for child in (path / "codex-skills").iterdir()
            if (child / "SKILL.md").is_file()
        )
        if (path / "codex-skills").is_dir()
        else []
    )
    checks = {
        "name": manifest.get("name") == PLUGIN,
        "skills_path": manifest.get("skills") == "./codex-skills/",
        "skill_count": len(roster) == EXPECTED_SKILLS,
        "no_default_skills": not (path / "skills").exists(),
    }
    return {"ok": all(checks.values()), "checks": checks, "roster": roster}


def probe(candidate: Path) -> dict[str, Any]:
    """Build a temporary marketplace, install, inspect, remove, and discard it."""
    if not (candidate / "package-manifest.json").is_file():
        return {"probe": "codex", "status": "invalid-candidate"}
    with tempfile.TemporaryDirectory(prefix="sentinel-codex-probe-") as temporary:
        workspace = Path(temporary)
        home = workspace / "codex-home"
        marketplace_root = workspace / "marketplace"
        installed_candidate = marketplace_root / "plugins" / PLUGIN
        home.mkdir()
        shutil.copytree(candidate, installed_candidate)
        manifest_path = marketplace_root / ".agents" / "plugins" / "marketplace.json"
        manifest_path.parent.mkdir(parents=True)
        manifest_path.write_text(json.dumps(codex_marketplace(), indent=2) + "\n")

        add_marketplace = run_command(
            ["codex", "plugin", "marketplace", "add", str(marketplace_root), "--json"],
            home,
        )
        if add_marketplace.returncode:
            return {
                "probe": "codex",
                "status": "marketplace-add-failed",
                "detail": add_marketplace.stderr.strip(),
            }
        available = run_command(
            [
                "codex",
                "plugin",
                "list",
                "--marketplace",
                MARKETPLACE,
                "--available",
                "--json",
            ],
            home,
        )
        if available.returncode or f'"name":"{PLUGIN}"' not in available.stdout.replace(
            " ", ""
        ):
            return {
                "probe": "codex",
                "status": "marketplace-list-failed",
                "detail": available.stderr.strip() or available.stdout.strip(),
            }
        install = run_command(
            ["codex", "plugin", "add", f"{PLUGIN}@{MARKETPLACE}", "--json"], home
        )
        if install.returncode:
            return {
                "probe": "codex",
                "status": "plugin-add-failed",
                "detail": install.stderr.strip(),
            }
        verification = verify_install(installed_path(install.stdout, home))
        remove = run_command(
            ["codex", "plugin", "remove", f"{PLUGIN}@{MARKETPLACE}", "--json"], home
        )
        return {
            "probe": "codex",
            "status": "ok"
            if verification["ok"] and not remove.returncode
            else "verification-failed",
            "verification": verification,
            "remove_returncode": remove.returncode,
            "remove_detail": remove.stderr.strip(),
        }


def main(argv: list[str] | None = None) -> int:
    """Run the disposable Codex probe and emit a portable JSON result."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--candidate", required=True, type=Path)
    parser.add_argument("--report", type=Path)
    args = parser.parse_args(argv)
    try:
        result = probe(args.candidate.resolve())
    except (OSError, subprocess.SubprocessError) as exc:
        result = {"probe": "codex", "status": "probe-error", "detail": str(exc)}
    encoded = json.dumps(result, indent=2)
    print(encoded)
    if args.report:
        args.report.write_text(encoded + "\n", encoding="utf-8")
    return 0 if result["status"] == "ok" else 1


if __name__ == "__main__":
    raise SystemExit(main())
