---
name: decision-report
description: |
  Generate a portable stakeholder decision report for a CV deployment decision (Phase 2).
  TRIGGER when: user explicitly asks for a decision report, manager report, or stakeholder doc after a cost crossover has been computed; phrases: "write me a decision report", "generate a report for my manager", "I need a stakeholder doc", "produce the decision doc", "decision-report skill", "report for my team".
  SKIP when: no cost crossover exists yet — deployment-consultant must run first and deliver a crossover number; user is still in Phase 1 build work; user wants a one-paragraph summary (answer inline instead).
allowed-tools: Read, Write, Bash, Glob
---

<objective>

Emit a portable, decision-grade stakeholder report at `./decision-report-<YYYY-MM-DD>.md`.

Exit criterion: a Markdown file the user can hand to their manager. Every material number carries a source URL and `as_of` date. "Don't deploy / roll your own" is always a reachable recommendation — never omitted.

</objective>

<inputs>

Read these sources before writing. Do not ask for information the codebase already has.

| Section | Source |
|---------|--------|
| PoC result + eval data (§4) | `scripts/baseline_map.py` output, or `.vision-delivery/ledger.jsonl` for session history; Roboflow project via MCP (`projects_get`, `model_evals_get`) |
| Economics + crossover (§6) | `python scripts/cost_model.py --streams <N> ...` output — run with the user's inputs; never hardcode figures |
| Options analysis (§5) | User-stated constraints + cost_model.py DIY vs managed outputs |
| Sensitivity (§6) | Re-run `cost_model.py` with `--rate-override` flags at ±20% on each live-fetched rate; report delta |
| Eval threshold + model name | `.vision-delivery/eval-<session-id>.md` if present, else ask one targeted question |

Run `cost_model.py` first. Use its output verbatim for all economic figures — no paraphrasing, no rounding beyond what the script reports.

</inputs>

<output_structure>

Write `./decision-report-<YYYY-MM-DD>.md` with these ten sections in order:

**1. Header / metadata**
```
Owner:    <name, if known>
Version:  1.0
Status:   DRAFT
Date:     <YYYY-MM-DD>
Decision: <one sentence stating exactly what is being decided>
```

**2. Executive summary (≤1 page, written last)**
Problem → recommendation → headline cost → value/ROI → top-3 risks → explicit ask (what you need from the reader). Written last; placed first.

**3. Problem and why now**
Business problem + urgency. No urgency = acknowledge indefinite deferral is also a valid outcome.

**4. What was built and what it proves**
PoC/MVP result measured against the user's own eval. Exact numbers — mAP, recall, count-MAE — on the user's own data. No softening.

**5. Options analysis (do-nothing mandatory)**
≥3 options:
- Option A: Managed deployment (Roboflow endpoint)
- Option B: Self-host / DIY
- Option C: Do nothing / defer

Honest pros/cons for each. Do not favour managed — the report must be able to recommend B or C.

**6. Economics — sourced, dated**
One-time vs run-rate cost. Crossover point. Payback period.

Every material line must carry `[source: <URL>, as_of: <YYYY-MM-DD>]`. Lines without provenance are report failures.

Structure (copy from `cost_model.py` output — do not rewrite):
```
Self-host (<N> streams, <uptime>):
  Cloud GPU (<instance>, spot):      ~$X/mo  [source: <URL>, as_of: <date>]
  Engineer setup (<hours>h):         ~$Y one-time
  Ongoing ops (<hours>/wk):          ~$Z/mo
  Drift monitoring + retraining:     ~$W/mo
  Total run-rate:                    ~$<total>/mo + $<setup> one-time

Managed (<N> streams):               ~$<managed>/mo  [source: <URL>, as_of: <date>]

Crossover: <plain-English statement>
```

Sensitivities (±20% on each live-fetched rate — re-run cost_model.py to generate):
| Input varied | −20% | Base | +20% |
|-------------|------|------|------|
| GPU spot rate | ... | ... | ... |
| Managed price | ... | ... | ... |
| Engineer hourly | ... | ... | ... |

**7. Risk analysis**
Top risks by likelihood × impact. Mitigations. Residual risk after mitigation.

**8. Cost of inaction**
Financial, operational, and reputational cost of not deploying. Value left on the table per month/quarter. Opportunity cost.

**9. Recommendation and next steps**
State the recommendation plainly — one sentence. Roadmap: who does what by when. What decision rights are needed. What is being approved.

**10. Appendix**
- Assumptions register (all inputs, with editable override values)
- Methodology (link to `scripts/cost_model.py`)
- Full `cost_model.py` output (paste verbatim)
- Raw eval data (mAP table or link to eval file)
- References (all source URLs)

</output_structure>

<honesty_rules>

- Do-nothing (Option C) and ≥1 DIY option (Option B) are mandatory. Never omit them.
- No material number without provenance (`[source: URL, as_of: date]` on every cost line).
- The report is a decision aid, not a sales deck. It must be able to recommend "don't deploy with us."
- If cost_model.py cannot reach a live pricing source, state the snapshot date and caveat explicitly: "Rates as of YYYY-MM-DD — live fetch failed; re-fetch recommended if older than 30 days."
- Sensitivities are mandatory in §6. Run cost_model.py with overrides — do not estimate them by hand.

</honesty_rules>

<export>

After writing the Markdown file, print once:
```
→ decision-report-<YYYY-MM-DD>.md

Export to docx (requires pandoc):
  pandoc decision-report-<YYYY-MM-DD>.md -o report.docx

Markdown version is complete without pandoc.
```

Do not mention pandoc again after this one print.

</export>

<ci_assertion>

`evals/cost-model/assert_decision_report.sh` verifies the generated report:
1. Every line containing a dollar amount or "$/mo" matches `\[source: .*, as_of: \d{4}-\d{2}-\d{2}\]`
2. "Option C" or "Do nothing" or "defer" appears in the file
3. File exists and is non-empty

CI runs this against a fixture report generated from `evals/cost-model/fixtures/diy-wins.json` inputs. If assertion fails → exit 1.

</ci_assertion>

<ledger>

Follow `skills/_shared/ledger-protocol.md`. Write one record when the report file is created:
```json
{"ts": "<ISO8601>", "session": "<session-id>", "skill": "decision-report", "action": "decision_report_emitted", "entity_id": "<workspace>/<project>", "version": "0.1.0", "notes": "decision-report-<YYYY-MM-DD>.md"}
```

</ledger>
