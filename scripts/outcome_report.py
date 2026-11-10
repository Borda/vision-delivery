#!/usr/bin/env python3
"""Draft a redacted Sentinel outcome report from the project ledger and eval files.

The draft answers the fields of the project's outcome-report issue form, for the user to check
and post themselves. It is printed, or written to a new file with ``--out``. This helper never
posts anything, opens no network connection, and never writes the ledger.

Workspace and project identifiers, session names, acceptance IDs, file paths, and free-text
notes are withheld by default; each comes back only with its own ``--include-*`` flag. Text
that looks like a credential is always removed, and email addresses, IPv4 addresses, and host
names are always masked. A metric name is shown only when the scorer defines it.

The scrub is a denylist. It cannot recognize a customer, site, product, or person named in
words the ledger does not hold, and the draft tells the user so.

Usage:
    python3 scripts/outcome_report.py --ledger <project>/.vision-delivery/ledger.jsonl --host claude-code \\
        [--route <name>|not-sure] [--experience none|some|professional] [--decision go|revise-or-stop|no] \\
        [--friction "text"] [--include-identifiers] [--include-paths] [--include-notes] [--out PATH] [--json]

Exit codes:
    0: the draft was printed, and written to ``--out`` when given. An empty ledger, or ledger lines
       that are not one JSON object each, only add an ``outcome-report-warning`` on standard error;
       such lines are skipped.
    2: no draft (``outcome-report-error`` on standard error): the ledger is missing or unreadable,
       an answer or the skill roster is invalid, or ``--out`` names an existing file or link.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from pathlib import Path
from typing import Any

from ledger_report import (
    STEP_TITLES,
    DeliveryStep,
    Measurement,
    Milestone,
    ProjectStatus,
    Verdict,
    _default_ledger,
    load_records,
    parse_time,
    project_status,
    scan_eval_files,
)
from redaction import (
    ABSOLUTE_PATH,
    EMAIL,
    HOME_PATH_TO_LINE_END,
    HOST_NAME,
    RELATIVE_FILE,
    RELATIVE_PATH,
    URL_HOST,
    mask_ipv4,
    remove_credentials,
)
from skill_roster import Roster, RosterError, Surface, load_roster

NOT_SURE = "not sure"
REDACTED_IDENTIFIER = "[identifier]"
REDACTED_PATH = "[path]"
REDACTED_SECRET = "[removed: looked like a credential]"
REDACTED_EMAIL = "[email]"
REDACTED_ADDRESS = "[address]"
REDACTED_HOST = "[host]"
#: Shortest identifier the scrubber replaces inside free text, always as a whole token.
MIN_IDENTIFIER_LENGTH = 2
MAX_NOTES = 10
#: Metric names the scorer (``resources/scripts/score_baseline.py``) defines; any other metric text may be free text.
SCORER_METRICS = frozenset(
    {"accuracy", "catch_rate", "count_mae", "exact_count_rate", "false_alarm_rate", "over_count_rate", "precision"}
)
PLAIN_WORDS = "recorded in plain words"
#: Placeholders for identifiers held back from path scrubbing: private-use characters, never word characters.
_HELD_BASE = 0xE100
_HELD_OPEN, _HELD_CLOSE = chr(0xE000), chr(0xE001)
_HELD = re.compile(f"{_HELD_OPEN}([{chr(_HELD_BASE)}-{chr(0xF8FF)}]){_HELD_CLOSE}")
#: What the scrub cannot do, printed in every draft.
UNDETECTABLE_NOTICE = (
    "Sentinel can detect credentials, file paths, host names, email and IPv4 addresses, and the identifiers the "
    "ledger records. It cannot recognize a customer, site, product, or person named in words the ledger does not "
    "hold: find and remove those yourself."
)


class Host(str, Enum):
    """The host the skill ran on."""

    CLAUDE_CODE = "claude-code"
    CODEX = "codex"


class Experience(str, Enum):
    """The user's computer-vision experience before the session."""

    NONE = "none"
    SOME = "some"
    PROFESSIONAL = "professional"


class Decision(str, Enum):
    """Whether Sentinel helped the user reach a decision."""

    GO = "go"
    REVISE_OR_STOP = "revise-or-stop"
    NO = "no"


HOST_LABELS = {Host.CLAUDE_CODE: "Claude Code", Host.CODEX: "Codex"}
DECISION_LABELS = {Decision.GO: "yes, go", Decision.REVISE_OR_STOP: "yes, revise or stop", Decision.NO: "no"}
#: Form answer for the furthest milestone reached, furthest first.
FURTHEST_LABELS = (
    (Milestone.DECISION_REPORT, "decision report"),
    (Milestone.PROOF, "delivery handoff or artifact"),
    (Milestone.TRAINED, "trained or improved a model"),
    (Milestone.MEASURED_HIGHER_RUNG, "higher-rung baseline scored"),
    (Milestone.MEASURED, "rung 0 baseline scored"),
    (Milestone.TARGET_LOCKED, "target agreed"),
)


@dataclass(frozen=True)
class FormField:
    """One field of the outcome-report issue form."""

    field_id: str
    label: str
    options: tuple[str, ...]
    required: bool


#: The issue form's fields in order; the route options come from the roster at run time.
FORM_FIELDS = (
    FormField("host", "Host", tuple(HOST_LABELS.values()), True),
    FormField("route", "Route used", (), True),
    FormField(
        "experience", "Your computer-vision experience before this session", tuple(e.value for e in Experience), True
    ),
    FormField("furthest", "Furthest step reached", tuple(label for _, label in reversed(FURTHEST_LABELS)), True),
    FormField("outcome", "Did it help you reach a decision?", tuple(DECISION_LABELS.values()), True),
    FormField("time", "Rough time to the first measured number", (), False),
    FormField("friction", "What got in the way, or what worked well", (), False),
)


@dataclass(frozen=True)
class Redaction:
    """Which withheld groups the user chose to include."""

    identifiers: bool = False
    paths: bool = False
    notes: bool = False


@dataclass(frozen=True)
class DraftInputs:
    """Answers only the user can give, plus the redaction choice."""

    host: Host | None = None
    route: str = ""
    experience: Experience | None = None
    decision: Decision | None = None
    friction: str = ""
    redaction: Redaction = field(default_factory=Redaction)


@dataclass(frozen=True)
class OutcomeDraft:
    """A filled outcome report, ready to print as Markdown or JSON."""

    title: str
    answers: dict[str, str]
    filled_by: dict[str, str]
    evidence: tuple[str, ...]
    withheld: tuple[str, ...]
    route_options: tuple[str, ...]

    def to_markdown(self) -> str:
        """Render the draft as Markdown, one form field per heading.

        Examples:
            >>> draft = OutcomeDraft("t", {}, {}, (), (), ("read-text",))
            >>> "### Route used" in draft.to_markdown()
            True
        """
        lines = [
            f"# Draft outcome report: {self.title}",
            "",
            "> Check every line for private data before you post it. Sentinel did not post this draft and never "
            "will. Open the outcome-report issue form yourself and copy each answer into the field of the same name.",
            ">",
            f"> {UNDETECTABLE_NOTICE}",
        ]
        for form_field in FORM_FIELDS:
            options = self.route_options if form_field.field_id == "route" else form_field.options
            answer = self.answers.get(form_field.field_id, "")
            if not answer:
                answer = f"_Choose one: {'; '.join(options)}._" if options else "_Optional: write this yourself._"
            lines.extend(["", f"### {form_field.label}", "", answer])
        lines.extend(["", "## How each answer was filled", ""])
        lines.extend(f"- {_label(field_id)}: {how}" for field_id, how in self.filled_by.items())
        lines.extend(["", "## Evidence you may paste into the last field", ""])
        lines.extend(f"- {line}" for line in self.evidence)
        if self.withheld:
            lines.extend(["", "## Withheld from this draft", ""])
            lines.extend(f"- {line}" for line in self.withheld)
        return "\n".join(lines) + "\n"

    def to_json(self) -> dict[str, Any]:
        """Return the draft as JSON-ready data.

        Examples:
            >>> OutcomeDraft("t", {"host": "Codex"}, {}, (), (), ()).to_json()["answers"]
            {'host': 'Codex'}
        """
        return {
            "title": self.title,
            "notice": UNDETECTABLE_NOTICE,
            "answers": dict(self.answers),
            "filled_by": dict(self.filled_by),
            "evidence": list(self.evidence),
            "withheld": list(self.withheld),
            "route_options": list(self.route_options),
        }


def _label(field_id: str) -> str:
    """Return the form label of one field id."""
    return next(item.label for item in FORM_FIELDS if item.field_id == field_id)


def route_options(roster: Roster) -> tuple[str, ...]:
    """Return the form's route choices: every roster route on the issue form, then "not sure".

    Examples:
        >>> route_options(load_roster())[-1]
        'not sure'
    """
    return (*sorted(roster.on_surface(Surface.ISSUE_FORM)), NOT_SURE)


def furthest_step(milestones: frozenset[Milestone]) -> str:
    """Return the form answer for the furthest step the ledger and eval files prove.

    Examples:
        >>> furthest_step(frozenset({Milestone.TARGET_LOCKED, Milestone.MEASURED}))
        'rung 0 baseline scored'
        >>> furthest_step(frozenset())
        ''
    """
    return next((label for milestone, label in FURTHEST_LABELS if milestone in milestones), "")


def derived_route(records: list[dict[str, Any]], options: tuple[str, ...]) -> str:
    """Return the route of the latest skill-written ledger row that names a form route.

    Examples:
        >>> derived_route([{"source": "skill", "skill": "read-text"}], ("read-text", "not sure"))
        'read-text'
        >>> derived_route([{"source": "hook", "skill": "hook"}], ("read-text", "not sure"))
        ''
    """
    for record in reversed(records):
        if record.get("source") == "skill" and record.get("skill") in options and record.get("skill") != NOT_SURE:
            return str(record["skill"])
    return ""


def _duration(minutes: float) -> str:
    """Say a duration roughly, the way the form's placeholder does."""
    if minutes < 1:
        return "under a minute"
    if minutes < 120:
        return f"about {round(minutes)} minutes"
    if minutes < 48 * 60:
        return f"about {round(minutes / 60)} hours"
    return f"about {round(minutes / (24 * 60))} days"


def time_to_first_number(ledger: Path, records: list[dict[str, Any]]) -> str:
    """Return the rough time from the first recorded step to the first measured number.

    The start is the earliest ledger row or frozen target; the end is the earliest scorer
    result or ``baseline_measured`` row. Empty when either is missing.

    Examples:
        >>> rows = [{"ts": "2026-11-10T10:00:00Z"},
        ...         {"ts": "2026-11-10T10:12:00Z", "action": "baseline_measured", "status": "success"}]
        >>> time_to_first_number(Path("no-such-dir") / "ledger.jsonl", rows)
        'about 12 minutes'
    """
    files = scan_eval_files(ledger.parent)
    starts = [parse_time(record.get("ts")) for record in records]
    starts += [parse_time(target.frozen_at) for target in files.acceptances]
    ends = [parse_time(result.measured_at) for result in files.evidence]
    ends += [
        parse_time(record.get("ts"))
        for record in records
        if record.get("action") == "baseline_measured" and record.get("status") == "success"
    ]
    start = min((moment for moment in starts if moment is not None), default=None)
    end = min((moment for moment in ends if moment is not None), default=None)
    if start is None or end is None or end < start:
        return ""
    return _duration((end - start).total_seconds() / 60)


def known_identifiers(records: list[dict[str, Any]], status: ProjectStatus, safe: set[str]) -> set[str]:
    """Collect project-identifying strings: sessions, entity paths and their parts, acceptance IDs.

    Examples:
        >>> rows = [{"session": "factory-counter", "entity_id": "acme-ws/conveyor/3"}]
        >>> empty = project_status(Path("no-such-dir") / "ledger.jsonl")
        >>> sorted(known_identifiers(rows, empty, set()))
        ['acme-ws', 'acme-ws/conveyor/3', 'conveyor', 'factory-counter']
    """
    found: set[str] = {status.session}
    for record in records:
        for key in ("session", "entity_id", "acceptance_id", "brief_event_id", "event_id"):
            value = record.get(key)
            if isinstance(value, str):
                found.add(value)
                found.update(value.split("/") if key == "entity_id" else ())
    if status.target is not None:
        found.add(status.target.acceptance_id)
    safe_keys = {_normalized(item) for item in safe}
    return {item for item in found if len(item) >= MIN_IDENTIFIER_LENGTH and _normalized(item) not in safe_keys}


def _normalized(text: str) -> str:
    """Fold letter case and treat ``_`` as ``-``, the way identifiers are matched."""
    return text.casefold().replace("_", "-")


def _identifier_pattern(identifier: str) -> re.Pattern[str]:
    """Match one identifier as a whole token in any letter case, with ``-`` and ``_`` interchangeable."""
    body = "".join("[-_]" if char in "-_" else re.escape(char) for char in identifier)
    return re.compile(rf"(?<![\w-]){body}(?![\w-])", re.IGNORECASE)


def _scrub_addresses(text: str) -> str:
    """Remove email addresses, IPv4 addresses, and host names; no flag brings these back."""
    text = EMAIL.sub(REDACTED_EMAIL, text)
    text = mask_ipv4(text, REDACTED_ADDRESS)
    text = URL_HOST.sub(REDACTED_HOST, text)
    return HOST_NAME.sub(REDACTED_HOST, text)


def _scrub_paths(text: str, private_paths: tuple[str, ...]) -> str:
    """Remove a home-folder path to the end of its line, the project's own paths, and any other path."""
    text = HOME_PATH_TO_LINE_END.sub(REDACTED_PATH, text)
    for private in sorted((item for item in private_paths if item), key=len, reverse=True):
        text = text.replace(private, REDACTED_PATH)
    for pattern in (ABSOLUTE_PATH, RELATIVE_PATH, RELATIVE_FILE):
        text = pattern.sub(REDACTED_PATH, text)
    return text


def scrub(text: str, identifiers: set[str], redaction: Redaction, private_paths: tuple[str, ...]) -> str:
    """Remove credentials, addresses, and host names always; identifiers and paths unless the user included them.

    Examples:
        >>> scrub("ACME_Line slow at datasets/acme/v3 and /home/u/acme frames", {"acme-line"}, Redaction(), ())
        '[identifier] slow at [path] and [path]'
        >>> key = "AKIA" + "0123456789ABCDEF"
        >>> scrub(f"key {key} on gpu7.acme.internal", set(), Redaction(identifiers=True, paths=True), ())
        'key [removed: looked like a credential] on [host]'
    """
    text = _scrub_addresses(remove_credentials(text, REDACTED_SECRET))
    if redaction.paths:
        return text if redaction.identifiers else _hide_identifiers(text, identifiers)
    if redaction.identifiers:
        # An included identifier such as ``workspace/project/3`` is shaped like a relative path: hold it back.
        held, kept = _hold_identifiers(text, identifiers)
        return _HELD.sub(lambda match: kept[ord(match.group(1)) - _HELD_BASE], _scrub_paths(held, private_paths))
    return _hide_identifiers(_scrub_paths(text, private_paths), identifiers)


def _hide_identifiers(text: str, identifiers: set[str]) -> str:
    """Replace every known identifier, longest first."""
    for identifier in sorted(identifiers, key=len, reverse=True):
        text = _identifier_pattern(identifier).sub(REDACTED_IDENTIFIER, text)
    return text


def _hold_identifiers(text: str, identifiers: set[str]) -> tuple[str, list[str]]:
    """Swap each identifier occurrence for a private-use placeholder that no path pattern treats as a word."""
    kept: list[str] = []

    def hold(match: re.Match[str]) -> str:
        kept.append(match.group(0))
        return f"{_HELD_OPEN}{chr(_HELD_BASE + len(kept) - 1)}{_HELD_CLOSE}"

    for identifier in sorted(identifiers, key=len, reverse=True):
        text = _identifier_pattern(identifier).sub(hold, text)
    return text, kept


def _measured_line(result: Measurement) -> str:
    """Describe a scored result; the metric is named only when the scorer defines it."""
    observed = result.observed_value
    if result.metric in SCORER_METRICS:
        value = f"{result.metric} {observed:g}" if observed is not None else result.metric
    else:
        value = f"a metric {PLAIN_WORDS}" + (f", value {observed:g}" if observed is not None else "")
    counts = f", {result.numerator} of {result.denominator}" if result.denominator is not None else ""
    interval = ""
    if result.interval_lower is not None and result.interval_upper is not None:
        interval = f", 95% interval {result.interval_lower:.3g} to {result.interval_upper:.3g}"
    rung = f", rung {result.rung}" if result.rung is not None else ""
    return f"Last measured result: {value}{counts}{interval}: {result.verdict.label}{rung}"


def _result_evidence(status: ProjectStatus) -> list[str]:
    """Describe the target and last result without any identifier or free-text metric name."""
    lines: list[str] = []
    if status.target is None:
        lines.append("Locked target: none")
    else:
        rule = status.target.rule() if status.target.metric in SCORER_METRICS else ""
        lines.append(f"Locked target: {rule or PLAIN_WORDS}")
    result = status.measurement
    if result is None:
        lines.append("Last measured result: none")
    elif result.verdict == Verdict.UNKNOWN:
        lines.append("Last measured result: recorded in the ledger without a scorer verdict")
    else:
        lines.append(_measured_line(result))
    return lines


def evidence_lines(status: ProjectStatus) -> list[str]:
    """Return the identifier-free evidence summary: step, target rule, last result, brief counts.

    Examples:
        >>> evidence_lines(project_status(Path("no-such-dir") / "ledger.jsonl"))[0]
        'Delivery step now: 1 of 7, lock the success target'
    """
    lines = [f"Delivery step now: {status.step.number} of {len(DeliveryStep)}, {STEP_TITLES[status.step]}"]
    lines.extend(_result_evidence(status))
    states: dict[str, int] = {}
    for brief in status.briefs:
        states[brief.state.value] = states.get(brief.state.value, 0) + 1
    summary = ", ".join(f"{count} {state}" for state, count in sorted(states.items())) or "none"
    lines.append(f"Action briefs recorded: {summary}")
    lines.append(f"Ledger rows: {status.ledger_rows}")
    return lines


def _opt_in_lines(
    records: list[dict[str, Any]], status: ProjectStatus, inputs: DraftInputs, clean: Callable[[str], str]
) -> tuple[list[str], list[str]]:
    """Return the evidence lines the user opted into, and the list of what stays withheld."""
    shown: list[str] = []
    withheld: list[str] = []
    redaction = inputs.redaction
    if redaction.identifiers:
        sessions = sorted({str(r["session"]) for r in records if r.get("source") == "skill" and r.get("session")})
        entities = sorted({str(r["entity_id"]) for r in records if r.get("entity_id")})
        # Every shown line goes through clean(): included identifiers or paths still lose credentials.
        shown.append(clean(f"Sessions: {', '.join(sessions) or 'none'}; entities: {', '.join(entities) or 'none'}"))
    else:
        withheld.append("Workspace and project identifiers, session names, and acceptance IDs (--include-identifiers).")
    if redaction.paths:
        sources = [status.ledger] + [item.source for item in (status.target, status.measurement) if item is not None]
        shown.append(clean(f"Files: {', '.join(sources)}"))
    else:
        withheld.append("File paths and eval file names (--include-paths).")
    if redaction.notes:
        notes = [str(r["notes"]) for r in records if r.get("source") == "skill" and r.get("notes")][-MAX_NOTES:]
        shown.extend(f"Ledger note: {clean(note)}" for note in notes)
    else:
        withheld.append("Free-text ledger notes (--include-notes).")
    return shown, withheld


def draft_outcome(
    ledger: Path, inputs: DraftInputs, now: datetime | None = None, roster: Roster | None = None
) -> OutcomeDraft:
    """Fill the outcome report from the ledger, the eval files, and the user's own answers.

    Args:
        ledger: The project's ``.vision-delivery/ledger.jsonl``.
        inputs: Answers only the user can give, and which withheld groups to include.
        now: The moment to judge action-brief freshness at.
        roster: The skill roster; defaults to the one shipped with this plugin.

    Returns:
        The draft.

    Examples:
        >>> draft = draft_outcome(Path("no-such-dir") / "ledger.jsonl", DraftInputs(host=Host.CODEX))
        >>> (draft.answers["host"], draft.answers["furthest"])
        ('Codex', '')
    """
    options = route_options(roster or load_roster())
    status = project_status(ledger, now=now)
    records = [record for record in load_records(ledger) if isinstance(record, dict)]
    safe = {*options, *(item.label for item in FORM_FIELDS)}
    identifiers = known_identifiers(records, status, safe)
    private_paths = (str(ledger.parent.parent), str(Path.home()))

    def clean(text: str) -> str:
        return scrub(text, identifiers, inputs.redaction, private_paths)

    route = inputs.route or derived_route(records, options)
    answers = {
        "host": HOST_LABELS[inputs.host] if inputs.host else "",
        "route": route,
        "experience": inputs.experience.value if inputs.experience else "",
        "furthest": furthest_step(status.milestones),
        "outcome": DECISION_LABELS[inputs.decision] if inputs.decision else "",
        "time": time_to_first_number(ledger, records),
        "friction": clean(inputs.friction.strip()),
    }
    filled_by = {
        "host": "your host" if inputs.host else "left for you",
        "route": "your answer" if inputs.route else ("the latest skill row in the ledger" if route else "left for you"),
        "experience": "your answer" if inputs.experience else "left for you",
        "furthest": "the ledger and eval files (check it)" if answers["furthest"] else "left for you",
        "outcome": "your answer" if inputs.decision else "left for you",
        "time": "ledger and eval-file timestamps (rough)" if answers["time"] else "left for you",
        "friction": "your words, scrubbed" if answers["friction"] else "left for you",
    }
    shown, withheld = _opt_in_lines(records, status, inputs, clean)
    title_route = route if route else "route not chosen"
    title = f"[Outcome] {title_route}: {answers['furthest'] or 'no step recorded'}"
    # The target rule and metric text come from eval files a person or an agent wrote, so they are scrubbed too.
    evidence = [clean(line) for line in evidence_lines(status)]
    return OutcomeDraft(title, answers, filled_by, (*evidence, *shown), tuple(withheld), options)


def _write_new(path: Path, text: str) -> None:
    """Write the draft to a new file; an existing file or link is never replaced."""
    descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_NOFOLLOW", 0), 0o600)
    with os.fdopen(descriptor, "w", encoding="utf-8", newline="\n") as stream:
        stream.write(text)


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    """Parse drafting options."""
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--ledger", type=Path, default=None, help="path to the project's ledger.jsonl")
    parser.add_argument("--host", choices=[host.value for host in Host], help="host the session ran on")
    parser.add_argument("--route", default="", help="route used: a route name, or not-sure (default: from the ledger)")
    parser.add_argument("--experience", choices=[item.value for item in Experience])
    parser.add_argument("--decision", choices=[item.value for item in Decision], help="did it help reach a decision")
    parser.add_argument("--friction", default="", help="your words for what got in the way or worked well")
    parser.add_argument("--include-identifiers", action="store_true", help="show sessions, entities, acceptance IDs")
    parser.add_argument("--include-paths", action="store_true", help="show file paths and eval file names")
    parser.add_argument("--include-notes", action="store_true", help="show free-text ledger notes")
    parser.add_argument("--out", type=Path, default=None, help="also write the draft to this new file")
    parser.add_argument("--json", action="store_true", help="print JSON instead of Markdown")
    return parser.parse_args(argv)


class LedgerInputError(ValueError):
    """Report a ledger the draft cannot be built from."""


@dataclass(frozen=True)
class LedgerCheck:
    """What a first read of the ledger found, before any draft is built."""

    rows: int
    unreadable: tuple[int, ...]


def inspect_ledger(ledger: Path) -> LedgerCheck:
    """Count the ledger rows that are JSON objects, and number the non-blank lines that are not.

    Raises:
        LedgerInputError: When the ledger is missing or cannot be read as UTF-8 text.

    Examples:
        >>> try:
        ...     inspect_ledger(Path("no-such-dir") / "ledger.jsonl")
        ... except LedgerInputError as exc:
        ...     str(exc).startswith("no ledger at")
        True
    """
    try:
        text = ledger.read_text(encoding="utf-8")
    except FileNotFoundError:
        raise LedgerInputError(
            f"no ledger at {ledger}; pass --ledger <project>/.vision-delivery/ledger.jsonl"
        ) from None
    except (OSError, UnicodeDecodeError) as exc:
        raise LedgerInputError(f"cannot read the ledger {ledger}: {exc}") from exc
    rows, unreadable = 0, []
    for number, raw in enumerate(text.splitlines(), 1):
        if not raw.strip():
            continue
        try:
            record = json.loads(raw)
        except json.JSONDecodeError:
            record = None
        if isinstance(record, dict):
            rows += 1
        else:
            unreadable.append(number)
    return LedgerCheck(rows, tuple(unreadable))


def ledger_warnings(check: LedgerCheck) -> list[str]:
    """Return the warnings for a ledger the draft can still be built from.

    Examples:
        >>> ledger_warnings(LedgerCheck(rows=0, unreadable=(3,)))[1]
        'skipped 1 unreadable ledger line (3); fix or remove it for a complete draft'
    """
    warnings = []
    if check.rows == 0:
        warnings.append("the ledger has no rows; the draft holds only your own answers")
    if check.unreadable:
        count = len(check.unreadable)
        noun, pronoun = ("line", "it") if count == 1 else ("lines", "them")
        numbers = ", ".join(str(number) for number in check.unreadable)
        warnings.append(
            f"skipped {count} unreadable ledger {noun} ({numbers}); fix or remove {pronoun} for a complete draft"
        )
    return warnings


def _draft_inputs(args: argparse.Namespace, route: str) -> DraftInputs:
    """Turn the parsed options into the user's answers and redaction choice."""
    return DraftInputs(
        host=Host(args.host) if args.host else None,
        route=route,
        experience=Experience(args.experience) if args.experience else None,
        decision=Decision(args.decision) if args.decision else None,
        friction=args.friction,
        redaction=Redaction(args.include_identifiers, args.include_paths, args.include_notes),
    )


def main(argv: list[str] | None = None) -> int:
    """Print the draft; exit 2 when the ledger, an answer, the roster, or the output path is unusable."""
    args = parse_args(argv)
    ledger = args.ledger or _default_ledger()
    try:
        roster = load_roster()
        check = inspect_ledger(ledger)
    except (RosterError, LedgerInputError) as exc:
        print(f"outcome-report-error: {exc}", file=sys.stderr)
        return 2
    route = NOT_SURE if args.route == "not-sure" else args.route
    if route and route not in route_options(roster):
        print(f"outcome-report-error: --route must be one of {', '.join(route_options(roster))}", file=sys.stderr)
        return 2
    for warning in ledger_warnings(check):
        print(f"outcome-report-warning: {warning}", file=sys.stderr)
    draft = draft_outcome(ledger, _draft_inputs(args, route), roster=roster)
    text = json.dumps(draft.to_json(), indent=2) + "\n" if args.json else draft.to_markdown()
    if args.out is not None:
        try:
            _write_new(args.out, text)
        except OSError as exc:
            print(f"outcome-report-error: draft not written: {exc}", file=sys.stderr)
            return 2
    sys.stdout.write(text)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
