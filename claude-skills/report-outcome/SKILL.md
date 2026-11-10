---
name: report-outcome
description: |-
  Draft a redacted Sentinel outcome report from the project ledger and eval files, for the user to check and post themselves. TRIGGER when: the user asks to report how Sentinel went, give feedback, draft or file an outcome report, tell the maintainers what worked or what got in the way, share how the project ended, or fill in the outcome-report issue form. SKIP when: the user wants a stakeholder or manager decision report (decision-report); asks where the project stands or what step is next (status); wants a bug report or a suggestion (the bug or suggestion issue form); or wants to count, measure, label, or train.
allowed-tools: Bash, Read, AskUserQuestion
---

# Report Outcome

Turn the project's ledger into a draft of the outcome-report issue form, so the maintainers learn whether Sentinel helped on a real task. The user reviews the draft and posts it; this skill never does.

## Hard limits

- Never post, submit, or upload anything. Never run `gh`, `git push`, a browser, or any network tool, and never call a Roboflow tool.
- Never write the ledger. The helper prints the draft, or writes it to a new file the user names.
- Workspace and project identifiers, session names, acceptance IDs, file paths, and free-text notes stay out of the draft unless the user opts in to each one by name. Credentials, host names, and email and IPv4 addresses are removed in every case; no option brings them back.

## 1. Ask the user

Ask in one short message, and accept "skip" for any answer:

1. Their computer-vision experience before this session: none, some, or professional.
2. Whether Sentinel helped them reach a decision: yes, go; yes, revise or stop; or no.
3. In their own words, what got in the way or what worked well (optional).
4. Whether to include identifiers, file paths, or ledger notes. Each stays out unless they say yes to it by name.

## 2. Draft

Resolve the plugin root from the absolute path of this loaded skill file, and resolve the user's project root separately. Then run:

```bash
python3 <plugin-root>/scripts/outcome_report.py \
    --ledger <project-root>/.vision-delivery/ledger.jsonl \
    --host claude-code \
    [--experience none|some|professional] [--decision go|revise-or-stop|no] \
    [--friction "<their words>"] \
    [--include-identifiers] [--include-paths] [--include-notes]
```

Pass only the answers the user gave, and only the include flags they agreed to. Pass `--route <name>` only when the user names the route; otherwise the helper reads it from the ledger or leaves it for them. Add `--out <project-root>/outcome-report-draft.md` only when the user asks for a file; the helper never replaces an existing file.

If the helper exits 2 with `outcome-report-error: no ledger at <path>`, the ledger path is wrong: ask the user for the project folder and rerun with `--ledger`. An `outcome-report-warning` on standard error still comes with a draft; tell the user the ledger had no rows or which line numbers were skipped.

## 3. Hand over

Show the draft exactly as printed. Then tell the user:

- check every line for private data, such as customer or site names, faces, plates, and internal paths, before posting, even after redaction; the draft's own notice says the helper cannot recognize a customer, site, product, or person named in words the ledger does not hold;
- the helper filled the furthest step and the time to the first number from local records, so correct them when they are wrong;
- to post it, open the outcome-report issue form linked from the project README ("Tell us how it went") and copy each answer into the field of the same name.

Do not offer to post the report for them.
