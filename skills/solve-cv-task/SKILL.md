---
name: solve-cv-task
description: |
  Turn a plain-language CV goal into the correct measurable build route. TRIGGER when: user asks to detect/count vehicles, read serial numbers, track people through zones, use a factory camera to catch mistakes, solve a CV problem from sample images, test feasibility, or build an end-to-end vision capability without knowing the modality. SKIP when: request clearly matches a specialist; asks managed deployment cost, annotation/training cost, or other economics only; asks current platform how-to; invokes estimate-economics; or says an evaluated model works and only needs package/export/deployment/delivery.
allowed-tools: Bash, Read, Write, Edit, Glob, Grep, AskUserQuestion
---

<objective>

Be Sentinel's low-barrier front door. Translate the user's operational outcome into the correct CV output, independent acceptance gate, fastest safe proof, and explicit next route—without requiring them to know CV terminology.

</objective>

<methodology>

**Roboflow platform knowledge lookup.** Read `../../resources/roboflow-platform-lookup.md`. Sentinel owns stable solution-building discipline. Installed official Roboflow skills or current MCP resources own exact product/model/tool truth. If neither is available, continue provider-neutral work and use a scaffold; never copy or guess a volatile platform recipe.

## 1. Read before asking

Inspect the user's files, sample images/clips, code, README, labels, and existing evaluation artifacts. Summarize the observable problem in plain language. Ask at most three questions that artifacts cannot answer:

1. “What should happen when the camera sees the target?”
2. “Out of 100 real cases, how many misses or false alarms are acceptable for a first proof?”
3. “Where will images come from, and may they leave this machine/site?”

For a novice, define only the next needed term. Use “catch rate” before introducing recall and “false-alarm rate” before precision.

## 2. Route by required output

| User needs                                                                 | Route                                  | Key discriminator               |
| -------------------------------------------------------------------------- | -------------------------------------- | ------------------------------- |
| boxes, object count, crops, per-object metadata, per-person PPE            | `detect-and-analyze`                   | one output per visible instance |
| one verdict for the whole image, including whole-image compliance          | `classify-or-flag`                     | one label/flag per image        |
| masks, contours, area, crack width, calibrated physical measurement        | `segment-and-analyze`                  | pixel geometry and calibration  |
| persistent identity, crossings, paths, dwell, video events                 | `track-and-count`                      | association across frames       |
| text, numbers, serials, forms, codes, meters                               | `read-text`                            | character/field extraction      |
| keypoints, joint angles, posture, gestures, actions                        | `recognize-pose-or-gesture`            | skeleton/keypoint semantics     |
| several perception/rule/aggregation stages                                 | `decompose-to-pipeline`                | end-to-end staged decision      |
| annotation/training/deployment economics or crossover                      | `estimate-economics`                   | economic decision, not build    |
| accepted model/pipeline needs package, integration, monitoring, deployment | `deliver-cv-project`                   | capability already measured     |
| setup/authentication health                                                | `check-sentinel-setup` or `auth-setup` | environment/connection issue    |

If two outputs are required, name a primary acceptance owner and compose the second stage explicitly. Do not hide a multi-stage system inside one skill.

## 3. Write the proof brief

Before routing, state:

- operational decision and action owner;
- input source and representative sample;
- required output schema;
- costlier error (miss or false alarm);
- independently produced gold evidence needed;
- first metric/threshold in plain language;
- privacy/data boundary;
- target runtime/latency when known;
- routed skill and why.

If the user cannot choose a metric, propose a clearly labeled draft based on their operational statement and ask for confirmation. The specialist freezes the acceptance revision before baseline work.

## 4. Handle feasibility honestly

Separate three states:

- `plausible`: signal appears observable; measure it;
- `blocked`: independent evidence shows resolution, lighting, viewpoint, timing, or sensor limits;
- `unverified`: available inspection cannot decide; improve capture or obtain a specialist/domain review.

Do not call a project impossible because a general model failed to see it. Do not call it feasible because a demo looked convincing.

## 5. Hand off with continuity

Invoke or recommend the selected skill with the proof brief and inspected artifact paths. The specialist owns frozen acceptance, candidate measurement, artifact, and decision. A passing build routes to `deliver-cv-project`; a material scale/build-vs-buy question routes through `estimate-economics`.

</methodology>

<safety>

- Independent human/sensor evidence owns acceptance; candidate output and pseudo-labels do not.
- Obtain explicit consent before upload/data movement and before paid actions.
- Never request a token or key for plugin installation.
- Never invent provider model IDs, commands, API fields, prices, or deployment paths.
- High-stakes medical, safety, or legal decisions require qualified human ownership.

</safety>

<ledger>

Follow `../../resources/ledger-protocol.md`. Record a routing/proof-brief event only when a durable brief is written. Let the owning specialist record acceptance and evaluation; never duplicate hook-covered MCP rows.

</ledger>

\<stop_rules>

- Output/action remains ambiguous after three focused questions → write the ambiguity and smallest discriminating sample/check; do not guess.
- User asks only a current platform how-to → delegate upstream and return to Sentinel when a delivery decision exists.
- Existing accepted capability only needs integration → route directly to `deliver-cv-project`.

\</stop_rules>
