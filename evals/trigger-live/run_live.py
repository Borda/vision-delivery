#!/usr/bin/env python3
"""Live trigger eval: feed labeled prompts to a host session and assert which skill fires.

Unlike ``evals/trigger/run.py`` (a description lint — vocabulary coverage only),
this harness measures actual routing. Claude runs from ``--plugin-dir``; Codex
runs through a preinstalled plugin in ``CODEX_HOME``. The fired skill is read
from each host's JSON transcript using the same namespaced-skill pattern.
Computes per-skill accuracy and a confusion listing, plus a router-tolerance
view (``solve-cv-task`` counts as correct for modality prompts).

Cost: one model call per case. Default samples 1 should_fire case per skill;
``--all`` runs every case. NOT wired into ``make eval`` — run on demand:

    python3 evals/trigger-live/run_live.py --host claude [--all] [--model sonnet]
    CODEX_HOME=/isolated/home python3 evals/trigger-live/run_live.py --host codex

Results land in ``evals/trigger-live/runs/<UTC-timestamp>.jsonl``, which is gitignored scratch.

For dual-plugin routing, add repeatable ``--with-plugin-dir <path>`` flags on Claude;
``--dual-cases`` selects the six cross-plugin prompts. A front-door collision means
a front-door prompt fired something other than Sentinel, including no plugin.
Dual numbers stay unpublished until packed with ``scripts/publish_run.py pack --suite trigger-live``.

No published number without a committed artifact folder: before a routing number goes into a docs page, README,
or changelog, pack its results file with
``python3 scripts/publish_run.py pack --suite trigger-live --run <results file> --set <set-id>``, commit
``evals/trigger-live/published/<set-id>/``, and cite that folder next to the number
(``evals/trigger-live/published/README.md`` says what is kept). The routing numbers published before this rule,
including the run summarized in ``docs/support-and-scope.md``, predate it: their results were never committed and
cannot be re-scored.
"""

from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
import tempfile
from collections.abc import Iterator
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
CASES_DIR = ROOT / "evals" / "trigger"
RUNS_DIR = Path(__file__).resolve().parent / "runs"
DUAL_CASES = Path(__file__).resolve().parent / "dual-cases.json"
SKILL_RE = re.compile(r'"skill"\s*:\s*"(?:sentinel:)?([A-Za-z0-9_-]+)"')
NAMESPACED_SKILL_RE = re.compile(r"(?:(?P<plugin>[A-Za-z0-9_-]+):)?(?P<skill>[A-Za-z0-9_-]+)")
PER_CASE_TIMEOUT_S = 180
ROUTER = "solve-cv-task"


def fire_prompt(prompt: str, model: str | None, host: str) -> str | None:
    """Run one headless routing turn; return the fired skill name or None.

    Runs in a fresh empty temp dir — with the repo as cwd, the session can
    find real artifacts (old benchmark CSVs, eval files) and answer the prompt
    from disk instead of routing (verified live 2026-07-10).

    Examples:
        >>> callable(fire_prompt)
        True
    """
    transcript = _run_prompt(_prompt_command(prompt, model, host))
    m = SKILL_RE.search(transcript or "")
    return m.group(1) if m else None


def _prompt_command(prompt: str, model: str | None, host: str, plugin_dirs: tuple[Path, ...] = ()) -> list[str]:
    """Build host arguments, loading Sentinel before any additional Claude plugins."""
    if host == "claude":
        cmd = ["claude", "--plugin-dir", str(ROOT)]
        for directory in plugin_dirs:
            cmd.extend(["--plugin-dir", str(directory)])
        if model:
            cmd.extend(["--model", model])
        cmd.extend(
            [
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
        )
    else:
        cmd = [
            "codex",
            "exec",
            "--json",
            "--ephemeral",
            "--sandbox",
            "read-only",
            "--cd",
            "{cwd}",
            prompt,
        ]
        if model:
            cmd[-1:-1] = ["--model", model]
    return cmd


def _run_prompt(cmd: list[str]) -> str | None:
    """Capture one routing transcript in an isolated temporary working directory."""
    with tempfile.TemporaryDirectory(prefix="trigger-live-") as tmp:
        try:
            resolved_cmd = [part.replace("{cwd}", tmp) for part in cmd]
            res = subprocess.run(
                resolved_cmd,
                capture_output=True,
                text=True,
                timeout=PER_CASE_TIMEOUT_S,
                cwd=tmp,
                stdin=subprocess.DEVNULL,
            )
        except subprocess.TimeoutExpired:
            return None
    return res.stdout


def _skill_values(value: object) -> Iterator[str]:
    """Walk decoded events in transcript order, ignoring skill-like text inside strings."""
    if isinstance(value, dict):
        for key, item in value.items():
            if key == "skill" and isinstance(item, str):
                yield item
            else:
                yield from _skill_values(item)
    elif isinstance(value, list):
        for item in value:
            yield from _skill_values(item)


def parse_fired_skill(transcript: str) -> tuple[str | None, str | None]:
    """Return the first skill field's plugin and name from stream-JSON events.

    Bare names retain a ``None`` plugin; absent skills return ``(None, None)``.
    Malformed non-JSON status lines do not count as routing evidence.
    """
    for line in transcript.splitlines():
        try:
            event = json.loads(line)
        except json.JSONDecodeError:
            continue
        for value in _skill_values(event):
            match = NAMESPACED_SKILL_RE.fullmatch(value)
            if match:
                return match.group("plugin"), match.group("skill")
    return None, None


def _validate_dual_case(case: object, seen: set[str]) -> dict[str, str]:
    """Validate the exact case schema before any model calls are made."""
    if not isinstance(case, dict) or set(case) != {"id", "prompt", "expected_plugin"}:
        raise ValueError("each dual case requires exactly id, prompt, expected_plugin (no extra keys)")
    if any(not isinstance(value, str) or not value.strip() for value in case.values()):
        raise ValueError("dual case id, prompt, expected_plugin must be non-empty strings")
    if case["expected_plugin"] not in {"sentinel", "roboflow", "front-door"}:
        raise ValueError("expected_plugin must be sentinel, roboflow, or front-door")
    if case["id"] in seen:
        raise ValueError(f"duplicate dual case id: {case['id']}")
    seen.add(case["id"])
    return case


def load_dual_cases(path: Path | None = None) -> list[dict[str, str]]:
    """Load strictly validated dual cases; raise a reason on invalid JSON or schema."""
    data = json.loads((path or DUAL_CASES).read_text(encoding="utf-8"))
    if not isinstance(data, dict) or set(data) != {"cases"}:
        raise ValueError("dual cases file requires exactly the cases key (no extra keys)")
    if not isinstance(data["cases"], list) or not data["cases"]:
        raise ValueError("dual cases must be a non-empty list")
    seen: set[str] = set()
    return [_validate_dual_case(case, seen) for case in data["cases"]]


def load_cases(only_skill: str | None, negatives: bool = False) -> list[tuple[str, str, bool]]:
    """Return (skill, prompt, should_fire) triples from the trigger case files.

    Negative cases (``should_not_fire``) pass when the named skill does NOT
    fire — another skill or no skill are both fine. They feed the per-skill
    false-positive count for precision.
    """
    triples: list[tuple[str, str, bool]] = []
    for f in sorted(CASES_DIR.glob("*.cases.json")):
        skill = f.stem.replace(".cases", "")
        if only_skill and skill != only_skill:
            continue
        data = json.loads(f.read_text())
        for case in data.get("should_fire", []):
            prompt = case["prompt"]
            if prompt.startswith("/"):
                continue  # slash-command entry is exercised elsewhere
            triples.append((skill, prompt, True))
        if negatives:
            for case in data.get("should_not_fire", []):
                prompt = case["prompt"]
                if prompt.startswith("/"):
                    continue
                triples.append((skill, prompt, False))
    return triples


def _parse_args() -> argparse.Namespace:
    """Parse run options and refuse unsupported plugin combinations before execution."""
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--all", action="store_true", help="Run every case (default: 1 per skill).")
    ap.add_argument(
        "--model",
        default=None,
        help="Host model override (Claude defaults to sonnet; Codex keeps its configured default).",
    )
    ap.add_argument("--skill", default=None, help="Restrict to one skill's cases.")
    ap.add_argument(
        "--negatives",
        action="store_true",
        help="Also run should_not_fire cases (per-skill false positives).",
    )
    ap.add_argument(
        "--host",
        choices=("claude", "codex"),
        default="claude",
        help="Host runner; Codex requires Sentinel preinstalled in CODEX_HOME.",
    )
    ap.add_argument("--out-tag", default=None, help="Suffix for the results file.")
    ap.add_argument(
        "--with-plugin-dir",
        type=Path,
        action="append",
        default=[],
        help="Additional Claude plugin directory (repeatable, loaded after Sentinel).",
    )
    ap.add_argument("--dual-cases", action="store_true", help="Run the six dual-plugin cases instead of trigger cases.")
    args = ap.parse_args()
    if args.with_plugin_dir and args.host == "codex":
        ap.error("--with-plugin-dir is supported only with --host claude, not codex")
    if args.dual_cases and not args.with_plugin_dir:
        ap.error("--dual-cases requires at least one --with-plugin-dir")
    args.with_plugin_dir = [directory.resolve() for directory in args.with_plugin_dir]
    return args


def _select_cases(args: argparse.Namespace) -> list[tuple[str, str, bool]]:
    """Retain the legacy sampling and negative-case selection for trigger runs."""
    triples = load_cases(args.skill, negatives=args.negatives)
    if not args.all:
        seen: set[str] = set()
        sampled: list[tuple[str, str, bool]] = []
        for skill, prompt, positive in triples:
            if positive and skill not in seen:
                sampled.append((skill, prompt, positive))
                seen.add(skill)
        triples = sampled
    return triples


def _run_single_cases(triples: list[tuple[str, str, bool]], model: str | None, host: str) -> list[dict]:
    """Run legacy cases with their original row fields and progress output."""
    rows = []
    for skill, prompt, positive in triples:
        fired = fire_prompt(prompt, model, host)
        if positive:
            ok_exact = fired == skill
            ok_tolerant = ok_exact or (fired == ROUTER and skill != ROUTER)
            icon = "=" if ok_exact else ("~" if ok_tolerant else "x")
        else:
            ok_exact = ok_tolerant = fired != skill  # pass = named skill silent
            icon = "-" if ok_exact else "F"
        row = {
            "expected": skill,
            "should_fire": positive,
            "fired": fired,
            "exact": ok_exact,
            "router_tolerant": ok_tolerant,
            "prompt": prompt,
            "model": model,
            "host": host,
        }
        rows.append(row)
        print(f"  {icon} {'+' if positive else '-'} expected={skill:<26} fired={fired}")
    return rows


def _print_precision_recall(rows: list[dict]) -> None:
    """Print the legacy per-skill precision and recall table."""
    # Per-skill precision/recall: TP = positive fired exactly; FN = positive
    # fired other/none; FP = negative where the named skill fired anyway.
    skills = sorted({r["expected"] for r in rows})
    print("\nPer-skill precision/recall (exact, router not credited):")
    for s in skills:
        tp = sum(1 for r in rows if r["should_fire"] and r["expected"] == s and r["fired"] == s)
        fn = sum(1 for r in rows if r["should_fire"] and r["expected"] == s and r["fired"] != s)
        fp = sum(1 for r in rows if not r["should_fire"] and r["expected"] == s and r["fired"] == s)
        prec = tp / (tp + fp) if (tp + fp) else None
        rec = tp / (tp + fn) if (tp + fn) else None
        fmt = lambda v: "—" if v is None else f"{v:.2f}"  # noqa: E731
        print(f"  {s:<26} P={fmt(prec)} R={fmt(rec)} (tp={tp} fp={fp} fn={fn})")


def _single_summary(rows: list[dict], out_path: Path) -> int:
    """Print the original single-plugin summary and return its routing status."""
    total_pos = sum(r["should_fire"] for r in rows)
    exact = sum(r["exact"] for r in rows if r["should_fire"])
    tolerant = sum(r["router_tolerant"] for r in rows if r["should_fire"])
    if total_pos:
        print(f"\nRouting accuracy (positives): exact {exact}/{total_pos}, router-tolerant {tolerant}/{total_pos}")
    _print_precision_recall(rows)
    print(f"Results: {out_path}")
    misroutes = [r for r in rows if r["should_fire"] and not r["router_tolerant"]]
    false_fires = [r for r in rows if not r["should_fire"] and not r["exact"]]
    if misroutes:
        print("Misroutes (neither expected skill nor router fired):")
        for r in misroutes:
            print(f"  expected={r['expected']} fired={r['fired']} :: {r['prompt'][:70]}")
    if false_fires:
        print("False fires (skill fired on its should_not_fire prompt):")
        for r in false_fires:
            print(f"  skill={r['expected']} :: {r['prompt'][:70]}")
    return 0 if not (misroutes or false_fires) else 1


def _run_dual_cases(cases: list[dict[str, str]], model: str | None, args: argparse.Namespace) -> list[dict]:
    """Record plugin ownership separately from skill names for every dual prompt."""
    directories = tuple(args.with_plugin_dir)
    plugins = [directory.name for directory in (ROOT, *directories)]
    rows = []
    for case in cases:
        transcript = _run_prompt(_prompt_command(case["prompt"], model, args.host, directories))
        plugin, skill = parse_fired_skill(transcript or "")
        row = {
            **case,
            "fired_plugin": plugin,
            "fired_skill": skill,
            "plugins": plugins,
            "model": model,
            "host": args.host,
        }
        rows.append(row)
        print(f"  expected_plugin={case['expected_plugin']:<10} fired_plugin={plugin} fired_skill={skill}")
    return rows


def dual_summary(rows: list[dict]) -> dict:
    """Count plugin ownership by expectation and retain front-door collision prompts."""
    groups: dict[str, dict[str, int]] = {}
    collisions = []
    for row in rows:
        expected, fired = row["expected_plugin"], row["fired_plugin"]
        counts = groups.setdefault(expected, {"sentinel": 0, "other": 0, "none": 0})
        bucket = "none" if fired is None else ("sentinel" if fired == "sentinel" else "other")
        counts[bucket] += 1
        if expected == "front-door" and fired != "sentinel":
            collisions.append(row["prompt"])
    return {"groups": groups, "front_door_collisions": len(collisions), "collision_prompts": collisions}


def _dual_summary(rows: list[dict], out_path: Path) -> int:
    """Print dual measurements; only cross-routes between the two named plugins fail."""
    summary = dual_summary(rows)
    print("\nDual-plugin routing by expected_plugin:")
    for expected, counts in sorted(summary["groups"].items()):
        print(f"  {expected}: sentinel={counts['sentinel']} other={counts['other']} none={counts['none']}")
    print(f"front_door_collisions={summary['front_door_collisions']}")
    for prompt in summary["collision_prompts"]:
        print(f"  {prompt}")
    print(f"Results: {out_path}")
    return int(
        any(
            (r["expected_plugin"], r["fired_plugin"]) in {("sentinel", "roboflow"), ("roboflow", "sentinel")}
            for r in rows
        )
    )


def main() -> int:
    """Run the selected suite, persist rows, and report the appropriate routing summary."""
    args = _parse_args()
    model = args.model or ("sonnet" if args.host == "claude" else None)
    if model and "fable" in model.lower():
        sys.exit("live evals run sonnet or opus only — never fable (owner rule)")
    dual = bool(args.with_plugin_dir)
    if dual:
        try:
            cases = (
                load_dual_cases()
                if args.dual_cases
                else [{"prompt": prompt, "expected_plugin": "sentinel"} for _, prompt, _ in _select_cases(args)]
            )
        except (OSError, ValueError) as exc:
            sys.exit(f"invalid dual cases: {exc}")
        rows = _run_dual_cases(cases, model, args)
    else:
        rows = _run_single_cases(_select_cases(args), model, args.host)
    RUNS_DIR.mkdir(exist_ok=True)
    ts = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H-%M-%SZ")
    tag = args.out_tag or ("dual" if dual else args.host)
    out_path = RUNS_DIR / f"{ts}-{tag}.jsonl"
    with out_path.open("w") as fh:
        for row in rows:
            fh.write(json.dumps(row) + "\n")
    return _dual_summary(rows, out_path) if dual else _single_summary(rows, out_path)


if __name__ == "__main__":
    sys.exit(main())
