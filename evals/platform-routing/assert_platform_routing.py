#!/usr/bin/env python3
"""Assert Roboflow platform lookups stay thin and source-backed."""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).parent.parent.parent
CASES = Path(__file__).with_name("cases.json")
LOOKUP = ROOT / "skills" / "_shared" / "roboflow-platform-lookup.md"
SOLVER = ROOT / "skills" / "solve-cv-task" / "SKILL.md"
MODEL_SELECTION = ROOT / "skills" / "_shared" / "model-selection.md"
DOCS = ROOT / "docs" / "roboflow-skills.md"


def read(path: Path) -> str:
    if not path.exists():
        raise AssertionError(f"Missing required file: {path}")
    return path.read_text(encoding="utf-8")


def assert_contains(text: str, needle: str, path: Path) -> None:
    if needle not in text:
        raise AssertionError(f"{path} is missing `{needle}`")


STALE_COMMAND_PATTERNS = [
    "/vision-delivery:",  # pre-rename namespace
    "/sentinel:estimate\u0060",  # bare /sentinel:estimate` — verified Unknown command 2026-07-10; use /sentinel:estimate-economics
]


def assert_no_stale_commands() -> None:
    """Fail when docs/skills/agents reference a slash command that does not resolve.

    Examples:
        >>> assert_no_stale_commands()
    """
    import pathlib

    repo = pathlib.Path(__file__).resolve().parents[2]
    scopes = ["skills", "agents", "docs", "README.md"]
    for scope in scopes:
        p = repo / scope
        files = [p] if p.is_file() else list(p.rglob("*.md"))
        for f in files:
            text = f.read_text(encoding="utf-8")
            for pat in STALE_COMMAND_PATTERNS:
                needle = pat.encode().decode("unicode_escape")
                if needle in text:
                    raise AssertionError(
                        f"{f} contains stale command reference {needle!r}"
                    )


def main() -> None:
    lookup = read(LOOKUP)
    solver = read(SOLVER)
    model_selection = read(MODEL_SELECTION)
    docs = read(DOCS)
    cases = json.loads(CASES.read_text(encoding="utf-8"))["platform_routes"]

    for phrase in (
        "Local Roboflow skill",
        "Roboflow MCP skill resource",
        "Minimal `vision-delivery` fallback",
        "Do not copy large Roboflow platform recipes",
        "Return to the `vision-delivery` eval gate",
    ):
        assert_contains(lookup, phrase, LOOKUP)

    for case in cases:
        assert_contains(lookup, case["local_skill"], LOOKUP)
        assert_contains(lookup, case["mcp_resource"], LOOKUP)
        assert_contains(docs, case["local_skill"], DOCS)
        assert_contains(docs, case["mcp_resource"], DOCS)
        for tool in case["mcp_tools"]:
            assert_contains(lookup, tool, LOOKUP)

    assert_contains(solver, "roboflow-platform-lookup.md", SOLVER)
    assert_contains(solver, "Roboflow platform knowledge lookup", SOLVER)
    assert_contains(model_selection, "stable fallback only", MODEL_SELECTION)
    assert_contains(
        model_selection,
        "Validate volatile model IDs before `trainings_create`",
        MODEL_SELECTION,
    )
    assert_contains(docs, "Direct unauthenticated probing", DOCS)
    assert_contains(docs, "OAuth-protected-resource challenge", DOCS)
    assert_no_stale_commands()

    model_ids = re.findall(
        r"`(?:rf|yolo|sam|vit|resnet|deeplab)[^`]+`", model_selection
    )
    if (
        len(model_ids) > 45
    ):  # raised from 30 on 2026-07-09: seg/pose/classification IDs verified + pinned (H-05)
        raise AssertionError(
            "model-selection fallback has too many exact platform IDs; "
            "prefer Roboflow skills/MCP resources over expanding local copies"
        )

    print("Roboflow platform routing stays thin and source-backed.")


if __name__ == "__main__":
    try:
        main()
    except AssertionError as exc:
        print(f"platform-routing assertion failed: {exc}", file=sys.stderr)
        sys.exit(1)
