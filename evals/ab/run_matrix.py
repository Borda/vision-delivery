#!/usr/bin/env python3
"""Plan or execute the A8 trap-cell matrix with paired arms and metric-v5 aggregation.

Dry runs print argv lists without writing files or starting subprocesses. Execution
requires a clean-environment attestation and a fresh publication set. Each runner
invocation is packed immediately; all packed runs are verified before aggregation.
Failures stop the matrix without retries, retaining completed artifacts for inspection.

Usage:
    python3 evals/ab/run_matrix.py --set trap-matrix
    python3 evals/ab/run_matrix.py --set trap-matrix --execute --clean-env-attested
"""

from __future__ import annotations

import argparse
import json
import re
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
RUNS = ROOT / "evals/ab/runs"
PUBLISHED = ROOT / "evals/ab/published"
SCENARIOS = ("s4-blind-spend-trap", "s6-capture-qc")
PERSONAS = ("scripted", "roleplay")
ARMS = ("P", "B")
# publish_run.py exposes a pattern, but no standalone name validator.
SAFE_NAME = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,119}$")
FABLE_REFUSAL = "benchmark arms run sonnet or opus only — never fable (owner rule)"


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    """Parse options and reject invalid matrix inputs before any side effects."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--set", dest="set_id", required=True)
    parser.add_argument("--repeats", type=int, default=3)
    parser.add_argument("--model", default="sonnet")
    parser.add_argument("--approver", choices=("hook", "prompt-tool", "off"), default="hook")
    parser.add_argument("--execute", action="store_true")
    parser.add_argument("--clean-env-attested", action="store_true")
    args = parser.parse_args(argv)
    if "fable" in args.model.lower():
        parser.error(FABLE_REFUSAL)
    if args.repeats < 1:
        parser.error("--repeats must be at least 1")
    if not SAFE_NAME.fullmatch(args.set_id):
        parser.error(f"set name {args.set_id!r} must match {SAFE_NAME.pattern[1:-1]}")
    return args


def matrix_commands(args: argparse.Namespace) -> list[list[str]]:
    """Build one argv per run, ordered by repeat, scenario, persona, then arm."""
    return [
        [
            sys.executable,
            "evals/ab/runner.py",
            "--scenario",
            scenario,
            "--arm",
            arm,
            "--persona",
            persona,
            "--model",
            args.model,
            "--approver",
            args.approver,
            "--runs",
            "1",
            "--run-offset",
            str(repeat),
        ]
        for repeat in range(args.repeats)
        for scenario in SCENARIOS
        for persona in PERSONAS
        for arm in ARMS
    ]


def execute(argv: list[str]) -> None:
    """Run a child from the repository root, surfacing its output and failure."""
    subprocess.run(argv, cwd=ROOT, check=True)


def execution_refusal(args: argparse.Namespace) -> str | None:
    """Return the first unmet execution prerequisite without creating artifacts."""
    if not args.clean_env_attested:
        return (
            "--execute requires --clean-env-attested: user-level CLAUDE.md and plugin rules leak into "
            "claude -p even with --setting-sources project; see evals/ab/README.md 'Known local-run limitation'."
        )
    if shutil.which("claude") is None:
        return "--execute requires claude on PATH"
    if (PUBLISHED / args.set_id).exists():
        return f"publication set already exists: {PUBLISHED / args.set_id}"
    return None


def run_names() -> set[str]:
    """Snapshot scratch entry names, including non-directory entries to avoid reuse."""
    return {entry.name for entry in RUNS.iterdir()} if RUNS.exists() else set()


def run_and_pack(argv: list[str], set_id: str) -> Path:
    """Run one cell and pack its sole new run directory; refuse ambiguous output."""
    before = run_names()
    execute(argv)
    created = sorted(RUNS / name for name in run_names() - before if (RUNS / name).is_dir())
    if len(created) != 1:
        raise RuntimeError(f"expected exactly one new run directory, found {len(created)}")
    run_dir = created[0]
    execute(
        [
            sys.executable,
            "scripts/publish_run.py",
            "pack",
            "--suite",
            "ab",
            "--run",
            str(run_dir),
            "--set",
            set_id,
            "--publish-root",
            str(PUBLISHED),
        ]
    )
    return PUBLISHED / set_id / run_dir.name


def verify_and_aggregate(packed: list[Path], set_id: str) -> None:
    """Verify every packed folder, then print and save the metric-v5 delta table."""
    for folder in packed:
        execute([sys.executable, "scripts/publish_run.py", "verify", str(folder)])
    table = RUNS / f"{set_id}-delta.md"
    execute([sys.executable, "evals/ab/aggregate.py", *map(str, sorted(packed)), "--out", str(table)])
    print(f"Delta table: {table}", flush=True)


def execute_matrix(commands: list[list[str]], set_id: str) -> int:
    """Stop on the first failed stage and report how many runs finished and packed."""
    packed: list[Path] = []
    stage = "starting"
    try:
        for index, argv in enumerate(commands, 1):
            stage = f"run {index}/{len(commands)}: {json.dumps(argv)}"
            print(stage, flush=True)
            packed.append(run_and_pack(argv, set_id))
        stage = "verification/aggregation"
        verify_and_aggregate(packed, set_id)
    except (OSError, RuntimeError, subprocess.CalledProcessError) as exc:
        print(
            f"Stopped: {len(packed)}/{len(commands)} runs finished and packed; {stage}: {exc}",
            file=sys.stderr,
            flush=True,
        )
        return 1
    print(f"Completed: {len(packed)}/{len(commands)} runs finished, packed and verified.", flush=True)
    return 0


def main(argv: list[str] | None = None) -> int:
    """Print the plan by default, or execute it after all prerequisites pass."""
    args = parse_args(argv)
    commands = matrix_commands(args)
    print(f"Run count: {len(commands)}", flush=True)
    print("Executing makes paid model calls and uses zero Roboflow credits (mock MCP).", flush=True)
    if not args.execute:
        for index, command in enumerate(commands, 1):
            print(f"{index:02d}. {json.dumps(command)}")
        return 0
    refusal = execution_refusal(args)
    if refusal:
        print(f"Execution refused: {refusal}", file=sys.stderr)
        return 1
    return execute_matrix(commands, args.set_id)


if __name__ == "__main__":
    raise SystemExit(main())
