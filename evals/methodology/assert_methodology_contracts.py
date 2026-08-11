#!/usr/bin/env python3
"""Assert Sentinel's acceptance, routing, and provenance contracts."""

from __future__ import annotations

import json
import re
import sys
import tempfile
from importlib.util import module_from_spec, spec_from_file_location
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SKILL_ROOTS = (ROOT / "codex-skills", ROOT / "claude-skills")
SKILLS = ROOT / "claude-skills"
RESOURCES = ROOT / "resources"
BUILD_SKILLS = (
    "classify-or-flag",
    "decompose-to-pipeline",
    "detect-and-analyze",
    "read-text",
    "recognize-pose-or-gesture",
    "segment-and-analyze",
    "track-and-count",
)
MODALITY_SKILLS = tuple(name for name in BUILD_SKILLS if name != "decompose-to-pipeline")


def read(path: Path) -> str:
    """Read one required repository file as UTF-8."""
    if not path.is_file():
        raise AssertionError(f"Missing required file: {path.relative_to(ROOT)}")
    return path.read_text(encoding="utf-8")


def require(text: str, needle: str, path: Path) -> None:
    """Require an exact contract phrase in a file."""
    if needle not in text:
        raise AssertionError(f"{path.relative_to(ROOT)} is missing {needle!r}")


def reject(text: str, pattern: str, path: Path) -> None:
    """Reject a regular-expression pattern from a file."""
    if re.search(pattern, text, flags=re.IGNORECASE):
        raise AssertionError(f"{path.relative_to(ROOT)} contains forbidden pattern {pattern!r}")


def assert_independent_acceptance() -> None:
    """Require pseudo-labels to remain bootstrap-only and independently checked."""
    fde_path = RESOURCES / "fde-methodology.md"
    decompose_path = SKILLS / "decompose-to-pipeline" / "SKILL.md"
    for path in (fde_path, decompose_path):
        text = read(path)
        require(text, "independent acceptance", path)
        require(text, "blinded human", path)
        require(text, "pseudo-label", path)
        reject(text, r"LLM as oracle", path)
        reject(text, r"no CV model can", path)
        reject(text, r"replaces human annotation for the eval", path)


def assert_immutable_thresholds() -> None:
    """Require acceptance thresholds to be frozen before baseline measurement."""
    fde_path = RESOURCES / "fde-methodology.md"
    fde = read(fde_path)
    for phrase in (
        "acceptance_id",
        "frozen before any baseline",
        "baseline is diagnostic evidence",
        "new revision",
    ):
        require(fde, phrase, fde_path)

    for name in MODALITY_SKILLS:
        path = SKILLS / name / "SKILL.md"
        text = read(path)
        require(text, "Acceptance ID:", path)
        require(text, "Frozen before baseline:", path)
        require(text, "Baseline result (diagnostic only):", path)
        reject(text, r"Threshold logic:\s*max\(", path)

    baseline_path = ROOT / "scripts" / "baseline_map.py"
    baseline = read(baseline_path)
    require(baseline, "acceptance_map50", baseline_path)
    require(baseline, "baseline_gap", baseline_path)
    reject(baseline, r"threshold\s*=\s*max\(", baseline_path)


def _baseline_module():
    """Load baseline matching code without executing the network entrypoint."""
    path = ROOT / "scripts" / "baseline_map.py"
    spec = spec_from_file_location("sentinel_baseline_map", path)
    if spec is None or spec.loader is None:
        raise AssertionError(f"cannot load {path.relative_to(ROOT)}")
    module = module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def assert_baseline_matching_and_redaction() -> None:
    """Exercise overlap, duplicate, empty, absent-class, and secret-error paths."""
    baseline = _baseline_module()
    overlapping_ground_truth = {
        "frame": [
            {"box": [0, 0, 10, 10], "matched": False},
            {"box": [4, 0, 14, 10], "matched": False},
        ]
    }
    predictions = [
        (0.9, "frame", [0, 0, 10, 10]),
        (0.8, "frame", [1, 0, 11, 10]),
    ]
    true_positive, false_positive, count = baseline.match_predictions(predictions, overlapping_ground_truth)
    assert true_positive == [1.0, 1.0]
    assert false_positive == [0.0, 0.0]
    assert count == 2

    duplicate_tp, duplicate_fp, _ = baseline.match_predictions(
        [(0.9, "frame", [0, 0, 10, 10]), (0.8, "frame", [0, 0, 10, 10])],
        {"frame": [{"box": [0, 0, 10, 10], "matched": False}]},
    )
    assert duplicate_tp == [1.0, 0.0]
    assert duplicate_fp == [0.0, 1.0]
    assert baseline.match_predictions([], {}) == ([], [], 0)
    assert baseline.compute_map50([], []) == 0.0
    assert (
        baseline.compute_map50(
            [{"img_id": "frame", "boxes": [[0, 0, 10, 10]], "labels": [3]}],
            [
                {
                    "img_id": "frame",
                    "boxes": [[0, 0, 10, 10], [0, 0, 10, 10]],
                    "labels": [3, 8],
                    "scores": [0.9, 0.8],
                }
            ],
        )
        == 1.0
    )

    original_get = baseline.requests.get
    secret = "https://example.test/export?token=do-not-leak"
    baseline.requests.get = lambda *_args, **_kwargs: (_ for _ in ()).throw(RuntimeError(secret))
    try:
        try:
            baseline._load_export(secret)
        except RuntimeError as exc:
            assert str(exc) == "ERROR: protected dataset export failed; URL redacted."
            assert secret not in str(exc)
        else:
            raise AssertionError("network failure was not rejected")
    finally:
        baseline.requests.get = original_get

    with tempfile.TemporaryDirectory() as directory:
        export_file = Path(directory) / "export-url"
        export_file.write_text(secret, encoding="utf-8")
        export_file.chmod(0o600)
        assert baseline._protected_export_url(export_file) == secret
        export_file.chmod(0o644)
        assert baseline._protected_export_url(export_file) == ""
        export_file.chmod(0o600)
        link = Path(directory) / "export-link"
        link.symlink_to(export_file)
        assert baseline._protected_export_url(link) == ""

    source = (ROOT / "scripts" / "baseline_map.py").read_text(encoding="utf-8")
    assert "--export-url" not in source
    assert "--acceptance-map50" not in source
    assert '"acceptance_sha256"' in source

    with tempfile.TemporaryDirectory() as directory:
        acceptance_path = Path(directory) / "acceptance.json"
        acceptance_payload = {
            "schema_version": "1",
            "acceptance_id": "b1/v1",
            "frozen_at": "2026-08-11T00:00:00Z",
            "metric": "mAP@50",
            "comparator": "gte",
            "threshold": 0.65,
            "dataset_sha256": "a" * 64,
            "model_or_pipeline": baseline.MODEL_ID,
        }
        acceptance_path.write_text(json.dumps(acceptance_payload), encoding="utf-8")
        acceptance, digest = baseline._load_acceptance(acceptance_path)
        assert acceptance["acceptance_id"] == "b1/v1"
        assert len(digest) == 64
        acceptance_payload["threshold"] = True
        acceptance_path.write_text(json.dumps(acceptance_payload), encoding="utf-8")
        try:
            baseline._load_acceptance(acceptance_path)
        except RuntimeError as exc:
            assert "threshold" in str(exc)
        else:
            raise AssertionError("boolean acceptance threshold was accepted")
        acceptance_payload["threshold"] = 0.65
        acceptance_payload["comparator"] = "lte"
        acceptance_path.write_text(json.dumps(acceptance_payload), encoding="utf-8")
        try:
            baseline._load_acceptance(acceptance_path)
        except RuntimeError as exc:
            assert "comparator" in str(exc)
        else:
            raise AssertionError("mAP@50 lte comparator was accepted")


def assert_cheapest_improvement_order() -> None:
    """Require the shared improvement ladder to remain cheapest-first."""
    path = RESOURCES / "fde-methodology.md"
    text = read(path)
    markers = (
        "Confidence-threshold sweep",
        "Preprocessing or crop change",
        "Model or backbone switch",
        "Fine-tune a relevant checkpoint",
        "Label expansion or full custom data collection",
    )
    positions = [text.index(marker) for marker in markers]
    assert positions == sorted(positions), "improvement order is not cheapest-first"


def assert_routing_and_delegation() -> None:
    """Require output routing and a contradiction-free provider stop boundary."""
    lookup_path = RESOURCES / "roboflow-platform-lookup.md"
    lookup = read(lookup_path)
    for phrase in (
        "Platform action handshake",
        "Delegate read-only discovery",
        "fallback is scaffold-only",
        "Sentinel does not invoke the action",
        "Do not invoke uploads, dataset mutations, paid training, deployment, deletion",
    ):
        require(lookup, phrase, lookup_path)

    forbidden_provider_patterns = (
        r"delegate.*execution",
        r"delegate upload",
        r"perform any confirmed",
        r"hosted data movement not approved",
        r"paid(?:/data-moving| or destructive)? action lacks.*consent",
    )
    for skills_root in SKILL_ROOTS:
        for name in BUILD_SKILLS:
            path = skills_root / name / "SKILL.md"
            text = read(path)
            require(text, "Platform execution boundary", path)
            require(text, "../../resources/roboflow-platform-lookup.md", path)
            for pattern in forbidden_provider_patterns:
                reject(text, pattern, path)

    fde_path = RESOURCES / "fde-methodology.md"
    fde = read(fde_path)
    require(fde, "conversational consent does not authorize Sentinel", fde_path)
    for pattern in forbidden_provider_patterns:
        reject(fde, pattern, fde_path)

    solver_path = SKILLS / "solve-cv-task" / "SKILL.md"
    solver = read(solver_path)
    for phrase in (
        "per-person PPE",
        "whole-image compliance",
        "calibrated physical measurement",
        "deliver-cv-project",
    ):
        require(solver, phrase, solver_path)

    detect_path = SKILLS / "detect-and-analyze" / "SKILL.md"
    reject(read(detect_path), r"measure-in-image", detect_path)

    classify_path = SKILLS / "classify-or-flag" / "SKILL.md"
    classify = read(classify_path)
    require(classify, "one verdict for the whole image", classify_path)
    require(classify, "per-person PPE", classify_path)


def assert_skill_surface_and_ledger() -> None:
    """Require only user workflows to be discoverable and ledger ownership to be unique."""
    internal_dir = SKILLS / "_shared"
    if internal_dir.exists():
        raise AssertionError("skills/_shared exposes internal resources in the skill root")

    delivery_path = SKILLS / "deliver-cv-project" / "SKILL.md"
    delivery = read(delivery_path)
    for phrase in (
        "TRIGGER when:",
        "SKIP when:",
        "delivery-handoff",
        "acceptance_id",
        "artifact_kind",
    ):
        require(delivery, phrase, delivery_path)

    ledger_path = RESOURCES / "ledger-protocol.md"
    ledger = read(ledger_path)
    for phrase in (
        '"event_id"',
        '"status"',
        '"source"',
        "hook-covered MCP actions",
        "Unknown is never success",
        "absolute path of this loaded file",
        "--ledger",
    ):
        require(ledger, phrase, ledger_path)


def assert_host_skill_rosters() -> None:
    """Require every methodology-covered workflow on both host roots."""
    for skills_root in SKILL_ROOTS:
        for name in (*BUILD_SKILLS, "solve-cv-task", "deliver-cv-project"):
            path = skills_root / name / "SKILL.md"
            text = read(path)
            require(text, "TRIGGER when:", path)
            require(text, "SKIP when:", path)


def main() -> int:
    """Run all methodology assertions and return a shell status."""
    checks = (
        assert_independent_acceptance,
        assert_immutable_thresholds,
        assert_baseline_matching_and_redaction,
        assert_cheapest_improvement_order,
        assert_routing_and_delegation,
        assert_skill_surface_and_ledger,
        assert_host_skill_rosters,
    )
    for check in checks:
        check()
        print(f"PASS {check.__name__}")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except AssertionError as exc:
        print(f"methodology contract failed: {exc}", file=sys.stderr)
        raise SystemExit(1) from exc
