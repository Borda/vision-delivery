#!/usr/bin/env python3
"""Report sessions-reaching-deploy from .vision-delivery/ledger.jsonl.

Usage: python3 scripts/ledger_report.py [--json]
"""
import json
import sys
from collections import defaultdict
from pathlib import Path

LEDGER = Path(".vision-delivery/ledger.jsonl")
DEPLOY_ACTIONS = {"project_deployment_launch"}


def load_records():
    if not LEDGER.exists():
        return []
    records = []
    for i, line in enumerate(LEDGER.read_text().splitlines(), 1):
        line = line.strip()
        if not line:
            continue
        try:
            records.append(json.loads(line))
        except json.JSONDecodeError as exc:
            print(f"[warn] line {i} invalid JSON: {exc}", file=sys.stderr)
    return records


def main():
    emit_json = "--json" in sys.argv
    records = load_records()

    if not records:
        if emit_json:
            print(json.dumps({"sessions": 0, "sessions_reaching_deploy": 0, "records": 0}))
        else:
            print("No ledger records found. Run a skill session to populate .vision-delivery/ledger.jsonl")
        return

    sessions = defaultdict(list)
    for r in records:
        sessions[r.get("session", "unknown")].append(r)

    reaching_deploy = [
        s for s, recs in sessions.items()
        if any(r.get("action") in DEPLOY_ACTIONS for r in recs)
    ]

    action_counts = defaultdict(int)
    for r in records:
        action_counts[r.get("action", "unknown")] += 1

    if emit_json:
        print(json.dumps({
            "sessions": len(sessions),
            "sessions_reaching_deploy": len(reaching_deploy),
            "reaching_deploy_pct": round(len(reaching_deploy) / len(sessions) * 100, 1) if sessions else 0,
            "records": len(records),
            "action_counts": dict(action_counts),
            "sessions_detail": {
                s: {
                    "actions": [r.get("action") for r in recs],
                    "deployed": any(r.get("action") in DEPLOY_ACTIONS for r in recs),
                }
                for s, recs in sorted(sessions.items())
            },
        }, indent=2))
        return

    pct = round(len(reaching_deploy) / len(sessions) * 100) if sessions else 0

    print(f"\n{'─' * 50}")
    print(f"  Sessions-reaching-deploy: {len(reaching_deploy)} / {len(sessions)}  ({pct}%)")
    print(f"  Total records: {len(records)}")
    print(f"{'─' * 50}")

    print("\nSessions:")
    for s, recs in sorted(sessions.items()):
        actions = [r.get("action", "?") for r in recs]
        deployed = any(a in DEPLOY_ACTIONS for a in actions)
        flag = "  ✓ deploy" if deployed else ""
        print(f"  {s}: {', '.join(actions)}{flag}")

    print("\nAction breakdown:")
    for action, count in sorted(action_counts.items()):
        print(f"  {action}: {count}")
    print()


if __name__ == "__main__":
    main()
