#!/usr/bin/env python3
"""Check that every sample on the docs sample-output page is what the shipped tools print.

The page shows gate decisions, a ledger-helper refusal, and scorer lines. Each sample sits in
a fenced block under a ``<!-- sample: <name> -->`` marker. This script runs the real hook,
helper, and scorer on fixtures, and fails when a block on the page differs from their output,
so the page cannot drift from the code. It also checks the two scorer lines quoted in
``examples/first-baseline/README.md``.

Usage:
    python3 evals/docs/assert_sample_output.py           # compare the page with fresh output
    python3 evals/docs/assert_sample_output.py --print   # print fresh output for every sample
"""

from __future__ import annotations

import argparse
import doctest
import json
import os
import re
import subprocess
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
PAGE = ROOT / "docs" / "sample-output.md"
GATE = ROOT / "hooks" / "gate.js"
LEDGER_HELPER = ROOT / "scripts" / "ledger_append.py"
SCORER = ROOT / "resources" / "scripts" / "score_baseline.py"
EXAMPLE = ROOT / "examples" / "first-baseline"
#: Price date printed on the page; the helper needs today's date, so fresh output is mapped back to it.
SAMPLE_DATE = "2026-11-10"
SAMPLE_BLOCK = re.compile(r"<!-- sample: ([a-z0-9-]+) -->\n+```text\n(.*?)\n```", re.DOTALL)
BRIEF_FIELDS = {
    "--scope": "train a detection model on project pallets, version 3",
    "--cost-amount": "10",
    "--cost-unit": "credits",
    "--cost-source": "Roboflow plans-and-pricing skill, training table",
    "--data-movement": "none; the dataset is already in the workspace",
    "--rollback": "cancel the training job; spent credits are not refunded",
}
BUDGET_FIELDS = {
    **BRIEF_FIELDS,
    "--scope": "score the candidate model on the 40 gold images, one image per call",
    "--cost-amount": "40",
    "--cost-source": "Roboflow plans-and-pricing skill, hosted inference table",
    "--data-movement": "40 gold images are sent to hosted inference",
    "--rollback": "nothing to undo; inference changes no provider state",
}


def _environment() -> dict[str, str]:
    """Return the process environment without a declared project directory."""
    return {name: value for name, value in os.environ.items() if name != "CLAUDE_PROJECT_DIR"}


def gate_reason(project: Path, tool: str, mode: str = "default") -> str:
    """Run the PreToolUse gate for one Roboflow tool call and return its decision and reason."""
    payload = {
        "hook_event_name": "PreToolUse",
        "tool_name": f"mcp__roboflow__{tool}",
        "tool_input": {},
        "permission_mode": mode,
    }
    done = subprocess.run(
        ["node", str(GATE)],
        cwd=project,
        env=_environment(),
        input=json.dumps(payload),
        capture_output=True,
        text=True,
        check=True,
    )
    decision = json.loads(done.stdout)["hookSpecificOutput"]
    return f"{decision['permissionDecision']}: {decision['permissionDecisionReason']}"


def record_brief(
    project: Path,
    operation: str,
    event: str,
    *extra: str,
    omit: str = "",
    values: dict[str, str] | None = None,
) -> str:
    """Record one action brief with the ledger helper and return what it printed on stderr."""
    today = datetime.now(timezone.utc).date().isoformat()
    fields = [part for flag, value in (values or BRIEF_FIELDS).items() if flag != omit for part in (flag, value)]
    command = [
        sys.executable,
        str(LEDGER_HELPER),
        "--session",
        "demo",
        "--skill",
        "detect-and-analyze",
        "--action",
        "action_brief_emitted",
        "--operation",
        operation,
        "--event-id",
        f"manual:demo:brief:{event}",
        "--status",
        "success",
        "--cost-as-of",
        today,
        *fields,
        *extra,
    ]
    done = subprocess.run(command, cwd=project, env=_environment(), capture_output=True, text=True, check=False)
    return done.stderr.strip().splitlines()[-1].replace(today, SAMPLE_DATE) if done.stderr.strip() else ""


def scorer_line(pred: Path) -> str:
    """Score the committed example against an 85% target and return the plain verdict line."""
    command = [
        sys.executable,
        str(SCORER),
        "--gold",
        str(EXAMPLE / "gold.example.jsonl"),
        "--pred",
        str(pred),
        "--task",
        "count",
        "--metric",
        "catch_rate",
        "--comparator",
        "gte",
        "--threshold",
        "0.85",
    ]
    done = subprocess.run(command, capture_output=True, text=True, check=True)
    return done.stdout.splitlines()[0]


def fresh_samples() -> dict[str, str]:
    """Run the shipped tools on fixtures and return every sample by name."""
    today = datetime.now(timezone.utc).date().isoformat()
    samples: dict[str, str] = {}
    with tempfile.TemporaryDirectory() as raw:
        project = Path(raw)
        (project / ".vision-delivery").mkdir()
        samples["gate-denied"] = gate_reason(project, "trainings_create")
        samples["brief-rejected"] = record_brief(project, "trainings_create", "1", omit="--cost-source")
        record_brief(project, "trainings_create", "1")
        samples["gate-prompt"] = gate_reason(project, "trainings_create").replace(today, SAMPLE_DATE)
        samples["gate-no-prompt-mode"] = gate_reason(project, "trainings_create", "bypassPermissions")
        record_brief(project, "models_infer", "2", "--call-budget", "40", values=BUDGET_FIELDS)
        samples["gate-budget-prompt"] = gate_reason(project, "models_infer").replace(today, SAMPLE_DATE)

        predictions = EXAMPLE / "pred-rung0.example.jsonl"
        samples["scorer-inconclusive"] = scorer_line(predictions)
        short = project / "pred-short.jsonl"
        lines = predictions.read_text(encoding="utf-8").splitlines()
        short.write_text("\n".join(lines[:-1]) + "\n", encoding="utf-8", newline="\n")
        samples["scorer-no-verdict"] = scorer_line(short)
    return samples


def page_samples(text: str) -> tuple[dict[str, str], list[str]]:
    """Return the samples on the docs page by marker name, and the page's structural problems.

    Every fenced block on the page must be a marked sample, and a marker name may appear once,
    so no unchecked output can sit on the page beside the checked ones.

    Examples:
        >>> block = "<!-- sample: a -->\\n\\n```text\\nx\\n```\\n"
        >>> page_samples(block)
        ({'a': 'x'}, [])
        >>> page_samples(block + block)[1]
        ['sample a appears 2 times']
        >>> page_samples(block + "```text\\nunchecked\\n```\\n")[1]
        ['page has 2 code blocks but 1 marked samples; every code block must sit under a sample marker']
    """
    found = SAMPLE_BLOCK.findall(text)
    names = [name for name, _ in found]
    problems = [
        f"sample {name} appears {names.count(name)} times" for name in sorted(set(names)) if names.count(name) > 1
    ]
    fences = len(re.findall(r"^\s*```", text, flags=re.MULTILINE)) // 2
    if fences != len(found):
        problems.append(
            f"page has {fences} code blocks but {len(found)} marked samples; "
            "every code block must sit under a sample marker"
        )
    return dict(found), problems


def main() -> int:
    """Compare the docs page with fresh tool output, or print the fresh output."""
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--print", action="store_true", dest="show", help="print fresh output for every sample")
    args = parser.parse_args()

    fresh = fresh_samples()
    if args.show:
        for name, body in fresh.items():
            print(f"<!-- sample: {name} -->\n\n```text\n{body}\n```\n")
        return 0

    shown, problems = page_samples(PAGE.read_text(encoding="utf-8"))
    problems += [f"page lacks sample {name}" for name in fresh if name not in shown]
    problems += [f"page has unknown sample {name}" for name in shown if name not in fresh]
    for name in fresh.keys() & shown.keys():
        if fresh[name] != shown[name]:
            problems.append(f"sample {name} differs\n  page:  {shown[name]}\n  tools: {fresh[name]}")
    # The example's own README quotes the same two scorer lines, and the quick start quotes one.
    example_readme = (EXAMPLE / "README.md").read_text(encoding="utf-8")
    for name in ("scorer-inconclusive", "scorer-no-verdict"):
        if fresh[name] not in example_readme:
            problems.append(f"examples/first-baseline/README.md does not quote the current {name} line: {fresh[name]}")
    if fresh["scorer-inconclusive"] not in (ROOT / "docs" / "quickstart.md").read_text(encoding="utf-8"):
        problems.append(f"docs/quickstart.md does not quote the current count line: {fresh['scorer-inconclusive']}")
    doctest_failures, _ = doctest.testmod()
    if doctest_failures:
        problems.append(f"{doctest_failures} doctest failure(s) in this check")
    if problems:
        print("sample-output page is out of date:", file=sys.stderr)
        print("\n".join(f"- {problem}" for problem in problems), file=sys.stderr)
        return 1
    print(f"sample-output page matches the shipped tools ({len(fresh)} samples)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
