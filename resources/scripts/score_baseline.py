#!/usr/bin/env python3
"""Score count, flag, or text predictions against independent gold labels in plain language.

Stdlib only, so a rung 0 baseline (see `resources/baseline-ladder.md`) can be measured
before any account, install, or upload. Input files are JSON Lines with one object per
image: `{"image": "<id>", "count": <int>}`, `{"image": "<id>", "flag": <bool>}`, or
`{"image": "<id>", "text": "<string>"}`. Text values may be empty and contain at most 10,000
code points. Strings are compared exactly, code point by code point: no trimming, case folding,
or Unicode normalization. Any normalization policy must be applied to both files before scoring.
Text runs whose summed len(gold) * len(prediction) exceeds MAX_TEXT_COMPARE_CELLS = 200_000_000
are refused before scoring; split long documents into fields to stay within this comparison budget.

The printed line names the target metric's numerator and denominator, its point estimate,
and a 95% interval. Binomial rates (every flag metric, `exact_count_rate`, and `exact_match_rate`) use the Wilson
score interval. Count metrics built from per-image sums (`count_mae`, count `catch_rate`,
`over_count_rate`) use a percentile bootstrap over images with a fixed seed and resample
count, so the same files always print the same line; a resample whose denominator is zero
is skipped. Text `char_error_rate` uses the same image bootstrap: total unit-cost Levenshtein
distance over code points divided by total gold length. Missing text predictions are empty for
this distance and always non-matches for `exact_match_rate`, including when the gold is empty.

Verdict rule, for comparator `gte` (`lte` mirrors it):

- PASS: the whole interval meets the target (lower bound >= threshold; `lte`: upper <= threshold).
- BELOW-TARGET: the whole interval misses it (upper < threshold; `lte`: lower > threshold).
- INCONCLUSIVE: the interval includes the target, so the sample cannot settle it yet.
- NO VERDICT: any gold image has no prediction, the metric's denominator is zero, or too few
  independent units back it. A binomial rate needs MIN_DENOMINATOR units in its denominator. A
  bootstrap metric needs MIN_BOOTSTRAP_UNITS images that carry its denominator, because a
  percentile bootstrap is too narrow on a handful of images. A bootstrap interval of zero width
  (every image gave the same result) also gets no verdict: resampling identical images cannot
  show uncertainty, and `exact_count_rate` (text: `exact_match_rate`) answers that case with a Wilson interval.

Exit codes: 0 whenever a verdict line is printed and any requested evidence file is written,
NO VERDICT included; 2 when the input is unusable (malformed labels, predictions for unknown
images, a missing or invalid target) and nothing is scored, or when the evidence file cannot be
written. Only PASS sets `passes_acceptance` in the machine record.

Optional freeze check: with `--frozen-ledger <ledger>`, the scorer reads both files' shape, then
requires a successful `predictions_frozen` ledger row (written by `freeze_predictions.py`) holding
the SHA-256 of both the prediction file and the gold file. A prediction file never frozen, or a gold
file changed since the freeze, exits 2 before anything is scored. A matched freeze adds sentences to
the verdict line and a `predictions_frozen` block to the record: who the freeze declares wrote the
predictions, how the labels were entered, whether labels changed after an earlier freeze or after
the prediction file was written, and whether the result counts as independent. A ledger that is not
`.vision-delivery/ledger.jsonl` gets a warning. Without the option the scorer behaves as before.
"""

from __future__ import annotations

import argparse
import json
import math
import random
import sys
from dataclasses import asdict, dataclass, replace
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path
from statistics import NormalDist
from typing import Any

from prediction_freeze import LEDGER_DIR, LEDGER_NAME, FreezeCheck, require_freeze
from proof_chain import load_acceptance, sha256_file, write_json_exclusive

COUNT_METRICS = ("count_mae", "exact_count_rate", "catch_rate", "over_count_rate")
FLAG_METRICS = ("catch_rate", "false_alarm_rate", "precision", "accuracy")
TEXT_METRICS = ("exact_match_rate", "char_error_rate")
RATE_METRICS = frozenset(COUNT_METRICS + FLAG_METRICS + TEXT_METRICS) - {"count_mae"}
#: Error metrics: a target on one of these is a maximum. Every other metric is a minimum.
LOWER_IS_BETTER = frozenset({"count_mae", "over_count_rate", "false_alarm_rate", "char_error_rate"})
#: Metrics with no upper limit: count error, extra counts, and character edits per gold character.
UNBOUNDED_METRICS = frozenset({"count_mae", "over_count_rate", "char_error_rate"})
CONFIDENCE_LEVEL = 0.95
Z_SCORE = NormalDist().inv_cdf(0.5 + CONFIDENCE_LEVEL / 2)
#: Fewest independent units (real cases, images, ...) behind a metric before any verdict is given.
MIN_DENOMINATOR = 5
#: Fewest images behind a bootstrap metric; a percentile bootstrap under-covers on fewer.
MIN_BOOTSTRAP_UNITS = 20
MAX_TEXT_CODE_POINTS = 10_000
MAX_TEXT_COMPARE_CELLS = 200_000_000
BOOTSTRAP_RESAMPLES = 2000
BOOTSTRAP_SEED = 2024
INCONCLUSIVE_ADVICE = (
    "The 95% interval includes the target: label more images to settle it, or treat the result as not yet proven."
)


class Verdict(str, Enum):
    """Four-way outcome of comparing a 95% interval with the frozen target."""

    PASS = "pass"
    BELOW_TARGET = "below-target"
    INCONCLUSIVE = "inconclusive"
    NO_VERDICT = "no-verdict"

    @property
    def label(self) -> str:
        """Return the upper-case word printed in the plain line.

        Examples:
            >>> Verdict.NO_VERDICT.label, Verdict.BELOW_TARGET.label
            ('NO VERDICT', 'BELOW-TARGET')
        """
        return "NO VERDICT" if self == Verdict.NO_VERDICT else self.value.upper()


@dataclass(frozen=True)
class MetricText:
    """Plain wording for one metric: label, numerator/denominator phrase, and the nouns it counts."""

    label: str
    template: str
    den_noun: tuple[str, str]
    unit_noun: tuple[str, str]
    num_noun: tuple[str, str] = ("", "")


_REAL = ("real case", "real cases")
_CLEAN = ("clean image", "clean images")
_FLAGS = ("flag raised", "flags raised")
_IMAGES = ("image", "images")
_OBJECTS = ("labeled object", "labeled objects")
_OBJECT_IMAGES = ("image with labeled objects", "images with labeled objects")
_OF = "{num} of {den} {den_noun}"
METRIC_TEXT = {
    ("flag", "catch_rate"): MetricText("real cases caught", _OF, _REAL, _REAL),
    ("flag", "false_alarm_rate"): MetricText("clean images wrongly flagged", _OF, _CLEAN, _CLEAN),
    ("flag", "precision"): MetricText("flags that were real", _OF, _FLAGS, _FLAGS),
    ("flag", "accuracy"): MetricText("images judged correctly", _OF, _IMAGES, _IMAGES),
    ("count", "exact_count_rate"): MetricText("images counted exactly right", _OF, _IMAGES, _IMAGES),
    ("count", "catch_rate"): MetricText("per-image count agreement", _OF, _OBJECTS, _OBJECT_IMAGES),
    ("count", "over_count_rate"): MetricText(
        "extra counts per labeled object",
        "{num} {num_noun} over {den} {den_noun}",
        _OBJECTS,
        _OBJECT_IMAGES,
        ("extra count", "extra counts"),
    ),
    ("count", "count_mae"): MetricText(
        "average count error per image", "total count error {num} over {den} {den_noun}", _IMAGES, _IMAGES
    ),
    ("text", "exact_match_rate"): MetricText("texts read exactly right", _OF, _IMAGES, _IMAGES),
    ("text", "char_error_rate"): MetricText(
        "character errors per labeled character",
        "{num} {num_noun} over {den} {den_noun}",
        ("labeled character", "labeled characters"),
        ("image with labeled text", "images with labeled text"),
        ("character error", "character errors"),
    ),
}


@dataclass(frozen=True)
class Target:
    """Frozen pass rule: metric, direction, and threshold."""

    metric: str
    comparator: str
    threshold: float
    acceptance_id: str = ""
    acceptance_sha256: str = ""


@dataclass(frozen=True)
class Tally:
    """Numerator and denominator of one metric; `parts` holds per-image pairs when it is resampled by image."""

    numerator: int
    denominator: int
    parts: tuple[tuple[int, int], ...] = ()

    @property
    def value(self) -> float | None:
        """Return the point estimate, or None when the denominator is zero."""
        return self.numerator / self.denominator if self.denominator else None

    @property
    def units(self) -> int:
        """Return the independent units behind the denominator.

        Examples:
            >>> Tally(3, 4).units, Tally(9, 10, ((5, 5), (4, 5), (0, 0))).units
            (4, 2)
        """
        return sum(1 for _, denominator in self.parts if denominator) if self.parts else self.denominator

    @property
    def units_needed(self) -> int:
        """Return the fewest independent units this metric needs before a verdict.

        Examples:
            >>> Tally(3, 4).units_needed, Tally(9, 10, ((5, 5), (4, 5))).units_needed
            (5, 20)
        """
        return MIN_BOOTSTRAP_UNITS if self.parts else MIN_DENOMINATOR


@dataclass(frozen=True)
class Scored:
    """Target metric outcome: tally, 95% interval, verdict, and the plain reasons for a refusal."""

    text: MetricText
    tally: Tally
    interval: tuple[float, float] | None
    verdict: Verdict
    reasons: tuple[str, ...]
    missing: int
    images: int
    #: Counts beyond the labels that the target metric does not penalize (count `catch_rate` only).
    extra_counts: int = 0


def load_labels(path: Path, field: str) -> dict[str, Any]:
    """Read one JSONL label file keyed by image identity.

    Examples:
        >>> import tempfile, os
        >>> handle = tempfile.NamedTemporaryFile("w", suffix=".jsonl", delete=False)
        >>> _ = handle.write('{"image": "a", "count": 2}\\n'); handle.close()
        >>> load_labels(Path(handle.name), "count")
        {'a': 2}
        >>> os.unlink(handle.name)
    """
    labels: dict[str, Any] = {}
    for number, raw in enumerate(path.read_text(encoding="utf-8").split("\n"), 1):
        raw = raw.removesuffix("\r")
        if not raw.strip():
            continue
        row = json.loads(raw)
        image = row.get("image") if isinstance(row, dict) else None
        if not isinstance(image, str) or not image or field not in row:
            raise ValueError(f"{path.name}:{number} needs a non-empty 'image' and '{field}'")
        if image in labels:
            raise ValueError(f"{path.name}:{number} repeats image {image!r}")
        labels[image] = _checked_value(row[field], field, f"{path.name}:{number}")
    if not labels:
        raise ValueError(f"{path.name} has no labeled images")
    return labels


def _checked_value(value: Any, field: str, where: str) -> Any:
    """Validate count, flag, or text values; reject oversized text and lone surrogates."""
    if field == "text":
        if not isinstance(value, str):
            raise ValueError(f"{where} text must be a string")
        if len(value) > MAX_TEXT_CODE_POINTS:
            raise ValueError(f"{where} text must be at most 10,000 code points")
        if any("\ud800" <= character <= "\udfff" for character in value):
            raise ValueError(f"{where} text must not hold a lone surrogate code point")
        return value
    if field == "flag":
        if not isinstance(value, bool):
            raise ValueError(f"{where} flag must be true or false")
        return value
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise ValueError(f"{where} count must be a non-negative integer")
    return value


def _summed(parts: tuple[tuple[int, int], ...]) -> Tally:
    """Return a tally that sums per-image numerator/denominator pairs and keeps them for resampling."""
    return Tally(sum(num for num, _ in parts), sum(den for _, den in parts), parts)


def count_metrics(gold: dict[str, int], pred: dict[str, int]) -> dict[str, Tally]:
    """Tally count metrics; a missing prediction is tallied as zero, and the verdict then refuses.

    Examples:
        >>> tallies = count_metrics({"a": 2, "b": 0}, {"a": 1, "b": 1})
        >>> {name: (tally.numerator, tally.denominator) for name, tally in tallies.items()}
        {'count_mae': (2, 2), 'exact_count_rate': (0, 2), 'catch_rate': (1, 2), 'over_count_rate': (1, 2)}
    """
    pairs = [(pred.get(image, 0), truth) for image, truth in gold.items()]
    errors = tuple((abs(guess - truth), 1) for guess, truth in pairs)
    return {
        "count_mae": _summed(errors),
        "exact_count_rate": Tally(sum(error == 0 for error, _ in errors), len(pairs)),
        "catch_rate": _summed(tuple((min(guess, truth), truth) for guess, truth in pairs)),
        "over_count_rate": _summed(tuple((max(guess - truth, 0), truth) for guess, truth in pairs)),
    }


def flag_metrics(gold: dict[str, bool], pred: dict[str, bool]) -> dict[str, Tally]:
    """Tally flag metrics; a missing prediction is tallied as not flagged, and the verdict then refuses.

    Examples:
        >>> tallies = flag_metrics({"a": True, "b": False, "c": True}, {"a": True, "b": True, "c": False})
        >>> {name: (tally.numerator, tally.denominator) for name, tally in tallies.items()}
        {'catch_rate': (1, 2), 'false_alarm_rate': (1, 1), 'precision': (1, 2), 'accuracy': (1, 3)}
    """
    flagged = {image: pred.get(image, False) for image in gold}
    hits = sum(gold[image] and flagged[image] for image in gold)
    positives = sum(gold.values())
    false_alarms = sum(flagged[image] and not gold[image] for image in gold)
    return {
        "catch_rate": Tally(hits, positives),
        "false_alarm_rate": Tally(false_alarms, len(gold) - positives),
        "precision": Tally(hits, hits + false_alarms),
        "accuracy": Tally(sum(flagged[image] == gold[image] for image in gold), len(gold)),
    }


def levenshtein(gold: str, pred: str) -> int:
    """Return unit-cost insertions, deletions, and substitutions over code points.

    Two-row dynamic programming stores only the shorter string's row. Runtime is
    quadratic in string lengths, bounded here by the label loader's 10,000-code-point limit.

    Args:
        gold: Reference string, compared without normalization.
        pred: Predicted string, compared without normalization.

    Returns:
        Minimum number of single-code-point edits.

    Examples:
        >>> levenshtein("kitten", "sitting"), levenshtein("", "é😀")
        (3, 2)
        >>> levenshtein("é", "e\u0301"), levenshtein("abc", "abc")
        (2, 0)
    """
    if len(gold) < len(pred):
        gold, pred = pred, gold
    previous = list(range(len(pred) + 1))
    for row, gold_char in enumerate(gold, 1):
        current = [row]
        for column, pred_char in enumerate(pred, 1):
            current.append(min(current[-1] + 1, previous[column] + 1, previous[column - 1] + (gold_char != pred_char)))
        previous = current
    return previous[-1]


def text_metrics(gold: dict[str, str], pred: dict[str, str]) -> dict[str, Tally]:
    """Tally exact matches and character edits, retaining every image for bootstrap sampling.

    Missing predictions count as non-matches and as empty strings for edit distance.
    Empty gold contributes edits but no labeled characters or denominator units.

    Args:
        gold: Gold text keyed by image identity.
        pred: Predictions keyed by image identity.

    Returns:
        Exact-match and character-error tallies.

    Examples:
        >>> tallies = text_metrics({"a": "ab", "b": ""}, {"a": "axb", "b": "x"})
        >>> tallies["exact_match_rate"].numerator, tallies["char_error_rate"].parts
        (0, ((1, 2), (1, 0)))
        >>> text_metrics({"empty": ""}, {})["exact_match_rate"].numerator
        0
    """
    parts = tuple((levenshtein(truth, pred.get(image, "")), len(truth)) for image, truth in gold.items())
    return {
        "exact_match_rate": Tally(
            sum(image in pred and pred[image] == truth for image, truth in gold.items()), len(gold)
        ),
        "char_error_rate": _summed(parts),
    }


def wilson_interval(successes: int, trials: int, z: float = Z_SCORE) -> tuple[float, float]:
    """Return the Wilson score interval for a binomial rate.

    Examples:
        >>> [round(bound, 4) for bound in wilson_interval(34, 40)]
        [0.7093, 0.9294]
        >>> wilson_interval(0, 10)[0], wilson_interval(10, 10)[1]
        (0.0, 1.0)
    """
    if trials <= 0:
        raise ValueError("a Wilson interval needs at least one trial")
    rate = successes / trials
    spread = z * z / trials
    center = (rate + spread / 2) / (1 + spread)
    half_width = z * math.sqrt(rate * (1 - rate) / trials + spread / (4 * trials)) / (1 + spread)
    low = 0.0 if successes == 0 else max(0.0, center - half_width)
    high = 1.0 if successes == trials else min(1.0, center + half_width)
    return low, high


def _percentile(ordered: list[float], fraction: float) -> float:
    """Return a percentile of sorted values by linear interpolation between neighbours."""
    position = fraction * (len(ordered) - 1)
    below = math.floor(position)
    above = min(below + 1, len(ordered) - 1)
    return ordered[below] + (ordered[above] - ordered[below]) * (position - below)


def bootstrap_interval(
    parts: tuple[tuple[int, int], ...],
    resamples: int = BOOTSTRAP_RESAMPLES,
    seed: int = BOOTSTRAP_SEED,
) -> tuple[float, float] | None:
    """Return a seeded percentile bootstrap interval for a ratio of per-image sums.

    Images are resampled with replacement; a resample whose denominator sums to zero is skipped.

    Examples:
        >>> bootstrap_interval(((1, 1), (0, 1), (1, 1), (1, 1))) == bootstrap_interval(((1, 1), (0, 1), (1, 1), (1, 1)))
        True
        >>> bootstrap_interval(((2, 2), (3, 3)))
        (1.0, 1.0)
    """
    rng = random.Random(seed)
    ratios: list[float] = []
    for _ in range(resamples):
        drawn = rng.choices(parts, k=len(parts))
        denominator = sum(den for _, den in drawn)
        if denominator:
            ratios.append(sum(num for num, _ in drawn) / denominator)
    if not ratios:
        return None
    ratios.sort()
    tail = (1 - CONFIDENCE_LEVEL) / 2
    return _percentile(ratios, tail), _percentile(ratios, 1 - tail)


def interval_for(tally: Tally) -> tuple[float, float] | None:
    """Return the 95% interval for one tally, or None when its denominator is zero."""
    if not tally.denominator:
        return None
    if tally.parts:
        return bootstrap_interval(tally.parts)
    return wilson_interval(tally.numerator, tally.denominator)


def _noun(count: int, forms: tuple[str, str]) -> str:
    """Pick the singular or plural form for a count."""
    return forms[0] if count == 1 else forms[1]


def refusal_reasons(text: MetricText, tally: Tally, missing: int, images: int) -> tuple[str, ...]:
    """Return plain reasons that forbid a verdict; empty when a verdict may be given.

    Examples:
        >>> refusal_reasons(METRIC_TEXT[("flag", "catch_rate")], Tally(1, 1), missing=3, images=4)
        ('3 of 4 gold images have no prediction', 'there is only 1 real case, fewer than the 5 needed')
    """
    reasons: list[str] = []
    if missing:
        verb = "has" if missing == 1 else "have"
        reasons.append(f"{missing} of {images} gold {_noun(images, _IMAGES)} {verb} no prediction")
    if not tally.denominator:
        reasons.append(f"there are no {text.den_noun[1]} to measure")
    elif tally.units < tally.units_needed:
        verb = "is" if tally.units == 1 else "are"
        noun = _noun(tally.units, text.unit_noun)
        reasons.append(f"there {verb} only {tally.units} {noun}, fewer than the {tally.units_needed} needed")
    return tuple(reasons)


def decide(target: Target, interval: tuple[float, float] | None, reasons: tuple[str, ...]) -> Verdict:
    """Compare the whole 95% interval with the frozen target.

    Examples:
        >>> rule = Target("catch_rate", "gte", 0.8)
        >>> [decide(rule, bounds, ()).value for bounds in ((0.81, 0.95), (0.6, 0.79), (0.71, 0.93))]
        ['pass', 'below-target', 'inconclusive']
        >>> decide(rule, (0.9, 1.0), ("2 of 3 gold images have no prediction",)).value
        'no-verdict'
    """
    if reasons or interval is None:
        return Verdict.NO_VERDICT
    low, high = interval
    if target.comparator == "gte":
        meets, misses = low >= target.threshold, high < target.threshold
    else:
        meets, misses = high <= target.threshold, low > target.threshold
    if meets:
        return Verdict.PASS
    return Verdict.BELOW_TARGET if misses else Verdict.INCONCLUSIVE


def score_target(task: str, target: Target, tally: Tally, missing: int, images: int) -> Scored:
    """Score the target metric: interval, refusal reasons, and verdict."""
    text = METRIC_TEXT[(task, target.metric)]
    interval = interval_for(tally)
    reasons = refusal_reasons(text, tally, missing, images)
    if interval is None and tally.denominator:
        reasons += ("no resample produced a usable 95% interval",)
    elif interval is not None and tally.parts and interval[0] == interval[1]:
        exact_metric = "exact_match_rate" if task == "text" else "exact_count_rate"
        reasons += (
            "every image gave the same result, so resampling them cannot show how much the number would vary"
            f" (score {exact_metric} for a verdict on this sample)",
        )
    return Scored(text, tally, interval, decide(target, interval, reasons), reasons, missing, images)


def plain_value(metric: str, value: float, decimals: int | None = None) -> str:
    """Format a metric value for a non-specialist reader.

    Examples:
        >>> plain_value("catch_rate", 0.85), plain_value("catch_rate", 0.7996, 1), plain_value("count_mae", 0.5)
        ('85%', '80.0%', '0.50')
    """
    if metric in RATE_METRICS:
        return f"{value:.{0 if decimals is None else decimals}%}"
    return f"{value:.{2 if decimals is None else decimals}f}"


def _format_numbers(metric: str, values: list[float], threshold: float) -> list[str]:
    """Format values plus the threshold (last) so no value other than the threshold prints as it.

    Examples:
        >>> _format_numbers("catch_rate", [0.85, 0.7996], 0.8)
        ['85.00%', '79.96%', '80.00%']
        >>> _format_numbers("catch_rate", [0.85, 0.71], 0.8)
        ['85%', '71%', '80%']
    """
    base = 0 if metric in RATE_METRICS else 2
    texts: list[str] = []
    for decimals in range(base, base + 3):
        texts = [plain_value(metric, number, decimals) for number in (*values, threshold)]
        if all(number == threshold or text != texts[-1] for number, text in zip(values, texts[:-1], strict=True)):
            break
    return texts


def format_line(target: Target, scored: Scored) -> str:
    """Return the plain verdict line: counts, estimate, 95% interval, target, verdict, and what it means."""
    text, tally = scored.text, scored.tally
    measure = text.template.format(
        num=tally.numerator,
        den=tally.denominator,
        num_noun=_noun(tally.numerator, text.num_noun),
        den_noun=_noun(tally.denominator, text.den_noun),
    )
    shown = [number for number in (tally.value, *(scored.interval or ())) if number is not None]
    *numbers, threshold = _format_numbers(target.metric, shown, target.threshold)
    if not numbers:
        estimate = "no value"
    elif len(numbers) == 1:
        estimate = numbers[0]
    else:
        estimate = f"{numbers[0]}, 95% interval {numbers[1]} to {numbers[2]}"
    symbol = ">=" if target.comparator == "gte" else "<="
    parts = [
        f"{text.label[:1].upper()}{text.label[1:]}: {measure} ({estimate}); "
        f"target {symbol} {threshold}: {scored.verdict.label}."
    ]
    if scored.verdict == Verdict.INCONCLUSIVE:
        parts.append(INCONCLUSIVE_ADVICE)
    if scored.reasons:
        parts.append(f"No verdict because {', and '.join(scored.reasons)}.")
    if scored.extra_counts:
        parts.append(
            f"This number does not penalize over-counting: the predictions hold {scored.extra_counts} "
            f"{_noun(scored.extra_counts, ('count', 'counts'))} beyond the labels (see over_count_rate)."
        )
    parts.append(f"Missing predictions: {scored.missing}.")
    return " ".join(parts)


def build_record(args: argparse.Namespace, tallies: dict[str, Tally], target: Target, scored: Scored) -> dict[str, Any]:
    """Return the machine record; existing fields keep their names, new ones add counts, interval, and verdict."""
    tally = scored.tally
    low, high = scored.interval if scored.interval is not None else (None, None)
    record: dict[str, Any] = {
        "schema_version": "1",
        "measured_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "task": args.task,
        "images": scored.images,
        "metrics": {name: item.value for name, item in tallies.items()},
        "metric_counts": {
            name: {"numerator": item.numerator, "denominator": item.denominator} for name, item in tallies.items()
        },
        "target": asdict(target),
        "observed_value": tally.value,
        "numerator": tally.numerator,
        "denominator": tally.denominator,
        "interval_lower": low,
        "interval_upper": high,
        "interval_method": "bootstrap-percentile" if tally.parts else "wilson",
        "confidence_level": CONFIDENCE_LEVEL,
        "min_denominator": tally.units_needed,
        "missing_predictions": scored.missing,
        "verdict": scored.verdict.value,
        "verdict_reasons": list(scored.reasons),
        "passes_acceptance": scored.verdict == Verdict.PASS,
        "gold_sha256": sha256_file(args.gold),
        "pred_sha256": sha256_file(args.pred),
    }
    if tally.parts:
        record["bootstrap"] = {"resamples": BOOTSTRAP_RESAMPLES, "seed": BOOTSTRAP_SEED}
    return record


def resolve_target(args: argparse.Namespace, allowed: tuple[str, ...]) -> Target:
    """Return the acceptance-file target in deliver mode, or the inline target in explore mode."""
    if args.acceptance is not None:
        data = load_acceptance(args.acceptance)
        target = Target(
            str(data["metric"]),
            str(data["comparator"]),
            float(data["threshold"]),
            str(data["acceptance_id"]),
            sha256_file(args.acceptance),
        )
    elif args.metric and args.comparator and args.threshold is not None:
        target = Target(args.metric, args.comparator, args.threshold)
    else:
        raise ValueError("give --acceptance, or all of --metric, --comparator, and --threshold")
    if target.metric not in allowed:
        raise ValueError(f"metric {target.metric!r} is not scored for this task; choose one of {allowed}")
    check_target(target)
    return target


def check_target(target: Target) -> None:
    """Reject a target that any result would meet, or that points the wrong way.

    An error metric (`count_mae`, `over_count_rate`, `false_alarm_rate`, `char_error_rate`) is a maximum (`lte`);
    every other metric is a minimum (`gte`). A minimum of 0% and a maximum of 100% are met by
    every result, so they are refused.

    Examples:
        >>> check_target(Target("catch_rate", "gte", 0.8))
        >>> check_target(Target("count_mae", "lte", 0.5))
        >>> wrong = (("catch_rate", "gte", 0.0), ("accuracy", "lte", 1.0), ("count_mae", "gte", 1.0),
        ...          ("false_alarm_rate", "lte", 1.0), ("precision", "gte", 1.5))
        >>> for bad in (Target(*fields) for fields in wrong):
        ...     try:
        ...         check_target(bad)
        ...     except ValueError as exc:
        ...         print(str(exc).split(":")[0])
        threshold for catch_rate must be above 0 and at most 1 (a share of cases)
        accuracy is better when higher, so its target must be a minimum (comparator gte)
        count_mae is better when lower, so its target must be a maximum (comparator lte)
        threshold for false_alarm_rate must be at least 0 and below 1 (a share of cases)
        threshold for precision must be above 0 and at most 1 (a share of cases)
    """
    metric, threshold = target.metric, target.threshold
    if not math.isfinite(threshold):
        raise ValueError("threshold must be finite")
    lower_is_better = metric in LOWER_IS_BETTER
    wanted = "lte" if lower_is_better else "gte"
    if target.comparator != wanted:
        direction = "lower" if lower_is_better else "higher"
        bound = "maximum" if lower_is_better else "minimum"
        raise ValueError(f"{metric} is better when {direction}, so its target must be a {bound} (comparator {wanted})")
    if metric in UNBOUNDED_METRICS:
        if threshold < 0:
            raise ValueError(f"threshold for {metric} must be zero or more: got {threshold}")
    elif lower_is_better and not 0 <= threshold < 1:
        raise ValueError(f"threshold for {metric} must be at least 0 and below 1 (a share of cases): got {threshold}")
    elif not lower_is_better and not 0 < threshold <= 1:
        raise ValueError(f"threshold for {metric} must be above 0 and at most 1 (a share of cases): got {threshold}")


def load_inputs(args: argparse.Namespace, field: str) -> tuple[dict[str, Any], dict[str, Any]]:
    """Load labels, reject unknown images, and bound the aggregate text comparison workload."""
    gold = load_labels(args.gold, field)
    pred = load_labels(args.pred, field)
    extra = sorted(set(pred) - set(gold))
    if extra:
        raise ValueError(f"predictions name images missing from gold: {extra[:5]}")
    if field == "text":
        cells = sum(len(value) * len(pred.get(image, "")) for image, value in gold.items())
        if cells > MAX_TEXT_COMPARE_CELLS:
            raise ValueError(
                "text comparison exceeds MAX_TEXT_COMPARE_CELLS = "
                f"{MAX_TEXT_COMPARE_CELLS:_}; split long documents into fields"
            )
    return gold, pred


def check_freeze(ledger: Path, args: argparse.Namespace, gold: dict[str, Any]) -> FreezeCheck:
    """Require a freeze of both input files in the ledger; warn when the ledger is not a project ledger.

    Raises:
        ValueError: When the ledger holds no freeze of this prediction file and gold file.
    """
    freeze = require_freeze(ledger, args.pred, args.gold, gold)
    if not freeze.ledger_is_project_ledger:
        print(
            f"score-baseline-warning: {ledger} is not a project ledger ({LEDGER_DIR}/{LEDGER_NAME}); "
            "the evidence records ledger_is_project_ledger: false",
            file=sys.stderr,
        )
    return freeze


def parse_args() -> argparse.Namespace:
    """Parse scorer inputs."""
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--gold", required=True, type=Path)
    parser.add_argument("--pred", required=True, type=Path)
    parser.add_argument("--task", required=True, choices=("count", "flag", "text"))
    parser.add_argument("--metric")
    parser.add_argument("--comparator", choices=("gte", "lte"))
    parser.add_argument("--threshold", type=float)
    parser.add_argument("--acceptance", type=Path)
    parser.add_argument("--evidence-out", type=Path)
    parser.add_argument(
        "--frozen-ledger",
        type=Path,
        help="refuse unless this ledger froze the prediction file and the gold file before scoring",
    )
    return parser.parse_args()


def main() -> int:
    """Score predictions, print a plain verdict, and optionally write evidence."""
    args = parse_args()
    allowed = {"count": COUNT_METRICS, "flag": FLAG_METRICS, "text": TEXT_METRICS}[args.task]
    try:
        target = resolve_target(args, allowed)
        gold, pred = load_inputs(args, args.task)
        freeze = check_freeze(args.frozen_ledger, args, gold) if args.frozen_ledger is not None else None
    except (ValueError, KeyError, json.JSONDecodeError, OSError) as exc:
        print(f"score-baseline-error: {exc}", file=sys.stderr)
        return 2
    if args.task == "count":
        tallies = count_metrics(gold, pred)
    elif args.task == "flag":
        tallies = flag_metrics(gold, pred)
    else:
        tallies = text_metrics(gold, pred)
    missing = len(set(gold) - set(pred))
    scored = score_target(args.task, target, tallies[target.metric], missing, len(gold))
    if args.task == "count" and target.metric == "catch_rate":
        scored = replace(scored, extra_counts=tallies["over_count_rate"].numerator)
    line = format_line(target, scored)
    print(line if freeze is None else f"{line} {freeze.plain_note()}")
    record = build_record(args, tallies, target, scored)
    if freeze is not None:
        record["predictions_frozen"] = freeze.evidence()
    print(json.dumps(record, sort_keys=True))
    if args.evidence_out is not None:
        try:
            write_json_exclusive(args.evidence_out, record)
        except (ValueError, OSError) as exc:
            print(f"score-baseline-error: evidence not written: {exc}", file=sys.stderr)
            return 2
    return 0


if __name__ == "__main__":
    sys.exit(main())
