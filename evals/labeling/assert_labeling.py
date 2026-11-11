#!/usr/bin/env python3
"""Assert the gold-labeling helper and the prediction freeze keep rung 0 labels independent of predictions.

Deterministic and offline: every case builds a throwaway project in a temporary directory, runs the
shipped command-line helpers as subprocesses, and checks their exit codes, output, and files. Each
guard has a negative control: the refused input is shown to leave files unchanged, and a nearby
allowed input is shown to succeed. Interactive labeling runs through a pseudo-terminal (POSIX only);
elsewhere those cases are skipped with a printed line.
"""

from __future__ import annotations

import contextlib
import doctest
import hashlib
import importlib.util
import io
import json
import os
import select
import shutil
import subprocess
import sys
import tempfile
import time
from dataclasses import dataclass
from pathlib import Path
from types import ModuleType
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[2]
SCRIPTS = ROOT / "resources" / "scripts"
LABEL = SCRIPTS / "label_gold.py"
FREEZE = SCRIPTS / "freeze_predictions.py"
SCORER = SCRIPTS / "score_baseline.py"
APPEND = ROOT / "scripts" / "ledger_append.py"
HAS_PTY = os.name == "posix"
sys.path.insert(0, str(SCRIPTS))

import freeze_predictions  # noqa: E402
import label_gold  # noqa: E402
import prediction_freeze  # noqa: E402
import score_baseline  # noqa: E402

CLEAN_NOTE = (
    "Predictions and labels were fixed before this scoring run; the freeze records the predictions as written by "
    "an isolated subagent."
)
RECORD_NOTE = (
    "Labels were entered through the helper's --record option, the path an agent uses to transcribe labels given in "
    "chat: check them."
)
EVIDENCE_KEYS = {
    "event_id",
    "frozen_at",
    "label_set",
    "pred_sha256",
    "gold_sha256",
    "predictor_declared",
    "label_entry",
    "labels_changed_after_freeze",
    "labels_changed_after_predictions",
    "ledger_is_project_ledger",
    "independent",
}
TARGET = ("--task", "count", "--metric", "exact_count_rate", "--comparator", "gte", "--threshold", "0.5")


def environment() -> dict[str, str]:
    """Return the process environment without a declared project directory, so each case uses its own ledger."""
    return {name: value for name, value in os.environ.items() if name != "CLAUDE_PROJECT_DIR"}


def run(script: Path, *args: str, stdin: str = "", cwd: Path | None = None) -> subprocess.CompletedProcess[str]:
    """Run one helper with the given standard input and capture its output."""
    return subprocess.run(
        [sys.executable, str(script), *args],
        input=stdin,
        capture_output=True,
        text=True,
        check=False,
        cwd=cwd,
        env=environment(),
        timeout=120,
    )


def run_tty(script: Path, *args: str, answers: str) -> tuple[int, str]:
    """Run one helper on a pseudo-terminal, type `answers` ahead, and return its exit code and output."""
    import pty

    master, slave = pty.openpty()
    process = subprocess.Popen(
        [sys.executable, str(script), *args], stdin=slave, stdout=slave, stderr=slave, env=environment()
    )
    os.close(slave)
    os.write(master, answers.encode("utf-8"))
    chunks: list[bytes] = []
    deadline = time.monotonic() + 60
    while time.monotonic() < deadline:
        ready, _, _ = select.select([master], [], [], 0.05)
        data = b""
        if ready:
            try:
                data = os.read(master, 4096)
            except OSError:
                data = b""
        if data:
            chunks.append(data)
        elif process.poll() is not None:
            break
    else:
        process.kill()
        raise AssertionError(f"{script.name} did not finish on the pseudo-terminal")
    os.close(master)
    return process.wait(timeout=10), b"".join(chunks).decode("utf-8", "replace").replace("\r\n", "\n")


@dataclass(frozen=True)
class Project:
    """A throwaway user project: an image folder, a gold file path, and a ledger path."""

    root: Path
    frames: Path
    gold: Path
    ledger: Path
    task: str = "count"

    def common(self, gold: Path | None = None) -> tuple[str, ...]:
        """Return the labeling helper's shared arguments."""
        labels = str(gold or self.gold)
        return ("--images", str(self.frames), "--labels", labels, "--task", self.task, "--ledger", str(self.ledger))

    def label(self, *args: str, stdin: str = "", gold: Path | None = None) -> subprocess.CompletedProcess[str]:
        """Run the labeling helper on this project with piped standard input."""
        return run(LABEL, *self.common(gold), *args, stdin=stdin)

    def label_tty(self, *args: str, answers: str) -> tuple[int, str]:
        """Run the labeling helper on this project from a pseudo-terminal."""
        return run_tty(LABEL, *self.common(), *args, answers=answers)

    def freeze(self, pred: Path, *args: str, gold: Path | None = None) -> subprocess.CompletedProcess[str]:
        """Run the freeze helper on this project."""
        common = ("--task", self.task, "--gold", str(gold or self.gold), "--pred", str(pred))
        session = ("--session", "demo", "--skill", "detect-and-analyze", "--ledger", str(self.ledger))
        return run(FREEZE, *common, *session, *args)

    def score(self, pred: Path, gold: Path | None = None) -> subprocess.CompletedProcess[str]:
        """Score a prediction file with the freeze check against this project's ledger."""
        files = ("--gold", str(gold or self.gold), "--pred", str(pred))
        return run(SCORER, *files, *TARGET, "--frozen-ledger", str(self.ledger))

    def ledger_rows(self, action: str | None = None) -> list[dict[str, object]]:
        """Return every ledger row, or only the rows of one action."""
        if not self.ledger.exists():
            return []
        rows = [json.loads(line) for line in self.ledger.read_text(encoding="utf-8").splitlines() if line.strip()]
        return [row for row in rows if action is None or row["action"] == action]


def make_project(tmp: Path, name: str, images: int, task: str = "count") -> Project:
    """Create a project folder with `images` placeholder JPEG files and an empty `.vision-delivery` folder."""
    root = tmp / name
    frames = root / "frames"
    frames.mkdir(parents=True)
    (root / ".vision-delivery").mkdir()
    for index in range(1, images + 1):
        (frames / f"frame_{index:02d}.jpg").write_bytes(b"placeholder")
    return Project(
        root, frames, root / ".vision-delivery" / f"gold-{name}.jsonl", root / ".vision-delivery" / "ledger.jsonl", task
    )


def write_pred(path: Path, rows: dict[str, object], field: str = "count", separator: str = ": ") -> Path:
    """Write a prediction file the way a predictor would, one JSON line per image."""
    lines = (
        json.dumps({"image": image, field: value}, separators=(", ", separator)) + "\n" for image, value in rows.items()
    )
    path.write_text("".join(lines), "utf-8")
    return path


def scored_record(result: subprocess.CompletedProcess[str]) -> tuple[str, dict[str, object]]:
    """Return a scorer run's verdict line and its `predictions_frozen` evidence block."""
    lines = result.stdout.splitlines()
    block = json.loads(lines[-1])["predictions_frozen"]
    assert set(block) == EVIDENCE_KEYS, sorted(block)
    return lines[0], block


def assert_record_mode(tmp: Path) -> None:
    """Record mode writes sorted lines, records one ledger row per write, and changes a label only with --relabel."""
    project = make_project(tmp, "record", 3)
    absolute = str(project.frames / "frame_01.jpg")
    done = project.label("--record", "frame_03.jpg=0", "--record", f"{absolute}=2")
    assert done.returncode == 0, done.stderr
    expected = '{"image": "frame_01.jpg", "count": 2}\n{"image": "frame_03.jpg", "count": 0}\n'
    assert project.gold.read_text(encoding="utf-8") == expected
    assert score_baseline.load_labels(project.gold, "count") == {"frame_01.jpg": 2, "frame_03.jpg": 0}
    assert "frame_03.jpg: count 0 recorded." in done.stdout and "Labels:" in done.stdout, done.stdout
    rows = project.ledger_rows("labels_recorded")
    assert len(rows) == 1 and rows[0]["label_entry"] == "record-option" and rows[0]["status"] == "success", rows
    assert rows[0]["label_set"] == project.gold.name, rows
    assert rows[0]["gold_sha256"] == hashlib.sha256(project.gold.read_bytes()).hexdigest(), rows
    assert rows[0]["label_digests"] == prediction_freeze.label_digests(
        score_baseline.load_labels(project.gold, "count")
    )
    assert '"count"' not in json.dumps(rows[0]) and "added=2" in str(rows[0]["notes"]), "no label value on the row"

    same = project.label("--record", "frame_01.jpg=2")
    assert same.returncode == 0 and "already 2; unchanged" in same.stdout, same.stdout
    assert len(project.ledger_rows("labels_recorded")) == 1, "an unchanged write records no row"
    before = project.gold.read_bytes()
    refused = (
        ("--record", "frame_01.jpg=5"),
        ("--record", "frame_09.jpg=1"),
        ("--record", "frame_02.jpg=-1"),
        ("--record", "frame_02.jpg=1.5"),
        ("--record", "frame_02.jpg=three"),
        ("--record", "frame_02.jpg="),
        ("--record", "frame_02.jpg"),
        ("--record", "frame_02.jpg=1", "--record", "frame_02.jpg=2"),
    )
    for args in refused:
        result = project.label(*args)
        assert result.returncode == 2 and "label-gold-error" in result.stderr, (args, result.stderr)
        assert "Traceback" not in result.stderr, result.stderr
        assert project.gold.read_bytes() == before, args
    assert "pass --relabel" in project.label("--record", "frame_01.jpg=5").stderr

    changed = project.label("--record", "frame_01.jpg=5", "--relabel")
    assert changed.returncode == 0 and "changed from 2 to 5" in changed.stdout, changed.stdout
    assert len(project.ledger_rows("labels_recorded")) == 2 and "changed=1" in str(project.ledger_rows()[-1]["notes"])
    kept = sorted(item.name for item in project.gold.parent.iterdir())
    assert kept == sorted([project.gold.name, project.ledger.name]), f"temporary file left: {kept}"


def assert_unrecorded_write_rolled_back(tmp: Path) -> None:
    """A write whose ledger row cannot be recorded is undone; a missing ledger helper is refused before writing."""
    project = make_project(tmp, "rollback", 2)
    missing = project.label("--record", "frame_01.jpg=1", "--ledger-helper", str(project.root / "nope.py"))
    assert missing.returncode == 2 and "cannot find the ledger helper" in missing.stderr, missing.stderr
    assert not project.gold.exists()
    failing = project.root / "failing_helper.py"
    failing.write_text("import sys\nprint('helper refused', file=sys.stderr)\nsys.exit(2)\n", encoding="utf-8")
    first = project.label("--record", "frame_01.jpg=1", "--ledger-helper", str(failing))
    assert first.returncode == 2 and "helper refused" in first.stderr and not project.gold.exists(), first.stderr
    assert project.label("--record", "frame_01.jpg=1").returncode == 0
    before = project.gold.read_bytes()
    second = project.label("--record", "frame_02.jpg=4", "--ledger-helper", str(failing))
    assert second.returncode == 2 and project.gold.read_bytes() == before, second.stderr


def assert_folder_boundary(tmp: Path) -> None:
    """Only regular, visible image files directly in the folder can be labeled; links are never followed."""
    project = make_project(tmp, "boundary", 2)
    (project.frames / "nested").mkdir()
    (project.frames / "nested" / "deep.jpg").write_bytes(b"x")
    (project.frames / ".hidden.jpg").write_bytes(b"x")
    (project.frames / "notes.txt").write_text("not an image", encoding="utf-8")
    outside = project.root / "outside.jpg"
    outside.write_bytes(b"x")
    cases = ["nested/deep.jpg=1", ".hidden.jpg=1", "notes.txt=1", f"{outside}=1"]
    if os.name == "posix":
        (project.frames / "linked.jpg").symlink_to(outside)
        cases.append("linked.jpg=1")
    for case in cases:
        result = project.label("--record", case)
        assert result.returncode == 2 and not project.gold.exists(), (case, result.stderr)
    if os.name == "posix":
        assert "symbolic link" in project.label("--record", "linked.jpg=1").stderr
        victim = project.root / "victim.jsonl"
        victim.write_text("victim\n", encoding="utf-8")
        project.gold.symlink_to(victim)
        result = project.label("--record", "frame_01.jpg=1")
        assert result.returncode == 2 and "symbolic link" in result.stderr, result.stderr
        assert victim.read_text(encoding="utf-8") == "victim\n"
        project.gold.unlink()
    assert project.label("--record", "frame_02.jpg=1").returncode == 0

    # A label file outside the project folder is refused; anywhere inside it is allowed.
    escaped = project.label("--record", "frame_01.jpg=1", gold=tmp / "gold-outside.jsonl")
    assert escaped.returncode == 2 and "must sit inside the project folder" in escaped.stderr, escaped.stderr
    assert not (tmp / "gold-outside.jsonl").exists()
    labels_dir = project.root / "labels"
    labels_dir.mkdir()
    beside = project.label("--record", "frame_01.jpg=1", gold=labels_dir / "gold.jsonl")
    assert beside.returncode == 0, beside.stderr
    assert project.ledger_rows("labels_recorded")[-1]["label_set"] == "../labels/gold.jsonl"

    # Images directly in the project root: the label file in .vision-delivery sits inside the image folder.
    inside = tmp / "inside"
    (inside / ".vision-delivery").mkdir(parents=True)
    (inside / "frame_01.jpg").write_bytes(b"x")
    labels = inside / ".vision-delivery" / "gold.jsonl"
    result = run(
        LABEL, "--images", str(inside), "--labels", str(labels), "--task", "count", "--record", "frame_01.jpg=1"
    )
    assert result.returncode == 0 and "the label file is inside the image folder" in result.stdout, result.stdout
    empty = tmp / "empty-folder"
    empty.mkdir()
    result = run(LABEL, "--images", str(empty), "--labels", str(tmp / "g.jsonl"), "--task", "count", "--status")
    assert result.returncode == 2 and "no images directly in" in result.stderr, result.stderr


def assert_interactive(tmp: Path) -> None:
    """Interactive mode needs a terminal, asks only about unlabeled images, saves every answer, and resumes."""
    project = make_project(tmp, "interactive", 4)
    piped = project.label(stdin="3\n1\nq\n")
    assert piped.returncode == 2 and "standard input is not a terminal" in piped.stderr, piped.stderr
    assert "--record" in piped.stderr and not project.gold.exists() and not project.ledger_rows()
    if not HAS_PTY:
        print("skipped: interactive labeling through a pseudo-terminal needs a POSIX host")
        return
    code, first = project.label_tty(answers="3\nabc\n1\nq\n")
    assert code == 0, first
    assert "a count must be a whole number" in first and "Enter keeps" not in first, first
    assert score_baseline.load_labels(project.gold, "count") == {"frame_01.jpg": 3, "frame_02.jpg": 1}
    assert "2 answers saved this run" in first, first
    rows = project.ledger_rows("labels_recorded")
    assert [row["label_entry"] for row in rows] == ["interactive-terminal", "interactive-terminal"], rows

    code, second = project.label_tty(answers="s\n4\n")
    assert code == 0, second
    assert "frame_01.jpg" not in second.split("Stopped")[0] and "[1/2]" in second, second
    assert score_baseline.load_labels(project.gold, "count") == {
        "frame_01.jpg": 3,
        "frame_02.jpg": 1,
        "frame_04.jpg": 4,
    }

    code, review = project.label_tty("--relabel", answers="\n2\nq\n")
    assert code == 0 and "Enter keeps 3" in review, review
    assert score_baseline.load_labels(project.gold, "count")["frame_02.jpg"] == 2
    assert score_baseline.load_labels(project.gold, "count")["frame_01.jpg"] == 3

    # A later --record write makes the label file's entry mixed.
    assert project.label("--record", "frame_03.jpg=0").returncode == 0
    pred = write_pred(project.root / "pred.jsonl", score_baseline.load_labels(project.gold, "count"))
    assert project.freeze(pred, "--predictor", "isolated-subagent").returncode == 0
    assert project.ledger_rows("predictions_frozen")[0]["label_entry"] == "mixed"

    flags = make_project(tmp, "interactive-flag", 2, task="flag")
    code, result = flags.label_tty(answers="maybe\ny\nno\n")
    assert code == 0 and "a flag must be yes or no" in result, result
    assert score_baseline.load_labels(flags.gold, "flag") == {"frame_01.jpg": True, "frame_02.jpg": False}
    assert "Every image in the folder already has a label" in flags.label_tty(answers="")[1]


def assert_sample_floor(tmp: Path) -> None:
    """The floor report uses the scorer's own minimums and separates real cases from clean images."""
    assert label_gold.MIN_DENOMINATOR is score_baseline.MIN_DENOMINATOR
    minimum, boot = score_baseline.MIN_DENOMINATOR, score_baseline.MIN_BOOTSTRAP_UNITS
    exact = "for a verdict on images counted exactly right (exact_count_rate)"
    agreement = "for a verdict on per-image count agreement (catch_rate)"
    few = label_gold.sample_floor(label_gold.Task.COUNT, {f"i{n}": 1 for n in range(minimum - 1)})
    assert any(line.startswith(f"Too small {exact}") for line in few), few
    enough = label_gold.sample_floor(label_gold.Task.COUNT, {f"i{n}": 1 for n in range(minimum)})
    assert any(line.startswith(f"Large enough {exact}: {minimum} images") for line in enough), enough

    # Images with no objects count for count_mae but not for the per-object metrics.
    mixed = {f"i{n}": (1 if n < boot - 1 else 0) for n in range(boot + 3)}
    lines = label_gold.sample_floor(label_gold.Task.COUNT, mixed)
    assert any(line.startswith(f"Too small {agreement}: {boot - 1} images with labeled objects") for line in lines)
    assert any(line.startswith("Large enough for a verdict on average count error per image") for line in lines)
    mixed["extra"] = 2
    lines = label_gold.sample_floor(label_gold.Task.COUNT, mixed)
    assert any(line.startswith(f"Large enough {agreement}: {boot} images with labeled objects") for line in lines)

    flags = {"a": True, "b": True, "c": False}
    lines = label_gold.sample_floor(label_gold.Task.FLAG, flags)
    assert lines[0] == "3 images labeled: 2 real cases and 1 clean image.", lines
    clean = "(false_alarm_rate): 1 clean image, 5 needed; label 4 more clean images."
    assert any(clean in line for line in lines), lines
    assert all(floor.needed == minimum for floor in label_gold.metric_floors(label_gold.Task.FLAG, flags))

    project = make_project(tmp, "floor", 3)
    project.label("--record", "frame_01.jpg=1")
    status = project.label("--status")
    assert status.returncode == 0 and "2 images in the folder have no label yet" in status.stdout, status.stdout
    assert "Not frozen" in status.stdout, status.stdout


def assert_list_images(tmp: Path) -> None:
    """List mode prints labeled image paths and never a label value."""
    project = make_project(tmp, "listing", 3)
    assert project.label("--list-images").returncode == 2
    project.label("--record", "frame_03.jpg=7", "--record", "frame_01.jpg=9")
    listed = project.label("--list-images")
    assert listed.returncode == 0, listed.stderr
    expected = [os.path.abspath(project.frames / name) for name in ("frame_01.jpg", "frame_03.jpg")]
    assert listed.stdout.splitlines() == expected, listed.stdout
    (project.frames / "frame_03.jpg").unlink()
    gone = project.label("--list-images")
    assert gone.returncode == 2 and "not in" in gone.stderr, gone.stderr


def labeled_project(tmp: Path, name: str) -> tuple[Project, dict[str, object]]:
    """Return a project whose six images are labeled through the helper, and those labels."""
    project = make_project(tmp, name, 6)
    labels: dict[str, object] = {f"frame_{index:02d}.jpg": index % 3 for index in range(1, 7)}
    done = project.label(*(part for image, value in labels.items() for part in ("--record", f"{image}={value}")))
    assert done.returncode == 0, done.stderr
    return project, labels


def assert_freeze_records(tmp: Path) -> None:
    """The freeze records helper-computed facts once, and later label writes are refused with a reason."""
    project, labels = labeled_project(tmp, "freeze")
    pred = write_pred(project.root / ".vision-delivery" / "pred-rung0-demo.jsonl", labels)
    frozen = project.freeze(pred, "--predictor", "isolated-subagent")
    assert frozen.returncode == 0, frozen.stderr
    result = json.loads(frozen.stdout)
    pred_sha = hashlib.sha256(pred.read_bytes()).hexdigest()
    gold_sha = hashlib.sha256(project.gold.read_bytes()).hexdigest()
    assert (result["pred_sha256"], result["gold_sha256"]) == (pred_sha, gold_sha), result
    assert result["event_id"] == f"manual:demo:predictions_frozen:{pred_sha[:12]}-{gold_sha[:12]}", result
    rows = project.ledger_rows("predictions_frozen")
    assert len(rows) == 1 and rows[0]["status"] == "success", rows
    assert rows[0]["label_set"] == project.gold.name and rows[0]["predictor"] == "isolated-subagent", rows
    assert rows[0]["pred_sha256"] == pred_sha and "predictor=isolated-subagent" in str(rows[0]["notes"]), rows
    assert rows[0]["label_entry"] == "record-option" and rows[0]["labels_changed_after_freeze"] == 0, rows
    assert rows[0]["labels_changed_after_predictions"] is False, rows
    assert rows[0]["label_digests"] == prediction_freeze.label_digests(
        score_baseline.load_labels(project.gold, "count")
    )
    assert project.freeze(pred, "--predictor", "isolated-subagent").returncode == 0
    assert len(project.ledger_rows("predictions_frozen")) == 1, "an identical freeze must not add a row"

    before = project.gold.read_bytes()
    for args in (("--record", "frame_01.jpg=9", "--relabel"), ("--record", "frame_01.jpg=1")):
        refused = project.label(*args)
        assert refused.returncode == 2 and "frozen at" in refused.stderr, (args, refused.stderr)
        assert "can no longer be added or changed" in refused.stderr and "start a new label file" in refused.stderr
    if HAS_PTY:
        code, output = project.label_tty(answers="1\n")
        assert code == 2 and "frozen at" in output and "[1/" not in output, output
    assert project.gold.read_bytes() == before
    assert "Frozen: predictions for this label set" in project.label("--status").stdout
    assert project.label("--list-images").returncode == 0


def assert_refit_copy_disclosed(tmp: Path) -> None:
    """A copied label file refitted to the predictions, frozen with reformatted predictions, is refused or disclosed."""
    project, labels = labeled_project(tmp, "refit")
    pred = write_pred(project.root / ".vision-delivery" / "pred.jsonl", {**labels, "frame_01.jpg": 0})
    assert project.freeze(pred, "--predictor", "isolated-subagent").returncode == 0
    copy = project.gold.with_name("gold-refit-2.jsonl")
    shutil.copyfile(project.gold, copy)
    assert project.label("--record", "frame_01.jpg=0", "--relabel", gold=copy).returncode == 0
    reformatted = write_pred(
        project.root / ".vision-delivery" / "pred-2.jsonl", {**labels, "frame_01.jpg": 0}, separator=":  "
    )
    for candidate in (pred, reformatted):
        refused = project.freeze(candidate, "--predictor", "isolated-subagent", gold=copy)
        assert refused.returncode == 2 and "1 label differs from an earlier prediction freeze" in refused.stderr
        assert "--acknowledge-label-change" in refused.stderr, refused.stderr
    assert project.score(reformatted, gold=copy).returncode == 2, "an unrecorded freeze cannot be scored"

    acknowledged = project.freeze(
        reformatted, "--predictor", "isolated-subagent", "--acknowledge-label-change", gold=copy
    )
    assert acknowledged.returncode == 0, acknowledged.stderr
    assert project.ledger_rows("predictions_frozen")[-1]["labels_changed_after_freeze"] == 1
    line, block = scored_record(project.score(reformatted, gold=copy))
    assert "1 label changed after an earlier prediction freeze: this is not an independent measurement." in line, line
    assert block["labels_changed_after_freeze"] == 1 and block["independent"] is False, block

    # Direct writer route: the same freeze through ledger_append.py is refused the same way.
    direct = run(
        APPEND, "--ledger", str(project.ledger), "--session", "d", "--skill", "x", "--action", "predictions_frozen",
        "--event-id", "manual:direct:1", "--status", "success", "--pred", str(pred), "--gold", str(copy),
        "--predictor", "isolated-subagent",
    )  # fmt: skip
    assert direct.returncode == 2 and "1 label differs" in direct.stderr, direct.stderr
    # In-place edit of a frozen label file: always refused, acknowledged or not.
    project.gold.write_text(project.gold.read_text(encoding="utf-8").replace('"count": 1', '"count": 0', 1), "utf-8")
    for extra in ((), ("--acknowledge-label-change",)):
        inplace = run(
            APPEND, "--ledger", str(project.ledger), "--session", "d", "--skill", "x", "--action",
            "predictions_frozen", "--event-id", "manual:direct:2", "--status", "success", "--pred", str(pred),
            "--gold", str(project.gold), "--predictor", "isolated-subagent", *extra,
        )  # fmt: skip
        assert inplace.returncode == 2 and "changed after predictions for it were frozen" in inplace.stderr


def assert_label_change_after_predictions(tmp: Path) -> None:
    """Score first, relabel, then freeze: refused; acknowledged, the scorer says the result is not independent."""
    project, labels = labeled_project(tmp, "late")
    pred = write_pred(project.root / ".vision-delivery" / "pred.jsonl", {**labels, "frame_01.jpg": 0})
    unfrozen = run(SCORER, "--gold", str(project.gold), "--pred", str(pred), *TARGET)
    assert unfrozen.returncode == 0, unfrozen.stderr
    time.sleep(1.2)  # the ledger time has whole seconds; the relabel must fall after the prediction file
    assert project.label("--record", "frame_01.jpg=0", "--relabel").returncode == 0
    refused = project.freeze(pred, "--predictor", "isolated-subagent")
    assert refused.returncode == 2 and "after the prediction file was written" in refused.stderr, refused.stderr
    acknowledged = project.freeze(pred, "--predictor", "isolated-subagent", "--acknowledge-label-change")
    assert acknowledged.returncode == 0, acknowledged.stderr
    line, block = scored_record(project.score(pred))
    assert "Labels changed after the prediction file was written: this is not an independent measurement." in line
    assert block["labels_changed_after_predictions"] is True and block["independent"] is False, block

    # A hand edit after the helper's last recorded write trips the same check.
    edited, edited_labels = labeled_project(tmp, "late-edit")
    edited.gold.write_text(edited.gold.read_text(encoding="utf-8").replace('"count": 2', '"count": 3', 1), "utf-8")
    pred = write_pred(edited.root / "pred.jsonl", edited_labels)
    result = edited.freeze(pred, "--predictor", "isolated-subagent")
    assert result.returncode == 2 and "changed since its last recorded write" in result.stderr, result.stderr


def assert_freeze_refusals(tmp: Path) -> None:
    """The freeze refuses hand-edited labels, unknown images, malformed files, links, and a missing writer."""
    project, labels = labeled_project(tmp, "refuse")
    pred = write_pred(project.root / "pred.jsonl", labels)
    assert project.freeze(pred, "--predictor", "same-session").returncode == 0
    row = project.ledger_rows("predictions_frozen")[0]
    assert "independence not enforced" in str(row["notes"]) and row["predictor"] == "same-session", row

    # Hand-editing the frozen label file, then freezing new predictions on it, is refused.
    with project.gold.open("a", encoding="utf-8") as stream:
        stream.write('{"image": "frame_07.jpg", "count": 1}\n')
    other = write_pred(project.root / "pred-2.jsonl", {**labels, "frame_07.jpg": 1})
    edited = project.freeze(other, "--predictor", "isolated-subagent", "--acknowledge-label-change")
    assert edited.returncode == 2 and "changed after predictions for it were frozen" in edited.stderr, edited.stderr

    fresh, fresh_labels = labeled_project(tmp, "refuse-fresh")
    rows_before = len(fresh.ledger_rows())
    unknown = write_pred(fresh.root / "pred-unknown.jsonl", {"frame_99.jpg": 1})
    malformed = fresh.root / "pred-bad.jsonl"
    malformed.write_text('{"image": "frame_01.jpg", "count": -2}\n', encoding="utf-8")
    flagged = write_pred(fresh.root / "pred-flag.jsonl", {"frame_01.jpg": True}, field="flag")
    for bad in (unknown, malformed, flagged, fresh.root / "missing.jsonl"):
        result = fresh.freeze(bad, "--predictor", "isolated-subagent")
        assert result.returncode == 2 and "freeze-predictions-error" in result.stderr, (bad, result.stderr)
    good = write_pred(fresh.root / "pred-good.jsonl", fresh_labels)
    if os.name == "posix":
        link = fresh.root / "pred-link.jsonl"
        link.symlink_to(good)
        assert fresh.freeze(link, "--predictor", "isolated-subagent").returncode == 2
    lost = fresh.freeze(good, "--predictor", "isolated-subagent", "--ledger-helper", str(fresh.root / "nope.py"))
    assert lost.returncode == 2 and "cannot find the ledger helper" in lost.stderr, lost.stderr
    assert len(fresh.ledger_rows()) == rows_before, "a refused freeze must not write the ledger"
    assert fresh.freeze(good, "--predictor", "isolated-subagent").returncode == 0


def assert_default_ledger(tmp: Path) -> None:
    """Without --ledger, the ledger is ledger.jsonl in the label file's .vision-delivery folder, from any cwd."""
    project, labels = labeled_project(tmp, "default")
    pred = write_pred(project.root / "pred.jsonl", labels)
    elsewhere = tmp / "elsewhere"
    elsewhere.mkdir()
    args = ("--task", "count", "--gold", str(project.gold), "--pred", str(pred), "--predictor", "isolated-subagent")
    frozen = run(FREEZE, *args, "--session", "d", "--skill", "classify-or-flag", cwd=elsewhere)
    assert frozen.returncode == 0, frozen.stderr
    assert json.loads(frozen.stdout)["ledger"] == str(project.ledger)
    common = ("--images", str(project.frames), "--labels", str(project.gold), "--task", "count")
    for cwd in (elsewhere, project.root):
        refused = run(LABEL, *common, "--record", "frame_01.jpg=2", "--relabel", cwd=cwd)
        assert refused.returncode == 2 and "frozen at" in refused.stderr, refused.stderr
        assert "Frozen:" in run(LABEL, *common, "--status", cwd=cwd).stdout
    assert not (elsewhere / ".vision-delivery").exists()

    outside = project.root / "gold-outside.jsonl"
    result = run(LABEL, *common[:2], "--labels", str(outside), "--task", "count", "--status", cwd=project.root)
    assert result.returncode == 2 and "pass --ledger" in result.stderr, result.stderr
    result = run(FREEZE, *args[:2], "--gold", str(outside), *args[4:], "--session", "d", "--skill", "s")
    assert result.returncode == 2 and "pass --ledger" in result.stderr, result.stderr

    # The writer itself refuses a label file outside the project folder.
    foreign = write_pred(tmp / "gold-foreign.jsonl", labels)
    direct = run(
        APPEND, "--ledger", str(project.ledger), "--session", "d", "--skill", "x", "--action", "labels_recorded",
        "--event-id", "manual:foreign:1", "--status", "success", "--gold", str(foreign), "--label-entry",
        "record-option",
    )  # fmt: skip
    assert direct.returncode == 2 and "must sit inside the project folder" in direct.stderr, direct.stderr


def assert_scored_after_freeze(tmp: Path) -> None:
    """The whole flow: label, list, predict, freeze, score with the freeze check; tampering is refused."""
    project, labels = labeled_project(tmp, "flow")
    listed = project.label("--list-images").stdout.splitlines()
    pred = write_pred(project.root / "pred.jsonl", {Path(path).name: 1 for path in listed})
    assert project.freeze(pred, "--predictor", "isolated-subagent").returncode == 0
    scored = project.score(pred)
    assert scored.returncode == 0, scored.stderr
    line, block = scored_record(scored)
    assert line.endswith(f"Missing predictions: 0. {CLEAN_NOTE} {RECORD_NOTE}"), line
    assert block["label_entry"] == "record-option" and block["independent"] is True, block
    assert block["ledger_is_project_ledger"] is True and block["predictor_declared"] == "isolated-subagent", block
    assert "frozen before scoring" not in scored.stdout
    pred.write_text(pred.read_text(encoding="utf-8").replace('"count": 1', '"count": 0', 1), encoding="utf-8")
    tampered = project.score(pred)
    assert tampered.returncode == 2 and "not frozen before scoring" in tampered.stderr, tampered.stderr
    assert tampered.stdout == "", "nothing may be scored when the freeze check fails"

    if not HAS_PTY:
        print("skipped: the interactive-label scoring case needs a POSIX host")
        return
    typed = make_project(tmp, "typed", 2)
    code, output = typed.label_tty(answers="1\n0\n")
    assert code == 0, output
    pred = write_pred(typed.root / "pred.jsonl", {"frame_01.jpg": 1, "frame_02.jpg": 0})
    assert typed.freeze(pred, "--predictor", "isolated-subagent").returncode == 0
    line, block = scored_record(typed.score(pred))
    assert line.endswith(f"Missing predictions: 0. {CLEAN_NOTE}"), line
    assert block["label_entry"] == "interactive-terminal" and block["independent"] is True, block


def assert_hand_written_rows(tmp: Path) -> None:
    """A hand-written freeze row without the helper's fields is not a freeze, for the scorer or the labeling guard."""
    project, labels = labeled_project(tmp, "hand")
    pred = write_pred(project.root / "pred.jsonl", labels)
    digests = {
        "pred_sha256": hashlib.sha256(pred.read_bytes()).hexdigest(),
        "gold_sha256": hashlib.sha256(project.gold.read_bytes()).hexdigest(),
    }
    base = {"action": "predictions_frozen", "status": "success", "event_id": "hand", "predictor": "isolated-subagent"}
    for row in (
        {**base, **digests, "ts": "x", "label_set": "x"},
        {**base, **digests, "ts": "2026-11-10T00:00:00Z", "label_set": project.gold.name},
        {**base, **digests, "ts": "2026-11-10T00:00:00Z", "label_set": f"../.vision-delivery/{project.gold.name}"},
    ):
        with project.ledger.open("a", encoding="utf-8") as stream:
            stream.write(json.dumps(row) + "\n")
        assert project.score(pred).returncode == 2, row
        assert "Not frozen" in project.label("--status").stdout, row


def _assert_text_write(project: Project, image: str, value: str, *, relabel: bool = False) -> None:
    """Check one text write, its exact scorer round-trip, and its value-free ledger receipt."""
    count = len(project.ledger_rows("labels_recorded"))
    result = project.label("--record", f"{image}={value}", *(("--relabel",) if relabel else ()))
    assert result.returncode == 0, result.stderr
    labels = score_baseline.load_labels(project.gold, "text")
    assert labels[Path(image).name] == value, labels
    rows = project.ledger_rows("labels_recorded")
    assert len(rows) == count + 1, rows
    row = rows[-1]
    assert row["label_entry"] == "record-option" and row["status"] == "success", row
    assert row["gold_sha256"] == hashlib.sha256(project.gold.read_bytes()).hexdigest(), row
    assert row["label_digests"] == {
        name: prediction_freeze.label_digest(name, label) for name, label in labels.items()
    }, row
    assert '"text"' not in json.dumps(row) and '"value"' not in json.dumps(row), row


def assert_text_record_mode(tmp: Path) -> None:
    """Text records preserve equals signs, whitespace, Unicode, empty strings, and the maximum length.

    Examples:
        Run through ``main()`` to exercise real helper subprocesses in a temporary project.
    """
    project = make_project(tmp, "text-record", 7, task="text")
    _assert_text_write(project, "frame_01.jpg", "total=a=b==")
    _assert_text_write(project, str(project.frames / "frame_02.jpg"), "  padded label  ")
    _assert_text_write(project, "frame_03.jpg", "Příliš žluťoučký 🐈 e\u0301")
    _assert_text_write(project, "frame_04.jpg", "")
    _assert_text_write(project, "frame_05.jpg", "🐈" * 10_000)
    (project.frames / "name=part.jpg").write_bytes(b"placeholder")
    _assert_text_write(project, "name=part.jpg", "x=y")
    same = project.label("--record", "frame_04.jpg=")
    assert same.returncode == 0 and "unchanged" in same.stdout, same.stderr
    assert len(project.ledger_rows("labels_recorded")) == 6


def assert_text_record_refusals(tmp: Path) -> None:
    """Invalid or changed text records leave the entire gold file and ledger unchanged.

    Examples:
        Run through ``main()`` to verify refusal and nearby allowed relabeling.
    """
    project = make_project(tmp, "text-refused", 2, task="text")
    _assert_text_write(project, "frame_01.jpg", "original secret label")
    before, ledger = project.gold.read_bytes(), project.ledger.read_bytes()
    oversized = project.label("--record", "frame_02.jpg=" + "x" * 10_001)
    assert oversized.returncode == 2 and "10,000" in oversized.stderr, oversized.stderr
    assert project.gold.read_bytes() == before and project.ledger.read_bytes() == ledger
    unknown = project.label("--record", "missing.jpg=private unresolved label")
    assert unknown.returncode == 2 and "label-gold-error" in unknown.stderr, unknown.stderr
    assert "private unresolved label" not in unknown.stderr + unknown.stdout
    assert str(project.frames) in unknown.stderr and "no '=' split names an image" in unknown.stderr
    assert project.gold.read_bytes() == before and project.ledger.read_bytes() == ledger
    changed = project.label("--record", "frame_01.jpg=changed secret label")
    assert changed.returncode == 2 and "--relabel" in changed.stderr, changed.stderr
    assert "secret label" not in changed.stderr + changed.stdout
    assert project.gold.read_bytes() == before and project.ledger.read_bytes() == ledger
    batch = project.label("--record", "frame_02.jpg=valid", "--record", "missing.jpg=bad")
    assert batch.returncode == 2 and project.gold.read_bytes() == before
    assert project.ledger.read_bytes() == ledger
    _assert_text_write(project, "frame_01.jpg", "changed secret label", relabel=True)
    status, listed = project.label("--status"), project.label("--list-images")
    assert status.returncode == listed.returncode == 0, (status.stderr, listed.stderr)
    assert "secret label" not in status.stdout + listed.stdout
    assert listed.stdout.splitlines() == [str(project.frames / "frame_01.jpg")]


def _assert_text_separator(tmp: Path, separator: str, name: str) -> None:
    """Keep Unicode line separators in text values and escape them in the gold file."""
    project = make_project(tmp, name, 1, task="text")
    value = f"café{separator}receipt"
    _assert_text_write(project, "frame_01.jpg", value)
    written = project.gold.read_text(encoding="utf-8")
    assert separator not in written and f"\\u{ord(separator):04x}" in written, repr(written)
    assert "café" in written
    status = project.label("--status")
    assert status.returncode == 0, status.stderr
    assert (
        prediction_freeze.label_digest("frame_01.jpg", value)
        == hashlib.sha256(("frame_01.jpg\0" + json.dumps(value)).encode("utf-8")).hexdigest()[
            : prediction_freeze.LABEL_DIGEST_HEX
        ]
    )
    pred = project.root / "pred.jsonl"
    pred.write_bytes(
        (json.dumps({"image": "frame_01.jpg", "text": value}, ensure_ascii=False) + "\r\n").encode("utf-8")
    )
    frozen = project.freeze(pred, "--predictor", "isolated-subagent")
    assert frozen.returncode == 0, frozen.stderr
    rows = project.ledger_rows()
    rows[-1]["notes"] = value
    project.ledger.write_bytes("".join(json.dumps(row, ensure_ascii=False) + "\r\n" for row in rows).encode("utf-8"))
    freezes = prediction_freeze.read_freezes(project.ledger)
    assert len(freezes) == 1 and freezes[0].gold_sha256 == hashlib.sha256(project.gold.read_bytes()).hexdigest()


def assert_text_ambiguous_record(tmp: Path) -> None:
    """Refuse multiple image-name splits without labeling either image.

    Examples:
        Run through ``main()`` to check ambiguous input and its nearby unique split.
    """
    project = make_project(tmp, "text-ambiguous", 1, task="text")
    (project.frames / "frame_01.jpg=other.jpg").write_bytes(b"placeholder")
    result = project.label("--record", "frame_01.jpg=other.jpg=private value")
    assert result.returncode == 2 and "2 image names match" in result.stderr, result.stderr
    assert "interactive mode" in result.stderr and "private value" not in result.stdout + result.stderr
    assert not project.gold.exists() and not project.ledger.exists()
    _assert_text_write(project, "frame_01.jpg", "one=split")
    assert "frame_01.jpg=other.jpg" not in score_baseline.load_labels(project.gold, "text")


def _assert_text_prefix_errors(tmp: Path) -> None:
    """Treat label prefixes that cannot be filesystem paths as nonmatching splits."""
    project = make_project(tmp, "text-prefix-errors", 1, task="text")
    value = "private receipt " * 30 + "=total"
    _assert_text_write(project, "frame_01.jpg", value)
    unresolved = project.label("--record", f"missing.jpg={value}")
    assert unresolved.returncode == 2 and "no '=' split names an image" in unresolved.stderr, unresolved.stderr
    assert "private receipt" not in unresolved.stderr + unresolved.stdout
    labels = label_gold.LabelSet(project.frames, project.gold, label_gold.Task.TEXT, project.ledger, ("frame_01.jpg",))
    assert label_gold.parse_text_record("frame_01.jpg=receipt\0part=total", labels) == (
        "frame_01.jpg",
        "receipt\0part=total",
    )


def assert_text_write_rollback(tmp: Path) -> None:
    """Restore text gold bytes, or remove a new file, when the ledger helper refuses.

    Examples:
        Run through ``main()`` to exercise the same failure hook as count labels.
    """
    project = make_project(tmp, "text-rollback", 2, task="text")
    failing = project.root / "failing_helper.py"
    failing.write_text("import sys\nprint('helper refused', file=sys.stderr)\nsys.exit(2)\n", encoding="utf-8")
    first = project.label("--record", "frame_01.jpg=café\u2028receipt", "--ledger-helper", str(failing))
    assert first.returncode == 2 and "helper refused" in first.stderr, first.stderr
    assert not project.gold.exists() and not project.ledger.exists()
    _assert_text_write(project, "frame_01.jpg", "café\u2028receipt")
    before, ledger = project.gold.read_bytes(), project.ledger.read_bytes()
    second = project.label("--record", "frame_02.jpg=new receipt", "--ledger-helper", str(failing))
    assert second.returncode == 2 and "helper refused" in second.stderr, second.stderr
    assert project.gold.read_bytes() == before and project.ledger.read_bytes() == ledger


def _assert_readback_rollback(tmp: Path, exists: bool) -> None:
    """Restore the prior file even when the published file fails its scorer read-back."""
    project = make_project(tmp, f"text-readback-{exists}", 2, task="text")
    before: bytes | None = None
    if exists:
        _assert_text_write(project, "frame_01.jpg", "old receipt")
        before = project.gold.read_bytes().replace(b"\n", b"\r\n")
        project.gold.write_bytes(before)
    ledger = project.ledger.read_bytes() if exists else None
    errors = io.StringIO()
    responses: list[object] = ([{"frame_01.jpg": "old receipt"}] if exists else []) + [OSError("read-back refused")]
    with (
        patch.object(label_gold, "load_labels", side_effect=responses, autospec=True),
        contextlib.redirect_stderr(errors),
    ):
        status = label_gold.main([*project.common(), "--record", "frame_02.jpg=new receipt"], say=lambda text: None)
    assert status == 2 and "read-back refused" in errors.getvalue(), errors.getvalue()
    assert (project.gold.read_bytes() if project.gold.exists() else None) == before
    assert (project.ledger.read_bytes() if project.ledger.exists() else None) == ledger


def assert_text_surrogate_refused(tmp: Path) -> None:
    """Reject a lone surrogate before writing text or echoing its value.

    Examples:
        Run through ``main()`` with in-process arguments, since OS argv cannot encode a surrogate.
    """
    project = make_project(tmp, "text-surrogate", 2, task="text")
    _assert_text_write(project, "frame_01.jpg", "original receipt")
    before, ledger = project.gold.read_bytes(), project.ledger.read_bytes()
    errors, output = io.StringIO(), io.StringIO()
    with contextlib.redirect_stderr(errors), contextlib.redirect_stdout(output):
        status = label_gold.main([*project.common(), "--record", "frame_02.jpg=private\ud800value"])
    assert status == 2 and "text must not hold a lone surrogate code point" in errors.getvalue()
    assert "private" not in errors.getvalue() + output.getvalue()
    assert project.gold.read_bytes() == before and project.ledger.read_bytes() == ledger


def assert_text_interactive(tmp: Path) -> None:
    """Text terminals save s/q verbatim and reserve only exact colon commands; piped answers are refused.

    Examples:
        Run through ``main()``; terminal cases use the existing POSIX pseudo-terminal harness.
    """
    project = make_project(tmp, "text-interactive", 7, task="text")
    piped = project.label(stdin="s\nq\n:quit\n")
    assert piped.returncode == 2 and "standard input is not a terminal" in piped.stderr, piped.stderr
    assert not project.gold.exists() and not project.ledger_rows()
    if not HAS_PTY:
        print("skipped: interactive text labeling through a pseudo-terminal needs a POSIX host")
        return
    code, output = project.label_tty(answers="\ns\nq\n:skip\n:empty\n  spaced  \n :quit \n:quit\n")
    assert code == 0, output
    expected = {
        "frame_01.jpg": "s",
        "frame_02.jpg": "q",
        "frame_04.jpg": "",
        "frame_05.jpg": "  spaced  ",
        "frame_06.jpg": " :quit ",
    }
    assert score_baseline.load_labels(project.gold, "text") == expected
    assert ":skip" in output and ":quit" in output and ":empty" in output, output
    assert 'text "  spaced  " recorded.' in output and 'text "" recorded.' in output, output
    rows = project.ledger_rows("labels_recorded")
    assert len(rows) == 5 and all(row["label_entry"] == "interactive-terminal" for row in rows), rows
    assert [row["label_digests"] for row in rows] == [
        {image: prediction_freeze.label_digest(image, value) for image, value in list(expected.items())[:size]}
        for size in range(1, 6)
    ]
    assert all('"text"' not in json.dumps(row) and '"value"' not in json.dumps(row) for row in rows)
    before = project.gold.read_bytes()
    code, kept = project.label_tty("--relabel", answers="\n:skip\n:skip\n\n:quit\n")
    assert code == 0 and 'Enter keeps "s"' in kept and 'Enter keeps ""' in kept, kept
    assert project.gold.read_bytes() == before and len(project.ledger_rows("labels_recorded")) == 5


def _assert_text_floor(size: int, exact_ready: bool, char_ready: bool) -> None:
    """Check each scorer-derived text metric floor and its printed readiness."""
    labels = {f"i{index}": "label" for index in range(size)}
    floors = label_gold.metric_floors(label_gold.Task.TEXT, labels)
    assert [(floor.metric, floor.units, floor.needed, floor.ready) for floor in floors] == [
        ("exact_match_rate", size, score_baseline.MIN_DENOMINATOR, exact_ready),
        ("char_error_rate", size, score_baseline.MIN_BOOTSTRAP_UNITS, char_ready),
    ]
    lines = label_gold.sample_floor(label_gold.Task.TEXT, labels)
    exact_prefix = "Large enough" if exact_ready else "Too small"
    char_prefix = "Large enough" if char_ready else "Too small"
    assert lines[1].startswith(exact_prefix) and "(exact_match_rate)" in lines[1], lines
    assert lines[2].startswith(char_prefix) and "(char_error_rate)" in lines[2], lines


def assert_text_sample_floor(tmp: Path) -> None:
    """Text readiness counts all labels for exact matches and only nonempty labels for character errors.

    Examples:
        Run through ``main()`` to check both metric tallies and the status CLI.
    """
    _assert_text_floor(0, False, False)
    _assert_text_floor(4, False, False)
    _assert_text_floor(5, True, False)
    _assert_text_floor(19, True, False)
    _assert_text_floor(20, True, True)
    labels = {f"i{index}": "" if index == 19 else "label" for index in range(20)}
    floors = label_gold.metric_floors(label_gold.Task.TEXT, labels)
    assert [(floor.metric, floor.units, floor.ready) for floor in floors] == [
        ("exact_match_rate", 20, True),
        ("char_error_rate", 19, False),
    ]
    lines = label_gold.sample_floor(label_gold.Task.TEXT, labels)
    assert "19 images with text" in lines[0] and "1 image with an empty label" in lines[0], lines
    assert lines[2].startswith("Too small") and "19 images with labeled text, 20 needed" in lines[2], lines
    project = make_project(tmp, "text-floor", 2, task="text")
    done = project.label("--record", "frame_01.jpg=", "--record", "frame_02.jpg=private floor label")
    assert done.returncode == 0, done.stderr
    status = project.label("--status")
    assert status.returncode == 0 and "1 image with text" in status.stdout, status.stderr
    assert "1 image with an empty label" in status.stdout and "private floor label" not in status.stdout


def assert_text_scored_after_freeze(tmp: Path) -> None:
    """The text label/list/predict/freeze/score flow records label provenance and freezes later writes.

    Examples:
        Run through ``main()`` to exercise the shipped scorer with ``--frozen-ledger``.
    """
    project = make_project(tmp, "text-flow", 6, task="text")
    records = [f"frame_{index:02d}.jpg=flow text {index}" for index in range(1, 6)]
    arguments = [arg for record in records for arg in ("--record", record)]
    labeled = project.label(*arguments)
    assert labeled.returncode == 0, labeled.stderr
    listed = project.label("--list-images")
    assert listed.returncode == 0 and "flow text" not in listed.stdout, listed.stderr
    assert [Path(path).name for path in listed.stdout.splitlines()] == [
        f"frame_{index:02d}.jpg" for index in range(1, 6)
    ]
    labels = score_baseline.load_labels(project.gold, "text")
    pred = write_pred(project.root / "pred.jsonl", labels, field="text")
    frozen = project.freeze(pred, "--predictor", "isolated-subagent")
    assert frozen.returncode == 0, frozen.stderr
    scored = run(
        SCORER,
        "--task",
        "text",
        "--gold",
        str(project.gold),
        "--pred",
        str(pred),
        "--metric",
        "exact_match_rate",
        "--comparator",
        "gte",
        "--threshold",
        "0.5",
        "--frozen-ledger",
        str(project.ledger),
    )
    assert scored.returncode == 0, scored.stderr
    _, block = scored_record(scored)
    assert block["label_entry"] == "record-option" and block["independent"] is True, block
    before, ledger = project.gold.read_bytes(), project.ledger.read_bytes()
    refused = project.label("--record", "frame_06.jpg=later")
    assert refused.returncode == 2 and "frozen" in refused.stderr, refused.stderr
    assert project.gold.read_bytes() == before and project.ledger.read_bytes() == ledger
    assert project.label("--status").returncode == project.label("--list-images").returncode == 0


def load_ledger_append() -> ModuleType:
    """Load the ledger helper module without running it."""
    spec = importlib.util.spec_from_file_location("sentinel_ledger_append", APPEND)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def assert_shared_names() -> None:
    """The ledger writer and the readers agree on action names, predictor and entry values, and label digests."""
    ledger_append = load_ledger_append()
    assert ledger_append.PREDICTIONS_ACTION == prediction_freeze.PREDICTIONS_FROZEN
    assert ledger_append.LABELS_ACTION == prediction_freeze.LABELS_RECORDED
    assert tuple(ledger_append.PREDICTORS) == tuple(item.value for item in prediction_freeze.Predictor)
    entries = (*ledger_append.LABEL_ENTRIES, ledger_append.MIXED_ENTRY, ledger_append.UNRECORDED_ENTRY)
    assert entries == tuple(item.value for item in prediction_freeze.LabelEntry)
    assert ledger_append.LABEL_DIGEST_HEX == prediction_freeze.LABEL_DIGEST_HEX
    for image, value in (("a.jpg", 0), ("a.jpg", 12), ("b c.png", True), ("ü.jpg", False)):
        assert ledger_append.label_digest(image, value) == prediction_freeze.label_digest(image, value)
    assert freeze_predictions.LEDGER_HELPER == APPEND.resolve() == prediction_freeze.LEDGER_HELPER
    assert "--pred" not in label_gold.parse_args(["--images", "x", "--labels", "y", "--task", "count"]).__dict__


def main() -> int:
    """Run doctests and CLI cases."""
    for module in (label_gold, prediction_freeze, freeze_predictions):
        failures, _ = doctest.testmod(module)
        assert failures == 0, f"{failures} doctest failure(s) in {module.__name__}"
    assert_shared_names()
    with tempfile.TemporaryDirectory() as raw:
        # The ledger helper refuses a ledger path with a symlinked ancestor (macOS /var is one).
        tmp = Path(raw).resolve()
        assert_record_mode(tmp)
        assert_unrecorded_write_rolled_back(tmp)
        assert_folder_boundary(tmp)
        assert_interactive(tmp)
        assert_sample_floor(tmp)
        assert_list_images(tmp)
        assert_freeze_records(tmp)
        assert_refit_copy_disclosed(tmp)
        assert_label_change_after_predictions(tmp)
        assert_freeze_refusals(tmp)
        assert_default_ledger(tmp)
        assert_scored_after_freeze(tmp)
        assert_hand_written_rows(tmp)
        assert_text_record_mode(tmp)
        assert_text_record_refusals(tmp)
        _assert_text_separator(tmp, "\u2028", "text-line-separator")
        _assert_text_separator(tmp, "\u2029", "text-paragraph-separator")
        _assert_text_separator(tmp, "\u0085", "text-next-line")
        assert_text_ambiguous_record(tmp)
        _assert_text_prefix_errors(tmp)
        assert_text_write_rollback(tmp)
        _assert_readback_rollback(tmp, False)
        _assert_readback_rollback(tmp, True)
        assert_text_surrogate_refused(tmp)
        assert_text_interactive(tmp)
        assert_text_sample_floor(tmp)
        assert_text_scored_after_freeze(tmp)
    print("labeling and prediction-freeze assertions passed")
    return 0


if __name__ == "__main__":
    sys.exit(main())
