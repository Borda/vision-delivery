#!/usr/bin/env python3
"""Load Sentinel's skill roster, the one source for every skill name, kind, and listing.

`shared/skill-roster.json` names each skill once, with its kind, a one-line use, whether a
Sentinel scorer measures it, and the human-facing listings ("surfaces") that must name it.
Evaluations, the package validator, the route scaffold, and the outcome-report helper read
this file instead of keeping their own copies or counts.
"""

from __future__ import annotations

import json
import re
from collections.abc import Iterable
from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from typing import Any

#: Location of the roster inside a plugin root, as a package-relative path.
ROSTER_RELATIVE = "shared/skill-roster.json"
#: Roster of the plugin this module ships with.
ROSTER_PATH = Path(__file__).resolve().parents[1] / ROSTER_RELATIVE
SCHEMA_VERSION = 1
#: Top-level keys of the roster document: exactly the ones dump_roster writes back.
DOCUMENT_KEYS = frozenset({"kinds", "schema_version", "skills", "surfaces"})
#: Skill directory names: lowercase words joined by single hyphens.
SKILL_NAME = re.compile(r"^[a-z][a-z0-9]*(?:-[a-z0-9]+)*$")
MAX_NAME_LENGTH = 64
MAX_USE_LENGTH = 160
#: The router skill, and the heading of the table in it that sends a request to a route.
ROUTER_RELATIVE = "claude-skills/solve-cv-task/SKILL.md"
ROUTER_TABLE_HEADING = "## 2. Route by required output"
_BACKTICKED = re.compile(r"`([a-z][a-z0-9-]*)`")


class RosterError(ValueError):
    """Report a roster file that cannot be trusted as the skill source."""


class SkillKind(str, Enum):
    """What role a skill plays for the user."""

    ROUTER = "router"
    FLAGSHIP = "flagship"
    PREVIEW = "preview"
    GUIDED = "guided"
    UTILITY = "utility"


class Surface(str, Enum):
    """A human-facing listing that names skills and must agree with the roster."""

    CAPABILITY_CONTRACT = "capability-contract"
    README = "readme"
    LLMS = "llms"
    USE_CASES = "use-cases"
    ISSUE_FORM = "issue-form"


class ScorerTask(str, Enum):
    """The `score_baseline.py --task` that measures a skill's output."""

    COUNT = "count"
    FLAG = "flag"
    TEXT = "text"


#: Repository file that holds each human-facing listing.
SURFACE_FILES: dict[Surface, str] = {
    Surface.CAPABILITY_CONTRACT: "shared/capability-contract.md",
    Surface.README: "README.md",
    Surface.LLMS: "docs/llms.txt",
    Surface.USE_CASES: "docs/use-cases.md",
    Surface.ISSUE_FORM: ".github/ISSUE_TEMPLATE/outcome-report.yml",
}

#: Listings a new skill of each kind appears in, before anyone decides otherwise.
DEFAULT_SURFACES: dict[SkillKind, frozenset[Surface]] = {
    SkillKind.ROUTER: frozenset({Surface.CAPABILITY_CONTRACT, Surface.LLMS}),
    SkillKind.FLAGSHIP: frozenset(Surface),
    SkillKind.PREVIEW: frozenset(Surface),
    SkillKind.GUIDED: frozenset(Surface),
    SkillKind.UTILITY: frozenset({Surface.CAPABILITY_CONTRACT, Surface.README, Surface.LLMS}),
}


@dataclass(frozen=True)
class RosterEntry:
    """One skill as the roster records it."""

    name: str
    kind: SkillKind
    use: str
    scorer: ScorerTask | None
    surfaces: frozenset[Surface]

    def to_json(self) -> dict[str, Any]:
        """Return the entry as the JSON object stored in the roster file.

        Examples:
            >>> entry = RosterEntry("x-y", SkillKind.UTILITY, "does x", None, frozenset({Surface.README}))
            >>> entry.to_json()["surfaces"]
            ['readme']
        """
        return {
            "kind": self.kind.value,
            "name": self.name,
            "scorer": self.scorer.value if self.scorer is not None else None,
            "surfaces": sorted(surface.value for surface in self.surfaces),
            "use": self.use,
        }


@dataclass(frozen=True)
class Roster:
    """Every skill the plugin ships, sorted by name."""

    entries: tuple[RosterEntry, ...]

    def names(self) -> frozenset[str]:
        """Return every skill name.

        Examples:
            >>> Roster(()).names()
            frozenset()
        """
        return frozenset(entry.name for entry in self.entries)

    def entry(self, name: str) -> RosterEntry | None:
        """Return the entry for one skill name, or ``None`` when the roster lacks it.

        Examples:
            >>> Roster(()).entry("status") is None
            True
        """
        return next((entry for entry in self.entries if entry.name == name), None)

    def on_surface(self, surface: Surface) -> frozenset[str]:
        """Return the names one listing must show.

        Examples:
            >>> Roster(()).on_surface(Surface.README)
            frozenset()
        """
        return frozenset(entry.name for entry in self.entries if surface in entry.surfaces)

    def build_routes(self) -> frozenset[str]:
        """Return the routes that build a capability: every flagship and preview skill.

        The router's route table, the methodology contract, and the artifact contract all apply to
        exactly these skills, so each reads this set instead of keeping its own list.

        Examples:
            >>> Roster(()).build_routes()
            frozenset()
        """
        kinds = {SkillKind.FLAGSHIP, SkillKind.PREVIEW}
        return frozenset(entry.name for entry in self.entries if entry.kind in kinds)

    def with_entry(self, entry: RosterEntry) -> Roster:
        """Return a roster that adds one new entry, kept in name order.

        Raises:
            RosterError: When the name is already registered.

        Examples:
            >>> added = Roster(()).with_entry(RosterEntry("a", SkillKind.UTILITY, "u", None, frozenset(Surface)))
            >>> sorted(added.names())
            ['a']
        """
        if entry.name in self.names():
            raise RosterError(f"skill {entry.name!r} is already in the roster")
        return Roster(tuple(sorted((*self.entries, entry), key=lambda item: item.name)))


def router_table_routes(router_text: str) -> list[str]:
    """Return the skill names in the Route column of the router's route table, in table order.

    Examples:
        >>> rows = "| Needs | Route | Why |\\n| - | - | - |\\n| boxes | `a-b` | x |"
        >>> router_table_routes(ROUTER_TABLE_HEADING + "\\n\\n" + rows + "\\n\\n## 3")
        ['a-b']
        >>> router_table_routes("no table here")
        []
    """
    _, found, rest = router_text.partition(ROUTER_TABLE_HEADING)
    if not found:
        return []
    routes: list[str] = []
    for line in rest.split("\n## ", 1)[0].splitlines():
        cells = [cell.strip() for cell in line.strip().strip("|").split("|")]
        if line.lstrip().startswith("|") and len(cells) >= 2:
            routes.extend(_BACKTICKED.findall(cells[1]))
    return routes


def router_problems(roster: Roster, router_text: str) -> list[str]:
    """Return every disagreement between the router's route table and the roster.

    A build route the table lacks is never reached from the front door, and a table name the roster
    lacks points at a skill that does not ship.

    Examples:
        >>> router_problems(Roster(()), ROUTER_TABLE_HEADING + "\\n\\n| a | `ghost-route` | b |\\n")
        ['claude-skills/solve-cv-task/SKILL.md: route table names ghost-route, which is not in the roster']
    """
    listed = router_table_routes(router_text)
    problems = [
        f"{ROUTER_RELATIVE}: route table is missing the build route {name}"
        for name in sorted(roster.build_routes() - set(listed))
    ]
    problems.extend(
        f"{ROUTER_RELATIVE}: route table names {name}, which is not in the roster"
        for name in sorted(set(listed) - roster.names())
    )
    return problems


def check_name(name: object) -> str:
    """Return a valid skill name or raise.

    Raises:
        RosterError: When the name is not lowercase hyphenated words of at most 64 characters.

    Examples:
        >>> check_name("read-text")
        'read-text'
        >>> check_name("Read_Text")
        Traceback (most recent call last):
        ...
        skill_roster.RosterError: skill name 'Read_Text' must be lowercase words joined by single hyphens
    """
    if not isinstance(name, str) or len(name) > MAX_NAME_LENGTH or not SKILL_NAME.match(name):
        raise RosterError(f"skill name {name!r} must be lowercase words joined by single hyphens")
    return name


def _closed(enum_type: type[Enum], value: object, field: str, name: str) -> Any:
    """Convert one closed-set field, naming the skill and the allowed values on failure."""
    try:
        return enum_type(value)
    except ValueError:
        allowed = ", ".join(member.value for member in enum_type)
        raise RosterError(f"{name}: {field} {value!r} is not one of {allowed}") from None


def _surfaces(value: object, name: str) -> frozenset[Surface]:
    """Parse the surface list of one entry; the capability contract lists every skill."""
    if not isinstance(value, list) or not value:
        raise RosterError(f"{name}: surfaces must be a non-empty list")
    surfaces = frozenset(_closed(Surface, item, "surface", name) for item in value)
    if len(surfaces) != len(value):
        raise RosterError(f"{name}: surfaces repeat a value")
    if Surface.CAPABILITY_CONTRACT not in surfaces:
        raise RosterError(f"{name}: every skill is listed on the capability-contract surface")
    return surfaces


def parse_entry(item: object) -> RosterEntry:
    """Parse one roster entry from its JSON object.

    Raises:
        RosterError: When a field is missing, extra, or outside its allowed values.

    Examples:
        >>> raw = {"name": "status", "kind": "utility", "use": "where it stands", "scorer": None,
        ...        "surfaces": ["capability-contract"]}
        >>> parse_entry(raw).kind.value
        'utility'
    """
    if not isinstance(item, dict):
        raise RosterError("every roster entry must be a JSON object")
    name = check_name(item.get("name"))
    expected = {"name", "kind", "use", "scorer", "surfaces"}
    if set(item) != expected:
        raise RosterError(f"{name}: entry fields must be exactly {sorted(expected)}")
    use = item["use"]
    if not isinstance(use, str) or not use.strip() or "\n" in use or len(use) > MAX_USE_LENGTH:
        raise RosterError(f"{name}: use must be one line of 1 to {MAX_USE_LENGTH} characters")
    kind = _closed(SkillKind, item["kind"], "kind", name)
    scorer = None if item["scorer"] is None else _closed(ScorerTask, item["scorer"], "scorer", name)
    # A flagship route always has a Sentinel scorer; a preview route may have one; no other kind does.
    if kind == SkillKind.FLAGSHIP and scorer is None:
        raise RosterError(f"{name}: a flagship route names its scorer task")
    if scorer is not None and kind not in (SkillKind.FLAGSHIP, SkillKind.PREVIEW):
        raise RosterError(f"{name}: only a flagship or preview route names a scorer task")
    return RosterEntry(name=name, kind=kind, use=use, scorer=scorer, surfaces=_surfaces(item["surfaces"], name))


def _check_described(payload: dict[str, Any], key: str, members: Iterable[Enum]) -> None:
    """Require one description per closed-set value, so the file documents itself."""
    described = payload.get(key)
    wanted = {member.value for member in members}
    if not isinstance(described, dict) or set(described) != wanted:
        raise RosterError(f"roster {key} must describe exactly {sorted(wanted)}")
    if not all(isinstance(text, str) and text.strip() for text in described.values()):
        raise RosterError(f"roster {key} descriptions must be non-empty text")


def parse_roster(payload: object) -> Roster:
    """Parse and check a whole roster document.

    Raises:
        RosterError: When the schema, a description table, or any entry is invalid, or a
            name repeats, or the entries are not in name order.

    Examples:
        >>> parse_roster({"schema_version": 2})
        Traceback (most recent call last):
        ...
        skill_roster.RosterError: roster schema_version must be 1
    """
    if not isinstance(payload, dict) or payload.get("schema_version") != SCHEMA_VERSION:
        raise RosterError(f"roster schema_version must be {SCHEMA_VERSION}")
    unknown = sorted(set(payload) - DOCUMENT_KEYS)
    if unknown:
        raise RosterError(f"roster has unknown top-level keys {unknown}; dump_roster would drop them")
    _check_described(payload, "kinds", SkillKind)
    _check_described(payload, "surfaces", Surface)
    raw_skills = payload.get("skills")
    if not isinstance(raw_skills, list) or not raw_skills:
        raise RosterError("roster skills must be a non-empty list")
    entries = tuple(parse_entry(item) for item in raw_skills)
    names = [entry.name for entry in entries]
    if len(set(names)) != len(names):
        raise RosterError(f"roster names repeat: {sorted(name for name in set(names) if names.count(name) > 1)}")
    if names != sorted(names):
        raise RosterError("roster skills must be sorted by name")
    return Roster(entries)


def load_roster(path: Path = ROSTER_PATH) -> Roster:
    """Read and check the roster file.

    Raises:
        RosterError: When the file is missing, unreadable, not JSON, or invalid.

    Examples:
        >>> "solve-cv-task" in load_roster().names()
        True
    """
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise RosterError(f"cannot read the skill roster {path.name}: {exc}") from exc
    return parse_roster(payload)


def dump_roster(roster: Roster, template: dict[str, Any]) -> str:
    """Render a roster in the repository's JSON style: two-space indent, sorted keys.

    Args:
        roster: Entries to write.
        template: The current roster document, whose description tables are kept.

    Returns:
        The file text, ending in one newline.

    Examples:
        >>> text = dump_roster(Roster(()), {"schema_version": 1, "kinds": {}, "surfaces": {}})
        >>> text.splitlines()[1]
        '  "kinds": {},'
    """
    document = {
        "kinds": template.get("kinds", {}),
        "schema_version": SCHEMA_VERSION,
        "skills": [entry.to_json() for entry in roster.entries],
        "surfaces": template.get("surfaces", {}),
    }
    return json.dumps(document, indent=2, sort_keys=True) + "\n"
