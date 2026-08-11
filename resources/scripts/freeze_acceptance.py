#!/usr/bin/env python3
"""Create an immutable-input acceptance artifact before measurement."""

from __future__ import annotations

import argparse
import json
import os
from datetime import datetime, timezone
from pathlib import Path

from proof_chain import load_acceptance, sha256_file, validate_acceptance


def parse_args() -> argparse.Namespace:
    """Parse acceptance fields and exclusive output path."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", required=True, type=Path)
    parser.add_argument("--acceptance-id", required=True)
    parser.add_argument("--metric", required=True)
    parser.add_argument("--comparator", required=True, choices=("gte", "lte"))
    parser.add_argument("--threshold", required=True, type=float)
    parser.add_argument("--unit", required=True)
    parser.add_argument("--dataset-sha256", required=True)
    parser.add_argument("--model-or-pipeline", required=True)
    parser.add_argument("--confirmed-by", required=True)
    return parser.parse_args()


def main() -> int:
    """Write a new acceptance artifact without replacing an existing record."""
    args = parse_args()
    if args.out.exists() or args.out.is_symlink():
        raise SystemExit("acceptance output already exists; revisions require a new path")
    args.out.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "schema_version": "1",
        "acceptance_id": args.acceptance_id,
        "frozen_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "metric": args.metric,
        "comparator": args.comparator,
        "threshold": args.threshold,
        "unit": args.unit,
        "dataset_sha256": args.dataset_sha256,
        "model_or_pipeline": args.model_or_pipeline,
        "confirmed_by": args.confirmed_by,
    }
    validate_acceptance(payload)
    descriptor = os.open(args.out, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(descriptor, "w", encoding="utf-8") as stream:
        json.dump(payload, stream, indent=2)
        stream.write("\n")
    load_acceptance(args.out)
    print(
        json.dumps(
            {
                "status": "frozen",
                "acceptance_id": args.acceptance_id,
                "acceptance_sha256": sha256_file(args.out),
                "path": str(args.out),
            }
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
