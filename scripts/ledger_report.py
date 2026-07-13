#!/usr/bin/env python3
"""Read .vision-delivery/ledger.jsonl and report delivery metrics.

Usage:
    python3 scripts/ledger_report.py              # human-readable text
    python3 scripts/ledger_report.py --json       # machine-readable JSON
    python3 scripts/ledger_report.py --ledger path/to/other.jsonl
"""

import argparse
import json
import sys
from collections import Counter
from pathlib import Path

_PRE_DEPLOY_ACTIONS = {
    "baseline_measured",
    "models_train",
}  # models_train: legacy pre-2026-07-09 rows


def _is_deployment(record: dict) -> bool:
    """Return whether a record is a verified deployment outcome."""
    if record.get("action") == "project_deployment_launch":
        return True
    return (
        record.get("action") == "roboflow_mcp_call"
        and record.get("category") == "deployment"
    )


def _is_pre_deployment(record: dict) -> bool:
    """Return whether a successful record proves measured/build progress."""
    if record.get("action") in _PRE_DEPLOY_ACTIONS:
        return True
    return record.get("action") == "roboflow_mcp_call" and record.get("category") in {
        "evaluation",
        "training",
    }


def _default_ledger() -> Path:
    """Return the ledger in the user's current project, not the plugin cache."""
    return Path.cwd() / ".vision-delivery" / "ledger.jsonl"


def load_records(ledger: Path) -> list[dict]:
    """Load JSONL records, skipping blank lines and malformed entries."""
    if not ledger.exists():
        return []
    records: list[dict] = []
    for i, raw in enumerate(ledger.read_text(encoding="utf-8").splitlines(), 1):
        line = raw.strip()
        if not line:
            continue
        try:
            records.append(json.loads(line))
        except json.JSONDecodeError as exc:
            print(f"# warn: line {i} invalid JSON — {exc}", file=sys.stderr)
    return records


def deduplicate_records(records: list[dict]) -> tuple[list[dict], int]:
    """Deduplicate records that carry a stable host tool-use identifier.

    Records without an ``event_id`` are retained because there is no reliable
    evidence that two otherwise-identical manual records describe one event.

    Args:
        records: Ledger records in append order.

    Returns:
        Deduplicated records and the number of duplicate rows ignored.
    """
    positions: dict[str, int] = {}
    deduplicated: list[dict] = []
    duplicates = 0
    for record in records:
        event_id = record.get("event_id")
        if not isinstance(event_id, str) or not event_id:
            deduplicated.append(record)
            continue
        if event_id in positions:
            deduplicated[positions[event_id]] = record
            duplicates += 1
            continue
        positions[event_id] = len(deduplicated)
        deduplicated.append(record)
    return deduplicated, duplicates


def compute_metrics(records: list[dict]) -> dict:
    """Derive all report metrics from a list of ledger records."""
    raw_records = len(records)
    records, duplicates_ignored = deduplicate_records(records)
    total_events = len(records)
    successful_records = [r for r in records if r.get("status") == "success"]
    sessions = len({r.get("session", "unknown") for r in records})

    deployed = {
        r.get("session", "unknown") for r in successful_records if _is_deployment(r)
    }
    progressed = {
        r.get("session", "unknown") for r in successful_records if _is_pre_deployment(r)
    }
    deploy_sessions = len(deployed)
    deploy_pct = round(deploy_sessions / sessions * 100, 1) if sessions else 0.0

    solved_no_deploy = len(progressed - deployed)

    workload_mix = dict(
        Counter(r.get("skill", "unknown") for r in successful_records).most_common()
    )
    action_breakdown = dict(
        Counter(
            r.get("operation") or r.get("action", "unknown") for r in successful_records
        ).most_common()
    )
    outcome_breakdown = dict(
        Counter(r.get("status", "legacy-unknown") for r in records).most_common()
    )

    return {
        "raw_records": raw_records,
        "total_events": total_events,
        "duplicates_ignored": duplicates_ignored,
        "verified_success_events": len(successful_records),
        "sessions": sessions,
        "sessions_reaching_deploy": deploy_sessions,
        "sessions_reaching_deploy_pct": deploy_pct,
        "solved_no_deploy": solved_no_deploy,
        "workload_mix": workload_mix,
        "action_breakdown": action_breakdown,
        "outcome_breakdown": outcome_breakdown,
        "coverage_note": "verified-success metrics only; legacy rows without status are retained as unknown, and host hook coverage still depends on hook trust",
    }


def print_text(m: dict) -> None:
    """Render metrics as human-readable text."""
    deploy_pct = int(m["sessions_reaching_deploy_pct"])
    print("vision-delivery ledger report")
    print("(verified successes only; legacy status-less rows remain unknown)")
    print("─" * 33)
    print(f"Ledger rows:              {m['raw_records']}")
    print(f"Unique events:            {m['total_events']}")
    print(f"Verified successes:       {m['verified_success_events']}")
    print(f"Duplicates ignored:       {m['duplicates_ignored']}")
    print(f"Sessions:                 {m['sessions']}")
    print(f"Sessions reaching deploy: {m['sessions_reaching_deploy']} ({deploy_pct}%)")
    print(f"Solved-no-deploy:         {m['solved_no_deploy']}")

    print("\nWorkload mix (by skill):")
    if m["workload_mix"]:
        for skill, count in m["workload_mix"].items():
            print(f"  {skill:<26} {count}")
    else:
        print("  (none)")

    print("\nOutcome breakdown:")
    if m["outcome_breakdown"]:
        for status, count in m["outcome_breakdown"].items():
            print(f"  {status:<26} {count}")
    else:
        print("  (none)")

    print("\nAction breakdown:")
    if m["action_breakdown"]:
        for action, count in m["action_breakdown"].items():
            print(f"  {action:<26} {count}")
    else:
        print("  (none)")


def main() -> None:
    """Entry point — parse args, load ledger, emit report."""
    parser = argparse.ArgumentParser(description="vision-delivery ledger report")
    parser.add_argument("--json", action="store_true", help="emit JSON output")
    parser.add_argument(
        "--ledger", type=Path, default=None, help="path to ledger.jsonl"
    )
    args = parser.parse_args()

    ledger = args.ledger if args.ledger else _default_ledger()
    records = load_records(ledger)
    m = compute_metrics(records)

    if args.json:
        print(json.dumps(m, indent=2))
    else:
        print_text(m)


if __name__ == "__main__":
    main()
