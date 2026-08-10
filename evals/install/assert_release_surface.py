#!/usr/bin/env python3
"""Assert the versioned release-candidate assets and public claim boundaries."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def require(condition: bool, message: str) -> None:
    """Raise an assertion with the release-surface condition that failed."""
    if not condition:
        raise AssertionError(message)


def read_text(root: Path, relative: str) -> str:
    """Read one UTF-8 release surface file below ``root``."""
    return (root / relative).read_text(encoding="utf-8")


def assert_release_surface(root: Path) -> None:
    """Require release assets, v0.3 metadata, and honest install wording."""
    manifest = json.loads(read_text(root, ".codex-plugin/plugin.json"))
    interface = manifest["interface"]
    expected_assets = {
        "composerIcon": "./assets/icon.png",
        "logo": "./assets/logo.png",
        "logoDark": "./assets/logo.png",
    }
    for field, relative in expected_assets.items():
        require(interface.get(field) == relative, f"missing {field} asset path")
        asset = root / relative.removeprefix("./")
        require(asset.is_file(), f"missing {field} asset: {relative}")
        require(
            asset.read_bytes().startswith(b"\x89PNG\r\n\x1a\n"), f"{field} is not PNG"
        )

    require(manifest.get("version") == "0.3.0", "Codex manifest is not v0.3.0")
    require(
        "## 0.3.0 (unreleased)" in read_text(root, "CHANGELOG.md"),
        "changelog lacks the unreleased v0.3.0 section",
    )
    for relative in ("README.md", "docs/index.md", "docs/quickstart.md"):
        text = read_text(root, relative)
        require("v0.3 release candidate" in text, f"{relative} lacks v0.3 wording")
        require(
            "public-GitHub path remains unverified" in text,
            f"{relative} overclaims public install",
        )


def main() -> int:
    """Run release-surface assertions against the working tree or a fixture root."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=ROOT)
    args = parser.parse_args()
    try:
        assert_release_surface(args.root.resolve())
    except (AssertionError, OSError, KeyError, json.JSONDecodeError) as exc:
        print(f"release surface assertion failed: {exc}", file=sys.stderr)
        return 1
    print("release surface assertions passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
