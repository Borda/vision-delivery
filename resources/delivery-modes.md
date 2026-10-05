# Delivery Modes

Sentinel serves two users with one workflow. A newcomer wants a plain answer: "does this work on my images?". An engineer handing a result to production or a third party needs a tamper-evident proof chain. Use the lightest mode that fits the decision.

## Explore (default)

For feasibility, first baselines, and internal "is this worth pursuing?" decisions.

- Record the target in plain words in `.vision-delivery/eval-<session>.md`: what counts as a hit, how many misses or false alarms are acceptable out of 100, which error is worse, and the gold images. The fields of `fde-methodology.md` Step 2 still apply; they stay in the file, not in the chat.
- Freeze the target before any baseline result, exactly as in deliver mode. Say "target locked" with its time, not a digest.
- Climb `baseline-ladder.md` from rung 0 and score with `scripts/score_baseline.py` using the inline `--metric/--comparator/--threshold` target.
- Report in plain language: "caught 34 of 40 (85%); target was at least 80%; pass on a small sample of 40".
- Do not show SHA-256 digests, schema versions, ledger event IDs, or helper command lines unless the user asks. Run the helpers yourself and summarize their result.
- Explore results may say `go to deliver`, `revise`, or `stop`. They never say production-ready.

## Deliver

Switch to deliver mode when any of these is true:

- the result will run in production, feed an automated action, or reach a customer or third party;
- the user asks for a delivery handoff, packaged artifact, decision report, or a binding economics decision;
- a paid or state-changing provider action is about to be briefed;
- the user asks for an auditable record.

Deliver mode adds the full proof chain: `freeze_acceptance.py` JSON with `acceptance_sha256`, scorer evidence with `--acceptance` and `--evidence-out`, digest-bound ledger rows, artifact smoke, and the delivery handoff validators in `artifact-contract.md`. Carry the explore target forward unchanged as the first frozen revision. Changing it creates a new revision.

Tell the user once when the mode changes and why, in one sentence. The digests are for auditors and validators. The user still gets plain-language results.
