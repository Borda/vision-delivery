#!/usr/bin/env python3
"""Deployment cost crossover estimator: DIY self-hosting vs Roboflow managed.

Invoked by the ``estimate-economics`` recipe to compute a back-of-envelope
comparison between self-hosting computer-vision inference on cloud GPUs and a
Roboflow managed endpoint. Always reports a fully-loaded DIY option (5 cost
components). A verdict (``diy`` / ``managed``) is emitted ONLY when a real
managed figure is supplied via ``--managed-usd-mo`` (e.g. an enterprise
quote); without one the model abstains (``insufficient-data``) — the public
Core plan floor is credits-based and not comparable to a fully-loaded DIY
run-rate, and treating it as a price would structurally bias the verdict.

Pricing is read from the committed snapshot ``PRICING_SNAPSHOT.json`` beside
this file. A live fetch of each source URL is *attempted* (to confirm sources
are reachable) but live HTML is never parsed — snapshot values are used.

Usage:
    python scripts/cost_model.py --streams 5 --fps 10 --model-size medium \\
        --uptime 24x7 --region us-east-1 [--existing-gpu] [--use-spot] \\
        [--managed-usd-mo 1500] [--override-gpu-spot 0.20] \\
        [--override-engineer 75] [--json]

Examples:
    >>> # As a module, the pure helpers are independently testable.
    >>> instances_needed(5, "medium")
    3
    >>> hours_per_month("business")
    176
"""

from __future__ import annotations

import argparse
import json
import math
import sys
from datetime import date, datetime
from pathlib import Path
from typing import Any

try:
    import requests  # type: ignore
except ImportError:  # pragma: no cover - requests optional
    requests = None  # type: ignore

SNAPSHOT_PATH = Path(__file__).parent / "PRICING_SNAPSHOT.json"

# name -> source URL; used for the (non-parsing) live-reachability probe.
PRICING_SOURCES: dict[str, str] = {
    "aws_gpu": "https://instances.vantage.sh/aws/ec2/g4dn.xlarge",
    "roboflow_managed": "https://roboflow.com/pricing",
    "engineer_hourly": "https://www.payscale.com/research/US/Job=Machine_Learning_Engineer/Salary",
}

# Capacity / effort model constants.
STREAMS_PER_INSTANCE: dict[str, int] = {"nano": 4, "medium": 2, "large": 1}
SETUP_HOURS: dict[str, int] = {"nano": 16, "medium": 24, "large": 40}
HOURS_24X7 = 720
HOURS_BUSINESS = 176
DRIFT_MONTHLY_USD = 150.0
# Roboflow Core plan (annual) — cheapest paid tier. Displayed as a REFERENCE
# floor only; never used as the managed side of a verdict — credits-based,
# not a per-stream price, so treating it as one would bias the comparison.
MANAGED_FLOOR_USD_MO = 79.0
WEEKS_PER_MONTH = 52 / 12
SNAPSHOT_STALE_DAYS = 30


class CostModelError(Exception):
    """Raised when inputs or the pricing snapshot are invalid."""


# --------------------------------------------------------------------------- #
# Pure helpers (no I/O) — independently testable.
# --------------------------------------------------------------------------- #
def hours_per_month(uptime: str) -> int:
    """Return billable hours per month for an uptime profile.

    Args:
        uptime: Either ``"24x7"`` (always on) or ``"business"`` (~176h/mo).

    Returns:
        Hours per month.

    Examples:
        >>> hours_per_month("24x7")
        720
        >>> hours_per_month("business")
        176
    """
    return HOURS_24X7 if uptime == "24x7" else HOURS_BUSINESS


def instances_needed(streams: int, model_size: str) -> int:
    """Return GPU instance count needed to serve ``streams`` at ``model_size``.

    Args:
        streams: Number of camera streams (>= 1).
        model_size: One of ``nano``, ``medium``, ``large``.

    Returns:
        Ceil of streams divided by per-instance stream capacity.

    Examples:
        >>> instances_needed(5, "medium")
        3
        >>> instances_needed(4, "nano")
        1
    """
    per_instance = STREAMS_PER_INSTANCE[model_size]
    return math.ceil(streams / per_instance)


def ops_hours_per_week(streams: int) -> float:
    """Return weekly monitoring hours as a function of stream count.

    Args:
        streams: Number of camera streams.

    Returns:
        Hours per week of ongoing ops/monitoring.

    Examples:
        >>> ops_hours_per_week(1)
        0.5
        >>> ops_hours_per_week(3)
        1.0
        >>> ops_hours_per_week(6)
        2.0
    """
    if streams <= 1:
        return 0.5
    if streams <= 5:
        return 1.0
    return 2.0


def _ordinal(n: int) -> str:
    """Return the English ordinal suffix form of ``n`` (e.g. 2 -> '2nd').

    Examples:
        >>> _ordinal(2)
        '2nd'
        >>> _ordinal(4)
        '4th'
        >>> _ordinal(11)
        '11th'
    """
    if 10 <= n % 100 <= 20:
        suffix = "th"
    else:
        suffix = {1: "st", 2: "nd", 3: "rd"}.get(n % 10, "th")  # codespell:ignore nd
    return f"{n}{suffix}"


def scaling_cliff_note(
    streams: int, model_size: str, gpu_rate: float, hours: int
) -> str:
    """Describe the cost step when the next GPU instance becomes necessary.

    Args:
        streams: Current stream count.
        model_size: Model size affecting per-instance capacity.
        gpu_rate: GPU $/hr used for the incremental instance cost.
        hours: Billable hours per month.

    Returns:
        Human-readable note describing the next scaling cliff.

    Examples:
        >>> note = scaling_cliff_note(5, "medium", 0.274, 720)
        >>> "GPU instance" in note
        True
    """
    return _scaling_cliff(streams, model_size, gpu_rate, hours)[0]


def _scaling_cliff(
    streams: int, model_size: str, gpu_rate: float, hours: int
) -> tuple[str, float]:
    """Return (human note, incremental $/mo) for the next GPU-instance cliff.

    Examples:
        >>> note, inc = _scaling_cliff(5, "medium", 0.274, 720)
        >>> inc > 0
        True
    """
    per_instance = STREAMS_PER_INSTANCE[model_size]
    current = instances_needed(streams, model_size)
    # Smallest stream count that forces one more instance than now.
    next_cliff_streams = current * per_instance + 1
    next_instances = instances_needed(next_cliff_streams, model_size)
    added = next_instances - current
    incremental = round(gpu_rate * hours * added, 2)
    note = (
        f"At {next_cliff_streams} streams, a {_ordinal(next_instances)} GPU instance "
        f"is needed (+${incremental:,.0f}/mo)."
    )
    return note, incremental


# --------------------------------------------------------------------------- #
# Snapshot loading and live-reachability probe.
# --------------------------------------------------------------------------- #
def load_snapshot(path: Path = SNAPSHOT_PATH) -> dict[str, Any]:
    """Load and minimally validate the committed pricing snapshot.

    Args:
        path: Path to ``PRICING_SNAPSHOT.json``.

    Returns:
        Parsed snapshot mapping.

    Raises:
        CostModelError: If the file is missing or malformed.

    Examples:
        >>> snap = load_snapshot()
        >>> "sources" in snap
        True
    """
    if not path.exists():
        raise CostModelError(f"Pricing snapshot not found: {path}")
    try:
        snap = json.loads(path.read_text())
    except json.JSONDecodeError as exc:
        raise CostModelError(f"Pricing snapshot is invalid JSON: {exc}") from exc
    for key in ("as_of", "sources"):
        if key not in snap:
            raise CostModelError(f"Pricing snapshot missing required key '{key}'")
    return snap


def snapshot_age_days(as_of: str, today: date | None = None) -> int | None:
    """Return age of the snapshot in days, or ``None`` if ``as_of`` unparsable.

    Args:
        as_of: ISO date string from the snapshot.
        today: Reference date (defaults to ``date.today()``).

    Returns:
        Whole days since ``as_of``, or ``None`` on parse failure.

    Examples:
        >>> snapshot_age_days("2026-06-25", date(2026, 6, 25))
        0
    """
    today = today or date.today()
    try:
        parsed = datetime.strptime(as_of, "%Y-%m-%d").date()
    except (ValueError, TypeError):
        return None
    return (today - parsed).days


def probe_live_sources() -> dict[str, bool]:
    """Attempt a non-parsing reachability probe of each pricing source.

    Satisfies the "attempted live fetch" requirement without brittle HTML
    parsing. Snapshot values are always used for the actual numbers.

    Returns:
        Mapping of source name to reachability boolean. Empty when
        ``requests`` is unavailable.

    Examples:
        >>> isinstance(probe_live_sources(), dict)
        True
    """
    # ponytail: skip live HTML parse; flag when snapshot >30d old
    if requests is None:
        return {}
    reachable: dict[str, bool] = {}
    for name, url in PRICING_SOURCES.items():
        try:
            resp = requests.get(url, timeout=8)
            reachable[name] = resp.status_code < 400
        except Exception:  # noqa: BLE001 - probe is best-effort, never fatal
            reachable[name] = False
    return reachable


# --------------------------------------------------------------------------- #
# Cost computation.
# --------------------------------------------------------------------------- #
def _resolve_gpu_rate(args: argparse.Namespace, gpu_src: dict[str, Any]) -> float:
    """Resolve GPU $/hr: override -> spot (if --use-spot) -> on-demand."""
    if args.override_gpu_spot is not None:
        return float(args.override_gpu_spot)
    if args.use_spot:
        return float(gpu_src["spot_usd_hr"])
    return float(gpu_src["ondemand_usd_hr"])


def _pricing_mode(args: argparse.Namespace) -> str:
    """Return a label for the GPU pricing source actually used."""
    if args.override_gpu_spot is not None:
        return "override"
    return "spot" if args.use_spot else "on-demand"


def compute(args: argparse.Namespace, snapshot: dict[str, Any]) -> dict[str, Any]:
    """Compute the full DIY-vs-managed comparison result.

    Args:
        args: Parsed CLI namespace.
        snapshot: Loaded pricing snapshot.

    Returns:
        A result mapping with ``diy``, ``managed``, recommendation, crossover,
        scaling cliff and source provenance — the basis for both output modes.

    Examples:
        >>> snap = load_snapshot()
        >>> ns = argparse.Namespace(streams=5, fps=10, model_size="medium",
        ...     uptime="24x7", region="us-east-1", existing_gpu=False,
        ...     use_spot=True, managed_usd_mo=1500.0, override_gpu_spot=None,
        ...     override_engineer=None)
        >>> res = compute(ns, snap)
        >>> res["recommendation"] in ("diy", "managed")
        True
    """
    sources = snapshot["sources"]
    gpu_src = sources["aws_gpu"]
    eng_src = sources["engineer_hourly"]
    managed_src = sources["roboflow_managed"]
    as_of = snapshot["as_of"]

    hours = hours_per_month(args.uptime)
    n_instances = instances_needed(args.streams, args.model_size)
    gpu_rate = _resolve_gpu_rate(args, gpu_src)
    engineer_hourly = (
        float(args.override_engineer)
        if args.override_engineer is not None
        else float(eng_src["hourly_usd"])
    )

    # 1. GPU cloud cost.
    if args.existing_gpu:
        gpu_cost_mo = 0.0
        gpu_note = "existing hardware"
    else:
        gpu_cost_mo = round(gpu_rate * hours * n_instances, 2)
        gpu_note = None

    # 2. One-time engineer setup.
    setup_hours = SETUP_HOURS[args.model_size]
    setup_one_time = round(setup_hours * engineer_hourly, 2)

    # 3. Ongoing ops/monitoring.
    ops_hpw = ops_hours_per_week(args.streams)
    ops_mo = round(ops_hpw * WEEKS_PER_MONTH * engineer_hourly, 2)

    # 4. Drift monitoring + retraining budget.
    drift_mo = DRIFT_MONTHLY_USD

    total_run_rate_mo = round(gpu_cost_mo + ops_mo + drift_mo, 2)

    # 5. Scaling cliff note (reported, not summed).
    cliff, cliff_incremental = _scaling_cliff(
        args.streams, args.model_size, gpu_rate, hours
    )

    # Managed side. A comparable figure exists ONLY when the user supplies one.
    if args.managed_usd_mo is not None:
        managed_mo: float | None = round(float(args.managed_usd_mo), 2)
        managed_source = "user-provided"
        managed_url = "user-provided"
        managed_caveat = "user-provided (e.g. enterprise quote)"
    else:
        managed_mo = None
        managed_source = managed_src["source_url"]
        managed_url = managed_src["source_url"]
        managed_caveat = (
            "Credits-based pricing; no public per-stream price. The Core plan "
            f"floor (${MANAGED_FLOOR_USD_MO:,.0f}/mo annual, ~15 credits) is a "
            "reference only — NOT comparable to a fully-loaded DIY run-rate."
        )

    # Recommendation + crossover. No real managed figure -> abstain.
    if managed_mo is None:
        recommendation = "insufficient-data"
        crossover_months = None
        reason = (
            f"insufficient managed pricing to compare — DIY run-rate is "
            f"~${total_run_rate_mo:,.0f}/mo (+${setup_one_time:,.0f} one-time); "
            "get a Roboflow quote and re-run with --managed-usd-mo"
        )
    elif managed_mo > total_run_rate_mo:
        recommendation = "diy"
        monthly_saving = round(managed_mo - total_run_rate_mo, 2)
        crossover_months = (
            round(setup_one_time / monthly_saving, 1) if monthly_saving > 0 else None
        )
        crossover_month_int = math.ceil(crossover_months) if crossover_months else 1
        reason = (
            f"DIY saves ~${monthly_saving:,.0f}/mo from month "
            f"{max(crossover_month_int, 1)} onward"
        )
    else:
        recommendation = "managed"
        crossover_months = None
        monthly_delta = round(total_run_rate_mo - managed_mo, 2)
        reason = (
            f"Managed is ~${monthly_delta:,.0f}/mo cheaper and avoids "
            f"${setup_one_time:,.0f} one-time setup"
        )

    return {
        "as_of": as_of,
        "recommendation": recommendation,
        "reason": reason,
        "diy": {
            "gpu_cost_mo": gpu_cost_mo,
            "gpu_note": gpu_note,
            "n_instances": n_instances,
            "setup_one_time": setup_one_time,
            "setup_hours": setup_hours,
            "ops_mo": ops_mo,
            "ops_hours_per_week": ops_hpw,
            "drift_mo": drift_mo,
            "total_run_rate_mo": total_run_rate_mo,
            "gpu_rate_usd_hr": gpu_rate,
            "hours_per_mo": hours,
            "pricing_mode": _pricing_mode(args),
        },
        "managed": {
            "total_mo": managed_mo,
            "reference_floor_usd_mo": (
                MANAGED_FLOOR_USD_MO if managed_mo is None else None
            ),
            "source": managed_source,
            "caveat": managed_caveat,
        },
        "crossover_months": crossover_months,
        "scaling_cliff": cliff,
        "scaling_cliff_incremental_usd_mo": cliff_incremental,
        "sources": {
            "gpu_rate_usd_hr": gpu_rate,
            "gpu_source_url": gpu_src["source_url"],
            "gpu_as_of": gpu_src.get("as_of", as_of),
            "managed_source_url": managed_url,
            "managed_as_of": managed_src.get("as_of", as_of),
            "engineer_usd_hr": engineer_hourly,
            "engineer_source_url": eng_src["source_url"],
            "engineer_as_of": eng_src.get("as_of", as_of),
        },
    }


# --------------------------------------------------------------------------- #
# Rendering.
# --------------------------------------------------------------------------- #
def render_json(result: dict[str, Any]) -> str:
    """Render the machine-readable JSON payload."""
    diy = result["diy"]
    payload = {
        "recommendation": result["recommendation"],
        "reason": result["reason"],
        "diy": {
            "gpu_cost_mo": diy["gpu_cost_mo"],
            "n_instances": diy["n_instances"],
            "setup_one_time": diy["setup_one_time"],
            "ops_mo": diy["ops_mo"],
            "drift_mo": diy["drift_mo"],
            "total_run_rate_mo": diy["total_run_rate_mo"],
        },
        "managed": {
            "total_mo": result["managed"]["total_mo"],
            "reference_floor_usd_mo": result["managed"]["reference_floor_usd_mo"],
            "source": result["managed"]["source"],
            "caveat": (
                None
                if result["managed"]["source"] == "user-provided"
                else result["managed"]["caveat"]
            ),
        },
        "crossover_months": result["crossover_months"],
        "scaling_cliff": result["scaling_cliff"],
        "scaling_cliff_incremental_usd_mo": result["scaling_cliff_incremental_usd_mo"],
        "sources": result["sources"],
    }
    return json.dumps(payload, indent=2)


def render_text(
    result: dict[str, Any], args: argparse.Namespace, stale_days: int | None
) -> str:
    """Render the human-readable report with per-line source provenance."""
    diy = result["diy"]
    src = result["sources"]
    as_of = result["as_of"]
    lines: list[str] = []

    staleness = ""
    if stale_days is not None and stale_days > SNAPSHOT_STALE_DAYS:
        staleness = f" — WARNING: snapshot is {stale_days} days old, re-confirm prices"
    lines.append(
        f"Back-of-envelope (as of {as_of} — re-confirm if >30 days old){staleness}:"
    )
    lines.append("")
    lines.append(f"Self-host ({args.streams} streams, {args.uptime}):")

    gpu_label = (
        "existing hardware, $0"
        if diy["gpu_note"]
        else f"{diy['n_instances']}x g4dn.xlarge, {diy['pricing_mode']}"
    )
    lines.append(
        f"  Cloud GPU ({gpu_label}):".ljust(42)
        + f"~${diy['gpu_cost_mo']:,.0f}/mo  "
        + f"[source: {src['gpu_source_url']}, as_of: {src['gpu_as_of']}]"
    )
    lines.append(
        f"  Engineer setup ({diy['setup_hours']}h, one-time):".ljust(42)
        + f"~${diy['setup_one_time']:,.0f} one-time  "
        + f"[source: {src['engineer_source_url']}, as_of: {src['engineer_as_of']}]"
    )
    lines.append(
        f"  Ongoing ops ({diy['ops_hours_per_week']:g}h/wk monitoring):".ljust(42)
        + f"~${diy['ops_mo']:,.0f}/mo  "
        + f"[source: {src['engineer_source_url']}, as_of: {src['engineer_as_of']}]"
    )
    lines.append(
        "  Drift monitoring + retraining:".ljust(42)
        + f"~${diy['drift_mo']:,.0f}/mo  "
        + f"[source: estimate, as_of: {as_of}]"
    )
    lines.append(
        "  Total run-rate:".ljust(42)
        + f"~${diy['total_run_rate_mo']:,.0f}/mo + ${diy['setup_one_time']:,.0f} one-time"
    )
    lines.append("")

    managed = result["managed"]
    managed_src_label = (
        "user-provided" if managed["source"] == "user-provided" else managed["source"]
    )
    if managed["total_mo"] is None:
        lines.append(f"Roboflow managed ({args.streams} streams): no comparable figure")
        lines.append(
            "  Credits-based pricing; no public per-stream price. Reference floor: "
            f"~${managed['reference_floor_usd_mo']:,.0f}/mo Core plan (~15 credits) — "
            "NOT comparable to a fully-loaded DIY run-rate  "
            + f"[source: {managed_src_label}, as_of: {src['managed_as_of']}]"
        )
    else:
        lines.append(
            f"Roboflow managed ({args.streams} streams):".ljust(42)
            + f"~${managed['total_mo']:,.0f}/mo  "
            + f"[source: {managed_src_label}, as_of: {src['managed_as_of']}]"
        )
        lines.append(
            "  Note: No public per-stream price. Figure above is a user-provided enterprise quote."
        )
    lines.append(
        "  Public info: https://roboflow.com/pricing — Core plan $79/mo (credits), "
        "dedicated GPU = Enterprise."
    )
    lines.append("")

    # Crossover sentence.
    if result["recommendation"] == "insufficient-data":
        lines.append("Crossover: not computable without a real managed figure.")
    elif result["recommendation"] == "diy":
        lines.append(
            f"Crossover: At {args.streams} streams {args.uptime} with a "
            f"${managed['total_mo']:,.0f}/mo managed figure, {result['reason']}."
        )
    else:
        lines.append(f"Crossover: {result['reason']}.")
    lines.append("")

    if result["recommendation"] == "insufficient-data":
        lines.append(
            "Recommendation: none — insufficient managed pricing to compare. "
            f"DIY run-rate is ~${diy['total_run_rate_mo']:,.0f}/mo "
            f"(+${diy['setup_one_time']:,.0f} one-time). Get a Roboflow quote "
            "(https://roboflow.com/pricing) and re-run with --managed-usd-mo <quote>."
        )
    else:
        rec_label = "DIY" if result["recommendation"] == "diy" else "Managed"
        alt = "Managed" if rec_label == "DIY" else "DIY"
        lines.append(
            f'Recommendation: {rec_label}  <- (or "{alt}" if the other is cheaper)'
        )
    lines.append("")
    lines.append(f"Scaling cliff: {result['scaling_cliff']}")
    lines.append("")
    lines.append("Sources:")
    lines.append(f"  GPU rate:  {src['gpu_source_url']} (as_of: {src['gpu_as_of']})")
    lines.append(f"  Managed:   {managed_src_label}")
    lines.append(
        f"  Engineer:  {src['engineer_source_url']} (as_of: {src['engineer_as_of']})"
    )
    lines.append("")
    lines.append(
        "All inputs editable — pass --managed-usd-mo, --override-gpu-spot, "
        "or --override-engineer with corrected values."
    )
    return "\n".join(lines)


# --------------------------------------------------------------------------- #
# CLI.
# --------------------------------------------------------------------------- #
def build_parser() -> argparse.ArgumentParser:
    """Construct the argument parser."""
    p = argparse.ArgumentParser(
        description="DIY self-hosting vs Roboflow managed cost crossover estimator.",
    )
    p.add_argument(
        "--streams", type=int, required=True, help="Number of camera streams."
    )
    p.add_argument("--fps", type=int, default=10, help="Frames per second per stream.")
    p.add_argument(
        "--model-size",
        choices=["nano", "medium", "large"],
        default="medium",
        help="Model size class.",
    )
    p.add_argument(
        "--uptime",
        choices=["24x7", "business"],
        default="24x7",
        help="Uptime profile (business = ~176h/mo).",
    )
    p.add_argument(
        "--region", default="us-east-1", help="Cloud region for GPU pricing."
    )
    p.add_argument(
        "--existing-gpu",
        action="store_true",
        help="Use existing hardware; GPU cloud cost = $0.",
    )
    p.add_argument(
        "--use-spot",
        action="store_true",
        default=True,
        help="Use spot GPU pricing (default).",
    )
    p.add_argument(
        "--on-demand",
        dest="use_spot",
        action="store_false",
        help="Use on-demand GPU pricing instead of spot.",
    )
    p.add_argument(
        "--managed-usd-mo",
        type=float,
        default=None,
        help="Override managed cost per month (e.g. enterprise quote).",
    )
    p.add_argument(
        "--override-gpu-spot",
        type=float,
        default=None,
        help="Override GPU $/hr for sensitivity runs.",
    )
    p.add_argument(
        "--override-engineer",
        type=float,
        default=None,
        help="Override engineer hourly rate.",
    )
    p.add_argument("--json", action="store_true", help="Emit machine-readable JSON.")
    return p


def _validate(args: argparse.Namespace) -> None:
    """Validate CLI inputs at the boundary."""
    if args.streams < 1:
        raise CostModelError("--streams must be >= 1")
    if args.fps < 1:
        raise CostModelError("--fps must be >= 1")
    for name, val in (
        ("--managed-usd-mo", args.managed_usd_mo),
        ("--override-gpu-spot", args.override_gpu_spot),
        ("--override-engineer", args.override_engineer),
    ):
        if val is not None and val < 0:
            raise CostModelError(f"{name} must be >= 0")


def main(argv: list[str] | None = None) -> int:
    """CLI entry point.

    Args:
        argv: Optional argument list (defaults to ``sys.argv[1:]``).

    Returns:
        Process exit code (0 success, 2 on input/config error).

    Examples:
        >>> import contextlib, io
        >>> with contextlib.redirect_stdout(io.StringIO()):
        ...     rc = main(["--streams", "1", "--model-size", "nano",
        ...                "--uptime", "business", "--existing-gpu",
        ...                "--managed-usd-mo", "500"])
        >>> rc
        0
    """
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        _validate(args)
        snapshot = load_snapshot()
    except CostModelError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2

    # Best-effort live-reachability probe (never parses HTML, never fatal).
    probe_live_sources()
    stale_days = snapshot_age_days(snapshot["as_of"])

    result = compute(args, snapshot)

    if args.json:
        print(render_json(result))
    else:
        print(render_text(result, args, stale_days))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
