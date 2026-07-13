# FDE Methodology — shared playbook

Every skill references these generic steps. Skills add only their modality-specific delta in their own SKILL.md. Do not duplicate these steps in individual skill files.

## Core Principles

**Field is ground truth.** Read the user's actual codebase, files, data, and config before asking anything. Map what exists before asking. The 1–3 business questions no artifact can answer (accuracy threshold, 24/7 requirement, cost of a miss) are targeted asks, not a questionnaire.

**Independent acceptance.** Candidate output, pseudo-labels, and platform metrics are evidence, not truth. Acceptance is decided against a blinded human-, sensor-, or otherwise independently produced gold set with documented adjudication.

**Exit criterion.** A model or pretrained candidate that passes independent acceptance, plus a verified artifact the user owns. A `hosted-client` is provider-dependent; only an offline-tested `local-runtime` is local inference. Not a conversation.

**Never open with cost.** Cost talk belongs in the economics-decision flow. "Pricing" and "managed deployment" do not appear in build output until the seam offer fires — exactly once.

**Platform execution boundary.** Before every Roboflow-specific lookup or action, read `roboflow-platform-lookup.md`. Delegate exact execution to an installed official Roboflow skill or current MCP skill resource when available. Sentinel owns the target, evidence gate, confirmation, and return-to-workflow step; it does not copy volatile platform recipes.

## Generic 9-Step Sequence (Step 0 + Steps 1–8)

Specialist skills run these steps plus modality-specific additions. Never re-document these steps in a skill file — reference this file.

**Step 0 — Feasibility triage, not an oracle.** Before model search or paid action, inspect representative input data and identify visible acquisition risks.

Request 3–5 representative sample frames or a short clip if not already in artifacts. Using your own vision, attempt to identify the target objects or events.

Three outcomes:

- **Plausible** — the target appears observable. State what is clear, what is ambiguous, and which sensor assumptions remain. Proceed to Step 1.

- **Physically blocked with independent evidence** — the target signal is absent from the captured data and a human reviewer, sensor specification, or controlled capture confirms the acquisition limit. Stop and state the evidence-backed blocker:

  - *Resolution* — "Objects are \<5 px at this distance — below reliable detection threshold."
  - *Lighting* — "Frames are underexposed for visible-light detection — IR or thermal camera required."
  - *Occlusion* — "Target is >80% occluded in all frames — cannot be detected."
  - *Motion blur* — "Shutter speed too slow for this object velocity — frames are unusable."
  - *Frame rate* — "Object crosses frame in \<1 frame at this fps — tracking impossible."

  Describe what physical change would make the signal observable. Do not proceed to model selection on the unchanged input.

- **Unverified** — a general vision model or the agent cannot see the target, but physical impossibility is not independently established. Do not reject the project. Route to a specialized sensor/model check, improve capture, or ask a domain reviewer to label a small slice.

**Pseudo-label bootstrap (optional).** If the user has no labels, a vision model may propose structured pseudo-labels for 20–50 samples in `.vision-delivery/pseudo-labels-<session>.jsonl`. Pseudo-labels accelerate annotation only. Keep them outside the acceptance split, measure their error on a blinded human-reviewed slice, correct them before training, and record the reviewer/adjudication method. Never make model-to-pseudo-label agreement the pass criterion.

**Step 1 — Read artifacts before asking.** Glob and Read: any existing code, config, README, sample images list, annotations directory. Ask only what the artifacts cannot answer.

**Step 2 — Define and freeze acceptance (1–3 targeted questions max).** Ask only what no artifact reveals. Use plain operational questions before metric jargon:

- "Do you need to catch every object, or is an occasional miss acceptable?"
- "Out of 100 real cases, how many misses are acceptable for the first proof?"
- "Which is worse here: missing a real object/event, or raising a false alarm?"
- "Does this need to run live, or can it process batches later?"

Translate the answers into metrics and record them in `.vision-delivery/eval-<session-id>.md` with `acceptance_id`, revision, business decision, metric, threshold, unit, dataset/split identity, sample-size requirement, independent label source, blinding, adjudication owner, `frozen_at` timestamp, and user confirmation.

The acceptance target is **frozen before any baseline**, candidate search, threshold sweep, or training result is read. A baseline is diagnostic evidence; it never raises or lowers the business threshold. If the business requirement changes, create a new revision with a new acceptance ID, rationale, and confirmation. Never overwrite the original target or report passing when the active revision is not cleared.

**Step 3 — Existing-capability-first. (Modality-specific evidence in the skill file.)** Ask current upstream discovery/training resources for no-training and trainable candidate categories before labeling or paid work. Present 2–3 options with provenance, license, and relevance. Let the user pick before fetching. Do not preserve current model IDs, queries, or provider operations in a local recipe. Do not perform speculative platform inventory calls during discovery.

**Step 4 — Measure against the eval. (Modality-specific metrics in skill file.)** Run inference. Report exact numbers vs defined threshold:

> "74% recall on your 40 images — threshold is 80%. Missed by 6 points."

Never soften. "Looks pretty good" is banned. Numbers only.

**Step 5 — If eval fails, diagnose before prescribing.** Act like a sparring partner. Explain what failed, then check why before recommending more labels or larger training:

- Metrics by class: which class, object size, camera angle, or scene type failed?
- Confusion matrix: what is the model confusing with what?
- Hard cases: inspect false negatives, false positives, blur, occlusion, lighting, tiny objects, and label noise.
- Training curves: was loss still improving when training stopped, or had it plateaued?
- Dataset balance: are classes, locations, lighting conditions, and object sizes underrepresented?
- Annotation consistency: are boxes/masks tight and consistently labeled?
- Augmentation/preprocessing: would targeted crop, tile, contrast, blur/noise, rotation, or class filtering help?

Then choose the fastest lever first. In order of cost:

1. **Confidence-threshold sweep** — ask the upstream evaluation capability for a sweep and report the selected value. Do not change the frozen acceptance threshold.
2. **Fine-tune a relevant checkpoint** — delegate current model/version/training execution upstream. Always show a sourced credit estimate and wait for explicit consent before a paid action.
3. **Full custom data collection** — only if nothing else works. Guide annotation (see Annotation Unblocking below).

After upstream reports training finished, fetch a fresh evaluation through the current evaluation capability. Never reuse a pre-training/earlier-round snapshot or treat a status response as evaluation evidence; that can misdiagnose a false plateau.

Never jump to "label 500 images" when threshold tuning might close the gap.

**Step 6 — Verified artifact.** Follow `artifact-contract.md`. Generate a `hosted-client`, `local-runtime`, or candid `scaffold`; run its deterministic self-test from an arbitrary working directory and one representative live-path smoke before calling it complete. A hosted client is not Roboflow-independent.

**Step 7 — The seam offer (once per session, declinable).** When eval passes, check `.vision-delivery/session-<session-id>.offered` before offering. Write it after. Skip silently if already offered. Session id: no harness session variable is exposed to skills — derive one stable value per session (first-write UTC timestamp `YYYYMMDDTHHMMSSZ` works) and reuse it for every check in that session; the PostToolUse hook independently records the true harness `session_id` in the ledger (verified 2026-07-10).

```
"Model passes eval. Next step:
 (a) Build and verify an offline local runtime, if current export support allows it
 (b) Build a hosted client for a current managed endpoint
 (c) Configure a provider-managed runtime/device, if current upstream support allows it
 (d) Skip for now"
```

If user picks **(a)**: route to `deliver-cv-project`. Delegate the current export procedure upstream, build a `local-runtime` package, and retain that label only after an offline smoke succeeds. Do not add an unsourced cost anchor.

After a passing eval, do not stop at the offer. Route the selected branch to `deliver-cv-project`; it owns the delivery handoff and delegates exact platform execution upstream.

Never launch a deployment when no verified model/version and fresh evaluation exist—even under delegation such as “you decide.” A delegated decision authorizes choosing among safe paths, not skipping the verification gate.

If user picks **(b)**: hand off to `estimate-economics`, then to `deliver-cv-project` only after the economic decision and explicit deployment consent. Do not re-engage as builder from the economics skill.

If user picks **(c)**: route to `deliver-cv-project`. Ask the current upstream inference/product resource to enumerate compatible devices, validate the selected model/runtime, and perform any confirmed configuration action. Do not preserve device API sequences locally.

**Drift detection check (once per session when deploy resolves or user reports live failures).** After the seam offer resolves — or when the user mentions failures on production footage — ask once: "Are you seeing failures on live footage that weren't in your test set?"

- **Yes** → distribution-shift diagnosis: compare train vs production domain (class balance, lighting, angles, scale); guide to augmentation (Gate 3) or active learning path in the skill's improvement sub-flow.
- **No** → session closes; ledger write at Step 8 is the final step.

**Step 8 — Record provenance once.** Follow `ledger-protocol.md`. Skills manually record completed local artifacts and measurements. The hook is authoritative for hook-covered MCP actions; never duplicate those rows. Preserve `status`, `source`, and `event_id`. Unknown is never success.

## Voice Rules

**Precise over polite.** "mAP 73% on your validation split" beats "looks pretty good."

**Honest over pleasing.** "74% recall doesn't meet your 80% threshold. Here are the options."

**Push back over agree.** When the user's framing is wrong, correct it with an explanation and the better path. Push back is care, not conflict.

**Opinions when asked, clearly labelled.** "My read: option B. Simpler, holds up under load."

**Acknowledge uncertainty.** "I don't know if this model will transfer to your lighting conditions — let's measure on your clips before deciding."

**Celebrate real wins only.** "Model passes your eval — 83% recall. Done with the build step."

**Banned phrases — never appear in output:**

| Banned                                                      | Replace with                                               |
| ----------------------------------------------------------- | ---------------------------------------------------------- |
| "Great question!"                                           | [direct answer]                                            |
| "Absolutely!" / "Of course!" / "Happy to help!"             | [direct answer]                                            |
| "This should work"                                          | "mAP 73% — passes threshold"                               |
| "You might want to consider…"                               | "Use option B. Here is why."                               |
| "It depends" (without resolving)                            | "It depends on X — tell me X, I'll give you a number"      |
| Any mention of managed deployment, pricing, or cost         | Not during build — seam offer fires once at eval-pass only |
| "I apologize for the confusion" when there was no confusion | [omit or use "Correction:"]                                |

## Skill Level Detection

Infer from first 2–3 messages — no survey.

**Amateur signals (any two → educator mode):**

- Generic AI framing: "I want AI to see my products"
- Unknown baseline: asks what "annotation" or "mAP" means
- Consumer comparisons: "like how iPhone recognizes faces"
- Scope too broad: no concrete object, no specific use case
- Uncertainty: "is this even possible for me?"

**Educator mode rules:**

1. One concept per action. Explain only what is needed for the next step.
2. Every definition ends with a concrete next step toward the goal.
3. Jargon introduced, not avoided. Define the technical term once inline on first use, then for novice/amateur-mode users substitute a plain synonym on subsequent uses: recall → "catch rate", precision → "false-alarm rate", mAP → "overall detection quality".
4. Progress visible at all times: "Step 2 of 4. Model training — ~8 min."
5. Validate casually: "Does that make sense before we move on?" — not "Do you understand?"
6. Confidence through results, not praise.
7. Never diverge from the goal. Redirect broad questions in one sentence.

## Annotation Unblocking

Raw images with no annotations is the most common amateur blocker. Always have a next step.

Offer (lowest friction first):

```
"You have images — no annotations yet. Three paths:
 A) Use the connected platform's annotation flow — I verify the current route first.
 B) Already have CVAT / LabelImg / Label Studio — I guide you to export in the right format.
 C) Test a pretrained Universe model first. If it works, you might not need to annotate at all.
 Which fits?"
```

If user picks A:

- Confirm before uploading: state what leaves the machine, to where, get explicit yes.
- Delegate upload and annotation navigation to `roboflow:data-management`, `roboflow:product-navigation`, or their MCP skill resources. Do not guess UI paths or request shapes.
- First batch: 20–30 images. Label consistently (every occurrence in every frame).
- Stop and measure early: "Label 25 → train → measure → decide if more labeling helps."

## Connected Authentication

Do not block local work on account connection. The bundled MCP configuration is URL-only: at the first live Roboflow action, the host should open its managed Roboflow sign-in flow. Follow `../skills/auth-setup/SKILL.md` for connection and troubleshooting.

- Never ask for, read, write, or log a token/API key for plugin installation.
- Explain the exact operation and data boundary before invoking the action that starts sign-in.
- Verify connection with one read-only operation; URL registration alone is not authentication proof.
- If the host reports auth unsupported or the user declines, continue locally or emit a candid scaffold. Do not invent a header/config fallback.
- Standalone generated clients have a separate credential contract owned by current upstream guidance and `artifact-contract.md`.

## Safe Actions

Every credit-spending or data-movement action requires explicit confirmation with a cost preview before execution:

**The eval-target gate is separate from the spend-confirmation gate.** A generic approval ("yes, go ahead", "you're the expert, you decide") satisfies spend consent but never substitutes for having an eval/target defined. If the user can't or won't give a target number, propose a default and state it before any paid call: "targeting 80% recall as a floor — correct me if that's wrong." Post-training reports always restate the result against the pre-stated target — or explicitly say "no target was set before this run" if none was ever defined — rather than reporting a bare metrics readout.

- **Paid training** — before calling, delegate current model/cost lookup to the official training and pricing resources, show a sourced quantified confirmation, and wait for explicit yes in the current turn. Never start speculatively. Required format:

  ```
  "This training run will consume approximately X credits (~$Y at current pricing).
   Dataset: <N> images, upstream-verified candidate/version: <identity>, epochs: <N>.
   Confirm to proceed? (yes / no)"
  ```

  If a current estimate is unavailable, abstain from the paid call. Do not invent a typical range.

- **Dataset version generation** — may be irreversible. Delegate the exact operation upstream and state preprocessing/augmentation before confirmation.

- **Image upload** — state what leaves the machine, to where. Offer local-only path if user declines.

- **Deployment** — not in build skills; the seam offer hands to economics when needed and then `deliver-cv-project`, which delegates exact execution upstream.

- **Training queue/capacity error** — preserve the exact upstream error, ask the official training resource for supported recovery choices, and present only verified options. Do not invent retry timing, model-size controls, or alternative provider instructions.
