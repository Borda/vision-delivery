#!/usr/bin/env python3
"""Assert the versioned release-candidate assets and public claim boundaries."""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[2]
#: Short form of the pitch for fields with a small length budget.
SHORT_PITCH = "A measured first answer with no Roboflow account, then an independent acceptance check."


def require(condition: bool, message: str) -> None:
    """Raise an assertion with the release-surface condition that failed."""
    if not condition:
        raise AssertionError(message)


def read_text(root: Path, relative: str) -> str:
    """Read one UTF-8 release surface file below ``root``."""
    return (root / relative).read_text(encoding="utf-8")


def assert_one_pitch(root: Path) -> None:
    """Require the same pitch sentence, word for word, on every public surface.

    The Claude Code manifest description is the reference. Four different pitches once
    described this project; a surface that drifts from the reference fails here.
    """
    pitch = json.loads(read_text(root, ".claude-plugin/plugin.json")).get("description", "")
    require(pitch.endswith(".") and 100 <= len(pitch) <= 240, "pitch must be one sentence of 100 to 240 characters")
    require(
        "no Roboflow account" in pitch and "Claude Code" in pitch,
        "pitch must name the start with no Roboflow account and the host that has the gate",
    )

    marketplace = json.loads(read_text(root, ".claude-plugin/marketplace.json"))
    require(marketplace.get("description") == pitch, "Claude marketplace description differs from the pitch")
    require(
        [entry.get("description") for entry in marketplace.get("plugins", [])] == [pitch],
        "Claude marketplace plugin description differs from the pitch",
    )
    codex = json.loads(read_text(root, ".codex-plugin/plugin.json"))
    require(codex.get("description") == pitch, "Codex manifest description differs from the pitch")
    # The Codex plugin browser shows the interface copy: the long text opens with the pitch and
    # says Codex has no gate; the short text is the pitch's declared short form.
    interface = codex.get("interface", {})
    long_text = interface.get("longDescription", "")
    require(long_text.startswith(f"{pitch} "), "Codex long description does not open with the pitch")
    require("Codex has no spend gate" in long_text, "Codex long description does not say Codex has no gate")
    require(interface.get("shortDescription") == SHORT_PITCH, "Codex short description differs from the short pitch")
    site = yaml.safe_load(read_text(root, "mkdocs.yml"))
    require(site.get("site_description") == pitch, "docs site description differs from the pitch")

    home = read_text(root, "docs/index.md")
    require(home.splitlines()[1] == f"description: {pitch}", "docs home description differs from the pitch")
    require(re.findall(r"<h2>(.*?)</h2>", home) == [pitch], "docs home headline differs from the pitch")
    # The first line of prose in the README, after the title, badges, and banner, is the pitch alone.
    readme_prose = [
        line
        for line in read_text(root, "README.md").splitlines()
        if line.strip() and not line.startswith(("#", "[![", "!["))
    ]
    require(readme_prose[0] == f"**{pitch}**", "README does not lead with the pitch")
    # The summary line of each agent-facing file is, or opens with, the pitch and nothing before it.
    summaries = [line for line in read_text(root, "docs/llms.txt").splitlines() if line.startswith("> ")]
    require(summaries == [f"> {pitch}"], "docs/llms.txt summary is not the pitch alone")
    full_prose = [
        line for line in read_text(root, "docs/llms-full.txt").splitlines() if line.strip() and not line.startswith("#")
    ]
    require(full_prose[0].startswith(f"{pitch} "), "docs/llms-full.txt does not open with the pitch")
    for relative in ("CITATION.cff", "docs/llms-full.txt", "docs/llms.txt", "README.md", "docs/index.md"):
        require("business-first" not in read_text(root, relative).lower(), f"{relative} still carries the old pitch")


def assert_release_surface(root: Path) -> None:
    """Require release assets, v0.5 metadata, and consistent install wording."""
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

    require(manifest.get("version") == "0.5.0", "Codex manifest is not v0.5.0")
    changelog = read_text(root, "CHANGELOG.md")
    require(
        "## 0.5.0 (unreleased)" in changelog,
        "changelog lacks the unreleased v0.5.0 section",
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
        require("v0.5 release candidate" in text, f"{relative} lacks v0.5 wording")
        require("v0.3" in text, f"{relative} lacks public-install provenance")
        require(
            public_install_claim in text.lower(),
            f"{relative} lacks manual public-install verification",
        )
        require(
            "v0.5 public-install path remains unverified" in text,
            f"{relative} does not disclose missing v0.5 public-install evidence",
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
        assert_one_pitch(args.root.resolve())
    except (AssertionError, OSError, KeyError, json.JSONDecodeError) as exc:
        print(f"release surface assertion failed: {exc}", file=sys.stderr)
        return 1
    print("release surface assertions passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
