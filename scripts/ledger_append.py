#!/usr/bin/env python3
"""Append one record to .vision-delivery/ledger.jsonl safely.

Uses json.dumps — safe for any field value including single quotes,
newlines, or other shell-special characters. Never use echo '...' >>
for ledger writes (shell injection risk on free-form notes/entity_id).

Usage:
    python3 scripts/ledger_append.py \
        --session m1-acceptance --skill detect-and-analyze \
        --action models_train --entity-id workspace/project/1 \
        --notes "rfdetr-medium, mAP@50=84.6%"
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

LEDGER = Path(__file__).parent.parent / ".vision-delivery" / "ledger.jsonl"
VERSION = "0.1.0"


def main() -> int:
    p = argparse.ArgumentParser(description="Append a ledger record.")
    p.add_argument("--session", required=True)
    p.add_argument("--skill", required=True)
    p.add_argument("--action", required=True)
    p.add_argument("--entity-id", default="")
    p.add_argument("--notes", default="")
    p.add_argument("--ledger", default=str(LEDGER))
    args = p.parse_args()

    record = {
        "ts": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "session": args.session,
        "skill": args.skill,
        "action": args.action,
        "entity_id": args.entity_id,
        "version": VERSION,
        "notes": args.notes,
    }

    ledger_path = Path(args.ledger)
    ledger_path.parent.mkdir(parents=True, exist_ok=True)
    with ledger_path.open("a", encoding="utf-8") as f:
        f.write(json.dumps(record) + "\n")

    return 0


if __name__ == "__main__":
    sys.exit(main())
