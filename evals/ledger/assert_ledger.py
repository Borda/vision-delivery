#!/usr/bin/env python3
"""Regression checks for outcome-grade, idempotent delivery metrics."""

from __future__ import annotations

import hashlib
import importlib.util
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import ModuleType
from typing import Any, NamedTuple

SCRIPT = Path(__file__).parents[2] / "scripts" / "ledger_report.py"
APPEND_SCRIPT = Path(__file__).parents[2] / "scripts" / "ledger_append.py"


def load_module() -> ModuleType:
    """Load the ledger report script without requiring package installation."""
    spec = importlib.util.spec_from_file_location("sentinel_ledger_report", SCRIPT)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"could not load {SCRIPT}")
    module = importlib.util.module_from_spec(spec)
    # dataclasses look the defining module up in sys.modules while the class body runs
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


#: Price date used by brief fixtures: today, because the helper rejects a date over 90 days old.
TODAY = datetime.now(timezone.utc).date()


def run_brief(
    cwd: str, event: str, operation: str, *extra: str, omit: tuple[str, ...] = (), script: Path = APPEND_SCRIPT
) -> subprocess.CompletedProcess[str]:
    """Append one action brief through the helper and return the finished process."""
    fields = {
        "--scope": "train detection model on conveyor v3",
        "--cost-amount": "10",
        "--cost-unit": "credits",
        "--cost-source": "Roboflow plans-and-pricing skill, training table",
        "--cost-as-of": TODAY.isoformat(),
        "--data-movement": "none; the dataset is already in the workspace",
        "--rollback": "cancel the job; spent credits are not refunded",
    }
    structured = [part for flag, value in fields.items() if flag not in omit for part in (flag, value)]
    command = [
        sys.executable,
        str(script),
        "--session",
        "brief",
        "--skill",
        "detect-and-analyze",
        "--action",
        "action_brief_emitted",
        "--operation",
        operation,
        "--event-id",
        f"manual:brief:{event}",
        "--status",
        "success",
        *structured,
        *extra,
    ]
    return subprocess.run(command, cwd=cwd, check=False, capture_output=True, text=True)


def append_brief(cwd: str, event: str, operation: str, *extra: str, omit: tuple[str, ...] = ()) -> int:
    """Append one action brief through the helper and return its exit code."""
    return run_brief(cwd, event, operation, *extra, omit=omit).returncode


def check_action_briefs() -> None:
    """Assert the helper rejects an action brief the gate could not show a person."""
    with tempfile.TemporaryDirectory() as temp_dir:
        ledger = Path(temp_dir) / ".vision-delivery" / "ledger.jsonl"
        assert append_brief(temp_dir, "complete", "trainings_create") == 0
        row = json.loads(ledger.read_text(encoding="utf-8").splitlines()[-1])
        assert row["operation"] == "trainings_create"
        assert row["brief"] == {
            "scope": "train detection model on conveyor v3",
            "cost_amount": 10.0,
            "cost_unit": "credits",
            "cost_source": "Roboflow plans-and-pricing skill, training table",
            "cost_as_of": TODAY.isoformat(),
            "data_movement": "none; the dataset is already in the workspace",
            "rollback": "cancel the job; spent credits are not refunded",
        }
        rows_before = len(ledger.read_text(encoding="utf-8").splitlines())

        for flag in (
            "--scope",
            "--cost-amount",
            "--cost-unit",
            "--cost-source",
            "--cost-as-of",
            "--data-movement",
            "--rollback",
        ):
            assert append_brief(temp_dir, f"no{flag}", "trainings_create", omit=(flag,)) == 2, flag
        assert append_brief(temp_dir, "blank-source", "trainings_create", "--cost-source", "  ") == 2
        assert append_brief(temp_dir, "negative", "trainings_create", "--cost-amount", "-1") == 2
        assert append_brief(temp_dir, "nan", "trainings_create", "--cost-amount", "nan") == 2
        assert append_brief(temp_dir, "bad-date", "trainings_create", "--cost-as-of", "2026-02-31") == 2
        assert append_brief(temp_dir, "future-date", "trainings_create", "--cost-as-of", "2999-01-01") == 2
        # A price looked up long ago is not a current estimate; the gate applies the same 90 days.
        old_price = (TODAY - timedelta(days=120)).isoformat()
        assert append_brief(temp_dir, "old-date", "trainings_create", "--cost-as-of", old_price) == 2
        # Only the YYYY-MM-DD form the gate reads is accepted.
        for loose in (TODAY.strftime("%Y%m%d"), f"{TODAY.isocalendar().year}-W{TODAY.isocalendar().week:02d}-1"):
            assert append_brief(temp_dir, f"loose-{loose}", "trainings_create", "--cost-as-of", loose) == 2, loose
        assert append_brief(temp_dir, "prefixed", "mcp__roboflow__trainings_create") == 2
        # Billed media analysis takes video: a brief per execution, never a call budget.
        assert append_brief(temp_dir, "media-budget", "media_analyze", "--call-budget", "5") == 2
        assert append_brief(temp_dir, "read-only", "trainings_get") == 2
        assert append_brief(temp_dir, "budget-missing", "models_infer") == 2
        assert append_brief(temp_dir, "budget-zero", "models_infer", "--call-budget", "0") == 2
        assert append_brief(temp_dir, "budget-huge", "models_infer", "--call-budget", "100000") == 2
        assert append_brief(temp_dir, "budget-on-brief", "trainings_create", "--call-budget", "5") == 2
        assert len(ledger.read_text(encoding="utf-8").splitlines()) == rows_before

        assert append_brief(temp_dir, "budget", "models_infer", "--call-budget", "40") == 0
        row = json.loads(ledger.read_text(encoding="utf-8").splitlines()[-1])
        assert row["brief"]["call_budget"] == 40
        assert append_brief(temp_dir, "media", "media_analyze") == 0
        aged_price = (TODAY - timedelta(days=60)).isoformat()
        assert append_brief(temp_dir, "aged-date", "trainings_create", "--cost-as-of", aged_price) == 0
        # A tool the policy does not list is gated, so it can carry a brief; the helper warns,
        # because the name may be misspelled.
        unlisted = run_brief(temp_dir, "unlisted", "future_capability_execute")
        assert unlisted.returncode == 0 and "is not in the gate policy" in unlisted.stderr, unlisted.stderr
        listed = run_brief(temp_dir, "listed", "versions_generate")
        assert listed.returncode == 0 and "ledger-append-warning" not in listed.stderr, listed.stderr

        # Without the gate policy the helper cannot check the brief against what the gate
        # enforces, so it records nothing.
        lone = Path(temp_dir) / "lone" / "scripts"
        lone.mkdir(parents=True)
        (lone / "ledger_append.py").write_bytes(APPEND_SCRIPT.read_bytes())
        rows_before = len(ledger.read_text(encoding="utf-8").splitlines())
        orphan = run_brief(temp_dir, "no-policy", "models_infer", script=lone / "ledger_append.py")
        assert orphan.returncode == 2 and "cannot read the gate policy" in orphan.stderr, orphan.stderr
        assert len(ledger.read_text(encoding="utf-8").splitlines()) == rows_before

        failed = subprocess.run(
            [
                sys.executable,
                str(APPEND_SCRIPT),
                "--session",
                "brief",
                "--skill",
                "detect-and-analyze",
                "--action",
                "action_brief_emitted",
                "--event-id",
                "manual:brief:abandoned",
                "--status",
                "cancelled",
            ],
            cwd=temp_dir,
            check=False,
        )
        assert failed.returncode == 0


def run_freeze_row(cwd: Path, event: str, *extra: str, status: str = "success") -> subprocess.CompletedProcess[str]:
    """Append one predictions_frozen row through the helper and return the finished process."""
    command = [
        sys.executable,
        str(APPEND_SCRIPT),
        "--session",
        "freeze",
        "--skill",
        "classify-or-flag",
        "--action",
        "predictions_frozen",
        "--event-id",
        f"manual:freeze:{event}",
        "--status",
        status,
        *extra,
    ]
    return subprocess.run(command, cwd=cwd, check=False, capture_output=True, text=True)


def check_prediction_freezes() -> None:
    """Assert a predictions_frozen row carries helper-computed digests and refuses incomplete input."""
    with tempfile.TemporaryDirectory() as temp_dir:
        # The helper refuses a ledger path with a symlinked ancestor (macOS /var is one).
        root = Path(temp_dir).resolve()
        ledger = root / ".vision-delivery" / "ledger.jsonl"
        data = root / "data"
        data.mkdir()
        gold = data / "gold.jsonl"
        gold.write_text('{"image": "a.jpg", "flag": true}\n', encoding="utf-8")
        pred = data / "pred.jsonl"
        pred.write_text('{"image": "a.jpg", "flag": false}\n', encoding="utf-8")
        files = ("--pred", str(pred), "--gold", str(gold))
        for name, extra in (
            ("no-pred", ("--gold", str(gold), "--predictor", "isolated-subagent")),
            ("no-gold", ("--pred", str(pred), "--predictor", "isolated-subagent")),
            ("no-predictor", files),
            ("bad-predictor", (*files, "--predictor", "me")),
            ("missing-file", ("--pred", str(data / "none.jsonl"), "--gold", str(gold), "--predictor", "same-session")),
        ):
            result = run_freeze_row(root, name, *extra)
            assert result.returncode == 2, (name, result.stderr)
        if os.name == "posix":
            link = data / "pred-link.jsonl"
            link.symlink_to(pred)
            linked = run_freeze_row(
                root, "link", "--pred", str(link), "--gold", str(gold), "--predictor", "same-session"
            )
            assert linked.returncode == 2 and "regular non-symlink" in linked.stderr, linked.stderr
        assert not ledger.exists(), "a refused freeze must not create a ledger row"

        done = run_freeze_row(root, "ok", *files, "--predictor", "isolated-subagent")
        assert done.returncode == 0, done.stderr
        row = json.loads(ledger.read_text(encoding="utf-8").splitlines()[-1])
        assert row["pred_sha256"] == hashlib.sha256(pred.read_bytes()).hexdigest()
        assert row["gold_sha256"] == hashlib.sha256(gold.read_bytes()).hexdigest()
        assert row["label_set"] == "../data/gold.jsonl" and row["predictor"] == "isolated-subagent", row
        # The helper computes the label digests and the label-change checks from the files and the ledger.
        assert row["label_digests"] == {"a.jpg": hashlib.sha256(b"a.jpg\0true").hexdigest()[:16]}, row
        assert row["label_entry"] == "unrecorded" and row["labels_changed_after_freeze"] == 0, row
        assert row["labels_changed_after_predictions"] is False, row

        cancelled = run_freeze_row(root, "cancelled", status="cancelled")
        assert cancelled.returncode == 0, cancelled.stderr
        row = json.loads(ledger.read_text(encoding="utf-8").splitlines()[-1])
        assert "pred_sha256" not in row and "label_set" not in row, row


def _check_text_prediction_freeze() -> None:
    """Text gold freezes record string digests; mixed label fields and non-string text are refused."""
    with tempfile.TemporaryDirectory() as temp_dir:
        root = Path(temp_dir).resolve()
        gold, pred = root / "gold.jsonl", root / "pred.jsonl"
        ledger = root / ".vision-delivery" / "ledger.jsonl"
        gold.write_text('{"image": "a.jpg", "text": "é😀"}\n{"image": "b.jpg", "text": ""}\n', encoding="utf-8")
        pred.write_text('{"image": "a.jpg", "text": "é"}\n', encoding="utf-8")
        files = ("--gold", str(gold), "--pred", str(pred), "--predictor", "isolated-subagent")
        frozen = run_freeze_row(root, "text", *files)
        assert frozen.returncode == 0, frozen.stderr
        original = ledger.read_bytes()
        row = json.loads(original.splitlines()[-1])
        assert row["action"] == "predictions_frozen" and row["status"] == "success", row
        assert row["gold_sha256"] == hashlib.sha256(gold.read_bytes()).hexdigest(), row
        assert row["label_digests"] == {
            "a.jpg": hashlib.sha256(f"a.jpg\0{json.dumps('é😀')}".encode()).hexdigest()[:16],
            "b.jpg": hashlib.sha256(b'b.jpg\0""').hexdigest()[:16],
        }, row
        gold.write_text('{"image": "a.jpg", "count": 1, "text": "x"}\n', encoding="utf-8")
        mixed = run_freeze_row(root, "mixed-text", *files)
        assert mixed.returncode == 2 and "exactly one of 'count', 'flag', or 'text'" in mixed.stderr, mixed.stderr
        gold.write_text('{"image": "a.jpg", "text": 1}\n', encoding="utf-8")
        invalid = run_freeze_row(root, "invalid-text", *files)
        assert invalid.returncode == 2 and "invalid text" in invalid.stderr, invalid.stderr
        assert ledger.read_bytes() == original, "refused text freezes must not append a ledger row"


def _check_text_freeze_boundaries() -> None:
    """Freeze bounded Unicode labels without treating JSON string separators as line breaks."""
    with tempfile.TemporaryDirectory() as temp_dir:
        root = Path(temp_dir).resolve()
        gold, pred = root / "gold.jsonl", root / "pred.jsonl"
        ledger = root / ".vision-delivery" / "ledger.jsonl"
        text = "first\u2028second\u2029third\u0085fourth"
        gold.write_text(
            json.dumps({"image": "a.jpg", "text": text}, ensure_ascii=False) + "\r\n",
            encoding="utf-8",
            newline="\n",
        )
        pred.write_text('{"image": "a.jpg", "text": "first"}\n', encoding="utf-8", newline="\n")
        files = ("--gold", str(gold), "--pred", str(pred), "--predictor", "isolated-subagent")
        done = run_freeze_row(root, "unicode-separators", *files)
        assert done.returncode == 0, done.stderr
        row = json.loads(ledger.read_bytes().splitlines()[-1])
        expected = hashlib.sha256(f"a.jpg\0{json.dumps(text)}".encode()).hexdigest()[:16]
        assert row["label_digests"] == {"a.jpg": expected}, row
        gold = root / "boundary-gold.jsonl"
        gold.write_text(json.dumps({"image": "b.jpg", "text": "x" * 10_000}) + "\n", encoding="utf-8", newline="\n")
        files = ("--gold", str(gold), "--pred", str(pred), "--predictor", "isolated-subagent")
        boundary = run_freeze_row(root, "text-limit", *files)
        assert boundary.returncode == 0, boundary.stderr
        before = ledger.read_bytes()
        for event, value in (("text-too-long", "x" * 10_001), ("text-surrogate", "\ud800")):
            gold.write_text(json.dumps({"image": "a.jpg", "text": value}) + "\n", encoding="utf-8", newline="\n")
            refused = run_freeze_row(root, event, *files)
            assert refused.returncode == 2 and "invalid text" in refused.stderr, (event, refused.stderr)
        assert ledger.read_bytes() == before, "invalid Unicode labels appended a freeze row"


def check_policy_operations(module: ModuleType) -> None:
    """Assert report operation names come from the gate policy, not from guesses."""
    policy = json.loads((Path(__file__).parents[2] / "hooks" / "gate-policy.json").read_text(encoding="utf-8"))
    deployment, progress = module._policy_operations()
    assert deployment == frozenset(policy["deployment_operations"])
    assert "project_deployment_launch" in deployment
    assert deployment <= policy["tools"].keys()
    assert {"trainings_create", "models_infer", "workflow_evals_runs_start"} <= progress
    assert not {"trainings_get", "model_evals_get", "project_deployment_get"} & progress
    assert all(policy["tools"][name]["class"] != "open" for name in deployment | progress)

    records = [
        {"session": "s", "action": "roboflow_mcp_call", "operation": "models_infer", "status": "success"},
        {"session": "r", "action": "roboflow_mcp_call", "operation": "trainings_get", "status": "success"},
    ]
    metrics = module.compute_metrics(records)
    assert metrics["solved_no_deploy"] == 1
    assert metrics["sessions_reaching_deploy"] == 0


# --- Project status reader vs the Claude Code gate --------------------------------------------
# Every expected brief state below is derived from `briefState` in hooks/gate.js and from
# resources/ledger-protocol.md, never from scripts/ledger_report.py. Each fixture ledger is also
# run through the real gate (node hooks/gate.js) when node is installed.

GATE = Path(__file__).parents[2] / "hooks" / "gate.js"
TRAIN = "trainings_create"  # per-execution brief
UPLOAD = "image_upload"  # per-execution brief
INFER = "models_infer"  # call budget
AUTOLABEL = "autolabel_preview"  # call budget
UNLISTED = "future_capability_execute"  # not in the policy, so gated per execution
_BUDGET_PROMPT = re.compile(r"Call budget: (\d+) calls under this brief, (\d+) used so far")
_USED_UP = re.compile(r"is used up \((\d+) of (\d+) calls\)")


def _ts(delta: timedelta = timedelta(), fmt: str = "%Y-%m-%dT%H:%M:%SZ") -> str:
    """Return the current UTC time shifted by ``delta``, rendered with ``fmt``."""
    return (datetime.now(timezone.utc) + delta).strftime(fmt)


def _fields(**changes: object) -> dict[str, object]:
    """Return complete structured brief fields; a change to ``None`` drops that field."""
    fields: dict[str, object] = {
        "scope": "train detection model on conveyor v3",
        "cost_amount": 10,
        "cost_unit": "credits",
        "cost_source": "Roboflow plans-and-pricing skill, training table",
        "cost_as_of": TODAY.isoformat(),
        "data_movement": "none; the dataset is already in the workspace",
        "rollback": "cancel the job; spent credits are not refunded",
    }
    fields.update(changes)
    return {key: value for key, value in fields.items() if value is not None}


def _brief_row(operation: str, event: str, brief: object = None, ts: str = "", **extra: object) -> dict[str, object]:
    """Return a hand-written brief row, for brief states the writer refuses to record."""
    return {
        "ts": ts or _ts(),
        "session": "status",
        "skill": "detect-and-analyze",
        "action": "action_brief_emitted",
        "operation": operation,
        "status": "success",
        "source": "skill",
        "event_id": f"manual:brief:{event}",
        "brief": _fields() if brief is None else brief,
        **extra,
    }


# Call and reservation rows are written only by the trusted hooks (ledger-protocol.md), so the
# fixtures hand-write them in the hooks' shape.
def _call_row(operation: str, status: str = "success", **extra: object) -> dict[str, object]:
    """Return a PostToolUse-shaped provider call row."""
    return {
        "ts": _ts(),
        "session": "host",
        "skill": "hook",
        "action": "roboflow_mcp_call",
        "operation": operation,
        "status": status,
        "source": "hook",
        **extra,
    }


def _reserve_row(operation: str, unit: str) -> dict[str, object]:
    """Return a PreToolUse-shaped call-budget reservation row."""
    return {
        "ts": _ts(),
        "session": "host",
        "skill": "hook",
        "action": "roboflow_mcp_call_reserved",
        "operation": operation,
        "status": "attempted",
        "source": "hook",
        "event_id": f"reserve:{unit}",
    }


class WriterBrief(NamedTuple):
    """An action brief recorded through ``ledger_append.py``; a non-empty ``ts`` replaces its timestamp."""

    event: str
    operation: str
    extra: tuple[str, ...] = ()
    ts: str = ""


class WriterRow(NamedTuple):
    """A successful non-brief row recorded through ``ledger_append.py``; ``{vision}`` names the ledger folder."""

    action: str
    event: str
    extra: tuple[str, ...] = ()


Row = WriterBrief | WriterRow | dict[str, object] | bytes


class GateCase(NamedTuple):
    """One fixture ledger and the states of one operation's briefs, as the gate sees them."""

    name: str
    operation: str
    rows: tuple[Row, ...]
    states: tuple[str, ...]
    used: int = 0
    limit: int = 1
    interrupted: int = 0
    gate_says: tuple[str, ...] = ()
    warns: str = ""
    #: The gate's answer when the reader cannot know it (``unknown`` briefs); ``None`` means ``expect_open``.
    gate_asks: bool | None = None

    @property
    def expect_open(self) -> bool:
        """Return whether the reader shows a brief the next call of the operation can use."""
        return "open" in self.states

    @property
    def gate_opens(self) -> bool:
        """Return whether the next call of the operation reaches the permission prompt."""
        return self.expect_open if self.gate_asks is None else self.gate_asks


def _retime_last(ledger: Path, ts: str) -> None:
    """Replace the timestamp of the ledger's last row, keeping the writer's row otherwise unchanged."""
    lines = ledger.read_bytes().decode("utf-8").rstrip("\n").split("\n")
    row = json.loads(lines[-1])
    row["ts"] = ts
    lines[-1] = json.dumps(row)
    ledger.write_bytes(("\n".join(lines) + "\n").encode("utf-8"))


def _run_writer(root: Path, ledger: Path, row: WriterRow) -> None:
    """Record one successful non-brief row through the real writer."""
    extra = [arg.replace("{vision}", str(ledger.parent)) for arg in row.extra]
    command = [sys.executable, str(APPEND_SCRIPT), "--session", "status", "--skill", "solve-cv-task"]
    command += ["--action", row.action, "--event-id", f"manual:{row.event}", "--status", "success"]
    result = subprocess.run(
        [*command, "--ledger", str(ledger), *extra], cwd=root, check=False, capture_output=True, text=True
    )
    assert result.returncode == 0, (row, result.stderr)


def build_ledger(root: Path, rows: tuple[Row, ...]) -> Path:
    """Write fixture rows to ``root/.vision-delivery/ledger.jsonl`` in order; bytes are written verbatim."""
    ledger = root / ".vision-delivery" / "ledger.jsonl"
    for row in rows:
        if isinstance(row, WriterBrief):
            result = run_brief(str(root), row.event, row.operation, *row.extra, "--ledger", str(ledger))
            assert result.returncode == 0, (row, result.stderr)
            if row.ts:
                _retime_last(ledger, row.ts)
        elif isinstance(row, WriterRow):
            _run_writer(root, ledger, row)
        else:
            ledger.parent.mkdir(parents=True, exist_ok=True)
            line = row if isinstance(row, bytes) else json.dumps(row, ensure_ascii=False).encode("utf-8") + b"\n"
            with ledger.open("ab") as handle:
                handle.write(line)
    return ledger


def _tree_digest(directory: Path) -> str:
    """Hash every path and file content under ``directory``; ``absent`` when it does not exist."""
    if not directory.exists():
        return "absent"
    digest = hashlib.sha256()
    for path in sorted(directory.rglob("*")):
        digest.update(path.relative_to(directory).as_posix().encode("utf-8") + b"\0")
        if path.is_file():
            digest.update(path.read_bytes())
    return digest.hexdigest()


def read_status(module: ModuleType, ledger: Path) -> Any:
    """Run the status reader with the real clock and policy, and assert it wrote nothing."""
    before = _tree_digest(ledger.parent)
    status = module.project_status(ledger)
    assert _tree_digest(ledger.parent) == before, "the status reader changed the .vision-delivery folder"
    return status


def gate_decision(node: str, root: Path, operation: str, zone: str = "") -> tuple[str, str]:
    """Run hooks/gate.js on one PreToolUse call and return its decision and reason.

    Auto mode makes the gate ask for every call it lets through, even inside a call budget
    (gate.js), so the answer is ``ask`` exactly when a brief is open and ``deny`` otherwise.
    """
    payload = {
        "hook_event_name": "PreToolUse",
        "tool_name": f"mcp__roboflow__{operation}",
        "tool_input": {},
        "permission_mode": "auto",
        "tool_use_id": f"toolu_status_{operation}",
    }
    env = {**os.environ, "CLAUDE_PROJECT_DIR": str(root)}
    if zone:
        env["TZ"] = zone
    result = subprocess.run(
        [node, str(GATE)], input=json.dumps(payload), cwd=root, env=env, capture_output=True, text=True, check=False
    )
    assert result.returncode == 0, result.stderr
    if not result.stdout.strip():
        return "none", ""
    decision = json.loads(result.stdout)["hookSpecificOutput"]
    return decision["permissionDecision"], decision["permissionDecisionReason"]


def brief_cases() -> list[GateCase]:
    """Return the brief fixtures; each expected state follows `briefState` in hooks/gate.js."""
    budget3 = ("--call-budget", "3")
    budget2 = ("--call-budget", "2")
    # V8's legacy parser reads an RFC 2822 date that Python's ISO reader refuses.
    rfc2822 = _ts(timedelta(minutes=-5), "%a, %d %b %Y %H:%M:%S GMT")
    unreadable = "timestamp the status reader cannot read"
    half_call = b'{"action": "roboflow_mcp_call", "operation": "trainings_create", "status": "succ\n'
    bad_utf8 = json.dumps(_call_row(TRAIN, notes="X")).encode("utf-8").replace(b"X", b"\xff") + b"\n"
    return [
        # readRecords: no rows, no approval; a malformed row approves or uses nothing.
        GateCase("no ledger file", TRAIN, (), (), warns="No ledger file yet"),
        GateCase("empty ledger", TRAIN, (b"",), ()),
        GateCase("malformed line only", TRAIN, (b"not json\n",), (), warns="not valid JSON"),
        GateCase("malformed call line uses nothing", TRAIN, (WriterBrief("m", TRAIN), half_call), ("open",)),
        # One brief, one execution; failed and cancelled calls leave it open (NOT_EXECUTED).
        GateCase("open brief", TRAIN, (WriterBrief("open", TRAIN),), ("open",), gate_says=("manual:brief:open",)),
        GateCase("call uses the brief", TRAIN, (WriterBrief("u", TRAIN), _call_row(TRAIN)), ("used",), used=1),
        GateCase(
            "unknown outcome uses it", TRAIN, (WriterBrief("u", TRAIN), _call_row(TRAIN, "unknown")), ("used",), used=1
        ),
        GateCase(
            "failed call leaves it open",
            TRAIN,
            (WriterBrief("f", TRAIN), _call_row(TRAIN, "failed")),
            ("open",),
            interrupted=1,
            warns="ended failed or cancelled",
        ),
        GateCase(
            "cancelled call leaves it open",
            TRAIN,
            (WriterBrief("c", TRAIN), _call_row(TRAIN, "cancelled")),
            ("open",),
            interrupted=1,
        ),
        GateCase("other operation's call", TRAIN, (WriterBrief("o", TRAIN), _call_row(UPLOAD)), ("open",)),
        GateCase("call before the brief", TRAIN, (_call_row(TRAIN), WriterBrief("b", TRAIN)), ("open",)),
        # Freshness (24 hours, 5 minutes of clock skew) and the price date (90 days).
        GateCase(
            "brief older than 24 hours", TRAIN, (WriterBrief("old", TRAIN, ts=_ts(timedelta(hours=-26))),), ("expired",)
        ),
        GateCase(
            "brief 10 minutes ahead", TRAIN, (WriterBrief("ahead", TRAIN, ts=_ts(timedelta(minutes=10))),), ("invalid",)
        ),
        GateCase(
            "brief 2 minutes ahead", TRAIN, (WriterBrief("skew", TRAIN, ts=_ts(timedelta(minutes=2))),), ("open",)
        ),
        GateCase(
            "price older than 90 days",
            TRAIN,
            (_brief_row(TRAIN, "old-price", _fields(cost_as_of=(TODAY - timedelta(days=120)).isoformat())),),
            ("invalid",),
            gate_says=("cost_as_of",),
        ),
        GateCase(
            "price 60 days old",
            TRAIN,
            (WriterBrief("aged-price", TRAIN, ("--cost-as-of", (TODAY - timedelta(days=60)).isoformat())),),
            ("open",),
        ),
        # A later valid brief replaces an earlier one; a later broken one never cancels it.
        GateCase(
            "later valid brief replaces",
            TRAIN,
            (WriterBrief("first", TRAIN), WriterBrief("second", TRAIN)),
            ("replaced", "open"),
            gate_says=("manual:brief:second",),
        ),
        GateCase(
            "new brief after a used one",
            TRAIN,
            (WriterBrief("first", TRAIN), _call_row(TRAIN), WriterBrief("second", TRAIN)),
            ("used", "open"),
            gate_says=("manual:brief:second",),
        ),
        GateCase(
            "incomplete later brief",
            TRAIN,
            (WriterBrief("first", TRAIN), _brief_row(TRAIN, "broken", _fields(rollback=None))),
            ("open", "invalid"),
            gate_says=("manual:brief:first",),
        ),
        GateCase(
            "incomplete brief",
            TRAIN,
            (_brief_row(TRAIN, "no-scope", _fields(scope=None)),),
            ("invalid",),
            gate_says=("scope",),
        ),
        GateCase(
            "notes-only brief",
            TRAIN,
            (_brief_row(TRAIN, "notes", "train v3; ~10 credits"),),
            ("invalid",),
            gate_says=("structured brief fields",),
        ),
        GateCase(
            "call budget on a per-execution operation",
            TRAIN,
            (_brief_row(TRAIN, "wide", _fields(call_budget=5)), _call_row(TRAIN)),
            ("used",),
            used=1,
        ),
        # An operation the policy does not list defaults to the per-execution class.
        GateCase(
            "unlisted operation",
            UNLISTED,
            (WriterBrief("unlisted", UNLISTED),),
            ("open",),
            gate_says=("not in the gate policy",),
        ),
        GateCase(
            "unlisted operation used",
            UNLISTED,
            (WriterBrief("unlisted", UNLISTED), _call_row(UNLISTED)),
            ("used",),
            used=1,
        ),
        # Call budgets: used = max(recorded calls that may have run, reserved units).
        GateCase("budget with units left", INFER, (WriterBrief("b", INFER, budget3),), ("open",), limit=3),
        GateCase(
            "reservation and its call use one unit",
            INFER,
            (WriterBrief("b", INFER, budget3), _reserve_row(INFER, "a"), _call_row(INFER)),
            ("open",),
            used=1,
            limit=3,
        ),
        GateCase(
            "reserved units without outcome are used",
            INFER,
            (
                WriterBrief("b", INFER, budget3),
                _reserve_row(INFER, "a"),
                _reserve_row(INFER, "b"),
                _reserve_row(INFER, "c"),
            ),
            ("used",),
            used=3,
            limit=3,
        ),
        GateCase(
            "budget exhausted by calls",
            INFER,
            (WriterBrief("b", INFER, budget3), _call_row(INFER), _call_row(INFER), _call_row(INFER)),
            ("used",),
            used=3,
            limit=3,
        ),
        GateCase(
            "failed budget calls use no unit",
            INFER,
            (WriterBrief("b", INFER, budget3), *(_call_row(INFER, "failed") for _ in range(3))),
            ("open",),
            limit=3,
            interrupted=3,
        ),
        GateCase(
            "autolabel preview with a unit left",
            AUTOLABEL,
            (WriterBrief("al", AUTOLABEL, budget2), _reserve_row(AUTOLABEL, "a"), _call_row(AUTOLABEL)),
            ("open",),
            used=1,
            limit=2,
        ),
        GateCase(
            "autolabel preview exhausted",
            AUTOLABEL,
            (WriterBrief("al", AUTOLABEL, budget2), _call_row(AUTOLABEL), _call_row(AUTOLABEL)),
            ("used",),
            used=2,
            limit=2,
        ),
        GateCase(
            "budget brief without a budget",
            INFER,
            (_brief_row(INFER, "nobudget"),),
            ("invalid",),
            gate_says=("call_budget",),
        ),
        GateCase(
            "new budget brief starts a new count",
            INFER,
            (WriterBrief("b1", INFER, ("--call-budget", "1")), _call_row(INFER), WriterBrief("b2", INFER, budget2)),
            ("used", "open"),
            limit=2,
        ),
        # Regressions: the Python port read these rows differently from the gate. A brief time the
        # reader cannot read makes every brief of that operation unknown, never open.
        GateCase(
            "basic-format time",
            TRAIN,
            (WriterBrief("basic", TRAIN, ts=_ts(timedelta(hours=-1), "%Y%m%dT%H%M%SZ")),),
            ("unknown",),
            warns=unreadable,
        ),
        GateCase(
            "two-digit offset",
            TRAIN,
            (WriterBrief("off2", TRAIN, ts=_ts(timedelta(hours=-1), "%Y-%m-%dT%H:%M:%S+00")),),
            ("unknown",),
            warns=unreadable,
        ),
        GateCase(
            "RFC 2822 brief replaces an open budget",
            INFER,
            (
                WriterBrief("A", INFER, ("--call-budget", "5"), ts=_ts(timedelta(minutes=-10))),
                WriterBrief("B", INFER, ("--call-budget", "1"), ts=rfc2822),
                _call_row(INFER),
            ),
            ("unknown", "unknown"),
            used=1,
            limit=1,
            gate_says=("manual:brief:B is used up",),
            warns=unreadable,
        ),
        GateCase(
            "lone RFC 2822 brief",
            TRAIN,
            (WriterBrief("rfc", TRAIN, ts=rfc2822),),
            ("unknown",),
            gate_says=("manual:brief:rfc",),
            warns=unreadable,
            gate_asks=True,
        ),
        GateCase(
            "four-digit offset",
            TRAIN,
            (WriterBrief("off4", TRAIN, ts=_ts(timedelta(hours=-1), "%Y-%m-%dT%H:%M:%S+0000")),),
            ("open",),
        ),
        GateCase(
            "NaN hides a call row",
            TRAIN,
            (WriterBrief("nan-call", TRAIN), _call_row(TRAIN, latency=float("nan"))),
            ("open",),
            warns="1 ledger line(s)",
        ),
        GateCase("NaN hides a brief row", TRAIN, (_brief_row(TRAIN, "nan-brief", latency=float("nan")),), ()),
        GateCase(
            "line separators stay inside one row",
            TRAIN,
            (WriterBrief("ls", TRAIN), _call_row(TRAIN, notes="line break\x85end")),
            ("used",),
            used=1,
        ),
        GateCase("invalid UTF-8 inside a row", TRAIN, (WriterBrief("utf8", TRAIN), bad_utf8), ("used",), used=1),
        GateCase(
            "byte-order mark is blank",
            TRAIN,
            (_brief_row(TRAIN, "bom", _fields(scope="﻿")),),
            ("invalid",),
            gate_says=("scope",),
        ),
        GateCase("unit separator is not blank", TRAIN, (_brief_row(TRAIN, "us", _fields(scope="\x1f")),), ("open",)),
        GateCase(
            "integer past the float range",
            TRAIN,
            (_brief_row(TRAIN, "huge", _fields(cost_amount=10**400)),),
            ("invalid",),
            gate_says=("cost_amount",),
        ),
    ]


def _assert_reader(status: Any, case: GateCase) -> None:
    """Assert the status reader labels the operation's briefs as the case derives from the gate."""
    briefs = [brief for brief in status.briefs if brief.operation == case.operation]
    assert tuple(brief.state.value for brief in briefs) == case.states, (case.name, briefs)
    counted = [brief for brief in briefs if brief.state.value in ("open", "used")]
    if counted:
        last = counted[-1]
        assert (last.used, last.limit, last.interrupted) == (case.used, case.limit, case.interrupted), (case.name, last)
        assert last.remaining == (case.limit - case.used if case.expect_open else None), (case.name, last)
    assert status.next_action.startswith("Action brief") == case.expect_open, (case.name, status.next_action)
    assert not case.warns or any(case.warns in warning for warning in status.warnings), (case.name, status.warnings)


def _assert_gate(case: GateCase, decision: str, reason: str) -> None:
    """Assert the gate decides, and counts calls, as the case says the reader does."""
    assert decision == ("ask" if case.gate_opens else "deny"), (case.name, decision, reason)
    budget = _BUDGET_PROMPT.search(reason)
    if budget:
        assert (int(budget[1]), int(budget[2])) == (case.limit, case.used), (case.name, reason)
    used_up = _USED_UP.search(reason)
    if used_up:
        assert (int(used_up[1]), int(used_up[2])) == (case.used, case.limit), (case.name, reason)
    if case.interrupted:
        assert f"Warning: {case.interrupted} earlier call(s)" in reason, (case.name, reason)
    for text in case.gate_says:
        assert text in reason, (case.name, text, reason)


def check_status_matches_gate(module: ModuleType) -> int:
    """Assert the status reader's open, used, and budget-left answers match hooks/gate.js."""
    node = shutil.which("node")
    if node is None:
        print("skip: node not found; brief states were checked against the expected cases only", file=sys.stderr)
    cases = brief_cases()
    for case in cases:
        with tempfile.TemporaryDirectory() as temp_dir:
            # The gate refuses a ledger under a symlinked folder, and macOS /var is one.
            root = Path(temp_dir).resolve()
            ledger = build_ledger(root, case.rows)
            # The reader runs first: the gate appends a reservation row for an open budget.
            _assert_reader(read_status(module, ledger), case)
            if node is not None:
                _assert_gate(case, *gate_decision(node, root, case.operation))
    return len(cases)


def check_unreadable_ledger(module: ModuleType) -> None:
    """Assert a ledger the gate cannot read opens no brief and says why, without a crash."""
    with tempfile.TemporaryDirectory() as temp_dir:
        root = Path(temp_dir).resolve()
        ledger = root / ".vision-delivery" / "ledger.jsonl"
        ledger.mkdir(parents=True)
        status = read_status(module, ledger)
        assert status.briefs == () and any("could not be read" in item for item in status.warnings), status.warnings
        assert not any("No ledger file yet" in item for item in status.warnings), status.warnings
        node = shutil.which("node")
        if node is not None:
            decision, reason = gate_decision(node, root, TRAIN)
            assert decision == "deny" and "could not read" in reason, (decision, reason)


def _status_cli(*args: str, zone: str = "") -> subprocess.CompletedProcess[str]:
    """Run ledger_report.py with ``args`` and return the finished process."""
    env = {key: value for key, value in os.environ.items() if key != "CLAUDE_PROJECT_DIR"}
    if zone:
        env["TZ"] = zone
    return subprocess.run([sys.executable, str(SCRIPT), *args], env=env, capture_output=True, text=True, check=False)


def check_naive_timestamp_zone() -> None:
    """Assert a brief time without an offset is local time to the reader, as Date.parse reads it in the gate."""
    node = shutil.which("node")
    with tempfile.TemporaryDirectory() as temp_dir:
        root = Path(temp_dir).resolve()
        ledger = build_ledger(root, (WriterBrief("naive", TRAIN, ts=_ts(timedelta(hours=-20), "%Y-%m-%dT%H:%M:%S")),))
        # 20 hours ago on a UTC clock is fresh; read as Tokyo time (UTC+9) it is 29 hours old.
        for zone, state, decision in (("UTC", "open", "ask"), ("Asia/Tokyo", "expired", "deny")):
            result = _status_cli("--status", "--json", "--ledger", str(ledger), zone=zone)
            assert result.returncode == 0, result.stderr
            assert [brief["state"] for brief in json.loads(result.stdout)["briefs"]] == [state], (zone, result.stdout)
            if node is not None:
                assert gate_decision(node, root, TRAIN, zone)[0] == decision, zone


def _acceptance_fixture(threshold: float = 0.8) -> dict[str, object]:
    """Return a frozen acceptance file body."""
    return {
        "schema_version": "1",
        "acceptance_id": "fixture/v1",
        "frozen_at": "2026-11-01T00:00:00Z",
        "metric": "catch_rate",
        "comparator": "gte",
        "threshold": threshold,
        "unit": "fraction",
        "dataset_sha256": "a" * 64,
        "model_or_pipeline": "fixture/v1",
        "confirmed_by": "fixture owner",
    }


def _evidence_fixture(verdict: str) -> dict[str, object]:
    """Return a scorer evidence body in the shape score_baseline.py --evidence-out writes."""
    return {
        "schema_version": "1",
        "measured_at": _ts(timedelta(hours=-1)),
        "target": {"metric": "catch_rate", "comparator": "gte", "threshold": 0.8, "unit": "fraction"},
        "observed_value": 0.85,
        "numerator": 17,
        "denominator": 20,
        "interval_lower": 0.64,
        "interval_upper": 0.95,
        "verdict": verdict,
    }


def _pass_evidence(target: dict[str, object] | None = None, **extra: object) -> dict[str, object]:
    """Return PASS evidence; ``target`` changes fields of its target, ``extra`` adds top-level fields."""
    rule: dict[str, object] = {"metric": "catch_rate", "comparator": "gte", "threshold": 0.8, "unit": "fraction"}
    rule.update(target or {})
    return {**_evidence_fixture("pass"), "target": rule, **extra}


def _freeze_block(**changes: object) -> dict[str, object]:
    """Return a scorer ``predictions_frozen`` block written by hand, clean unless ``changes`` say otherwise."""
    block: dict[str, object] = {
        "event_id": "manual:freeze",
        "frozen_at": _ts(timedelta(hours=-2)),
        "label_set": "gold.jsonl",
        "pred_sha256": "c" * 64,
        "gold_sha256": "d" * 64,
        "predictor_declared": "isolated-subagent",
        "label_entry": "interactive-terminal",
        "labels_changed_after_freeze": 0,
        "labels_changed_after_predictions": False,
        "ledger_is_project_ledger": True,
        "independent": True,
    }
    block.update(changes)
    return block


class EvalCase(NamedTuple):
    """Eval files and ledger rows, the delivery step and next action that follow, and text the status shows."""

    name: str
    files: dict[str, object]
    step: str
    action: str
    passed: bool = False
    rows: tuple[Row, ...] = ()
    session: str = ""
    shows: tuple[str, ...] = ()


def eval_cases() -> list[EvalCase]:
    """Return eval-file fixtures; only a PASS known to be against the locked target counts as a pass."""
    locked: dict[str, object] = {"acceptance-fixture.json": _acceptance_fixture()}
    passed: dict[str, object] = {**locked, "evidence-rung0.json": _evidence_fixture("pass")}
    bound = ("--acceptance", "{vision}/acceptance-fixture.json")
    # Scorer evidence records the SHA-256 of the acceptance file bytes; the case writes json.dumps output.
    digest = hashlib.sha256(json.dumps(_acceptance_fixture()).encode("utf-8")).hexdigest()
    rescore = "re-score the same predictions"
    old_freeze = {
        "event_id": "manual:freeze",
        "frozen_at": _ts(timedelta(hours=-2)),
        "label_set": "gold.jsonl",
        "predictor": "isolated-subagent",
        "independence_enforced_by_isolation": True,
    }
    return [
        EvalCase("no target", {}, "scope", "Lock the success target"),
        EvalCase("target locked", locked, "baseline", "Measure the cheapest baseline"),
        EvalCase(
            "eval files without a ledger",
            locked,
            "baseline",
            "Measure the cheapest baseline",
            shows=("Eval files exist in the ledger's folder, but there is no ledger file",),
        ),
        # A target written only in plain words cannot be compared with the rule the scorer used.
        EvalCase(
            "pass against a plain-word target",
            {
                "eval-s1.md": "Target: at least 80% of images judged correctly\n",
                "evidence-rung0.json": _pass_evidence({"metric": "accuracy", "threshold": 0.5}),
            },
            "baseline",
            "cannot be compared with the locked target",
            shows=("scored against accuracy >= 0.5, cannot compare with the locked target",),
        ),
        # Acceptance identity: a different ID or file digest is a different target, whatever the rule.
        EvalCase(
            "pass under another acceptance revision",
            {
                "acceptance-fixture.json": {**_acceptance_fixture(), "acceptance_id": "fixture/v2"},
                "evidence-rung0.json": _pass_evidence({"acceptance_id": "fixture/v1"}),
            },
            "baseline",
            rescore,
            shows=("(acceptance fixture/v1), a different target than the locked one",),
        ),
        EvalCase(
            "pass under an edited acceptance file",
            {
                **locked,
                "evidence-rung0.json": _pass_evidence({"acceptance_id": "fixture/v1", "acceptance_sha256": "0" * 64}),
            },
            "baseline",
            rescore,
        ),
        EvalCase(
            "pass under the same acceptance file",
            {
                **locked,
                "evidence-rung0.json": _pass_evidence({"acceptance_id": "fixture/v1", "acceptance_sha256": digest}),
            },
            "proof",
            "The target passed",
            passed=True,
            shows=("; predictions not frozen)",),
        ),
        # The result line says whether the predictions were frozen, by whom, and when they are not independent.
        EvalCase(
            "frozen by an isolated subagent",
            {**locked, "evidence-rung0.json": _pass_evidence(predictions_frozen=_freeze_block())},
            "proof",
            "The target passed",
            passed=True,
            shows=("; predictions frozen, predictor isolated-subagent)",),
        ),
        EvalCase(
            "frozen in the same session",
            {
                **locked,
                "evidence-rung0.json": _pass_evidence(
                    predictions_frozen=_freeze_block(predictor_declared="same-session", independent=False)
                ),
            },
            "proof",
            "The target passed",
            passed=True,
            shows=("; predictions frozen, predictor same-session, not independent)",),
        ),
        EvalCase(
            "labels changed after an earlier freeze",
            {
                **locked,
                "evidence-rung0.json": _pass_evidence(
                    predictions_frozen=_freeze_block(labels_changed_after_freeze=2, independent=False)
                ),
            },
            "proof",
            "The target passed",
            passed=True,
            shows=("; predictions frozen, predictor isolated-subagent, not independent)",),
        ),
        EvalCase(
            "independence claimed despite a label change",
            {
                **locked,
                "evidence-rung0.json": _pass_evidence(
                    predictions_frozen=_freeze_block(labels_changed_after_predictions=True)
                ),
            },
            "proof",
            "The target passed",
            passed=True,
            shows=("predictor isolated-subagent, not independent)",),
        ),
        EvalCase(
            "evidence from before the label checks",
            {**locked, "evidence-rung0.json": _pass_evidence(predictions_frozen=old_freeze)},
            "proof",
            "The target passed",
            passed=True,
            shows=("; predictions frozen, predictor isolated-subagent, label-change checks not on file)",),
        ),
        EvalCase(
            "eval notes lock the target",
            {"eval-factory-counter.md": "metric: catch_rate\ncomparator: gte\nthreshold: 0.8\n"},
            "baseline",
            "Measure the cheapest baseline",
            session="factory-counter",
        ),
        EvalCase(
            "pass",
            passed,
            "proof",
            "The target passed",
            passed=True,
            shows=("PASS (measured", "; predictions not frozen)"),
        ),
        EvalCase(
            "integer past the float range in evidence",
            {**locked, "evidence-rung0.json": {**_evidence_fixture("below-target"), "observed_value": 10**400}},
            "improve",
            "misses the target",
        ),
        EvalCase(
            "below target",
            {**locked, "evidence-rung0.json": _evidence_fixture("below-target")},
            "improve",
            "misses the target",
        ),
        EvalCase(
            "inconclusive",
            {**locked, "evidence-rung0.json": _evidence_fixture("inconclusive")},
            "improve",
            "label more gold",
        ),
        EvalCase(
            "no verdict",
            {**locked, "evidence-rung0.json": _evidence_fixture("no-verdict")},
            "improve",
            "refused a verdict",
        ),
        EvalCase(
            "pass against another target",
            {"acceptance-fixture.json": _acceptance_fixture(0.9), "evidence-rung0.json": _evidence_fixture("pass")},
            "baseline",
            rescore,
            shows=("scored against catch_rate >= 0.8, a different target than the locked one",),
        ),
        EvalCase(
            "measured row without evidence",
            locked,
            "baseline",
            "no scorer evidence file",
            rows=(WriterRow("baseline_measured", "baseline", bound),),
        ),
        EvalCase(
            "open brief comes first",
            passed,
            "proof",
            "Action brief manual:brief:next",
            True,
            (WriterBrief("next", TRAIN),),
        ),
        EvalCase(
            "proof on file",
            {**passed, "delivery-handoff-s.json": {"schema_version": "1"}},
            "economics",
            "Estimate one-time",
            True,
        ),
        EvalCase(
            "economics on file",
            {**passed, "economics-s.md": "one-time: 10 credits\n"},
            "decision",
            "Write the decision report",
            True,
        ),
        EvalCase(
            "decision recorded",
            {**passed, "decision-report.md": "Decision: fixture\n"},
            "done",
            "Hand the decision report",
            True,
            (WriterRow("decision_report_emitted", "report", (*bound, "--report", "{vision}/decision-report.md")),),
        ),
    ]


def check_status_eval_files(module: ModuleType) -> int:
    """Assert the delivery step and the one next action that follow from eval files and ledger rows."""
    cases = eval_cases()
    for case in cases:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir).resolve()
            vision = root / ".vision-delivery"
            vision.mkdir()
            for name, content in case.files.items():
                (vision / name).write_text(
                    content if isinstance(content, str) else json.dumps(content), encoding="utf-8"
                )
            status = read_status(module, build_ledger(root, case.rows))
            assert status.step.value == case.step, (case.name, status.step)
            assert case.action in status.next_action, (case.name, status.next_action)
            assert (module.Milestone.PASSED in status.milestones) == case.passed, (case.name, status.milestones)
            assert not case.session or status.session == case.session, (case.name, status.session)
            text = "\n".join(module.status_lines(status))
            for shown in case.shows:
                assert shown in text, (case.name, shown, text)
    return len(cases)


def check_upstream_search_order(module: Any) -> None:
    """Assert the status reader reports an upstream search that ran out of order or reused held-out labels."""
    search = {"action": module.UPSTREAM_SEARCH_ACTION, "status": "success", "ts": "2026-11-10T10:00:00Z"}
    measured = {"action": "baseline_measured", "status": "success", "ts": "2026-11-10T09:00:00Z"}
    failed = {**search, "status": "failed"}
    target = "metric: accuracy\ncomparator: gte\nthreshold: 0.8\n"
    cases: tuple[tuple[str, list[dict[str, str]], str, tuple[str, ...]], ...] = (
        ("search after target and baseline", [measured, search], target, ()),
        (
            "search after target and a prediction freeze",
            [{**measured, "action": "predictions_frozen"}, search],
            target,
            (),
        ),
        ("search before any baseline", [search, measured], target, ("before the target was locked",)),
        ("search with no locked target", [measured, search], "", ("before the target was locked",)),
        ("failed search row does not count", [failed, measured], target, ()),
        ("one search, one score", [measured, search, measured], target, ()),
        ("second search after a score", [measured, search, measured, search], target, ("held-out labels",)),
    )
    for name, rows, notes, expected in cases:
        with tempfile.TemporaryDirectory() as temp_dir:
            folder = Path(temp_dir).resolve() / ".vision-delivery"
            folder.mkdir()
            ledger = folder / "ledger.jsonl"
            ledger.write_text("".join(json.dumps(row) + "\n" for row in rows), encoding="utf-8")
            if notes:
                (folder / "eval-s1.md").write_text(notes, encoding="utf-8")
            warnings = [text for text in module.project_status(ledger).warnings if "upstream candidate search" in text]
            assert len(warnings) == len(expected), (name, warnings)
            for phrase, warning in zip(expected, warnings, strict=True):
                assert phrase in warning, (name, phrase, warning)


def check_recheck_status(module: Any) -> None:
    """Assert recheck warnings apply only to evidence against the locked target.

    Examples:
        Run this check through ``python3 evals/ledger/assert_ledger.py``.
    """
    stamp = "2026-11-10T10:00:00Z"
    cases: tuple[tuple[str, list[dict[str, str]], str, str], ...] = (
        ("no recheck", [], "", ""),
        ("holds", [_recheck_row("holds", stamp)], f"Last recheck: holds on {stamp}", ""),
        ("drifted", [_recheck_row("drifted", stamp)], f"Last recheck: drifted on {stamp}", "has drifted"),
        ("uncertain", [_recheck_row("uncertain", stamp)], f"Last recheck: uncertain on {stamp}", "label more fresh"),
        (
            "latest row wins",
            [_recheck_row("drifted", "2026-11-09T10:00:00Z"), _recheck_row("holds", stamp)],
            f"Last recheck: holds on {stamp}",
            "",
        ),
        (
            "failed row does not count",
            [_recheck_row("holds", stamp), {**_recheck_row("drifted", stamp), "status": "failed"}],
            f"Last recheck: holds on {stamp}",
            "",
        ),
        (
            "hand-written notes",
            [{key: value for key, value in _recheck_row("holds", stamp).items() if key != "drift"}],
            f"Last recheck: unreadable on {stamp}",
            "",
        ),
        (
            "different target",
            [{**_recheck_row("drifted", stamp), "acceptance_sha256": "b" * 64}],
            f"Last recheck: drifted on {stamp}, against a different target than the locked one",
            "",
        ),
        (
            "unknown target",
            [{key: value for key, value in _recheck_row("uncertain", stamp).items() if key != "acceptance_sha256"}],
            f"Last recheck: uncertain on {stamp}, cannot compare with the locked target",
            "",
        ),
        (
            "invalid drift",
            [{**_recheck_row("holds", stamp), "drift": "pass"}],
            f"Last recheck: unreadable on {stamp}",
            "",
        ),
        (
            "fresh predictions not frozen",
            [{**_recheck_row("holds", stamp), "predictions_frozen": "not-frozen"}],
            f"Last recheck: holds on {stamp}, fresh predictions not frozen",
            "",
        ),
        (
            "freeze not independent",
            [{**_recheck_row("drifted", stamp), "predictions_frozen": "not-independent"}],
            f"Last recheck: drifted on {stamp}, not independent",
            "has drifted",
        ),
        (
            "freeze state missing",
            [{key: value for key, value in _recheck_row("holds", stamp).items() if key != "predictions_frozen"}],
            f"Last recheck: holds on {stamp}, freeze state not on file",
            "",
        ),
    )
    for name, rows, line, warning in cases:
        with tempfile.TemporaryDirectory() as temp_dir:
            folder = Path(temp_dir).resolve() / ".vision-delivery"
            folder.mkdir()
            (folder / "acceptance-fixture.json").write_text(
                json.dumps(_acceptance_fixture()), encoding="utf-8", newline="\n"
            )
            ledger = folder / "ledger.jsonl"
            ledger.write_text("".join(json.dumps(row) + "\n" for row in rows), encoding="utf-8", newline="\n")
            status = module.project_status(ledger)
            shown = [text for text in module.status_lines(status) if text.startswith("Last recheck:")]
            assert shown == ([line] if line else []), (name, shown)
            assert status.to_json().get("recheck", "") == line.removeprefix("Last recheck: "), (name, status.recheck)
            assert bool(line) == ("recheck" in status.to_json()), (name, status.to_json())
            raised = [text for text in status.warnings if "recheck" in text]
            assert len(raised) == (1 if warning else 0), (name, raised)
            assert not warning or warning in raised[0], (name, raised)


def _recheck_row(drift: str, stamp: str) -> dict[str, str]:
    """Build a recheck row bound to the fixture's exact frozen acceptance bytes."""
    notes = f"drift={drift}; shifted=no; metric=catch_rate; value=0.8; baseline=0.9"
    return {
        "action": "recheck_measured",
        "status": "success",
        "ts": stamp,
        "notes": notes,
        "drift": drift,
        "acceptance_sha256": hashlib.sha256(json.dumps(_acceptance_fixture()).encode()).hexdigest(),
        "predictions_frozen": "independent",
    }


def _check_recheck_evidence_is_not_result(module: Any) -> None:
    """A later recheck evidence file leaves the baseline result and project action intact."""
    with tempfile.TemporaryDirectory() as temp_dir:
        folder = Path(temp_dir).resolve() / ".vision-delivery"
        folder.mkdir()
        ledger = folder / "ledger.jsonl"
        ledger.write_text("", encoding="utf-8", newline="\n")
        (folder / "acceptance-fixture.json").write_text(
            json.dumps(_acceptance_fixture()), encoding="utf-8", newline="\n"
        )
        (folder / "evidence-baseline.json").write_text(
            json.dumps(_evidence_fixture("below-target")), encoding="utf-8", newline="\n"
        )
        before = module.project_status(ledger)
        evidence = _pass_evidence(recheck={"drift": "holds"}, measured_at="2999-01-01T00:00:00Z")
        (folder / "recheck-evidence.json").write_text(json.dumps(evidence), encoding="utf-8", newline="\n")
        after = module.project_status(ledger)
        assert after.measurement == before.measurement, (before.measurement, after.measurement)
        assert after.step == before.step and after.next_action == before.next_action, (before, after)
        assert next(line for line in module.status_lines(before) if line.startswith("Last result:")) == next(
            line for line in module.status_lines(after) if line.startswith("Last result:")
        )


def check_status_cli() -> None:
    """Assert --status text and JSON output, exit codes, and that the default report is unchanged."""
    with tempfile.TemporaryDirectory() as temp_dir:
        root = Path(temp_dir).resolve()
        ledger = build_ledger(root, (WriterBrief("cli", TRAIN),))
        before = _tree_digest(ledger.parent)
        text = _status_cli("--status", "--ledger", str(ledger))
        lines = text.stdout.splitlines()
        assert text.returncode == 0 and lines[0] == "Sentinel project status (read-only)", (text.returncode, lines)
        assert "Briefs:       1 open, 0 earlier" in lines, lines
        assert any(
            line.startswith("  open     manual:brief:cli for trainings_create (brief): 0 of 1 calls used, 1 left")
            for line in lines
        ), lines
        assert any(
            line.startswith("Next action:  Action brief manual:brief:cli for trainings_create is open")
            for line in lines
        ), lines
        as_json = _status_cli("--status", "--json", "--ledger", str(ledger))
        payload = json.loads(as_json.stdout)
        assert as_json.returncode == 0 and payload["step"] == "scope" and payload["step_number"] == 1, payload
        assert "recheck" not in payload, payload
        summary = [(b["state"], b["operation"], b["used"], b["limit"], b["remaining"]) for b in payload["briefs"]]
        assert summary == [("open", TRAIN, 0, 1, 1)], summary
        # Without --status the metrics report is printed exactly as before the status reader existed.
        default = _status_cli("--ledger", str(ledger))
        assert default.returncode == 0 and default.stdout.splitlines()[:2] == [
            "vision-delivery ledger report",
            "(verified successes only; legacy status-less rows remain unknown)",
        ], default.stdout
        assert "Ledger rows:              1" in default.stdout and "Sentinel project status" not in default.stdout
        metrics = json.loads(_status_cli("--json", "--ledger", str(ledger)).stdout)
        assert (
            set(metrics)
            == {
                "raw_records",
                "total_events",
                "duplicates_ignored",
                "integrity_conflicts",
                "verified_success_events",
                "sessions",
                "sessions_reaching_deploy",
                "sessions_reaching_deploy_pct",
                "solved_no_deploy",
                "workload_mix",
                "action_breakdown",
                "outcome_breakdown",
                "coverage_note",
            }
            and metrics["raw_records"] == 1
        ), metrics
        assert _status_cli("--status", "--no-such-flag").returncode == 2
        assert _tree_digest(ledger.parent) == before, "a report run changed the .vision-delivery folder"
        missing = _status_cli("--status", "--ledger", str(root / "none" / "ledger.jsonl"))
        assert missing.returncode == 0 and "Warning:      No ledger file yet" in missing.stdout, missing.stdout
        assert not (root / "none").exists(), "the status reader created a folder"


def _check_event_metrics(module: ModuleType) -> None:
    """Exclude unsuccessful claims and deduplicate events without hiding conflicting outcomes."""
    records = [
        {
            "session": "ok",
            "skill": "hook",
            "action": "roboflow_mcp_call",
            "operation": "project_deployment_launch",
            "category": "deployment",
            "status": "success",
            "event_id": "deploy-1",
        },
        {
            "session": "ok",
            "skill": "hook",
            "action": "roboflow_mcp_call",
            "operation": "project_deployment_launch",
            "category": "deployment",
            "status": "success",
            "event_id": "deploy-1",
        },
        {
            "session": "failed",
            "skill": "hook",
            "action": "roboflow_mcp_call",
            "operation": "project_deployment_launch",
            "category": "deployment",
            "status": "failed",
            "event_id": "deploy-2",
        },
        {
            "session": "legacy",
            "skill": "detect-and-analyze",
            "action": "project_deployment_launch",
        },
        {
            "session": "measured",
            "skill": "detect-and-analyze",
            "action": "baseline_measured",
            "status": "success",
        },
        {
            "session": "read-only",
            "skill": "hook",
            "action": "roboflow_mcp_call",
            "operation": "project_deployment_get",
            "category": "deployment",
            "status": "success",
            "event_id": "deploy-read-1",
        },
        {
            "session": "manual-claim",
            "skill": "arbitrary",
            "action": "project_deployment_launch",
            "status": "success",
            "event_id": "manual:fake-deploy:1",
        },
    ]
    metrics = module.compute_metrics(records)

    assert metrics["raw_records"] == 7
    assert metrics["total_events"] == 6
    assert metrics["duplicates_ignored"] == 1
    assert metrics["verified_success_events"] == 4
    assert metrics["sessions"] == 6
    assert metrics["sessions_reaching_deploy"] == 1
    assert metrics["sessions_reaching_deploy_pct"] == 16.7
    assert metrics["solved_no_deploy"] == 1
    assert metrics["outcome_breakdown"] == {
        "success": 4,
        "failed": 1,
        "legacy-unknown": 1,
    }

    conflicting_records = [
        {
            "session": "conflict",
            "skill": "hook",
            "action": "roboflow_mcp_call",
            "status": "success",
            "event_id": "conflict-1",
        },
        {
            "session": "conflict",
            "skill": "hook",
            "action": "roboflow_mcp_call",
            "status": "failed",
            "event_id": "conflict-1",
        },
    ]
    conflicting_metrics = module.compute_metrics(conflicting_records)
    assert conflicting_metrics["total_events"] == 1
    assert conflicting_metrics["verified_success_events"] == 0
    assert conflicting_metrics["integrity_conflicts"] == 1
    assert conflicting_metrics["outcome_breakdown"] == {"unknown": 1}


def _check_append_integrity() -> None:
    """Exercise bound report appends, idempotence, conflicts, and concurrent writes."""
    with tempfile.TemporaryDirectory() as temp_dir:
        acceptance = Path(temp_dir) / "acceptance.json"
        acceptance.write_text(
            json.dumps(
                {
                    "schema_version": "1",
                    "acceptance_id": "fixture/v1",
                    "frozen_at": "2026-08-11T00:00:00Z",
                    "metric": "mAP@50",
                    "comparator": "gte",
                    "threshold": 0.65,
                    "unit": "fraction",
                    "dataset_sha256": "a" * 64,
                    "model_or_pipeline": "fixture/v1",
                    "confirmed_by": "fixture owner",
                }
            ),
            encoding="utf-8",
            newline="\n",
        )
        report = Path(temp_dir) / "decision-report.md"
        report.write_text("Decision: fixture\n", encoding="utf-8", newline="\n")
        proof_args = [
            "--acceptance",
            str(acceptance),
            "--report",
            str(report),
        ]
        subprocess.run(
            [
                sys.executable,
                str(APPEND_SCRIPT),
                "--session",
                "arbitrary-cwd",
                "--skill",
                "decision-report",
                "--action",
                "decision_report_emitted",
                *proof_args,
                "--event-id",
                "manual:arbitrary-cwd:report:1",
                "--status",
                "success",
            ],
            cwd=temp_dir,
            check=True,
        )
        ledger = Path(temp_dir) / ".vision-delivery" / "ledger.jsonl"
        appended = json.loads(ledger.read_text(encoding="utf-8"))
        assert appended["status"] == "success"
        assert appended["source"] == "skill"
        assert appended["report_sha256"] == hashlib.sha256(report.read_bytes()).hexdigest()

        duplicate = subprocess.run(
            [
                sys.executable,
                str(APPEND_SCRIPT),
                "--session",
                "arbitrary-cwd",
                "--skill",
                "decision-report",
                "--action",
                "decision_report_emitted",
                *proof_args,
                "--event-id",
                "manual:arbitrary-cwd:report:1",
                "--status",
                "success",
            ],
            cwd=temp_dir,
            check=False,
        )
        assert duplicate.returncode == 0
        assert len(ledger.read_text(encoding="utf-8").splitlines()) == 1

        unbound = subprocess.run(
            [
                sys.executable,
                str(APPEND_SCRIPT),
                "--session",
                "arbitrary-cwd",
                "--skill",
                "decision-report",
                "--action",
                "decision_report_emitted",
                "--event-id",
                "manual:arbitrary-cwd:unbound:1",
                "--status",
                "success",
            ],
            cwd=temp_dir,
            check=False,
        )
        assert unbound.returncode == 2

        conflict = subprocess.run(
            [
                sys.executable,
                str(APPEND_SCRIPT),
                "--session",
                "arbitrary-cwd",
                "--skill",
                "decision-report",
                "--action",
                "different_action",
                "--event-id",
                "manual:arbitrary-cwd:report:1",
                "--status",
                "success",
            ],
            cwd=temp_dir,
            check=False,
        )
        assert conflict.returncode == 2

        concurrent_commands = [
            [
                sys.executable,
                str(APPEND_SCRIPT),
                "--session",
                "concurrent",
                "--skill",
                "decision-report",
                "--action",
                "decision_report_emitted",
                *proof_args,
                "--event-id",
                "manual:concurrent:report:1",
                "--status",
                "success",
            ]
            for _ in range(12)
        ]
        processes = [subprocess.Popen(command, cwd=temp_dir) for command in concurrent_commands]
        assert all(process.wait() == 0 for process in processes)
        assert (
            sum(
                1
                for row in ledger.read_text(encoding="utf-8").splitlines()
                if json.loads(row).get("event_id") == "manual:concurrent:report:1"
            )
            == 1
        )


def _check_ledger_symlink_refusal() -> None:
    """Refuse ledger symlinks while preserving their directory and file targets."""
    if os.name == "posix":
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            victim_dir = root / "victim-dir"
            victim_dir.mkdir()
            ledger_dir = root / ".vision-delivery"
            ledger_dir.symlink_to(victim_dir, target_is_directory=True)
            result = subprocess.run(
                [
                    sys.executable,
                    str(APPEND_SCRIPT),
                    "--session",
                    "symlink",
                    "--skill",
                    "decision-report",
                    "--action",
                    "eval_definition",
                    "--event-id",
                    "symlink-directory",
                    "--status",
                    "success",
                ],
                cwd=root,
                check=False,
            )
            assert result.returncode == 2
            assert not (victim_dir / "ledger.jsonl").exists()

            ledger_dir.unlink()
            ledger_dir.mkdir()
            victim_file = root / "victim.jsonl"
            victim_file.write_text("victim\n", encoding="utf-8", newline="\n")
            (ledger_dir / "ledger.jsonl").symlink_to(victim_file)
            result = subprocess.run(
                [
                    sys.executable,
                    str(APPEND_SCRIPT),
                    "--session",
                    "symlink",
                    "--skill",
                    "decision-report",
                    "--action",
                    "eval_definition",
                    "--event-id",
                    "symlink-file",
                    "--status",
                    "success",
                ],
                cwd=root,
                check=False,
            )
            assert result.returncode == 2
            assert victim_file.read_text(encoding="utf-8") == "victim\n"


def main() -> int:
    """Run the ledger's reader and writer acceptance checks.

    Examples:
        Run ``python3 evals/ledger/assert_ledger.py`` to print the passing assertion message.
    """
    module = load_module()
    check_policy_operations(module)
    check_action_briefs()
    check_prediction_freezes()
    _check_text_prediction_freeze()
    _check_text_freeze_boundaries()
    check_status_matches_gate(module)
    check_naive_timestamp_zone()
    check_unreadable_ledger(module)
    check_status_eval_files(module)
    check_upstream_search_order(module)
    check_recheck_status(module)
    _check_recheck_evidence_is_not_result(module)
    check_status_cli()
    _check_event_metrics(module)
    _check_append_integrity()
    _check_ledger_symlink_refusal()
    print("ledger assertions passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
