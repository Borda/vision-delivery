#!/usr/bin/env python3
"""Package a user-recorded golden run as redacted, reproducible scoring evidence.

Purpose: Preserve labels, predictions, dataset provenance and a session transcript together.
Scope: Offline packaging only; no images, remote calls, publication or claim of label independence.
Usage: Run ``pack --help`` for input flags, then ``verify <folder>`` to check the resulting evidence.
Outputs: A new date-number folder and golden-manifest.json with byte sizes, hashes and masking flags.
Failure: Exit 1 refuses unsafe input or failed verification; argparse uses exit 2 for invalid CLI syntax.
Used by: Maintainers following examples/golden-run/README.md after their own live session.

All inputs are decoded and checked before the output tree is created. Scoring uses a temporary redacted
snapshot, so evidence hashes describe the exact committed bytes. Verification reproduces the printed verdict
line, not the scorer's time-dependent JSON timestamp. Digests detect accidental edits; a coordinated rewrite
of the manifest and files is not authenticated. Review and repository history remain the provenance record.
"""

from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
import tempfile
from datetime import date
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

from publish_run import (
    MAX_FILE_BYTES,
    ROOT,
    Masker,
    PublishedFile,
    PublishRefusedError,
    canonical_json,
    credential_findings,
    decode_values,
    prepare_file,
    sha256,
    value_findings,
)

MANIFEST = "golden-manifest.json"
ROUTE = re.compile(r"[a-z0-9][a-z0-9-]{0,62}")
RUN_FOLDER = re.compile(r"\d{4}-\d{2}-\d{2}-[1-9]\d*")
LIMITS = (
    "Gold labels and predictions were produced by the user's own session; this folder shows what was scored, "
    "not that the labels are independent of the predictions."
)
# A conservative offline set: an unrecognized identifier needs human licence review, not a guessed approval.
OPEN_LICENSES = frozenset(
    name.casefold()
    for name in (
        "CC0-1.0",
        "CC-BY-1.0",
        "CC-BY-2.0",
        "CC-BY-2.5",
        "CC-BY-3.0",
        "CC-BY-4.0",
        "CC-BY-SA-1.0",
        "CC-BY-SA-2.0",
        "CC-BY-SA-2.5",
        "CC-BY-SA-3.0",
        "CC-BY-SA-4.0",
        "PDDL-1.0",
        "ODC-By-1.0",
        "ODbL-1.0",
        "MIT",
        "Apache-2.0",
        "BSD-2-Clause",
        "BSD-3-Clause",
    )
)
REQUIRED = {"dataset.json", "gold.jsonl", "pred.jsonl", "scorer-output.txt", "scorer-evidence.json"}
OPTIONAL = {"transcript.txt", "transcript.jsonl", "ledger.jsonl", "acceptance.json"}


def require(condition: object, message: str) -> None:
    """Refuse without echoing potentially sensitive input values."""
    if not condition:
        raise PublishRefusedError([message])


def read_bounded(path: Path) -> bytes:
    """Read at most the commit-size limit from a regular, non-symlink source."""
    require(path.is_file() and not path.is_symlink(), "input must be a regular file, not a symlink")
    with path.open("rb") as stream:
        raw = stream.read(MAX_FILE_BYTES + 1)
    require(len(raw) <= MAX_FILE_BYTES, "file exceeds the 250 KB commit limit")
    return raw


def check_dataset(value: object) -> dict[str, Any]:
    """Validate provenance, conservative open licensing, dates and the no-image policy."""
    require(isinstance(value, dict), "dataset must be a JSON object")
    assert isinstance(value, dict)
    for key in ("name", "source_url", "license_spdx", "license_url", "retrieved_on", "citation"):
        require(isinstance(value.get(key), str) and value[key].strip(), f"dataset needs non-empty {key}")
    for key in ("source_url", "license_url"):
        url = urlsplit(value[key])
        require(url.scheme == "https" and url.hostname and not url.username, f"dataset {key} needs a public HTTPS URL")
    require(value["license_spdx"].strip().casefold() in OPEN_LICENSES, "dataset licence is unknown or not open")
    require(re.fullmatch(r"\d{4}-\d{2}-\d{2}", value["retrieved_on"]), "dataset date must be YYYY-MM-DD")
    date.fromisoformat(value["retrieved_on"])
    require(type(value.get("image_count")) is int and value["image_count"] > 0, "dataset image_count must be positive")
    require(value.get("images_committed") is False, "dataset images_committed must be false")
    return value


def text_values(text: str) -> list[object]:
    """Decode embedded JSON lines too, so a text suffix cannot hide escaped private data."""
    try:
        return [json.loads(text)]
    except json.JSONDecodeError:
        values: list[object] = [text, decode_text_escapes(text)]
    for line in text.splitlines():
        try:
            values.append(json.loads(line))
        except json.JSONDecodeError:
            continue
    return values


def decode_text_escapes(text: str) -> str:
    """Expose JSON Unicode escapes in prose and fenced fragments before masking or judging them."""
    return re.sub(r"\\u([0-9a-fA-F]{4})", lambda match: chr(int(match[1], 16)), text)


def check_content(name: str, raw: bytes) -> list[object]:
    """Decode committed content and refuse any surviving private-data shapes."""
    require(len(raw) <= MAX_FILE_BYTES, f"{name}: file exceeds the 250 KB commit limit")
    text = raw.decode("utf-8")
    values = decode_values(name, raw) if name.endswith((".json", ".jsonl")) else text_values(text)
    findings = value_findings(name, values)
    if findings:
        raise PublishRefusedError(findings)
    return values


def prepare(name: str, raw: bytes, masker: Masker) -> PublishedFile:
    """Mask decoded JSON or text and check both raw credentials and all final content."""
    text = raw.decode("utf-8")
    values = decode_values(name, raw) if name.endswith((".json", ".jsonl")) else text_values(text)
    findings = credential_findings(tuple((name, json.dumps(value, ensure_ascii=False)) for value in values))
    if findings:
        raise PublishRefusedError(findings)
    if name.endswith((".json", ".jsonl")):
        item = prepare_file(name, raw, masker)
    else:
        # Decode valid JSON fragments before masking even in a mixed prose/JSON transcript.
        lines = []
        for line in decode_text_escapes(text).splitlines(keepends=True):
            try:
                line = json.dumps(json.loads(line), ensure_ascii=False) + "\n"
            except json.JSONDecodeError:
                pass
            lines.append(line)
        normalized = "".join(lines)
        data = masker.mask(normalized).encode("utf-8")
        item = PublishedFile(name, data, data != normalized.encode("utf-8"))
    check_content(name, item.data)
    return item


def transcript_name(path: Path, raw: bytes) -> str:
    """Recognize JSON Lines by content, while requiring valid JSON for a .jsonl source."""
    if path.suffix.lower() == ".jsonl":
        decode_values("transcript.jsonl", raw)
        return "transcript.jsonl"
    try:
        values = decode_values("transcript.jsonl", raw)
    except PublishRefusedError:
        return "transcript.txt"
    return "transcript.jsonl" if values else "transcript.txt"


def collect(args: argparse.Namespace) -> dict[str, PublishedFile]:
    """Read and redact exactly the allowed inputs before creating any output directory."""
    require(ROUTE.fullmatch(args.route), "route must match [a-z0-9][a-z0-9-]{0,62}")
    masker = Masker.for_run(args.transcript.absolute().parent)
    sources = {"dataset.json": args.dataset_file, "gold.jsonl": args.gold, "pred.jsonl": args.pred}
    for name in ("ledger", "acceptance"):
        if getattr(args, name) is not None:
            sources[name + (".jsonl" if name == "ledger" else ".json")] = getattr(args, name)
    files = {name: prepare(name, read_bounded(path), masker) for name, path in sources.items()}
    raw = read_bounded(args.transcript)
    name = transcript_name(args.transcript, raw)
    files[name] = prepare(name, raw, masker)
    check_dataset(json.loads(files["dataset.json"].data))
    return files


def score(folder: Path, settings: dict[str, Any]) -> tuple[bytes, bytes]:
    """Invoke the actual repository scorer on a snapshot and capture its stdout and evidence."""
    with tempfile.TemporaryDirectory(prefix="golden-score-") as temporary:
        evidence = Path(temporary) / "evidence.json"
        command = [sys.executable, str(ROOT / "resources/scripts/score_baseline.py")]
        for option in ("gold", "pred"):
            command.extend([f"--{option}", str(folder / f"{option}.jsonl")])
        for option in ("task", "metric", "comparator", "threshold"):
            command.extend([f"--{option}", str(settings[option])])
        if (folder / "acceptance.json").exists():
            command.extend(["--acceptance", str(folder / "acceptance.json")])
        command.extend(["--evidence-out", str(evidence)])
        result = subprocess.run(command, capture_output=True, timeout=120, check=False)
        require(result.returncode == 0, f"scorer refused the inputs (exit {result.returncode}); no pack written")
        output, raw = result.stdout, read_bounded(evidence)
    record = json.loads(raw)
    target = record["target"]
    require(record["task"] == settings["task"], "scorer task does not match requested task")
    require(
        all(target[key] == settings[key] for key in ("metric", "comparator", "threshold")),
        "acceptance target does not match the requested scoring settings",
    )
    return output, raw


def scored_files(files: dict[str, PublishedFile], settings: dict[str, Any]) -> dict[str, PublishedFile]:
    """Score exactly the bytes to be published, including redacted acceptance when supplied."""
    with tempfile.TemporaryDirectory(prefix="golden-inputs-") as temporary:
        folder = Path(temporary)
        for item in files.values():
            (folder / item.path).write_bytes(item.data)
        output, evidence = score(folder, settings)
    masker = Masker.for_run(folder)
    files["scorer-output.txt"] = prepare("scorer-output.txt", output, masker)
    files["scorer-evidence.json"] = prepare("scorer-evidence.json", evidence, masker)
    return files


def harness_commit() -> str | None:
    """Read the local harness revision without changing Git state; absence is allowed."""
    try:
        result = subprocess.run(
            ["git", "-C", str(ROOT), "rev-parse", "HEAD"], capture_output=True, text=True, timeout=10, check=False
        )
    except (OSError, subprocess.TimeoutExpired):
        return None
    value = result.stdout.strip()
    return value if result.returncode == 0 and re.fullmatch(r"[0-9a-f]{40,64}", value) else None


def manifest_bytes(files: dict[str, PublishedFile], settings: dict[str, Any], identity: tuple[str, str]) -> bytes:
    """Build the complete manifest, including exact dataset metadata and the honest limits sentence."""
    evidence = json.loads(files["scorer-evidence.json"].data)
    verdict = str(evidence["verdict"]).upper().replace("NO-VERDICT", "NO VERDICT")
    value = {
        "schema_version": 1,
        "route": identity[0],
        "run_folder": identity[1],
        "dataset": json.loads(files["dataset.json"].data),
        **settings,
        "verdict": verdict,
        "first_line": files["scorer-output.txt"].data.decode().splitlines()[0],
        "files": [files[name].record() for name in sorted(files)],
        "harness_commit": harness_commit(),
        "limits": LIMITS,
    }
    raw = canonical_json(value).encode()
    check_content(MANIFEST, raw)
    return raw


def write_pack(args: argparse.Namespace, files: dict[str, PublishedFile], settings: dict[str, Any]) -> Path:
    """Publish by same-filesystem rename under an exclusive route lock; never replace a run."""
    parent = args.out_root / args.route
    # Validate the manifest before touching the destination. The final identity uses only a date and integer.
    manifest_bytes(files, settings, (args.route, f"{date.today().isoformat()}-1"))
    parent.mkdir(parents=True, exist_ok=True)
    lock = parent / ".pack-lock"
    try:
        lock.mkdir()
    except FileExistsError as exc:
        raise PublishRefusedError(["another pack owns this route lock; no run written"]) from exc
    try:
        number = 1
        prefix = date.today().isoformat()
        while (parent / f"{prefix}-{number}").exists() or (parent / f"{prefix}-{number}").is_symlink():
            number += 1
        target = parent / f"{prefix}-{number}"
        raw = manifest_bytes(files, settings, (args.route, target.name))
        with tempfile.TemporaryDirectory(prefix=".golden-", dir=parent) as temporary:
            staging = Path(temporary) / "run"
            staging.mkdir()
            for item in files.values():
                (staging / item.path).write_bytes(item.data)
            (staging / MANIFEST).write_bytes(raw)
            require(not target.exists() and not target.is_symlink(), "run folder already exists")
            staging.rename(target)
    finally:
        lock.rmdir()
    return target


def checked_manifest(folder: Path) -> dict[str, Any]:
    """Validate the manifest schema, identity and fixed metadata before trusting any record."""
    require(folder.is_dir() and not folder.is_symlink(), "verify needs a regular run folder")
    raw = read_bounded(folder / MANIFEST)
    check_content(MANIFEST, raw)
    value = json.loads(raw)
    require(isinstance(value, dict) and value.get("schema_version") == 1, "unsupported manifest schema")
    require(value.get("route") == folder.parent.name and ROUTE.fullmatch(folder.parent.name), "route identity differs")
    require(value.get("run_folder") == folder.name and RUN_FOLDER.fullmatch(folder.name), "run identity differs")
    require(value.get("limits") == LIMITS, "manifest limits sentence differs")
    require(isinstance(value.get("files"), list), "manifest files must be a list")
    check_dataset(value.get("dataset"))
    return value


def checked_files(folder: Path, records: list[object]) -> dict[str, bytes]:
    """Check allowed flat names, digests, sizes, redaction and exact directory membership."""
    files: dict[str, bytes] = {}
    for record in records:
        require(isinstance(record, dict), "manifest file record must be an object")
        assert isinstance(record, dict)
        name = record.get("path")
        require(isinstance(name, str) and name in REQUIRED | OPTIONAL, "unrecognized manifest file name")
        assert isinstance(name, str)
        require(name not in files, "duplicate manifest file record")
        raw = read_bounded(folder / name)
        require(record.get("sha256") == sha256(raw) and record.get("bytes") == len(raw), "file digest or size differs")
        require(type(record.get("masked")) is bool, "file record needs a masking flag")
        check_content(name, raw)
        files[name] = raw
    require(REQUIRED <= files.keys(), "manifest omits required files")
    require(len({"transcript.txt", "transcript.jsonl"} & files.keys()) == 1, "manifest needs exactly one transcript")
    require({path.name for path in folder.iterdir()} == set(files) | {MANIFEST}, "unlisted files or folders present")
    return files


def verify(folder: Path) -> None:
    """Re-hash every file and reproduce the scorer's first line using recorded settings."""
    manifest = checked_manifest(folder)
    files = checked_files(folder, manifest["files"])
    require(json.loads(files["dataset.json"]) == manifest["dataset"], "dataset metadata differs from manifest")
    # Re-score a private copy, avoiding any writes or implicit trust in paths under the packed folder.
    with tempfile.TemporaryDirectory(prefix="golden-verify-") as temporary:
        snapshot = Path(temporary)
        for name, raw in files.items():
            (snapshot / name).write_bytes(raw)
        output, raw = score(snapshot, manifest)
    first = output.decode("utf-8").splitlines()[0]
    require(first == files["scorer-output.txt"].decode("utf-8").splitlines()[0], "re-scored printed line differs")
    require(first == manifest.get("first_line"), "manifest printed line differs")
    evidence = json.loads(raw)
    require(
        manifest.get("verdict") == str(evidence["verdict"]).upper().replace("NO-VERDICT", "NO VERDICT"),
        "manifest verdict differs",
    )
    stored = json.loads(files["scorer-evidence.json"])
    # A scorer timestamp is the only expected difference between identical offline scoring invocations.
    stored.pop("measured_at", None)
    evidence.pop("measured_at", None)
    require(stored == evidence, "re-scored evidence differs")


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    """Parse the two bounded CLI operations."""
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    commands = parser.add_subparsers(dest="command", required=True)
    pack = commands.add_parser("pack", help="pack one user-recorded session")
    pack.add_argument("--route", required=True)
    for option in ("dataset-file", "gold", "pred", "transcript"):
        pack.add_argument(f"--{option}", type=Path, required=True)
    pack.add_argument("--task", required=True, choices=("count", "flag", "text"))
    pack.add_argument("--metric", required=True)
    pack.add_argument("--comparator", required=True, choices=("gte", "lte"))
    pack.add_argument("--threshold", required=True, type=float)
    pack.add_argument("--ledger", type=Path)
    pack.add_argument("--acceptance", type=Path)
    pack.add_argument("--out-root", type=Path, default=ROOT / "examples/golden-run")
    commands.add_parser("verify", help="check hashes and reproduce scoring").add_argument("folder", type=Path)
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    """Pack or verify; report refusal categories without echoing private content."""
    args = parse_args(argv)
    try:
        if args.command == "verify":
            verify(args.folder)
            print("OK golden run verified")
            return 0
        settings = {key: getattr(args, key) for key in ("task", "metric", "comparator", "threshold")}
        files = scored_files(collect(args), settings)
        folder = write_pack(args, files, settings)
        print(folder)
        print(f"{MANIFEST} sha256 {sha256((folder / MANIFEST).read_bytes())}")
    except PublishRefusedError as exc:
        print("golden-run-refused: " + "; ".join(exc.findings), file=sys.stderr)
        return 1
    except (OSError, ValueError, KeyError, TypeError, RecursionError, subprocess.TimeoutExpired):
        print("golden-run-refused: unreadable, malformed or unusable input; no successful pack", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
