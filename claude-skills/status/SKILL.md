---
name: status
description: |-
  Show where a Sentinel CV project stands, read-only, from the project ledger and eval files: the delivery-loop step, the locked target, the last measured result and its verdict, any open action brief or call budget, and the one next action. TRIGGER when: the user asks where the project stands, for the project status or progress, what step comes next or what to do next, to resume or continue a Sentinel project after a break, whether an action brief or call budget is still open or how many calls are left, or what the last result or verdict was. SKIP when: the user wants to count, detect, measure, score, label, or train now (the route skills); check whether Sentinel installed correctly (check-sentinel-setup); connect or sign in to Roboflow (auth-setup); estimate cost or economics (estimate-economics); or draft an outcome report or give feedback (report-outcome).
allowed-tools: Bash, Read
---

# Status

Report where a project stands without changing anything. Use it when a project resumes after a break, before choosing the next step, or when the user asks whether an action brief is still open.

## Read-only boundary

- Never write, edit, or delete the ledger or any eval file, and never run `ledger_append.py` from this skill.
- Never call a Roboflow or other provider tool, and never open a network connection.
- Never record an action brief or reserve a call budget.

## Run the status reader

Resolve the plugin root from the absolute path of this loaded skill file, and resolve the user's project root separately. Then run:

```bash
python3 <plugin-root>/scripts/ledger_report.py --status \
    --ledger <project-root>/.vision-delivery/ledger.jsonl
```

Add `--json` when you need individual fields. Report what the reader prints; do not parse the ledger or the eval files yourself. A missing ledger is a valid answer: the project has recorded nothing yet, or, when the reader warns that eval files exist without a ledger, the steps that wrote them were not recorded.

## Report

Tell the user, in plain words:

1. the step (`Step: N of 7`) and what it means;
2. the locked target, or that no target is locked yet;
3. the last measured result with its verdict, exactly as printed. Never call `INCONCLUSIVE`, `NO VERDICT`, or a verdict that is not on file a pass. A result the reader says `cannot compare with the locked target`, or was scored against `a different target than the locked one`, is not a pass of the locked target whatever verdict it shows: name the rule it was scored against. Repeat the prediction freeze as printed (`predictions frozen, predictor ...`, `not independent`, `label-change checks not on file`, or `predictions not frozen`), and never call a result independent, because the reader never says so. When the reader prints `Last recheck:`, repeat the whole line: `holds` means the latest fresh sample passed the target that row is bound to, `drifted` means it scored below it, `uncertain` means the sample could not settle it, and `unreadable` means the row carries no drift status the reader can read. When the line says `against a different target than the locked one` or `cannot compare with the locked target`, the recheck says nothing about the locked target: say so. Repeat its freeze note too (`fresh predictions not frozen`, `not independent`, or `freeze state not on file`). A recheck is one later sample, not a new baseline;
4. every open action brief: its operation, the calls used and left, and when it expires. On Claude Code the next call of that operation reaches the permission prompt with the brief; on Codex there is no gate, so the user runs the action or leaves it. A brief shown as `unknown` has a timestamp the reader cannot read: say the reader cannot tell whether a brief of that operation is open and the gate decides at the next call, and never report it as open or closed;
5. the one next action the reader prints, and every warning line.

When the reader prints a session, reuse that session id for every later ledger write and eval file in this project instead of deriving a new one.

Do not add steps, numbers, or verdicts the reader did not print. When the user wants to act on the next action, hand over to the skill it names, such as `solve-cv-task` to lock a target or `deliver-cv-project` to build proof.

## Ledger

This skill records nothing. The reader interprets the rows described in `../../resources/ledger-protocol.md`, and it judges an action brief open by the same rules as the Claude Code gate: recorded within the last 24 hours, complete, and with calls left. When a brief's timestamp is in a form the reader cannot read, it shows every brief of that operation as `unknown` instead of guessing which one the gate uses.
