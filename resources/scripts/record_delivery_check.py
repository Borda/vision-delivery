#!/usr/bin/env python3
"""Run one explicitly reviewed delivery command and record digest-bound evidence."""

from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

from proof_chain import (
    load_acceptance,
    load_check_contract,
    sha256_file,
    sha256_tree,
    validate_artifact_command,
    write_json_exclusive,
)


def parse_args() -> argparse.Namespace:
    """Parse reviewed execution inputs and the command after ``--``."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--acceptance", required=True, type=Path)
    parser.add_argument("--artifact-dir", required=True, type=Path)
    parser.add_argument("--check-contract", required=True, type=Path)
    parser.add_argument("--evidence-out", required=True, type=Path)
    parser.add_argument("--timeout", type=float, default=120.0)
    parser.add_argument(
        "--execute-reviewed",
        action="store_true",
        help="Confirm a human reviewed the command and its host privileges.",
    )
    parser.add_argument("command", nargs=argparse.REMAINDER)
    args = parser.parse_args()
    if args.command[:1] == ["--"]:
        args.command = args.command[1:]
    if not args.command:
        parser.error("a command is required after --")
    if not args.execute_reviewed:
        parser.error("--execute-reviewed is required; generated code is not auto-executed")
    return args


def main() -> int:
    """Execute the reviewed command and write evidence only after success."""
    args = parse_args()
    if args.evidence_out.exists() or args.evidence_out.is_symlink():
        raise SystemExit("evidence output already exists")
    acceptance = load_acceptance(args.acceptance)
    acceptance_digest = sha256_file(args.acceptance)
    artifact_digest = sha256_tree(args.artifact_dir)
    contract = load_check_contract(
        args.check_contract,
        acceptance=acceptance,
        acceptance_sha256=acceptance_digest,
        artifact_dir=args.artifact_dir,
        artifact_sha256=artifact_digest,
    )
    validate_artifact_command(
        args.command,
        args.artifact_dir,
        self_test=False,
        require_current_python=True,
    )
    if args.command != contract["command"]:
        raise SystemExit("reviewed command does not match the frozen check contract")
    try:
        completed = subprocess.run(
            args.command,
            cwd=args.artifact_dir,
            text=True,
            capture_output=True,
            timeout=args.timeout,
            check=False,
        )
    except subprocess.TimeoutExpired:
        print(
            json.dumps({"status": "failed", "reason": "reviewed delivery command timed out"}),
            file=sys.stderr,
        )
        return 1
    if completed.returncode != 0:
        print(
            json.dumps(
                {
                    "status": "failed",
                    "reason": "reviewed delivery command failed",
                    "returncode": completed.returncode,
                }
            ),
            file=sys.stderr,
        )
        return 1
    stdout_digest = hashlib.sha256(completed.stdout.encode()).hexdigest()
    if stdout_digest != contract["expected_stdout_sha256"]:
        print(
            json.dumps(
                {
                    "status": "failed",
                    "reason": "reviewed delivery output did not match the frozen oracle",
                }
            ),
            file=sys.stderr,
        )
        return 1
    payload = {
        "schema_version": "2",
        "producer": "sentinel-reviewed-check",
        "status": "passed",
        "check": contract["check"],
        "checked_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "acceptance_id": acceptance["acceptance_id"],
        "acceptance_sha256": acceptance_digest,
        "artifact_sha256": artifact_digest,
        "check_contract_sha256": sha256_file(args.check_contract),
        "command": args.command,
        "command_sha256": hashlib.sha256(json.dumps(args.command, separators=(",", ":")).encode()).hexdigest(),
        "expected_stdout_sha256": contract["expected_stdout_sha256"],
        "stdout_sha256": stdout_digest,
        "stderr_sha256": hashlib.sha256(completed.stderr.encode()).hexdigest(),
        "data_consent_id": contract["data_consent_id"],
    }
    write_json_exclusive(args.evidence_out, payload)
    print(json.dumps({"status": "passed", "evidence": str(args.evidence_out)}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
