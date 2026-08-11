#!/usr/bin/env python3
"""Install and remove a Sentinel candidate through a disposable Claude config."""

from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import tempfile
from pathlib import Path
from typing import Any

MARKETPLACE = "sentinel-phase4-claude"
PLUGIN = "sentinel"
EXPECTED_SKILLS = 13


def run_command(command: list[str], config_dir: Path) -> subprocess.CompletedProcess[str]:
    """Run one Claude CLI command isolated from the user's configured data."""
    environment = {**os.environ, "CLAUDE_CONFIG_DIR": str(config_dir)}
    return subprocess.run(
        command,
        capture_output=True,
        check=False,
        env=environment,
        text=True,
        timeout=120,
    )


def claude_marketplace() -> dict[str, Any]:
    """Return the one-entry Claude marketplace contract for the copied candidate."""
    return {
        "name": MARKETPLACE,
        "owner": {"name": "Sentinel Phase 4 probe"},
        "plugins": [
            {
                "name": PLUGIN,
                "description": "Disposable Sentinel candidate",
                "source": "./plugins/sentinel",
            }
        ],
    }


def installed_path(config_dir: Path) -> Path | None:
    """Return the one installed Sentinel version under the disposable cache."""
    base = config_dir / "plugins" / "cache" / MARKETPLACE / PLUGIN
    versions = sorted(path for path in base.iterdir() if path.is_dir()) if base.is_dir() else []
    return versions[0] if len(versions) == 1 else None


def verify_install(path: Path | None) -> dict[str, Any]:
    """Verify the installed Claude manifest and skill roster without model execution."""
    if path is None:
        return {"ok": False, "issues": ["installed candidate path was not found"]}
    manifest_path = path / ".claude-plugin" / "plugin.json"
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        return {"ok": False, "issues": [f"installed manifest is unreadable: {exc}"]}
    roster = (
        sorted(child.name for child in (path / "claude-skills").iterdir() if (child / "SKILL.md").is_file())
        if (path / "claude-skills").is_dir()
        else []
    )
    checks = {
        "name": manifest.get("name") == PLUGIN,
        "skills_path": manifest.get("skills") == "./claude-skills/",
        "skill_count": len(roster) == EXPECTED_SKILLS,
        "no_default_skills": not (path / "skills").exists(),
    }
    return {"ok": all(checks.values()), "checks": checks, "roster": roster}


def probe(candidate: Path) -> dict[str, Any]:
    """Build a temporary marketplace, install, inspect, remove, and discard it."""
    if not (candidate / "package-manifest.json").is_file():
        return {"probe": "claude", "status": "invalid-candidate"}
    with tempfile.TemporaryDirectory(prefix="sentinel-claude-probe-") as temporary:
        workspace = Path(temporary)
        config_dir = workspace / "claude-config"
        marketplace_root = workspace / "marketplace"
        installed_candidate = marketplace_root / "plugins" / PLUGIN
        config_dir.mkdir()
        shutil.copytree(candidate, installed_candidate)
        manifest_path = marketplace_root / ".claude-plugin" / "marketplace.json"
        manifest_path.parent.mkdir(parents=True)
        manifest_path.write_text(json.dumps(claude_marketplace(), indent=2) + "\n")

        add_marketplace = run_command(
            [
                "claude",
                "plugin",
                "marketplace",
                "add",
                str(marketplace_root),
                "--scope",
                "user",
            ],
            config_dir,
        )
        if add_marketplace.returncode:
            return {
                "probe": "claude",
                "status": "marketplace-add-failed",
                "detail": add_marketplace.stderr.strip(),
            }
        available = run_command(["claude", "plugin", "list", "--available", "--json"], config_dir)
        if available.returncode or f'"name":"{PLUGIN}"' not in available.stdout.replace(" ", ""):
            return {
                "probe": "claude",
                "status": "marketplace-list-failed",
                "detail": available.stderr.strip() or available.stdout.strip(),
            }
        install = run_command(
            [
                "claude",
                "plugin",
                "install",
                f"{PLUGIN}@{MARKETPLACE}",
                "--scope",
                "user",
            ],
            config_dir,
        )
        if install.returncode:
            return {
                "probe": "claude",
                "status": "plugin-install-failed",
                "detail": install.stderr.strip(),
            }
        verification = verify_install(installed_path(config_dir))
        remove = run_command(
            [
                "claude",
                "plugin",
                "uninstall",
                f"{PLUGIN}@{MARKETPLACE}",
                "--scope",
                "user",
                "--yes",
            ],
            config_dir,
        )
        return {
            "probe": "claude",
            "status": "ok" if verification["ok"] and not remove.returncode else "verification-failed",
            "verification": verification,
            "remove_returncode": remove.returncode,
            "remove_detail": remove.stderr.strip(),
        }


def main(argv: list[str] | None = None) -> int:
    """Run the disposable Claude probe and emit a portable JSON result."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--candidate", required=True, type=Path)
    parser.add_argument("--report", type=Path)
    args = parser.parse_args(argv)
    try:
        result = probe(args.candidate.resolve())
    except (OSError, subprocess.SubprocessError) as exc:
        result = {"probe": "claude", "status": "probe-error", "detail": str(exc)}
    encoded = json.dumps(result, indent=2)
    print(encoded)
    if args.report:
        args.report.write_text(encoded + "\n", encoding="utf-8")
    return 0 if result["status"] == "ok" else 1


if __name__ == "__main__":
    raise SystemExit(main())
