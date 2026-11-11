#!/usr/bin/env python3
"""Check dual-plugin routing offline with synthetic transcripts and temporary artifacts."""

from __future__ import annotations

import contextlib
import doctest
import io
import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import run_live

EXPECTED_CASES = [
    (
        "sentinel-acceptance",
        "sentinel",
        "Before we build anything, help me define what number counts as success for catching damaged boxes "
        "on our packing line, and what it would cost us to be wrong.",
    ),
    (
        "sentinel-spend",
        "sentinel",
        "Should we pay for a trained model, or is a free baseline good enough for counting pallets in my photos? "
        "Show me the evidence before spending anything.",
    ),
    (
        "roboflow-train",
        "roboflow",
        "Train an object detection model on the labeled dataset already in my Roboflow project "
        "and show me how it performs.",
    ),
    (
        "roboflow-batch",
        "roboflow",
        "Run my deployed Roboflow workflow over the 5,000 images in my cloud storage bucket.",
    ),
    ("front-door-factory", "front-door", "Here is a factory video; detect assembly mistakes for me."),
    ("front-door-camera", "front-door", "Use a factory camera to catch mistakes on the line."),
]


def stream(skill: str | None) -> str:
    """Build a synthetic assistant tool-use event, with no host process involved."""
    content = [{"type": "tool_use", "name": "Skill", "input": {"skill": skill}}] if skill else []
    return json.dumps({"type": "assistant", "message": {"content": content}}) + "\n"


def check_parsing() -> None:
    """Distinguish namespaces and ignore skill names appearing only in prose."""
    cases = (
        ({"input": {"skill": "sentinel:solve-cv-task"}}, ("sentinel", "solve-cv-task")),
        ({"input": {"skill": "roboflow:workflow-from-eval"}}, ("roboflow", "workflow-from-eval")),
        ({"skill": "solve-cv-task"}, (None, "solve-cv-task")),
        ({"prompt": 'Mention sentinel:solve-cv-task and "skill": "roboflow:workflow-from-eval"'}, (None, None)),
        ({"type": "result"}, (None, None)),
        ({"skill": "third-party:draw-vision"}, ("third-party", "draw-vision")),
        ({"skill": "invalid:too:many"}, (None, None)),
    )
    for event, expected in cases:
        assert run_live.parse_fired_skill(json.dumps(event)) == expected, event
    assert run_live.parse_fired_skill("not JSON\n" + stream("roboflow:workflow-from-eval")) == (
        "roboflow",
        "workflow-from-eval",
    )
    assert run_live.parse_fired_skill(stream("sentinel:solve-cv-task") + stream("roboflow:workflow-from-eval")) == (
        "sentinel",
        "solve-cv-task",
    )
    nested = {"content": [{"input": {"skill": "roboflow:workflow-from-eval"}}, {"skill": "sentinel:solve-cv-task"}]}
    assert run_live.parse_fired_skill(json.dumps(nested)) == ("roboflow", "workflow-from-eval")
    upstream = json.loads((run_live.ROOT / "evals/platform-routing/upstream-skills.json").read_text())
    for skill in upstream["skills"]:
        assert run_live.parse_fired_skill(stream(f"roboflow:{skill}")) == ("roboflow", skill)


def invoke(scratch: Path, argv: list[str], transcripts: list[str]) -> tuple[int | str | None, list[dict], str, list]:
    """Run the real CLI entrypoint with only its host subprocess boundary stubbed."""
    runs = scratch / "runs"
    output = io.StringIO()
    results = [SimpleNamespace(stdout=text) for text in transcripts]
    with (
        patch.object(sys, "argv", ["run_live.py", *argv]),
        patch.object(run_live, "RUNS_DIR", runs),
        patch("run_live.subprocess.run", autospec=True, side_effect=results) as runner,
        contextlib.redirect_stdout(output),
        contextlib.redirect_stderr(output),
    ):
        try:
            code: int | str | None = run_live.main()
        except SystemExit as exc:
            code = exc.code
    paths = list(runs.glob("*.jsonl"))
    rows = [json.loads(line) for path in paths for line in path.read_text().splitlines()]
    return code, rows, output.getvalue(), runner.call_args_list


def check_single(scratch: Path) -> None:
    """Preserve single-plugin row bytes, summary text, argv, and the fire_prompt doctest."""
    cases = scratch / "cases"
    cases.mkdir()
    prompt = "Count objects."
    (cases / "detect-and-analyze.cases.json").write_text(json.dumps({"should_fire": [{"prompt": prompt}]}))
    with patch.object(run_live, "CASES_DIR", cases):
        code, rows, output, calls = invoke(scratch, [], [stream("sentinel:solve-cv-task")])
    expected = {
        "expected": "detect-and-analyze",
        "should_fire": True,
        "fired": "solve-cv-task",
        "exact": False,
        "router_tolerant": True,
        "prompt": prompt,
        "model": "sonnet",
        "host": "claude",
    }
    (path,) = (scratch / "runs").glob("*.jsonl")
    assert code == 0 and rows == [expected]
    assert path.name.endswith("-claude.jsonl")
    assert path.read_bytes() == (json.dumps(expected) + "\n").encode()
    assert output == (
        f"  ~ + expected={'detect-and-analyze':<26} fired=solve-cv-task\n"
        "\nRouting accuracy (positives): exact 0/1, router-tolerant 1/1\n"
        "\nPer-skill precision/recall (exact, router not credited):\n"
        f"  {'detect-and-analyze':<26} P=— R=0.00 (tp=0 fp=0 fn=1)\nResults: {path}\n"
    )
    assert calls[0].args[0] == [
        "claude",
        "--plugin-dir",
        str(run_live.ROOT),
        "--model",
        "sonnet",
        "--setting-sources",
        "project",
        "--max-turns",
        "2",
        "--allowedTools",
        "Skill",
        "--output-format",
        "stream-json",
        "--verbose",
        "-p",
        prompt,
    ]
    assert calls[0].kwargs == {
        "capture_output": True,
        "text": True,
        "timeout": 180,
        "cwd": calls[0].kwargs["cwd"],
        "stdin": subprocess.DEVNULL,
    }
    assert not Path(calls[0].kwargs["cwd"]).exists()
    assert doctest.testmod(run_live).failed == 0


def check_codex_and_timeout(scratch: Path) -> None:
    """Keep Codex arguments and the legacy None-on-timeout return value unchanged."""
    with patch(
        "run_live.subprocess.run", autospec=True, return_value=SimpleNamespace(stdout=stream("sentinel:solve-cv-task"))
    ) as runner:
        assert run_live.fire_prompt("Count objects.", "opus", "codex") == "solve-cv-task"
    cwd = runner.call_args.kwargs["cwd"]
    assert runner.call_args.args[0] == [
        "codex",
        "exec",
        "--json",
        "--ephemeral",
        "--sandbox",
        "read-only",
        "--cd",
        cwd,
        "--model",
        "opus",
        "Count objects.",
    ]
    with patch("run_live.subprocess.run", autospec=True, side_effect=subprocess.TimeoutExpired("stub", 180)):
        assert run_live.fire_prompt("Count objects.", None, "claude") is None
    with patch.object(run_live, "CASES_DIR", scratch):
        code, rows, _, calls = invoke(scratch, ["--model", "fable"], [])
    assert "sonnet or opus only" in str(code) and not rows and not calls


def check_dual(scratch: Path) -> Path:
    """Load every dual prompt, append plugins in order, and write only the dual row shape."""
    extra = (scratch / "official-roboflow").resolve()
    second = (scratch / "another-plugin").resolve()
    extra.mkdir()
    second.mkdir()
    argv = ["--dual-cases", "--with-plugin-dir", str(extra), "--with-plugin-dir", str(second), "--model", "opus"]
    fired = [
        "sentinel:solve-cv-task",
        "sentinel:choose-approach",
        "roboflow:roboflow-training-and-evaluation",
        "roboflow:roboflow-batch-processing",
        "sentinel:solve-cv-task",
        "roboflow:workflow-from-eval",
    ]
    code, rows, output, calls = invoke(scratch, argv, [stream(skill) for skill in fired])
    assert code == 0 and len(rows) == len(calls) == 6
    for row, call, (identity, expected, prompt), skill in zip(rows, calls, EXPECTED_CASES, fired, strict=True):
        plugin, name = skill.split(":")
        assert row == {
            "id": identity,
            "prompt": prompt,
            "expected_plugin": expected,
            "fired_plugin": plugin,
            "fired_skill": name,
            "plugins": [run_live.ROOT.name, extra.name, second.name],
            "model": "opus",
            "host": "claude",
        }
        assert call.args[0] == [
            "claude",
            "--plugin-dir",
            str(run_live.ROOT),
            "--plugin-dir",
            str(extra),
            "--plugin-dir",
            str(second),
            "--model",
            "opus",
            "--setting-sources",
            "project",
            "--max-turns",
            "2",
            "--allowedTools",
            "Skill",
            "--output-format",
            "stream-json",
            "--verbose",
            "-p",
            prompt,
        ]
    assert "front_door_collisions=1\n  Use a factory camera to catch mistakes on the line.\n" in output
    (path,) = (scratch / "runs").glob("*.jsonl")
    assert path.name.endswith("-dual.jsonl")
    return path


def check_refusals(scratch: Path) -> None:
    """Reject invalid flag combinations before any subprocess or results directory is created."""
    for argv, reason in (
        (["--host", "codex", "--with-plugin-dir", "unused"], "only with --host claude, not codex"),
        (["--dual-cases"], "requires at least one --with-plugin-dir"),
    ):
        code, rows, output, calls = invoke(scratch, argv, [])
        assert code == 2 and reason in output and not rows and not calls
    assert not (scratch / "runs").exists()


def check_dual_trigger_cases(scratch: Path) -> None:
    """Resolve relative plugins before host isolation and honor an explicit output tag."""
    cases = scratch / "cases"
    cases.mkdir()
    (cases / "solve-cv-task.cases.json").write_text(json.dumps({"should_fire": [{"prompt": "Count objects."}]}))
    extra = scratch / "roboflow"
    extra.mkdir()
    relative = os.path.relpath(extra)
    with patch.object(run_live, "CASES_DIR", cases):
        code, rows, _, calls = invoke(
            scratch, ["--with-plugin-dir", relative, "--out-tag", "custom"], [stream("roboflow:workflow-from-eval")]
        )
    assert code == 1 and len(rows) == 1
    assert rows[0]["expected_plugin"] == "sentinel"
    assert rows[0]["plugins"] == [run_live.ROOT.name, extra.name]
    assert calls[0].args[0][:5] == ["claude", "--plugin-dir", str(run_live.ROOT), "--plugin-dir", str(extra.resolve())]
    (path,) = (scratch / "runs").glob("*.jsonl")
    assert path.name.endswith("-custom.jsonl")


def check_case_validation(scratch: Path) -> None:
    """Validate exact prompts and reject missing, extra, duplicate, and invalid case fields."""
    cases = run_live.load_dual_cases()
    assert [(c["id"], c["expected_plugin"], c["prompt"]) for c in cases] == EXPECTED_CASES
    valid = cases[0]
    invalid = [
        ([], "exactly the cases key"),
        ({}, "exactly the cases key"),
        ({"cases": cases, "extra": 1}, "exactly the cases key"),
        ({"cases": {}}, "non-empty list"),
        ({"cases": []}, "non-empty list"),
        ({"cases": ["not an object"]}, "exactly id, prompt, expected_plugin"),
        ({"cases": [{"prompt": "x", "expected_plugin": "sentinel"}]}, "exactly id, prompt, expected_plugin"),
        ({"cases": [{"id": "x", "expected_plugin": "sentinel"}]}, "exactly id, prompt, expected_plugin"),
        ({"cases": [{"id": "x", "prompt": "x"}]}, "exactly id, prompt, expected_plugin"),
        ({"cases": [{**valid, "extra": "x"}]}, "exactly id, prompt, expected_plugin"),
        ({"cases": [{**valid, "expected_plugin": "either"}]}, "must be sentinel, roboflow, or front-door"),
        ({"cases": [{**valid, "expected_plugin": []}]}, "non-empty strings"),
        ({"cases": [{**valid, "id": ""}]}, "non-empty strings"),
        ({"cases": [{**valid, "prompt": None}]}, "non-empty strings"),
        ({"cases": [valid, valid]}, "duplicate dual case id"),
    ]
    path = scratch / "bad-cases.json"
    for data, reason in invalid:
        path.write_text(json.dumps(data))
        with patch.object(run_live, "DUAL_CASES", path):
            code, rows, _, calls = invoke(scratch, ["--dual-cases", "--with-plugin-dir", "unused"], [])
        assert reason in str(code) and not rows and not calls, data
    path.write_text("not JSON")
    with patch.object(run_live, "DUAL_CASES", path):
        code, _, _, calls = invoke(scratch, ["--dual-cases", "--with-plugin-dir", "unused"], [])
    assert "invalid dual cases" in str(code) and not calls


def check_summary() -> None:
    """Distinguish per-group ownership, measured collisions, and actual cross-route failures."""
    pairs = [
        ("sentinel", "sentinel"),
        ("sentinel", "roboflow"),
        ("sentinel", None),
        ("roboflow", "sentinel"),
        ("roboflow", "roboflow"),
        ("roboflow", None),
        ("front-door", "sentinel"),
        ("front-door", "roboflow"),
        ("front-door", None),
        ("front-door", "third-party"),
        ("either", "roboflow"),
    ]
    rows = [
        {"expected_plugin": expected, "fired_plugin": fired, "prompt": f"Prompt {i}"}
        for i, (expected, fired) in enumerate(pairs)
    ]
    assert run_live.dual_summary(rows) == {
        "groups": {
            "sentinel": {"sentinel": 1, "other": 1, "none": 1},
            "roboflow": {"sentinel": 1, "other": 1, "none": 1},
            "front-door": {"sentinel": 1, "other": 2, "none": 1},
            "either": {"sentinel": 0, "other": 1, "none": 0},
        },
        "front_door_collisions": 3,
        "collision_prompts": ["Prompt 7", "Prompt 8", "Prompt 9"],
    }
    for row in rows:
        output = io.StringIO()
        with contextlib.redirect_stdout(output):
            code = run_live._dual_summary([row], Path("synthetic.jsonl"))
        expected = int(
            (row["expected_plugin"], row["fired_plugin"]) in {("sentinel", "roboflow"), ("roboflow", "sentinel")}
        )
        assert code == expected, row
        assert (
            f"front_door_collisions={int(row['expected_plugin'] == 'front-door' and row['fired_plugin'] != 'sentinel')}"
            in output.getvalue()
        )


def check_publish(results: Path, scratch: Path) -> None:
    """Pack real dual rows and verify their digest through the publisher's offline CLI."""
    script = str(run_live.ROOT / "scripts/publish_run.py")
    root = scratch / "published"
    argv = [
        sys.executable,
        script,
        "pack",
        "--suite",
        "trigger-live",
        "--run",
        str(results),
        "--set",
        "synthetic-dual",
        "--publish-root",
        str(root),
    ]
    packed = subprocess.run(argv, capture_output=True, text=True, timeout=60, check=False)
    assert packed.returncode == 0, packed.stderr
    folder = root / "synthetic-dual" / results.stem
    verified = subprocess.run(
        [sys.executable, script, "verify", str(folder)], capture_output=True, text=True, timeout=60, check=False
    )
    assert verified.returncode == 0, verified.stderr
    assert (folder / "results.jsonl").read_bytes() == results.read_bytes()


def main() -> int:
    """Run deterministic checks without invoking a model host."""
    check_parsing()
    check_summary()
    for check in (
        check_single,
        check_codex_and_timeout,
        check_refusals,
        check_case_validation,
        check_dual_trigger_cases,
    ):
        with tempfile.TemporaryDirectory(prefix="dual-routing-") as tmp:
            check(Path(tmp))
    with tempfile.TemporaryDirectory(prefix="dual-routing-") as tmp:
        scratch = Path(tmp)
        check_publish(check_dual(scratch), scratch)
    print("OK dual routing: offline checks passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
