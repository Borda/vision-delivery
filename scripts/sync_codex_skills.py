#!/usr/bin/env python3
"""Generate the Codex skill tree from the canonical Claude skill tree.

`claude-skills/` is the single source. Codex differs only in frontmatter
(no `allowed-tools`, no `/sentinel:` slash aliases, block-strip description)
plus explicit host-specific line overrides in `shared/codex-overrides.json`.
Codex-only files such as `agents/openai.yaml` are left untouched.

Usage:
    python scripts/sync_codex_skills.py          # rewrite codex-skills/*/SKILL.md
    python scripts/sync_codex_skills.py --check  # fail when the committed tree drifted
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CLAUDE_SKILLS = ROOT / "claude-skills"
CODEX_SKILLS = ROOT / "codex-skills"
OVERRIDES = ROOT / "shared" / "codex-overrides.json"
FRONTMATTER = re.compile(r"^---\n([\s\S]+?)\n---\n")
SLASH_ALIAS = re.compile(r" or `/sentinel:[a-z-]+`")


def load_overrides() -> dict[str, list[list[str]]]:
    """Return per-skill exact line replacements for host-specific wording.

    Examples:
        >>> isinstance(load_overrides(), dict)
        True
    """
    payload = json.loads(OVERRIDES.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError(f"{OVERRIDES.name} must be a JSON object")
    return payload


def codex_frontmatter(block: str) -> str:
    """Convert Claude skill metadata into the Codex-supported subset.

    Examples:
        >>> codex_frontmatter("name: x\\ndescription: |\\n  Run `$x` or `/sentinel:x`.\\nallowed-tools: Read")
        'name: x\\ndescription: |-\\n  Run `$x`.'
    """
    lines = [line for line in block.split("\n") if not line.startswith("allowed-tools:")]
    text = "\n".join(lines).replace("description: |\n", "description: |-\n")
    return SLASH_ALIAS.sub("", text)


def render(name: str, source: str, overrides: dict[str, list[list[str]]]) -> str:
    """Render one Codex SKILL.md from its Claude source.

    Examples:
        >>> render("x", "---\\nname: x\\nallowed-tools: Read\\n---\\nbody\\n", {})
        '---\\nname: x\\n---\\nbody\\n'
    """
    match = FRONTMATTER.match(source)
    if match is None:
        raise ValueError(f"{name}: missing YAML frontmatter")
    body = source[match.end() :]
    for old, new in overrides.get(name, []):
        if body.count(old) != 1:
            raise ValueError(f"{name}: override source must appear exactly once: {old!r}")
        body = body.replace(old, new)
    return f"---\n{codex_frontmatter(match.group(1))}\n---\n{body}"


def main() -> int:
    """Write or check every generated Codex skill file."""
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--check", action="store_true", help="report drift without writing")
    args = parser.parse_args()
    overrides = load_overrides()
    unknown = set(overrides) - {path.parent.name for path in CLAUDE_SKILLS.glob("*/SKILL.md")}
    if unknown:
        print(f"overrides name unknown skills: {sorted(unknown)}", file=sys.stderr)
        return 1
    drifted = []
    for source_path in sorted(CLAUDE_SKILLS.glob("*/SKILL.md")):
        name = source_path.parent.name
        expected = render(name, source_path.read_text(encoding="utf-8"), overrides)
        target = CODEX_SKILLS / name / "SKILL.md"
        current = target.read_text(encoding="utf-8") if target.exists() else None
        if current == expected:
            continue
        drifted.append(name)
        if not args.check:
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(expected, encoding="utf-8", newline="\n")
    if args.check and drifted:
        print(f"codex-skills drifted from claude-skills: {drifted}; run scripts/sync_codex_skills.py", file=sys.stderr)
        return 1
    print(f"codex skills {'checked' if args.check else 'synced'}; changed: {drifted or 'none'}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
