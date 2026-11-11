#!/usr/bin/env python3
"""Answer one question about a delivery: do its delivery checks pass.

The command runs the delivery checks in chain order over files already on disk and stops at the
first check that fails. It prints one plain line, then one JSON record. When every check passes,
the line is `DELIVERY CHECKS PASSED for acceptance <acceptance_id>.` followed by a fixed sentence
that names what the checks do not show. When one fails, the line is
`DELIVERY CHECKS FAILED: <step>: <reason>`.

The baseline step scores the label file and the prediction file again with the scorer's own
functions. The command never runs artifact code and never performs a `--execute-reviewed` step; it
checks the evidence those steps recorded. It writes no file, and no bytecode cache next to its
helpers. See `resources/threat-model.md` for what each step defends against and what no step can
defend against.

Inputs come from explicit options. A relative option path starts at `--project-root`; a path that
resolves outside the project root is unusable input. Without an option, the command looks in the
project's `.vision-delivery/` folder: one `delivery-handoff-*.json` (bound to `--acceptance` when it
is given), the acceptance file the handoff names in `acceptance_path`, the one `baseline-*.json`
and the one `economics-*.json` bound to that acceptance, `ledger.jsonl`, and the label and
prediction files whose SHA-256 the baseline names. No match, or several, is unusable input.

Exit codes: 0 the checks passed, 1 a check failed, 2 unusable input (a required file is missing,
ambiguous, or outside the project root).
"""

from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Callable
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Any

# The helpers below sit next to this file, often inside an installed plugin. Importing them must
# not write a bytecode cache there, so caching is off before the first helper import.
sys.dont_write_bytecode = True

from proof_chain import load_acceptance, load_json, sha256_file  # noqa: E402
from validate_delivery_handoff import (  # noqa: E402
    HandoffContext,
    check_delivery_contract,
    check_handoff_record,
    check_live_evidence,
    check_self_test,
)
from validate_proof_chain import (  # noqa: E402
    ChainInputs,
    ScoredFiles,
    ScoredSearch,
    chain_identity,
    check_baseline,
    check_economics,
    check_handoff_binding,
    check_later_records,
    check_ledger,
    check_report,
    load_ledger,
    newer_acceptances,
    proof_actions,
)

STATE_DIR = ".vision-delivery"
TRUST = "local-same-user"
PASSED_LINE = "DELIVERY CHECKS PASSED for acceptance {acceptance_id}."
FAILED_LINE = "DELIVERY CHECKS FAILED: {step}: {reason}"
LIMITS_SENTENCE = (
    "Every record agrees with the frozen target and with the artifact on disk; it is not shown that the scored"
    " predictions came from this artifact, and nothing is signed."
)
#: What passed checks do not show, one entry per limit that LIMITS_SENTENCE names.
NOT_SHOWN = ("that the scored predictions came from this artifact", "that any record is signed")
#: Explicit input options, by argparse attribute name.
INPUT_OPTIONS = ("handoff", "acceptance", "baseline", "economics", "ledger", "report", "gold", "pred")


class Step(str, Enum):
    """One delivery check, named after the chain step whose recorded outcome it verifies."""

    ACCEPTANCE = "acceptance"
    BASELINE = "baseline"
    HANDOFF = "handoff"
    SELF_TEST = "self-test"
    CHECK_CONTRACT = "check-contract"
    LIVE_CHECK = "live-check"
    ECONOMICS = "economics"
    LEDGER = "ledger"
    LATER_RECORDS = "later-records"
    REPORT = "report"


class StepStatus(str, Enum):
    """What happened to one step in this run."""

    PASSED = "passed"
    FAILED = "failed"
    NOT_RUN = "not-run"
    SKIPPED = "skipped"


class Outcome(str, Enum):
    """The overall answer, its JSON status, and its exit code."""

    PASSED = "passed"
    FAILED = "failed"
    UNUSABLE_INPUT = "unusable-input"

    @property
    def exit_code(self) -> int:
        """Return the process exit code for this outcome.

        Examples:
            >>> [outcome.exit_code for outcome in Outcome]
            [0, 1, 2]
        """
        return {Outcome.PASSED: 0, Outcome.FAILED: 1, Outcome.UNUSABLE_INPUT: 2}[self]

    @property
    def status(self) -> str:
        """Return the JSON `status`: `passed`, or `failed` for a failed check and for unusable input.

        Examples:
            >>> [outcome.status for outcome in Outcome]
            ['passed', 'failed', 'failed']
        """
        return Outcome.PASSED.value if self == Outcome.PASSED else Outcome.FAILED.value


class UnusableInputError(ValueError):
    """Raised when a required input file is missing, outside the project, or cannot be chosen without guessing."""


@dataclass(frozen=True)
class Binding:
    """Keep only candidate files whose JSON value at `keys` equals `digest`."""

    keys: tuple[str, ...]
    digest: str


@dataclass(frozen=True)
class DeliveryInputs:
    """Input paths fixed before the first step; a baseline or economics file left None is found by its binding."""

    project_root: Path
    acceptance: Path
    handoff: Path
    ledger: Path
    baseline: Path | None = None
    economics: Path | None = None
    report: Path | None = None
    gold: Path | None = None
    pred: Path | None = None

    @property
    def state_dir(self) -> Path:
        """Return the project's `.vision-delivery/` folder.

        Examples:
            >>> DeliveryInputs(*(Path("p"),) * 4).state_dir.as_posix()
            'p/.vision-delivery'
        """
        return self.project_root / STATE_DIR


@dataclass(frozen=True)
class StepResult:
    """The status of one step and, when it failed or could not run, why."""

    step: Step
    status: StepStatus
    reason: str = ""


@dataclass(frozen=True)
class DeliveryVerdict:
    """The answer for one delivery: outcome, per-step results, chain identity, and caveats."""

    outcome: Outcome
    steps: tuple[StepResult, ...] = ()
    reason: str = ""
    chain: dict[str, str] = field(default_factory=dict)
    inputs: dict[str, str | None] = field(default_factory=dict)
    caveats: tuple[str, ...] = ()

    @property
    def failed(self) -> StepResult | None:
        """Return the step that failed, if any.

        Examples:
            >>> DeliveryVerdict(Outcome.PASSED).failed is None
            True
        """
        return next((result for result in self.steps if result.status == StepStatus.FAILED), None)

    def line(self) -> str:
        """Return the one plain verdict line.

        Examples:
            >>> DeliveryVerdict(Outcome.PASSED, chain={"acceptance_id": "a/v1"}).line()  # doctest: +ELLIPSIS
            'DELIVERY CHECKS PASSED for acceptance a/v1. Every record agrees ..., and nothing is signed.'
            >>> failed = StepResult(Step.BASELINE, StepStatus.FAILED, "baseline verdict is inconclusive")
            >>> DeliveryVerdict(Outcome.FAILED, (failed,)).line()
            'DELIVERY CHECKS FAILED: baseline: baseline verdict is inconclusive'
            >>> DeliveryVerdict(Outcome.UNUSABLE_INPUT, reason="pass --baseline").line()
            'DELIVERY CHECKS FAILED: input: pass --baseline'
        """
        if self.outcome == Outcome.PASSED:
            head = PASSED_LINE.format(acceptance_id=self.chain.get("acceptance_id", ""))
            return " ".join(" ".join(part.split()) for part in (head, LIMITS_SENTENCE, *self.caveats))
        failed = self.failed
        step, reason = ("input", self.reason) if failed is None else (failed.step.value, failed.reason)
        return FAILED_LINE.format(step=step, reason=" ".join(reason.split()))

    def record(self) -> dict[str, Any]:
        """Return the JSON record printed after the verdict line.

        Examples:
            >>> record = DeliveryVerdict(Outcome.UNUSABLE_INPUT, reason="pass --baseline").record()
            >>> record["status"], record["failed_step"], len(record["not_shown"])
            ('failed', 'input', 2)
        """
        failed = self.failed
        failed_step = None if self.outcome == Outcome.PASSED else ("input" if failed is None else failed.step.value)
        return {
            "status": self.outcome.status,
            "trust": TRUST,
            "failed_step": failed_step,
            "reason": self.reason if failed is None else failed.reason,
            "not_shown": list(NOT_SHOWN),
            "caveats": list(self.caveats),
            "steps": [
                {"step": item.step.value, "status": item.status.value, "reason": item.reason} for item in self.steps
            ],
            "inputs": self.inputs,
            **self.chain,
        }


def _bound_to(path: Path, binding: Binding) -> bool:
    """Return whether one JSON candidate file carries the wanted digest at the binding's keys."""
    try:
        value: Any = load_json(path, "candidate file")
    except ValueError:
        return False
    for key in binding.keys:
        value = value.get(key) if isinstance(value, dict) else None
    return value == binding.digest


def discover(root: Path, pattern: str, option: str, binding: Binding | None = None) -> Path:
    """Return the one file in `.vision-delivery/` that matches the pattern and, if given, the binding.

    Args:
        root: The project root.
        pattern: The file-name pattern inside `.vision-delivery/`.
        option: The command-line option to name in the error.
        binding: Keep only files bound to this digest; unreadable files are not bound.

    Returns:
        The input file.

    Raises:
        UnusableInputError: When zero or several files match.

    Examples:
        >>> import tempfile
        >>> with tempfile.TemporaryDirectory() as folder:
        ...     discover(Path(folder), "baseline-*.json", "--baseline")
        Traceback (most recent call last):
        ...
        check_delivery.UnusableInputError: no .vision-delivery/baseline-*.json found; pass --baseline
    """
    matches = sorted(path for path in (root / STATE_DIR).glob(pattern) if path.is_file())
    qualifier = ""
    if binding is not None:
        matches = [path for path in matches if _bound_to(path, binding)]
        qualifier = " bound to this acceptance"
    if not matches:
        raise UnusableInputError(f"no {STATE_DIR}/{pattern}{qualifier} found; pass {option}")
    if len(matches) > 1:
        raise UnusableInputError(f"{len(matches)} files match {STATE_DIR}/{pattern}{qualifier}; pass {option}")
    return matches[0]


def explicit_input(root: Path, value: Path | None, option: str) -> Path | None:
    """Return an explicit input file; a relative path starts at the project root.

    Args:
        root: The resolved project root.
        value: The path given on the command line, if any.
        option: The command-line option to name in the error.

    Returns:
        The input file, or None when the option was not given.

    Raises:
        UnusableInputError: When the file resolves outside the project root or is not a file.

    Examples:
        >>> explicit_input(Path("/project"), Path("/elsewhere/baseline.json"), "--baseline")
        Traceback (most recent call last):
        ...
        check_delivery.UnusableInputError: --baseline /elsewhere/baseline.json is outside the project root /project
    """
    if value is None:
        return None
    path = value if value.is_absolute() else root / value
    if not path.resolve().is_relative_to(root):
        raise UnusableInputError(f"{option} {value} is outside the project root {root}")
    if not path.is_file():
        raise UnusableInputError(f"{option} {value} is not a file")
    return path


def acceptance_from_handoff(root: Path, handoff: Path) -> Path:
    """Return the acceptance file the handoff names in `acceptance_path`.

    Args:
        root: The project root.
        handoff: The delivery handoff file.

    Returns:
        The acceptance file.

    Raises:
        UnusableInputError: When the handoff names no readable, project-relative acceptance file.

    Examples:
        >>> import tempfile
        >>> with tempfile.TemporaryDirectory() as folder:
        ...     handoff = Path(folder) / "handoff.json"
        ...     _ = handoff.write_text('{"acceptance_path": "/abs.json"}', encoding="utf-8")
        ...     acceptance_from_handoff(Path(folder), handoff)
        Traceback (most recent call last):
        ...
        check_delivery.UnusableInputError: the handoff names no project-relative acceptance_path; pass --acceptance
    """
    try:
        data = json.loads(handoff.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise UnusableInputError(f"cannot read acceptance_path from the handoff ({exc}); pass --acceptance") from exc
    value = data.get("acceptance_path") if isinstance(data, dict) else None
    if not isinstance(value, str) or not value.strip() or Path(value).is_absolute() or ".." in Path(value).parts:
        raise UnusableInputError("the handoff names no project-relative acceptance_path; pass --acceptance")
    path = root / value
    if not path.is_file():
        raise UnusableInputError(f"the handoff acceptance_path {value} is not a file; pass --acceptance")
    return path


def _handoff_binding(acceptance: Path | None) -> Binding | None:
    """Return the binding that handoff discovery filters by when `--acceptance` is given."""
    if acceptance is None:
        return None
    try:
        return Binding(("acceptance_sha256",), sha256_file(acceptance))
    except ValueError as exc:
        raise UnusableInputError(f"--acceptance {acceptance} must be a regular non-symlink file") from exc


def resolve_inputs(args: argparse.Namespace) -> DeliveryInputs:
    """Resolve the project root, explicit options, the handoff, the acceptance file, and the ledger.

    The baseline and economics files, when not given, are found later by their binding to the
    checked acceptance.

    Args:
        args: Parsed command-line options.

    Returns:
        The resolved input paths.

    Raises:
        UnusableInputError: When the project root or a required file is missing, ambiguous, or outside the root.

    Examples:
        >>> resolve_inputs(argparse.Namespace(project_root=Path("absent-root")))
        Traceback (most recent call last):
        ...
        check_delivery.UnusableInputError: --project-root absent-root is not a folder
    """
    if not args.project_root.is_dir():
        raise UnusableInputError(f"--project-root {args.project_root} is not a folder")
    root = args.project_root.resolve()
    given = {name: explicit_input(root, getattr(args, name), f"--{name}") for name in INPUT_OPTIONS}
    acceptance = given["acceptance"]
    handoff = given["handoff"] or discover(root, "delivery-handoff-*.json", "--handoff", _handoff_binding(acceptance))
    return DeliveryInputs(
        project_root=root,
        acceptance=acceptance or acceptance_from_handoff(root, handoff),
        handoff=handoff,
        ledger=given["ledger"] or discover(root, "ledger.jsonl", "--ledger"),
        baseline=given["baseline"],
        economics=given["economics"],
        report=given["report"],
        gold=given["gold"],
        pred=given["pred"],
    )


def _required(path: Path | None, label: str) -> Path:
    """Return a path an earlier step resolved; the step order guarantees it."""
    if path is None:
        raise ValueError(f"the {label} step has not passed")
    return path


class _DeliveryRun:
    """Run the steps in order, carrying each step's checked facts to the next."""

    def __init__(self, inputs: DeliveryInputs) -> None:
        self.inputs = inputs
        self.acceptance: dict[str, Any] = {}
        self.acceptance_sha256 = ""
        self.baseline = inputs.baseline
        self.economics = inputs.economics
        self.scored: ScoredFiles | None = None
        self.handoff: HandoffContext | None = None
        self.contract: dict[str, Any] = {}
        self.records: list[dict[str, Any]] = []
        self.chain: dict[str, str] = {}
        self.caveats: tuple[str, ...] = ()

    @property
    def acceptance_id(self) -> str:
        """Return the frozen acceptance ID."""
        return str(self.acceptance["acceptance_id"])

    @property
    def context(self) -> HandoffContext:
        """Return the checked handoff; the handoff step runs before every step that reads it."""
        if self.handoff is None:
            raise ValueError("the handoff step has not passed")
        return self.handoff

    def plan(self) -> tuple[tuple[Step, Callable[[], None]], ...]:
        """Return the steps in chain order with the action that checks each one."""
        return (
            (Step.ACCEPTANCE, self.check_acceptance),
            (Step.BASELINE, self.check_baseline),
            (Step.HANDOFF, self.check_handoff),
            (Step.SELF_TEST, lambda: check_self_test(self.context)),
            (Step.CHECK_CONTRACT, self.check_contract),
            (Step.LIVE_CHECK, lambda: check_live_evidence(self.context, self.contract)),
            (Step.ECONOMICS, self.check_economics),
            (Step.LEDGER, self.check_ledger),
            (Step.LATER_RECORDS, self.check_later_records),
            (Step.REPORT, self.check_report),
        )

    def input_record(self) -> dict[str, str | None]:
        """Return the input paths used so far as plain strings for the JSON record."""
        gold = self.scored.gold if self.scored is not None else self.inputs.gold
        pred = self.scored.pred if self.scored is not None else self.inputs.pred
        paths = {
            "project_root": self.inputs.project_root,
            "acceptance": self.inputs.acceptance,
            "baseline": self.baseline,
            "gold": gold,
            "pred": pred,
            "handoff": self.inputs.handoff,
            "economics": self.economics,
            "ledger": self.inputs.ledger,
            "report": self.inputs.report,
        }
        return {name: None if path is None else str(path) for name, path in paths.items()}

    def _bound_file(self, given: Path | None, pattern: str, option: str, keys: tuple[str, ...]) -> Path:
        """Return the given file, or the one state file bound to the checked acceptance."""
        if given is not None:
            return given
        return discover(self.inputs.project_root, pattern, option, Binding(keys, self.acceptance_sha256))

    def check_acceptance(self) -> None:
        """Load and validate the frozen acceptance file."""
        self.acceptance = load_acceptance(self.inputs.acceptance)
        self.acceptance_sha256 = sha256_file(self.inputs.acceptance)

    def check_baseline(self) -> None:
        """Check the scorer evidence against the frozen acceptance and re-score its files."""
        self.baseline = self._bound_file(
            self.baseline, "baseline-*.json", "--baseline", ("target", "acceptance_sha256")
        )
        search = ScoredSearch(self.inputs.state_dir, self.inputs.gold, self.inputs.pred)
        baseline = load_json(self.baseline, "baseline result")
        self.scored = check_baseline(baseline, self.acceptance, self.acceptance_sha256, search)

    def check_handoff(self) -> None:
        """Check the handoff record and that it names the same acceptance."""
        context = check_handoff_record(self.inputs.handoff, self.inputs.project_root)
        check_handoff_binding(context.data, self.acceptance_id, self.acceptance_sha256)
        self.handoff = context

    def check_contract(self) -> None:
        """Check the delivery-check contract frozen before the live or offline run."""
        self.contract = check_delivery_contract(self.context)

    def check_economics(self) -> None:
        """Check that the economics record is bound to the frozen acceptance."""
        keys = ("proof", "acceptance_sha256")
        self.economics = self._bound_file(self.economics, "economics-*.json", "--economics", keys)
        economics = load_json(self.economics, "economics result")
        check_economics(economics, self.acceptance_id, self.acceptance_sha256)

    def check_ledger(self) -> None:
        """Check the ledger proof rows and compute the chain identity."""
        self.records = load_ledger(self.inputs.ledger)
        artifact_sha256 = self.context.artifact_sha256
        proof_rows = check_ledger(self.records, self.acceptance_id, self.acceptance_sha256, artifact_sha256)
        chain_inputs = ChainInputs(
            project_root=self.inputs.project_root,
            acceptance=self.inputs.acceptance,
            baseline=_required(self.baseline, "baseline"),
            handoff=self.inputs.handoff,
            ledger=self.inputs.ledger,
            economics=_required(self.economics, "economics"),
        )
        self.chain = {
            "acceptance_id": self.acceptance_id,
            "acceptance_sha256": self.acceptance_sha256,
            "artifact_sha256": artifact_sha256,
            "chain_id": chain_identity(chain_inputs, self.acceptance_sha256, artifact_sha256, proof_rows),
        }

    def check_later_records(self) -> None:
        """Fail on a later failed proof action or drifted recheck; collect the caveats that do not fail."""
        actions = proof_actions(self.inputs.report)
        later = check_later_records(self.records, self.acceptance_sha256, self.context.artifact_sha256, actions)
        self.caveats = later + newer_acceptances(self.inputs.state_dir, self.inputs.acceptance, self.acceptance)

    def check_report(self) -> None:
        """Check the decision report binding, when a report was given."""
        if self.inputs.report is None:
            return
        self.chain["report_sha256"] = check_report(
            self.inputs.report, self.records, self.acceptance_id, self.acceptance_sha256, self.chain["chain_id"]
        )


def _stopped(
    run: _DeliveryRun, results: list[StepResult], index: int, outcome: Outcome, reason: str
) -> DeliveryVerdict:
    """Return the verdict for a run that stopped at one step: failed, or unable to find its input."""
    plan = run.plan()
    status = StepStatus.FAILED if outcome == Outcome.FAILED else StepStatus.NOT_RUN
    steps = [*results, StepResult(plan[index][0], status, reason)]
    steps.extend(StepResult(later, StepStatus.NOT_RUN) for later, _ in plan[index + 1 :])
    return DeliveryVerdict(outcome, tuple(steps), reason=reason, inputs=run.input_record())


def run_checks(inputs: DeliveryInputs) -> DeliveryVerdict:
    """Run every step in order and stop at the first one that fails.

    Args:
        inputs: The resolved input paths.

    Returns:
        The verdict, with one result per step.

    Examples:
        >>> verdict = run_checks(DeliveryInputs(*(Path("absent"),) * 4))
        >>> verdict.line()
        'DELIVERY CHECKS FAILED: acceptance: acceptance artifact must be a regular non-symlink file'
        >>> [item.status.value for item in verdict.steps][:2]
        ['failed', 'not-run']
    """
    run = _DeliveryRun(inputs)
    results: list[StepResult] = []
    for index, (step, action) in enumerate(run.plan()):
        if step == Step.REPORT and inputs.report is None:
            results.append(StepResult(step, StepStatus.SKIPPED, "no --report given"))
            continue
        try:
            action()
        except UnusableInputError as exc:
            return _stopped(run, results, index, Outcome.UNUSABLE_INPUT, str(exc))
        except (OSError, ValueError) as exc:
            return _stopped(run, results, index, Outcome.FAILED, str(exc))
        results.append(StepResult(step, StepStatus.PASSED))
    return DeliveryVerdict(
        Outcome.PASSED, tuple(results), chain=dict(run.chain), inputs=run.input_record(), caveats=run.caveats
    )


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    """Parse the project root and optional explicit input paths."""
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    bound = "bound to the acceptance"
    parser.add_argument("--project-root", type=Path, default=Path.cwd(), help="default: the current folder")
    parser.add_argument("--handoff", type=Path, help=f"default: the one {STATE_DIR}/delivery-handoff-*.json")
    parser.add_argument("--acceptance", type=Path, help="default: the handoff's acceptance_path")
    parser.add_argument("--baseline", type=Path, help=f"default: the one {STATE_DIR}/baseline-*.json {bound}")
    parser.add_argument("--economics", type=Path, help=f"default: the one {STATE_DIR}/economics-*.json {bound}")
    parser.add_argument("--ledger", type=Path, help=f"default: {STATE_DIR}/ledger.jsonl")
    parser.add_argument("--gold", type=Path, help=f"default: the {STATE_DIR}/ file with the baseline gold_sha256")
    parser.add_argument("--pred", type=Path, help=f"default: the {STATE_DIR}/ file with the baseline pred_sha256")
    parser.add_argument("--report", type=Path, help="optional decision report to check as the last step")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    """Print the verdict line and JSON record, and return the exit code."""
    args = parse_args(argv)
    try:
        inputs = resolve_inputs(args)
    except UnusableInputError as exc:
        verdict = DeliveryVerdict(Outcome.UNUSABLE_INPUT, reason=str(exc))
    else:
        verdict = run_checks(inputs)
    print(verdict.line())
    print(json.dumps(verdict.record(), sort_keys=True))
    return verdict.outcome.exit_code


if __name__ == "__main__":
    sys.exit(main())
