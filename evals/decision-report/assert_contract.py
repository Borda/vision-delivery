#!/usr/bin/env python3
"""Assert the stakeholder-report skill retains its decision-grade contract."""

from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).parents[2]
SKILL = ROOT / "skills" / "decision-report" / "SKILL.md"


def main() -> int:
    """Check required options, provenance, helper portability, and ledger outcome."""
    text = SKILL.read_text(encoding="utf-8")
    required = (
        "Option A: Managed deployment",
        "Option B: Self-host / DIY",
        "Option C: Do nothing / defer",
        "[source: <URL>, as_of: <YYYY-MM-DD>]",
        "<plugin-root>/scripts/cost_model.py",
        '"status": "success"',
        '"source": "skill"',
    )
    missing = [needle for needle in required if needle not in text]
    if missing:
        raise AssertionError(f"decision-report contract is missing: {missing}")
    if re.search(r"(?:python|python3) scripts/cost_model\.py", text):
        raise AssertionError("decision-report uses a user-CWD-relative helper path")
    if '"version": "0.1.0"' in text:
        raise AssertionError("decision-report ledger schema is stale")
    print("decision-report contract assertions passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
