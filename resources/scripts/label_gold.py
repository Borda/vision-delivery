#!/usr/bin/env python3
"""Record gold count or flag labels that a person enters, one image at a time.

Stdlib only. The person looks at each image and types its label: this helper never proposes a
label and never reads a model output. It writes the JSON Lines gold file `score_baseline.py`
reads, one line per image sorted by image name: `{"image": "<file>", "count": <n>}` or
`{"image": "<file>", "flag": true|false}`. The image name is the file name inside the image folder.

Modes:

- interactive (default): walks the image folder and asks for one label per unlabeled image. Each
  answer is saved at once, so stopping and rerunning continues where it stopped. It refuses to run
  when standard input is not a terminal, because piped answers do not come from a person typing.
- `--record IMAGE=VALUE`: records a label the person gave, for an agent transcribing labels from
  a chat without writing JSON by hand. Repeat the option to record several labels in one write.
  These labels are marked as entered through `--record`, and the scorer says so; an agent can call
  this option, so the mark discloses the route but does not block it.
- `--status`: prints how many images are labeled and whether that is enough for a verdict.
- `--list-images`: prints the absolute path of every labeled image and never a label value, so a
  predictor can be handed the images without the labels.

Rules:

- An existing label changes only with `--relabel`; recording the same value again changes nothing.
- An image must be a regular file directly in the image folder: no subfolders, no hidden files,
  and no symbolic links, so a label never points out of the folder.
- The ledger is `--ledger`, or `ledger.jsonl` in the `.vision-delivery` folder that holds the label
  file; the label file must sit inside the ledger's folder. The working directory is never used.
- Every write appends one `labels_recorded` row through `scripts/ledger_append.py`, the single
  ledger writer, which records the file's digest, a short digest of every label, and how the labels
  were entered (`interactive-terminal` or `record-option`), never a label value. When that row
  cannot be written, the label file is put back as it was.
- Once predictions for this label file have been frozen in the project ledger
  (`freeze_predictions.py`), no label may be added or changed: a label written after predictions
  exist could be fitted to them.
- Writes are atomic (a temporary file in the same folder, then a rename) and serialized by a lock
  folder next to the label file.

After each write it says whether the set is large enough for the scorer to give a verdict, using
the scorer's own minimums (`MIN_DENOMINATOR` cases for a rate, `MIN_BOOTSTRAP_UNITS` images for a
metric resampled over images).

Exit codes: 0 on success, including a stop in interactive mode; 2 when a label, an image, or a
file is refused; 130 when interrupted.
"""

from __future__ import annotations

import argparse
import contextlib
import json
import os
import re
import stat
import sys
import tempfile
import time
import uuid
from collections.abc import Callable, Iterator, Mapping
from contextlib import contextmanager
from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from typing import Any

from prediction_freeze import (
    LABELS_RECORDED,
    LEDGER_HELPER,
    LabelEntry,
    append_ledger_row,
    freezes_for_label_set,
    ledger_for_labels,
    require_helper,
)
from proof_chain import sha256_file
from score_baseline import (
    COUNT_METRICS,
    FLAG_METRICS,
    METRIC_TEXT,
    MIN_DENOMINATOR,
    count_metrics,
    flag_metrics,
    load_labels,
)

IMAGE_SUFFIXES = frozenset({".bmp", ".gif", ".jpeg", ".jpg", ".png", ".tif", ".tiff", ".webp"})
YES_WORDS = frozenset({"y", "yes", "true", "1"})
NO_WORDS = frozenset({"n", "no", "false", "0"})
COUNT_TEXT = re.compile(r"[0-9]+")
LOCK_TIMEOUT_SECONDS = 5.0
LOCK_RETRY_SECONDS = 0.02
EXIT_REFUSED = 2
EXIT_INTERRUPTED = 130


class Task(str, Enum):
    """Label kind: a non-negative count or a yes/no flag per image."""

    COUNT = "count"
    FLAG = "flag"


class Mode(str, Enum):
    """What one run of the helper does."""

    INTERACTIVE = "interactive"
    RECORD = "record"
    STATUS = "status"
    LIST = "list-images"


class Answer(Enum):
    """Interactive answers that are not a label."""

    SKIP = "skip"
    STOP = "stop"


class LabelError(ValueError):
    """A label, image, or label file the helper refuses; the message says why and what to do."""


@dataclass(frozen=True)
class LabelSet:
    """One label file for one task, the image folder it names, and the ledger that may freeze it."""

    folder: Path
    labels_path: Path
    task: Task
    ledger: Path
    images: tuple[str, ...]
    helper: Path = LEDGER_HELPER
    session: str = "labeling"


@dataclass(frozen=True)
class MetricFloor:
    """How many independent units back one scorer metric, against the scorer's minimum."""

    metric: str
    label: str
    units: int
    needed: int
    unit_noun: tuple[str, str]

    @property
    def ready(self) -> bool:
        """Return whether the scorer will not refuse this metric for too few units.

        Examples:
            >>> MetricFloor("accuracy", "images judged correctly", 5, 5, ("image", "images")).ready
            True
        """
        return self.units >= self.needed

    @property
    def noun(self) -> str:
        """Return the unit noun in the form that matches `units`.

        Examples:
            >>> MetricFloor("catch_rate", "real cases caught", 1, 5, ("real case", "real cases")).noun
            'real case'
        """
        return self.unit_noun[0] if self.units == 1 else self.unit_noun[1]


def show(value: Any) -> str:
    """Return a label value as it is written in the label file.

    Examples:
        >>> show(3), show(True)
        ('3', 'true')
    """
    return json.dumps(value)


def list_images(folder: Path) -> tuple[str, ...]:
    """Return the image file names directly in a folder, sorted; links, hidden files, and subfolders are skipped.

    Raises:
        LabelError: When the folder is missing or holds no image file.

    Examples:
        >>> import tempfile
        >>> with tempfile.TemporaryDirectory() as raw:
        ...     for name in ("b.png", "a.JPG", ".hidden.jpg", "notes.txt"):
        ...         _ = (Path(raw) / name).write_bytes(b"x")
        ...     list_images(Path(raw))
        ('a.JPG', 'b.png')
    """
    if not folder.is_dir():
        raise LabelError(f"image folder not found: {folder}")
    names: list[str] = []
    with os.scandir(folder) as entries:
        for entry in entries:
            if entry.name.startswith(".") or entry.is_symlink() or not entry.is_file(follow_symlinks=False):
                continue
            if Path(entry.name).suffix.lower() in IMAGE_SUFFIXES:
                names.append(entry.name)
    if not names:
        suffixes = ", ".join(sorted(IMAGE_SUFFIXES))
        raise LabelError(f"no images directly in {folder}: looked for regular {suffixes} files")
    return tuple(sorted(names))


def parse_value(task: Task, raw: str) -> int | bool:
    """Parse one label a person typed: a whole number for a count, yes or no for a flag.

    Raises:
        LabelError: When the text is not a valid label for the task.

    Examples:
        >>> parse_value(Task.COUNT, " 3 "), parse_value(Task.FLAG, "Y"), parse_value(Task.FLAG, "false")
        (3, True, False)
        >>> for bad in ("-1", "1.5", "three", ""):
        ...     try:
        ...         parse_value(Task.COUNT, bad)
        ...     except LabelError:
        ...         print("refused", repr(bad))
        refused '-1'
        refused '1.5'
        refused 'three'
        refused ''
    """
    text = raw.strip()
    if task == Task.COUNT:
        if not COUNT_TEXT.fullmatch(text):
            raise LabelError(f"a count must be a whole number of zero or more, such as 0 or 3: got {raw!r}")
        return int(text)
    word = text.lower()
    if word in YES_WORDS:
        return True
    if word in NO_WORDS:
        return False
    raise LabelError(f"a flag must be yes or no (also y/n, true/false, 1/0): got {raw!r}")


def parse_record(raw: str, task: Task) -> tuple[str, int | bool]:
    """Split one `IMAGE=VALUE` argument; the last `=` separates the value.

    Raises:
        LabelError: When the argument has no image name or no valid value.

    Examples:
        >>> parse_record("frame_014.jpg=3", Task.COUNT)
        ('frame_014.jpg', 3)
        >>> parse_record("a=b.png=no", Task.FLAG)
        ('a=b.png', False)
    """
    image, separator, value = raw.rpartition("=")
    if not separator or not image:
        raise LabelError(f"--record needs IMAGE=VALUE, such as frame_014.jpg=3: got {raw!r}")
    return image, parse_value(task, value)


def resolve_image(labels: LabelSet, name: str) -> str:
    """Return the image name a `--record` argument means: a listed name, or an absolute path to a listed file.

    Raises:
        LabelError: When the name is not a regular image file directly in the image folder.

    Examples:
        >>> ls = LabelSet(Path("/p/frames"), Path("/p/gold.jsonl"), Task.COUNT, Path("/p/l.jsonl"), ("a.jpg",))
        >>> resolve_image(ls, "a.jpg"), resolve_image(ls, "/p/frames/a.jpg")
        ('a.jpg', 'a.jpg')
    """
    if name in labels.images:
        return name
    candidate = Path(name) if Path(name).is_absolute() else labels.folder / name
    if Path(name).is_absolute():
        with contextlib.suppress(ValueError):
            relative = Path(os.path.relpath(os.path.abspath(name), os.path.abspath(labels.folder))).as_posix()
            if relative in labels.images:
                return relative
    if candidate.is_symlink():
        raise LabelError(f"{name!r} is a symbolic link; the helper never follows links, so label the file itself")
    raise LabelError(
        f"{name!r} is not an image directly in {labels.folder}; "
        f"name an image as it appears there, such as {labels.images[0]!r}"
    )


def read_labels(path: Path, task: Task) -> dict[str, Any]:
    """Return the labels already in a label file; a missing or empty file holds none.

    Raises:
        LabelError: When the file is a symbolic link, not a regular file, or not valid labels for the task.

    Examples:
        >>> import tempfile
        >>> with tempfile.TemporaryDirectory() as raw:
        ...     path = Path(raw) / "gold.jsonl"
        ...     before = read_labels(path, Task.FLAG)
        ...     _ = path.write_text('{"image": "a.jpg", "flag": true}\\n')
        ...     before, read_labels(path, Task.FLAG)
        ({}, {'a.jpg': True})
    """
    if path.is_symlink():
        raise LabelError(f"the label file is a symbolic link: {path}; the helper never writes through links")
    if not path.exists():
        return {}
    if not path.is_file():
        raise LabelError(f"the label file is not a regular file: {path}")
    if not path.read_text(encoding="utf-8").strip():
        return {}
    try:
        return load_labels(path, task.value)
    except json.JSONDecodeError as exc:
        raise LabelError(f"{path.name} is not valid JSON Lines: {exc}") from exc


def render_labels(task: Task, labels: Mapping[str, Any]) -> str:
    """Return the label file text: one JSON object per image, sorted by image name.

    Examples:
        >>> print(render_labels(Task.COUNT, {"b.jpg": 0, "a.jpg": 2}), end="")
        {"image": "a.jpg", "count": 2}
        {"image": "b.jpg", "count": 0}
    """
    return "".join(
        json.dumps({"image": image, task.value: labels[image]}, ensure_ascii=False) + "\n" for image in sorted(labels)
    )


def write_labels(path: Path, task: Task, labels: Mapping[str, Any]) -> None:
    """Replace the label file atomically and check that the scorer reads back exactly these labels.

    Raises:
        LabelError: When the path is a symbolic link or the file does not read back as written.

    Examples:
        >>> import tempfile
        >>> with tempfile.TemporaryDirectory() as raw:
        ...     path = Path(raw) / "gold.jsonl"
        ...     write_labels(path, Task.COUNT, {"a.jpg": 2})
        ...     path.read_text(), sorted(item.name for item in Path(raw).iterdir())
        ('{"image": "a.jpg", "count": 2}\\n', ['gold.jsonl'])
    """
    if path.is_symlink():
        raise LabelError(f"the label file is a symbolic link: {path}; the helper never writes through links")
    replace_file(path, render_labels(task, labels).encode("utf-8"))
    if labels and load_labels(path, task.value) != dict(labels):
        raise LabelError(f"the label file {path} did not read back as written")


def replace_file(path: Path, data: bytes) -> None:
    """Replace a file's bytes atomically through a temporary file in the same folder, keeping its mode."""
    mode = stat.S_IMODE(path.stat().st_mode) if path.exists() else 0o644
    descriptor, temp_name = tempfile.mkstemp(prefix=f".{path.name}.", suffix=".tmp", dir=path.parent)
    temp = Path(temp_name)
    try:
        with os.fdopen(descriptor, "wb") as stream:
            stream.write(data)
            stream.flush()
            os.fsync(stream.fileno())
        os.chmod(temp, mode)
        os.replace(temp, path)
    finally:
        if temp.exists():
            temp.unlink()


def record_write(labels: LabelSet, entry: LabelEntry, before: Mapping[str, Any], after: Mapping[str, Any]) -> None:
    """Append the `labels_recorded` row for one write; the ledger helper computes every digest itself.

    Raises:
        ValueError: When the ledger helper is missing or refuses the row.
    """
    added = sum(1 for image in after if image not in before)
    changed = sum(1 for image in after if image in before and before[image] != after[image])
    notes = f"task={labels.task.value}; images_labeled={len(after)}; added={added}; changed={changed}"
    unique = uuid.uuid4().hex[:12]
    identity = f"manual:{labels.session}:{LABELS_RECORDED}:{sha256_file(labels.labels_path)[:12]}-{unique}"
    arguments = ["--session", labels.session, "--skill", "label-gold", "--action", LABELS_RECORDED]
    arguments += ["--event-id", identity, "--status", "success", "--gold", str(labels.labels_path)]
    append_ledger_row(labels.helper, labels.ledger, [*arguments, "--label-entry", entry.value, "--notes", notes])


@contextmanager
def label_lock(path: Path) -> Iterator[None]:
    """Hold a lock folder next to the label file so two runs never write it at once."""
    lock = path.with_name(f"{path.name}.lock")
    deadline = time.monotonic() + LOCK_TIMEOUT_SECONDS
    while True:
        try:
            lock.mkdir()
            break
        except FileExistsError:
            if time.monotonic() >= deadline:
                raise LabelError(
                    f"another labeling run holds {lock}; wait for it, or remove that folder if no run is active"
                ) from None
            time.sleep(LOCK_RETRY_SECONDS)
    try:
        yield
    finally:
        with contextlib.suppress(OSError):
            lock.rmdir()


def check_not_frozen(labels: LabelSet) -> None:
    """Refuse any write once predictions for this label file are frozen in the ledger.

    Raises:
        LabelError: When the ledger holds a successful freeze naming this label file.
    """
    freezes = freezes_for_label_set(labels.ledger, labels.labels_path)
    if freezes:
        first = freezes[0]
        raise LabelError(
            f"predictions for this label set were frozen at {first.frozen_at} (ledger event {first.event_id} in "
            f"{labels.ledger}), so its labels can no longer be added or changed: a label written after predictions "
            "exist could be fitted to them. To label more images, start a new label file (you may copy this file's "
            "lines into it first), then run a fresh rung 0 prediction on all of its images and freeze that."
        )


def merge_labels(
    task: Task, labels: Mapping[str, Any], changes: Mapping[str, Any], relabel: bool
) -> tuple[dict[str, Any], list[str]]:
    """Apply new labels to existing ones and say what happened to each.

    Raises:
        LabelError: When an image already has a different label and `relabel` is not set.

    Examples:
        >>> merge_labels(Task.COUNT, {"a.jpg": 2}, {"a.jpg": 2, "b.jpg": 0}, relabel=False)
        ({'a.jpg': 2, 'b.jpg': 0}, ['a.jpg: already 2; unchanged.', 'b.jpg: count 0 recorded.'])
        >>> merge_labels(Task.COUNT, {"a.jpg": 2}, {"a.jpg": 3}, relabel=True)[1]
        ['a.jpg: count changed from 2 to 3.']
    """
    merged = dict(labels)
    notes: list[str] = []
    for image, value in changes.items():
        if image not in merged:
            notes.append(f"{image}: {task.value} {show(value)} recorded.")
        elif merged[image] == value:
            notes.append(f"{image}: already {show(value)}; unchanged.")
        elif not relabel:
            raise LabelError(
                f"{image} already has {task.value} {show(merged[image])}; pass --relabel to change it to {show(value)}"
            )
        else:
            notes.append(f"{image}: {task.value} changed from {show(merged[image])} to {show(value)}.")
        merged[image] = value
    return merged, notes


def commit(
    labels: LabelSet, changes: Mapping[str, Any], relabel: bool, entry: LabelEntry
) -> tuple[dict[str, Any], list[str]]:
    """Under the lock: refuse a frozen set, re-read the file, merge the changes, write, and record the write.

    When the ledger row cannot be written, the label file is put back as it was before this write.
    """
    labels.labels_path.parent.mkdir(parents=True, exist_ok=True)
    with label_lock(labels.labels_path):
        check_not_frozen(labels)
        current = read_labels(labels.labels_path, labels.task)
        merged, notes = merge_labels(labels.task, current, changes, relabel)
        if merged != current:
            before = labels.labels_path.read_bytes() if labels.labels_path.exists() else None
            write_labels(labels.labels_path, labels.task, merged)
            try:
                record_write(labels, entry, current, merged)
            except ValueError:
                if before is None:
                    labels.labels_path.unlink()
                else:
                    replace_file(labels.labels_path, before)
                raise
    return merged, notes


def metric_floors(task: Task, labels: Mapping[str, Any]) -> list[MetricFloor]:
    """Return each gold-only metric's units against the scorer's minimum, using the scorer's own tallies.

    Flag `precision` is left out: its denominator is the number of flags the predictions raise.

    Examples:
        >>> [(item.metric, item.units, item.needed) for item in metric_floors(Task.FLAG, {"a": True, "b": False})]
        [('catch_rate', 1, 5), ('false_alarm_rate', 1, 5), ('accuracy', 2, 5)]
    """
    gold = dict(labels)
    metrics: tuple[str, ...]
    if task == Task.COUNT:
        tallies, metrics = count_metrics(gold, gold), COUNT_METRICS
    else:
        tallies, metrics = flag_metrics(gold, gold), tuple(name for name in FLAG_METRICS if name != "precision")
    floors: list[MetricFloor] = []
    for metric in metrics:
        text, tally = METRIC_TEXT[(task.value, metric)], tallies[metric]
        floors.append(MetricFloor(metric, text.label, tally.units, tally.units_needed, text.unit_noun))
    return floors


def _plural(count: int, singular: str, plural: str) -> str:
    """Return `count` with the matching noun form."""
    return f"{count} {singular if count == 1 else plural}"


def headline(task: Task, labels: Mapping[str, Any], unlabeled: int) -> str:
    """Return the one-sentence size of the label set.

    Examples:
        >>> headline(Task.COUNT, {"a": 2, "b": 0}, 3)
        '2 images labeled, 1 of them with objects; 3 images in the folder have no label yet.'
        >>> headline(Task.FLAG, {"a": True, "b": False, "c": False}, 0)
        '3 images labeled: 1 real case and 2 clean images.'
    """
    total = len(labels)
    if task == Task.COUNT:
        with_objects = sum(1 for value in labels.values() if value > 0)
        text = f"{_plural(total, 'image', 'images')} labeled, {with_objects} of them with objects"
    else:
        real = sum(1 for value in labels.values() if value)
        text = (
            f"{_plural(total, 'image', 'images')} labeled: {_plural(real, 'real case', 'real cases')} "
            f"and {_plural(total - real, 'clean image', 'clean images')}"
        )
    if unlabeled:
        verb = "has" if unlabeled == 1 else "have"
        return f"{text}; {_plural(unlabeled, 'image', 'images')} in the folder {verb} no label yet."
    return f"{text}."


def sample_floor(task: Task, labels: Mapping[str, Any], unlabeled: int = 0) -> list[str]:
    """Return plain sentences saying whether the label set is large enough for the scorer to give a verdict.

    Examples:
        >>> lines = sample_floor(Task.COUNT, {f"i{index}": 1 for index in range(6)})
        >>> print(lines[0])
        6 images labeled, 6 of them with objects.
        >>> print(lines[2])
        Large enough for a verdict on images counted exactly right (exact_count_rate): 6 images, 5 needed.
        >>> print(lines[3].split(": ", 1)[1])
        6 images with labeled objects, 20 needed; label 14 more images with labeled objects.
        >>> [line.split(" for a verdict")[0] for line in lines[1:5]]
        ['Too small', 'Large enough', 'Too small', 'Too small']
    """
    lines = [headline(task, labels, unlabeled)]
    floors = metric_floors(task, labels)
    for floor in floors:
        size = f"{floor.units} {floor.noun}, {floor.needed} needed"
        if floor.ready:
            lines.append(f"Large enough for a verdict on {floor.label} ({floor.metric}): {size}.")
        else:
            more = floor.needed - floor.units
            noun = floor.unit_noun[0] if more == 1 else floor.unit_noun[1]
            lines.append(
                f"Too small for a verdict on {floor.label} ({floor.metric}): {size}; label {more} more {noun}."
            )
    if task == Task.FLAG:
        lines.append(
            "Flags that were real (precision) depends on how many flags the predictions raise; "
            f"it needs at least {MIN_DENOMINATOR} raised flags."
        )
    if any(floor.ready for floor in floors):
        lines.append(
            "Large enough means the scorer will not refuse for too few cases; "
            "a small set can still come back INCONCLUSIVE."
        )
    return lines


def floor_summary(task: Task, labels: Mapping[str, Any]) -> str:
    """Return a one-line version of the sample floor for interactive mode.

    Examples:
        >>> floor_summary(Task.FLAG, {f"i{index}": index < 5 for index in range(7)})
        'Verdict possible on: catch_rate, accuracy. Not yet: false_alarm_rate (2 of 5 clean images).'
    """
    floors = metric_floors(task, labels)
    ready = [floor.metric for floor in floors if floor.ready]
    waiting = [
        f"{floor.metric} ({floor.units} of {floor.needed} {floor.unit_noun[1]})" for floor in floors if not floor.ready
    ]
    parts = [f"Verdict possible on: {', '.join(ready)}." if ready else "No verdict possible yet."]
    if waiting:
        parts.append(f"Not yet: {', '.join(waiting)}.")
    return " ".join(parts)


def report(labels: LabelSet, current: Mapping[str, Any], say: Callable[[str], None]) -> None:
    """Print the sample floor, labels for images no longer in the folder, and where the labels live."""
    unlabeled = sum(1 for image in labels.images if image not in current)
    for line in sample_floor(labels.task, current, unlabeled):
        say(line)
    absent = sorted(set(current) - set(labels.images))
    if absent:
        say(f"Warning: {len(absent)} labeled images are not in the image folder, for example {absent[0]!r}.")
    labels_real = Path(os.path.realpath(labels.labels_path))
    if labels_real.is_relative_to(os.path.realpath(labels.folder)):
        say(
            "Warning: the label file is inside the image folder; move it out (for example to .vision-delivery/) "
            "so a predictor handed this folder cannot open it."
        )
    say(f"Labels: {labels.labels_path}")


def run_record(labels: LabelSet, records: list[str], relabel: bool, say: Callable[[str], None]) -> int:
    """Record the labels given as `IMAGE=VALUE` arguments in one atomic write."""
    changes: dict[str, Any] = {}
    for raw in records:
        name, value = parse_record(raw, labels.task)
        image = resolve_image(labels, name)
        if image in changes and changes[image] != value:
            raise LabelError(f"{image} is given twice with different values")
        changes[image] = value
    merged, notes = commit(labels, changes, relabel, LabelEntry.RECORD_OPTION)
    for note in notes:
        say(note)
    report(labels, merged, say)
    return 0


def run_status(labels: LabelSet, say: Callable[[str], None]) -> int:
    """Print the label set's size, sample floor, and whether its predictions are frozen."""
    current = read_labels(labels.labels_path, labels.task)
    report(labels, current, say)
    freezes = freezes_for_label_set(labels.ledger, labels.labels_path)
    if freezes:
        frozen_at = freezes[0].frozen_at
        say(f"Frozen: predictions for this label set were frozen at {frozen_at}; labels can no longer change.")
    else:
        say(f"Not frozen: no prediction freeze in {labels.ledger} names this label file; labels can still change.")
    return 0


def run_list(labels: LabelSet, say: Callable[[str], None]) -> int:
    """Print the absolute path of every labeled image, never a label value.

    Raises:
        LabelError: When nothing is labeled yet, or a labeled image is missing from the folder.
    """
    current = read_labels(labels.labels_path, labels.task)
    if not current:
        raise LabelError(f"no labels in {labels.labels_path} yet; label images before predicting")
    absent = sorted(set(current) - set(labels.images))
    if absent:
        raise LabelError(f"{len(absent)} labeled images are not in {labels.folder}, for example {absent[0]!r}")
    for image in sorted(current):
        say(os.path.abspath(labels.folder / image))
    return 0


def ask_label(
    ask: Callable[[str], str], say: Callable[[str], None], task: Task, head: str, current: Any
) -> int | bool | Answer:
    """Ask for one label until the answer is valid, a skip, or a stop; end of input stops."""
    hint = "count (a whole number)" if task == Task.COUNT else "flag (y = real case, n = clean)"
    keep = f", Enter keeps {show(current)}" if current is not None else ""
    prompt = f"{head}\n  {hint}{keep}, s = skip, q = stop: "
    while True:
        try:
            raw = ask(prompt)
        except EOFError:
            return Answer.STOP
        word = raw.strip().lower()
        if word == "q":
            return Answer.STOP
        if word == "s" or (not word and current is not None):
            return Answer.SKIP
        try:
            return parse_value(task, raw)
        except LabelError as exc:
            say(f"  {exc}")


def run_interactive(labels: LabelSet, relabel: bool, ask: Callable[[str], str], say: Callable[[str], None]) -> int:
    """Walk the image folder and save each label the person types, continuing where an earlier run stopped."""
    current = read_labels(labels.labels_path, labels.task)
    check_not_frozen(labels)
    queue = [image for image in labels.images if relabel or image not in current]
    if not queue:
        say("Every image in the folder already has a label; pass --relabel to review them.")
        report(labels, current, say)
        return 0
    what = "how many objects it shows" if labels.task == Task.COUNT else "y if it is a real case, n if it is clean"
    say(
        f"{_plural(len(queue), 'image', 'images')} to label from {labels.folder} into {labels.labels_path}. "
        f"Open each image, look at it, and type {what}. Nothing is suggested: every label is yours. "
        "Each answer is saved at once; rerun to continue where you stopped."
    )
    saved = 0
    try:
        for index, image in enumerate(queue, 1):
            head = f"[{index}/{len(queue)}] {os.path.abspath(labels.folder / image)}"
            answer = ask_label(ask, say, labels.task, head, current.get(image))
            if answer is Answer.STOP:
                break
            if isinstance(answer, Answer):
                continue
            current, notes = commit(labels, {image: answer}, relabel, LabelEntry.INTERACTIVE_TERMINAL)
            saved += 1
            say(" ".join([*notes, floor_summary(labels.task, current)]))
    except KeyboardInterrupt:
        say(f"\nStopped. {_plural(saved, 'answer', 'answers')} saved; rerun to continue.")
        return EXIT_INTERRUPTED
    say(f"Stopped. {_plural(saved, 'answer', 'answers')} saved this run.")
    report(labels, current, say)
    return 0


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    """Parse labeling inputs."""
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--images", required=True, type=Path, help="folder that holds the images directly")
    parser.add_argument("--labels", required=True, type=Path, help="gold JSON Lines file to create or extend")
    parser.add_argument("--task", required=True, choices=[item.value for item in Task])
    parser.add_argument(
        "--ledger", type=Path, help="project ledger (default: ledger.jsonl in the .vision-delivery folder of --labels)"
    )
    parser.add_argument("--session", default="labeling", help="session slug recorded on the ledger rows")
    parser.add_argument("--ledger-helper", type=Path, default=LEDGER_HELPER, help=argparse.SUPPRESS)
    parser.add_argument("--relabel", action="store_true", help="allow changing a label that already exists")
    modes = parser.add_mutually_exclusive_group()
    modes.add_argument("--record", action="append", metavar="IMAGE=VALUE", help="record a label the person gave")
    modes.add_argument("--status", action="store_true", help="print the label set's size and sample floor")
    modes.add_argument("--list-images", action="store_true", help="print labeled image paths, never their labels")
    return parser.parse_args(argv)


def select_mode(args: argparse.Namespace) -> Mode:
    """Return the mode the arguments ask for; interactive when no other mode is named.

    Examples:
        >>> select_mode(argparse.Namespace(record=None, status=False, list_images=True)).value
        'list-images'
    """
    if args.record:
        return Mode.RECORD
    if args.status:
        return Mode.STATUS
    if args.list_images:
        return Mode.LIST
    return Mode.INTERACTIVE


def main(argv: list[str] | None = None, ask: Callable[[str], str] = input, say: Callable[[str], None] = print) -> int:
    """Run one labeling mode and return its exit code."""
    args = parse_args(argv)
    try:
        images = list_images(args.images)
        ledger = ledger_for_labels(args.labels, args.ledger)
        labels = LabelSet(args.images, args.labels, Task(args.task), ledger, images, args.ledger_helper, args.session)
        mode = select_mode(args)
        if mode in (Mode.RECORD, Mode.INTERACTIVE):
            require_helper(labels.helper)
        if mode == Mode.RECORD:
            return run_record(labels, args.record, args.relabel, say)
        if mode == Mode.STATUS:
            return run_status(labels, say)
        if mode == Mode.LIST:
            return run_list(labels, say)
        if not sys.stdin.isatty():
            raise LabelError(
                "interactive labeling needs a person typing at a terminal, and standard input is not a terminal; "
                "to record labels a person gave you, use --record IMAGE=VALUE (those labels are marked as entered "
                "through --record)"
            )
        return run_interactive(labels, args.relabel, ask, say)
    except (ValueError, OSError) as exc:
        print(f"label-gold-error: {exc}", file=sys.stderr)
        return EXIT_REFUSED


if __name__ == "__main__":
    sys.exit(main())
