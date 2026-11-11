#!/usr/bin/env python3
"""Scaffold a new Sentinel skill from the route template and register it in the skill roster.

Usage:
    python scripts/new_route.py <name> --kind preview --use "one-line use"
    python scripts/new_route.py <name> --kind flagship --scorer count --use "..." --surface readme

Creates `claude-skills/<name>/SKILL.md` and `evals/trigger/<name>.cases.json` from
`templates/route/`, then adds the skill to `shared/skill-roster.json`. A name that the roster,
either skill tree, or the trigger cases already hold is refused, and nothing is written. The
Codex copy comes from `scripts/sync_codex_skills.py`; the listings the roster names for the new
skill are printed so they can be updated by hand, and the roster evaluation fails until they are.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from dataclasses import dataclass
from pathlib import Path

from skill_roster import (
    DEFAULT_SURFACES,
    ROSTER_RELATIVE,
    ROUTER_RELATIVE,
    SURFACE_FILES,
    RosterEntry,
    RosterError,
    ScorerTask,
    SkillKind,
    Surface,
    check_name,
    dump_roster,
    parse_roster,
)

ROOT = Path(__file__).resolve().parents[1]
TEMPLATE_DIR = "templates/route"
#: Text the template carries until a person replaces it; the roster evaluation rejects leftovers.
TEMPLATE_MARKERS = ("TODO(template)", "ROUTE_NAME", "ROUTE_TITLE", "ROUTE_USE", "ROUTE_KIND")


class ScaffoldError(ValueError):
    """Report why a route cannot be created; nothing has been written."""


@dataclass(frozen=True)
class RouteRequest:
    """What the caller asked to create."""

    name: str
    kind: SkillKind
    use: str
    scorer: ScorerTask | None = None
    surfaces: frozenset[Surface] = frozenset()


@dataclass(frozen=True)
class ScaffoldPlan:
    """Every file the scaffold writes, rendered before anything touches the disk."""

    entry: RosterEntry
    skill_path: Path
    cases_path: Path
    roster_path: Path
    skill_text: str
    cases_text: str
    roster_text: str


def render_skill(template: str, entry: RosterEntry) -> str:
    """Fill the template's placeholders for one skill.

    Examples:
        >>> entry = RosterEntry("count-crates", SkillKind.PREVIEW, "count crates", None, frozenset(Surface))
        >>> render_skill("name: ROUTE_NAME\\n# ROUTE_TITLE\\nROUTE_USE. ROUTE_KIND", entry)
        'name: count-crates\\n# Count Crates\\nCount crates. preview'
    """
    title = " ".join(word.capitalize() for word in entry.name.split("-"))
    use = entry.use[:1].upper() + entry.use[1:]
    replacements = {
        "ROUTE_NAME": entry.name,
        "ROUTE_TITLE": title,
        "ROUTE_USE": use.rstrip("."),
        "ROUTE_KIND": entry.kind.value,
    }
    for marker, value in replacements.items():
        template = template.replace(marker, value)
    return template


def _taken(root: Path, name: str) -> list[str]:
    """Return every place that already holds ``name``."""
    candidates = (
        f"claude-skills/{name}",
        f"codex-skills/{name}",
        f"evals/trigger/{name}.cases.json",
    )
    return [relative for relative in candidates if (root / relative).exists() or (root / relative).is_symlink()]


def plan_route(root: Path, request: RouteRequest) -> ScaffoldPlan:
    """Check the request against the repository and render every file, writing nothing.

    Args:
        root: Repository root holding the roster, the template, and the skill trees.
        request: Name, kind, one-line use, scorer task, and listings.

    Returns:
        The rendered plan.

    Raises:
        ScaffoldError: When the name is invalid or taken, the template or roster is unusable,
            or the entry breaks a roster rule.

    Examples:
        >>> plan_route(ROOT, RouteRequest("solve-cv-task", SkillKind.ROUTER, "x"))
        Traceback (most recent call last):
        ...
        new_route.ScaffoldError: skill 'solve-cv-task' already exists in shared/skill-roster.json
    """
    roster_path = root / ROSTER_RELATIVE
    try:
        name = check_name(request.name)
        document = json.loads(roster_path.read_text(encoding="utf-8"))
        roster = parse_roster(document)
        if name in roster.names():
            raise ScaffoldError(f"skill {name!r} already exists in {ROSTER_RELATIVE}")
        taken = _taken(root, name)
        if taken:
            raise ScaffoldError(f"skill {name!r} already exists at {', '.join(taken)}")
        surfaces = request.surfaces or DEFAULT_SURFACES[request.kind]
        entry = RosterEntry(name, request.kind, request.use, request.scorer, surfaces | {Surface.CAPABILITY_CONTRACT})
        updated = roster.with_entry(entry)
        roster_text = dump_roster(updated, document)
        parse_roster(json.loads(roster_text))
        template = root / TEMPLATE_DIR
        skill_text = render_skill((template / "SKILL.md").read_text(encoding="utf-8"), entry)
        cases_text = (template / "cases.json").read_text(encoding="utf-8")
    except (RosterError, OSError, json.JSONDecodeError) as exc:
        raise ScaffoldError(str(exc)) from exc
    return ScaffoldPlan(
        entry=entry,
        skill_path=root / "claude-skills" / name / "SKILL.md",
        cases_path=root / "evals" / "trigger" / f"{name}.cases.json",
        roster_path=roster_path,
        skill_text=skill_text,
        cases_text=cases_text,
        roster_text=roster_text,
    )


def _write_new(path: Path, text: str) -> None:
    """Create one file that must not exist yet."""
    descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o644)
    with os.fdopen(descriptor, "w", encoding="utf-8", newline="\n") as stream:
        stream.write(text)


def apply_plan(plan: ScaffoldPlan) -> None:
    """Write the planned files; on any failure remove what this call created.

    The roster is replaced last and atomically, so a failure never leaves it naming a skill
    whose files are missing.

    Raises:
        ScaffoldError: When a file cannot be written.
    """
    created: list[Path] = []
    try:
        plan.skill_path.parent.mkdir(parents=False, exist_ok=False)
        created.append(plan.skill_path.parent)
        _write_new(plan.skill_path, plan.skill_text)
        created.append(plan.skill_path)
        _write_new(plan.cases_path, plan.cases_text)
        created.append(plan.cases_path)
        staging = plan.roster_path.with_name(f".{plan.roster_path.name}.new")
        _write_new(staging, plan.roster_text)
        created.append(staging)
        os.replace(staging, plan.roster_path)
        created.remove(staging)
    except OSError as exc:
        for path in reversed(created):
            if path.is_dir():
                path.rmdir()
            else:
                path.unlink(missing_ok=True)
        raise ScaffoldError(f"could not write the new route: {exc}") from exc


def next_steps(plan: ScaffoldPlan, root: Path) -> list[str]:
    """Return what a person must still do for the new skill to pass the evaluations.

    Examples:
        >>> entry = RosterEntry("x", SkillKind.UTILITY, "u", None, frozenset({Surface.CAPABILITY_CONTRACT}))
        >>> plan = ScaffoldPlan(entry, ROOT / "s", ROOT / "c", ROOT / "r", "", "", "")
        >>> next_steps(plan, ROOT)[-1]
        '- shared/capability-contract.md'
    """
    steps = [
        f"Created {plan.skill_path.relative_to(root).as_posix()} and {plan.cases_path.relative_to(root).as_posix()}; "
        f"registered {plan.entry.name} ({plan.entry.kind.value}) in {ROSTER_RELATIVE}.",
        "Replace every TODO(template) line in the skill, and write at least four should_fire and four "
        "should_not_fire trigger cases.",
        "Run scripts/sync_codex_skills.py to create the Codex copy.",
        "Name the skill in these listings (the roster evaluation fails until each one does):",
    ]
    if plan.entry.kind in (SkillKind.FLAGSHIP, SkillKind.PREVIEW):
        steps.append(
            f"- {ROUTER_RELATIVE} (the route table; the methodology and artifact contracts now apply to this route too)"
        )
    steps.extend(f"- {SURFACE_FILES[surface]}" for surface in sorted(plan.entry.surfaces, key=lambda item: item.value))
    return steps


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    """Parse scaffold options."""
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("name", help="skill directory name, lowercase words joined by hyphens")
    parser.add_argument("--kind", required=True, choices=[kind.value for kind in SkillKind])
    parser.add_argument("--use", required=True, help="one-line use, as the roster and docs/llms.txt show it")
    parser.add_argument(
        "--scorer",
        choices=[task.value for task in ScorerTask],
        help="required for a flagship route, optional for a preview route",
    )
    parser.add_argument(
        "--surface",
        action="append",
        choices=[surface.value for surface in Surface],
        help="listing that must name the skill; repeat it (default: the kind's usual listings)",
    )
    parser.add_argument("--root", type=Path, default=ROOT, help="repository root (default: this checkout)")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    """Create one route, or refuse with exit code 2 and write nothing."""
    args = parse_args(argv)
    root = args.root.resolve()
    request = RouteRequest(
        name=args.name,
        kind=SkillKind(args.kind),
        use=args.use,
        scorer=ScorerTask(args.scorer) if args.scorer else None,
        surfaces=frozenset(Surface(value) for value in args.surface or ()),
    )
    try:
        plan = plan_route(root, request)
        apply_plan(plan)
    except ScaffoldError as exc:
        print(f"new-route-error: {exc}", file=sys.stderr)
        return 2
    print("\n".join(next_steps(plan, root)))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
