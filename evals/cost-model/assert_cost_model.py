#!/usr/bin/env python3
"""CI assertion: cost_model.py honesty gates.

Asserts, in order:
1. Fixtures: diy-wins → "diy" (real quote), managed-wins → "managed" (real
   quote), abstain-default → "insufficient-data" (no quote — the model must
   never convert the Core plan floor into a verdict).
2. Every dollar line in text output carries [source: ..., as_of: YYYY-MM-DD].
3. Snapshot staleness canary: PRICING_SNAPSHOT.json `as_of` must be younger
   than MAX_SNAPSHOT_AGE_DAYS (override with ALLOW_STALE_SNAPSHOT=1).
4. Monotonicity properties over a streams sweep (fixed real quote):
   DIY total and instance count non-decreasing, scaling-cliff increment >= 0,
   crossover_months >= 0 when present.
5. Abstention sweep: without a quote, no point in the sweep may emit a
   diy/managed verdict.

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
SNAPSHOT = Path(__file__).parent.parent.parent / "scripts" / "PRICING_SNAPSHOT.json"
MAX_SNAPSHOT_AGE_DAYS = 90
SWEEP_STREAMS = [1, 2, 3, 4, 5, 8, 12, 20, 40, 80, 200]

# Matches lines like ~$123/mo  [source: ..., as_of: 2026-06-25]
SOURCE_PATTERN = re.compile(r"\[source: .+, as_of: \d{4}-\d{2}-\d{2}\]")
DOLLAR_LINE_PATTERN = re.compile(r"~\$[\d,]+")


def run_json(args: list[str]) -> dict:
    result = subprocess.run(
        [sys.executable, str(SCRIPT)] + args + ["--json"],
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        raise AssertionError(
            f"cost_model.py exited {result.returncode}:\n{result.stderr}"
        )
    return json.loads(result.stdout)


def run_text(args: list[str]) -> str:
    result = subprocess.run(
        [sys.executable, str(SCRIPT)] + args,
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        raise AssertionError(
            f"cost_model.py exited {result.returncode}:\n{result.stderr}"
        )
    return result.stdout


def assert_source_citations(text: str, fixture_name: str) -> None:
    """Every sourced line containing ~$... must also contain [source: ..., as_of: ...].

    Derived totals (Total run-rate, Crossover) are exempt — their inputs already carry sources.
    """
    # Lines that aggregate sourced inputs; no independent source needed.
    EXEMPT_PREFIXES = (
        "Total run-rate:",
        "Crossover:",
        "Scaling cliff:",
        "Recommendation:",  # abstention message restates already-sourced totals
    )
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


def assert_snapshot_fresh(failures: list[str]) -> None:
    """Staleness canary: fail when the committed snapshot is too old (M-03).

    Override with ALLOW_STALE_SNAPSHOT=1 for a deliberate stale run.
    """
    import os
    from datetime import date, datetime

    if os.environ.get("ALLOW_STALE_SNAPSHOT") == "1":
        print("  SKIP snapshot staleness (ALLOW_STALE_SNAPSHOT=1)")
        return
    snap = json.loads(SNAPSHOT.read_text())
    as_of = datetime.strptime(snap["as_of"], "%Y-%m-%d").date()
    age = (date.today() - as_of).days
    if age > MAX_SNAPSHOT_AGE_DAYS:
        failures.append(
            f"[staleness] PRICING_SNAPSHOT.json as_of={snap['as_of']} is {age} days old "
            f"(max {MAX_SNAPSHOT_AGE_DAYS}) — refresh rates or set ALLOW_STALE_SNAPSHOT=1"
        )
    else:
        print(f"  PASS [staleness] snapshot age {age}d <= {MAX_SNAPSHOT_AGE_DAYS}d")


def assert_monotonicity(failures: list[str]) -> None:
    """Property checks over a streams sweep with a fixed real quote (M-05)."""
    base = ["--model-size", "medium", "--uptime", "24x7", "--managed-usd-mo", "1000"]
    prev_total = 0.0
    prev_instances = 0
    ok = True
    for streams in SWEEP_STREAMS:
        data = run_json(["--streams", str(streams), *base])
        diy = data["diy"]
        if diy["total_run_rate_mo"] < prev_total:
            failures.append(
                f"[monotonic] DIY total decreased at streams={streams}: "
                f"{diy['total_run_rate_mo']} < {prev_total}"
            )
            ok = False
        if diy["n_instances"] < prev_instances:
            failures.append(
                f"[monotonic] instance count decreased at streams={streams}"
            )
            ok = False
        if data["scaling_cliff_incremental_usd_mo"] < 0:
            failures.append(
                f"[monotonic] negative scaling-cliff increment at streams={streams}"
            )
            ok = False
        if data["crossover_months"] is not None and data["crossover_months"] < 0:
            failures.append(
                f"[monotonic] negative crossover_months at streams={streams}"
            )
            ok = False
        prev_total = diy["total_run_rate_mo"]
        prev_instances = diy["n_instances"]
    if ok:
        print(f"  PASS [monotonic] {len(SWEEP_STREAMS)}-point sweep properties hold")


def assert_abstention_sweep(failures: list[str]) -> None:
    """Without a real quote, no sweep point may emit a diy/managed verdict (C-04)."""
    ok = True
    for streams in SWEEP_STREAMS:
        data = run_json(
            ["--streams", str(streams), "--model-size", "medium", "--uptime", "24x7"]
        )
        if data["recommendation"] != "insufficient-data":
            failures.append(
                f"[abstention] streams={streams}: expected insufficient-data, "
                f"got {data['recommendation']!r}"
            )
            ok = False
    if ok:
        print(
            f"  PASS [abstention] no verdict without a quote across {len(SWEEP_STREAMS)} points"
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

    assert_snapshot_fresh(failures)
    assert_monotonicity(failures)
    assert_abstention_sweep(failures)

    if failures:
        print("\nFAIL:")
        for f in failures:
            print(f"  {f}")
        return 1

    print("\nAll assertions passed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
