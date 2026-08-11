#!/usr/bin/env python3
"""Assert the versioned release-candidate assets and public claim boundaries."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[2]


def require(condition: bool, message: str) -> None:
    """Raise an assertion with the release-surface condition that failed."""
    if not condition:
        raise AssertionError(message)


def read_text(root: Path, relative: str) -> str:
    """Read one UTF-8 release surface file below ``root``."""
    return (root / relative).read_text(encoding="utf-8")


def assert_release_surface(root: Path) -> None:
    """Require release assets, v0.4 metadata, and consistent install wording."""
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
        require(asset.read_bytes().startswith(b"\x89PNG\r\n\x1a\n"), f"{field} is not PNG")

    require(manifest.get("version") == "0.4.0", "Codex manifest is not v0.4.0")
    changelog = read_text(root, "CHANGELOG.md")
    require(
        "## 0.4.0 (unreleased)" in changelog,
        "changelog lacks the unreleased v0.4.0 section",
    )
    require(
        "### Breaking changes and migration" in changelog,
        "changelog lacks the v0.4 proof-contract migration",
    )
    public_install_claim = "manual public-github marketplace installation"
    require(
        public_install_claim in changelog.lower(),
        "changelog lacks manual public-install verification",
    )
    require(
        "v0.3 evidence" in changelog,
        "changelog does not scope public-install evidence to v0.3",
    )
    for relative in (
        "README.md",
        "docs/index.md",
        "docs/quickstart.md",
        "docs/llms.txt",
        "docs/llms-full.txt",
    ):
        text = read_text(root, relative)
        require("v0.4 release candidate" in text, f"{relative} lacks v0.4 wording")
        require("v0.3" in text, f"{relative} lacks public-install provenance")
        require(
            public_install_claim in text.lower(),
            f"{relative} lacks manual public-install verification",
        )
        require(
            "v0.4 public-install path remains unverified" in text,
            f"{relative} does not disclose missing v0.4 public-install evidence",
        )

    makefile = read_text(root, "Makefile")
    expected_quality_hooks = {
        "lint": "pre-commit run ruff --all-files",
        "format": "pre-commit run ruff-format --all-files",
        "lint-js": "pre-commit run eslint --all-files",
        "typecheck": "pre-commit run mypy --all-files",
    }
    for target, command in expected_quality_hooks.items():
        require(
            f"{target}:\n\t{command}" in makefile,
            f"Makefile {target} does not use the {command.split()[2]} hook",
        )

    pre_commit = yaml.safe_load(read_text(root, ".pre-commit-config.yaml"))
    mypy_hooks = [
        hook
        for repository in pre_commit["repos"]
        if repository["repo"] == "https://github.com/pre-commit/mirrors-mypy"
        for hook in repository["hooks"]
        if hook["id"] == "mypy"
    ]
    require(len(mypy_hooks) == 1, "pre-commit must define exactly one mypy hook")
    require(
        "requests==2.34.2" in mypy_hooks[0].get("additional_dependencies", []),
        "pre-commit mypy must install the CI-pinned requests dependency",
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
