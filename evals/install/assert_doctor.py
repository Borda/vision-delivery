#!/usr/bin/env python3
"""Assert the Sentinel package doctor works from arbitrary directories."""

from __future__ import annotations

import json
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
DOCTOR = ROOT / "resources" / "scripts" / "sentinel_doctor.py"


def run_doctor(*args: str, cwd: str) -> subprocess.CompletedProcess[str]:
    """Run the doctor with captured output for one test case."""
    return subprocess.run(
        [sys.executable, str(DOCTOR), "--json", *args],
        cwd=cwd,
        text=True,
        capture_output=True,
        timeout=20,
        check=False,
    )


def copy_plugin_fixture(target: Path) -> None:
    """Copy the package surfaces required by the offline doctor."""
    for relative in (".codex-plugin", ".claude-plugin", "skills", "resources"):
        shutil.copytree(ROOT / relative, target / relative)
    shutil.copy2(ROOT / ".mcp.json", target / ".mcp.json")


def main() -> int:
    """Check healthy and broken package outcomes."""
    with tempfile.TemporaryDirectory() as cwd:
        healthy = run_doctor(cwd=cwd)
        if healthy.returncode != 0:
            raise AssertionError(f"healthy doctor failed: {healthy.stderr}")
        payload = json.loads(healthy.stdout)
        if payload.get("status") != "passed" or payload.get("skill_count", 0) < 2:
            raise AssertionError(f"unexpected healthy result: {payload}")
        if "authenticated Roboflow read succeeded" not in payload.get(
            "external_checks", []
        ):
            raise AssertionError("doctor blurred package health with external auth")

        cachebusted_root = Path(cwd) / "cachebusted-plugin"
        copy_plugin_fixture(cachebusted_root)
        codex_manifest = cachebusted_root / ".codex-plugin" / "plugin.json"
        codex_payload = json.loads(codex_manifest.read_text(encoding="utf-8"))
        release_version = codex_payload["version"].partition("+codex.")[0]
        codex_payload["version"] = f"{release_version}+codex.doctor-test"
        codex_manifest.write_text(json.dumps(codex_payload), encoding="utf-8")
        cachebusted = run_doctor("--plugin-root", str(cachebusted_root), cwd=cwd)
        if cachebusted.returncode != 0:
            raise AssertionError(f"cache-busted doctor failed: {cachebusted.stdout}")
        cachebusted_payload = json.loads(cachebusted.stdout)
        if cachebusted_payload.get("version") != release_version:
            raise AssertionError(
                f"doctor exposed a host-only cache-buster: {cachebusted_payload}"
            )

        claude_manifest = cachebusted_root / ".claude-plugin" / "plugin.json"
        claude_payload = json.loads(claude_manifest.read_text(encoding="utf-8"))
        claude_payload["version"] = "999.0.0"
        claude_manifest.write_text(json.dumps(claude_payload), encoding="utf-8")
        mismatched = run_doctor("--plugin-root", str(cachebusted_root), cwd=cwd)
        if mismatched.returncode == 0:
            raise AssertionError("doctor accepted a real host release mismatch")

        broken = run_doctor("--plugin-root", cwd, cwd=cwd)
        if broken.returncode == 0:
            raise AssertionError("doctor accepted an empty plugin root")
        broken_payload = json.loads(broken.stdout)
        if broken_payload.get("status") != "failed" or not broken_payload.get("errors"):
            raise AssertionError(f"unexpected broken result: {broken_payload}")

    print("Sentinel doctor assertions passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
