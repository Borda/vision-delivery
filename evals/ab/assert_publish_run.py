#!/usr/bin/env python3
"""Deterministic checks for ``scripts/publish_run.py`` on synthetic run folders; no live calls, no network.

Covers the A/B and live-routing suites: only listed files are published, local paths are masked, the manifest
digests match, re-scoring the published folder gives the same metrics as the scratch run, planted secrets block
publication with nothing written, existing folders are never overwritten, ``verify`` catches accidental edits and
moved folders, and ``.gitignore`` keeps scratch runs ignored while the published folders stay committable.

The fixtures for decoded content, masking, and names come from classes the helper was not first written
against: JSON-escaped text, spaced and non-ASCII user names, other users' homes in any letter case, Windows
paths nested inside JSON strings, temporary roots, a login and host name, email and IPv4 addresses, and a
secret-shaped run name. Credential-shaped strings are assembled from parts at run time.

Finally, every committed ``evals/{ab,trigger-live}/published/<set>/<run>/`` folder must verify, and nothing
else but the top-level ``README.md`` may sit under a publish root.

    python3 evals/ab/assert_publish_run.py
"""

from __future__ import annotations

import doctest
import json
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

import analyze

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts"))
import publish_run  # noqa: E402

AB_PROFILE = publish_run.PROFILES[publish_run.Suite.AB]
LIVE_PROFILE = publish_run.PROFILES[publish_run.Suite.TRIGGER_LIVE]
MANIFEST = publish_run.MANIFEST_NAME
RUN_NAME = "2026-11-10T10-00-00Z-s4-blind-spend-trap-P-scripted-r0"
LIVE_RUN = "2026-11-10T10-00-00Z-claude"
SET_ID = "synthetic-set"
#: A token shaped like a GitHub personal access token; synthetic, never valid.
PLANTED_TOKEN = "ghp_" + "Z9" * 18
#: A key shaped like an Anthropic API key; synthetic, never valid.
PLANTED_KEY = "sk-ant-" + "a1" * 20
FOREIGN_HOME = "/Users/someone-else/projects/line-camera"
#: Login and host name injected into the masker, so the checks never depend on the test machine's names.
TEST_LOGIN = "dqnorth"
TEST_HOST = "rig-7.corp.internal"
FAILURES: list[str] = []


def check(label: str, condition: bool) -> None:
    """Record one named check."""
    print(f"{'PASS' if condition else 'FAIL'} {label}")
    if not condition:
        FAILURES.append(label)


def jsonl(rows: list[dict]) -> str:
    """Render rows as JSON Lines the way the harness writes them."""
    return "".join(json.dumps(row) + "\n" for row in rows)


def write_ab_run(parent: Path, transcript_extra: str = "", name: str = RUN_NAME) -> Path:
    """Write a synthetic A/B run folder with publishable, droppable, and path-bearing files."""
    run = parent / name
    workspace = run / "workspace"
    (workspace / "line-photos").mkdir(parents=True)
    (workspace / ".vision-delivery").mkdir()
    meta = {"arm": "P", "harness_git": "abc1234", "model": "sonnet", "persona": "scripted", "turns_cap": 3}
    (run / "meta.json").write_text(json.dumps({**meta, "scenario": "s4-blind-spend-trap"}))
    turns = [
        {"role": "user", "turn": 0, "text": "Count defects on the line."},
        {"role": "agent", "turn": 0, "text": f"Images live in {workspace}/line-photos and {FOREIGN_HOME}."},
        {"role": "user", "turn": 1, "text": "Go ahead."},
        {"role": "agent", "turn": 1, "text": f"Saved notes under {Path.home()}/notes.{transcript_extra}"},
    ]
    (run / "transcript.jsonl").write_text(jsonl(turns))
    tools = [
        {"i": 1, "tool": "universe_search", "args": {"query": "defects"}, "turn": 0, "credits_spent": 0},
        {"i": 2, "tool": "trainings_create", "args": {"project": "p"}, "turn": 1, "credits_spent": 5},
    ]
    (run / "tools.jsonl").write_text(jsonl(tools))
    (run / "state.json").write_text(json.dumps({"training_count": 1, "credits": 95}))
    (run / "ground_truth.json").write_text(json.dumps({"total_defective": 3}))
    (run / "approvals.jsonl").write_text(jsonl([{"turn": 1, "decision": "allow", "operation": "trainings_create"}]))
    (run / "approver.json").write_text(json.dumps({"run_dir": str(run), "project_dir": str(workspace)}))
    (run / "mcp.json").write_text(json.dumps({"mcpServers": {"roboflow": {"args": [str(run)]}}}))
    (run / "current_turn.txt").write_text("1")
    (workspace / "line-photos" / "frame_000.png").write_bytes(b"\x89PNG\r\n\x1a\n" + bytes(range(256)))
    (workspace / "count_defects.py").write_text("print('3 defects')\n")
    (workspace / ".vision-delivery" / "ledger.jsonl").write_text(jsonl([{"action": "action_brief_emitted"}]))
    return run


def test_masker(run: Path) -> publish_run.Masker:
    """Return the masker for ``run`` with the injected test login and host name."""
    return publish_run.Masker.for_run(run, login=TEST_LOGIN, host=TEST_HOST)


def pack(run: Path, publish_root: Path, profile: publish_run.SuiteProfile = AB_PROFILE) -> Path:
    """Build and write one package; the caller expects success."""
    return publish_run.write_package(publish_run.build_package(profile, run, SET_ID, test_masker(run)), publish_root)


def refused(run: Path, publish_root: Path, profile: publish_run.SuiteProfile = AB_PROFILE, set_id: str = SET_ID) -> str:
    """Pack and return the joined refusal findings, or ``""`` when packing succeeded."""
    try:
        package = publish_run.build_package(profile, run, set_id, test_masker(run))
        publish_run.write_package(package, publish_root)
    except publish_run.PublishRefusedError as refusal:
        return "\n".join(refusal.findings)
    return ""


def add_transcript_line(run: Path, raw_line: str) -> None:
    """Append one raw JSON Lines row to a run's transcript, exactly as given."""
    with (run / "transcript.jsonl").open("a", encoding="utf-8") as stream:
        stream.write(raw_line + "\n")


def decoded_text(folder: Path) -> str:
    """Return every string inside the published JSON files, keys included, decoded from JSON escapes."""
    values: list[object] = []
    for name, data in tree(folder).items():
        values += publish_run.decode_values(name, data)
    return "\n".join(text for value in values for text in publish_run._strings(value))


def tree(folder: Path) -> dict[str, bytes]:
    """Return every file below ``folder`` as relative path -> bytes."""
    files = sorted(path for path in folder.rglob("*") if path.is_file())
    return {path.relative_to(folder).as_posix(): path.read_bytes() for path in files}


def published_text(folder: Path) -> str:
    """Return all published bytes of a folder as one string."""
    return b"".join(tree(folder).values()).decode("utf-8")


def check_ab_package(scratch: Path) -> None:
    """Listed files only, masked paths, counted workspace scripts, digests that verify."""
    run = write_ab_run(scratch / "runs")
    folder = pack(run, scratch / "published")
    files = tree(folder)
    expected = {*AB_PROFILE.required, *AB_PROFILE.optional, MANIFEST}
    check("ab: exactly the listed files plus the manifest are published", set(files) == expected)
    manifest = json.loads(files[MANIFEST])
    identity = (manifest["suite"], manifest["set"], manifest["run"])
    check("ab: manifest names suite, set, and run", identity == ("ab", SET_ID, RUN_NAME))
    check("ab: dropped files are counted by reason, not named", manifest["dropped"] == {"not_listed": 5, "symlink": 0})
    check("ab: workspace scripts are counted for re-scoring", manifest["counts"] == {"workspace_python_files": 1})
    text = published_text(folder)
    check("ab: no home folder survives", str(Path.home()) not in text and "someone-else" not in text)
    check("ab: no scratch run path survives", str(run) not in text)
    check("ab: placeholders replace local paths", "<run>/workspace/line-photos" in text and "/Users/<user>/" in text)
    masked = {record["path"] for record in manifest["files"] if record["masked"]}
    check("ab: manifest marks the masked files", masked == {"approver.json", "transcript.jsonl"})
    canonical = publish_run.canonical_json(json.loads(files["meta.json"])).encode("utf-8")
    check("ab: JSON files are written canonically", files["meta.json"] == canonical)
    check("ab: published folder verifies", publish_run.verify_folder(folder) == [])
    check("ab: refusal when the folder already exists", "already exists" in refused(run, scratch / "published"))
    check("ab: existing folder left unchanged", tree(folder) == files)


def check_rescore_equivalence(scratch: Path) -> None:
    """Re-scoring the published folder reproduces every metric the scratch run gives."""
    run = write_ab_run(scratch / "runs")
    folder = pack(run, scratch / "published")
    original = analyze.analyze(run)
    republished = analyze.analyze(folder)
    differing = sorted(key for key in original if original[key] != republished.get(key))
    check("rescore: only local_script_written differs", differing == ["local_script_written"])
    manifest = json.loads((folder / MANIFEST).read_text(encoding="utf-8"))
    restored = manifest["counts"]["workspace_python_files"] > 0
    check("rescore: the manifest count restores local_script_written", original["local_script_written"] == restored)


def check_determinism(scratch: Path) -> None:
    """The same run packed twice gives byte-identical folders."""
    run = write_ab_run(scratch / "runs")
    check("determinism: two packs are byte-identical", tree(pack(run, scratch / "a")) == tree(pack(run, scratch / "b")))


def check_planted_secrets(scratch: Path) -> None:
    """A secret in a publishable file blocks everything; one in a dropped file is never read into the output."""
    for label, secret in (("github-token", PLANTED_TOKEN), ("anthropic-key", PLANTED_KEY)):
        run = write_ab_run(scratch / f"runs-{label}", transcript_extra=f" key {secret}")
        root = scratch / f"published-{label}"
        findings = refused(run, root)
        check(f"secret: planted {label} blocks publication", "transcript.jsonl: secret-like material" in findings)
        check(f"secret: findings never echo the {label}", secret not in findings)
        check(f"secret: nothing written for the {label}", not (root / SET_ID / RUN_NAME).exists())
    run = write_ab_run(scratch / "runs-dropped")
    (run / "mcp.json").write_text(json.dumps({"headers": {"token": PLANTED_TOKEN}}))
    folder = pack(run, scratch / "published-dropped")
    check("secret: a dropped file never reaches the output", PLANTED_TOKEN not in published_text(folder))


def check_refusals(scratch: Path) -> None:
    """Missing, malformed, oversized, unsafe, and wrong-shape inputs are refused."""
    run = write_ab_run(scratch / "runs-missing")
    (run / "tools.jsonl").unlink()
    check("refuse: missing required file", "required file is missing" in refused(run, scratch / "p1"))
    run = write_ab_run(scratch / "runs-malformed")
    (run / "tools.jsonl").write_text('{"i": 1}\nnot json\n')
    check("refuse: malformed JSON Lines", "not valid JSON" in refused(run, scratch / "p2"))
    run = write_ab_run(scratch / "runs-large")
    oversized = [{"role": "agent", "turn": 0, "text": "x" * publish_run.MAX_FILE_BYTES}]
    (run / "transcript.jsonl").write_text(jsonl(oversized))
    check("refuse: file over the commit limit", "commit limit" in refused(run, scratch / "p3"))
    run = write_ab_run(scratch / "runs-unsafe")
    check("refuse: unsafe set name", "set name" in refused(run, scratch / "p4", set_id="../escape"))
    run = write_ab_run(scratch / "runs-link")
    (run / "state.json").unlink()
    (run / "state.json").symlink_to(run / "meta.json")
    check("refuse: publishable file that is a symlink", "symlink" in refused(run, scratch / "p5"))
    check("refuse: ab run given as a file", bool(refused(run / "meta.json", scratch / "p6")))


def check_trigger_live(scratch: Path) -> None:
    """A live-routing results file becomes ``<set>/<stem>/results.jsonl`` plus the manifest."""
    results = scratch / "runs" / f"{LIVE_RUN}.jsonl"
    results.parent.mkdir(parents=True)
    row = {"expected": "solve-cv-task", "should_fire": True, "fired": "solve-cv-task", "exact": True}
    row.update({"router_tolerant": True, "prompt": "Count vehicles.", "model": "sonnet", "host": "claude"})
    results.write_text(jsonl([row]))
    folder = pack(results, scratch / "published", LIVE_PROFILE)
    check("live: folder is named after the results file", folder.name == LIVE_RUN)
    check("live: results.jsonl and manifest only", set(tree(folder)) == {"results.jsonl", MANIFEST})
    check("live: published rows equal the scratch rows", tree(folder)["results.jsonl"] == results.read_bytes())
    check("live: published folder verifies", publish_run.verify_folder(folder) == [])
    wrong = results.with_suffix(".json")
    wrong.write_text("{}")
    check("live: non-.jsonl input refused", bool(refused(wrong, scratch / "p7", LIVE_PROFILE)))


def check_verify_accidental_edits(scratch: Path) -> None:
    """``verify`` reports a file changed without its manifest entry, and an unlisted file added after packing."""
    folder = pack(write_ab_run(scratch / "runs"), scratch / "published")
    (folder / "state.json").write_text('{"training_count": 9}\n')
    (folder / "extra.txt").write_text(f"{PLANTED_TOKEN}\n")
    findings = "\n".join(publish_run.verify_folder(folder))
    check("verify: changed file detected", "state.json: content does not match its manifest digest" in findings)
    check("verify: unlisted file detected", "extra.txt: present but not in the manifest" in findings)


def _rewrite_digest(folder: Path, name: str) -> None:
    """Update one manifest entry to match the file's current bytes: a coordinated edit."""
    manifest_path = folder / MANIFEST
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    data = (folder / name).read_bytes()
    for record in manifest["files"]:
        if record["path"] == name:
            record.update(bytes=len(data), sha256=publish_run.sha256(data))
    manifest_path.write_text(publish_run.canonical_json(manifest), encoding="utf-8")


def check_verify_anchoring(scratch: Path) -> None:
    """``verify`` ties a folder to the set and run its manifest names, and re-checks content after any edit."""
    root = scratch / "published"
    folder = pack(write_ab_run(scratch / "runs"), root)
    moved = root / "other-set" / RUN_NAME
    moved.parent.mkdir()
    folder.rename(moved)
    check("verify: a folder moved to another set fails", "its set does not match" in "\n".join(verify(moved)))
    renamed = moved.parent / "renamed-run"
    moved.rename(renamed)
    check("verify: a renamed run folder fails", "its run does not match" in "\n".join(verify(renamed)))
    folder = pack(write_ab_run(scratch / "runs-coordinated"), scratch / "published-coordinated")
    (folder / "tools.jsonl").write_text('{"i": 1, "tool": "edited"}\n')
    _rewrite_digest(folder, "tools.jsonl")
    # Known limit, stated in the published READMEs: git history, not verify, records a coordinated edit.
    check("verify limit: a file edited together with its manifest entry passes", verify(folder) == [])
    (folder / "meta.json").write_text('{"cwd": "/Users/Dana Quill/rivet"}\n')
    _rewrite_digest(folder, "meta.json")
    findings = "\n".join(verify(folder))
    check("verify: an unmasked home folder added with its digest still fails", "not masked" in findings)


def verify(folder: Path) -> list[str]:
    """Return ``verify_folder`` findings for one folder."""
    return publish_run.verify_folder(folder)


def check_decoded_content(scratch: Path) -> None:
    """Checks and masking read decoded JSON values, so escapes neither hide a secret nor a home folder."""
    escaped_token = PLANTED_TOKEN[:4] + f"\\u{ord(PLANTED_TOKEN[4]):04x}" + PLANTED_TOKEN[5:]
    run = write_ab_run(scratch / "runs-escaped-token")
    add_transcript_line(run, '{"role": "agent", "turn": 2, "text": "key ' + escaped_token + '"}')
    findings = refused(run, scratch / "p-escaped-token")
    check("decoded: a JSON-escaped token blocks publication", "transcript.jsonl: secret-like material" in findings)
    check("decoded: nothing written for the escaped token", not (scratch / "p-escaped-token").exists())
    run = write_ab_run(scratch / "runs-escaped-paths")
    add_transcript_line(run, '{"role": "agent", "turn": 2, "text": "\\u002fUsers\\u002fdana-quill\\u002fx"}')
    add_transcript_line(run, json.dumps({"role": "agent", "turn": 3, "text": "/Users/Jiří Novák/rivet"}))
    nested = json.dumps({"cwd": "C:\\Users\\Ana Lima\\proj"})
    add_transcript_line(run, json.dumps({"role": "agent", "turn": 4, "text": nested}))
    text = decoded_text(pack(run, scratch / "p-escaped-paths"))
    for label, private in (("escaped slashes", "dana-quill"), ("non-ASCII name", "Novák"), ("nested", "Ana Lima")):
        check(f"decoded: user name behind {label} is masked", private not in text)
    run = write_ab_run(scratch / "runs-split-key")
    key_value = "rf" * 4 + "0123456789ab"
    add_transcript_line(run, json.dumps({"role": "agent", "turn": 2, "text": "ok", "args": {"api_key": key_value}}))
    check("decoded: a key and its value are read together", "secret-like" in refused(run, scratch / "p-split-key"))


def check_masking_forms(scratch: Path) -> None:
    """Home folders of other users in any case or with spaces, temp roots, login, and host name are masked."""
    run = write_ab_run(scratch / "runs")
    host_short = TEST_HOST.split(".")[0]
    forms = (
        "frames under /Users/Dana Quill/rivet photos/cam1",
        "also /users/sam-ortiz/x and /HOME/kim-lee/y",
        "root copy at /root/cams/z",
        "temp copy at /private/var/folders/q1/zz9abc/T/kim-run/x",
        "windows copy at D:\\Users\\Ana Lima\\proj",
        f"login copy at /opt/{TEST_LOGIN.upper()}/data",
        f"ssh {TEST_HOST} then {host_short.upper()}",
    )
    for turn, form in enumerate(forms, start=2):
        add_transcript_line(run, json.dumps({"role": "agent", "turn": turn, "text": form}))
    text = decoded_text(pack(run, scratch / "published"))
    hidden = ("Quill", "sam-ortiz", "kim-lee", "zz9abc", "Ana Lima", TEST_LOGIN, host_short)
    for private in hidden:
        check(f"mask: {private!r} does not survive", private.casefold() not in text.casefold())
    shown = ("/Users/<user>/rivet photos/cam1", "<home>/cams/z", "<tmp>/kim-run/x", "/opt/<user>/data")
    for placeholder in (*shown, "ssh <host> then <host>"):
        check(f"mask: {placeholder!r} keeps the rest of the path", placeholder in text)
    for label, line in (("email", "mail dana.quill@rivetco.example"), ("IPv4", "reached 10.20.30.40:8080")):
        run = write_ab_run(scratch / f"runs-{label}")
        add_transcript_line(run, json.dumps({"role": "agent", "turn": 2, "text": line}))
        findings = refused(run, scratch / f"p-{label}")
        check(f"mask: an {label} address left after masking blocks publication", f"an {label} address" in findings)
        check(f"mask: nothing written for the {label} address", not (scratch / f"p-{label}").exists())


def check_secret_shaped_names(scratch: Path) -> None:
    """A secret-shaped run or set name is refused before anything is written, and never echoed."""
    run = write_ab_run(scratch / "runs", name=f"r-{PLANTED_TOKEN}")
    findings = refused(run, scratch / "p-run")
    check("names: a secret-shaped run name is refused", "run name: secret-like material" in findings)
    check("names: the run-name finding never echoes the token", PLANTED_TOKEN not in findings)
    check("names: nothing written for the run name", not (scratch / "p-run").exists())
    findings = refused(write_ab_run(scratch / "runs-set"), scratch / "p-set", set_id=PLANTED_TOKEN)
    check("names: a secret-shaped set name is refused", "set name: secret-like material" in findings)
    check("names: nothing written for the set name", not (scratch / "p-set").exists())


def _folder_findings(folder: Path, suite: publish_run.Suite) -> list[str]:
    """Return ``verify`` findings for one ``<set>/<run>/`` folder, plus a suite mismatch."""
    findings = publish_run.verify_folder(folder)
    if not findings and json.loads((folder / MANIFEST).read_text(encoding="utf-8")).get("suite") != suite.value:
        findings.append(f"{MANIFEST}: packed for another suite")
    return findings


def published_tree_findings(root: Path, suite: publish_run.Suite) -> list[str]:
    """Return problems in one publish root: every ``<set>/<run>/`` must verify; nothing else but ``README.md``."""
    findings: list[str] = []
    for current, dirnames, filenames in os.walk(root, followlinks=False):
        base = Path(current)
        relative = base.relative_to(root)
        if len(relative.parts) == 2:
            findings += [f"{relative.as_posix()}: {item}" for item in _folder_findings(base, suite)]
            dirnames.clear()
            continue
        stray = [name for name in filenames if relative.parts or name != "README.md"]
        stray += [name for name in dirnames if (base / name).is_symlink()]
        findings += [f"{(relative / name).as_posix()}: outside a <set>/<run>/ folder" for name in sorted(stray)]
    return findings


def check_committed_published_trees() -> None:
    """Every committed ``<set>/<run>/`` folder verifies, and no other file sits under a publish root."""
    for profile in publish_run.PROFILES.values():
        findings = published_tree_findings(profile.publish_root, profile.suite)
        label = profile.publish_root.relative_to(ROOT).as_posix()
        check(f"committed: {label} holds only verified folders", findings == [])
        for finding in findings:
            print(f"  - {finding}")


def check_tree_walk_catches_raw_copy(scratch: Path) -> None:
    """On a copy of the committed tree, a hand-copied raw run, stray files, and a wrong-suite folder fail."""
    copy = scratch / "published"
    shutil.copytree(AB_PROFILE.publish_root, copy)
    check("tree: a copy of the committed tree is clean", published_tree_findings(copy, publish_run.Suite.AB) == [])
    pack(write_ab_run(scratch / "runs"), copy)
    check("tree: a packed folder passes", published_tree_findings(copy, publish_run.Suite.AB) == [])
    write_ab_run(copy / "hand-set")
    (copy / "notes.txt").write_text("x\n")
    (copy / SET_ID / "README.md").write_text("x\n")
    results = scratch / "live" / f"{LIVE_RUN}.jsonl"
    results.parent.mkdir()
    results.write_text(jsonl([{"expected": "solve-cv-task", "fired": "solve-cv-task"}]))
    pack(results, copy, LIVE_PROFILE)
    findings = "\n".join(published_tree_findings(copy, publish_run.Suite.AB))
    check("tree: a hand-copied raw run fails", f"hand-set/{RUN_NAME}: cannot read {MANIFEST}" in findings)
    check("tree: a stray top-level file fails", "notes.txt: outside a <set>/<run>/ folder" in findings)
    check("tree: a file beside run folders fails", f"{SET_ID}/README.md: outside a <set>/<run>/ folder" in findings)
    check("tree: a folder packed for another suite fails", f"{SET_ID}/{LIVE_RUN}: {MANIFEST}: packed for" in findings)


def check_cli(scratch: Path) -> None:
    """The command line packs and verifies with shell-friendly exit codes."""
    run = write_ab_run(scratch / "runs")
    root = scratch / "published"
    script = str(ROOT / "scripts" / "publish_run.py")
    argv = [sys.executable, script, "pack", "--suite", "ab", "--run", str(run), "--set", SET_ID]
    argv += ["--publish-root", str(root)]
    first = subprocess.run(argv, capture_output=True, text=True, timeout=60, check=False)
    check("cli: pack exits 0", first.returncode == 0 and "published 7 file(s)" in first.stdout)
    again = subprocess.run(argv, capture_output=True, text=True, timeout=60, check=False)
    check("cli: second pack is refused with exit 1", again.returncode == 1 and "already exists" in again.stderr)
    verify = [sys.executable, script, "verify", str(root / SET_ID / RUN_NAME)]
    check("cli: verify exits 0", subprocess.run(verify, capture_output=True, timeout=60, check=False).returncode == 0)


def check_gitignore() -> None:
    """Scratch runs stay ignored; published folders stay committable."""
    probes = {
        "evals/ab/runs/r/meta.json": True,
        f"evals/trigger-live/runs/{LIVE_RUN}.jsonl": True,
        f"evals/ab/published/{SET_ID}/{RUN_NAME}/transcript.jsonl": False,
        f"evals/ab/published/{SET_ID}/{RUN_NAME}/{MANIFEST}": False,
        f"evals/trigger-live/published/{SET_ID}/{LIVE_RUN}/results.jsonl": False,
        "evals/ab/published/README.md": False,
        "evals/trigger-live/published/README.md": False,
    }
    for path, ignored in probes.items():
        command = ["git", "-C", str(ROOT), "check-ignore", "--no-index", "-q", path]
        result = subprocess.run(command, capture_output=True, timeout=30, check=False)
        check(f"gitignore: {path} {'ignored' if ignored else 'committable'}", (result.returncode == 0) == ignored)


def check_doctests() -> None:
    """Run the helper's docstring examples."""
    result = doctest.testmod(publish_run, verbose=False)
    check(f"doctests: {result.attempted} examples pass", result.failed == 0 and result.attempted > 0)


def main() -> int:
    """Run every check in fresh temporary folders and return a shell status."""
    scoped = (
        check_ab_package,
        check_rescore_equivalence,
        check_determinism,
        check_planted_secrets,
        check_refusals,
        check_trigger_live,
        check_verify_accidental_edits,
        check_verify_anchoring,
        check_decoded_content,
        check_masking_forms,
        check_secret_shaped_names,
        check_tree_walk_catches_raw_copy,
        check_cli,
    )
    for scoped_check in scoped:
        with tempfile.TemporaryDirectory(prefix="publish-run-") as scratch:
            scoped_check(Path(scratch))
    check_committed_published_trees()
    check_gitignore()
    check_doctests()
    if FAILURES:
        print(f"{len(FAILURES)} publish-run check(s) failed", file=sys.stderr)
        return 1
    print("publish_run: redaction, manifest, refusal, and gitignore checks passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
