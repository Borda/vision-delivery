#!/usr/bin/env python3
"""Check the one skill roster: its schema, the route scaffold, and the listings that name skills.

Every case is offline. The scaffold and listing cases run on copies in temporary folders, so the
repository itself is only read.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import tempfile
from collections.abc import Callable
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
for _folder in (ROOT / "scripts", ROOT / "evals" / "install"):
    if str(_folder) not in sys.path:
        sys.path.insert(0, str(_folder))

from assert_release_surface import roster_listing_problems  # noqa: E402
from new_route import TEMPLATE_DIR  # noqa: E402
from skill_roster import (  # noqa: E402
    DEFAULT_SURFACES,
    ROSTER_PATH,
    ROSTER_RELATIVE,
    ROUTER_RELATIVE,
    SURFACE_FILES,
    RosterEntry,
    RosterError,
    ScorerTask,
    SkillKind,
    Surface,
    dump_roster,
    load_roster,
    parse_roster,
    router_problems,
    router_table_routes,
)

NEW_ROUTE = ROOT / "scripts" / "new_route.py"
#: Text a shipped skill must never carry; the route template holds it until a person edits it.
LEFTOVER_MARKERS = ("TODO(template)", "ROUTE_")
#: A skill-shaped name that no roster holds.
GHOST = "ghost-route"
#: Name the scaffold cases create.
NEW_NAME = "count-crates"
#: A roster skill shown on every listing, used to edit listing copies.
LISTED_EVERYWHERE = "detect-and-analyze"
SUBPROCESS_TIMEOUT = 60


def require(condition: bool, message: str) -> None:
    """Raise an assertion carrying the roster condition that failed."""
    if not condition:
        raise AssertionError(message)


def _entry(name: object, kind: str = "utility", scorer: str | None = None, surfaces: tuple[str, ...] = ()) -> dict:
    """Return one raw roster entry; it lists only the capability contract unless told otherwise."""
    return {
        "kind": kind,
        "name": name,
        "scorer": scorer,
        "surfaces": ["capability-contract", *surfaces],
        "use": f"use of {name}",
    }


def _document(*skills: dict[str, Any]) -> dict[str, Any]:
    """Return the committed roster document with its skills replaced."""
    base = json.loads(ROSTER_PATH.read_text(encoding="utf-8"))
    return {**base, "skills": list(skills)}


def schema_negatives() -> dict[str, dict[str, Any]]:
    """Return one roster document per schema rule, each breaking exactly that rule."""
    without_use = {key: value for key, value in _entry("a-b").items() if key != "use"}
    return {
        "duplicate name": _document(_entry("a-b"), _entry("a-b")),
        "unsorted entries": _document(_entry("b-c"), _entry("a-b")),
        "missing field": _document(without_use),
        "extra field": _document({**_entry("a-b"), "owner": "someone"}),
        "unknown kind": _document(_entry("a-b", kind="wizard")),
        "unknown surface": _document(_entry("a-b", surfaces=("blog",))),
        "flagship without a scorer": _document(_entry("a-b", kind="flagship")),
        "utility skill with a scorer": _document(_entry("a-b", kind="utility", scorer="count")),
        "guided skill with a scorer": _document(_entry("a-b", kind="guided", scorer="text")),
        "bad name: capitals and underscore": _document(_entry("Bad_Name")),
        "bad name: double hyphen": _document(_entry("a--b")),
        "bad name: leading hyphen": _document(_entry("-ab")),
        "bad name: longer than 64": _document(_entry("a" * 65)),
        "bad name: not text": _document(_entry(7)),
        "unknown top-level key": {**_document(_entry("a-b")), "owners": {}},
    }


def check_schema_negative_controls() -> None:
    """A valid document parses; each single-rule break raises RosterError."""
    valid = _document(_entry("a-b"), _entry("c-d", kind="flagship", scorer="count", surfaces=("readme",)))
    require(sorted(parse_roster(valid).names()) == ["a-b", "c-d"], "the valid control document did not parse")
    accepted = []
    for label, document in schema_negatives().items():
        try:
            parse_roster(document)
        except RosterError:
            continue
        accepted.append(label)
    require(not accepted, f"roster schema accepted: {accepted}")


def check_committed_roster_round_trips() -> None:
    """The committed roster loads, renders back to its exact text, and matches claude-skills/."""
    text = ROSTER_PATH.read_text(encoding="utf-8")
    roster = load_roster()
    require(dump_roster(roster, json.loads(text)) == text, f"dump_roster(load) differs from {ROSTER_RELATIVE}")
    shipped = {path.parent.name for path in (ROOT / "claude-skills").glob("*/SKILL.md")}
    require(roster.names() == shipped, f"roster and claude-skills/ differ: {sorted(roster.names() ^ shipped)}")


def _scaffold_tree(base: Path, *, trigger_folder: bool = True) -> Path:
    """Build the smallest repository the scaffold needs: roster, template, and skill folders."""
    root = base / "repo"
    (root / "shared").mkdir(parents=True)
    shutil.copyfile(ROSTER_PATH, root / ROSTER_RELATIVE)
    shutil.copytree(ROOT / TEMPLATE_DIR, root / TEMPLATE_DIR)
    (root / "claude-skills").mkdir()
    if trigger_folder:
        (root / "evals" / "trigger").mkdir(parents=True)
    return root


def _snapshot(root: Path) -> dict[str, bytes]:
    """Return every path below ``root`` with its bytes, folders marked."""
    return {
        path.relative_to(root).as_posix(): b"<folder>" if path.is_dir() else path.read_bytes()
        for path in sorted(root.rglob("*"))
    }


def _new_route(root: Path, *args: str) -> subprocess.CompletedProcess[str]:
    """Run the scaffold against ``root`` and return the finished process."""
    command = [sys.executable, str(NEW_ROUTE), *args, "--root", str(root)]
    return subprocess.run(command, capture_output=True, text=True, timeout=SUBPROCESS_TIMEOUT, check=False)


def _registered(root: Path, name: str) -> RosterEntry:
    """Return the entry the scaffold registered, failing when the roster lacks it."""
    entry = load_roster(root / ROSTER_RELATIVE).entry(name)
    if entry is None:
        raise AssertionError(f"{name} is not in the scaffolded roster")
    return entry


def check_scaffold_creates_and_registers() -> None:
    """The scaffold writes the skill and its trigger cases, and registers the entry, nothing else."""
    with tempfile.TemporaryDirectory() as tmp:
        root = _scaffold_tree(Path(tmp))
        before = _snapshot(root)
        done = _new_route(root, NEW_NAME, "--kind", "preview", "--use", "count crates on a pallet")
        require(done.returncode == 0, f"scaffold failed: {done.stderr}")
        after = _snapshot(root)
        skill, cases = f"claude-skills/{NEW_NAME}/SKILL.md", f"evals/trigger/{NEW_NAME}.cases.json"
        added = sorted(set(after) - set(before))
        require(added == [f"claude-skills/{NEW_NAME}", skill, cases], f"scaffold created {added}")
        changed = sorted(key for key in before if after.get(key) != before[key])
        require(changed == [ROSTER_RELATIVE], f"scaffold changed {changed}, expected only the roster")
        text = (root / skill).read_text(encoding="utf-8")
        require("ROUTE_" not in text, "the created skill keeps an unreplaced ROUTE_ placeholder")
        require(text.startswith(f"---\nname: {NEW_NAME}\n"), "the created skill does not name itself")
        require("Count crates on a pallet. TRIGGER when:" in text, "the created skill lacks its use text")
        payload = json.loads((root / cases).read_text(encoding="utf-8"))
        require(set(payload) == {"should_fire", "should_not_fire"}, "trigger cases lack their two lists")
        entry = _registered(root, NEW_NAME)
        require((entry.kind, entry.scorer) == (SkillKind.PREVIEW, None), f"registered {entry}")
        require(entry.use == "count crates on a pallet", f"registered use {entry.use!r}")
        require(entry.surfaces == DEFAULT_SURFACES[SkillKind.PREVIEW], "preview entry lacks its default listings")
        missing = [SURFACE_FILES[surface] for surface in entry.surfaces if SURFACE_FILES[surface] not in done.stdout]
        require(not missing, f"next steps do not name the listings {missing}")


def check_scaffold_flagship_with_chosen_listing() -> None:
    """A flagship route keeps its scorer, and a chosen listing gains the capability contract."""
    with tempfile.TemporaryDirectory() as tmp:
        root = _scaffold_tree(Path(tmp))
        args = ("--kind", "flagship", "--scorer", "count", "--surface", "readme", "--use", "count crates")
        done = _new_route(root, NEW_NAME, *args)
        require(done.returncode == 0, f"flagship scaffold failed: {done.stderr}")
        entry = _registered(root, NEW_NAME)
        require(entry.scorer == ScorerTask.COUNT, f"flagship scorer {entry.scorer}")
        require(entry.surfaces == {Surface.README, Surface.CAPABILITY_CONTRACT}, f"listings {entry.surfaces}")


#: Scaffold arguments that must be refused with exit code 2 and no write.
REFUSALS: dict[str, tuple[str, ...]] = {
    "duplicate in the roster": ("status", "--kind", "utility", "--use", "x"),
    "duplicate Claude skill folder": ("orphan-route", "--kind", "preview", "--use", "x"),
    "duplicate Codex skill folder": ("codex-orphan", "--kind", "preview", "--use", "x"),
    "duplicate trigger cases": ("cases-orphan", "--kind", "preview", "--use", "x"),
    "bad name": ("Bad_Name", "--kind", "preview", "--use", "x"),
    "unknown kind": (NEW_NAME, "--kind", "wizard", "--use", "x"),
    "flagship without a scorer": (NEW_NAME, "--kind", "flagship", "--use", "x"),
    "scorer on a utility skill": (NEW_NAME, "--kind", "utility", "--scorer", "count", "--use", "x"),
    "blank use": (NEW_NAME, "--kind", "preview", "--use", " "),
}


def check_scaffold_refusals_write_nothing() -> None:
    """Every refused request exits 2, leaves every file untouched, and keeps the roster loadable."""
    with tempfile.TemporaryDirectory() as tmp:
        root = _scaffold_tree(Path(tmp))
        (root / "claude-skills" / "orphan-route").mkdir()
        (root / "codex-skills" / "codex-orphan").mkdir(parents=True)
        (root / "evals" / "trigger" / "cases-orphan.cases.json").write_text("{}\n", encoding="utf-8")
        before = _snapshot(root)
        wrong = []
        for label, args in REFUSALS.items():
            done = _new_route(root, *args)
            if done.returncode != 2 or not done.stderr.strip() or _snapshot(root) != before:
                wrong.append(f"{label}: exit {done.returncode}")
        require(not wrong, f"scaffold did not refuse cleanly: {wrong}")
        load_roster(root / ROSTER_RELATIVE)


def _assert_rolled_back(root: Path, before: dict[str, bytes], done: subprocess.CompletedProcess[str]) -> None:
    """Require a failed scaffold to exit 2 with no partial file and the roster unchanged."""
    require(done.returncode == 2, f"a failure midway exited {done.returncode}: {done.stderr}")
    leftovers = sorted(set(_snapshot(root)) ^ set(before))
    require(not leftovers, f"a failure midway left partial files: {leftovers}")
    require(_snapshot(root) == before, "a failure midway changed an existing file")
    load_roster(root / ROSTER_RELATIVE)


def check_failure_midway_rolls_back() -> None:
    """A write that fails after the skill file exists removes it, and the roster stays unchanged."""
    with tempfile.TemporaryDirectory() as tmp:
        root = _scaffold_tree(Path(tmp), trigger_folder=False)
        before = _snapshot(root)
        _assert_rolled_back(root, before, _new_route(root, NEW_NAME, "--kind", "preview", "--use", "x"))
    if os.name == "nt" or not hasattr(os, "geteuid") or os.geteuid() == 0:
        print("     read-only roster folder case not applicable here (Windows or root)")
        return
    with tempfile.TemporaryDirectory() as tmp:
        root = _scaffold_tree(Path(tmp))
        before = _snapshot(root)
        (root / "shared").chmod(0o555)
        try:
            done = _new_route(root, NEW_NAME, "--kind", "preview", "--use", "x")
        finally:
            (root / "shared").chmod(0o755)
        _assert_rolled_back(root, before, done)


def _scan_markers(folder: Path) -> list[str]:
    """Return ``path: marker`` for every template marker left in a folder's files."""
    return [
        f"{path.relative_to(ROOT).as_posix()}: {marker}"
        for path in sorted(folder.rglob("*"))
        if path.is_file()
        for marker in LEFTOVER_MARKERS
        if marker in path.read_text(encoding="utf-8", errors="replace")
    ]


def check_shipped_skills_have_no_template_markers() -> None:
    """No shipped skill keeps template text; the template itself proves the scan can see it."""
    require(len(_scan_markers(ROOT / TEMPLATE_DIR)) >= len(LEFTOVER_MARKERS), "the marker scan misses the template")
    found = _scan_markers(ROOT / "claude-skills")
    require(not found, f"shipped skills keep template markers: {found}")


def _listing_tree(base: Path) -> Path:
    """Copy every human-facing listing file into a temporary repository."""
    root = base / "repo"
    for relative in SURFACE_FILES.values():
        target = root / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(ROOT / relative, target)
    return root


def _edit_listing(root: Path, surface: Surface, name: str, add: str | None) -> None:
    """Remove ``name`` from one listing copy, or list ``add`` right beside it."""
    path = root / SURFACE_FILES[surface]
    edited: list[str] = []
    for line in path.read_text(encoding="utf-8").splitlines(keepends=True):
        if surface == Surface.ISSUE_FORM and line.strip() == f"- {name}":
            edited += [line, line.replace(name, add)] if add else []
            continue
        if surface != Surface.ISSUE_FORM and line.lstrip().startswith(("|", "- ")) and f"`{name}`" in line:
            line = line.replace(f"`{name}`", f"`{name}`, `{add}`" if add else "")
        edited.append(line)
    text = "".join(edited)
    require(text != path.read_text(encoding="utf-8"), f"fixture edit found no {name} in {path.name}")
    path.write_text(text, encoding="utf-8")


def _problems_after(surface: Surface, add: str | None) -> list[str]:
    """Return the listing problems after one edit to one listing copy."""
    roster = load_roster()
    with tempfile.TemporaryDirectory() as tmp:
        root = _listing_tree(Path(tmp))
        require(roster_listing_problems(root, roster) == [], "the unedited listing copy already fails")
        _edit_listing(root, surface, LISTED_EVERYWHERE, add)
        return roster_listing_problems(root, roster)


def check_listing_drift_is_caught() -> None:
    """The repository passes; a missing name and a stale name each fail on exactly one listing."""
    roster = load_roster()
    problems = roster_listing_problems(ROOT, roster)
    require(not problems, f"the repository listings disagree with the roster: {problems}")
    wrong: list[str] = []
    for surface in Surface:
        require(LISTED_EVERYWHERE in roster.on_surface(surface), f"{LISTED_EVERYWHERE} is not on {surface.value}")
        where = SURFACE_FILES[surface]
        missing = _problems_after(surface, None)
        if missing != [f"{where}: missing {LISTED_EVERYWHERE}"]:
            wrong.append(f"missing on {surface.value}: {missing}")
        stale = _problems_after(surface, GHOST)
        if stale != [f"{where}: stale {GHOST} (not in the roster)"]:
            wrong.append(f"stale on {surface.value}: {stale}")
    misplaced = _problems_after(Surface.LLMS, "auth-setup")
    if f"{SURFACE_FILES[Surface.LLMS]}: stale auth-setup (the roster does not list it on llms)" not in misplaced:
        wrong.append(f"roster skill on a listing the roster does not name: {misplaced}")
    require(not wrong, "listing drift not reported as expected:\n  " + "\n  ".join(wrong))


def check_router_table_names_every_build_route() -> None:
    """The router's route table lists every flagship and preview route, and nothing the roster lacks."""
    roster = load_roster()
    router = (ROOT / ROUTER_RELATIVE).read_text(encoding="utf-8")
    listed = router_table_routes(router)
    require(len(listed) >= len(roster.build_routes()), f"the route table parser found only {listed}")
    require(router_problems(roster, router) == [], f"router and roster disagree: {router_problems(roster, router)}")
    dropped = "\n".join(line for line in router.splitlines() if f"`{LISTED_EVERYWHERE}`" not in line)
    require(
        router_problems(roster, dropped)
        == [f"{ROUTER_RELATIVE}: route table is missing the build route {LISTED_EVERYWHERE}"],
        f"a build route missing from the route table was not reported: {router_problems(roster, dropped)}",
    )
    ghost = router.replace(f"`{LISTED_EVERYWHERE}`", f"`{GHOST}`", 1)
    require(
        f"{ROUTER_RELATIVE}: route table names {GHOST}, which is not in the roster" in router_problems(roster, ghost),
        f"a route table name the roster lacks was not reported: {router_problems(roster, ghost)}",
    )


CHECKS: tuple[Callable[[], None], ...] = (
    check_router_table_names_every_build_route,
    check_schema_negative_controls,
    check_committed_roster_round_trips,
    check_scaffold_creates_and_registers,
    check_scaffold_flagship_with_chosen_listing,
    check_scaffold_refusals_write_nothing,
    check_failure_midway_rolls_back,
    check_shipped_skills_have_no_template_markers,
    check_listing_drift_is_caught,
)


def main() -> int:
    """Run every roster check and return 1 when any fails."""
    failed = 0
    for check in CHECKS:
        try:
            check()
        except (AssertionError, RosterError) as exc:
            failed += 1
            print(f"FAIL {check.__name__}: {exc}")
        else:
            print(f"ok   {check.__name__}")
    print(f"roster checks: {len(CHECKS) - failed} passed, {failed} failed")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
