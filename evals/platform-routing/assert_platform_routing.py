#!/usr/bin/env python3
"""Assert Roboflow platform lookups stay thin and source-backed."""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).parent.parent.parent
CASES = Path(__file__).with_name("cases.json")
LOOKUP = ROOT / "resources" / "roboflow-platform-lookup.md"
SOLVER = ROOT / "skills" / "solve-cv-task" / "SKILL.md"
MODEL_SELECTION = ROOT / "resources" / "model-selection.md"


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
    cases = json.loads(CASES.read_text(encoding="utf-8"))["platform_routes"]

    for phrase in (
        "official `roboflow/computer-vision-skills` skill",
        "matching `roboflow://skills/...` MCP resource",
        "local provider-neutral scaffold",
        "Do not copy Roboflow platform recipes into Sentinel",
        "Return to the Sentinel acceptance/delivery workflow",
    ):
        assert_contains(lookup, phrase, LOOKUP)

    for case in cases:
        assert_contains(lookup, case["local_skill"], LOOKUP)
        assert_contains(lookup, case["mcp_resource"], LOOKUP)

    assert_contains(solver, "roboflow-platform-lookup.md", SOLVER)
    assert_contains(solver, "Roboflow platform knowledge lookup", SOLVER)
    assert_contains(model_selection, "stable fallback only", MODEL_SELECTION)
    assert_contains(
        model_selection,
        "Validate every volatile model identifier and paid-training operation",
        MODEL_SELECTION,
    )
    assert_no_stale_commands()

    model_ids = re.findall(
        r"`(?:rf|yolo|sam|vit|resnet|deeplab)[^`]+`", model_selection
    )
    if model_ids:
        raise AssertionError(
            "model-selection fallback copies exact platform IDs; "
            "delegate the current catalog upstream"
        )

    active_paths = [*sorted((ROOT / "skills").glob("*/SKILL.md"))]
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
    )
    for path in active_paths:
        text = read(path)
        for pattern in forbidden:
            if re.search(pattern, text):
                raise AssertionError(
                    f"{path.relative_to(ROOT)} duplicates volatile upstream recipe "
                    f"pattern {pattern!r}"
                )

    print("Roboflow platform routing stays thin and source-backed.")


if __name__ == "__main__":
    try:
        main()
    except AssertionError as exc:
        print(f"platform-routing assertion failed: {exc}", file=sys.stderr)
        sys.exit(1)
