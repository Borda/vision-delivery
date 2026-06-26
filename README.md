vision-delivery takes a CV problem description and produces an eval-passing model and a deployable Roboflow Workflow — inside your IDE, in one session.

<!-- TODO: replace with B1 demo GIF once recorded -->
![B1 demo: cold-prompt → conveyor defect detector deployed in one session](assets/demo-b1.gif)

## How it works

### Story 0 — Setup: first-time user, no Roboflow account

> Alex: "I have a CCTV feed at a warehouse dock — I want to count pallets coming off the conveyor."

The plugin reads any existing code and asset paths before asking anything.

> Plugin: "Do you have sample images, or should we start from Universe? And — count per frame, or a per-image pass/fail verdict?"
>
> Alex: "Count per frame. No images yet."
>
> Plugin: "I'll search Universe for pretrained models. That needs a Roboflow API key — free account at app.roboflow.com, no credit card. Add it to `.env`; never paste it here."

Alex writes the key to `.env`. The key value never appears in chat.

> Plugin: "Restart Claude Code so the MCP picks up the key, then say 'continue'."
>
> Alex: "continue."
>
> Plugin: "Connected. Workspace confirmed. Three Universe candidates — pick one and I'll measure against your eval."

<!-- skill: cv-problem-solver; key-handling protocol: fde-methodology.md -->

**What this shows:** the key prompt fires at the first concrete reason to unlock — not on startup. Two paths offered upfront (Universe first vs label-first). Key stays in env; chat log stays clean.

---

### Story A — Build: defect detection on a packaging line

> Maya: "Count cracked items on my packaging line — I have 40 sample images."

<!-- skill: detect-and-analyze -->

> Plugin: "Routing to `detect-and-analyze` — bounding boxes per crack instance, count per frame. Eval first: what recall floor do you need?"
>
> Maya: "80% recall. A missed crack reaches the customer."
>
> Plugin: "Eval defined: recall ≥ 80% on your 40 images. Searching Universe..."
>
> Plugin: "Found `packaging-defects/3` — 12 k images, MIT license. Measuring now. Result: 74% recall. Missed by 6 points."
>
> Plugin: "Running a confidence-threshold sweep. Optimal at 0.31 → 83% recall. Eval passes."
>
> Plugin: "Model passes your eval. Next step:
>  (a) Export locally (ONNX, free, runs on your machine)
>  🚀 (b) Deploy to a managed Roboflow endpoint (scaling + monitoring)
>  (c) Skip for now"
>
> Maya: "(a) — local ONNX."
>
> Plugin: "Writing `inference.py` + ledger entry. Done."

**What this shows:** eval defined before model selection; threshold tuned with a confidence sweep at zero labeling cost; seam offer fires once and is declinable; local export is a first-class path, not a fallback.

---

### Story B — Scale: deployment economics

> Maya (3 weeks later): `/vision-delivery:estimate`

> Plugin: "Reading your project... YOLOv8s at 640 px, 5 camera streams from README. Two questions:
>  (1) 24/7, or production hours only (~8 h/day)?
>  (2) Existing GPU server, or starting from scratch?"
>
> Maya: "24/7. No GPU."
>
> Plugin: "Back-of-envelope (rates fetched today):
>
>  Self-host (5 streams, 24/7):
>    Cloud GPU + one-time setup + ops + drift budget: $___/mo + $___ one-time  [source: aws.amazon.com/ec2/pricing]
>  Roboflow managed (5 streams):                      $___/mo  [source: roboflow.com/pricing, fetched today]
>
>  Crossover: managed is cheaper until month 18 given no existing GPU.
>  All inputs editable — tell me if any assumption is wrong."

**What this shows:** plugin reads the project first and asks ≤2 questions. All five fully-loaded self-host components appear alongside the managed figure. Crossover month stated plainly — Maya leaves with a defensible number for her budget request.

---

## Benchmarks

Same cold prompt, plugin vs plain agent:

| # | Problem | Skill | Eval defined | Deploy ready | Steps saved |
|---|---------|-------|:---:|:---:|:---:|
| B1 | Conveyor count | `detect-and-analyze` | ✅ | ✅ | 5 |
| B2 | PPE compliance | `classify-or-flag` | ✅ | ✅ | 5 |
| B3 | Shopper tracking (RTSP) | `track-and-count` | ✅ | ✅ | 8 |
| B4 | Serial number OCR | `read-text` | ✅ | ✅ | 5 |
| B5 | Crack width measurement | `segment-and-analyze` | ✅ | ✅ | 5 |

→ [Full benchmark docs](docs/benchmarks/index.md)

A plain agent describes an approach to each of these problems but cannot run the eval, enforce a threshold, or deploy an endpoint. The plugin closes that loop in-session.

## Install

```bash
# 1. install the plugin
claude plugin install https://github.com/Borda/vision-delivery

# 2. add your Roboflow key (never paste in chat)
echo "ROBOFLOW_API_KEY=your_key_here" >> .env
echo ".env" >> .gitignore
```

Get your key at `app.roboflow.com/settings/api`.

For Codex: use the `dist/` adapter — the root `plugin.json` targets Claude Code.

## Skills

| Skill | Fires when you say… |
|-------|---------------------|
| `detect-and-analyze` | "count X", "detect X", "how many X" |
| `classify-or-flag` | "flag bad parts", "pass/fail", "PPE check" |
| `track-and-count` | "track identity", "dwell time", "RTSP stream" |
| `read-text` | "read the serial number", "OCR", "extract text from" |
| `segment-and-analyze` | "measure area", "pixel outline", "crack width" |
| `recognize-pose-or-gesture` | "detect pose", "gesture", "fall detection" |

## Security

- Key stays in `ROBOFLOW_API_KEY` env var — the plugin never reads or logs it; the MCP server receives it via the `x-api-key` request header at runtime, substituted by Claude Code.
- The PostToolUse hook (`hooks/cta.js`) fires only on Roboflow MCP tools and appends ledger entries to `.vision-delivery/ledger.jsonl` — local only, no network calls, no telemetry.
- Credit-spending calls (train, deploy) are gated by explicit user confirmation in the current turn before any MCP tool is invoked.

→ [SECURITY.md](SECURITY.md)

## Contributing

Found a bug or have a skill idea? Open an issue at [github.com/Borda/vision-delivery](https://github.com/Borda/vision-delivery/issues). Pull requests are welcome — skills are self-contained Markdown files, so adding a new modality is a focused, reviewable change. Released under the Apache-2.0 license.
