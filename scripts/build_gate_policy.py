#!/usr/bin/env python3
"""Generate the PreToolUse gate policy from a provider's published MCP tool catalog.

The gate (``hooks/gate.js``) never guesses from a tool name. It looks the tool up in
``hooks/gate-policy.json``, which this script derives from the provider's own tool
annotations plus the reviewed rules in ``scripts/gate_policy_rules.json``:

- a tool the provider marks ``readOnlyHint: true`` is ``open`` (no brief needed);
- every other tool, and every tool without that annotation, is ``brief``
  (one action brief per execution);
- an override with a written reason may gate a read-only tool (``brief``), or move a tool
  to ``budget`` (one brief with a stated call budget); no override can open a tool the
  provider does not mark read-only;
- a tool that is not in the policy at all is treated as ``brief`` by the gate.

The file format is provider-neutral: nothing in it is specific to one MCP server.

Usage:
    # At release time, from a freshly downloaded catalog:
    python3 scripts/build_gate_policy.py --catalog roboflow-cowork-tools.json \
        --release cowork-catalog-2c8dbbd --as-of 2026-11-10 --expect-sha256 <digest>

    # After editing the rules only (re-applies them to the recorded annotations):
    python3 scripts/build_gate_policy.py

    # In CI: fail when the committed policy differs from what the rules produce.
    python3 scripts/build_gate_policy.py --check
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
from datetime import date
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
POLICY_PATH = ROOT / "hooks" / "gate-policy.json"
RULES_PATH = ROOT / "scripts" / "gate_policy_rules.json"
SCHEMA_VERSION = 1
CLASSES = ("open", "brief", "budget")
DEFAULT_CLASS = "brief"
DEFAULT_CATEGORY = "other"
TOOL_NAME = re.compile(r"^[A-Za-z0-9_-]{1,200}$")


class PolicyError(ValueError):
    """Raised when the catalog or the rules cannot produce a trustworthy policy."""


def _load_json(path: Path) -> Any:
    """Read one JSON document, reporting an unusable file as a policy error."""
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise PolicyError(f"cannot read {path}: {exc}") from exc


def read_catalog(path: Path, expect_sha256: str | None) -> tuple[dict[str, bool], str]:
    """Return each catalog tool's read-only flag and the catalog file digest.

    A tool with no ``readOnlyHint`` annotation is recorded as not read-only, so it is gated.

    Args:
        path: Provider catalog JSON with a top-level ``tools`` list.
        expect_sha256: Digest the provider pins for this catalog; checked when given.

    Returns:
        Mapping of tool name to read-only flag, and the SHA-256 of the catalog bytes.
    """
    try:
        raw = path.read_bytes()
    except OSError as exc:
        raise PolicyError(f"cannot read catalog {path}: {exc}") from exc
    digest = hashlib.sha256(raw).hexdigest()
    if expect_sha256 and digest != expect_sha256.lower():
        raise PolicyError(f"catalog digest {digest} does not match the expected {expect_sha256}")
    try:
        document = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise PolicyError(f"catalog is not JSON: {exc}") from exc
    tools = document.get("tools") if isinstance(document, dict) else document
    if not isinstance(tools, list) or not tools:
        raise PolicyError("catalog has no tools list")
    flags: dict[str, bool] = {}
    for tool in tools:
        name = tool.get("name") if isinstance(tool, dict) else None
        if not isinstance(name, str) or not TOOL_NAME.match(name):
            raise PolicyError(f"catalog tool has an unusable name: {name!r}")
        if name in flags:
            raise PolicyError(f"catalog lists {name} twice")
        annotations = tool.get("annotations")
        hint = annotations.get("readOnlyHint") if isinstance(annotations, dict) else None
        flags[name] = hint is True
    return flags, digest


def flags_digest(flags: dict[str, bool]) -> str:
    """Return a digest of every tool's read-only flag, recorded in the policy provenance.

    A policy edited by hand to flip a flag no longer matches this digest, so the offline
    check fails without the catalog. It does not stop an edit that also rewrites the digest;
    the release-time comparison against the catalog covers that.

    Examples:
        >>> flags_digest({"b_write": False, "a_list": True}) == flags_digest({"a_list": True, "b_write": False})
        True
        >>> flags_digest({"a_list": True}) == flags_digest({"a_list": False})
        False
    """
    lines = "".join(f"{name}\t{int(flags[name])}\n" for name in sorted(flags))
    return hashlib.sha256(lines.encode("utf-8")).hexdigest()


def _category(name: str, rules: list[tuple[str, re.Pattern[str]]]) -> str:
    """Return the first matching reporting category for a tool name."""
    for category, pattern in rules:
        if pattern.search(name):
            return category
    return DEFAULT_CATEGORY


def _category_rules(rules: dict[str, Any]) -> list[tuple[str, re.Pattern[str]]]:
    """Compile the ordered category patterns from the rules file."""
    compiled: list[tuple[str, re.Pattern[str]]] = []
    for row in rules.get("categories", []):
        category = row.get("category") if isinstance(row, dict) else None
        pattern = row.get("pattern") if isinstance(row, dict) else None
        if not isinstance(category, str) or not category or not isinstance(pattern, str) or not pattern:
            raise PolicyError(f"category rule needs category and pattern: {row!r}")
        try:
            compiled.append((category, re.compile(pattern)))
        except re.error as exc:
            raise PolicyError(f"category pattern for {category} is invalid: {exc}") from exc
    return compiled


def _overrides(rules: dict[str, Any], flags: dict[str, bool]) -> dict[str, dict[str, str]]:
    """Validate overrides: known tool, known class, and a written reason for each."""
    overrides: dict[str, dict[str, str]] = {}
    for row in rules.get("overrides", []):
        if not isinstance(row, dict):
            raise PolicyError(f"override must be an object: {row!r}")
        tool, operation_class, reason = row.get("tool"), row.get("class"), row.get("reason")
        if tool not in flags:
            raise PolicyError(f"override names a tool that is not in the catalog: {tool!r}")
        if operation_class not in CLASSES:
            raise PolicyError(f"override for {tool} has unknown class {operation_class!r}")
        if not isinstance(reason, str) or len(reason.strip()) < 20:
            raise PolicyError(f"override for {tool} needs a written reason")
        if operation_class == "open" and not flags[tool]:
            raise PolicyError(f"override for {tool} cannot open a tool the provider does not mark read-only")
        if tool in overrides:
            raise PolicyError(f"override for {tool} is listed twice")
        overrides[tool] = {"class": operation_class, "reason": reason.strip(), "tool": tool}
    return overrides


def build_policy(flags: dict[str, bool], rules: dict[str, Any], source: dict[str, Any]) -> dict[str, Any]:
    """Apply the rules to the provider's read-only flags and return the policy document.

    Args:
        flags: Tool name to provider read-only flag.
        rules: Parsed ``gate_policy_rules.json``.
        source: Provenance of the catalog (name, release, digest, date).

    Returns:
        The policy document written to ``hooks/gate-policy.json``.

    Examples:
        >>> rules = {"provider": "demo", "schema_version": 1}
        >>> policy = build_policy({"things_list": True, "things_create": False}, rules, {})
        >>> policy["tools"]["things_list"]["class"], policy["tools"]["things_create"]["class"]
        ('open', 'brief')
    """
    if rules.get("schema_version") != SCHEMA_VERSION:
        raise PolicyError(f"rules must use schema_version {SCHEMA_VERSION}")
    provider = rules.get("provider")
    if not isinstance(provider, str) or not provider:
        raise PolicyError("rules must name the provider")
    category_rules = _category_rules(rules)
    overrides = _overrides(rules, flags)
    deployment_operations = rules.get("deployment_operations", [])
    for name in deployment_operations:
        if name not in flags or flags[name]:
            raise PolicyError(f"deployment operation {name!r} must be a catalog tool that is not read-only")
    tools: dict[str, dict[str, Any]] = {}
    for name in sorted(flags):
        operation_class = "open" if flags[name] else DEFAULT_CLASS
        if name in overrides:
            operation_class = overrides[name]["class"]
        tools[name] = {"category": _category(name, category_rules), "class": operation_class, "read_only": flags[name]}
    return {
        "default_class": DEFAULT_CLASS,
        "deployment_operations": sorted(deployment_operations),
        "overrides": [overrides[name] for name in sorted(overrides)],
        "provider": provider,
        "schema_version": SCHEMA_VERSION,
        "source": {**source, "flags_sha256": flags_digest(flags), "tool_count": len(tools)},
        "tools": tools,
    }


def policy_violations(policy: dict[str, Any]) -> list[str]:
    """List every way a policy document breaks the gate contract.

    The contract: no read-only tool is gated without a documented override, no other tool is
    open at all, and the read-only flags match the digest recorded from the catalog.

    Args:
        policy: A parsed policy document.

    Returns:
        Human-readable violations; empty when the policy holds.

    Examples:
        >>> bad = {"tools": {"things_delete": {"class": "open", "read_only": False, "category": "x"}}}
        >>> policy_violations(bad)
        ['things_delete is not read-only but is open']
    """
    violations: list[str] = []
    documented = {row.get("tool") for row in policy.get("overrides", []) if isinstance(row, dict)}
    for name, entry in sorted(policy.get("tools", {}).items()):
        operation_class, read_only = entry.get("class"), entry.get("read_only")
        if operation_class not in CLASSES:
            violations.append(f"{name} has unknown class {operation_class!r}")
        elif read_only is True and operation_class != "open" and name not in documented:
            violations.append(f"{name} is read-only but gated without a documented override")
        elif read_only is not True and operation_class == "open":
            violations.append(f"{name} is not read-only but is open")
    tools = policy.get("tools", {})
    source = policy.get("source")
    recorded = source.get("flags_sha256") if isinstance(source, dict) else None
    if recorded is not None and recorded != flags_digest(
        {name: tools[name].get("read_only") is True for name in tools}
    ):
        violations.append("read-only flags do not match the digest recorded from the catalog")
    return violations


def render(policy: dict[str, Any]) -> str:
    """Serialize a policy deterministically, in the form the JSON formatter hook keeps."""
    return json.dumps(policy, indent=2, sort_keys=True) + "\n"


def _recorded_inputs(policy_path: Path) -> tuple[dict[str, bool], dict[str, Any]]:
    """Recover the read-only flags and provenance recorded in an existing policy."""
    policy = _load_json(policy_path)
    tools = policy.get("tools") if isinstance(policy, dict) else None
    if not isinstance(tools, dict) or not tools:
        raise PolicyError(f"{policy_path} has no tools to re-derive from; pass --catalog")
    flags = {name: entry.get("read_only") is True for name, entry in tools.items()}
    recorded = policy.get("source", {}).get("flags_sha256")
    if recorded != flags_digest(flags):
        raise PolicyError(
            f"{policy_path}: read-only flags do not match the digest recorded from the catalog; "
            "regenerate with --catalog"
        )
    source = {
        key: value for key, value in policy.get("source", {}).items() if key not in ("tool_count", "flags_sha256")
    }
    return flags, source


def _inputs(args: argparse.Namespace) -> tuple[dict[str, bool], dict[str, Any]]:
    """Return read-only flags and provenance from the catalog, or from the committed policy."""
    if args.catalog is None:
        return _recorded_inputs(args.out)
    if not args.release:
        raise PolicyError("--release is required with --catalog")
    try:
        as_of = date.fromisoformat(args.as_of).isoformat() if args.as_of else date.today().isoformat()
    except ValueError as exc:
        raise PolicyError(f"--as-of must be YYYY-MM-DD: {exc}") from exc
    flags, digest = read_catalog(args.catalog, args.expect_sha256)
    return flags, {"as_of": as_of, "catalog": args.catalog.name, "release": args.release, "sha256": digest}


def main() -> int:
    """Generate or check the gate policy."""
    parser = argparse.ArgumentParser(description="Generate the gate policy from a provider tool catalog.")
    parser.add_argument("--catalog", type=Path, help="provider tool catalog JSON; omit to re-apply the rules only")
    parser.add_argument("--release", default="", help="provider release tag the catalog came from")
    parser.add_argument("--as-of", default="", help="date the catalog was pulled (YYYY-MM-DD); default today")
    parser.add_argument("--expect-sha256", default=None, help="digest the provider pins for the catalog")
    parser.add_argument("--rules", type=Path, default=RULES_PATH)
    parser.add_argument("--out", type=Path, default=POLICY_PATH)
    parser.add_argument("--check", action="store_true", help="do not write; fail when the policy would change")
    args = parser.parse_args()

    try:
        rules = _load_json(args.rules)
        if not isinstance(rules, dict):
            raise PolicyError("rules must be a JSON object")
        flags, source = _inputs(args)
        policy = build_policy(flags, rules, source)
        violations = policy_violations(policy)
        if violations:
            raise PolicyError("; ".join(violations))
        if args.check:
            if _load_json(args.out) != policy:
                print(
                    f"gate-policy-drift: {args.out} differs from the rules; rerun build_gate_policy.py", file=sys.stderr
                )
                return 1
            print(f"gate policy is current: {len(policy['tools'])} tools")
            return 0
        args.out.write_text(render(policy), encoding="utf-8", newline="\n")
    except PolicyError as exc:
        print(f"gate-policy-error: {exc}", file=sys.stderr)
        return 2

    classes = [entry["class"] for entry in policy["tools"].values()]
    summary = ", ".join(f"{classes.count(name)} {name}" for name in CLASSES)
    print(f"wrote {args.out}: {len(classes)} tools ({summary})")
    return 0


if __name__ == "__main__":
    sys.exit(main())
