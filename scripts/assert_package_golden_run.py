#!/usr/bin/env python3
"""Exercise the golden-run CLI offline with real scoring and disposable synthetic inputs."""

from __future__ import annotations

import getpass
import json
import socket
import subprocess
import sys
import tempfile
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "package_golden_run.py"


def write_json(path: Path, value: object) -> None:
    """Write portable JSON fixture bytes."""
    path.write_bytes((json.dumps(value) + "\n").encode())


def fixture(root: Path, task: str = "count") -> list[str]:
    """Create one self-contained input set and return its pack command."""
    root.mkdir(parents=True)
    dataset = {
        "name": "Synthetic self-check only",
        "source_url": "https://example.org/images",
        "license_spdx": "CC0-1.0",
        "license_url": "https://example.org/license",
        "retrieved_on": "2026-01-01",
        "citation": "Synthetic fixture, no real dataset or run",
        "image_count": 6,
        "images_committed": False,
    }
    write_json(root / "dataset.json", dataset)
    value = {"count": 2, "flag": True, "text": "sample"}[task]
    rows = [{"image": f"frame-{i}.png", task: value} for i in range(6)]
    labels = "".join(json.dumps(row) + "\n" for row in rows).encode()
    (root / "gold.jsonl").write_bytes(labels)
    (root / "pred.jsonl").write_bytes(labels)
    (root / "session.txt").write_bytes(b"A synthetic session.\n")
    metric = {"count": "exact_count_rate", "flag": "accuracy", "text": "exact_match_rate"}[task]
    args = [sys.executable, str(SCRIPT), "pack", "--route", "synthetic-route"]
    for option, name in (("dataset-file", "dataset.json"), ("gold", "gold.jsonl"), ("pred", "pred.jsonl")):
        args.extend([f"--{option}", str(root / name)])
    args.extend(["--task", task, "--metric", metric, "--comparator", "gte", "--threshold", "0.5"])
    args.extend(["--transcript", str(root / "session.txt"), "--out-root", str(root / "packed")])
    return args


def run(args: list[str], success: bool = True) -> subprocess.CompletedProcess[str]:
    """Run the real CLI and require the expected status without leaking fixture content."""
    result = subprocess.run(args, capture_output=True, text=True, timeout=60, check=False)
    expected = 0 if success else 1
    assert result.returncode == expected, (result.returncode, result.stdout, result.stderr)
    return result


def packed(root: Path) -> Path:
    """Find the sole completed pack below this fixture's output root."""
    folders = list((root / "packed").glob("*/*/golden-manifest.json"))
    assert len(folders) == 1, folders
    return folders[0].parent


def check_tasks(scratch: Path) -> None:
    """All task types pack, verify, detect a byte edit, and detect an extra file."""
    for task in ("count", "flag", "text"):
        root = scratch / task
        result = run(fixture(root, task))
        folder = packed(root)
        manifest = json.loads((folder / "golden-manifest.json").read_bytes())
        assert manifest["task"] == task and manifest["verdict"] == "PASS"
        assert str(folder) in result.stdout and "sha256" in result.stdout
        verify = [sys.executable, str(SCRIPT), "verify", str(folder)]
        run(verify)
        original = (folder / "transcript.txt").read_bytes()
        (folder / "transcript.txt").write_bytes(b"B" + original[1:])
        run(verify, False)
        (folder / "transcript.txt").write_bytes(original)
        (folder / "extra.txt").write_bytes(b"extra\n")
        run(verify, False)
        (folder / "extra.txt").unlink()
        run(verify)


def check_dataset_refusals(scratch: Path) -> None:
    """Invalid metadata cannot create any output root."""
    changes = (
        ("license_spdx", "proprietary"),
        ("license_spdx", "NOASSERTION"),
        ("license_spdx", "Unrecognized-1.0"),
        ("source_url", "http://example.org/images"),
        ("license_url", "http://example.org/license"),
        ("images_committed", True),
        ("citation", None),
        ("retrieved_on", "2026-02-30"),
        ("image_count", True),
    )
    for number, (key, value) in enumerate(changes):
        root = scratch / str(number)
        args = fixture(root)
        dataset = json.loads((root / "dataset.json").read_bytes())
        dataset[key] = value
        if value is None:
            del dataset[key]
        write_json(root / "dataset.json", dataset)
        run(args, False)
        assert not (root / "packed").exists()


def check_content_refusals(scratch: Path) -> None:
    """Credentials, decoded escapes, addresses, binary and oversized input refuse atomically."""
    token = "gh" + "p_" + "Z9" * 18
    escaped = token[:4] + f"\\u{ord(token[4]):04x}" + token[5:]
    cases = (
        token.encode(),
        ('{"text": "' + escaped + '"}\n').encode(),
        (
            'Session notes\n```json\n{\n  "token": "' + "".join(f"\\u{ord(char):04x}" for char in token) + '"\n}\n```\n'
        ).encode(),
        b"mail synthetic.person@example.org",
        b"address 10.20.30.40",
        b"x" * (250 * 1024 + 1),
        b"\xff",
    )
    for number, content in enumerate(cases):
        root = scratch / str(number)
        args = fixture(root)
        (root / "session.txt").write_bytes(content)
        result = run(args, False)
        assert token not in result.stderr
        assert not (root / "packed").exists()


def check_scorer_refusal(scratch: Path) -> None:
    """Syntactically valid JSON with malformed labels reaches the scorer and refuses the pack."""
    args = fixture(scratch)
    (scratch / "gold.jsonl").write_bytes(b'{"image": "frame-0.png", "count": "bad"}\n')
    result = run(args, False)
    assert "scorer" in result.stderr and "2" in result.stderr
    assert not (scratch / "packed").exists()


def check_numbering_and_masking(scratch: Path) -> None:
    """Packing twice preserves the first folder and masks decoded paths, login and host."""
    args = fixture(scratch)
    login, host = getpass.getuser(), socket.gethostname()
    note = f"{scratch}/frames /opt/{login}/frames {host} /Users/Other Person/frames"
    (scratch / "session.txt").write_bytes((json.dumps({"note": note}) + "\n").encode())
    run(args)
    folder = packed(scratch)
    assert folder.name == f"{date.today().isoformat()}-1"
    text = (folder / "transcript.jsonl").read_text(encoding="utf-8")
    assert "<run>/frames" in text and "/Users/<user>/frames" in text
    if len(login) >= 2:
        assert "/opt/<user>/frames" in text
    if len(host) >= 3:
        assert "<host>" in text and host not in text
    before = {p.name: p.read_bytes() for p in folder.iterdir()}
    run(args)
    assert before == {p.name: p.read_bytes() for p in folder.iterdir()}
    assert (folder.parent / f"{date.today().isoformat()}-2" / "golden-manifest.json").is_file()
    manifest = json.loads(before["golden-manifest.json"])
    assert next(item for item in manifest["files"] if item["path"] == "transcript.jsonl")["masked"]
    run([sys.executable, str(SCRIPT), "verify", str(folder)])


def check_no_verdict(scratch: Path) -> None:
    """A valid but undersized sample remains publishable evidence with NO VERDICT."""
    args = fixture(scratch)
    args[args.index("exact_count_rate")] = "catch_rate"
    run(args)
    folder = packed(scratch)
    manifest = json.loads((folder / "golden-manifest.json").read_bytes())
    assert manifest["verdict"] == "NO VERDICT"
    assert "NO VERDICT" in manifest["first_line"]
    run([sys.executable, str(SCRIPT), "verify", str(folder)])


def check_optional_inputs(scratch: Path) -> None:
    """A valid acceptance and contextual ledger round trip; conflicting settings refuse atomically."""
    args = fixture(scratch)
    acceptance = {
        "schema_version": "1",
        "acceptance_id": "synthetic-acceptance",
        "frozen_at": "2026-01-01T00:00:00Z",
        "metric": "exact_count_rate",
        "comparator": "gte",
        "threshold": 0.5,
        "unit": "images",
        "dataset_sha256": "0" * 64,
        "model_or_pipeline": "synthetic",
        "confirmed_by": "self-check",
    }
    write_json(scratch / "acceptance.json", acceptance)
    write_json(scratch / "ledger.jsonl", {"event": "synthetic context, not a freeze claim"})
    args.extend(["--acceptance", str(scratch / "acceptance.json"), "--ledger", str(scratch / "ledger.jsonl")])
    run(args)
    folder = packed(scratch)
    assert (folder / "acceptance.json").is_file() and (folder / "ledger.jsonl").is_file()
    run([sys.executable, str(SCRIPT), "verify", str(folder)])
    args[args.index("--out-root") + 1] = str(scratch / "refused")
    args[args.index("--threshold") + 1] = "0.9"
    run(args, False)
    assert not (scratch / "refused").exists()


def main() -> int:
    """Run all controlled cases under temporary directories and print one final OK line."""
    checks = (
        check_tasks,
        check_dataset_refusals,
        check_content_refusals,
        check_scorer_refusal,
        check_numbering_and_masking,
        check_no_verdict,
        check_optional_inputs,
    )
    with tempfile.TemporaryDirectory(prefix="golden-run-check-") as temporary:
        for number, check in enumerate(checks):
            check(Path(temporary) / str(number))
            print(f"OK {check.__name__}")
    print("OK package_golden_run: offline packing, redaction, scoring, and verification")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
