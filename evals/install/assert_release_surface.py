#!/usr/bin/env python3
"""Assert the versioned release-candidate assets and public claim boundaries."""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path
from typing import Any

import yaml

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT / "scripts") not in sys.path:
    sys.path.insert(0, str(ROOT / "scripts"))

from skill_roster import ROSTER_RELATIVE, SURFACE_FILES, Roster, RosterError, Surface, load_roster  # noqa: E402

#: The issue form's route option for a user who does not know which route ran.
NOT_SURE = "not sure"
#: A backticked skill-shaped name: lowercase words joined by single hyphens.
BACKTICKED_NAME = re.compile(r"`([a-z][a-z0-9]*(?:-[a-z0-9]+)*)`")
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


def _section(text: str, heading_word: str) -> str | None:
    """Return the lines under the first ``## `` heading that contains ``heading_word``."""
    lines = text.splitlines()
    start = next(
        (index for index, line in enumerate(lines) if line.startswith("## ") and heading_word in line),
        None,
    )
    if start is None:
        return None
    end = next((index for index in range(start + 1, len(lines)) if lines[index].startswith("## ")), len(lines))
    return "\n".join(lines[start + 1 : end])


def _table(block: str) -> list[dict[str, str]]:
    """Parse the first Markdown table in a block into rows keyed by header text."""
    rows = [line.strip().strip("|") for line in block.splitlines() if line.strip().startswith("|")]
    if len(rows) < 2:
        return []
    header = [cell.strip() for cell in rows[0].split("|")]
    return [dict(zip(header, (cell.strip() for cell in row.split("|")), strict=False)) for row in rows[2:]]


def _names(cell: str) -> list[str]:
    """Return the skill-shaped backticked names in one table cell or bullet."""
    return BACKTICKED_NAME.findall(cell)


def listing_rows(root: Path) -> dict[Surface, list[tuple[str, list[str], str]]]:
    """Read every human-facing roster listing as rows of (label, names, extra text).

    The label is the README Status cell; the extra text is the scorer cell for tables and the
    bullet text for docs/llms.txt. A listing that cannot be found yields no rows.
    """
    readme = _section(read_text(root, SURFACE_FILES[Surface.README]), "Routes") or ""
    use_cases = _section(read_text(root, SURFACE_FILES[Surface.USE_CASES]), "Route matrix") or ""
    contract = _section(read_text(root, SURFACE_FILES[Surface.CAPABILITY_CONTRACT]), "Skill roster") or ""
    llms = _section(read_text(root, SURFACE_FILES[Surface.LLMS]), "Canonical routes") or ""
    form = yaml.safe_load(read_text(root, SURFACE_FILES[Surface.ISSUE_FORM]))
    route_field: dict[str, Any] = next((item for item in form.get("body", []) if item.get("id") == "route"), {})
    options = route_field.get("attributes", {}).get("options", [])
    return {
        Surface.README: [
            (row.get("Status", "").strip("* ").lower(), _names(row.get("Route", "")), row.get("Sentinel scorer", ""))
            for row in _table(readme)
        ],
        Surface.USE_CASES: [
            ("", _names(row.get("Route", "")), row.get("Sentinel scorer", "")) for row in _table(use_cases)
        ],
        Surface.CAPABILITY_CONTRACT: [
            ("", _names(line), "") for line in contract.splitlines() if line.startswith("- ")
        ],
        Surface.LLMS: [
            ("", _names(line.split(":", 1)[0]), line.split(":", 1)[1].strip() if ":" in line else "")
            for line in llms.splitlines()
            if line.startswith("- `")
        ],
        Surface.ISSUE_FORM: [("", [option], "") for option in options if option != NOT_SURE],
    }


def _row_problems(surface: Surface, rows: list[tuple[str, list[str], str]], roster: Roster) -> list[str]:
    """Check what a listing says about each skill beyond its name: kind, scorer, and use text."""
    problems: list[str] = []
    where = SURFACE_FILES[surface]
    for label, names, extra in rows:
        for entry in filter(None, (roster.entry(name) for name in names)):
            if surface == Surface.README and label != entry.kind.value:
                problems.append(
                    f"{where}: {entry.name} is in the {label!r} row but the roster kind is {entry.kind.value}"
                )
            if surface in (Surface.README, Surface.USE_CASES):
                says_yes = extra.lower().startswith("yes")
                if says_yes != (entry.scorer is not None):
                    problems.append(f"{where}: scorer cell for {entry.name} disagrees with the roster")
                if surface == Surface.README and entry.scorer and f"--task {entry.scorer.value}" not in extra:
                    problems.append(f"{where}: scorer cell for {entry.name} does not name --task {entry.scorer.value}")
            if surface == Surface.LLMS and extra != f"{entry.use}.":
                problems.append(f"{where}: {entry.name} text {extra!r} differs from the roster use {entry.use!r}")
    return problems


def roster_listing_problems(root: Path, roster: Roster) -> list[str]:
    """Return every disagreement between the human-facing listings and the roster source.

    A name the roster puts on a listing but the listing lacks is missing; a name the listing shows
    but the roster does not put there (or does not know) is stale.
    """
    problems: list[str] = []
    for surface, rows in listing_rows(root).items():
        where = SURFACE_FILES[surface]
        listed = [name for _, names, _ in rows for name in names]
        if not listed:
            problems.append(f"{where}: no skill listing found")
        expected = roster.on_surface(surface)
        problems += [f"{where}: missing {name}" for name in sorted(expected - set(listed))]
        for name in sorted(set(listed) - expected):
            why = (
                "not in the roster" if roster.entry(name) is None else f"the roster does not list it on {surface.value}"
            )
            problems.append(f"{where}: stale {name} ({why})")
        problems += [f"{where}: {name} is listed twice" for name in sorted({n for n in listed if listed.count(n) > 1})]
        problems += _row_problems(surface, rows, roster)
    return problems


def assert_roster_listings(root: Path) -> None:
    """Require every human-facing skill listing to agree with ``shared/skill-roster.json``."""
    roster = load_roster(root / ROSTER_RELATIVE)
    problems = roster_listing_problems(root, roster)
    require(not problems, "skill listings disagree with the roster:\n  " + "\n  ".join(problems))
    form = yaml.safe_load(read_text(root, SURFACE_FILES[Surface.ISSUE_FORM]))
    options = next(item for item in form["body"] if item.get("id") == "route")["attributes"]["options"]
    require(NOT_SURE in options, "the outcome-report route dropdown lost its 'not sure' option")


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
        assert_roster_listings(args.root.resolve())
    except (AssertionError, OSError, KeyError, json.JSONDecodeError, RosterError, yaml.YAMLError) as exc:
        print(f"release surface assertion failed: {exc}", file=sys.stderr)
        return 1
    print("release surface assertions passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
