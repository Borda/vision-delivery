#!/usr/bin/env python3
"""Verify that every Sentinel release-version declaration agrees."""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path
from typing import Any

JSON_SOURCES: dict[str, tuple[str, ...]] = {
    "package.json": ("version",),
    "package-lock.json": ("version",),
    "package-lock.json packages root": ("packages", "", "version"),
    ".codex-plugin/plugin.json": ("version",),
    ".claude-plugin/plugin.json": ("version",),
    ".claude-plugin/marketplace.json": ("plugins", "0", "version"),
}
TEXT_SOURCES: dict[str, str] = {
    "CITATION.cff": r"^version:\s*(?P<version>\d+\.\d+\.\d+)\s*$",
    "CHANGELOG.md": r"^## (?P<version>\d+\.\d+\.\d+)(?: \(unreleased\))?\s*$",
    "scripts/ledger_append.py": r'^VERSION = "(?P<version>\d+\.\d+\.\d+)"$',
    "hooks/cta.js": r'^\s*version: "(?P<version>\d+\.\d+\.\d+)",$',
    "resources/ledger-protocol.md": r'^  "version": "(?P<version>\d+\.\d+\.\d+)",$',
    "skills/decision-report/SKILL.md": r'^  "version": "(?P<version>\d+\.\d+\.\d+)",$',
    "evals/install/assert_distribution.py": r"version (?P<version>\d+\.\d+\.\d+), URL-only",
}


class VersionCheckError(ValueError):
    """Describe an unreadable or malformed release-version declaration."""


def json_version(root: Path, source: str, path: tuple[str, ...]) -> str:
    """Read a release version from one JSON path."""
    file_path = root / source.split(" packages root")[0]
    payload: Any = json.loads(file_path.read_text(encoding="utf-8"))
    for part in path:
        if isinstance(payload, list):
            payload = payload[int(part)]
        else:
            payload = payload[part]
    if not isinstance(payload, str):
        raise VersionCheckError(f"{source} does not contain a string version")
    return payload


def text_version(root: Path, source: str, pattern: str) -> str:
    """Extract one release version, allowing historical changelog sections."""
    matches = re.findall(
        pattern, (root / source).read_text(encoding="utf-8"), re.MULTILINE
    )
    if not matches or (source != "CHANGELOG.md" and len(matches) != 1):
        raise VersionCheckError(f"{source} must contain exactly one release version")
    return matches[0]


def declared_versions(root: Path) -> dict[str, str]:
    """Collect all tracked Sentinel release-version declarations."""
    versions = {
        source: json_version(root, source, path)
        for source, path in JSON_SOURCES.items()
    }
    versions.update(
        {
            source: text_version(root, source, pattern)
            for source, pattern in TEXT_SOURCES.items()
        }
    )
    return versions


def main() -> int:
    """Compare release declarations and return a shell-friendly status."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--root", type=Path, default=Path(__file__).resolve().parents[1]
    )
    parser.add_argument(
        "--expected",
        help="Require this version in addition to internal consistency.",
    )
    args = parser.parse_args()

    try:
        versions = declared_versions(args.root.resolve())
    except (OSError, ValueError, KeyError, IndexError, json.JSONDecodeError) as exc:
        print(f"version check failed: {exc}", file=sys.stderr)
        return 1

    expected = args.expected or versions["package.json"]
    mismatches = {
        source: version for source, version in versions.items() if version != expected
    }
    if mismatches:
        print(f"version check failed: expected {expected}", file=sys.stderr)
        for source, version in sorted(mismatches.items()):
            print(f"- {source}: {version}", file=sys.stderr)
        return 1

    print(f"version check passed: {expected} across {len(versions)} declarations")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
