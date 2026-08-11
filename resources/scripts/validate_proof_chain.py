#!/usr/bin/env python3
"""Validate one locally digest-bound Sentinel decision chain."""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from proof_chain import load_acceptance, load_json, parse_utc, sha256_file
from validate_delivery_handoff import validate_handoff

REQUIRED_LEDGER_ACTIONS = {
    "baseline_measured",
    "artifact_verified",
    "delivery_handoff_emitted",
    "crossover_delivered",
}
REPORT_ACTION = "decision_report_emitted"
ARTIFACT_LEDGER_ACTIONS = {"artifact_verified", "delivery_handoff_emitted"}


def _binding(data: dict[str, Any], label: str) -> tuple[str, str]:
    """Return required acceptance ID and digest fields from one record."""
    acceptance_id = data.get("acceptance_id")
    acceptance_sha256 = data.get("acceptance_sha256")
    if not isinstance(acceptance_id, str) or not acceptance_id:
        raise ValueError(f"{label} is missing acceptance_id")
    if not isinstance(acceptance_sha256, str) or len(acceptance_sha256) != 64:
        raise ValueError(f"{label} is missing acceptance_sha256")
    return acceptance_id, acceptance_sha256


def _validate_binding(data: dict[str, Any], label: str, acceptance_id: str, acceptance_sha256: str) -> None:
    """Require one record to carry the selected acceptance binding."""
    if _binding(data, label) != (acceptance_id, acceptance_sha256):
        raise ValueError(f"{label} does not match the frozen acceptance")


def _load_ledger(path: Path) -> list[dict[str, Any]]:
    """Load a regular JSONL ledger and reject malformed rows."""
    if path.is_symlink() or not path.is_file():
        raise ValueError("ledger must be a regular non-symlink file")
    records: list[dict[str, Any]] = []
    for line_number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        if not line.strip():
            continue
        try:
            record = json.loads(line)
        except json.JSONDecodeError as exc:
            raise ValueError(f"ledger row {line_number} is invalid JSON") from exc
        if not isinstance(record, dict):
            raise ValueError(f"ledger row {line_number} is not an object")
        records.append(record)
    return records


def validate_chain(args: argparse.Namespace) -> dict[str, str]:
    """Validate all local proof boundaries and return the stable chain identity."""
    acceptance = load_acceptance(args.acceptance)
    acceptance_digest = sha256_file(args.acceptance)
    acceptance_id = str(acceptance["acceptance_id"])

    baseline = load_json(args.baseline, "baseline result")
    _validate_binding(baseline, "baseline result", acceptance_id, acceptance_digest)
    if baseline.get("dataset_sha256") != acceptance["dataset_sha256"]:
        raise ValueError("baseline dataset digest does not match acceptance")
    if baseline.get("model") != acceptance["model_or_pipeline"]:
        raise ValueError("baseline model does not match acceptance")
    if baseline.get("metric") != acceptance["metric"]:
        raise ValueError("baseline metric does not match acceptance")
    if baseline.get("comparator") != acceptance["comparator"]:
        raise ValueError("baseline comparator does not match acceptance")
    if baseline.get("threshold") != acceptance["threshold"]:
        raise ValueError("baseline threshold does not match acceptance")
    observed = baseline.get("observed_value")
    if isinstance(observed, bool) or not isinstance(observed, int | float) or not math.isfinite(observed):
        raise ValueError("baseline observed_value must be finite numeric")
    threshold = float(acceptance["threshold"])
    passes = observed >= threshold if acceptance["comparator"] == "gte" else observed <= threshold
    if baseline.get("passes_acceptance") is not passes:
        raise ValueError("baseline passes_acceptance disagrees with the frozen criterion")
    if not passes:
        raise ValueError("baseline does not pass the frozen acceptance criterion")
    measured_at = parse_utc(baseline.get("measured_at"), "baseline measured_at")
    if measured_at < parse_utc(acceptance["frozen_at"], "acceptance frozen_at"):
        raise ValueError("baseline measurement predates frozen acceptance")
    if measured_at > datetime.now(timezone.utc) + timedelta(minutes=5):
        raise ValueError("baseline measurement is unreasonably far in the future")

    handoff = validate_handoff(args.handoff, args.project_root)
    _validate_binding(handoff, "delivery handoff", acceptance_id, acceptance_digest)
    artifact_digest = handoff.get("artifact_sha256")
    if not isinstance(artifact_digest, str) or len(artifact_digest) != 64:
        raise ValueError("delivery handoff is missing artifact_sha256")

    economics = load_json(args.economics, "economics result")
    proof = economics.get("proof")
    if not isinstance(proof, dict) or proof.get("status") != "bound":
        raise ValueError("economics result is not bound to frozen acceptance")
    _validate_binding(proof, "economics result", acceptance_id, acceptance_digest)

    records = _load_ledger(args.ledger)
    matched_actions: set[str] = set()
    matched_records: list[dict[str, Any]] = []
    seen_events: dict[str, dict[str, Any]] = {}
    for record in records:
        event_id = record.get("event_id")
        if not isinstance(event_id, str) or not event_id:
            raise ValueError("ledger contains a row without event_id")
        previous = seen_events.get(event_id)
        if previous is not None and previous != record:
            raise ValueError(f"ledger contains conflicting event_id: {event_id}")
        seen_events[event_id] = record
        action = record.get("action")
        if action not in REQUIRED_LEDGER_ACTIONS | {REPORT_ACTION} or record.get("status") != "success":
            continue
        if record.get("acceptance_id") != acceptance_id:
            continue
        _validate_binding(record, f"ledger action {action}", acceptance_id, acceptance_digest)
        if action in ARTIFACT_LEDGER_ACTIONS and record.get("artifact_sha256") != artifact_digest:
            raise ValueError(f"ledger action {action} has the wrong artifact digest")
        if action in REQUIRED_LEDGER_ACTIONS:
            matched_actions.add(str(action))
            matched_records.append(record)
    missing_actions = sorted(REQUIRED_LEDGER_ACTIONS - matched_actions)
    if missing_actions:
        raise ValueError(f"ledger is missing successful proof actions: {', '.join(missing_actions)}")

    components = {
        "acceptance_sha256": acceptance_digest,
        "baseline_sha256": sha256_file(args.baseline),
        "artifact_sha256": artifact_digest,
        "handoff_sha256": sha256_file(args.handoff),
        "economics_sha256": sha256_file(args.economics),
        "ledger_proof_sha256": hashlib.sha256(
            json.dumps(
                sorted(matched_records, key=lambda record: str(record["event_id"])),
                sort_keys=True,
                separators=(",", ":"),
            ).encode()
        ).hexdigest(),
    }
    chain_id = hashlib.sha256(json.dumps(components, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
    if args.report is not None:
        if args.report.is_symlink() or not args.report.is_file():
            raise ValueError("decision report must be a regular non-symlink file")
        report = args.report.read_text(encoding="utf-8")
        report_digest = sha256_file(args.report)
        acceptance_line = f"Acceptance: {acceptance_id} / {acceptance_digest}"
        chain_line = f"Proof chain: {chain_id}"
        if acceptance_line not in report or chain_line not in report:
            raise ValueError("decision report does not carry the validated proof binding")
        report_records = [
            record
            for record in records
            if record.get("action") == REPORT_ACTION
            and record.get("status") == "success"
            and record.get("acceptance_id") == acceptance_id
        ]
        if not report_records:
            raise ValueError("ledger is missing successful decision_report_emitted")
        for record in report_records:
            _validate_binding(
                record,
                "ledger action decision_report_emitted",
                acceptance_id,
                acceptance_digest,
            )
        if not any(record.get("report_sha256") == report_digest for record in report_records):
            raise ValueError("decision_report_emitted does not bind this report digest")
    result = {
        "acceptance_id": acceptance_id,
        "acceptance_sha256": acceptance_digest,
        "artifact_sha256": artifact_digest,
        "chain_id": chain_id,
    }
    if args.report is not None:
        result["report_sha256"] = sha256_file(args.report)
    return result


def parse_args() -> argparse.Namespace:
    """Parse project proof components and optional terminal report."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--project-root", required=True, type=Path)
    parser.add_argument("--acceptance", required=True, type=Path)
    parser.add_argument("--baseline", required=True, type=Path)
    parser.add_argument("--handoff", required=True, type=Path)
    parser.add_argument("--ledger", required=True, type=Path)
    parser.add_argument("--economics", required=True, type=Path)
    parser.add_argument("--report", type=Path)
    return parser.parse_args()


def main() -> int:
    """Emit a machine-readable local-integrity verdict."""
    try:
        result = validate_chain(parse_args())
    except (OSError, ValueError) as exc:
        print(json.dumps({"status": "failed", "reason": str(exc)}), file=sys.stderr)
        return 1
    print(json.dumps({"status": "passed", "trust": "local-same-user", **result}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
