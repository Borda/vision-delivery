#!/usr/bin/env python3
"""Assert Claude entry agents remain thin adapters over canonical skills."""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

import yaml

ROOT = Path(__file__).parent.parent.parent
ENTRYPOINTS = {
    "cv-problem-solver": "solve-cv-task",
    "economics-consultant": "estimate-economics",
}


def frontmatter(path: Path) -> tuple[dict[str, Any], str]:
    raw = path.read_text(encoding="utf-8")
    match = re.match(r"^---\n([\s\S]+?)\n---\n([\s\S]*)$", raw)
    if match is None:
        raise AssertionError(f"{path} must start with YAML frontmatter")
    payload = yaml.safe_load(match.group(1))
    if not isinstance(payload, dict):
        raise AssertionError(f"{path} frontmatter must be a YAML object")
    return payload, match.group(2)


def normalize(value: object) -> str:
    return " ".join(str(value).split())


def clause(description: object, label: str) -> str:
    text = normalize(description).lower()
    match = re.search(rf"{label} when:\s*([\s\S]+?)(?=\s*(trigger|skip) when:|$)", text)
    if match is None:
        raise AssertionError(f"description is missing `{label} when:`")
    return match.group(1)


def main() -> None:
    for agent_name, skill_name in ENTRYPOINTS.items():
        agent_path = ROOT / "agents" / f"{agent_name}.md"
        skill_path = ROOT / "skills" / skill_name / "SKILL.md"

        agent_meta, agent_body = frontmatter(agent_path)
        skill_meta, skill_body = frontmatter(skill_path)

        assert agent_meta.get("name") == agent_name
        assert skill_meta.get("name") == skill_name
        for label in ("trigger", "skip"):
            agent_clause = clause(agent_meta.get("description"), label)
            skill_clause = clause(skill_meta.get("description"), label)
            for token in ("detect", "count", "cost", "deploy"):
                assert (token in agent_clause) == (token in skill_clause), (
                    f"{agent_path} `{label}` surface drifted from {skill_path}: {token}"
                )
        for field in ("tools", "model", "color"):
            assert field in agent_meta, f"{agent_path} is missing Claude `{field}`"
        assert "allowed-tools" in skill_meta, f"{skill_path} is missing Codex tools"
        assert str(skill_path.relative_to(ROOT)) in agent_body, (
            f"{agent_path} must point to the canonical skill"
        )
        for banned in ("<classification>", "<methodology>", "<cost_model_rules>"):
            assert banned not in agent_body, (
                f"{agent_path} contains workflow logic marker `{banned}`"
            )
        assert len(agent_body.splitlines()) <= 30, f"{agent_path} is no longer thin"
        assert len(skill_body.splitlines()) > len(agent_body.splitlines()), (
            f"{skill_path} should own the methodology"
        )

    print("Claude entry agents are thin adapters over canonical skills.")


if __name__ == "__main__":
    main()
