#!/usr/bin/env python3
"""Check the outcome-report draft: form agreement, redaction, and that the helper only reads.

Every case is offline. Fixture ledgers live in temporary folders, and credential-shaped strings
are assembled from parts at run time so repository secret scanners never see one.
"""

from __future__ import annotations

import ast
import hashlib
import itertools
import json
import re
import subprocess
import sys
import tempfile
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
SCRIPTS = ROOT / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

from outcome_report import (  # noqa: E402
    FORM_FIELDS,
    NOT_SURE,
    REDACTED_SECRET,
    SCORER_METRICS,
    UNDETECTABLE_NOTICE,
    route_options,
)
from skill_roster import load_roster  # noqa: E402

SCRIPT = SCRIPTS / "outcome_report.py"
SCORER = ROOT / "resources" / "scripts" / "score_baseline.py"
FORM_PATH = ROOT / ".github" / "ISSUE_TEMPLATE" / "outcome-report.yml"
SUBPROCESS_TIMEOUT = 60
FLAGS = ("--include-identifiers", "--include-paths", "--include-notes")
#: Top-level modules that open connections or start processes; the helper and its local imports use none.
NETWORK_OR_PROCESS = frozenset(
    {
        "aiohttp",
        "asyncio",
        "ftplib",
        "http",
        "httpx",
        "importlib",
        "multiprocessing",
        "requests",
        "smtplib",
        "socket",
        "ssl",
        "subprocess",
        "urllib",
        "urllib3",
        "webbrowser",
        "xmlrpc",
    }
)
SESSION = "harbor-crates-0917"
WORKSPACE = "northwind-docks"
ENTITY = f"{WORKSPACE}/pallet-counter/3"
ACCEPTANCE = "pallet-acceptance-v2"
NOTE_PHRASE = "glare on the east loading bay"
HOME = str(Path.home())


def require(condition: bool, message: str) -> None:
    """Raise an assertion carrying the outcome-report condition that failed."""
    if not condition:
        raise AssertionError(message)


@dataclass
class IssueField:
    """One body field of a GitHub issue form."""

    kind: str
    field_id: str = ""
    label: str = ""
    options: list[str] = field(default_factory=list)
    required: bool = False


def _scalar(value: str) -> str:
    """Return a plain YAML scalar without its quotes."""
    return value.strip().strip('"').strip("'")


def parse_issue_form(text: str) -> list[IssueField]:
    """Read the body fields of a GitHub issue form: the subset of YAML the outcome form uses."""
    fields: list[IssueField] = []
    in_options = False
    for raw in text.splitlines():
        line = raw.strip()
        if line.startswith("- type: "):
            fields.append(IssueField(kind=_scalar(line.removeprefix("- type: "))))
            in_options = False
        elif not fields:
            continue
        elif in_options and line.startswith("- "):
            fields[-1].options.append(_scalar(line[2:]))
        else:
            in_options = line == "options:"
            key, _, value = line.partition(": ")
            if key == "id":
                fields[-1].field_id = _scalar(value)
            elif key == "label":
                fields[-1].label = _scalar(value)
            elif key == "required":
                fields[-1].required = _scalar(value) == "true"
    return [item for item in fields if item.field_id]


def check_draft_fields_match_issue_form() -> None:
    """Field ids, labels, dropdown options, and required flags agree with the issue form."""
    form = parse_issue_form(FORM_PATH.read_text(encoding="utf-8"))
    require([item.field_id for item in form] == [item.field_id for item in FORM_FIELDS], "field ids differ")
    routes = route_options(load_roster())
    for spec, ours in zip(form, FORM_FIELDS, strict=True):
        require(spec.label == ours.label, f"{ours.field_id}: label {ours.label!r} differs from {spec.label!r}")
        require(spec.required == ours.required, f"{ours.field_id}: required flag differs")
        expected = routes if ours.field_id == "route" else ours.options
        require((spec.kind == "dropdown") == bool(expected), f"{ours.field_id}: dropdown or free text differs")
        if ours.field_id == "route":
            require(
                set(spec.options) == set(routes), f"route options differ: {sorted(set(spec.options) ^ set(routes))}"
            )
            require(spec.options[-1] == routes[-1] == NOT_SURE, "'not sure' is not the last route option")
        else:
            require(tuple(spec.options) == ours.options, f"{ours.field_id}: options {ours.options} differ")


@dataclass(frozen=True)
class Fixture:
    """A project folder with a ledger, plus the private strings placed in it."""

    project: Path
    ledger: Path
    session: str
    entity: str


def make_fixture(base: Path, *, folder: str = "project", secret: str = "", note_extra: str = "") -> Fixture:
    """Write a two-row ledger holding a session, entity ids, an acceptance ID, paths, and notes."""
    session = f"{SESSION}-{secret}" if secret else SESSION
    entity = f"{WORKSPACE}/{secret}/3" if secret else ENTITY
    note = f"{NOTE_PHRASE}; frames at {HOME}/clients/{WORKSPACE}/frames; acceptance_id={ACCEPTANCE}{note_extra}"
    rows = [
        {
            "ts": "2026-11-10T10:00:00Z",
            "source": "skill",
            "skill": "detect-and-analyze",
            "session": session,
            "action": "dataset_inspected",
            "status": "success",
            "entity_id": entity,
            "acceptance_id": ACCEPTANCE,
            "notes": note,
        },
        {
            "ts": "2026-11-10T10:20:00Z",
            "source": "skill",
            "skill": "detect-and-analyze",
            "session": session,
            "action": "target_proposed",
            "status": "success",
            "entity_id": entity,
            "notes": f"second note for {WORKSPACE}",
        },
    ]
    project = base / folder
    ledger = project / ".vision-delivery" / "ledger.jsonl"
    ledger.parent.mkdir(parents=True)
    ledger.write_text("".join(json.dumps(row) + "\n" for row in rows), encoding="utf-8")
    return Fixture(project, ledger, session, entity)


def run_report(ledger: Path, *args: str) -> subprocess.CompletedProcess[str]:
    """Run the helper on one ledger and return the finished process."""
    command = [sys.executable, str(SCRIPT), "--ledger", str(ledger), *args]
    return subprocess.run(command, capture_output=True, text=True, timeout=SUBPROCESS_TIMEOUT, check=False)


def _strings(value: Any) -> list[str]:
    """Return every string inside parsed JSON, so containment ignores JSON escaping."""
    if isinstance(value, dict):
        return [text for item in value.values() for text in _strings(item)]
    if isinstance(value, list):
        return [text for item in value for text in _strings(item)]
    return [value] if isinstance(value, str) else []


def _draft(ledger: Path, flags: tuple[str, ...], as_json: bool, friction: str) -> str:
    """Return the visible draft text for one flag set, failing when the helper fails."""
    done = run_report(ledger, *flags, *(("--json",) if as_json else ()), "--friction", friction)
    require(done.returncode == 0, f"helper failed with {flags}: {done.stderr}")
    return "\n".join(_strings(json.loads(done.stdout))) if as_json else done.stdout


def _flag_sets() -> list[tuple[str, ...]]:
    """Return every combination of the three opt-in flags, the empty set included."""
    return [combo for size in range(len(FLAGS) + 1) for combo in itertools.combinations(FLAGS, size)]


def check_each_flag_reveals_only_its_class() -> None:
    """The default draft hides every private class; each flag brings back its own class only."""
    friction = f"uploads to {WORKSPACE} were slow from {HOME}/clients/frames during {SESSION}"
    with tempfile.TemporaryDirectory() as tmp:
        fixture = make_fixture(Path(tmp))
        classes = {
            "--include-identifiers": (SESSION, ENTITY, WORKSPACE),
            "--include-paths": (str(fixture.ledger), HOME),
            "--include-notes": (NOTE_PHRASE,),
        }
        wrong: list[str] = []
        for flags, as_json in itertools.product(_flag_sets(), (False, True)):
            text = _draft(fixture.ledger, flags, as_json, friction)
            for flag, values in classes.items():
                shown = [value for value in values if value in text]
                expected = list(values) if flag in flags else []
                if shown != expected:
                    wrong.append(f"{flags or 'default'} json={as_json} {flag}: shows {shown}, expected {expected}")
            if ACCEPTANCE in text and "--include-identifiers" not in flags:
                wrong.append(f"{flags or 'default'} json={as_json}: acceptance ID shown")
        require(not wrong, "redaction classes leak or stay hidden:\n  " + "\n  ".join(wrong))


def _credentials() -> dict[str, str]:
    """Assemble credential-shaped strings at run time."""
    header = "-----BEGIN " + "RSA PRIVATE" + " KEY-----"
    footer = "-----END " + "RSA PRIVATE" + " KEY-----"
    return {
        "github": "ghp" + "_" + "Zq8" * 12,
        "aws": "AK" + "IA" + "R7" * 8,
        "pem header": header,
        "pem body": "MIIB" + "kq9Z" * 10,
        "pem footer": footer,
    }


def check_credentials_removed_in_every_mode() -> None:
    """A credential in a note, an entity id, a session, and a path is removed with any flags."""
    secrets = _credentials()
    github = secrets["github"]
    pem = f"{secrets['pem header']}\n{secrets['pem body']}\n{secrets['pem footer']}"
    extra = f"; retry with {secrets['aws']}; key {pem}; copy at {HOME}/keys/{github}/a.json"
    with tempfile.TemporaryDirectory() as tmp:
        fixture = make_fixture(Path(tmp), folder=f"proj-{github}", secret=github, note_extra=extra)
        wrong: list[str] = []
        for flags, as_json in itertools.product(_flag_sets(), (False, True)):
            text = _draft(fixture.ledger, flags, as_json, f"pasted {github} by mistake")
            leaked = [label for label, value in secrets.items() if value in text]
            if leaked or REDACTED_SECRET not in text:
                wrong.append(f"{flags or 'default'} json={as_json}: leaked {leaked}")
        require(not wrong, "credential-shaped text survived:\n  " + "\n  ".join(wrong))


def _more_credentials() -> dict[str, tuple[str, str]]:
    """Return label -> (text to plant, the part that must not survive), assembled at run time."""
    anthropic = "sk-" + "ant-" + "Qz7" * 8
    bearer = "eyJ" + "x9" * 12
    assigned = "rf" * 4 + "0123456789ab"
    signature = "ab12" * 6
    slack = "xox" + "b-" + "1234567890-abcdef"
    github_pat = "github" + "_pat_" + "A1" * 12
    return {
        "anthropic key": (anthropic, anthropic),
        "bearer header": ("Authorization: Bear" + "er " + bearer, bearer),
        "key assignment": ("api" + "_key=" + assigned, assigned),
        "signed URL": ("https://bucket.example/o?X-Amz-" + "Signature=" + signature, signature),
        "slack token": (slack, slack),
        "github fine-grained token": (github_pat, github_pat),
    }


def check_more_credential_shapes_removed_in_every_mode() -> None:
    """Run-transcript credential shapes are removed from friction and notes with any flags."""
    shapes = _more_credentials()
    planted = "; ".join(text for text, _ in shapes.values())
    with tempfile.TemporaryDirectory() as tmp:
        fixture = make_fixture(Path(tmp), note_extra=f"; {planted}")
        wrong: list[str] = []
        for flags, as_json in itertools.product(_flag_sets(), (False, True)):
            text = _draft(fixture.ledger, flags, as_json, f"pasted {planted}")
            leaked = [label for label, (_, secret) in shapes.items() if secret in text]
            if leaked or REDACTED_SECRET not in text:
                wrong.append(f"{flags or 'default'} json={as_json}: leaked {leaked}")
        require(not wrong, "credential-shaped text survived:\n  " + "\n  ".join(wrong))


#: Free-text private classes the scrub must catch, one per line: paths, addresses, and identifier variants.
FRICTION_LINES = (
    "frames under /Users/Dana Quill/rivet photos/cam1 were blurry",
    "copied from C:\\Users\\Dana Quill\\scans",
    "mirror at D:\\shared\\rivetco\\v3",
    "images in datasets/rivetco-parts/v3 were dark",
    "server gpu07.rivetco.internal timed out",
    "mail dana.quill@rivetco.example",
    "reached 10.20.30.40:8080",
    "Northwind_Docks line, camera BAY drifted",
)
INDEPENDENT_ENTITY = "northwind-docks/bay/3"


def _write_ledger(project: Path, entity: str = INDEPENDENT_ENTITY) -> Path:
    """Write a one-row ledger whose entity id holds a three-character part."""
    ledger = project / ".vision-delivery" / "ledger.jsonl"
    ledger.parent.mkdir(parents=True)
    row = {"ts": "2026-11-10T10:00:00Z", "source": "skill", "skill": "detect-and-analyze", "session": "rivet-0917"}
    row.update({"action": "dataset_inspected", "status": "success", "entity_id": entity})
    ledger.write_text(json.dumps(row) + "\n", encoding="utf-8")
    return ledger


def check_free_text_private_classes() -> None:
    """Spaced and Windows homes, other paths, hosts, emails, IPs, and identifier variants leave the default draft."""
    hidden = ("Dana", "Quill", "rivet photos", "rivetco", "gpu07", "10.20.30.40", "northwind")
    short_token = re.compile(r"(?i)(?<![\w-])bay(?![\w-])")
    friction = "\n".join(FRICTION_LINES)
    with tempfile.TemporaryDirectory() as tmp:
        ledger = _write_ledger(Path(tmp) / "project")
        wrong: list[str] = []
        for as_json in (False, True):
            text = _draft(ledger, (), as_json, friction)
            leaked = [value for value in hidden if value.casefold() in text.casefold()]
            leaked += ["bay"] if short_token.search(text) else []
            wrong += [f"default json={as_json}: shows {leaked}"] if leaked else []
            text = _draft(ledger, FLAGS, as_json, friction)
            leaked = [value for value in ("gpu07", "10.20.30.40", "@rivetco") if value in text]
            wrong += [f"all flags json={as_json}: shows {leaked}"] if leaked else []
        require(not wrong, "free-text private data survived:\n  " + "\n  ".join(wrong))


def _write_eval_files(vision: Path, metric: str) -> None:
    """Write a frozen acceptance and a scorer result that both name ``metric``."""
    target = {"metric": metric, "comparator": "gte", "threshold": 0.8, "unit": "rivetco seams"}
    acceptance = {"schema_version": "1", "acceptance_id": "rivet-acceptance-1", "frozen_at": "2026-11-10T10:05:00Z"}
    (vision / "acceptance-rivet.json").write_text(json.dumps({**acceptance, **target}), encoding="utf-8")
    result: dict[str, object] = {"schema_version": "1", "verdict": "pass", "measured_at": "2026-11-10T10:30:00Z"}
    result["target"] = target
    result.update({"observed_value": 0.9, "numerator": 9, "denominator": 10})
    (vision / "evidence-rivet-rung0.json").write_text(json.dumps(result), encoding="utf-8")


def _scorer_metric_names() -> set[str]:
    """Read the scorer's count and flag metric tuples from its source, without importing it."""
    names: set[str] = set()
    for node in ast.parse(SCORER.read_text(encoding="utf-8")).body:
        targets = [item.id for item in getattr(node, "targets", []) if isinstance(item, ast.Name)]
        if isinstance(node, ast.Assign) and {"COUNT_METRICS", "FLAG_METRICS"} & set(targets):
            names.update(ast.literal_eval(node.value))
    return names


def check_metric_text_is_a_closed_set() -> None:
    """Only a metric name the scorer defines reaches the draft; eval file names still show with --include-paths."""
    scorer = _scorer_metric_names()
    require(bool(scorer) and set(SCORER_METRICS) == scorer, f"metric set differs from the scorer: {sorted(scorer)}")
    expected = {
        "rivetco_seam_recall": (
            "Locked target: recorded in plain words",
            "a metric recorded in plain words, value 0.9",
        ),
        "catch_rate": ("Locked target: catch_rate >= 0.8", "Last measured result: catch_rate 0.9"),
    }
    with tempfile.TemporaryDirectory() as tmp:
        for metric, lines in expected.items():
            ledger = _write_ledger(Path(tmp) / metric)
            _write_eval_files(ledger.parent, metric)
            text = _draft(ledger, (), False, "")
            require(all(line in text for line in lines), f"{metric}: evidence lacks {lines}")
            require("rivetco" not in text and "seam" not in text, f"{metric}: free-text metric or unit leaked")
            shown = _draft(ledger, ("--include-paths",), False, "")
            require("acceptance-rivet.json" in shown, f"{metric}: --include-paths hides an eval file name")


def check_draft_states_what_it_cannot_detect() -> None:
    """Markdown and JSON drafts both tell the user that unrecorded customer names are not detected."""
    with tempfile.TemporaryDirectory() as tmp:
        fixture = make_fixture(Path(tmp))
        markdown = run_report(fixture.ledger)
        require(UNDETECTABLE_NOTICE in markdown.stdout, "the Markdown draft does not state what it cannot detect")
        data = json.loads(run_report(fixture.ledger, "--json").stdout)
        require(data.get("notice") == UNDETECTABLE_NOTICE, "the JSON draft does not state what it cannot detect")


def _imported_roots(path: Path) -> set[str]:
    """Return the top-level module names one Python file imports."""
    roots: set[str] = set()
    for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
        if isinstance(node, ast.Import):
            roots.update(alias.name.split(".")[0] for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module and node.level == 0:
            roots.add(node.module.split(".")[0])
    return roots


def check_no_network_or_process_imports() -> None:
    """Neither the helper nor the local modules it imports load a network or process module."""
    pending, seen, found = [SCRIPT], set(), []
    while pending:
        path = pending.pop()
        if path in seen:
            continue
        seen.add(path)
        roots = _imported_roots(path)
        found += [f"{path.name}: {name}" for name in sorted(roots & NETWORK_OR_PROCESS)]
        pending += [SCRIPTS / f"{name}.py" for name in roots if (SCRIPTS / f"{name}.py").is_file()]
    require(len(seen) > 1, "the import walk did not reach the local modules")
    require(not found, f"network or process imports: {found}")


def check_out_refuses_existing_file_and_links() -> None:
    """``--out`` writes a new file only; an existing file or a link is refused and nothing is written."""
    with tempfile.TemporaryDirectory() as tmp:
        base = Path(tmp)
        fixture = make_fixture(base)
        existing = base / "existing.md"
        existing.write_text("keep me\n", encoding="utf-8")
        target, dangling, linked = base / "target.md", base / "dangling.md", base / "linked.md"
        dangling.symlink_to(target)
        linked.symlink_to(existing)
        for out in (existing, dangling, linked):
            done = run_report(fixture.ledger, "--out", str(out))
            require(done.returncode == 2 and not done.stdout, f"--out {out.name} exited {done.returncode}")
            require("outcome-report-error" in done.stderr, f"--out {out.name} gave no clear message")
        require(existing.read_text(encoding="utf-8") == "keep me\n", "--out replaced an existing file")
        require(not target.exists() and dangling.is_symlink(), "--out followed a dangling link")
        fresh = base / "fresh.md"
        done = run_report(fixture.ledger, "--out", str(fresh))
        require(done.returncode == 0 and fresh.read_text(encoding="utf-8") == done.stdout, "--out new file failed")


def _digest(path: Path) -> str:
    """Return the SHA-256 of one file."""
    return hashlib.sha256(path.read_bytes()).hexdigest()


def check_ledger_never_written() -> None:
    """The ledger bytes and the ledger folder are identical before and after every mode."""
    with tempfile.TemporaryDirectory() as tmp:
        fixture = make_fixture(Path(tmp))
        digest, listing = _digest(fixture.ledger), sorted(fixture.ledger.parent.iterdir())
        for flags in _flag_sets():
            run_report(fixture.ledger, *flags, "--json")
            run_report(fixture.ledger, *flags, "--host", "codex", "--decision", "go")
        run_report(fixture.ledger, "--out", str(Path(tmp) / "draft.md"))
        require(_digest(fixture.ledger) == digest, "the ledger changed")
        require(sorted(fixture.ledger.parent.iterdir()) == listing, "the ledger folder changed")


def check_missing_empty_and_malformed_ledgers() -> None:
    """Missing ledger: exit 2. Empty ledger or bad lines: exit 0 with a warning naming the problem."""
    with tempfile.TemporaryDirectory() as tmp:
        base = Path(tmp)
        done = run_report(base / "nowhere" / "ledger.jsonl")
        require(done.returncode == 2 and not done.stdout, f"missing ledger exited {done.returncode}")
        require("outcome-report-error: no ledger at" in done.stderr, f"missing ledger message: {done.stderr!r}")
        empty = base / "empty.jsonl"
        empty.write_text("", encoding="utf-8")
        done = run_report(empty)
        require(done.returncode == 0 and done.stdout.startswith("# Draft outcome report"), "empty ledger: no draft")
        require("outcome-report-warning: the ledger has no rows" in done.stderr, f"empty ledger: {done.stderr!r}")
        fixture = make_fixture(base)
        good = fixture.ledger.read_text(encoding="utf-8").splitlines()
        fixture.ledger.write_text("\n".join([good[0], "{not json", "[1, 2]", good[1]]) + "\n", encoding="utf-8")
        done = run_report(fixture.ledger)
        require(done.returncode == 0 and "Ledger rows: 2" in done.stdout, f"malformed ledger exited {done.returncode}")
        warning = "outcome-report-warning: skipped 2 unreadable ledger lines (2, 3)"
        require(warning in done.stderr, f"malformed ledger message: {done.stderr!r}")


def check_end_to_end_markdown_and_json() -> None:
    """A Markdown run and a JSON run answer every form field in order; a bad route exits 2."""
    with tempfile.TemporaryDirectory() as tmp:
        fixture = make_fixture(Path(tmp))
        answers = ("--host", "claude-code", "--experience", "some", "--decision", "revise-or-stop")
        done = run_report(fixture.ledger, *answers, "--friction", "labels took a while")
        require(done.returncode == 0, f"markdown run failed: {done.stderr}")
        text = done.stdout
        require(text.startswith("# Draft outcome report: [Outcome] detect-and-analyze: "), "markdown title")
        positions = [text.find(f"### {item.label}\n") for item in FORM_FIELDS]
        require(-1 not in positions and positions == sorted(positions), "markdown headings miss or reorder fields")
        for answer in ("Claude Code", "detect-and-analyze", "some", "yes, revise or stop", "labels took a while"):
            require(f"\n\n{answer}\n" in text, f"markdown lacks the answer {answer!r}")
        done = run_report(fixture.ledger, "--json", "--host", "codex", "--route", "not-sure")
        require(done.returncode == 0, f"json run failed: {done.stderr}")
        data = json.loads(done.stdout)
        require(list(data["answers"]) == [item.field_id for item in FORM_FIELDS], "json answer keys differ")
        require((data["answers"]["host"], data["answers"]["route"]) == ("Codex", NOT_SURE), f"{data['answers']}")
        require(data["route_options"] == list(route_options(load_roster())), "json route options differ")
        bad = run_report(fixture.ledger, "--route", "made-up-route")
        require(bad.returncode == 2 and not bad.stdout, f"unknown route exited {bad.returncode}")


CHECKS: tuple[Callable[[], None], ...] = (
    check_draft_fields_match_issue_form,
    check_each_flag_reveals_only_its_class,
    check_credentials_removed_in_every_mode,
    check_more_credential_shapes_removed_in_every_mode,
    check_free_text_private_classes,
    check_metric_text_is_a_closed_set,
    check_draft_states_what_it_cannot_detect,
    check_no_network_or_process_imports,
    check_out_refuses_existing_file_and_links,
    check_ledger_never_written,
    check_missing_empty_and_malformed_ledgers,
    check_end_to_end_markdown_and_json,
)


def main() -> int:
    """Run every outcome-report check and return 1 when any fails."""
    failed = 0
    for check in CHECKS:
        try:
            check()
        except AssertionError as exc:
            failed += 1
            print(f"FAIL {check.__name__}: {exc}")
        else:
            print(f"ok   {check.__name__}")
    print(f"outcome-report checks: {len(CHECKS) - failed} passed, {failed} failed")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
