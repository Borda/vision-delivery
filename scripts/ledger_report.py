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

_DEPLOY_ACTION = "project_deployment_launch"
_PRE_DEPLOY_ACTIONS = {"baseline_measured", "models_train"}


def _default_ledger() -> Path:
    return Path(__file__).parent.parent / ".vision-delivery" / "ledger.jsonl"


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


def compute_metrics(records: list[dict]) -> dict:
    """Derive all report metrics from a list of ledger records."""
    total_events = len(records)

    session_actions: dict[str, set[str]] = {}
    for r in records:
        sid = r.get("session", "unknown")
        action = r.get("action", "unknown")
        session_actions.setdefault(sid, set()).add(action)

    sessions = len(session_actions)

    deploy_sessions = sum(
        1 for actions in session_actions.values() if _DEPLOY_ACTION in actions
    )
    deploy_pct = round(deploy_sessions / sessions * 100, 1) if sessions else 0.0

    solved_no_deploy = sum(
        1
        for actions in session_actions.values()
        if actions & _PRE_DEPLOY_ACTIONS and _DEPLOY_ACTION not in actions
    )

    workload_mix = dict(
        Counter(r.get("skill", "unknown") for r in records).most_common()
    )
    action_breakdown = dict(
        Counter(r.get("action", "unknown") for r in records).most_common()
    )

    return {
        "total_events": total_events,
        "sessions": sessions,
        "sessions_reaching_deploy": deploy_sessions,
        "sessions_reaching_deploy_pct": deploy_pct,
        "solved_no_deploy": solved_no_deploy,
        "workload_mix": workload_mix,
        "action_breakdown": action_breakdown,
    }


def print_text(m: dict) -> None:
    """Render metrics as human-readable text."""
    deploy_pct = int(m["sessions_reaching_deploy_pct"])
    print("vision-delivery ledger report")
    print("─" * 33)
    print(f"Total events:             {m['total_events']}")
    print(f"Sessions:                 {m['sessions']}")
    print(
        f"Sessions reaching deploy: {m['sessions_reaching_deploy']}"
        f" ({deploy_pct}%)"
    )
    print(f"Solved-no-deploy:         {m['solved_no_deploy']}")

    print("\nWorkload mix (by skill):")
    if m["workload_mix"]:
        for skill, count in m["workload_mix"].items():
            print(f"  {skill:<26} {count}")
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
