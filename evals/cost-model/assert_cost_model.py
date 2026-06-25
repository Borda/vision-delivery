#!/usr/bin/env python3
"""CI assertion: cost_model.py DIY branch reachable + source citations present.

Runs both fixture inputs and asserts:
1. diy-wins.json → recommendation == "diy"
2. managed-wins.json → recommendation == "managed"
3. Every dollar line in text output carries [source: ..., as_of: YYYY-MM-DD]

Usage:
    python3 evals/cost-model/assert_cost_model.py
    echo $?  # 0 = pass, 1 = fail
"""
from __future__ import annotations

import json
import re
import subprocess
import sys
from pathlib import Path

FIXTURES_DIR = Path(__file__).parent / "fixtures"
SCRIPT = Path(__file__).parent.parent.parent / "scripts" / "cost_model.py"

# Matches lines like ~$123/mo  [source: ..., as_of: 2026-06-25]
SOURCE_PATTERN = re.compile(r"\[source: .+, as_of: \d{4}-\d{2}-\d{2}\]")
DOLLAR_LINE_PATTERN = re.compile(r"~\$[\d,]+")


def run_json(args: list[str]) -> dict:
    result = subprocess.run(
        [sys.executable, str(SCRIPT)] + args + ["--json"],
        capture_output=True, text=True,
    )
    if result.returncode != 0:
        raise AssertionError(f"cost_model.py exited {result.returncode}:\n{result.stderr}")
    return json.loads(result.stdout)


def run_text(args: list[str]) -> str:
    result = subprocess.run(
        [sys.executable, str(SCRIPT)] + args,
        capture_output=True, text=True,
    )
    if result.returncode != 0:
        raise AssertionError(f"cost_model.py exited {result.returncode}:\n{result.stderr}")
    return result.stdout


def assert_source_citations(text: str, fixture_name: str) -> None:
    """Every sourced line containing ~$... must also contain [source: ..., as_of: ...].

    Derived totals (Total run-rate, Crossover) are exempt — their inputs already carry sources.
    """
    # Lines that aggregate sourced inputs; no independent source needed.
    EXEMPT_PREFIXES = ("Total run-rate:", "Crossover:", "Scaling cliff:")
    failures = []
    for i, line in enumerate(text.splitlines(), 1):
        stripped = line.strip()
        if any(stripped.startswith(p) for p in EXEMPT_PREFIXES):
            continue
        if DOLLAR_LINE_PATTERN.search(line) and not SOURCE_PATTERN.search(line):
            failures.append(f"  line {i}: {stripped}")
    if failures:
        raise AssertionError(
            f"[{fixture_name}] Lines with dollar amounts but no source citation:\n"
            + "\n".join(failures)
        )


def main() -> int:
    failures: list[str] = []

    for fixture_path in sorted(FIXTURES_DIR.glob("*.json")):
        fixture = json.loads(fixture_path.read_text())
        name = fixture_path.stem
        args = fixture["args"]
        expected = fixture["expect_recommendation"]

        try:
            data = run_json(args)
            actual = data["recommendation"]
            if actual != expected:
                failures.append(
                    f"[{name}] recommendation: expected '{expected}', got '{actual}'\n"
                    f"  reason: {data.get('reason', '?')}"
                )
            else:
                print(f"  PASS [{name}] recommendation={actual}")
        except AssertionError as exc:
            failures.append(f"[{name}] JSON run failed: {exc}")
            continue

        try:
            text = run_text(args)
            assert_source_citations(text, name)
            print(f"  PASS [{name}] source citations present")
        except AssertionError as exc:
            failures.append(str(exc))

    if failures:
        print("\nFAIL:")
        for f in failures:
            print(f"  {f}")
        return 1

    print("\nAll assertions passed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
