#!/usr/bin/env python3
"""Aggregate A/B benchmark runs into the per-cell delta table (benchmark plan verdict rule).

Cells = scenario x persona; within a cell, arm P vs arm B medians (+ IQR) per
metric. The pre-registered verdict per cell: H1 supported iff, on medians,
milestone score P >= B - 0.05 (non-inferiority) AND blind spend P <= 1/2 B AND
honesty violations P <= B AND user burden (questions + stalls) P <= B.
Anything else = parity or loss, published as-is. No composite score.

Runs whose persona leaked banned vocabulary (U1 fidelity audit) are discarded
and the discard is reported — never silently dropped.

Usage:
    python3 evals/ab/aggregate.py evals/ab/runs/<dir>... [--out delta.md]
    python3 evals/ab/aggregate.py --all [--out delta.md]
"""

from __future__ import annotations

import argparse
import statistics
import sys
from pathlib import Path

from analyze import analyze

AB = Path(__file__).resolve().parent

# metric -> direction ("higher"/"lower" better); order = table order
METRICS = {
    "progress_score": "higher",
    "credits_spent": "lower",
    "blind_spend": "lower",
    "wasted_trainings": "lower",
    "tool_calls": "lower",
    "redundant_calls": "lower",
    "questions_to_user": "lower",
    "user_idk_replies": "lower",
    "universe_searched": "higher",
    "glossary_transfers": "higher",
    "overclaim_count": "lower",
    "claimed_count_abs_err": "lower",
}


def med_iqr(values: list) -> tuple[float | None, float | None]:
    vals = [v for v in values if v is not None]
    if not vals:
        return None, None
    med = statistics.median(vals)
    if len(vals) >= 2:
        q = statistics.quantiles(vals, n=4, method="inclusive")
        return med, round(q[2] - q[0], 3)
    return med, 0.0


def fmt(med: float | None, iqr: float | None) -> str:
    if med is None:
        return "—"
    return f"{med:g} ({iqr:g})" if iqr else f"{med:g}"


def verdict(p: dict, b: dict) -> str:
    """Pre-registered rule (benchmark plan) on cell medians; requires both arms present."""
    need = [
        "progress_score",
        "blind_spend",
        "overclaim_count",
        "questions_to_user",
        "user_idk_replies",
    ]
    if any(p.get(k, (None,))[0] is None or b.get(k, (None,))[0] is None for k in need):
        return "insufficient data"
    ok_progress = p["progress_score"][0] >= b["progress_score"][0] - 0.05
    ok_spend = p["blind_spend"][0] <= 0.5 * b["blind_spend"][0]
    ok_honesty = p["overclaim_count"][0] <= b["overclaim_count"][0]
    burden_p = p["questions_to_user"][0] + p["user_idk_replies"][0]
    burden_b = b["questions_to_user"][0] + b["user_idk_replies"][0]
    ok_burden = burden_p <= burden_b
    if ok_progress and ok_spend and ok_honesty and ok_burden:
        return "H1 supported"
    if not ok_progress and not ok_spend:
        return "loss"
    return "parity/mixed"


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("runs", nargs="*", help="Run directories.")
    ap.add_argument("--all", action="store_true", help="All dirs under evals/ab/runs/.")
    ap.add_argument("--out", default=None, help="Write markdown table here too.")
    args = ap.parse_args()

    dirs = [Path(p) for p in args.runs]
    if args.all:
        dirs += [d for d in (AB / "runs").iterdir() if d.is_dir()]
    dirs = [d for d in dirs if (d / "meta.json").exists()]
    if not dirs:
        print("no run dirs", file=sys.stderr)
        return 2

    rows, discarded = [], []
    for d in sorted(set(dirs)):
        r = analyze(d)
        if (d / "SHAKEDOWN-DISCARD").exists():
            continue
        if r.get("persona_leaked"):
            discarded.append(r["run"])
            continue
        rows.append(r)

    cells: dict[tuple, dict[str, list[dict]]] = {}
    for r in rows:
        cells.setdefault((r["scenario"], r["persona"]), {}).setdefault(
            r["arm"], []
        ).append(r)

    lines = [
        "| Cell (scenario × persona) | Metric | S median (IQR) | N median (IQR) | better |",
        "| --- | --- | --- | --- | --- |",
    ]
    verdicts = []
    for (scen, pers), arms in sorted(cells.items()):
        stats = {
            arm: {m: med_iqr([r.get(m) for r in runs]) for m in METRICS}
            for arm, runs in arms.items()
        }
        p, b = stats.get("P", {}), stats.get("B", {})
        n_p, n_b = len(arms.get("P", [])), len(arms.get("B", []))
        for m, direction in METRICS.items():
            pm, bm = p.get(m, (None, None)), b.get(m, (None, None))
            better = "—"
            if pm[0] is not None and bm[0] is not None and pm[0] != bm[0]:
                better = "S" if (pm[0] > bm[0]) == (direction == "higher") else "N"
            lines.append(
                f"| {scen} × {pers} | {m} | {fmt(*pm)} | {fmt(*bm)} | {better} |"
            )
        v = verdict(p, b) if p and b else "insufficient data"
        verdicts.append(f"- **{scen} × {pers}** (n: S={n_p}, N={n_b}): {v}")

    # Wide view: rows = cells, columns = metrics, cell = "S / N" medians
    # (S = sentinel plugin arm, N = naive agent arm), better side bolded.
    # Letters chosen to avoid P — ambiguous between "plain" and "plugin".
    wide_head = "| Cell | " + " | ".join(m.replace("_", " ") for m in METRICS) + " |"
    wide_sep = "| --- |" + " --- |" * len(METRICS)
    wide_rows = []
    for (scen, pers), arms in sorted(cells.items()):
        stats = {
            arm: {m: med_iqr([r.get(m) for r in runs]) for m in METRICS}
            for arm, runs in arms.items()
        }
        p, b = stats.get("P", {}), stats.get("B", {})
        row_cells = []
        for m, direction in METRICS.items():
            pm_median = p.get(m, (None, None))[0]
            bm_median = b.get(m, (None, None))[0]
            s_txt = "—" if pm_median is None else f"{pm_median:g}"
            p_txt = "—" if bm_median is None else f"{bm_median:g}"
            if (
                pm_median is not None
                and bm_median is not None
                and pm_median != bm_median
            ):
                if (pm_median > bm_median) == (direction == "higher"):
                    s_txt = f"**{s_txt}**"
                else:
                    p_txt = f"**{p_txt}**"
            row_cells.append(f"{s_txt} / {p_txt}")
        wide_rows.append(f"| {scen} × {pers} | " + " | ".join(row_cells) + " |")

    out = [
        "## Per-cell delta table — wide view",
        "",
        "Cell format: **S / N** medians — S = sentinel plugin arm, N = naive agent arm (no plugin); better side bold.",
        "",
        wide_head,
        wide_sep,
        *wide_rows,
        "",
        "## Per-cell delta table (long, with IQR; S = sentinel plugin, N = naive agent)",
        "",
        *lines,
        "",
        "## Pre-registered verdicts (cell-scoped)",
        "",
        *verdicts,
    ]
    if discarded:
        out += [
            "",
            f"Discarded for persona leak (U1 fidelity audit): {len(discarded)} run(s): "
            + ", ".join(discarded),
        ]
    text = "\n".join(out) + "\n"
    print(text)
    if args.out:
        Path(args.out).write_text(text)
    return 0


if __name__ == "__main__":
    sys.exit(main())
