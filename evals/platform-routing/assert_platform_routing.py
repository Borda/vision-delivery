#!/usr/bin/env python3
"""Assert Roboflow platform lookups stay thin, source-backed, and match the upstream skill roster.

Set ``SENTINEL_UPSTREAM_SKILLS_DIR`` to the ``skills/`` directory of a ``roboflow/computer-vision-skills`` clone
to also compare the committed roster with the upstream skill names.
"""

from __future__ import annotations

import json
import os
import re
import sys
from collections.abc import Iterator, Mapping
from dataclasses import dataclass
from pathlib import Path

ROOT = Path(__file__).parent.parent.parent
CASES = Path(__file__).with_name("cases.json")
ROSTER = Path(__file__).with_name("upstream-skills.json")
LOOKUP = ROOT / "resources" / "roboflow-platform-lookup.md"
DOCS_SKILLS = ROOT / "docs" / "roboflow-skills.md"
SOLVERS = (
    ROOT / "codex-skills" / "solve-cv-task" / "SKILL.md",
    ROOT / "claude-skills" / "solve-cv-task" / "SKILL.md",
)
MODEL_SELECTION = ROOT / "resources" / "model-selection.md"

#: Environment variable naming an upstream ``skills/`` directory for the live drift check.
UPSTREAM_DIR_ENV = "SENTINEL_UPSTREAM_SKILLS_DIR"
#: Delegation-map columns holding the official skill name and its MCP resource address.
MAP_SKILL_COLUMN = "First official skill"
MAP_RESOURCE_COLUMN = "MCP resource fallback"
#: MCP entrypoint address the upstream server advertises for each skill.
RESOURCE_TEMPLATE = "skill://roboflow/{name}/SKILL.md"
#: Trees and file types searched for stale upstream skill names and resource addresses.
FRESHNESS_SCOPES = ("resources", "docs", "claude-skills", "agents", "shared", "evals", "README.md")
FRESHNESS_SUFFIXES = frozenset({".md", ".txt", ".json"})
#: Retired upstream resource scheme; current addresses use ``skill://roboflow/``.
STALE_RESOURCE_PREFIX = "roboflow://skills/"
NAMESPACED_SKILL = re.compile(r"\broboflow:([a-z0-9][a-z0-9-]*)")
RESOURCE_SKILL = re.compile(r"skill://roboflow/([A-Za-z0-9_.-]+)/")
BACKTICKED_SKILL = re.compile(r"`(roboflow-[a-z0-9-]+)`")
SKILL_CELL = re.compile(r"`([a-z0-9-]+)`")
FRONTMATTER_NAME = re.compile(r"^name:\s*(.+?)\s*$", re.MULTILINE)


@dataclass(frozen=True)
class UpstreamRoster:
    """Committed snapshot of the official Roboflow skill names Sentinel delegates to."""

    skills: frozenset[str]
    not_mapped: Mapping[str, str]
    source_commit: str


def read(path: Path) -> str:
    if not path.exists():
        raise AssertionError(f"Missing required file: {path}")
    return path.read_text(encoding="utf-8")


def assert_contains(text: str, needle: str, path: Path) -> None:
    if needle not in text:
        raise AssertionError(f"{path} is missing `{needle}`")


def load_roster(path: Path) -> UpstreamRoster:
    """Parse and validate the committed upstream skill roster."""
    raw = json.loads(read(path))
    skills = raw.get("skills")
    if not isinstance(skills, list) or not skills or not all(isinstance(name, str) and name for name in skills):
        raise AssertionError(f"{path} needs a non-empty `skills` list of skill names")
    if len(set(skills)) != len(skills):
        raise AssertionError(f"{path} lists a skill name twice")
    not_mapped = raw.get("not_mapped")
    if not isinstance(not_mapped, dict):
        raise AssertionError(f"{path} needs a `not_mapped` object of skill name -> reason")
    for name, reason in not_mapped.items():
        if name not in skills:
            raise AssertionError(f"{path} `not_mapped` names {name!r}, which is not in `skills`")
        if not isinstance(reason, str) or not reason.strip():
            raise AssertionError(f"{path} `not_mapped` entry {name!r} needs a reason")
    commit = raw.get("source_commit")
    if not isinstance(commit, str) or not commit:
        raise AssertionError(f"{path} needs the upstream `source_commit` the roster was taken from")
    return UpstreamRoster(skills=frozenset(skills), not_mapped=dict(not_mapped), source_commit=commit)


def _row_cells(line: str) -> list[str]:
    return [cell.strip() for cell in line.strip().strip("|").split("|")]


def table_column(text: str, header: str) -> list[str]:
    """Return the body cells under ``header`` in the first Markdown table that has that column.

    Examples:
        >>> table_column("| a | b |\\n| - | - |\\n| `x` | y |\\n\\ntext", "a")
        ['`x`']
    """
    lines = text.splitlines()
    for index, line in enumerate(lines):
        if not line.lstrip().startswith("|") or header not in _row_cells(line):
            continue
        column = _row_cells(line).index(header)
        cells = []
        for row in lines[index + 2 :]:
            if not row.lstrip().startswith("|"):
                break
            row_cells = _row_cells(row)
            if len(row_cells) <= column:
                raise AssertionError(f"table row lacks a `{header}` cell: {row.strip()}")
            cells.append(row_cells[column])
        return cells
    raise AssertionError(f"no Markdown table with a `{header}` column")


def lookup_map(lookup: str) -> dict[str, str]:
    """Return ``skill name -> MCP resource`` for every row of the delegation map."""
    mapped: dict[str, str] = {}
    rows = zip(table_column(lookup, MAP_SKILL_COLUMN), table_column(lookup, MAP_RESOURCE_COLUMN), strict=True)
    for skill_cell, resource_cell in rows:
        match = SKILL_CELL.fullmatch(skill_cell)
        if not match:
            raise AssertionError(f"{LOOKUP} map cell {skill_cell!r} must hold exactly one backticked skill name")
        name = match.group(1)
        expected = f"`{RESOURCE_TEMPLATE.format(name=name)}`"
        if resource_cell != expected:
            raise AssertionError(f"{LOOKUP} maps {name!r} to {resource_cell}; expected {expected}")
        if name in mapped:
            raise AssertionError(f"{LOOKUP} maps {name!r} twice")
        mapped[name] = RESOURCE_TEMPLATE.format(name=name)
    return mapped


def assert_map_matches_roster(mapped: Mapping[str, str], roster: UpstreamRoster) -> None:
    """Every mapped skill exists upstream; every upstream skill is mapped or deliberately not mapped."""
    unknown = sorted(set(mapped) - roster.skills)
    if unknown:
        raise AssertionError(
            f"{LOOKUP} maps skills missing from {ROSTER.name}: {unknown}; fix the name or refresh the roster"
        )
    contradictory = sorted(set(mapped) & set(roster.not_mapped))
    if contradictory:
        raise AssertionError(f"{ROSTER.name} lists {contradictory} as not_mapped, but {LOOKUP} maps them")
    unmapped = sorted(roster.skills - set(mapped) - set(roster.not_mapped))
    if unmapped:
        raise AssertionError(
            f"upstream skills {unmapped} are neither in the {LOOKUP} delegation map "
            f"nor in {ROSTER.name} `not_mapped` with a reason"
        )


def stale_references(text: str, roster: frozenset[str]) -> list[str]:
    """List upstream skill references in ``text`` that use a retired form or a name the roster lacks.

    Examples:
        >>> stale_references("`roboflow:inference` or `roboflow:roboflow-inference`", frozenset({"roboflow-inference"}))
        ['roboflow:inference']
        >>> stale_references("read skill://roboflow/universe/SKILL.md", frozenset({"roboflow-universe"}))
        ['skill://roboflow/universe/']
    """
    found = [STALE_RESOURCE_PREFIX] * text.count(STALE_RESOURCE_PREFIX)
    found += [f"roboflow:{name}" for name in NAMESPACED_SKILL.findall(text) if name not in roster]
    found += [f"skill://roboflow/{name}/" for name in RESOURCE_SKILL.findall(text) if name not in roster]
    found += [f"`{name}`" for name in BACKTICKED_SKILL.findall(text) if name not in roster]
    return found


def iter_freshness_files() -> Iterator[Path]:
    for scope in FRESHNESS_SCOPES:
        path = ROOT / scope
        if path.is_file():
            yield path
            continue
        yield from (f for f in sorted(path.rglob("*")) if f.suffix in FRESHNESS_SUFFIXES and f.is_file())


def assert_no_stale_upstream_references(roster: UpstreamRoster) -> None:
    """Fail on retired ``roboflow:<topic>`` or ``roboflow://skills/`` forms, or unknown skill names."""
    problems = []
    for path in iter_freshness_files():
        for number, line in enumerate(read(path).splitlines(), start=1):
            problems += [f"{path.relative_to(ROOT)}:{number}: {ref}" for ref in stale_references(line, roster.skills)]
    if problems:
        raise AssertionError(
            "stale upstream Roboflow skill references (use names from "
            f"{ROSTER.name} and {RESOURCE_TEMPLATE.format(name='<name>')}):\n  " + "\n  ".join(problems)
        )


def skill_frontmatter_name(text: str) -> str | None:
    """Return the ``name`` field of a ``SKILL.md`` YAML frontmatter block, or ``None`` when absent.

    Examples:
        >>> skill_frontmatter_name("---\\nname: draw-vision\\ndescription: d\\n---\\nbody")
        'draw-vision'
        >>> skill_frontmatter_name("no frontmatter") is None
        True
    """
    if not text.startswith("---"):
        return None
    end = text.find("\n---", 3)
    match = FRONTMATTER_NAME.search(text[3:end]) if end != -1 else None
    return match.group(1).strip("'\"") if match else None


def upstream_skill_names(skills_dir: Path) -> set[str]:
    """Read skill names from ``<skills_dir>/*/SKILL.md`` frontmatter; never executes upstream content."""
    if not skills_dir.is_dir():
        raise AssertionError(f"{UPSTREAM_DIR_ENV}={skills_dir} is not a directory; point it at the upstream skills/")
    manifests = sorted(skills_dir.glob("*/SKILL.md"))
    if not manifests:
        raise AssertionError(
            f"{UPSTREAM_DIR_ENV}={skills_dir} holds no */SKILL.md; point it at skills/, not the repository root"
        )
    names: set[str] = set()
    for manifest in manifests:
        name = skill_frontmatter_name(manifest.read_text(encoding="utf-8"))
        if not name:
            raise AssertionError(f"{manifest} has no frontmatter `name`")
        if name in names:
            raise AssertionError(f"upstream skill name {name!r} appears in more than one SKILL.md")
        names.add(name)
    return names


def assert_roster_matches_upstream(roster: UpstreamRoster) -> None:
    """Compare the committed roster with a live upstream ``skills/`` directory when one is configured."""
    configured = os.environ.get(UPSTREAM_DIR_ENV, "").strip()
    if not configured:
        if os.environ.get("SENTINEL_REQUIRE_UPSTREAM", "").strip():
            raise AssertionError(f"{UPSTREAM_DIR_ENV} must name a current upstream skills directory for a release")
        print(f"note: {UPSTREAM_DIR_ENV} is unset; skipped the upstream roster drift check.")
        return
    upstream = upstream_skill_names(Path(configured).expanduser())
    added = sorted(upstream - roster.skills)
    removed = sorted(roster.skills - upstream)
    if added or removed:
        raise AssertionError(
            f"{ROSTER.name} (source_commit {roster.source_commit[:12]}) drifted from {configured}: "
            f"new upstream {added}, gone upstream {removed}; refresh the roster and its source fields, "
            "then update the delegation map"
        )
    print(f"Upstream roster matches the {len(upstream)} skills in {configured}.")


def assert_upstream_freshness(lookup: str, cases: list[dict[str, str]]) -> None:
    """Tie the delegation map, docs mirror, and routing cases to the committed upstream roster."""
    roster = load_roster(ROSTER)
    mapped = lookup_map(lookup)
    assert_map_matches_roster(mapped, roster)
    docs = read(DOCS_SKILLS)
    for name in mapped:
        assert_contains(docs, f"`{name}`", DOCS_SKILLS)
    for case in cases:
        skill = case["local_skill"]
        if skill not in mapped:
            raise AssertionError(f"routing case {case['need']!r} expects {skill!r}, which {LOOKUP} does not map")
        if case["mcp_resource"] != mapped[skill]:
            raise AssertionError(
                f"routing case {case['need']!r} expects {case['mcp_resource']!r}; {LOOKUP} maps {mapped[skill]!r}"
            )
    assert_no_stale_upstream_references(roster)
    assert_roster_matches_upstream(roster)


STALE_COMMAND_PATTERNS = [
    "/vision-delivery:",  # pre-rename namespace
    # bare /sentinel:estimate` — verified Unknown command 2026-07-10; use /sentinel:estimate-economics
    "/sentinel:estimate\u0060",
]


def assert_no_stale_commands() -> None:
    """Fail when docs/skills/agents reference a slash command that does not resolve.

    Examples:
        >>> assert_no_stale_commands()
    """
    import pathlib

    repo = pathlib.Path(__file__).resolve().parents[2]
    scopes = ["codex-skills", "claude-skills", "agents", "docs", "README.md"]
    for scope in scopes:
        p = repo / scope
        files = [p] if p.is_file() else list(p.rglob("*.md"))
        for f in files:
            text = f.read_text(encoding="utf-8")
            for pat in STALE_COMMAND_PATTERNS:
                needle = pat.encode().decode("unicode_escape")
                if needle in text:
                    raise AssertionError(f"{f} contains stale command reference {needle!r}")


def main() -> None:
    lookup = read(LOOKUP)
    solvers = [(path, read(path)) for path in SOLVERS]
    model_selection = read(MODEL_SELECTION)
    cases: list[dict[str, str]] = json.loads(CASES.read_text(encoding="utf-8"))["platform_routes"]

    for phrase in (
        "official `roboflow/computer-vision-skills` skill",
        f"matching `{RESOURCE_TEMPLATE.format(name='<name>')}` MCP resource",
        "local provider-neutral scaffold",
        "Do not copy Roboflow platform recipes into Sentinel",
        "Return to the Sentinel acceptance/delivery workflow",
    ):
        assert_contains(lookup, phrase, LOOKUP)

    assert_upstream_freshness(lookup, cases)

    for path, solver in solvers:
        assert_contains(solver, "roboflow-platform-lookup.md", path)
        assert_contains(solver, "Roboflow platform knowledge lookup", path)
    assert_contains(model_selection, "stable fallback only", MODEL_SELECTION)
    assert_contains(
        model_selection,
        "Validate every volatile model identifier and paid-training operation",
        MODEL_SELECTION,
    )
    assert_no_stale_commands()

    model_ids = re.findall(r"`(?:rf|yolo|sam|vit|resnet|deeplab)[^`]+`", model_selection)
    if model_ids:
        raise AssertionError(
            "model-selection fallback copies exact platform IDs; delegate the current catalog upstream"
        )

    active_paths = [*sorted((ROOT / "codex-skills").glob("*/SKILL.md"))]
    active_paths.extend(sorted((ROOT / "claude-skills").glob("*/SKILL.md")))
    active_paths.extend(sorted((ROOT / "agents").glob("*.md")))
    active_paths.extend(sorted((ROOT / "evals" / "e2e").glob("*.md")))
    active_paths.extend([ROOT / "resources" / "fde-methodology.md", MODEL_SELECTION])
    forbidden = (
        r"\b(?:rfdetr|RF-DETR|yolov?\d*|YOLOv?\d*|SAM\d*|CLIP|ByteTrack|MediaPipe|Florence)\b",
        r"\b(?:models|trainings|versions|annotation_jobs|workflow_specs|"
        r"project_deployment|devices|model_evals)_[a-z0-9_]+\b",
        r"universe_search\s*:",
        r"checkpoint\s*:",
        r"roboflow://",
        r"skill://",
    )
    for path in active_paths:
        text = read(path)
        for pattern in forbidden:
            if re.search(pattern, text):
                raise AssertionError(
                    f"{path.relative_to(ROOT)} duplicates volatile upstream recipe pattern {pattern!r}"
                )

    print("Roboflow platform routing stays thin and source-backed.")


if __name__ == "__main__":
    try:
        main()
    except AssertionError as exc:
        print(f"platform-routing assertion failed: {exc}", file=sys.stderr)
        sys.exit(1)
