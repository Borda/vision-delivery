#!/usr/bin/env python3
"""Append one record to .vision-delivery/ledger.jsonl safely.

Uses json.dumps — safe for any field value including single quotes,
newlines, or other shell-special characters. Never use echo '...' >>
for ledger writes (shell injection risk on free-form notes/entity_id).

Usage:
    python3 scripts/ledger_append.py \
        --session m1-acceptance --skill detect-and-analyze \
        --action artifact_verified --event-id manual:m1:artifact:1 \
        --status success --notes "acceptance_id=m1; digest=abc123"
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

LEDGER = Path.cwd() / ".vision-delivery" / "ledger.jsonl"
VERSION = "0.2.0"


def main() -> int:
    p = argparse.ArgumentParser(description="Append a ledger record.")
    p.add_argument("--session", required=True)
    p.add_argument("--skill", required=True)
    p.add_argument("--action", required=True)
    p.add_argument("--entity-id", default="")
    p.add_argument("--event-id", required=True)
    p.add_argument(
        "--status",
        choices=("attempted", "success", "failed", "timeout", "cancelled", "unknown"),
        required=True,
    )
    p.add_argument("--source", choices=("skill", "hook", "import"), default="skill")
    p.add_argument("--notes", default="")
    p.add_argument("--streams", type=int, default=None)
    p.add_argument("--decision", default=None)
    p.add_argument("--ledger", default=str(LEDGER))
    args = p.parse_args()

    record = {
        "ts": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "session": args.session,
        "skill": args.skill,
        "action": args.action,
        "entity_id": args.entity_id,
        "version": VERSION,
        "status": args.status,
        "source": args.source,
        "event_id": args.event_id,
        "notes": args.notes,
    }
    if args.streams is not None:
        record["streams"] = args.streams
    if args.decision is not None:
        record["decision"] = args.decision

    ledger_path = Path(args.ledger)
    if not args.event_id.strip():
        p.error("--event-id must not be empty")

    ledger_path.parent.mkdir(parents=True, exist_ok=True)
    if ledger_path.exists():
        for line in ledger_path.read_text(encoding="utf-8").splitlines():
            try:
                existing = json.loads(line)
            except json.JSONDecodeError:
                continue
            if existing.get("event_id") != args.event_id:
                continue
            comparable = {key: value for key, value in record.items() if key != "ts"}
            prior = {key: existing.get(key) for key in comparable}
            if prior == comparable:
                return 0
            print(
                f"event_id {args.event_id!r} already exists with different content",
                file=sys.stderr,
            )
            return 2

    with ledger_path.open("a", encoding="utf-8") as f:
        f.write(json.dumps(record, allow_nan=False) + "\n")

    return 0


if __name__ == "__main__":
    sys.exit(main())
