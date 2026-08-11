#!/usr/bin/env python3
"""Freeze one delivery command and exact output oracle before execution."""

from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone
from pathlib import Path

from proof_chain import (
    SHA256_RE,
    load_acceptance,
    load_check_contract,
    sha256_file,
    sha256_tree,
    validate_artifact_command,
    write_json_exclusive,
)


def parse_args() -> argparse.Namespace:
    """Parse immutable proof inputs and the canonical command after ``--``."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", required=True, type=Path)
    parser.add_argument("--acceptance", required=True, type=Path)
    parser.add_argument("--artifact-dir", required=True, type=Path)
    parser.add_argument("--check", required=True, choices=("live", "offline"))
    parser.add_argument("--expected-stdout-sha256", required=True)
    parser.add_argument("--confirmed-by", required=True)
    parser.add_argument("--data-consent-id", default="")
    parser.add_argument("command", nargs=argparse.REMAINDER)
    args = parser.parse_args()
    if args.command[:1] == ["--"]:
        args.command = args.command[1:]
    if not args.command:
        parser.error("a command is required after --")
    if args.check == "live" and not args.data_consent_id.strip():
        parser.error("--data-consent-id is required for a live check")
    return args


def main() -> int:
    """Write an exclusive contract and verify it through the shared loader."""
    args = parse_args()
    acceptance = load_acceptance(args.acceptance)
    acceptance_sha256 = sha256_file(args.acceptance)
    artifact_sha256 = sha256_tree(args.artifact_dir)
    command = validate_artifact_command(
        args.command,
        args.artifact_dir,
        self_test=False,
        require_current_python=True,
    )
    if SHA256_RE.fullmatch(args.expected_stdout_sha256) is None:
        raise SystemExit("--expected-stdout-sha256 must be lowercase SHA-256")
    if not args.confirmed_by.strip():
        raise SystemExit("--confirmed-by must be non-empty")
    payload = {
        "schema_version": "1",
        "frozen_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "acceptance_id": acceptance["acceptance_id"],
        "acceptance_sha256": acceptance_sha256,
        "artifact_sha256": artifact_sha256,
        "check": args.check,
        "command": command,
        "expected_stdout_sha256": args.expected_stdout_sha256,
        "confirmed_by": args.confirmed_by,
        "data_consent_id": args.data_consent_id if args.check == "live" else "not-applicable",
    }
    write_json_exclusive(args.out, payload)
    load_check_contract(
        args.out,
        acceptance=acceptance,
        acceptance_sha256=acceptance_sha256,
        artifact_dir=args.artifact_dir,
        artifact_sha256=artifact_sha256,
    )
    print(
        json.dumps(
            {
                "status": "frozen",
                "path": str(args.out),
                "check_contract_sha256": sha256_file(args.out),
            }
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
