#!/usr/bin/env python3
"""Trigger-eval runner for vision-delivery skills — STRUCTURAL proxy.

Checks that a skill's YAML frontmatter `description` field DECLARES the right
trigger surface (TRIGGER/SKIP clauses) to cover each labeled test case. Does NOT
call an LLM or verify that the model actually fires — that requires a live eval.

TODO(M-later): live-judged trigger eval — feed cases to a real session and assert
the correct skill fires (or doesn't). This structural check is a fast, deterministic
CI gate; the live check is the faithful one.

Exit codes: 0 = all cases covered, 1 = one or more cases uncovered.

Usage:
    python3 evals/trigger/run.py                    # all skills
    python3 evals/trigger/run.py detect-and-analyze  # one skill
"""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path

import yaml

ROOT = Path(__file__).parent.parent.parent
EVALS_DIR = Path(__file__).parent

STOP = frozenset(
    "the and or in on of a an to from for with my this me i is it are was "
    "how can do what have has need want build just tell give help already".split()
)


def parse_description(skill_path: Path) -> str:
    raw = skill_path.read_text(encoding="utf-8")
    m = re.match(r"^---\n([\s\S]+?)\n---", raw)
    if not m:
        return ""
    fm = yaml.safe_load(m.group(1))
    return str(fm.get("description", ""))


def extract_clauses(description: str) -> tuple[str, str]:
    desc = description.lower()
    trigger_m = re.search(r"trigger when:\s*([\s\S]+?)(?=\s*skip when:|$)", desc)
    skip_m = re.search(r"skip when:\s*([\s\S]+?)$", desc)
    return (trigger_m.group(1) if trigger_m else ""), (
        skip_m.group(1) if skip_m else ""
    )


def keywords(prompt: str) -> list[str]:
    tokens = re.split(r"[^a-z]+", prompt.lower())
    return [t for t in tokens if len(t) >= 3 and t not in STOP]


def is_covered(kws: list[str], clause: str) -> bool:
    return any(kw in clause for kw in kws)


def run_skill(skill_name: str) -> bool:
    skill_path = ROOT / "skills" / skill_name / "SKILL.md"
    cases_path = EVALS_DIR / f"{skill_name}.cases.json"

    if not skill_path.exists():
        print(f"  ✗ SKILL.md not found: {skill_path}", file=sys.stderr)
        return False
    if not cases_path.exists():
        print(f"  ✗ cases file not found: {cases_path}", file=sys.stderr)
        return False

    description = parse_description(skill_path)
    if not description:
        print(f"  ✗ No description in frontmatter for {skill_name}", file=sys.stderr)
        return False

    trigger, skip = extract_clauses(description)
    cases = json.loads(cases_path.read_text(encoding="utf-8"))

    rows = []
    passed = failed = 0

    for c in cases.get("should_fire", []):
        kws = keywords(c["prompt"])
        covered = is_covered(kws, trigger)
        rows.append(("should_fire", c["prompt"][:60], covered, kws[:4]))
        if covered:
            passed += 1
        else:
            failed += 1

    for c in cases.get("should_not_fire", []):
        kws = keywords(c["prompt"])
        covered = is_covered(kws, skip)
        rows.append(("should_not_fire", c["prompt"][:60], covered, kws[:4]))
        if covered:
            passed += 1
        else:
            failed += 1

    print(f"\nSkill: {skill_name}")
    print(f"{'TYPE':<16} {'OK':<8} PROMPT")
    print("─" * 80)
    for typ, prompt, covered, kws in rows:
        icon = "✓" if covered else "✗"
        hint = "" if covered else f"  ← keywords: [{', '.join(kws)}]"
        print(f"{typ:<16} {icon:<8} {prompt}{hint}")
    print(f"\n  {passed} passed, {failed} failed")

    return failed == 0


def main() -> None:
    arg = sys.argv[1] if len(sys.argv) > 1 else None
    if arg:
        skill_names = [arg]
    else:
        skill_names = sorted(
            p.stem.replace(".cases", "") for p in EVALS_DIR.glob("*.cases.json")
        )

    all_passed = True
    for name in skill_names:
        if not run_skill(name):
            all_passed = False

    if not all_passed:
        print(
            "\n✗ One or more skills have uncovered trigger cases — update SKILL.md description.",
            file=sys.stderr,
        )
        sys.exit(1)

    print("\n✓ All trigger cases covered structurally.")


if __name__ == "__main__":
    main()
