#!/usr/bin/env python3
"""Contract checks for the generated gate policy and its generator.

The gate decides from ``hooks/gate-policy.json`` alone, so this file checks that the
committed policy is what the rules produce, that it holds the gate contract over every
listed tool, and that the generator fails closed on catalogs it cannot trust.

Set ``SENTINEL_TOOL_CATALOG`` to a freshly downloaded provider catalog to also check that
the committed policy still matches upstream (the release-time drift check).
"""

from __future__ import annotations

import hashlib
import importlib.util
import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path
from types import ModuleType

ROOT = Path(__file__).parents[2]
GENERATOR = ROOT / "scripts" / "build_gate_policy.py"
POLICY = ROOT / "hooks" / "gate-policy.json"
RULES = ROOT / "scripts" / "gate_policy_rules.json"
CATALOG_VARIABLE = "SENTINEL_TOOL_CATALOG"


def load_generator() -> ModuleType:
    """Load the generator script without requiring package installation."""
    spec = importlib.util.spec_from_file_location("sentinel_build_gate_policy", GENERATOR)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"could not load {GENERATOR}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def generate(*args: str) -> subprocess.CompletedProcess[str]:
    """Run the generator as a subprocess."""
    return subprocess.run([sys.executable, str(GENERATOR), *args], check=False, capture_output=True, text=True)


def write_catalog(path: Path, tools: list[dict]) -> str:
    """Write a fixture catalog and return its digest."""
    raw = json.dumps({"tools": tools}).encode()
    path.write_bytes(raw)
    return hashlib.sha256(raw).hexdigest()


def tool(name: str, read_only: bool | None) -> dict:
    """Return one catalog entry; ``None`` leaves the read-only annotation out."""
    entry: dict = {"name": name, "description": "fixture"}
    if read_only is not None:
        entry["annotations"] = {"readOnlyHint": read_only}
    return entry


def check_committed_policy(generator: ModuleType) -> None:
    """The committed policy matches the rules and holds the contract over every tool."""
    policy = json.loads(POLICY.read_text(encoding="utf-8"))
    assert policy["schema_version"] == 1
    assert policy["default_class"] == "brief"
    assert policy["source"]["tool_count"] == len(policy["tools"]) >= 300
    assert len(policy["source"]["sha256"]) == 64 and policy["source"]["release"]
    flags = {name: entry["read_only"] for name, entry in policy["tools"].items()}
    assert policy["source"]["flags_sha256"] == generator.flags_digest(flags)
    assert generator.policy_violations(policy) == []

    read_only = [name for name, entry in policy["tools"].items() if entry["read_only"]]
    writes = [name for name, entry in policy["tools"].items() if not entry["read_only"]]
    documented = {row["tool"] for row in policy["overrides"]}
    assert all(len(row["reason"]) >= 20 for row in policy["overrides"])
    gated_reads = [name for name in read_only if policy["tools"][name]["class"] != "open"]
    open_writes = [name for name in writes if policy["tools"][name]["class"] == "open"]
    assert set(gated_reads) <= documented, gated_reads
    assert open_writes == [], open_writes

    # Tools the regex classifier used to let through or block wrongly.
    for name in (
        "workflows_run",
        "workflow_specs_run",
        "batch_processing_run",
        "datasource_trigger",
        "autolabel_start",
    ):
        assert policy["tools"][name]["class"] == "brief", name
    for name in ("api_keys_create", "api_keys_revoke", "api_keys_roll", "devices_send_command", "projects_create"):
        assert policy["tools"][name]["class"] == "brief", name
    for name in ("trainings_get", "trainings_list", "versions_get", "project_deployment_get", "image_upload_status"):
        assert policy["tools"][name]["class"] == "open", name
    # Paid, data-moving, destructive, or state-changing tools: one brief per execution.
    for name in (
        "trainings_create",
        "image_upload",
        "projects_delete",
        "versions_generate",
        "project_deployment_launch",
        "project_deployment_run",
    ):
        assert policy["tools"][name]["class"] == "brief" and policy["tools"][name]["read_only"] is False, name
    # Read-only upstream, but billed per call. Single-image inference runs under a call budget;
    # media analysis also takes video, so it needs a brief for every execution.
    assert policy["tools"]["models_infer"] == {"category": "inference", "class": "budget", "read_only": True}
    assert policy["tools"]["media_analyze"] == {"category": "inference", "class": "brief", "read_only": True}
    budgeted = sorted(name for name, entry in policy["tools"].items() if entry["class"] == "budget")
    assert budgeted == ["autolabel_preview", "models_infer"], budgeted
    assert policy["tools"]["project_deployment_launch"]["category"] == "deployment"
    assert policy["tools"]["trainings_create"]["category"] == "training"
    assert policy["deployment_operations"] == ["project_deployment_launch", "workflow_version_deploy"]

    current = generate("--check")
    assert current.returncode == 0, current.stderr


def check_generator(generator: ModuleType) -> None:
    """The generator is deterministic and refuses input it cannot trust."""
    rules = json.loads(RULES.read_text(encoding="utf-8"))
    with tempfile.TemporaryDirectory() as temp_dir:
        temp = Path(temp_dir)
        catalog = temp / "catalog.json"
        digest = write_catalog(
            catalog,
            [
                tool("models_infer", True),
                tool("media_analyze", True),
                tool("project_deployment_run", False),
                tool("autolabel_preview", False),
                tool("project_deployment_launch", False),
                tool("workflow_version_deploy", False),
                tool("projects_list", True),
                tool("projects_delete", False),
                tool("mystery_tool", None),
            ],
        )
        out = temp / "policy.json"
        common = ("--catalog", str(catalog), "--release", "fixture-1", "--as-of", "2026-11-10", "--out", str(out))
        first = generate(*common, "--expect-sha256", digest)
        assert first.returncode == 0, first.stderr
        rendered = out.read_text(encoding="utf-8")
        policy = json.loads(rendered)
        fixture_flags = {name: entry["read_only"] for name, entry in policy["tools"].items()}
        assert policy["source"] == {
            "as_of": "2026-11-10",
            "catalog": "catalog.json",
            "flags_sha256": generator.flags_digest(fixture_flags),
            "release": "fixture-1",
            "sha256": digest,
            "tool_count": 9,
        }
        assert policy["tools"]["projects_list"] == {"category": "other", "class": "open", "read_only": True}
        assert policy["tools"]["projects_delete"] == {"category": "destructive", "class": "brief", "read_only": False}
        # No annotation is not proof of a read: the tool is gated.
        assert policy["tools"]["mystery_tool"] == {"category": "other", "class": "brief", "read_only": False}
        assert policy["tools"]["models_infer"]["class"] == "budget"

        assert generate(*common).returncode == 0
        assert out.read_text(encoding="utf-8") == rendered
        assert generate(*common, "--check").returncode == 0
        # Re-applying the rules to the recorded annotations reproduces the policy.
        assert generate("--out", str(out), "--check").returncode == 0

        assert generate(*common, "--expect-sha256", "0" * 64).returncode == 2
        assert generate("--catalog", str(catalog), "--out", str(out)).returncode == 2
        assert generate(*common, "--as-of", "yesterday").returncode == 2

        tampered = json.loads(rendered)
        tampered["tools"]["projects_delete"]["class"] = "open"
        out.write_text(json.dumps(tampered), encoding="utf-8")
        assert generate("--out", str(out), "--check").returncode == 1
        assert generator.policy_violations(tampered) == ["projects_delete is not read-only but is open"]

        # Flipping the read-only flag together with the class is caught without the catalog:
        # the flags no longer match the digest recorded when the policy was generated.
        flipped = json.loads(rendered)
        flipped["tools"]["projects_delete"].update({"class": "open", "read_only": True})
        out.write_text(json.dumps(flipped), encoding="utf-8")
        refused = generate("--out", str(out), "--check")
        assert refused.returncode == 2 and "do not match the digest" in refused.stderr, refused.stderr
        assert generator.policy_violations(flipped) == [
            "read-only flags do not match the digest recorded from the catalog"
        ]

        for bad_tools in (
            [],
            [tool("dup", True), tool("dup", False)],
            [tool("bad name!", True)],
            [tool("projects_list", True)],
        ):
            write_catalog(catalog, bad_tools)
            assert generate(*common).returncode == 2, bad_tools

    flags = {"things_get": True, "things_delete": False}
    base = {"provider": "demo", "schema_version": 1}
    for override in (
        {"tool": "things_missing", "class": "budget", "reason": "a long enough written reason"},
        {"tool": "things_get", "class": "allow", "reason": "a long enough written reason"},
        {"tool": "things_delete", "class": "open", "reason": "short"},
        {"tool": "things_delete", "class": "open", "reason": "a long enough written reason"},
        {"tool": "things_delete", "class": "open"},
    ):
        try:
            generator.build_policy(flags, {**base, "overrides": [override]}, {})
        except generator.PolicyError:
            continue
        raise AssertionError(f"override accepted: {override}")
    for bad_rules in (
        {**base, "schema_version": 2},
        {"schema_version": 1},
        {**base, "categories": [{"category": "x", "pattern": "("}]},
        {**base, "deployment_operations": ["things_get"]},
        {**base, "deployment_operations": ["things_missing"]},
    ):
        try:
            generator.build_policy(flags, bad_rules, {})
        except generator.PolicyError:
            continue
        raise AssertionError(f"rules accepted: {bad_rules}")
    assert rules["provider"] == "roboflow"


def check_upstream_drift() -> None:
    """With a fresh catalog at hand, the committed policy must still match upstream."""
    catalog = os.environ.get(CATALOG_VARIABLE, "")
    if not catalog:
        # The release gate (`make eval-upstream`) sets this, so a release cannot skip the comparison.
        assert not os.environ.get("SENTINEL_REQUIRE_UPSTREAM", "").strip(), (
            f"{CATALOG_VARIABLE} must name a current upstream tool catalog for a release"
        )
        print(f"note: {CATALOG_VARIABLE} is unset; upstream drift check skipped")
        return
    policy = json.loads(POLICY.read_text(encoding="utf-8"))
    source = policy["source"]
    result = generate("--catalog", catalog, "--release", source["release"], "--as-of", source["as_of"], "--check")
    assert result.returncode == 0, f"policy drifted from the upstream catalog: {result.stderr}"
    print("committed policy matches the supplied upstream catalog")


def main() -> int:
    """Run every gate policy check."""
    generator = load_generator()
    check_committed_policy(generator)
    check_generator(generator)
    check_upstream_drift()
    print("gate policy assertions passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
