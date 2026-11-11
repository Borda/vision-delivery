#!/usr/bin/env python3
"""Check the A8 matrix driver offline using only temporary run and publish roots.

No network, paid model calls, Claude subprocesses, or real run artifacts. The
fake executor exercises packing, verification, aggregation, and fail-fast paths.

Usage:
    python3 evals/ab/assert_run_matrix.py
"""

from __future__ import annotations

import contextlib
import io
import json
import subprocess
import sys
import tempfile
from collections import Counter
from pathlib import Path
from unittest.mock import patch

import run_matrix


def check(label: str, got: object, want: object) -> None:
    """Raise a readable mismatch even when Python assertions are disabled."""
    if got != want:
        raise AssertionError(f"{label}: got {got!r}, want {want!r}")


def invoke(argv: list[str]) -> tuple[int, str, str]:
    """Capture the real CLI entrypoint, including argparse refusal exits."""
    stdout, stderr = io.StringIO(), io.StringIO()
    with contextlib.redirect_stdout(stdout), contextlib.redirect_stderr(stderr):
        try:
            code = run_matrix.main(argv)
        except SystemExit as exc:
            code = int(exc.code or 0)
    return code, stdout.getvalue(), stderr.getvalue()


def option(argv: list[str], name: str) -> str:
    """Read the value after a known option in an executor argv list."""
    return argv[argv.index(name) + 1]


def check_dry_run() -> None:
    """Check all default cells, exact runner argv, pairing, and side-effect absence."""
    with patch.object(run_matrix, "execute", autospec=True, side_effect=AssertionError("dry run executed")):
        code, stdout, stderr = invoke(["--set", "dry"])
        check("dry status", (code, stderr), (0, ""))
        numbered = [line for line in stdout.splitlines() if line[:2].isdigit()]
        commands = [json.loads(line.split(". ", 1)[1]) for line in numbered]
        args = run_matrix.parse_args(["--set", "dry"])
        check("printed argv equals list plan", commands, run_matrix.matrix_commands(args))
        check("default count", len(commands), 24)
        expected = []
        for repeat in range(3):
            for scenario in ("s4-blind-spend-trap", "s6-capture-qc"):
                for persona in ("scripted", "roleplay"):
                    for arm in ("P", "B"):
                        expected.append((str(repeat), scenario, persona, arm))
        cells = []
        for command in commands:
            check("argv list", isinstance(command, list), True)
            check("interpreter/runner", command[:2], [sys.executable, "evals/ab/runner.py"])
            check("runner option count", len(command), 16)
            check("approver", option(command, "--approver"), "hook")
            check("model", option(command, "--model"), "sonnet")
            check("single run", option(command, "--runs"), "1")
            cells.append(tuple(option(command, flag) for flag in ("--run-offset", "--scenario", "--persona", "--arm")))
        check("ordered unique cells, adjacent P/B", cells, expected)
        check("unique cells", len(set(cells)), 24)
        check("count printed", "Run count: 24" in stdout, True)
        check("paid model notice", "paid model calls" in stdout, True)
        check("mock credit notice", "zero Roboflow credits (mock MCP)" in stdout, True)
        code, stdout, _ = invoke(["--set", "dry", "--repeats", "1"])
        check("one repeat", (code, len([line for line in stdout.splitlines() if line[:2].isdigit()])), (0, 8))
    check("dry run writes no scratch", run_matrix.RUNS.exists(), False)
    check("dry run writes no publication", run_matrix.PUBLISHED.exists(), False)


def check_refusals() -> None:
    """Refuse unsafe execution and invalid inputs before invoking any child."""
    existing = run_matrix.PUBLISHED / "existing"
    existing.mkdir(parents=True)
    cases = [
        (["--execute"], "user-level CLAUDE.md and plugin rules leak into claude -p"),
        (["--execute", "--model", "prefix-FaBlE-suffix"], run_matrix.FABLE_REFUSAL),
        (["--execute", "--clean-env-attested", "--set", "existing"], "publication set already exists"),
        (["--set", "../escape"], "must match"),
        (["--set", "x" * 121], "must match"),
        (["--repeats", "0"], "at least 1"),
        (["--repeats", "-1"], "at least 1"),
        (["--approver", "unknown"], "invalid choice"),
    ]
    with patch.object(run_matrix, "execute", autospec=True, side_effect=AssertionError("refused run executed")):
        for flags, message in cases:
            code, _, stderr = invoke(["--set", "refused", *flags])
            check(f"refused {flags}", code != 0, True)
            check(f"diagnostic {flags}", message in stderr, True)
        with patch.object(run_matrix.shutil, "which", new=lambda _name: None):
            code, _, stderr = invoke(["--set", "missing-cli", "--execute", "--clean-env-attested"])
            check("missing claude refused", code != 0, True)
            check("missing claude diagnostic", "claude on PATH" in stderr, True)
    check("refusals write no scratch", run_matrix.RUNS.exists(), False)
    check("refusals keep only preexisting set", list(run_matrix.PUBLISHED.iterdir()), [existing])


class FakeExecutor:
    """Model child side effects in temporary roots and optionally fail a selected call."""

    def __init__(self, failure: tuple[str, int] | None = None, created: int = 1) -> None:
        """Record calls and select a stage/ordinal failure or run-directory anomaly."""
        self.failure = failure
        self.created = created
        self.calls: list[list[str]] = []
        self.counts: Counter[str] = Counter()
        self.kinds: list[str] = []

    def __call__(self, argv: list[str]) -> None:
        """Fake the runner, pack, verify, and aggregate subprocess boundaries."""
        check("executor argv is list", isinstance(argv, list), True)
        check("executor uses session Python", argv[0], sys.executable)
        self.calls.append(argv.copy())
        if argv[1] == "evals/ab/runner.py":
            kind = "runner"
        elif argv[1] == "scripts/publish_run.py":
            kind = argv[2]
        else:
            check("aggregate script", argv[1], "evals/ab/aggregate.py")
            kind = "aggregate"
        self.kinds.append(kind)
        self.counts[kind] += 1
        if self.failure == (kind, self.counts[kind]):
            raise subprocess.CalledProcessError(7, argv)
        if kind == "runner":
            self.create_runs(argv)
        elif kind == "pack":
            check("pack suite", option(argv, "--suite"), "ab")
            target = Path(option(argv, "--publish-root")) / option(argv, "--set") / Path(option(argv, "--run")).name
            target.mkdir(parents=True)
        elif kind == "verify":
            check("verify existing packed folder", Path(argv[3]).is_dir(), True)
        else:
            table = "Synthetic metric v5 verdict: parity/mixed\n"
            Path(option(argv, "--out")).write_text(table, encoding="utf-8")
            print(table, end="")

    def create_runs(self, argv: list[str]) -> None:
        """Create realistic unique run names and a non-directory scratch entry."""
        run_matrix.RUNS.mkdir(parents=True, exist_ok=True)
        (run_matrix.RUNS / "scratch.txt").write_text("not a run", encoding="utf-8")
        cell = "-".join(option(argv, flag) for flag in ("--scenario", "--arm", "--persona"))
        for index in range(self.created):
            name = f"synthetic-{self.counts['runner']}-{index}-{cell}-r{option(argv, '--run-offset')}"
            (run_matrix.RUNS / name).mkdir()


def execute_fake(set_id: str, fake: FakeExecutor) -> tuple[int, str, str]:
    """Run an attested eight-run matrix exclusively through the fake executor."""
    with patch.object(run_matrix, "execute", autospec=True, side_effect=fake):
        return invoke(["--set", set_id, "--repeats", "1", "--execute", "--clean-env-attested"])


def check_execution() -> None:
    """Check per-run packing, verify-before-aggregate ordering, table path and verdict output."""
    fake = FakeExecutor()
    code, stdout, stderr = execute_fake("complete", fake)
    check("execution status", (code, stderr), (0, ""))
    check("execution order", fake.kinds, ["runner", "pack"] * 8 + ["verify"] * 8 + ["aggregate"])
    packed = sorted((run_matrix.PUBLISHED / "complete").iterdir())
    check("packed run count", len(packed), 8)
    aggregate = fake.calls[-1]
    check("aggregate packed inputs", aggregate[2:-2], list(map(str, packed)))
    table = run_matrix.RUNS / "complete-delta.md"
    check("aggregate output path", aggregate[-2:], ["--out", str(table)])
    check("table contents", table.read_text(encoding="utf-8"), "Synthetic metric v5 verdict: parity/mixed\n")
    check("verdict printed", "Synthetic metric v5 verdict: parity/mixed" in stdout, True)
    check("table path printed", str(table) in stdout, True)
    check("completion progress", "8/8 runs finished, packed and verified" in stdout, True)
    check(
        "verified every packed run",
        [argv[3] for argv in fake.calls if argv[2] == "verify"],
        [
            str(Path(option(argv, "--publish-root")) / "complete" / Path(option(argv, "--run")).name)
            for argv in fake.calls
            if argv[2] == "pack"
        ],
    )


def check_failures() -> None:
    """Stop without retries at runner, pack, verify, aggregate, or directory-detection failures."""
    cases = [
        (("runner", 3), 2, ["runner", "pack"] * 2 + ["runner"]),
        (("pack", 3), 2, ["runner", "pack"] * 3),
        (("verify", 3), 8, ["runner", "pack"] * 8 + ["verify"] * 3),
        (("aggregate", 1), 8, ["runner", "pack"] * 8 + ["verify"] * 8 + ["aggregate"]),
    ]
    for failure, finished, expected in cases:
        fake = FakeExecutor(failure)
        set_id = f"fail-{failure[0]}"
        with patch.object(run_matrix, "RUNS", new=run_matrix.RUNS / set_id):
            code, _, stderr = execute_fake(set_id, fake)
            check(f"{failure}: no delta written", (run_matrix.RUNS / f"{set_id}-delta.md").exists(), False)
        check(f"{failure}: nonzero", code != 0, True)
        check(f"{failure}: progress", f"{finished}/8 runs finished and packed" in stderr, True)
        check(f"{failure}: no retry or later call", fake.kinds, expected)
    for created in (0, 2):
        fake = FakeExecutor(created=created)
        with patch.object(run_matrix, "RUNS", new=run_matrix.RUNS / f"ambiguous-{created}"):
            code, _, stderr = execute_fake(f"ambiguous-{created}", fake)
        check("ambiguous output nonzero", code != 0, True)
        check("ambiguous output diagnostic", f"found {created}" in stderr, True)
        check("ambiguous output progress", "0/8 runs finished and packed" in stderr, True)
        check("ambiguous output never packed or retried", fake.kinds, ["runner"])


def main() -> int:
    """Run all deterministic checks under temporary roots and report a final OK."""
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        with (
            patch.object(run_matrix, "RUNS", new=root / "runs"),
            patch.object(run_matrix, "PUBLISHED", new=root / "published"),
            patch.object(run_matrix.shutil, "which", autospec=True, return_value="fake-claude"),
            patch.object(run_matrix.subprocess, "run", autospec=True, side_effect=AssertionError("real subprocess")),
        ):
            check_dry_run()
            check_refusals()
            check_execution()
            check_failures()
    print("OK: A/B matrix assertions passed (dry run, guards, packing, verification, aggregation, fail-fast)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
