#!/usr/bin/env python3
"""Live trigger eval: feed labeled prompts to a headless plugin session, assert which skill fires.

Unlike ``evals/trigger/run.py`` (a description lint — vocabulary coverage only),
this harness measures actual routing: each prompt runs in ``claude --plugin-dir .``
with tools restricted to ``Skill`` and the fired skill is read from the Skill
tool_use event in the stream-json transcript. Computes per-skill accuracy and a
confusion listing, plus a router-tolerance view (``solve-cv-task`` counts as
correct for modality prompts — it is the intended dispatcher).

Cost: one model call per case. Default samples 1 should_fire case per skill;
``--all`` runs every case. NOT wired into ``make eval`` — run on demand:

    python3 evals/trigger-live/run_live.py [--all] [--model sonnet] [--skill NAME]

Results land in ``evals/trigger-live/runs/<UTC-timestamp>.jsonl``.
"""

from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
CASES_DIR = ROOT / "evals" / "trigger"
RUNS_DIR = Path(__file__).resolve().parent / "runs"
SKILL_RE = re.compile(r'"skill"\s*:\s*"(?:sentinel:)?([A-Za-z0-9_-]+)"')
PER_CASE_TIMEOUT_S = 180
ROUTER = "solve-cv-task"


def fire_prompt(prompt: str, model: str) -> str | None:
    """Run one headless routing turn; return the fired skill name or None.

    Runs in a fresh empty temp dir — with the repo as cwd, the session can
    find real artifacts (old benchmark CSVs, eval files) and answer the prompt
    from disk instead of routing (verified live 2026-07-10).

    Examples:
        >>> callable(fire_prompt)
        True
    """
    import tempfile

    cmd = [
        "claude",
        "--plugin-dir",
        str(ROOT),
        "--model",
        model,
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
    with tempfile.TemporaryDirectory(prefix="trigger-live-") as tmp:
        try:
            res = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=PER_CASE_TIMEOUT_S,
                cwd=tmp,
                stdin=subprocess.DEVNULL,
            )
        except subprocess.TimeoutExpired:
            return None
    m = SKILL_RE.search(res.stdout)
    return m.group(1) if m else None


def load_cases(
    only_skill: str | None, negatives: bool = False
) -> list[tuple[str, str, bool]]:
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


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument(
        "--all", action="store_true", help="Run every case (default: 1 per skill)."
    )
    ap.add_argument("--model", default="sonnet", help="Model for the routed session.")
    ap.add_argument("--skill", default=None, help="Restrict to one skill's cases.")
    ap.add_argument(
        "--negatives",
        action="store_true",
        help="Also run should_not_fire cases (per-skill false positives).",
    )
    ap.add_argument("--out-tag", default=None, help="Suffix for the results file.")
    args = ap.parse_args()

    if "fable" in args.model.lower():
        sys.exit("live evals run sonnet or opus only — never fable (owner rule)")

    triples = load_cases(args.skill, negatives=args.negatives)
    if not args.all:
        seen: set[str] = set()
        sampled = []
        for skill, prompt, positive in triples:
            if positive and skill not in seen:
                sampled.append((skill, prompt, positive))
                seen.add(skill)
        triples = sampled

    RUNS_DIR.mkdir(exist_ok=True)
    ts = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H-%M-%SZ")
    tag = f"-{args.out_tag}" if args.out_tag else ""
    out_path = RUNS_DIR / f"{ts}{tag}.jsonl"

    exact = tolerant = total_pos = 0
    rows = []
    for skill, prompt, positive in triples:
        fired = fire_prompt(prompt, args.model)
        if positive:
            ok_exact = fired == skill
            ok_tolerant = ok_exact or (fired == ROUTER and skill != ROUTER)
            exact += ok_exact
            tolerant += ok_tolerant
            total_pos += 1
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
            "model": args.model,
        }
        rows.append(row)
        print(f"  {icon} {'+' if positive else '-'} expected={skill:<26} fired={fired}")

    with out_path.open("w") as fh:
        for row in rows:
            fh.write(json.dumps(row) + "\n")

    if total_pos:
        print(
            f"\nRouting accuracy (positives): exact {exact}/{total_pos}, "
            f"router-tolerant {tolerant}/{total_pos}"
        )
    # Per-skill precision/recall: TP = positive fired exactly; FN = positive
    # fired other/none; FP = negative where the named skill fired anyway.
    skills = sorted({r["expected"] for r in rows})
    print("\nPer-skill precision/recall (exact, router not credited):")
    for s in skills:
        tp = sum(
            1
            for r in rows
            if r["should_fire"] and r["expected"] == s and r["fired"] == s
        )
        fn = sum(
            1
            for r in rows
            if r["should_fire"] and r["expected"] == s and r["fired"] != s
        )
        fp = sum(
            1
            for r in rows
            if not r["should_fire"] and r["expected"] == s and r["fired"] == s
        )
        prec = tp / (tp + fp) if (tp + fp) else None
        rec = tp / (tp + fn) if (tp + fn) else None
        fmt = lambda v: "—" if v is None else f"{v:.2f}"  # noqa: E731
        print(f"  {s:<26} P={fmt(prec)} R={fmt(rec)} (tp={tp} fp={fp} fn={fn})")

    print(f"Results: {out_path}")
    misroutes = [r for r in rows if r["should_fire"] and not r["router_tolerant"]]
    false_fires = [r for r in rows if not r["should_fire"] and not r["exact"]]
    if misroutes:
        print("Misroutes (neither expected skill nor router fired):")
        for r in misroutes:
            print(
                f"  expected={r['expected']} fired={r['fired']} :: {r['prompt'][:70]}"
            )
    if false_fires:
        print("False fires (skill fired on its should_not_fire prompt):")
        for r in false_fires:
            print(f"  skill={r['expected']} :: {r['prompt'][:70]}")
    return 0 if not (misroutes or false_fires) else 1


if __name__ == "__main__":
    sys.exit(main())
