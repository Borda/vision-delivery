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
import hashlib
import json
import math
import os
import stat
import sys
import time
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


def _project_root() -> Path:
    """Return the user's project root so nested working directories share one ledger.

    Examples:
        >>> isinstance(_project_root(), Path)
        True
    """
    declared = os.environ.get("CLAUDE_PROJECT_DIR", "")
    if declared and Path(declared).is_absolute():
        return Path(declared)
    start = Path.cwd()
    for candidate in (start, *start.parents):
        if (candidate / ".vision-delivery").exists() or (candidate / ".git").exists():
            return candidate
    return start


LEDGER = _project_root() / ".vision-delivery" / "ledger.jsonl"
VERSION = "0.5.0"
LOCK_TIMEOUT_SECONDS = 5.0
LOCK_RETRY_SECONDS = 0.01
PROOF_ACTIONS = {
    "baseline_measured",
    "artifact_verified",
    "delivery_handoff_emitted",
    "crossover_delivered",
    "decision_report_emitted",
}
ARTIFACT_ACTIONS = {"artifact_verified", "delivery_handoff_emitted"}
REPORT_ACTION = "decision_report_emitted"
BRIEF_ACTION = "action_brief_emitted"


def _absolute_path(path: Path) -> Path:
    """Return an absolute lexical path without resolving symbolic links."""
    return path if path.is_absolute() else Path.cwd() / path


def _reject_symlink_path(path: Path) -> None:
    """Reject a path when it or any existing ancestor is a symbolic link."""
    for candidate in (path, *path.parents):
        try:
            if candidate.is_symlink():
                raise ValueError(f"ledger path may not contain a symlink: {candidate}")
        except OSError as exc:
            raise ValueError(f"cannot inspect ledger path {candidate}: {exc}") from exc


def _prepare_ledger_path(path: Path) -> Path:
    """Create and validate the ledger parent without following symbolic links."""
    ledger_path = _absolute_path(path)
    _reject_symlink_path(ledger_path)
    try:
        ledger_path.parent.mkdir(parents=True, exist_ok=True)
    except OSError as exc:
        raise ValueError(f"cannot create ledger directory: {exc}") from exc
    _reject_symlink_path(ledger_path)
    if ledger_path.exists():
        try:
            mode = ledger_path.stat().st_mode
        except OSError as exc:
            raise ValueError(f"cannot inspect ledger file: {exc}") from exc
        if not stat.S_ISREG(mode):
            raise ValueError(f"ledger path must be a regular file: {ledger_path}")
    return ledger_path


@contextmanager
def _ledger_lock(ledger_path: Path) -> Iterator[None]:
    """Serialize ledger reads and appends with an atomically-created directory."""
    lock_path = ledger_path.with_name(f"{ledger_path.name}.lock")
    deadline = time.monotonic() + LOCK_TIMEOUT_SECONDS
    while True:
        _reject_symlink_path(lock_path)
        try:
            lock_path.mkdir()
            break
        except FileExistsError:
            _reject_symlink_path(lock_path)
            if time.monotonic() >= deadline:
                raise ValueError(f"timed out waiting for ledger lock: {lock_path}") from None
            time.sleep(LOCK_RETRY_SECONDS)
        except OSError as exc:
            raise ValueError(f"cannot create ledger lock: {exc}") from exc
    try:
        yield
    finally:
        try:
            if lock_path.is_dir() and not lock_path.is_symlink():
                lock_path.rmdir()
        except OSError:
            pass


def _comparable_record(record: dict[str, Any]) -> dict[str, Any]:
    """Remove the generated timestamp before duplicate-content comparison."""
    return {key: value for key, value in record.items() if key != "ts"}


def _read_records(ledger_path: Path) -> list[dict[str, Any]]:
    """Read ledger records while preserving malformed rows for append tolerance."""
    if not ledger_path.exists():
        return []
    records: list[dict[str, Any]] = []
    for line in ledger_path.read_text(encoding="utf-8").splitlines():
        try:
            parsed = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(parsed, dict):
            records.append(parsed)
    return records


def _append_record(ledger_path: Path, record: dict[str, Any]) -> None:
    """Append one JSON record after checking the target is still a regular file."""
    _prepare_ledger_path(ledger_path)
    flags = os.O_WRONLY | os.O_APPEND | os.O_CREAT
    if hasattr(os, "O_NOFOLLOW"):
        flags |= os.O_NOFOLLOW
    try:
        descriptor = os.open(ledger_path, flags, 0o600)
    except OSError as exc:
        raise ValueError(f"cannot open ledger safely: {exc}") from exc
    with os.fdopen(descriptor, "a", encoding="utf-8") as file:
        file.write(json.dumps(record, allow_nan=False) + "\n")


def _acceptance_binding(path: Path) -> tuple[str, str]:
    """Load a complete frozen acceptance artifact and return its ID and digest."""
    if path.is_symlink() or not path.is_file():
        raise ValueError("acceptance must be a regular non-symlink JSON file")
    try:
        raw = path.read_bytes()
        data = json.loads(raw)
    except (OSError, json.JSONDecodeError) as exc:
        raise ValueError(f"cannot read acceptance artifact: {exc}") from exc
    required = {
        "schema_version",
        "acceptance_id",
        "frozen_at",
        "metric",
        "comparator",
        "threshold",
        "unit",
        "dataset_sha256",
        "model_or_pipeline",
        "confirmed_by",
    }
    if not isinstance(data, dict) or data.get("schema_version") != "1":
        raise ValueError("acceptance must use Sentinel schema 1")
    if required - data.keys():
        raise ValueError("acceptance is missing frozen fields")
    acceptance_id = data.get("acceptance_id")
    if not isinstance(acceptance_id, str) or not acceptance_id.strip():
        raise ValueError("acceptance_id must be non-empty text")
    dataset_digest = data.get("dataset_sha256")
    if (
        not isinstance(dataset_digest, str)
        or len(dataset_digest) != 64
        or any(character not in "0123456789abcdef" for character in dataset_digest)
    ):
        raise ValueError("acceptance dataset_sha256 must be lowercase SHA-256")
    threshold = data.get("threshold")
    if isinstance(threshold, bool) or not isinstance(threshold, int | float) or not math.isfinite(threshold):
        raise ValueError("acceptance threshold must be finite numeric")
    if data.get("comparator") not in {"gte", "lte"}:
        raise ValueError("acceptance comparator must be gte or lte")
    return acceptance_id, hashlib.sha256(raw).hexdigest()


def _artifact_tree_digest(root: Path) -> str:
    """Return a deterministic digest for a non-symlink artifact tree."""
    if root.is_symlink() or not root.is_dir():
        raise ValueError("artifact directory must be a non-symlink directory")
    entries = sorted(root.rglob("*"))
    if not entries:
        raise ValueError("artifact directory contains no files")
    digest = hashlib.sha256(b"SENTINEL-TREE-V2\0")
    for path in entries:
        if path.is_symlink():
            raise ValueError(f"artifact directory contains a symlink: {path}")
        relative = path.relative_to(root).as_posix().encode()
        mode = path.lstat().st_mode
        if stat.S_ISDIR(mode):
            entry_type = b"D"
            content = b""
        elif stat.S_ISREG(mode):
            entry_type = b"F"
            content = path.read_bytes()
        else:
            raise ValueError(f"artifact directory contains a special file: {path}")
        digest.update(entry_type)
        digest.update(len(relative).to_bytes(8, "big"))
        digest.update(relative)
        digest.update(stat.S_IMODE(mode).to_bytes(4, "big"))
        digest.update(len(content).to_bytes(8, "big"))
        digest.update(content)
    return digest.hexdigest()


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
    p.add_argument(
        "--operation",
        default="",
        help="provider operation or category an action_brief_emitted row approves (read by the PreToolUse gate)",
    )
    p.add_argument("--acceptance", type=Path)
    p.add_argument("--artifact-dir", type=Path)
    p.add_argument("--report", type=Path)
    p.add_argument("--streams", type=int, default=None)
    p.add_argument("--decision", default=None)
    p.add_argument("--ledger", default=str(LEDGER))
    args = p.parse_args()

    acceptance_id = ""
    acceptance_sha256 = ""
    artifact_sha256 = ""
    report_sha256 = ""
    if args.status == "success" and args.action == BRIEF_ACTION and not args.operation.strip():
        p.error(f"--operation is required for successful {BRIEF_ACTION}")
    try:
        if args.status == "success" and args.action in PROOF_ACTIONS:
            if args.acceptance is None:
                p.error(f"--acceptance is required for successful {args.action}")
            acceptance_id, acceptance_sha256 = _acceptance_binding(args.acceptance)
        if args.status == "success" and args.action in ARTIFACT_ACTIONS:
            if args.artifact_dir is None:
                p.error(f"--artifact-dir is required for successful {args.action}")
            artifact_sha256 = _artifact_tree_digest(args.artifact_dir)
        if args.status == "success" and args.action == REPORT_ACTION:
            if args.report is None:
                p.error("--report is required for successful decision_report_emitted")
            if args.report.is_symlink() or not args.report.is_file():
                p.error("--report must be a regular non-symlink file")
            report_sha256 = hashlib.sha256(args.report.read_bytes()).hexdigest()
    except ValueError as exc:
        p.error(str(exc))

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
    if acceptance_id:
        record["acceptance_id"] = acceptance_id
        record["acceptance_sha256"] = acceptance_sha256
    if artifact_sha256:
        record["artifact_sha256"] = artifact_sha256
    if report_sha256:
        record["report_sha256"] = report_sha256
    if args.operation:
        record["operation"] = args.operation
    if args.streams is not None:
        record["streams"] = args.streams
    if args.decision is not None:
        record["decision"] = args.decision

    ledger_path = Path(args.ledger)
    if not args.event_id.strip():
        p.error("--event-id must not be empty")

    try:
        ledger_path = _prepare_ledger_path(ledger_path)
        with _ledger_lock(ledger_path):
            ledger_path = _prepare_ledger_path(ledger_path)
            for existing in _read_records(ledger_path):
                if existing.get("event_id") != args.event_id:
                    continue
                if _comparable_record(existing) == _comparable_record(record):
                    return 0
                print(
                    f"ledger-integrity-conflict: event_id {args.event_id!r} already exists with different content",
                    file=sys.stderr,
                )
                return 2
            _append_record(ledger_path, record)
    except ValueError as exc:
        print(f"ledger-append-error: {exc}", file=sys.stderr)
        return 2

    return 0


if __name__ == "__main__":
    sys.exit(main())
