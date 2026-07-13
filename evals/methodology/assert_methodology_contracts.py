#!/usr/bin/env python3
"""Assert Sentinel's acceptance, routing, and provenance contracts."""

from __future__ import annotations

import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SKILLS = ROOT / "skills"
RESOURCES = ROOT / "resources"
BUILD_SKILLS = (
    "classify-or-flag",
    "decompose-to-pipeline",
    "detect-and-analyze",
    "read-text",
    "recognize-pose-or-gesture",
    "segment-and-analyze",
    "track-and-count",
)
MODALITY_SKILLS = tuple(
    name for name in BUILD_SKILLS if name != "decompose-to-pipeline"
)


def read(path: Path) -> str:
    """Read one required repository file as UTF-8."""
    if not path.is_file():
        raise AssertionError(f"Missing required file: {path.relative_to(ROOT)}")
    return path.read_text(encoding="utf-8")


def require(text: str, needle: str, path: Path) -> None:
    """Require an exact contract phrase in a file."""
    if needle not in text:
        raise AssertionError(f"{path.relative_to(ROOT)} is missing {needle!r}")


def reject(text: str, pattern: str, path: Path) -> None:
    """Reject a regular-expression pattern from a file."""
    if re.search(pattern, text, flags=re.IGNORECASE):
        raise AssertionError(
            f"{path.relative_to(ROOT)} contains forbidden pattern {pattern!r}"
        )


def assert_independent_acceptance() -> None:
    """Require pseudo-labels to remain bootstrap-only and independently checked."""
    fde_path = RESOURCES / "fde-methodology.md"
    decompose_path = SKILLS / "decompose-to-pipeline" / "SKILL.md"
    for path in (fde_path, decompose_path):
        text = read(path)
        require(text, "independent acceptance", path)
        require(text, "blinded human", path)
        require(text, "pseudo-label", path)
        reject(text, r"LLM as oracle", path)
        reject(text, r"no CV model can", path)
        reject(text, r"replaces human annotation for the eval", path)


def assert_immutable_thresholds() -> None:
    """Require acceptance thresholds to be frozen before baseline measurement."""
    fde_path = RESOURCES / "fde-methodology.md"
    fde = read(fde_path)
    for phrase in (
        "acceptance_id",
        "frozen before any baseline",
        "baseline is diagnostic evidence",
        "new revision",
    ):
        require(fde, phrase, fde_path)

    for name in MODALITY_SKILLS:
        path = SKILLS / name / "SKILL.md"
        text = read(path)
        require(text, "Acceptance ID:", path)
        require(text, "Frozen before baseline:", path)
        require(text, "Baseline result (diagnostic only):", path)
        reject(text, r"Threshold logic:\s*max\(", path)

    baseline_path = ROOT / "scripts" / "baseline_map.py"
    baseline = read(baseline_path)
    require(baseline, "acceptance_map50", baseline_path)
    require(baseline, "baseline_gap", baseline_path)
    reject(baseline, r"threshold\s*=\s*max\(", baseline_path)


def assert_routing_and_delegation() -> None:
    """Require output-schema routing and upstream platform delegation."""
    lookup_path = RESOURCES / "roboflow-platform-lookup.md"
    lookup = read(lookup_path)
    for phrase in (
        "Platform action handshake",
        "Delegate exact execution",
        "fallback is scaffold-only",
    ):
        require(lookup, phrase, lookup_path)

    for name in BUILD_SKILLS:
        path = SKILLS / name / "SKILL.md"
        text = read(path)
        require(text, "Platform execution boundary", path)
        require(text, "../../resources/roboflow-platform-lookup.md", path)

    solver_path = SKILLS / "solve-cv-task" / "SKILL.md"
    solver = read(solver_path)
    for phrase in (
        "per-person PPE",
        "whole-image compliance",
        "calibrated physical measurement",
        "deliver-cv-project",
    ):
        require(solver, phrase, solver_path)

    detect_path = SKILLS / "detect-and-analyze" / "SKILL.md"
    reject(read(detect_path), r"measure-in-image", detect_path)

    classify_path = SKILLS / "classify-or-flag" / "SKILL.md"
    classify = read(classify_path)
    require(classify, "one verdict for the whole image", classify_path)
    require(classify, "per-person PPE", classify_path)


def assert_skill_surface_and_ledger() -> None:
    """Require only user workflows to be discoverable and ledger ownership to be unique."""
    internal_dir = SKILLS / "_shared"
    if internal_dir.exists():
        raise AssertionError(
            "skills/_shared exposes internal resources in the skill root"
        )

    delivery_path = SKILLS / "deliver-cv-project" / "SKILL.md"
    delivery = read(delivery_path)
    for phrase in (
        "TRIGGER when:",
        "SKIP when:",
        "delivery-handoff",
        "acceptance_id",
        "artifact_kind",
    ):
        require(delivery, phrase, delivery_path)

    ledger_path = RESOURCES / "ledger-protocol.md"
    ledger = read(ledger_path)
    for phrase in (
        '"event_id"',
        '"status"',
        '"source"',
        "hook-covered MCP actions",
        "Unknown is never success",
        "absolute path of this loaded file",
        "--ledger",
    ):
        require(ledger, phrase, ledger_path)


def main() -> int:
    """Run all methodology assertions and return a shell status."""
    checks = (
        assert_independent_acceptance,
        assert_immutable_thresholds,
        assert_routing_and_delegation,
        assert_skill_surface_and_ledger,
    )
    for check in checks:
        check()
        print(f"PASS {check.__name__}")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except AssertionError as exc:
        print(f"methodology contract failed: {exc}", file=sys.stderr)
        raise SystemExit(1) from exc
