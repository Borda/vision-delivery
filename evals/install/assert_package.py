#!/usr/bin/env python3
"""Assert deterministic Sentinel package construction and validator rejection paths."""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import sys
import tempfile
from collections.abc import Callable
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SCRIPTS = ROOT / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

import build_package  # noqa: E402
import validate_package  # noqa: E402


def update_inventory_hash(candidate: Path, relative: str) -> None:
    """Update one test-mutated file's inventory hash without hiding other checks."""
    manifest_path = candidate / "package-manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    for record in manifest["files"]:
        if record["path"] == relative:
            record["sha256"] = hashlib.sha256(
                (candidate / relative).read_bytes()
            ).hexdigest()
            break
    else:
        raise AssertionError(f"inventory does not contain {relative}")
    manifest_path.write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")


def assert_rejected(
    original: Path, name: str, mutate: Callable[[Path], None], expected: str
) -> None:
    """Copy a valid candidate, apply one mutation, and require a named finding."""
    with tempfile.TemporaryDirectory(prefix=f"sentinel-package-{name}-") as temporary:
        candidate = Path(temporary) / "candidate"
        shutil.copytree(original, candidate)
        mutate(candidate)
        findings = validate_package.validate_package(candidate)
    if not any(expected in finding for finding in findings):
        raise AssertionError(f"{name} was not rejected as {expected!r}: {findings}")


def change_manifest_pointer(candidate: Path) -> None:
    """Point Codex at the retired root while preserving inventory integrity."""
    manifest_path = candidate / ".codex-plugin" / "plugin.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["skills"] = "./skills/"
    manifest_path.write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    update_inventory_hash(candidate, ".codex-plugin/plugin.json")


def add_personal_path(candidate: Path) -> None:
    """Embed the local home path while preserving README inventory integrity."""
    readme = candidate / "README.md"
    readme.write_text(
        readme.read_text(encoding="utf-8") + f"\n{Path.home()}\n", encoding="utf-8"
    )
    update_inventory_hash(candidate, "README.md")


def add_secret_like_text(candidate: Path) -> None:
    """Embed a synthetic AWS-shaped token without changing any manifest semantics."""
    readme = candidate / "README.md"
    readme.write_text(
        readme.read_text(encoding="utf-8") + "\nAKIA0123456789ABCDEF\n",
        encoding="utf-8",
    )
    update_inventory_hash(candidate, "README.md")


def add_path_escape(candidate: Path) -> None:
    """Replace one inventory path with an escaping path for validator coverage."""
    manifest_path = candidate / "package-manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["files"][0]["path"] = "../escape"
    manifest_path.write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")


def add_roster_mismatch(candidate: Path) -> None:
    """Alter declared Codex roster so it no longer matches candidate contents."""
    manifest_path = candidate / "package-manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["skills"]["codex"] = ["solve-cv-task"]
    manifest_path.write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")


def add_symlink(candidate: Path) -> None:
    """Add a symlink only on platforms where symlink creation is supported."""
    os.symlink(candidate / "README.md", candidate / "duplicate-readme")


def add_extra_file(candidate: Path) -> None:
    """Add an untracked candidate file to exercise inventory closure."""
    (candidate / "extra.txt").write_text("unexpected\n", encoding="utf-8")


def remove_front_door_skill(candidate: Path) -> None:
    """Remove one required Codex skill to exercise package inventory closure."""
    (candidate / "codex-skills" / "solve-cv-task" / "SKILL.md").unlink()


def main() -> int:
    """Build a candidate, assert deterministic rebuilds, and exercise rejection rules."""
    with tempfile.TemporaryDirectory(prefix="sentinel-package-test-") as temporary:
        candidate = Path(temporary) / "candidate"
        build_package.build_package(ROOT, candidate)
        findings = validate_package.validate_package(candidate)
        if findings:
            raise AssertionError(f"valid candidate failed validation: {findings}")
        differences = build_package.check_determinism(ROOT, candidate)
        if differences:
            raise AssertionError(f"candidate rebuild drifted: {differences}")

        assert_rejected(
            candidate,
            "extra-file",
            add_extra_file,
            "extra unmanifested",
        )
        assert_rejected(
            candidate,
            "missing-skill",
            remove_front_door_skill,
            "missing payload file",
        )
        assert_rejected(
            candidate, "manifest-pointer", change_manifest_pointer, "does not point"
        )
        assert_rejected(
            candidate, "roster-mismatch", add_roster_mismatch, "roster does not match"
        )
        assert_rejected(
            candidate, "path-escape", add_path_escape, "unsafe manifest path"
        )
        assert_rejected(
            candidate, "personal-path", add_personal_path, "personal-path leak"
        )
        assert_rejected(
            candidate, "secret", add_secret_like_text, "secret-like material"
        )
        if os.name == "posix":
            assert_rejected(candidate, "symlink", add_symlink, "symlink in package")

    print("Sentinel deterministic package assertions passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
