#!/usr/bin/env python3
"""Deployment cost crossover estimator: DIY self-hosting vs Roboflow managed.

Invoked by the ``estimate-economics`` recipe to compute a back-of-envelope
comparison between self-hosting computer-vision inference on cloud GPUs and a
Roboflow managed endpoint. Always reports a fully-loaded DIY option (5 cost
components). A verdict (``diy`` / ``managed``) is emitted ONLY when a managed
figure exists, in this order of precedence:

1. ``--managed-usd-mo`` — a dated user-supplied quote (basis ``user-quote``).
2. ``--managed-credits-mo`` — a dated, sourced credits/month figure priced
   against the stated public plan anchors in the snapshot (basis
   ``public-credit-plan``). The tool never infers credits from FPS or streams.
   Credits above the public Core ceiling cannot be priced without
   extrapolation and abstain.

Without either, the model abstains (``insufficient-data``) — the public Core
plan floor alone is not comparable to a fully-loaded DIY run-rate, and
treating it as a price would structurally bias the verdict.

Pricing is read from the committed snapshot ``PRICING_SNAPSHOT.json`` beside
this file. A live fetch of each source URL is *attempted* (to confirm sources
are reachable) but live HTML is never parsed — snapshot values are used.

Usage:
    python scripts/cost_model.py --streams 5 --fps 10 --model-size medium \\
        --uptime 24x7 --region us-east-1 [--existing-gpu] [--use-spot] \\
        [--managed-usd-mo 1500 --managed-quote-as-of 2026-07-13] \\
        [--managed-credits-mo 120 --credits-source <text/url> \\
         --credits-as-of 2026-10-01] \\
        [--override-gpu-spot 0.20] \\
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
import hashlib
import json
import math
import sys
from dataclasses import dataclass
from datetime import date, datetime
from enum import Enum
from pathlib import Path
from typing import Any

requests: Any | None
try:
    import requests
except ImportError:  # pragma: no cover - requests optional
    requests = None

SNAPSHOT_PATH = Path(__file__).parent / "PRICING_SNAPSHOT.json"

# name -> source URL; used for the (non-parsing) live-reachability probe.
PRICING_SOURCES: dict[str, str] = {
    "aws_gpu": "https://instances.vantage.sh/aws/ec2/g4dn.xlarge",
    "roboflow_managed": "https://roboflow.com/pricing",
    "engineer_hourly": "https://www.payscale.com/research/US/Job=Machine_Learning_Engineer/Salary",
}

# Capacity / effort model constants.
STREAMS_PER_INSTANCE: dict[str, int] = {"nano": 4, "medium": 2, "large": 1}
BASELINE_FPS = 10
SETUP_HOURS: dict[str, int] = {"nano": 16, "medium": 24, "large": 40}
HOURS_24X7 = 720
HOURS_BUSINESS = 176
DRIFT_MONTHLY_USD = 150.0
WEEKS_PER_MONTH = 52 / 12
SNAPSHOT_STALE_DAYS = 30
USER_QUOTE_SOURCE = "user-supplied managed quote"
#: Decimal places kept when deriving whole extra credits, so float noise in a
#: user-supplied credit count (e.g. 30.000000000000004) cannot add a credit.
CREDIT_ROUNDING_DIGITS = 9
CREDIT_PLAN_SCOPE_CAVEAT = (
    "Public credit-plan estimate: cheapest stated anchor (Free / Core floor + "
    "on-demand extra credits / Core ceiling) covering the user-supplied credits. "
    "Upper bound — intermediate Core tiers are not encoded and prepaid extra "
    "credits (listed from $4) may be cheaper. Excludes Enterprise scope "
    "(uptime SLA, priority GPU access, managed GPU cluster); confirm plan terms "
    "cover the workload."
)


class CostModelError(Exception):
    """Raised when inputs or the pricing snapshot are invalid."""


class CreditsOutOfRangeError(CostModelError):
    """Raised when a credit need cannot be priced from the stated public anchors."""


class ManagedBasis(str, Enum):
    """What the managed monthly figure used in a verdict is based on."""

    USER_QUOTE = "user-quote"
    PUBLIC_CREDIT_PLAN = "public-credit-plan"


class CreditPlan(str, Enum):
    """Public plan anchor chosen to cover a monthly credit need."""

    FREE = "free"
    CORE_FLOOR = "core-floor"
    CORE_CEILING = "core-ceiling"


CREDIT_PLAN_LABELS: dict[CreditPlan, str] = {
    CreditPlan.FREE: "Free plan",
    CreditPlan.CORE_FLOOR: "Core plan floor",
    CreditPlan.CORE_CEILING: "Core plan ceiling",
}


@dataclass(frozen=True)
class CreditPlanTiers:
    """Public Roboflow credit-plan anchors parsed from the pricing snapshot.

    Only the anchors stated in the sourced pricing text are represented; no
    intermediate Core tier or per-inference credit cost is encoded.
    """

    free_usd_mo: float
    free_credits_mo: float
    core_floor_usd_mo: float
    core_floor_credits_mo: float
    core_ceiling_usd_mo: float
    core_ceiling_credits_mo: float
    on_demand_usd_per_credit: float
    prepaid_from_usd_per_credit: float


@dataclass(frozen=True)
class CreditPlanEstimate:
    """Monthly cost of one plan anchor covering a credit need."""

    plan: CreditPlan
    plan_usd_mo: float
    included_credits_mo: float
    extra_credits: int
    extra_usd_mo: float
    total_usd_mo: float


@dataclass(frozen=True)
class ManagedSide:
    """Resolved managed side of the comparison (figure, basis, provenance)."""

    total_mo: float | None
    basis: ManagedBasis | None
    source: str
    as_of: str
    caveat: str
    credit_plan: dict[str, Any] | None = None
    abstain_reason: str | None = None


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


def instances_needed(streams: int, model_size: str, fps: int = BASELINE_FPS) -> int:
    """Estimate GPU instances for streams, model-size class, and frame rate.

    Args:
        streams: Number of camera streams (>= 1).
        model_size: One of ``nano``, ``medium``, ``large``.
        fps: Frames per second per stream (>= 1).

    Returns:
        Ceil of normalized frame workload divided by the baseline capacity.

    Examples:
        >>> instances_needed(5, "medium")
        3
        >>> instances_needed(4, "nano")
        1
    """
    per_instance = STREAMS_PER_INSTANCE[model_size]
    return math.ceil((streams * fps) / (per_instance * BASELINE_FPS))


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
    streams: int,
    model_size: str,
    gpu_rate: float,
    hours: int,
    fps: int = BASELINE_FPS,
) -> str:
    """Describe the cost step when the next GPU instance becomes necessary.

    Args:
        streams: Current stream count.
        model_size: Model size affecting per-instance capacity.
        gpu_rate: GPU $/hr used for the incremental instance cost.
        hours: Billable hours per month.
        fps: Frames per second per stream.

    Returns:
        Human-readable note describing the next scaling cliff.

    Examples:
        >>> note = scaling_cliff_note(5, "medium", 0.274, 720)
        >>> "GPU instance" in note
        True
    """
    return _scaling_cliff(streams, model_size, gpu_rate, hours, fps)[0]


def _scaling_cliff(
    streams: int,
    model_size: str,
    gpu_rate: float,
    hours: int,
    fps: int = BASELINE_FPS,
) -> tuple[str, float]:
    """Return (human note, incremental $/mo) for the next GPU-instance cliff.

    Examples:
        >>> note, inc = _scaling_cliff(5, "medium", 0.274, 720)
        >>> inc > 0
        True
    """
    per_instance = STREAMS_PER_INSTANCE[model_size]
    current = instances_needed(streams, model_size, fps)
    # Smallest stream count that forces one more instance than now.
    next_cliff_streams = math.floor(current * per_instance * BASELINE_FPS / fps) + 1
    next_instances = instances_needed(next_cliff_streams, model_size, fps)
    added = next_instances - current
    incremental = round(gpu_rate * hours * added, 2)
    note = (
        f"At {next_cliff_streams} streams running {fps} FPS each, a "
        f"{_ordinal(next_instances)} GPU instance "
        f"is needed (+${incremental:,.0f}/mo)."
    )
    return note, incremental


def _plan_candidate(
    plan: CreditPlan, credits_mo: float, plan_usd_mo: float, included_credits_mo: float, usd_per_credit: float
) -> CreditPlanEstimate:
    """Cost one plan anchor plus whole on-demand extra credits for the remainder."""
    shortfall = round(credits_mo - included_credits_mo, CREDIT_ROUNDING_DIGITS)
    extra_credits = max(0, math.ceil(shortfall))
    extra_usd_mo = round(extra_credits * usd_per_credit, 2)
    return CreditPlanEstimate(
        plan=plan,
        plan_usd_mo=plan_usd_mo,
        included_credits_mo=included_credits_mo,
        extra_credits=extra_credits,
        extra_usd_mo=extra_usd_mo,
        total_usd_mo=round(plan_usd_mo + extra_usd_mo, 2),
    )


def estimate_credit_plan(credits_mo: float, tiers: CreditPlanTiers) -> CreditPlanEstimate:
    """Price a monthly credit need against the stated public plan anchors only.

    Candidates are the Free plan (only when it covers the need outright — the
    source does not state extra credits on Free), the Core floor plus
    on-demand extra credits, and the Core ceiling. The cheapest wins; ties go
    to the lower plan. Because intermediate Core tiers are not encoded, the
    result is an upper bound on the public-plan cost.

    Args:
        credits_mo: Credits consumed per month (user-supplied, >= 0).
        tiers: Public plan anchors from the pricing snapshot.

    Returns:
        The cheapest anchor combination covering ``credits_mo``.

    Raises:
        CreditsOutOfRangeError: If ``credits_mo`` exceeds the Core ceiling —
            pricing it would require extrapolating into Enterprise pricing.

    Examples:
        >>> tiers = CreditPlanTiers(0.0, 10.0, 39.0, 20.0, 1399.0, 500.0, 6.0, 4.0)
        >>> estimate_credit_plan(8, tiers).plan.value, estimate_credit_plan(8, tiers).total_usd_mo
        ('free', 0.0)
        >>> est = estimate_credit_plan(100, tiers)
        >>> (est.plan.value, est.extra_credits, est.total_usd_mo)
        ('core-floor', 80, 519.0)
        >>> estimate_credit_plan(20.5, tiers).total_usd_mo
        45.0
        >>> estimate_credit_plan(300, tiers).plan.value
        'core-ceiling'
        >>> estimate_credit_plan(500, tiers).total_usd_mo
        1399.0
        >>> estimate_credit_plan(501, tiers)  # doctest: +IGNORE_EXCEPTION_DETAIL
        Traceback (most recent call last):
        CreditsOutOfRangeError: exceeds the public Core ceiling
    """
    if credits_mo > tiers.core_ceiling_credits_mo:
        raise CreditsOutOfRangeError(
            f"{credits_mo:g} credits/mo exceeds the public Core ceiling "
            f"({tiers.core_ceiling_credits_mo:g} credits/mo at ${tiers.core_ceiling_usd_mo:,.0f}); "
            "above it Roboflow lists Enterprise custom/volume pricing, so pricing it "
            "would require extrapolation"
        )
    rate = tiers.on_demand_usd_per_credit
    candidates: list[CreditPlanEstimate] = []
    if credits_mo <= tiers.free_credits_mo:
        candidates.append(_plan_candidate(CreditPlan.FREE, credits_mo, tiers.free_usd_mo, tiers.free_credits_mo, rate))
    candidates.append(
        _plan_candidate(CreditPlan.CORE_FLOOR, credits_mo, tiers.core_floor_usd_mo, tiers.core_floor_credits_mo, rate)
    )
    candidates.append(
        _plan_candidate(
            CreditPlan.CORE_CEILING, credits_mo, tiers.core_ceiling_usd_mo, tiers.core_ceiling_credits_mo, rate
        )
    )
    # min() keeps the first minimum, so ties resolve to the lower plan.
    return min(candidates, key=lambda candidate: candidate.total_usd_mo)


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


def _tier_number(plan_tiers: dict[str, Any], group: str, key: str) -> float:
    """Return ``plan_tiers[group][key]`` as a finite non-negative float.

    Raises:
        CostModelError: If the value is missing or not a finite non-negative number.
    """
    section = plan_tiers.get(group)
    value = section.get(key) if isinstance(section, dict) else None
    if isinstance(value, bool) or not isinstance(value, int | float) or not math.isfinite(value) or value < 0:
        raise CostModelError(
            f"Pricing snapshot roboflow_managed.plan_tiers.{group}.{key} must be a finite non-negative number"
        )
    return float(value)


def load_credit_tiers(managed_src: dict[str, Any]) -> CreditPlanTiers:
    """Parse and validate the structured public plan anchors from the snapshot.

    Args:
        managed_src: The snapshot's ``sources.roboflow_managed`` mapping.

    Returns:
        Validated plan anchors.

    Raises:
        CostModelError: If ``plan_tiers`` is missing, malformed, or out of order.

    Examples:
        >>> tiers = load_credit_tiers(load_snapshot()["sources"]["roboflow_managed"])
        >>> tiers.core_floor_credits_mo < tiers.core_ceiling_credits_mo
        True
    """
    plan_tiers = managed_src.get("plan_tiers")
    if not isinstance(plan_tiers, dict):
        raise CostModelError("Pricing snapshot is missing roboflow_managed.plan_tiers")
    tiers = CreditPlanTiers(
        free_usd_mo=_tier_number(plan_tiers, "free", "usd_mo"),
        free_credits_mo=_tier_number(plan_tiers, "free", "credits_mo"),
        core_floor_usd_mo=_tier_number(plan_tiers, "core_floor", "usd_mo"),
        core_floor_credits_mo=_tier_number(plan_tiers, "core_floor", "credits_mo"),
        core_ceiling_usd_mo=_tier_number(plan_tiers, "core_ceiling", "usd_mo"),
        core_ceiling_credits_mo=_tier_number(plan_tiers, "core_ceiling", "credits_mo"),
        on_demand_usd_per_credit=_tier_number(plan_tiers, "additional_credits", "on_demand_usd_per_credit"),
        prepaid_from_usd_per_credit=_tier_number(plan_tiers, "additional_credits", "prepaid_from_usd_per_credit"),
    )
    if not tiers.free_credits_mo < tiers.core_floor_credits_mo <= tiers.core_ceiling_credits_mo:
        raise CostModelError("Pricing snapshot plan_tiers credit anchors must increase Free < Core floor <= ceiling")
    return tiers


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


def _reference_caveat(tiers: CreditPlanTiers) -> str:
    """Caveat shown when no comparable managed figure exists."""
    return (
        "Credits-based pricing; no public per-stream price. The Core plan "
        f"floor (${tiers.core_floor_usd_mo:,.0f}/mo, ~{tiers.core_floor_credits_mo:g} credits) is a "
        "reference only — NOT comparable to a fully-loaded DIY run-rate."
    )


def _credit_plan_side(
    args: argparse.Namespace, managed_src: dict[str, Any], as_of: str, tiers: CreditPlanTiers
) -> ManagedSide:
    """Price user-supplied credits against the public anchors, or abstain with a reason."""
    pricing_url = managed_src["source_url"]
    pricing_as_of = managed_src.get("as_of", as_of)
    provenance: dict[str, Any] = {
        "credits_mo": float(args.managed_credits_mo),
        "credits_source": args.credits_source.strip(),
        "credits_as_of": args.credits_as_of,
        "pricing_source_url": pricing_url,
        "pricing_as_of": pricing_as_of,
    }
    try:
        estimate = estimate_credit_plan(float(args.managed_credits_mo), tiers)
    except CreditsOutOfRangeError as exc:
        return ManagedSide(
            total_mo=None,
            basis=None,
            source=pricing_url,
            as_of=pricing_as_of,
            caveat=_reference_caveat(tiers),
            credit_plan={"status": "unpriced", "reason": str(exc), **provenance},
            abstain_reason=str(exc),
        )
    priced = {
        "status": "priced",
        "estimate_kind": "upper-bound-on-public-anchors",
        "plan": estimate.plan.value,
        "plan_usd_mo": estimate.plan_usd_mo,
        "included_credits_mo": estimate.included_credits_mo,
        "extra_credits": estimate.extra_credits,
        "extra_usd_per_credit": tiers.on_demand_usd_per_credit,
        "extra_credit_pricing": "on-demand",
        "prepaid_from_usd_per_credit": tiers.prepaid_from_usd_per_credit,
        "extra_usd_mo": estimate.extra_usd_mo,
        "total_usd_mo": estimate.total_usd_mo,
    }
    return ManagedSide(
        total_mo=estimate.total_usd_mo,
        basis=ManagedBasis.PUBLIC_CREDIT_PLAN,
        source=pricing_url,
        as_of=pricing_as_of,
        caveat=CREDIT_PLAN_SCOPE_CAVEAT,
        credit_plan={**priced, **provenance},
    )


def _resolve_managed(
    args: argparse.Namespace, managed_src: dict[str, Any], as_of: str, tiers: CreditPlanTiers
) -> ManagedSide:
    """Resolve the managed figure: user quote > public credit plan > none.

    Args:
        args: Parsed CLI namespace.
        managed_src: Snapshot ``roboflow_managed`` mapping.
        as_of: Snapshot-wide ``as_of`` fallback date.
        tiers: Public plan anchors.

    Returns:
        The managed side with figure (or ``None``), basis, and provenance.
    """
    if args.managed_usd_mo is not None:
        superseded = None
        if args.managed_credits_mo is not None:
            superseded = {
                "status": "superseded-by-quote",
                "credits_mo": float(args.managed_credits_mo),
                "credits_source": args.credits_source.strip(),
                "credits_as_of": args.credits_as_of,
            }
        return ManagedSide(
            total_mo=round(float(args.managed_usd_mo), 2),
            basis=ManagedBasis.USER_QUOTE,
            source=USER_QUOTE_SOURCE,
            as_of=args.managed_quote_as_of,
            caveat="user-supplied quote; scope and taxes require confirmation",
            credit_plan=superseded,
        )
    if args.managed_credits_mo is not None:
        return _credit_plan_side(args, managed_src, as_of, tiers)
    return ManagedSide(
        total_mo=None,
        basis=None,
        source=managed_src["source_url"],
        as_of=managed_src.get("as_of", as_of),
        caveat=_reference_caveat(tiers),
    )


def _decide(managed: ManagedSide, total_run_rate_mo: float, setup_one_time: float) -> tuple[str, float | None, str]:
    """Return (recommendation, crossover_months, reason) for the resolved managed side.

    Examples:
        >>> side = ManagedSide(None, None, "src", "2026-10-05", "caveat")
        >>> _decide(side, 300.0, 1000.0)[0]
        'insufficient-data'
        >>> side = ManagedSide(500.0, ManagedBasis.USER_QUOTE, "q", "2026-10-01", "c")
        >>> _decide(side, 300.0, 1000.0)[:2]
        ('diy', 5.0)
    """
    managed_mo = managed.total_mo
    if managed_mo is None:
        hint = (
            f"{managed.abstain_reason}; get a dated Roboflow quote and re-run with --managed-usd-mo and "
            "--managed-quote-as-of"
            if managed.abstain_reason
            else "get a dated Roboflow quote and re-run with --managed-usd-mo and --managed-quote-as-of, "
            "or supply public-plan credits/month with --managed-credits-mo, --credits-source and --credits-as-of"
        )
        reason = (
            f"insufficient managed pricing to compare — DIY run-rate is "
            f"~${total_run_rate_mo:,.0f}/mo (+${setup_one_time:,.0f} one-time); {hint}"
        )
        return "insufficient-data", None, reason
    credit_basis = managed.basis == ManagedBasis.PUBLIC_CREDIT_PLAN
    if managed_mo > total_run_rate_mo:
        monthly_saving = round(managed_mo - total_run_rate_mo, 2)
        crossover_months = round(setup_one_time / monthly_saving, 1) if monthly_saving > 0 else None
        crossover_month_int = math.ceil(crossover_months) if crossover_months else 1
        reason = f"DIY saves ~${monthly_saving:,.0f}/mo from month {max(crossover_month_int, 1)} onward"
        if credit_basis:
            reason += (
                " versus a public credit-plan upper bound — intermediate Core tiers may be cheaper; "
                "confirm the current tier price before deciding"
            )
        return "diy", crossover_months, reason
    monthly_delta = round(total_run_rate_mo - managed_mo, 2)
    reason = f"Managed is ~${monthly_delta:,.0f}/mo cheaper and avoids ${setup_one_time:,.0f} one-time setup"
    if credit_basis:
        reason += " (public credit-plan estimate; excludes Enterprise SLA and managed GPU cluster)"
    return "managed", None, reason


def compute(args: argparse.Namespace, snapshot: dict[str, Any]) -> dict[str, Any]:
    """Compute the full DIY-vs-managed comparison result.

    Args:
        args: Parsed CLI namespace.
        snapshot: Loaded pricing snapshot.

    Returns:
        A result mapping with ``diy``, ``managed``, recommendation, crossover,
        scaling cliff and source provenance — the basis for both output modes.

    Raises:
        CostModelError: If the snapshot's public plan anchors are malformed.

    Examples:
        >>> snap = load_snapshot()
        >>> ns = argparse.Namespace(streams=5, fps=10, model_size="medium",
        ...     uptime="24x7", region="us-east-1", existing_gpu=False,
        ...     use_spot=True, managed_usd_mo=1500.0,
        ...     managed_quote_as_of="2026-07-13", override_gpu_spot=None,
        ...     override_engineer=None, managed_credits_mo=None,
        ...     credits_source=None, credits_as_of=None)
        >>> res = compute(ns, snap)
        >>> res["recommendation"] in ("diy", "managed")
        True
        >>> res["managed"]["basis"]
        'user-quote'
    """
    sources = snapshot["sources"]
    gpu_src = sources["aws_gpu"]
    eng_src = sources["engineer_hourly"]
    managed_src = sources["roboflow_managed"]
    as_of = snapshot["as_of"]
    tiers = load_credit_tiers(managed_src)

    hours = hours_per_month(args.uptime)
    n_instances = instances_needed(args.streams, args.model_size, args.fps)
    gpu_rate = _resolve_gpu_rate(args, gpu_src)
    engineer_hourly = (
        float(args.override_engineer) if args.override_engineer is not None else float(eng_src["hourly_usd"])
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
    cliff, cliff_incremental = _scaling_cliff(args.streams, args.model_size, gpu_rate, hours, args.fps)

    # Managed side: user quote > public credit plan > abstain.
    managed = _resolve_managed(args, managed_src, as_of, tiers)
    recommendation, crossover_months, reason = _decide(managed, total_run_rate_mo, setup_one_time)

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
            "fps_per_stream": args.fps,
            "capacity_basis_fps": BASELINE_FPS,
        },
        "managed": {
            "total_mo": managed.total_mo,
            "basis": managed.basis.value if managed.basis is not None else None,
            "reference_floor_usd_mo": (tiers.core_floor_usd_mo if managed.total_mo is None else None),
            "public_anchors": {
                "floor_usd_mo": tiers.core_floor_usd_mo,
                "floor_credits_mo": tiers.core_floor_credits_mo,
                "ceiling_usd_mo": tiers.core_ceiling_usd_mo,
                "ceiling_credits_mo": tiers.core_ceiling_credits_mo,
                "source_url": managed_src["source_url"],
                "as_of": managed_src.get("as_of", as_of),
            },
            "source": managed.source,
            "caveat": managed.caveat,
            "credit_plan": managed.credit_plan,
        },
        "crossover_months": crossover_months,
        "scaling_cliff": cliff,
        "scaling_cliff_incremental_usd_mo": cliff_incremental,
        "sources": {
            "gpu_rate_usd_hr": gpu_rate,
            "gpu_source_url": gpu_src["source_url"],
            "gpu_as_of": gpu_src.get("as_of", as_of),
            "managed_source_url": managed.source,
            "managed_as_of": managed.as_of,
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
    proof = result.get(
        "proof",
        {"status": "unbound", "acceptance_id": "", "acceptance_sha256": ""},
    )
    payload = {
        "proof": proof,
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
            "basis": result["managed"]["basis"],
            "reference_floor_usd_mo": result["managed"]["reference_floor_usd_mo"],
            "source": result["managed"]["source"],
            "caveat": (None if result["managed"]["source"] == USER_QUOTE_SOURCE else result["managed"]["caveat"]),
            "credit_plan": result["managed"]["credit_plan"],
        },
        "crossover_months": result["crossover_months"],
        "scaling_cliff": result["scaling_cliff"],
        "scaling_cliff_incremental_usd_mo": result["scaling_cliff_incremental_usd_mo"],
        "sources": result["sources"],
    }
    return json.dumps(payload, indent=2, allow_nan=False)


def render_text(result: dict[str, Any], args: argparse.Namespace, stale_days: int | None) -> str:
    """Render the human-readable report with per-line source provenance."""
    proof = result.get(
        "proof",
        {"status": "unbound", "acceptance_id": "", "acceptance_sha256": ""},
    )
    proof_line = (
        f"Proof binding: acceptance_id={proof['acceptance_id']}; acceptance_sha256={proof['acceptance_sha256']}"
        if proof["status"] == "bound"
        else "Proof binding: unbound assumptions only; not decision-grade evidence"
    )
    lines = [proof_line, ""]
    lines.extend(_render_diy_section(result, args, stale_days))
    lines.extend(_render_managed_section(result, args))
    lines.extend(_render_decision_section(result, args))
    return "\n".join(lines)


def _render_diy_section(result: dict[str, Any], args: argparse.Namespace, stale_days: int | None) -> list[str]:
    """Render the header and self-host cost lines.

    Args:
        result: Computed cost-model result.
        args: Parsed CLI namespace.
        stale_days: Snapshot age in days, or None when unknown.

    Returns:
        Report lines for the DIY section.
    """
    diy = result["diy"]
    src = result["sources"]
    as_of = result["as_of"]
    lines: list[str] = []

    staleness = ""
    if stale_days is not None and stale_days > SNAPSHOT_STALE_DAYS:
        staleness = f" — WARNING: snapshot is {stale_days} days old, re-confirm prices"
    lines.append(f"Back-of-envelope (as of {as_of} — re-confirm if >30 days old){staleness}:")
    lines.append("")
    lines.append(f"Self-host ({args.streams} streams, {args.fps} FPS each, {args.uptime}):")

    gpu_label = (
        "existing hardware, $0" if diy["gpu_note"] else f"{diy['n_instances']}x g4dn.xlarge, {diy['pricing_mode']}"
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
        "  Total run-rate:".ljust(42) + f"~${diy['total_run_rate_mo']:,.0f}/mo + ${diy['setup_one_time']:,.0f} one-time"
    )
    lines.append("")
    return lines


def _render_managed_section(result: dict[str, Any], args: argparse.Namespace) -> list[str]:
    """Render the managed-offer comparison lines.

    Args:
        result: Computed cost-model result.
        args: Parsed CLI namespace.

    Returns:
        Report lines for the managed section.
    """
    src = result["sources"]
    managed = result["managed"]
    anchors = managed["public_anchors"]
    anchors_cite = f"[source: {anchors['source_url']}, as_of: {anchors['as_of']}]"
    credit_plan = managed["credit_plan"]
    if managed["basis"] == ManagedBasis.PUBLIC_CREDIT_PLAN.value:
        lines = _render_credit_plan_lines(managed, args)
    elif managed["total_mo"] is None:
        cite = f"[source: {managed['source']}, as_of: {src['managed_as_of']}]"
        lines = [f"Roboflow managed ({args.streams} streams): no comparable figure"]
        if credit_plan is not None:
            lines.append(f"  Credits not priceable: {credit_plan['reason']}  {cite}  {_credits_cite(credit_plan)}")
        lines.append(
            "  Credits-based pricing; no public per-stream price. Reference floor: "
            f"~${managed['reference_floor_usd_mo']:,.0f}/mo Core plan "
            f"(~{anchors['floor_credits_mo']:g} credits) — "
            f"NOT comparable to a fully-loaded DIY run-rate  {cite}"
        )
    else:
        lines = [
            f"Roboflow managed ({args.streams} streams):".ljust(42)
            + f"~${managed['total_mo']:,.0f}/mo  "
            + f"[source: {managed['source']}, as_of: {src['managed_as_of']}]",
            "  Note: No public per-stream price. Figure above is a user-provided enterprise quote.",
        ]
        if credit_plan is not None:
            lines.append(
                f"  Note: --managed-credits-mo {credit_plan['credits_mo']:g} was supplied but is superseded "
                "by the quote above."
            )
    lines.append(
        f"  Public info: Core plan ${anchors['floor_usd_mo']:,.0f}/mo ({anchors['floor_credits_mo']:g} credits) "
        f"up to ${anchors['ceiling_usd_mo']:,.0f}/mo ({anchors['ceiling_credits_mo']:g} credits); "
        f"dedicated GPU = Enterprise  {anchors_cite}"
    )
    lines.append("")
    return lines


def _credits_cite(credit_plan: dict[str, Any]) -> str:
    """Citation for the user-supplied credits/month figure."""
    return f"[credits source: {credit_plan['credits_source']}, as_of: {credit_plan['credits_as_of']}]"


def _render_credit_plan_lines(managed: dict[str, Any], args: argparse.Namespace) -> list[str]:
    """Render the managed lines for a public credit-plan estimate.

    Args:
        managed: The result's ``managed`` mapping (basis ``public-credit-plan``).
        args: Parsed CLI namespace.

    Returns:
        Report lines: figure, plan breakdown, credits provenance, scope caveat.
    """
    plan = managed["credit_plan"]
    cite = f"[source: {plan['pricing_source_url']}, as_of: {plan['pricing_as_of']}]"
    label = CREDIT_PLAN_LABELS[CreditPlan(plan["plan"])]
    breakdown = f"  Basis: {label} ${plan['plan_usd_mo']:,.0f}/mo incl. {plan['included_credits_mo']:g} credits"
    if plan["extra_credits"]:
        breakdown += (
            f" + {plan['extra_credits']} on-demand credits x ${plan['extra_usd_per_credit']:,.2f}"
            f" = ${plan['extra_usd_mo']:,.0f}"
        )
    return [
        f"Roboflow managed ({args.streams} streams, public credit plan): ".ljust(42)
        + f"~${managed['total_mo']:,.0f}/mo  {cite}",
        f"{breakdown}  {cite}",
        f"  Credits/mo: {plan['credits_mo']:g} (user-supplied, not inferred from FPS)  {_credits_cite(plan)}",
        f"  Scope: {managed['caveat']}",
    ]


def _render_decision_section(result: dict[str, Any], args: argparse.Namespace) -> list[str]:
    """Render crossover, recommendation, scaling cliff, and source lines.

    Args:
        result: Computed cost-model result.
        args: Parsed CLI namespace.

    Returns:
        Report lines for the decision section.
    """
    src = result["sources"]
    managed = result["managed"]
    managed_src_label = managed["source"]
    lines: list[str] = []

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
        lines.append(f"Recommendation: none — {result['reason']}.")
    else:
        rec_label = "DIY" if result["recommendation"] == "diy" else "Managed"
        alt = "Managed" if rec_label == "DIY" else "DIY"
        lines.append(f'Recommendation: {rec_label}  <- (or "{alt}" if the other is cheaper)')
    lines.append("")
    lines.append(f"Scaling cliff: {result['scaling_cliff']}")
    lines.append(
        "Capacity assumption: committed streams-per-instance estimates are calibrated "
        f"at {BASELINE_FPS} FPS and scale linearly with requested FPS; benchmark the "
        "selected runtime before purchase."
    )
    lines.append("")
    lines.append("Sources:")
    lines.append(f"  GPU rate:  {src['gpu_source_url']} (as_of: {src['gpu_as_of']})")
    lines.append(f"  Managed:   {managed_src_label} (as_of: {src['managed_as_of']})")
    credit_plan = managed["credit_plan"]
    if credit_plan is not None:
        lines.append(f"  Credits:   {credit_plan['credits_source']} (as_of: {credit_plan['credits_as_of']})")
    lines.append(f"  Engineer:  {src['engineer_source_url']} (as_of: {src['engineer_as_of']})")
    lines.append("")
    lines.append(
        "All inputs editable — pass a dated managed quote, dated public-plan credits "
        "(--managed-credits-mo), --override-gpu-spot, or --override-engineer with corrected values."
    )
    return lines


# --------------------------------------------------------------------------- #
# CLI.
# --------------------------------------------------------------------------- #
def build_parser() -> argparse.ArgumentParser:
    """Construct the argument parser."""
    p = argparse.ArgumentParser(
        description="DIY self-hosting vs Roboflow managed cost crossover estimator.",
    )
    p.add_argument("--streams", type=int, required=True, help="Number of camera streams.")
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
        "--region",
        choices=["us-east-1"],
        default="us-east-1",
        help="Cloud region covered by the committed GPU-price snapshot.",
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
        "--managed-quote-as-of",
        default=None,
        help="ISO date of the user-supplied managed quote; required with its amount.",
    )
    p.add_argument(
        "--managed-credits-mo",
        type=float,
        default=None,
        help=(
            "Roboflow credits consumed per month, from the user or current upstream guidance "
            "(never inferred from FPS). Priced against the public plan anchors; a "
            "--managed-usd-mo quote takes precedence."
        ),
    )
    p.add_argument(
        "--credits-source",
        default=None,
        help="Where the credits/month figure came from (text or URL); required with --managed-credits-mo.",
    )
    p.add_argument(
        "--credits-as-of",
        default=None,
        help="ISO date of the credits/month figure; required with --managed-credits-mo.",
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
    p.add_argument(
        "--acceptance",
        type=Path,
        help="Frozen acceptance JSON to bind into machine and text output.",
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
        ("--managed-credits-mo", args.managed_credits_mo),
        ("--override-gpu-spot", args.override_gpu_spot),
        ("--override-engineer", args.override_engineer),
    ):
        if val is None:
            continue
        if not math.isfinite(val):
            raise CostModelError(f"{name} must be finite")
        if val < 0:
            raise CostModelError(f"{name} must be >= 0")
    _validate_managed_quote(args)
    _validate_credit_inputs(args)


def _load_acceptance_binding(path: Path | None) -> dict[str, str]:
    """Return a minimal immutable acceptance binding for economic output."""
    if path is None:
        return {
            "status": "unbound",
            "acceptance_id": "",
            "acceptance_sha256": "",
        }
    if path.is_symlink() or not path.is_file():
        raise CostModelError("--acceptance must be a regular non-symlink JSON file")
    try:
        raw = path.read_bytes()
        data = json.loads(raw)
    except (OSError, json.JSONDecodeError) as exc:
        raise CostModelError(f"cannot read --acceptance: {exc}") from exc
    if not isinstance(data, dict) or data.get("schema_version") != "1":
        raise CostModelError("--acceptance must use Sentinel acceptance schema 1")
    required = {
        "acceptance_id",
        "frozen_at",
        "metric",
        "comparator",
        "threshold",
        "unit",
        "dataset_sha256",
        "model_or_pipeline",
        "confirmed_by",
    }
    if required - data.keys():
        raise CostModelError("--acceptance is missing frozen acceptance fields")
    acceptance_id = _validate_acceptance_fields(data)
    return {
        "status": "bound",
        "acceptance_id": acceptance_id,
        "acceptance_sha256": hashlib.sha256(raw).hexdigest(),
    }


def _validate_acceptance_fields(data: dict[str, Any]) -> str:
    """Validate frozen acceptance field values and return the acceptance ID.

    Args:
        data: Parsed acceptance mapping already known to carry every required key.

    Returns:
        The non-empty acceptance ID.

    Raises:
        CostModelError: If any field value violates the acceptance schema.
    """
    acceptance_id = data.get("acceptance_id")
    if not isinstance(acceptance_id, str) or not acceptance_id.strip():
        raise CostModelError("--acceptance must contain acceptance_id")
    try:
        frozen_at = datetime.fromisoformat(str(data["frozen_at"]).replace("Z", "+00:00"))
    except ValueError as exc:
        raise CostModelError("--acceptance frozen_at must be ISO-8601") from exc
    if frozen_at.tzinfo is None:
        raise CostModelError("--acceptance frozen_at must include a timezone")
    threshold = data["threshold"]
    if isinstance(threshold, bool) or not isinstance(threshold, int | float) or not math.isfinite(threshold):
        raise CostModelError("--acceptance threshold must be finite numeric")
    if data["comparator"] not in {"gte", "lte"}:
        raise CostModelError("--acceptance comparator must be gte or lte")
    dataset_digest = data["dataset_sha256"]
    if (
        not isinstance(dataset_digest, str)
        or len(dataset_digest) != 64
        or any(character not in "0123456789abcdef" for character in dataset_digest)
    ):
        raise CostModelError("--acceptance dataset_sha256 must be lowercase SHA-256")
    for field in ("metric", "unit", "model_or_pipeline", "confirmed_by"):
        if not isinstance(data[field], str) or not data[field].strip():
            raise CostModelError(f"--acceptance {field} must be non-empty text")
    return acceptance_id


def _validate_managed_quote(args: argparse.Namespace) -> None:
    """Require a dated, non-future managed quote when one is supplied.

    Args:
        args: Parsed CLI namespace.

    Raises:
        CostModelError: If the quote/date pairing or the date itself is invalid.
    """
    if args.managed_usd_mo is None and args.managed_quote_as_of is not None:
        raise CostModelError("--managed-quote-as-of requires --managed-usd-mo")
    if args.managed_usd_mo is not None and args.managed_quote_as_of is None:
        raise CostModelError("--managed-usd-mo requires --managed-quote-as-of YYYY-MM-DD")
    if args.managed_quote_as_of is not None:
        _require_past_iso_date(args.managed_quote_as_of, "--managed-quote-as-of")


def _validate_credit_inputs(args: argparse.Namespace) -> None:
    """Require sourced, dated, non-future provenance for a credits/month figure.

    Args:
        args: Parsed CLI namespace.

    Raises:
        CostModelError: If the credits/source/date pairing or any value is invalid.
    """
    credits_given = args.managed_credits_mo is not None
    for flag, value, hint in (
        ("--credits-source", args.credits_source, " <text/url>"),
        ("--credits-as-of", args.credits_as_of, " YYYY-MM-DD"),
    ):
        if credits_given and value is None:
            raise CostModelError(f"--managed-credits-mo requires {flag}{hint}")
        if not credits_given and value is not None:
            raise CostModelError(f"{flag} requires --managed-credits-mo")
    if args.credits_source is not None and not args.credits_source.strip():
        raise CostModelError("--credits-source must be non-empty text")
    if args.credits_as_of is not None:
        _require_past_iso_date(args.credits_as_of, "--credits-as-of")


def _require_past_iso_date(value: str, flag: str) -> date:
    """Parse ``value`` as ``YYYY-MM-DD`` and reject future dates.

    Raises:
        CostModelError: If the date is malformed or later than today.

    Examples:
        >>> _require_past_iso_date("2026-07-01", "--x")
        datetime.date(2026, 7, 1)
    """
    try:
        parsed = datetime.strptime(value, "%Y-%m-%d").date()
    except ValueError as exc:
        raise CostModelError(f"{flag} must be an ISO date (YYYY-MM-DD)") from exc
    if parsed > date.today():
        raise CostModelError(f"{flag} cannot be in the future")
    return parsed


def _validate_finite_result(value: Any, path: str = "result") -> None:
    """Reject arithmetic overflow before rendering a business decision.

    Args:
        value: Nested result value to inspect.
        path: Human-readable location used in validation errors.

    Raises:
        CostModelError: If any computed floating-point value is non-finite.
    """
    if isinstance(value, float) and not math.isfinite(value):
        raise CostModelError(f"computed {path} must be finite; reduce override values")
    if isinstance(value, dict):
        for key, child in value.items():
            _validate_finite_result(child, f"{path}.{key}")
    elif isinstance(value, (list, tuple)):
        for index, child in enumerate(value):
            _validate_finite_result(child, f"{path}[{index}]")


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
        ...                "--managed-usd-mo", "500",
        ...                "--managed-quote-as-of", "2026-07-13"])
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

    try:
        result = compute(args, snapshot)
        result["proof"] = _load_acceptance_binding(args.acceptance)
        _validate_finite_result(result)
    except (CostModelError, OverflowError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2

    if args.json:
        print(render_json(result))
    else:
        print(render_text(result, args, stale_days))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
