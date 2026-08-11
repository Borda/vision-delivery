#!/usr/bin/env python3
"""Build Sentinel's deterministic dual-host plugin candidate.

The builder admits tracked files plus an explicit bootstrap allowlist for new
runtime helpers under review, records their SHA-256 digests and executable
modes, and writes a stable manifest. It never packages arbitrary untracked
files, reports, caches, or other source-checkout state.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
MANIFEST_NAME = "package-manifest.json"
SCHEMA_VERSION = 1
INCLUDE_DIRS = (
    ".agents",
    ".claude-plugin",
    ".codex-plugin",
    "agents",
    "assets",
    "claude-skills",
    "codex-skills",
    "hooks",
    "resources",
    "scripts",
    "shared",
)
REQUIRED_FILES = (".mcp.json", "CHANGELOG.md", "LICENSE", "NOTICE", "README.md")
BOOTSTRAP_RUNTIME_FILES = (
    "resources/scripts/freeze_acceptance.py",
    "resources/scripts/freeze_delivery_check.py",
    "resources/scripts/proof_chain.py",
    "resources/scripts/record_delivery_check.py",
    "resources/scripts/validate_proof_chain.py",
)
EXCLUDED_PARTS = frozenset(
    {
        ".cache",
        ".claude",
        ".git",
        ".mypy_cache",
        ".plans",
        ".reports",
        ".ruff_cache",
        ".temp",
        "__pycache__",
        "node_modules",
    }
)


def sha256(data: bytes) -> str:
    """Return a lowercase SHA-256 digest for exact file bytes."""
    return hashlib.sha256(data).hexdigest()


def stable_json(value: dict[str, Any]) -> bytes:
    """Encode a JSON object deterministically with a final newline."""
    return (json.dumps(value, indent=2, sort_keys=True) + "\n").encode("utf-8")


def tracked_modes(source_root: Path) -> dict[str, bool]:
    """Return reviewed runtime paths mapped to their executable bit."""
    try:
        completed = subprocess.run(
            ["git", "-C", str(source_root), "ls-files", "--stage"],
            capture_output=True,
            check=True,
            text=True,
            timeout=30,
        )
    except (FileNotFoundError, subprocess.SubprocessError) as exc:
        raise ValueError(f"cannot read tracked executable modes: {exc}") from exc

    modes: dict[str, bool] = {}
    for line in completed.stdout.splitlines():
        metadata, separator, relative = line.partition("\t")
        if not separator:
            continue
        modes[relative] = metadata.split(maxsplit=1)[0] == "100755"
    for relative in BOOTSTRAP_RUNTIME_FILES:
        path = source_root / relative
        if path.is_file() and not path.is_symlink():
            modes.setdefault(relative, bool(path.stat().st_mode & 0o111))
    return modes


def is_payload_path(relative: str) -> bool:
    """Return whether a tracked path belongs in the closed runtime candidate."""
    if relative in REQUIRED_FILES:
        return True
    parts = relative.split("/")
    return (
        parts[0] in INCLUDE_DIRS
        and not any(part in EXCLUDED_PARTS for part in parts)
        and not relative.endswith((".pyc", ".pyo"))
    )


def skill_roster(source_root: Path, root_name: str) -> list[str]:
    """Return the sorted roster of directories containing a `SKILL.md` file."""
    skills_root = source_root / root_name
    if not skills_root.is_dir():
        return []
    return sorted(child.name for child in skills_root.iterdir() if (child / "SKILL.md").is_file())


def write_file(path: Path, data: bytes, executable: bool) -> None:
    """Write one candidate file with a normalized portable mode."""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(data)
    path.chmod(0o755 if executable else 0o644)


def reject_symlinked_output_path(output: Path) -> Path:
    """Return an absolute output path after rejecting untrusted symlink segments."""
    output = output.absolute()
    temp_root = Path(tempfile.gettempdir()).absolute()
    trusted_temp_ancestors = {temp_root, *temp_root.parents}
    for candidate in (output, *output.parents):
        try:
            if candidate.is_symlink() and candidate not in trusted_temp_ancestors:
                raise ValueError(f"output path may not contain a symlink: {candidate}")
        except OSError as exc:
            raise ValueError(f"cannot inspect output path {candidate}: {exc}") from exc
    return output


def ensure_safe_output(source_root: Path, output: Path) -> None:
    """Reject destinations whose replacement could escape the intended tree."""
    output = reject_symlinked_output_path(output)
    if output == Path(output.anchor):
        raise ValueError("output may not be a filesystem root")
    if output == source_root or source_root.is_relative_to(output):
        raise ValueError("output may not contain the source root")
    if output.exists():
        raise ValueError("output must not already exist")


def build_package(source_root: Path, output: Path) -> dict[str, Any]:
    """Build a candidate from tracked runtime files and return its manifest.

    Args:
        source_root: Repository root providing the tracked plugin files.
        output: Missing destination directory for the candidate.

    Returns:
        Deterministic package manifest with identity, host rosters, and files.

    Raises:
        ValueError: If a required runtime file is absent or a selected path is a
            symlink rather than a regular tracked file.
    """
    source_root = source_root.resolve()
    output = output.absolute()
    ensure_safe_output(source_root, output)
    modes = tracked_modes(source_root)
    missing = [name for name in REQUIRED_FILES if name not in modes]
    if missing:
        raise ValueError(f"required package files are not tracked: {', '.join(missing)}")

    payload = sorted(relative for relative in modes if is_payload_path(relative))
    output.mkdir(parents=True)

    records: list[dict[str, Any]] = []
    for relative in payload:
        source = source_root / relative
        if source.is_symlink():
            raise ValueError(f"symlink payload is not allowed: {relative}")
        if not source.is_file():
            raise ValueError(f"tracked package file is missing: {relative}")
        data = source.read_bytes()
        write_file(output / relative, data, modes[relative])
        records.append({"path": relative, "sha256": sha256(data), "executable": modes[relative]})

    claude_manifest = json.loads((source_root / ".claude-plugin" / "plugin.json").read_text(encoding="utf-8"))
    package_manifest = {
        "schema_version": SCHEMA_VERSION,
        "name": claude_manifest["name"],
        "version": claude_manifest["version"],
        "skills": {
            "claude": skill_roster(source_root, "claude-skills"),
            "codex": skill_roster(source_root, "codex-skills"),
        },
        "files": records,
    }
    write_file(output / MANIFEST_NAME, stable_json(package_manifest), executable=False)
    return package_manifest


def tree_bytes(root: Path) -> dict[str, bytes]:
    """Return candidate file bytes keyed by normalized relative paths."""
    return {path.relative_to(root).as_posix(): path.read_bytes() for path in sorted(root.rglob("*")) if path.is_file()}


def check_determinism(source_root: Path, output: Path) -> list[str]:
    """Build a temporary candidate and report byte differences from `output`."""
    output = reject_symlinked_output_path(output)
    if not output.is_dir():
        return [f"missing candidate: {output}"]
    with tempfile.TemporaryDirectory(prefix="sentinel-package-check-") as temporary:
        rebuilt = Path(temporary) / "candidate"
        build_package(source_root, rebuilt)
        expected = tree_bytes(output)
        actual = tree_bytes(rebuilt)
    differences = sorted(set(expected) ^ set(actual))
    differences.extend(path for path in sorted(set(expected) & set(actual)) if expected[path] != actual[path])
    return differences


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    """Parse builder command-line options."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", required=True, type=Path, help="candidate directory")
    parser.add_argument(
        "--source-root",
        type=Path,
        default=ROOT,
        help="plugin source root (default: repo)",
    )
    parser.add_argument("--check", action="store_true", help="rebuild and byte-compare")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    """Build or deterministically re-check a Sentinel package candidate."""
    args = parse_args(argv)
    source_root = args.source_root.resolve()
    output = args.out.absolute()
    try:
        if args.check:
            differences = check_determinism(source_root, output)
            if differences:
                print(
                    "non-deterministic package: " + ", ".join(differences),
                    file=sys.stderr,
                )
                return 1
            print("package build is deterministic")
            return 0
        manifest = build_package(source_root, output)
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        print(f"build-package-error: {exc}", file=sys.stderr)
        return 2
    print(f"built {manifest['name']} {manifest['version']}: {len(manifest['files'])} files -> {output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
