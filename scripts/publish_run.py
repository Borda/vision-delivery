#!/usr/bin/env python3
"""Package one finished behaviour-eval run into a committed, redacted artifact folder.

The plugin-vs-plain A/B (``evals/ab/``) and live routing (``evals/trigger-live/``) are paid, on-demand runs whose
scratch output is gitignored. A published number must point to a folder this helper wrote, so anyone can re-score
it from the repository alone.

``pack`` copies only the files the suite lists as publishable. It decodes every JSON value, masks local paths, home
folder owners, temporary roots, the login name, and the host name inside every string, re-serializes the result,
and writes ``publish-manifest.json`` with a SHA-256 digest per file. It refuses, writing nothing, when a file, the
set or run name, or the manifest would carry secret-like material, when an email or IPv4 address remains after
masking, or when a file is too large to commit or malformed. ``verify`` re-checks a published folder against its
manifest and its folder names. Both are denylists: they cannot judge whether agent text names something private.

Usage:
    python3 scripts/publish_run.py pack --suite ab --run evals/ab/runs/<run-id> --set <set-id>
    python3 scripts/publish_run.py pack --suite trigger-live --run evals/trigger-live/runs/<file>.jsonl --set <set-id>
    python3 scripts/publish_run.py verify evals/ab/published/<set-id>/<run-id>
"""

from __future__ import annotations

import argparse
import fnmatch
import getpass
import hashlib
import json
import os
import re
import shutil
import socket
import sys
from collections.abc import Callable, Iterator, Mapping
from dataclasses import dataclass
from enum import Enum
from pathlib import Path, PurePosixPath

from redaction import EMAIL, credential_index, has_ipv4, has_unmasked_folder, mask_folders

ROOT = Path(__file__).resolve().parents[1]
MANIFEST_NAME = "publish-manifest.json"
SCHEMA_VERSION = 1
#: Same limit as the repository's ``check-added-large-files --maxkb=250`` pre-commit hook.
MAX_FILE_BYTES = 250 * 1024
#: Set and run folder names: letters, digits, dot, dash, and underscore; never a path separator.
SAFE_NAME = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,119}$")
#: Shortest login name masked as a path segment, and shortest host name masked as a word.
MIN_LOGIN_LENGTH = 2
MIN_HOST_LENGTH = 3
#: Private-data shapes that must not remain in decoded content after masking; each finding names the shape only.
RESIDUE_CHECKS: tuple[tuple[str, Callable[[str], object]], ...] = (
    ("an email address", EMAIL.search),
    ("an IPv4 address", has_ipv4),
    ("a home folder owner or temporary root that is not masked", has_unmasked_folder),
)


def _current_login() -> str:
    """Return this machine's login name, or an empty string when it cannot be read."""
    try:
        return getpass.getuser()
    except (OSError, KeyError, ImportError):
        return ""


def _current_host() -> str:
    """Return this machine's host name, or an empty string when it cannot be read."""
    try:
        return socket.gethostname()
    except OSError:
        return ""


@dataclass(frozen=True)
class Masker:
    """Machine-specific text replaced before a run is committed.

    Attributes:
        literals: ``(text, placeholder)`` pairs replaced verbatim, longest text first.
        login: The current login name, masked where it is a whole path segment; empty to skip.
        hosts: The current host names, full and short, masked as whole words in any letter case.
    """

    literals: tuple[tuple[str, str], ...]
    login: str = ""
    hosts: tuple[str, ...] = ()

    @classmethod
    def for_run(cls, run_path: Path, login: str | None = None, host: str | None = None) -> Masker:
        """Build the masker for one run on this machine; ``login`` and ``host`` replace the detected names.

        Examples:
            >>> Masker.for_run(Path("/nowhere/run"), login="dq", host="rig-7.corp.internal").hosts
            ('rig-7.corp.internal', 'rig-7')
        """
        pairs = {(str(run_path), "<run>"), (str(run_path.resolve()), "<run>"), (str(ROOT), "<repo>")}
        pairs.add((str(Path.home()), "~"))
        literals = tuple(sorted((pair for pair in pairs if len(pair[0]) > 1), key=lambda pair: (-len(pair[0]), pair)))
        login = _current_login() if login is None else login
        host = _current_host() if host is None else host
        names = (host, host.split(".")[0])
        hosts = tuple(dict.fromkeys(name for name in names if len(name) >= MIN_HOST_LENGTH))
        return cls(literals, login if len(login) >= MIN_LOGIN_LENGTH else "", hosts)

    def mask(self, text: str) -> str:
        """Replace this machine's paths, login, and host name, then any home folder owner and temporary root.

        Examples:
            >>> masker = Masker.for_run(Path("/nowhere/run"), login="dq", host="rig-7.corp.internal")
            >>> masker.mask("rig-7 saved /nowhere/run/x, /opt/DQ/y, and /Users/Ana Lima/z")
            '<host> saved <run>/x, /opt/<user>/y, and /Users/<user>/z'
        """
        for needle, placeholder in self.literals:
            text = text.replace(needle, placeholder)
        text = mask_folders(text)
        if self.login:
            text = re.sub(rf"(?i)(?<=[/\\]){re.escape(self.login)}(?![^/\\\s\"'`<>])", "<user>", text)
        for host in self.hosts:
            text = re.sub(rf"(?i)(?<![\w.-]){re.escape(host)}(?![\w-]|\.[\w-])", "<host>", text)
        return text


def credential_findings(labelled: tuple[tuple[str, str], ...]) -> list[str]:
    """Return one finding per ``(label, text)`` pair whose text looks like it holds a credential.

    Examples:
        >>> credential_findings((("run name", "r-" + "gh" + "p_" + "Z9" * 18), ("set name", "s1")))
        ['run name: secret-like material (pattern 3)']
    """
    numbers = ((label, credential_index(text)) for label, text in labelled)
    return [f"{label}: secret-like material (pattern {number})" for label, number in numbers if number is not None]


class Suite(str, Enum):
    """Behaviour-eval suites whose runs can be published."""

    AB = "ab"
    TRIGGER_LIVE = "trigger-live"


class RunShape(str, Enum):
    """What one run of a suite is on disk."""

    FOLDER = "folder"
    FILE = "file"


class Command(str, Enum):
    """Helper subcommands."""

    PACK = "pack"
    VERIFY = "verify"


class DropReason(str, Enum):
    """Why a file of a run folder was not published; the manifest counts each reason."""

    NOT_LISTED = "not_listed"
    SYMLINK = "symlink"


class PublishRefusedError(Exception):
    """Raised when a run cannot be published; nothing is written.

    Attributes:
        findings: One line per problem, naming the file and the rule, never the matched text.
    """

    def __init__(self, findings: list[str]) -> None:
        super().__init__("; ".join(findings))
        self.findings = findings


@dataclass(frozen=True)
class SuiteProfile:
    """Which files of a suite's run are published, and where.

    Attributes:
        suite: The suite this profile describes.
        shape: Whether a run is a folder or a single results file.
        publish_root: Committed folder that holds ``<set>/<run>/``.
        required: Publishable files a run must have; for a file-shaped run, the one published name.
        optional: Publishable files a run may have.
        counted: ``(manifest key, pattern)`` pairs; files matching the ``fnmatch`` pattern (``*`` crosses folders)
            are counted in the manifest but never published.
    """

    suite: Suite
    shape: RunShape
    publish_root: Path
    required: tuple[str, ...]
    optional: tuple[str, ...] = ()
    counted: tuple[tuple[str, str], ...] = ()


PROFILES: Mapping[Suite, SuiteProfile] = {
    Suite.AB: SuiteProfile(
        suite=Suite.AB,
        shape=RunShape.FOLDER,
        publish_root=ROOT / "evals" / "ab" / "published",
        required=("meta.json", "tools.jsonl", "transcript.jsonl"),
        optional=("approvals.jsonl", "approver.json", "ground_truth.json", "state.json"),
        counted=(("workspace_python_files", "workspace/*.py"),),
    ),
    Suite.TRIGGER_LIVE: SuiteProfile(
        suite=Suite.TRIGGER_LIVE,
        shape=RunShape.FILE,
        publish_root=ROOT / "evals" / "trigger-live" / "published",
        required=("results.jsonl",),
    ),
}


@dataclass(frozen=True)
class PublishedFile:
    """One file as it will be committed.

    Attributes:
        path: Folder-relative POSIX path.
        data: Exact bytes written.
        masked: Whether path masking changed the content.
    """

    path: str
    data: bytes
    masked: bool

    def record(self) -> dict[str, object]:
        """Return the manifest entry for this file.

        Examples:
            >>> PublishedFile("a.json", b"{}\\n", False).record()["bytes"]
            3
        """
        return {"bytes": len(self.data), "masked": self.masked, "path": self.path, "sha256": sha256(self.data)}


@dataclass(frozen=True)
class Package:
    """A run ready to write: its published files plus what was left out.

    Attributes:
        profile: The suite profile used.
        set_id: Publication set the run belongs to.
        run_name: Folder name of the run inside the set.
        files: Published files, sorted by path.
        dropped: Count of unpublished files per drop reason.
        counts: Counts declared by the profile's ``counted`` patterns.
    """

    profile: SuiteProfile
    set_id: str
    run_name: str
    files: tuple[PublishedFile, ...]
    dropped: Mapping[str, int]
    counts: Mapping[str, int]

    def manifest(self) -> bytes:
        """Return the canonical manifest bytes; no clock value, so the same run always yields the same bytes.

        Examples:
            >>> profile = PROFILES[Suite.TRIGGER_LIVE]
            >>> package = Package(profile, "s", "r", (PublishedFile("results.jsonl", b"{}\\n", False),), {}, {})
            >>> json.loads(package.manifest())["files"][0]["path"]
            'results.jsonl'
        """
        payload = {
            "counts": dict(self.counts),
            "dropped": dict(self.dropped),
            "files": [item.record() for item in self.files],
            "run": self.run_name,
            "schema_version": SCHEMA_VERSION,
            "set": self.set_id,
            "suite": self.profile.suite.value,
        }
        return canonical_json(payload).encode("utf-8")


def sha256(data: bytes) -> str:
    """Return the hex SHA-256 digest of ``data``.

    Examples:
        >>> sha256(b"")[:12]
        'e3b0c44298fc'
    """
    return hashlib.sha256(data).hexdigest()


def canonical_json(value: object) -> str:
    """Serialize ``value`` the way the repository's JSON formatter leaves it: sorted keys, two-space indent.

    Examples:
        >>> canonical_json({"b": 1, "a": [1]})
        '{\\n  "a": [\\n    1\\n  ],\\n  "b": 1\\n}\\n'
    """
    return json.dumps(value, indent=2, sort_keys=True, ensure_ascii=True) + "\n"


def _decode(name: str, raw: bytes) -> str:
    try:
        text = raw.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise PublishRefusedError([f"{name}: not UTF-8 text ({exc.reason})"]) from exc
    return text.replace("\r\n", "\n")


def _parse(name: str, number: int, text: str) -> object:
    try:
        return json.loads(text)
    except json.JSONDecodeError as exc:
        raise PublishRefusedError([f"{name}:{number}: not valid JSON ({exc.msg})"]) from exc


def decode_values(name: str, raw: bytes) -> list[object]:
    """Decode a ``.jsonl`` file into one value per non-blank line, and any other file into one JSON value.

    Raises:
        PublishRefusedError: The bytes are not UTF-8, or a line or the file is not valid JSON.

    Examples:
        >>> decode_values("t.jsonl", b'{"a": "\\\\u002fx"}\\n\\n[1]\\n')
        [{'a': '/x'}, [1]]
    """
    text = _decode(name, raw)
    if not name.endswith(".jsonl"):
        return [_parse(name, 1, text)]
    return [_parse(name, number, line) for number, line in enumerate(text.splitlines(), 1) if line.strip()]


def render_values(name: str, values: list[object]) -> bytes:
    """Serialize decoded values deterministically: canonical JSON, or one compact-spaced line per value.

    Examples:
        >>> render_values("t.jsonl", [{"b": 1, "a": "é"}])
        b'{"b": 1, "a": "\\\\u00e9"}\\n'
    """
    if not name.endswith(".jsonl"):
        return canonical_json(values[0]).encode("utf-8")
    return "".join(json.dumps(value) + "\n" for value in values).encode("utf-8")


def _mask_value(value: object, masker: Masker) -> object:
    """Return a decoded JSON value with every string value masked; keys stay as they are and are checked."""
    if isinstance(value, str):
        return masker.mask(value)
    if isinstance(value, list):
        return [_mask_value(item, masker) for item in value]
    if isinstance(value, dict):
        return {key: _mask_value(item, masker) for key, item in value.items()}
    return value


def _strings(value: object) -> Iterator[str]:
    """Yield every string inside a decoded JSON value, keys included."""
    if isinstance(value, str):
        yield value
    elif isinstance(value, list):
        for item in value:
            yield from _strings(item)
    elif isinstance(value, dict):
        for key, item in value.items():
            yield key
            yield from _strings(item)


def value_findings(name: str, values: list[object]) -> list[str]:
    """Check decoded content for credentials and unmasked private data; never echo the matched text.

    Every string (keys too) is checked, and so is each value re-serialized without ASCII escapes, so a
    key and its value are also read together.

    Examples:
        >>> value_findings("t.jsonl", [{"note": "mail dana" + "@" + "rivetco.example from /tmp/x"}])
        ['t.jsonl: an email address', 't.jsonl: a home folder owner or temporary root that is not masked']
        >>> value_findings("t.jsonl", [{"api_key": "rf" * 4 + "0123456789ab"}])
        ['t.jsonl: secret-like material (pattern 9)']
    """
    texts = [text for value in values for text in (*_strings(value), json.dumps(value, ensure_ascii=False))]
    findings = credential_findings(tuple((name, text) for text in texts))[:1]
    return findings + [f"{name}: {label}" for label, found in RESIDUE_CHECKS if any(found(text) for text in texts)]


def prepare_file(name: str, raw: bytes, masker: Masker) -> PublishedFile:
    """Turn one source file into its committed form: decoded, masked inside every string value, re-serialized.

    Args:
        name: Published file name, ending in ``.json`` or ``.jsonl``.
        raw: Source bytes.
        masker: Machine-specific masking for this run.

    Returns:
        The file as it will be written; ``masked`` says whether masking changed any value.

    Raises:
        PublishRefusedError: The file is not UTF-8 or not valid JSON / JSON Lines.

    Examples:
        >>> masker = Masker.for_run(Path("/run"), login="", host="")
        >>> prepare_file("meta.json", b'{"b": 1, "a": "\\\\u002fhome\\\\u002fsam/x"}', masker).data
        b'{\\n  "a": "/home/<user>/x",\\n  "b": 1\\n}\\n'
    """
    values = decode_values(name, raw)
    data = render_values(name, [_mask_value(value, masker) for value in values])
    return PublishedFile(path=name, data=data, masked=data != render_values(name, values))


def content_findings(files: tuple[PublishedFile, ...]) -> list[str]:
    """Return size, format, secret, and private-data findings for files about to be committed or re-checked.

    Examples:
        >>> content_findings((PublishedFile("t.jsonl", b'{"k": "AKIA' + b"A" * 16 + b'"}\\n', False),))
        ['t.jsonl: secret-like material (pattern 2)']
        >>> content_findings((PublishedFile("t.jsonl", b"{}\\n", False),))
        []
    """
    findings = []
    for item in files:
        if len(item.data) > MAX_FILE_BYTES:
            findings.append(f"{item.path}: {len(item.data)} bytes exceeds the {MAX_FILE_BYTES}-byte commit limit")
        try:
            values = decode_values(item.path, item.data)
        except PublishRefusedError as refusal:
            findings += refusal.findings
            continue
        findings += value_findings(item.path, values)
    return findings


def _walk(root: Path) -> Iterator[tuple[str, Path]]:
    """Yield every file and symlink below ``root`` as ``(relative POSIX path, path)``, never following links."""
    for current, dirnames, filenames in os.walk(root, followlinks=False):
        base = Path(current)
        dirnames.sort()
        linked_dirs = [name for name in dirnames if (base / name).is_symlink()]
        for name in sorted([*filenames, *linked_dirs]):
            path = base / name
            yield path.relative_to(root).as_posix(), path


def _collect_folder(profile: SuiteProfile, run_path: Path) -> tuple[dict[str, bytes], dict[str, int], dict[str, int]]:
    listed = {*profile.required, *profile.optional}
    sources: dict[str, bytes] = {}
    dropped = {reason.value: 0 for reason in DropReason}
    counts = {key: 0 for key, _ in profile.counted}
    problems = []
    for relative, path in _walk(run_path):
        if path.is_symlink():
            if relative in listed:
                problems.append(f"{relative}: publishable file is a symlink")
            dropped[DropReason.SYMLINK.value] += 1
            continue
        if relative in listed:
            sources[relative] = path.read_bytes()
            continue
        dropped[DropReason.NOT_LISTED.value] += 1
        for key, pattern in profile.counted:
            counts[key] += fnmatch.fnmatchcase(relative, pattern)
    problems += [f"{name}: required file is missing" for name in profile.required if name not in sources]
    if problems:
        raise PublishRefusedError(problems)
    return sources, dropped, counts


def _collect_file(profile: SuiteProfile, run_path: Path) -> tuple[dict[str, bytes], dict[str, int], dict[str, int]]:
    if run_path.is_symlink() or not run_path.is_file() or run_path.suffix != ".jsonl":
        raise PublishRefusedError([f"{run_path.name}: a {profile.suite.value} run is one regular .jsonl file"])
    return {profile.required[0]: run_path.read_bytes()}, {}, {}


def run_name(profile: SuiteProfile, run_path: Path) -> str:
    """Return the folder name a run gets inside its set.

    Examples:
        >>> run_name(PROFILES[Suite.TRIGGER_LIVE], Path("runs/2026-11-10T10-00-00Z-claude.jsonl"))
        '2026-11-10T10-00-00Z-claude'
        >>> run_name(PROFILES[Suite.AB], Path("runs/2026-11-10T10-00-00Z-s4-P-scripted-r0"))
        '2026-11-10T10-00-00Z-s4-P-scripted-r0'
    """
    return run_path.stem if profile.shape == RunShape.FILE else run_path.name


def build_package(profile: SuiteProfile, run_path: Path, set_id: str, masker: Masker | None = None) -> Package:
    """Read a run, keep only its publishable files, and check them; nothing is written here.

    Args:
        profile: Suite profile naming the publishable files.
        run_path: Absolute path of the run folder (or results file for a file-shaped suite).
        set_id: Publication set name; a published number cites ``<publish root>/<set>/``.
        masker: Machine-specific masking; defaults to this machine's paths, login, and host name.

    Returns:
        The package to write.

    Raises:
        PublishRefusedError: Unsafe or secret-like names, a wrong run shape, a missing or malformed file, an
            oversized file, or secret-like material or unmasked private data in anything that would be committed.

    Examples:
        >>> build_package(PROFILES[Suite.AB], Path("/no/such/run"), "../escape")
        Traceback (most recent call last):
        ...
        publish_run.PublishRefusedError: set name '../escape' must match [A-Za-z0-9][A-Za-z0-9._-]{0,119}
    """
    name = run_name(profile, run_path)
    names = credential_findings((("set name", set_id), ("run name", name)))
    if names:
        raise PublishRefusedError(names)
    for label, value in (("set", set_id), ("run", name)):
        if not SAFE_NAME.fullmatch(value):
            raise PublishRefusedError([f"{label} name {value!r} must match {SAFE_NAME.pattern[1:-1]}"])
    if profile.shape == RunShape.FOLDER and (run_path.is_symlink() or not run_path.is_dir()):
        raise PublishRefusedError([f"{name}: a {profile.suite.value} run is a folder, not a symlink or file"])
    collect = _collect_folder if profile.shape == RunShape.FOLDER else _collect_file
    sources, dropped, counts = collect(profile, run_path)
    masker = masker or Masker.for_run(run_path)
    files = tuple(prepare_file(item, sources[item], masker) for item in sorted(sources))
    package = Package(profile, set_id, name, files, dropped, counts)
    findings = content_findings(files) + credential_findings(((MANIFEST_NAME, package.manifest().decode()),))
    if findings:
        raise PublishRefusedError(findings)
    return package


def write_package(package: Package, publish_root: Path) -> Path:
    """Write the package to ``<publish_root>/<set>/<run>/``, manifest last; never overwrite.

    Args:
        package: Package from :func:`build_package`.
        publish_root: Committed folder for the suite.

    Returns:
        The written folder.

    Raises:
        PublishRefusedError: The target path looks like it holds a credential, or the folder already exists.

    Examples:
        >>> callable(write_package)
        True
    """
    target = publish_root / package.set_id / package.run_name
    path_findings = credential_findings((("target path", str(target)),))
    if path_findings:
        raise PublishRefusedError(path_findings)
    target.parent.mkdir(parents=True, exist_ok=True)
    try:
        target.mkdir()
    except FileExistsError as exc:
        raise PublishRefusedError(
            [f"{_display(target)} already exists; a published folder is never overwritten"]
        ) from exc
    try:
        for item in package.files:
            (target / item.path).write_bytes(item.data)
        (target / MANIFEST_NAME).write_bytes(package.manifest())
    except OSError:
        shutil.rmtree(target, ignore_errors=True)
        raise
    return target


def _safe_relative(raw: object) -> PurePosixPath | None:
    """Return a folder-relative manifest path, or ``None`` when it is empty, absolute, or escapes the folder."""
    if not isinstance(raw, str) or not raw or "\\" in raw:
        return None
    relative = PurePosixPath(raw)
    return None if relative.is_absolute() or ".." in relative.parts else relative


def _record_findings(folder: Path, record: object) -> tuple[str | None, list[str]]:
    if not isinstance(record, dict):
        return None, ["manifest holds a file record that is not an object"]
    relative = _safe_relative(record.get("path"))
    if relative is None:
        return None, [f"unsafe manifest path: {record.get('path')!r}"]
    path = folder / relative
    if path.is_symlink() or not path.is_file():
        return relative.as_posix(), [f"{relative}: listed in the manifest but not a regular file"]
    data = path.read_bytes()
    if record.get("sha256") != sha256(data) or record.get("bytes") != len(data):
        return relative.as_posix(), [f"{relative}: content does not match its manifest digest"]
    return relative.as_posix(), []


def _identity_findings(folder: Path, manifest: dict[str, object], raw: str) -> list[str]:
    """Check that the manifest names this folder's set and run and a known suite, and holds no credential."""
    findings = credential_findings(((MANIFEST_NAME, raw),))
    if manifest.get("set") != folder.parent.name:
        findings.append(f"{MANIFEST_NAME}: its set does not match the set folder name")
    if manifest.get("run") != folder.name:
        findings.append(f"{MANIFEST_NAME}: its run does not match the run folder name")
    if manifest.get("suite") not in {suite.value for suite in Suite}:
        findings.append(f"{MANIFEST_NAME}: its suite is not one this helper publishes")
    return findings


def verify_folder(folder: Path) -> list[str]:
    """Re-check a published folder: its set and run names, digests, no unlisted files, no private data.

    ``verify`` catches accidental edits. A coordinated edit of a file and its manifest entry passes;
    git history is the record of who changed what.

    Args:
        folder: A ``<publish root>/<set>/<run>/`` folder.

    Returns:
        Findings; empty when the folder matches its manifest.

    Examples:
        >>> verify_folder(Path("/no/such/folder"))[0].startswith("cannot read publish-manifest.json")
        True
    """
    try:
        raw = (folder / MANIFEST_NAME).read_text(encoding="utf-8")
        manifest = json.loads(raw)
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        return [f"cannot read {MANIFEST_NAME}: {exc}"]
    if not isinstance(manifest, dict) or manifest.get("schema_version") != SCHEMA_VERSION:
        return [f"{MANIFEST_NAME} is not schema {SCHEMA_VERSION}"]
    records = manifest.get("files")
    if not isinstance(records, list):
        return [f"{MANIFEST_NAME} has no files list"]
    findings: list[str] = _identity_findings(folder, manifest, raw)
    listed: set[str] = set()
    for record in records:
        relative, problems = _record_findings(folder, record)
        findings += problems
        if relative:
            listed.add(relative)
    actual = {relative for relative, _ in _walk(folder) if relative != MANIFEST_NAME}
    findings += [f"{relative}: present but not in the manifest" for relative in sorted(actual - listed)]
    present = tuple(
        PublishedFile(relative, (folder / relative).read_bytes(), False)
        for relative in sorted(listed & actual)
        if (folder / relative).is_file()
    )
    return findings + content_findings(present)


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    """Parse helper options.

    Examples:
        >>> parse_args(["verify", "x"]).command
        'verify'
    """
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    commands = parser.add_subparsers(dest="command", required=True)
    pack = commands.add_parser(Command.PACK.value, help="copy one run into its committed, redacted folder")
    pack.add_argument("--suite", required=True, choices=[suite.value for suite in Suite])
    pack.add_argument("--run", required=True, type=Path, help="run folder (ab) or results .jsonl file (trigger-live)")
    pack.add_argument("--set", required=True, dest="set_id", help="publication set a published number cites")
    pack.add_argument("--publish-root", type=Path, default=None, help="override the suite's committed folder")
    verify = commands.add_parser(Command.VERIFY.value, help="re-check a published folder against its manifest")
    verify.add_argument("folder", type=Path)
    return parser.parse_args(argv)


def _display(path: Path) -> str:
    try:
        return path.relative_to(ROOT).as_posix()
    except ValueError:
        return str(path)


def _pack(args: argparse.Namespace) -> int:
    profile = PROFILES[Suite(args.suite)]
    run_path = Path(os.path.abspath(args.run))
    publish_root = Path(os.path.abspath(args.publish_root)) if args.publish_root else profile.publish_root
    if publish_root.resolve() in (run_path.resolve(), *run_path.resolve().parents):
        raise PublishRefusedError([f"{_display(run_path)} is already inside the publish folder"])
    package = build_package(profile, run_path, args.set_id)
    target = write_package(package, publish_root)
    print(f"published {len(package.files)} file(s) to {_display(target)}")
    print(f"dropped: {json.dumps(dict(package.dropped), sort_keys=True)}; counts: {json.dumps(dict(package.counts))}")
    print(f"{MANIFEST_NAME} sha256 {sha256(package.manifest())}")
    return 0


def main(argv: list[str] | None = None) -> int:
    """Run one subcommand and return a shell status: 0 done, 1 refused or mismatched.

    Examples:
        >>> import contextlib, io
        >>> with contextlib.redirect_stderr(io.StringIO()):
        ...     main(["verify", "/no/such/folder"])
        1
    """
    args = parse_args(argv)
    try:
        if Command(args.command) == Command.PACK:
            return _pack(args)
        findings = verify_folder(Path(os.path.abspath(args.folder)))
    except PublishRefusedError as refusal:
        print("publish refused:", file=sys.stderr)
        print("\n".join(f"- {finding}" for finding in refusal.findings), file=sys.stderr)
        return 1
    if findings:
        print(f"verify failed: {_display(Path(os.path.abspath(args.folder)))}", file=sys.stderr)
        print("\n".join(f"- {finding}" for finding in findings), file=sys.stderr)
        return 1
    print(f"verified: {_display(Path(os.path.abspath(args.folder)))} matches its manifest")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
