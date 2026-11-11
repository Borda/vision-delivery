#!/usr/bin/env python3
"""CI assertion: cost_model.py honesty gates.

Asserts, in order:
1. Fixtures: diy-wins → "diy" (real quote), managed-wins → "managed" (real
   quote), abstain-default → "insufficient-data" (no quote — the model must
   never convert the Core plan floor into a verdict). credit-plan-* fixtures
   cover sourced credits/month priced against the public plan anchors
   (in-range → verdict, beyond the Core ceiling → abstain, quote overrides
   credits) via optional ``expect_managed_basis``, ``expect_managed_total_mo``
   and ``expect_credit_plan_status`` keys.
2. Every dollar line in text output carries [source: ..., as_of: YYYY-MM-DD].
3. Snapshot staleness canary: PRICING_SNAPSHOT.json `as_of` must be younger
   than MAX_SNAPSHOT_AGE_DAYS (override with ALLOW_STALE_SNAPSHOT=1).
4. Monotonicity properties over a streams sweep (fixed real quote):
   DIY total and instance count non-decreasing, scaling-cliff increment >= 0,
   crossover_months >= 0 when present.
5. Abstention sweep: without a quote, no point in the sweep may emit a
   diy/managed verdict.
6. Boundary validation rejects negative and non-finite overrides while accepting zero
   and representative extreme finite values.
7. Credit-plan inputs: credits require a source and a non-future ISO date
   (and vice versa); plan-anchor boundaries price exactly as stated; the
   pricing date stays the snapshot date while the credits date is preserved.

Usage:
    python3 evals/cost-model/assert_cost_model.py
    echo $?  # 0 = pass, 1 = fail
"""

from __future__ import annotations

import contextlib
import hashlib
import importlib.util
import io
import json
import math
import re
import subprocess
import sys
import tempfile
from datetime import date, timedelta
from pathlib import Path
from typing import Any

FIXTURES_DIR = Path(__file__).parent / "fixtures"
SCRIPT = Path(__file__).parent.parent.parent / "scripts" / "cost_model.py"
SNAPSHOT = Path(__file__).parent.parent.parent / "scripts" / "PRICING_SNAPSHOT.json"
MAX_SNAPSHOT_AGE_DAYS = 90
SWEEP_STREAMS = [1, 2, 3, 4, 5, 8, 12, 20, 40, 80, 200]
# Optional fixture key -> path into the JSON payload's "managed" block.
FIXTURE_MANAGED_EXPECTATIONS = {
    "expect_managed_basis": ("basis",),
    "expect_managed_total_mo": ("total_mo",),
    "expect_credit_plan_status": ("credit_plan", "status"),
}
CREDITS_AS_OF = "2026-10-01"
# credits/mo -> (expected plan anchor, expected $/mo) from the stated public anchors:
# Free 10cr/$0, Core floor 20cr/$39 + on-demand $6/credit, Core ceiling 500cr/$1,399.
CREDIT_PLAN_BOUNDARIES = {
    "0": ("free", 0.0),
    "10": ("free", 0.0),
    "10.5": ("core-floor", 39.0),
    "20": ("core-floor", 39.0),
    "20.5": ("core-floor", 45.0),
    "246": ("core-floor", 1395.0),
    "247": ("core-ceiling", 1399.0),
    "500": ("core-ceiling", 1399.0),
}

# Matches lines like ~$123/mo  [source: ..., as_of: 2026-06-25]
SOURCE_PATTERN = re.compile(r"\[source: .+, as_of: \d{4}-\d{2}-\d{2}\]")
DOLLAR_LINE_PATTERN = re.compile(r"~\$-?[\d,]+")

# Captured from the unchanged CLI before adding batch workloads or value estimates.
STREAM_BASELINE: dict[str, Any] = {
    "proof": {"status": "unbound", "acceptance_id": "", "acceptance_sha256": ""},
    "recommendation": "diy",
    "reason": "DIY saves ~$481/mo from month 3 onward",
    "diy": {
        "gpu_cost_mo": 606.96,
        "n_instances": 3,
        "setup_one_time": 1453.92,
        "ops_mo": 262.51,
        "drift_mo": 150.0,
        "total_run_rate_mo": 1019.47,
    },
    "managed": {
        "total_mo": 1500.0,
        "basis": "user-quote",
        "reference_floor_usd_mo": None,
        "source": "user-supplied managed quote",
        "caveat": None,
        "credit_plan": None,
    },
    "crossover_months": 3.0,
    "scaling_cliff": "At 7 streams running 10 FPS each, a 4th GPU instance is needed (+$202/mo).",
    "scaling_cliff_incremental_usd_mo": 202.32,
    "sources": {
        "gpu_rate_usd_hr": 0.281,
        "gpu_source_url": "https://instances.vantage.sh/aws/ec2/g4dn.xlarge",
        "gpu_as_of": "2026-10-05",
        "managed_source_url": "user-supplied managed quote",
        "managed_as_of": "2026-07-13",
        "engineer_usd_hr": 60.58,
        "engineer_source_url": "https://www.payscale.com/research/US/Job=Machine_Learning_Engineer/Salary",
        "engineer_as_of": "2026-10-05",
    },
}
# Captured stream-mode output with no value options; the time-dependent staleness warning is removed from text.
# The text digest covers the "not computed" hint, which names --current-error-rate.
STREAM_TEXT_SHA256 = "c5bf18f403a13d600ee5de8317f3c55cdd74cf14fb4ba09a6aa01275b296cd91"
STREAM_JSON_SHA256 = "409f4fcbbfd2c5713c97f302818b83394942a722977eaa3e7ba1ad4dcf44e1b4"
QUOTE_ARGS = ["--managed-usd-mo", "1500", "--managed-quote-as-of", "2026-07-13"]
VALUE_INPUTS = {
    "--error-cost-usd": "10",
    "--error-cost-source": "user loss ledger",
    "--error-cost-as-of": "2026-07-13",
    "--current-error-rate": "0.2",
    "--model-error-rate": "0.1",
    "--error-rates-source": "scorer evidence",
}


def run_json(args: list[str]) -> dict:
    result = subprocess.run(
        [sys.executable, str(SCRIPT)] + args + ["--json"],
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        raise AssertionError(f"cost_model.py exited {result.returncode}:\n{result.stderr}")
    return json.loads(result.stdout)


def run_text(args: list[str]) -> str:
    result = subprocess.run(
        [sys.executable, str(SCRIPT)] + args,
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        raise AssertionError(f"cost_model.py exited {result.returncode}:\n{result.stderr}")
    return result.stdout


def assert_invalid_input(args: list[str], expected_error: str) -> None:
    """Assert that invalid CLI input fails without emitting a JSON verdict."""
    result = subprocess.run(
        [sys.executable, str(SCRIPT), *args, "--json"],
        capture_output=True,
        text=True,
    )
    if result.returncode != 2:
        raise AssertionError(f"expected exit 2 for {args!r}, got {result.returncode}: {result.stdout}")
    if expected_error not in result.stderr:
        raise AssertionError(f"expected {expected_error!r} in stderr for {args!r}: {result.stderr}")
    if result.stdout.strip():
        raise AssertionError(f"invalid input emitted stdout for {args!r}: {result.stdout}")


def assert_numeric_boundaries(failures: list[str]) -> None:
    """Reject non-finite/negative overrides and accept finite boundaries."""
    try:
        for option in (
            "--managed-usd-mo",
            "--managed-credits-mo",
            "--override-gpu-spot",
            "--override-engineer",
        ):
            for value in ("nan", "inf", "-inf"):
                option_args = [f"{option}={value}"] if value.startswith("-") else [option, value]
                assert_invalid_input(["--streams", "1", *option_args], f"{option} must be finite")
            assert_invalid_input(["--streams", "1", f"{option}=-0.01"], f"{option} must be >= 0")

        zero = run_json(
            [
                "--streams",
                "1",
                "--managed-usd-mo",
                "0",
                "--managed-quote-as-of",
                "2026-07-01",
            ]
        )
        if zero["managed"]["total_mo"] != 0:
            raise AssertionError("zero managed override was not preserved")
        extreme = run_json(["--streams", "1", "--override-engineer", "1e100"])
        if extreme["diy"]["setup_one_time"] <= 0:
            raise AssertionError("extreme finite override did not produce a finite cost")
        assert_invalid_input(
            ["--streams", "1", "--override-engineer", "1e308"],
            "computed result",
        )
        print("  PASS [numeric-boundaries] non-finite/negative rejected; finite bounds accepted")
    except (AssertionError, ValueError) as exc:
        failures.append(f"[numeric-boundaries] {exc}")


def assert_source_citations(text: str, fixture_name: str) -> None:
    """Every sourced line containing ~$... must also contain [source: ..., as_of: ...].

    Derived totals (Total run-rate, Crossover) are exempt — their inputs already carry sources.
    """
    # Lines that aggregate sourced inputs; no independent source needed.
    EXEMPT_PREFIXES = (
        "Total run-rate:",
        "Crossover:",
        "Scaling cliff:",
        "Recommendation:",  # abstention message restates already-sourced totals
    )
    failures = []
    for i, line in enumerate(text.splitlines(), 1):
        stripped = line.strip()
        if any(stripped.startswith(p) for p in EXEMPT_PREFIXES):
            continue
        if DOLLAR_LINE_PATTERN.search(line) and not SOURCE_PATTERN.search(line):
            failures.append(f"  line {i}: {stripped}")
    if failures:
        raise AssertionError(
            f"[{fixture_name}] Lines with dollar amounts but no source citation:\n" + "\n".join(failures)
        )


def assert_snapshot_fresh(failures: list[str]) -> None:
    """Staleness canary: fail when the committed snapshot is too old.

    Override with ALLOW_STALE_SNAPSHOT=1 for a deliberate stale run.
    """
    import os
    from datetime import date, datetime

    if os.environ.get("ALLOW_STALE_SNAPSHOT") == "1":
        print("  SKIP snapshot staleness (ALLOW_STALE_SNAPSHOT=1)")
        return
    snap = json.loads(SNAPSHOT.read_text())
    as_of = datetime.strptime(snap["as_of"], "%Y-%m-%d").date()
    age = (date.today() - as_of).days
    if age > MAX_SNAPSHOT_AGE_DAYS:
        failures.append(
            f"[staleness] PRICING_SNAPSHOT.json as_of={snap['as_of']} is {age} days old "
            f"(max {MAX_SNAPSHOT_AGE_DAYS}) — refresh rates or set ALLOW_STALE_SNAPSHOT=1"
        )
    else:
        print(f"  PASS [staleness] snapshot age {age}d <= {MAX_SNAPSHOT_AGE_DAYS}d")


def assert_monotonicity(failures: list[str]) -> None:
    """Monotonicity property checks over a streams sweep with a fixed real quote."""
    base = [
        "--model-size",
        "medium",
        "--uptime",
        "24x7",
        "--managed-usd-mo",
        "1000",
        "--managed-quote-as-of",
        "2026-07-01",
    ]
    prev_total = 0.0
    prev_instances = 0
    ok = True
    for streams in SWEEP_STREAMS:
        data = run_json(["--streams", str(streams), *base])
        diy = data["diy"]
        if diy["total_run_rate_mo"] < prev_total:
            failures.append(
                f"[monotonic] DIY total decreased at streams={streams}: {diy['total_run_rate_mo']} < {prev_total}"
            )
            ok = False
        if diy["n_instances"] < prev_instances:
            failures.append(f"[monotonic] instance count decreased at streams={streams}")
            ok = False
        if data["scaling_cliff_incremental_usd_mo"] < 0:
            failures.append(f"[monotonic] negative scaling-cliff increment at streams={streams}")
            ok = False
        if data["crossover_months"] is not None and data["crossover_months"] < 0:
            failures.append(f"[monotonic] negative crossover_months at streams={streams}")
            ok = False
        prev_total = diy["total_run_rate_mo"]
        prev_instances = diy["n_instances"]
    if ok:
        print(f"  PASS [monotonic] {len(SWEEP_STREAMS)}-point sweep properties hold")


def assert_fps_capacity(failures: list[str]) -> None:
    """Require higher requested frame rates to increase estimated capacity."""
    try:
        estimates = [run_json(["--streams", "4", "--model-size", "medium", "--fps", str(fps)]) for fps in (1, 10, 60)]
        counts = [estimate["diy"]["n_instances"] for estimate in estimates]
        if counts != sorted(counts) or counts[0] == counts[-1]:
            raise AssertionError(f"FPS did not materially affect instance capacity: {counts}")
        print(f"  PASS [fps-capacity] instance estimates rise with FPS: {counts}")
    except AssertionError as exc:
        failures.append(f"[fps-capacity] {exc}")


def assert_quote_provenance(failures: list[str]) -> None:
    """Require a dated managed quote and preserve its supplied date."""
    try:
        assert_invalid_input(
            ["--streams", "1", "--managed-usd-mo", "100"],
            "--managed-usd-mo requires --managed-quote-as-of",
        )
        assert_invalid_input(
            ["--streams", "1", "--managed-quote-as-of", "2026-07-01"],
            "--managed-quote-as-of requires --managed-usd-mo",
        )
        data = run_json(
            [
                "--streams",
                "1",
                "--managed-usd-mo",
                "100",
                "--managed-quote-as-of",
                "2026-07-01",
            ]
        )
        if data["sources"]["managed_as_of"] != "2026-07-01":
            raise AssertionError("user-supplied managed quote date was not preserved")
        print("  PASS [quote-provenance] dated quote required and preserved")
    except AssertionError as exc:
        failures.append(f"[quote-provenance] {exc}")


def assert_abstention_sweep(failures: list[str]) -> None:
    """Abstention sweep: without a real quote, no point may emit a diy/managed verdict."""
    ok = True
    for streams in SWEEP_STREAMS:
        data = run_json(["--streams", str(streams), "--model-size", "medium", "--uptime", "24x7"])
        if data["recommendation"] != "insufficient-data":
            failures.append(
                f"[abstention] streams={streams}: expected insufficient-data, got {data['recommendation']!r}"
            )
            ok = False
    if ok:
        print(f"  PASS [abstention] no verdict without a quote across {len(SWEEP_STREAMS)} points")


def assert_acceptance_binding(failures: list[str]) -> None:
    """Require decision-grade economics to preserve the frozen acceptance digest."""
    try:
        unbound = run_json(["--streams", "1"])
        if unbound["proof"]["status"] != "unbound":
            raise AssertionError("default economics did not declare unbound assumptions")
        with tempfile.TemporaryDirectory() as directory:
            acceptance = Path(directory) / "acceptance.json"
            acceptance.write_text(
                json.dumps({"schema_version": "1", "acceptance_id": "cost/v1"}),
                encoding="utf-8",
            )
            assert_invalid_input(
                ["--streams", "1", "--acceptance", str(acceptance)],
                "missing frozen acceptance fields",
            )
            acceptance.write_text(
                json.dumps(
                    {
                        "schema_version": "1",
                        "acceptance_id": "cost/v1",
                        "frozen_at": "2026-08-11T00:00:00Z",
                        "metric": "mAP@50",
                        "comparator": "gte",
                        "threshold": 0.65,
                        "unit": "fraction",
                        "dataset_sha256": "a" * 64,
                        "model_or_pipeline": "fixture/v1",
                        "confirmed_by": "fixture owner",
                    }
                ),
                encoding="utf-8",
            )
            bound = run_json(["--streams", "1", "--acceptance", str(acceptance)])
            if bound["proof"]["status"] != "bound":
                raise AssertionError("acceptance input did not bind economic output")
            if bound["proof"]["acceptance_id"] != "cost/v1":
                raise AssertionError("economic output acceptance ID drifted")
            if len(bound["proof"]["acceptance_sha256"]) != 64:
                raise AssertionError("economic output omitted acceptance digest")
        print("  PASS [acceptance-binding] bound and unbound scopes are explicit")
    except AssertionError as exc:
        failures.append(f"[acceptance-binding] {exc}")


def credit_args(credits: str, as_of: str = CREDITS_AS_OF) -> list[str]:
    """Return a 1-stream run with a sourced, dated credits/month figure."""
    return [
        "--streams",
        "1",
        "--managed-credits-mo",
        credits,
        "--credits-source",
        "eval: user-stated monthly credit usage",
        "--credits-as-of",
        as_of,
    ]


def assert_credit_plan(failures: list[str]) -> None:
    """Credits need dated provenance; anchors price as stated; dates stay distinct."""
    tomorrow = (date.today() + timedelta(days=1)).isoformat()
    invalid_cases = (
        (credit_args("100")[:-2], "--managed-credits-mo requires --credits-as-of"),
        (
            ["--streams", "1", "--managed-credits-mo", "100", "--credits-as-of", CREDITS_AS_OF],
            "--managed-credits-mo requires --credits-source",
        ),
        (["--streams", "1", "--credits-as-of", CREDITS_AS_OF], "--credits-as-of requires --managed-credits-mo"),
        (["--streams", "1", "--credits-source", "x"], "--credits-source requires --managed-credits-mo"),
        (credit_args("100", tomorrow), "--credits-as-of cannot be in the future"),
        (credit_args("100", "01/10/2026"), "--credits-as-of must be an ISO date"),
        (credit_args("100")[:5] + ["   "] + credit_args("100")[6:], "--credits-source must be non-empty text"),
    )
    try:
        for args, expected_error in invalid_cases:
            assert_invalid_input(args, expected_error)
        for credits, (plan, total) in CREDIT_PLAN_BOUNDARIES.items():
            managed = run_json(credit_args(credits))["managed"]
            got = (managed["basis"], managed["credit_plan"]["plan"], managed["total_mo"])
            if got != ("public-credit-plan", plan, total):
                raise AssertionError(f"{credits} credits/mo priced as {got}, expected {(plan, total)}")
        beyond = run_json(credit_args("500.5"))
        if beyond["recommendation"] != "insufficient-data" or beyond["managed"]["total_mo"] is not None:
            raise AssertionError("credits above the Core ceiling were priced instead of abstaining")
        priced = run_json(credit_args("100"))
        snapshot_as_of = json.loads(SNAPSHOT.read_text())["sources"]["roboflow_managed"]["as_of"]
        if priced["sources"]["managed_as_of"] != snapshot_as_of:
            raise AssertionError("credit-plan pricing date must be the snapshot date")
        if priced["managed"]["credit_plan"]["credits_as_of"] != CREDITS_AS_OF:
            raise AssertionError("user-supplied credits date was not preserved")
        if not priced["managed"]["caveat"] or "Enterprise" not in priced["managed"]["caveat"]:
            raise AssertionError("credit-plan estimate lost its Enterprise scope caveat")
        print(f"  PASS [credit-plan] provenance enforced; {len(CREDIT_PLAN_BOUNDARIES)} anchor boundaries priced")
    except AssertionError as exc:
        failures.append(f"[credit-plan] {exc}")


def _managed_value(data: dict, path: tuple[str, ...]) -> object:
    """Walk ``path`` under the payload's managed block; None when absent."""
    node: object = data["managed"]
    for key in path:
        if not isinstance(node, dict):
            return None
        node = node.get(key)
    return node


def check_fixture(fixture_path: Path, failures: list[str]) -> None:
    """Run one fixture: recommendation, optional managed expectations, citations."""
    fixture = json.loads(fixture_path.read_text())
    name = fixture_path.stem
    args = fixture["args"]
    expected = fixture["expect_recommendation"]
    try:
        data = run_json(args)
    except AssertionError as exc:
        failures.append(f"[{name}] JSON run failed: {exc}")
        return
    actual = data["recommendation"]
    if actual != expected:
        failures.append(
            f"[{name}] recommendation: expected '{expected}', got '{actual}'\n  reason: {data.get('reason', '?')}"
        )
    else:
        print(f"  PASS [{name}] recommendation={actual}")
    for key, path in FIXTURE_MANAGED_EXPECTATIONS.items():
        if key in fixture and _managed_value(data, path) != fixture[key]:
            failures.append(f"[{name}] {key}: expected {fixture[key]!r}, got {_managed_value(data, path)!r}")
    try:
        text = run_text(args)
        assert_source_citations(text, name)
        print(f"  PASS [{name}] source citations present")
    except AssertionError as exc:
        failures.append(str(exc))


class _CountingRequests:
    """Stand-in for the ``requests`` module that counts fetches and never touches the network."""

    def __init__(self) -> None:
        self.calls = 0

    def get(self, url: str, timeout: float = 0) -> None:
        """Count one fetch, then fail the way an unreachable host would."""
        self.calls += 1
        raise OSError(f"network is off in this check: {url}")


def assert_no_network_by_default(failures: list[str]) -> None:
    """The default run must fetch nothing; only ``--check-sources`` may fetch."""
    spec = importlib.util.spec_from_file_location("sentinel_cost_model", SCRIPT)
    if spec is None or spec.loader is None:
        failures.append(f"could not load {SCRIPT}")
        return
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    for extra, expect_fetches in ((), False), (("--check-sources",), True):
        stub = _CountingRequests()
        setattr(module, "requests", stub)  # noqa: B010 - the loaded module has no static type
        with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
            code = module.main(["--streams", "1", "--json", *extra])
        if code != 0:
            failures.append(f"cost_model {list(extra)} exited {code} with the network stubbed out")
        if bool(stub.calls) != expect_fetches:
            failures.append(f"cost_model {list(extra)} made {stub.calls} fetches; expected fetches: {expect_fetches}")


def _value_args(**overrides: str | None) -> list[str]:
    """Build sourced value inputs, allowing one omitted or replaced option."""
    inputs = VALUE_INPUTS | {"--" + key.replace("_", "-"): value for key, value in overrides.items()}
    return [part for key, value in inputs.items() if value is not None for part in (key, value)]


def _assert_stream_compatibility() -> None:
    """Preserve captured stream JSON and text bytes when value inputs are absent."""
    args = ["--streams", "5", *QUOTE_ARGS]
    expected = STREAM_BASELINE | {
        "workload": {"kind": "streams", "streams": 5, "images_per_day": None, "images_per_month": None},
        "value": None,
    }
    assert run_json(args) == expected
    assert hashlib.sha256(run_text([*args, "--json"]).encode()).hexdigest() == STREAM_JSON_SHA256
    text = run_text(args)
    age = (date.today() - date.fromisoformat(STREAM_BASELINE["sources"]["gpu_as_of"])).days
    if age > 30:
        text = text.replace(f" — WARNING: snapshot is {age} days old, re-confirm prices", "")
    assert hashlib.sha256(text.encode()).hexdigest() == STREAM_TEXT_SHA256


def _assert_batch_capacity() -> None:
    """Check hand-calculated aggregate GPU hours and daily instance boundaries."""
    cases = (
        ("nano", 1, 30, 1, 40),
        ("medium", 72001, 60, 1, 20),
        ("large", 864001, 750, 2, 10),
        ("large", 864000, 720, 1, 10),
    )
    for size, images, hours, instances, capacity in cases:
        args = ["--images-per-day", str(images), "--model-size", size, "--override-gpu-spot", "2"]
        data = run_json(args)
        diy = data["diy"]
        assert data["workload"] == {
            "kind": "batch",
            "streams": None,
            "images_per_day": images,
            "images_per_month": images * 30,
        }
        assert (diy["hours_per_mo"], diy["n_instances"], diy["gpu_cost_mo"]) == (hours, instances, hours * 2)
        assert diy["fps_per_stream"] is None
        assert diy["capacity_basis_images_per_second"] == capacity
        assert diy["ops_mo"] == (131.26 if instances == 1 else 262.51)
        assert diy["setup_one_time"] == {"nano": 969.28, "medium": 1453.92, "large": 2423.2}[size]
        assert diy["drift_mo"] == 150
        assert data["recommendation"] == "insufficient-data"
        assert run_json([*args, "--existing-gpu"])["diy"]["gpu_cost_mo"] == 0
        ceiling = instances * 24 * 3600 * capacity
        assert f"above {ceiling} images/day" in data["scaling_cliff"]
        assert "Each extra billed GPU hour per day adds ~$60.00/mo" in data["scaling_cliff"]
        assert "no longer fits in 24 hours on the current instances" in data["scaling_cliff"]
        assert data["scaling_cliff_incremental_usd_mo"] == 2 * 30
        assert run_json([*args, *QUOTE_ARGS])["recommendation"] in ("diy", "managed")
        text = run_text([*args, *QUOTE_ARGS])
        assert "None streams" not in text and "images/day" in text
        assert "ops hours use the stream-count table with the instance count" in text
        assert "Batch scaling:" in text and "Scaling cliff:" not in text
        assert "[source: GPU user override, as_of: " in text
        assert_source_citations(text, "batch")
    priced = run_json(["--images-per-day", "1", *credit_args("100")[2:]])
    assert priced["managed"]["total_mo"] == 519


def _assert_workload_validation() -> None:
    """Reject mixed/missing workload inputs and stream-only batch options."""
    for args, error in (
        ([], "exactly one of --streams and --images-per-day"),
        (["--streams", "1", "--images-per-day", "1"], "exactly one of --streams and --images-per-day"),
        (["--images-per-day", "0"], "--images-per-day must be >= 1"),
        (["--images-per-day", "1", "--fps", "10"], "--fps"),
        (["--images-per-day", "1", "--uptime", "24x7"], "--uptime"),
        (["--streams", "0"], "--streams must be >= 1"),
        (["--streams", "1", "--fps", "0"], "--fps must be >= 1"),
        (["--images-per-day", "1", "--decisions-per-day", "0"], "--decisions-per-day must be >= 1"),
    ):
        assert_invalid_input(args, error)


def _assert_batch_scaling() -> None:
    """Separate the hourly billing increment from the next instance's daily capacity."""
    args = ["--images-per-day", "1"]
    data = run_json(args)
    assert math.isclose(data["scaling_cliff_incremental_usd_mo"], data["sources"]["gpu_rate_usd_hr"] * 30)
    text = run_text(args)
    line = next(line for line in text.splitlines() if line.startswith("Batch scaling:"))
    assert "Each extra billed GPU hour per day adds ~$8.43/mo" in line
    assert "a further instance is needed above 1728000 images/day" in line
    assert "At 1 images/day" not in line
    assert "[source: GPU " + data["sources"]["gpu_source_url"] in line
    assert "as_of: " + data["sources"]["gpu_as_of"] in line
    assert_source_citations(text, "batch-scaling")
    try:
        assert_source_citations(SOURCE_PATTERN.sub("", line), "missing-batch-scaling-source")
    except AssertionError:
        pass
    else:
        raise AssertionError("batch scaling dollar line was exempt from source checks")
    for override, source, as_of in (
        ([], data["sources"]["gpu_source_url"], data["sources"]["gpu_as_of"]),
        (["--override-gpu-spot", "2"], "user override", date.today().isoformat()),
    ):
        text = run_text([*args, "--existing-gpu", *override])
        line = next(line for line in text.splitlines() if line.startswith("Batch scaling:"))
        assert f"[source: GPU {source}, as_of: {as_of}]" in line, line


def _assert_decisions_source() -> None:
    """Expose explicit decisions and the one-decision-per-image assumption in both formats."""
    for workload, decisions, source, daily in (
        (["--images-per-day", "1000"], [], "images-per-day, one decision per image", 1000),
        (["--images-per-day", "1000"], ["--decisions-per-day", "10"], "decisions-per-day option", 10),
        (["--streams", "5"], ["--decisions-per-day", "10"], "decisions-per-day option", 10),
    ):
        args = [*workload, *decisions, *_value_args()]
        value = run_json(args)["value"]
        assert value["decisions_per_day"] == daily
        assert value["decisions_source"] == source
        assert f"Decisions: {daily:,}/day; {daily * 30:,}/month ({source})" in run_text(args)


def _assert_large_value_display() -> None:
    """Render every value dollar amount as fixed decimals even for very large values."""
    args = [
        "--images-per-day",
        "1000",
        *QUOTE_ARGS,
        *_value_args(error_cost_usd="1e19"),
        "--model-error-rate-upper",
        "0.15",
    ]
    value = run_json(args)["value"]
    lines = run_text(args).split("Value at stake:\n", 1)[1].splitlines()
    expected = (
        ("Error cost:", "error_cost_usd", "/wrong decision"),
        ("Monthly value:", "value_at_stake_usd_mo", "/mo"),
        ("Low bound", "value_at_stake_low_usd_mo", "/mo"),
        ("Value minus DIY", "value_minus_diy_run_rate_usd_mo", "/mo"),
        ("Value minus managed:", "value_minus_managed_usd_mo", "/mo"),
    )
    for label, key, suffix in expected:
        line = next(line for line in lines if line.strip().startswith(label))
        assert f"~${value[key]:,.2f}{suffix}" in line
        amount = line.split("~$", 1)[1].split("/", 1)[0]
        assert re.fullmatch(r"-?\d{1,3}(?:,\d{3})*\.\d{2}", amount), amount


def _assert_value_cost_cites() -> None:
    """Cite the actual GPU and engineering cost inputs, including override precedence."""
    src = STREAM_BASELINE["sources"]
    today = date.today().isoformat()
    snapshot_gpu = f"[source: GPU {src['gpu_source_url']}, as_of: {src['gpu_as_of']}]"
    snapshot_engineer = f"[source: engineer {src['engineer_source_url']}, as_of: {src['engineer_as_of']}]"
    for overrides, gpu_cite, engineer_cite in (
        ([], snapshot_gpu, snapshot_engineer),
        (["--override-gpu-spot", "2"], f"[source: GPU user override, as_of: {today}]", snapshot_engineer),
        (["--override-engineer", "75"], snapshot_gpu, f"[source: engineer user override, as_of: {today}]"),
        (["--existing-gpu"], f"[source: GPU existing hardware, as_of: {today}]", snapshot_engineer),
        (
            ["--existing-gpu", "--override-gpu-spot", "2"],
            f"[source: GPU existing hardware, as_of: {today}]",
            snapshot_engineer,
        ),
    ):
        text = run_text(["--images-per-day", "1", *_value_args(), *overrides])
        line = next(line for line in text.splitlines() if "Value minus DIY run-rate:" in line)
        assert gpu_cite in line and engineer_cite in line, line
        assert (src["gpu_source_url"] in line) == (gpu_cite == snapshot_gpu)
        assert (src["engineer_source_url"] in line) == (engineer_cite == snapshot_engineer)
        assert_source_citations(text, "value-cost-cites")


def _assert_value_calculation() -> None:
    """Compute value from decisions without affecting the cost-only verdict."""
    args = ["--images-per-day", "1000", *QUOTE_ARGS]
    base = run_json(args)
    valued = run_json([*args, *_value_args(), "--model-error-rate-upper", "0.15"])
    value = valued["value"]
    expected_value = {
        "error_cost_usd": 10.0,
        "error_cost_source": "user loss ledger",
        "error_cost_as_of": "2026-07-13",
        "current_error_rate": 0.2,
        "model_error_rate": 0.1,
        "error_rates_source": "scorer evidence",
        "model_error_rate_upper": 0.15,
        "decisions_per_day": 1000,
        "decisions_source": "images-per-day, one decision per image",
        "decisions_per_month": 30000,
        "errors_avoided_mo": 3000.0,
        "value_at_stake_usd_mo": 30000.0,
        "value_at_stake_low_usd_mo": 15000.0,
        "value_minus_diy_run_rate_usd_mo": round(30000 - base["diy"]["total_run_rate_mo"], 2),
        "value_minus_managed_usd_mo": 28500.0,
    }
    assert value.keys() == expected_value.keys()
    for key, expected in expected_value.items():
        if isinstance(expected, float):
            assert math.isclose(value[key], expected, rel_tol=1e-12, abs_tol=1e-12), key
        else:
            assert value[key] == expected, key
    assert_invalid_input(["--streams", "5", "--decisions-per-day", "1000"], "error-cost value requires")
    for workload, decisions in (
        (["--streams", "5"], ["--decisions-per-day", "1000"]),
        (["--images-per-day", "1000"], []),
    ):
        for managed in ([], QUOTE_ARGS, credit_args("100")[2:]):
            plain = run_json([*workload, *managed])
            with_value = run_json([*workload, *decisions, *managed, *_value_args()])
            assert all(plain[key] == with_value[key] for key in ("recommendation", "reason", "crossover_months"))
            assert with_value["value"]["value_at_stake_low_usd_mo"] is None
    no_quote = run_json(["--images-per-day", "1000", *_value_args()])
    assert no_quote["value"]["value_minus_managed_usd_mo"] is None
    explicit = run_json(["--images-per-day", "1000", "--decisions-per-day", "10", *_value_args()])
    assert explicit["value"]["value_at_stake_usd_mo"] == 300
    text = run_text([*args, *_value_args(), "--model-error-rate-upper", "0.15"])
    assert "Value at stake" in text and "95%" in text
    assert "user loss ledger" in text and "scorer evidence" in text
    assert "Error rates: current process 0.2, model 0.1" in text
    assert_source_citations(text, "value")
    assert "Value at stake: not computed (supply --error-cost-usd, --current-error-rate, " in run_text(args)


def _assert_non_improving_value() -> None:
    """Preserve negative/zero values and describe no avoided errors."""
    for model_rate, expected in (("0.3", -30000), ("0.2", 0)):
        args = ["--images-per-day", "1000", *_value_args(model_error_rate=model_rate)]
        value = run_json(args)["value"]
        assert math.isclose(value["value_at_stake_usd_mo"], expected, rel_tol=1e-12, abs_tol=1e-12)
        assert "model avoids no errors" in run_text(args)
    zero = run_json(["--images-per-day", "1", *_value_args(error_cost_usd="0", current_error_rate="0")])
    assert zero["value"]["value_at_stake_usd_mo"] == 0


def _assert_subcent_value() -> None:
    """Preserve subcent calculations in JSON and round only the dollar display."""
    args = [
        "--images-per-day",
        "1",
        *_value_args(error_cost_usd="0.001", current_error_rate="0.1", model_error_rate="0.2"),
        "--model-error-rate-upper",
        "0.3",
    ]
    data = run_json(args)
    value = data["value"]
    assert value["value_at_stake_usd_mo"] == -0.003
    assert math.isclose(value["value_at_stake_low_usd_mo"], -0.006)
    assert value["value_minus_diy_run_rate_usd_mo"] == -0.003 - data["diy"]["total_run_rate_mo"]
    text = run_text(args)
    assert "~$0.00/wrong decision" in text and "Monthly value: ~$-0.00/mo" in text
    assert "~$-0.01/mo" in text
    assert_source_citations(text, "subcent-value")


def _assert_value_validation() -> None:
    """Reject incomplete provenance, invalid rates, future dates and missing decisions."""
    assert_invalid_input(["--images-per-day", "1", "--baseline-error-rate", "0.2"], "unrecognized arguments")
    for flag in VALUE_INPUTS:
        remaining = [item for key, val in VALUE_INPUTS.items() if key != flag for item in (key, val)]
        assert_invalid_input(["--images-per-day", "1", *remaining], flag)
    for args, error in (
        (["--model-error-rate-upper", "0.2"], "--error-cost-usd"),
        (_value_args(error_cost_as_of=(date.today() + timedelta(days=1)).isoformat()), "cannot be in the future"),
        (_value_args(error_cost_as_of="bad-date"), "--error-cost-as-of must be an ISO date"),
        (_value_args(error_cost_source="  "), "--error-cost-source must be non-empty text"),
        (_value_args(error_rates_source="  "), "--error-rates-source must be non-empty text"),
        ([*_value_args(), "--model-error-rate-upper", "0.09"], "--model-error-rate-upper"),
    ):
        assert_invalid_input(["--images-per-day", "1", *args], error)
    assert_invalid_input(["--streams", "1", *_value_args()], "--decisions-per-day")
    for option in ("error_cost_usd", "current_error_rate", "model_error_rate", "model_error_rate_upper"):
        flag = "--" + option.replace("_", "-")
        for val in ("nan", "inf", "-inf", "-0.1"):
            # Equals syntax ensures negative infinity is parsed as an option value.
            args = _value_args(**{option: None}) + [f"{flag}={val}"]
            assert_invalid_input(["--images-per-day", "1", *args], flag)
        if option != "error_cost_usd":
            assert_invalid_input(["--images-per-day", "1", *_value_args(**{option: "1.1"})], flag)
    assert_invalid_input(["--images-per-day", "1000", *_value_args(error_cost_usd="1e308")], "computed result")


def _assert_new_features(failures: list[str]) -> None:
    """Run feature checks while retaining the assertion script's compact diagnostics."""
    for check in (
        _assert_stream_compatibility,
        _assert_batch_capacity,
        _assert_batch_scaling,
        _assert_workload_validation,
        _assert_decisions_source,
        _assert_large_value_display,
        _assert_value_cost_cites,
        _assert_value_calculation,
        _assert_non_improving_value,
        _assert_subcent_value,
        _assert_value_validation,
    ):
        try:
            check()
            print(f"  PASS [{check.__name__}]")
        except (AssertionError, KeyError) as exc:
            failures.append(f"[{check.__name__}] {exc}")


def main() -> int:
    failures: list[str] = []
    assert_no_network_by_default(failures)

    for fixture_path in sorted(FIXTURES_DIR.glob("*.json")):
        check_fixture(fixture_path, failures)

    assert_snapshot_fresh(failures)
    assert_monotonicity(failures)
    assert_fps_capacity(failures)
    assert_quote_provenance(failures)
    assert_abstention_sweep(failures)
    assert_acceptance_binding(failures)
    assert_numeric_boundaries(failures)
    assert_credit_plan(failures)
    _assert_new_features(failures)

    if failures:
        print("\nFAIL:")
        for f in failures:
            print(f"  {f}")
        return 1

    print("\nAll assertions passed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
