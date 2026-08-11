#!/usr/bin/env python3
"""Assert dual-host Sentinel skill trees preserve the shared capability contract."""

from __future__ import annotations

import re
import sys
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[2]
CODEX_SKILLS = ROOT / "codex-skills"
CLAUDE_SKILLS = ROOT / "claude-skills"
CONTRACT = ROOT / "shared" / "capability-contract.md"
EXPECTED_ROSTER = {
    "auth-setup",
    "check-sentinel-setup",
    "classify-or-flag",
    "decision-report",
    "decompose-to-pipeline",
    "deliver-cv-project",
    "detect-and-analyze",
    "estimate-economics",
    "read-text",
    "recognize-pose-or-gesture",
    "segment-and-analyze",
    "solve-cv-task",
    "track-and-count",
}


def parse_frontmatter(path: Path) -> tuple[dict[str, object], str]:
    """Return YAML metadata and body from one required skill file."""
    raw = path.read_text(encoding="utf-8")
    match = re.match(r"^---\n([\s\S]+?)\n---\n([\s\S]*)$", raw)
    if match is None:
        raise AssertionError(f"{path.relative_to(ROOT)} must have YAML frontmatter")
    metadata = yaml.safe_load(match.group(1))
    if not isinstance(metadata, dict):
        raise AssertionError(f"{path.relative_to(ROOT)} metadata must be an object")
    return metadata, match.group(2)


def roster(root: Path) -> set[str]:
    """Return the discoverable skill names for one host root."""
    return {path.parent.name for path in root.glob("*/SKILL.md")}


def assert_skill_rosters() -> None:
    """Require exactly the frozen thirteen-name roster on both hosts."""
    codex_roster = roster(CODEX_SKILLS)
    claude_roster = roster(CLAUDE_SKILLS)
    assert codex_roster == EXPECTED_ROSTER, f"Codex roster drifted: {sorted(codex_roster)}"
    assert claude_roster == EXPECTED_ROSTER, f"Claude roster drifted: {sorted(claude_roster)}"


def assert_host_metadata() -> None:
    """Require documented Codex metadata and preserve Claude's tool declarations."""
    for name in sorted(EXPECTED_ROSTER):
        codex_path = CODEX_SKILLS / name / "SKILL.md"
        claude_path = CLAUDE_SKILLS / name / "SKILL.md"
        codex_metadata, codex_body = parse_frontmatter(codex_path)
        claude_metadata, _ = parse_frontmatter(claude_path)
        assert set(codex_metadata) == {"name", "description"}, (
            f"{codex_path.relative_to(ROOT)} has unsupported Codex metadata"
        )
        assert codex_metadata.get("name") == name
        assert claude_metadata.get("name") == name
        assert "allowed-tools" not in codex_metadata
        assert "AskUserQuestion" not in codex_body
        assert "CLAUDE_PLUGIN_" not in codex_body
        assert "/sentinel:" not in str(codex_metadata.get("description", ""))
        if name == "estimate-economics":
            assert "$estimate-economics" in str(codex_metadata.get("description", ""))
            assert "/sentinel:estimate-economics" in str(claude_metadata.get("description", ""))


def assert_shared_contract() -> None:
    """Require the host-neutral contract and Codex MCP dependency declarations."""
    text = CONTRACT.read_text(encoding="utf-8")
    for name in EXPECTED_ROSTER:
        assert f"`{name}`" in text, f"contract omits {name}"
    for phrase in (
        "MCP and authentication boundary",
        "Acceptance and artifact boundary",
        "Allowed host differences",
    ):
        assert phrase in text, f"contract omits {phrase}"

    auth_metadata = CODEX_SKILLS / "auth-setup" / "agents" / "openai.yaml"
    setup_metadata = CODEX_SKILLS / "check-sentinel-setup" / "agents" / "openai.yaml"
    assert auth_metadata.is_file(), "Codex auth setup MCP metadata is missing"
    assert setup_metadata.is_file(), "Codex setup metadata is missing"
    assert not (CLAUDE_SKILLS / "check-sentinel-setup" / "agents" / "openai.yaml").exists()
    assert "roboflow" in auth_metadata.read_text(encoding="utf-8")
    assert "dependencies" in auth_metadata.read_text(encoding="utf-8")


def assert_shared_workflow_gates() -> None:
    """Require routing and delivery safety gates on both host adapters."""
    for name in sorted(EXPECTED_ROSTER):
        for skills_root in (CODEX_SKILLS, CLAUDE_SKILLS):
            path = skills_root / name / "SKILL.md"
            metadata, body = parse_frontmatter(path)
            description = str(metadata.get("description", ""))
            assert "TRIGGER when:" in description, f"{path} lacks trigger routing"
            assert "SKIP when:" in description, f"{path} lacks skip routing"
            assert body.strip(), f"{path} lacks workflow instructions"

    for name in (
        "classify-or-flag",
        "detect-and-analyze",
        "read-text",
        "recognize-pose-or-gesture",
        "segment-and-analyze",
        "track-and-count",
    ):
        for skills_root in (CODEX_SKILLS, CLAUDE_SKILLS):
            path = skills_root / name / "SKILL.md"
            body = parse_frontmatter(path)[1]
            assert "Acceptance ID:" in body, f"{path} lacks frozen acceptance"
            assert "artifact-contract.md" in body, f"{path} lacks artifact gate"


def main() -> int:
    """Run the dual-host semantic parity assertions."""
    try:
        assert_skill_rosters()
        assert_host_metadata()
        assert_shared_contract()
        assert_shared_workflow_gates()
    except (AssertionError, OSError, yaml.YAMLError) as exc:
        print(f"skill parity failed: {exc}", file=sys.stderr)
        return 1
    print("dual-host skill parity assertions passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
