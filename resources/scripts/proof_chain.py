#!/usr/bin/env python3
"""Validate and hash Sentinel proof-chain artifacts."""

from __future__ import annotations

import hashlib
import json
import math
import os
import re
import stat
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

SHA256_HEX_LENGTH = 64
SHA256_RE = re.compile(r"[0-9a-f]{64}")
SECRET_ARG_RE = re.compile(
    r"(?i)(?:api[_-]?key|token|secret|password|authorization|bearer|"
    r"[?&](?:key|signature|sig|token|secret|password)=)"
)
ACCEPTANCE_FIELDS = (
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
)


def sha256_file(path: Path) -> str:
    """Return the SHA-256 digest of one regular file."""
    if path.is_symlink() or not path.is_file():
        raise ValueError(f"proof input must be a regular non-symlink file: {path}")
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def sha256_tree(root: Path) -> str:
    """Return a deterministic digest of a regular-file artifact tree."""
    if root.is_symlink() or not root.is_dir():
        raise ValueError(f"artifact root must be a non-symlink directory: {root}")
    entries = sorted(root.rglob("*"))
    if not entries:
        raise ValueError("artifact tree contains no regular files")
    digest = hashlib.sha256(b"SENTINEL-TREE-V2\0")
    for path in entries:
        if path.is_symlink():
            raise ValueError(f"artifact tree contains a symlink: {path}")
        relative = path.relative_to(root).as_posix().encode()
        mode = path.lstat().st_mode
        if stat.S_ISDIR(mode):
            entry_type = b"D"
            content = b""
        elif stat.S_ISREG(mode):
            entry_type = b"F"
            content = path.read_bytes()
        else:
            raise ValueError(f"artifact tree contains a special file: {path}")
        digest.update(entry_type)
        digest.update(len(relative).to_bytes(8, "big"))
        digest.update(relative)
        digest.update(stat.S_IMODE(mode).to_bytes(4, "big"))
        digest.update(len(content).to_bytes(8, "big"))
        digest.update(content)
    return digest.hexdigest()


def load_json(path: Path, label: str) -> dict[str, Any]:
    """Load a JSON object from a regular non-symlink file."""
    if path.is_symlink() or not path.is_file():
        raise ValueError(f"{label} must be a regular non-symlink file")
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ValueError(f"cannot read {label}: {exc}") from exc
    if not isinstance(value, dict):
        raise ValueError(f"{label} must contain a JSON object")
    return value


def write_json_exclusive(path: Path, value: dict[str, Any]) -> None:
    """Create one JSON record without replacing or following the final path."""
    path.parent.mkdir(parents=True, exist_ok=True)
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL
    if hasattr(os, "O_NOFOLLOW"):
        flags |= os.O_NOFOLLOW
    try:
        descriptor = os.open(path, flags, 0o600)
    except OSError as exc:
        raise ValueError(f"cannot create proof output safely: {exc}") from exc
    with os.fdopen(descriptor, "w", encoding="utf-8") as stream:
        json.dump(value, stream, indent=2)
        stream.write("\n")


def validate_artifact_command(
    command: Any,
    artifact_dir: Path,
    *,
    self_test: bool,
    require_current_python: bool = False,
) -> list[str]:
    """Return a narrow canonical Python argv that executes artifact inference.py."""
    if (
        not isinstance(command, list)
        or len(command) < 2
        or any(not isinstance(part, str) or not part for part in command)
    ):
        raise ValueError("artifact command must be a canonical argv array")
    if any(SECRET_ARG_RE.search(part) for part in command):
        raise ValueError("artifact command must not contain credential-shaped text")
    executable = Path(command[0]).name.removesuffix(".exe").casefold()
    if re.fullmatch(r"pythonw?(?:\d+(?:\.\d+)*)?", executable) is None:
        raise ValueError("artifact command must use a Python executable")
    if require_current_python and Path(command[0]).resolve() != Path(sys.executable).resolve():
        raise ValueError("artifact command must use the helper's current Python interpreter")
    script = Path(command[1])
    candidate = (script if script.is_absolute() else artifact_dir / script).resolve()
    if candidate != (artifact_dir / "inference.py").resolve():
        raise ValueError("artifact command must execute inference.py as its script")
    has_self_test = "--self-test" in command[2:]
    if has_self_test is not self_test:
        expected = "include" if self_test else "exclude"
        raise ValueError(f"artifact command must {expected} --self-test")
    return command


def load_check_contract(
    path: Path,
    *,
    acceptance: dict[str, Any],
    acceptance_sha256: str,
    artifact_dir: Path,
    artifact_sha256: str,
) -> dict[str, Any]:
    """Load a pre-execution command/output contract and verify its bindings."""
    data = load_json(path, "delivery-check contract")
    expected = {
        "schema_version": "1",
        "acceptance_id": acceptance["acceptance_id"],
        "acceptance_sha256": acceptance_sha256,
        "artifact_sha256": artifact_sha256,
    }
    for field, value in expected.items():
        if data.get(field) != value:
            raise ValueError(f"delivery-check contract {field} does not match")
    if data.get("check") not in {"live", "offline"}:
        raise ValueError("delivery-check contract check must be live or offline")
    validate_artifact_command(data.get("command"), artifact_dir, self_test=False)
    if SHA256_RE.fullmatch(str(data.get("expected_stdout_sha256", ""))) is None:
        raise ValueError("delivery-check contract output oracle must be lowercase SHA-256")
    if not isinstance(data.get("confirmed_by"), str) or not data["confirmed_by"].strip():
        raise ValueError("delivery-check contract confirmed_by must be non-empty")
    if data["check"] == "live" and not str(data.get("data_consent_id", "")).strip():
        raise ValueError("live delivery-check contract requires data_consent_id")
    frozen_at = parse_utc(data.get("frozen_at"), "delivery-check contract frozen_at")
    if frozen_at < parse_utc(acceptance["frozen_at"], "acceptance frozen_at"):
        raise ValueError("delivery-check contract predates acceptance")
    if frozen_at > datetime.now(timezone.utc) + timedelta(minutes=5):
        raise ValueError("delivery-check contract is unreasonably far in the future")
    return data


def parse_utc(value: Any, field: str) -> datetime:
    """Parse a timezone-aware ISO-8601 timestamp."""
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{field} must be a non-empty ISO-8601 timestamp")
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ValueError(f"{field} must be an ISO-8601 timestamp") from exc
    if parsed.tzinfo is None:
        raise ValueError(f"{field} must include a timezone")
    return parsed


def load_acceptance(path: Path) -> dict[str, Any]:
    """Load and validate a frozen acceptance artifact."""
    data = load_json(path, "acceptance artifact")
    validate_acceptance(data)
    return data


def validate_acceptance(data: dict[str, Any]) -> None:
    """Validate one in-memory frozen acceptance payload."""
    missing = [field for field in ACCEPTANCE_FIELDS if field not in data]
    if missing:
        raise ValueError(f"acceptance artifact is missing: {', '.join(missing)}")
    if data["schema_version"] != "1":
        raise ValueError("acceptance schema_version must be 1")
    for field in (
        "acceptance_id",
        "metric",
        "unit",
        "model_or_pipeline",
        "confirmed_by",
    ):
        if not isinstance(data[field], str) or not data[field].strip():
            raise ValueError(f"acceptance {field} must be non-empty text")
    if data["comparator"] not in {"gte", "lte"}:
        raise ValueError("acceptance comparator must be gte or lte")
    threshold = data["threshold"]
    if isinstance(threshold, bool) or not isinstance(threshold, int | float) or not math.isfinite(threshold):
        raise ValueError("acceptance threshold must be finite numeric")
    dataset_digest = data["dataset_sha256"]
    if (
        not isinstance(dataset_digest, str)
        or len(dataset_digest) != SHA256_HEX_LENGTH
        or any(character not in "0123456789abcdef" for character in dataset_digest)
    ):
        raise ValueError("acceptance dataset_sha256 must be lowercase SHA-256")
    parse_utc(data["frozen_at"], "acceptance frozen_at")


def validate_evidence(
    evidence: dict[str, Any],
    *,
    expected_producer: str,
    expected_check: str,
    acceptance: dict[str, Any],
    acceptance_sha256: str,
    artifact_sha256: str,
) -> None:
    """Validate one helper-produced local record and its proof bindings."""
    expected = {
        "schema_version": "2",
        "producer": expected_producer,
        "status": "passed",
        "check": expected_check,
        "acceptance_id": acceptance["acceptance_id"],
        "acceptance_sha256": acceptance_sha256,
        "artifact_sha256": artifact_sha256,
    }
    for field, value in expected.items():
        if evidence.get(field) != value:
            raise ValueError(f"evidence {field} does not match the proof chain")
    checked_at = parse_utc(evidence.get("checked_at"), "evidence checked_at")
    if checked_at < parse_utc(acceptance["frozen_at"], "acceptance frozen_at"):
        raise ValueError("evidence predates the frozen acceptance artifact")
    if checked_at > datetime.now(timezone.utc) + timedelta(minutes=5):
        raise ValueError("evidence checked_at is unreasonably far in the future")
