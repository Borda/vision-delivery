---
name: decompose-to-pipeline
description: |
  Decompose a complex vision+reasoning requirement into the cheapest end-to-end pipeline that meets it. Covers: feasibility assessment (LLM as oracle), sub-task decomposition (what needs a CV model vs logic vs LLM), LLM-baseline eval generation (pseudo-labels from LLM vision, no human annotation), cheaper-model equivalence proof, and end-to-end cost + latency comparison.
  TRIGGER when: user describes a system-level or ongoing monitoring requirement ("monitor X and alert me", "analyze my footage over time", "build a system that detects X and does Y", "is it even feasible to detect X given my setup", "I want to replace an LLM call with something cheaper", multi-condition requirements combining detection + aggregation + alerting/reporting).
  SKIP when: single-frame detection or counting with no temporal or system component (→ detect-and-analyze); image-level classification (→ classify-or-flag); deployment cost question only, no unsolved build problem (→ estimate-economics); task is clearly feasible and pipeline shape is already known.
allowed-tools: Bash, Read, Write, Edit, Glob, Grep, AskUserQuestion
---

<objective>

Design and prove the cheapest pipeline that meets the user's vision+reasoning requirement end-to-end. The exit criterion is a running pipeline with a measured cost-per-frame and latency, proven to meet the user's success condition.

**What this skill covers:**

- **Feasibility gate** — LLM as oracle: if the LLM cannot detect the target in the user's sample data, no CV model can. Stop before any money is spent.
- **Sub-task decomposition** — split the requirement into components; assign each to the cheapest capable tool.
- **LLM baseline** — use LLM vision output as pseudo-labels to define the eval and generate training data without human annotation.
- **Equivalence proof** — build cheaper CV pipeline; prove it matches the LLM baseline within the eval threshold.
- **Cost + latency comparison** — before any swap is proposed, show: $/inference, ms/frame, $/month at the user's scale.

**What this skill does NOT cover:**

- Single-inference detection or counting → `detect-and-analyze`
- Deployment infrastructure sizing → `estimate-economics`
- Annotation tooling → handled inline via `fde-methodology.md` Annotation Unblocking

</objective>

<methodology>

Steps 0, 1, 7, and 8 follow the generic sequence in `skills/_shared/fde-methodology.md`. Read that file first. This section documents the decomposition-specific additions.

**Step 0 — Feasibility gate (mandatory, from fde-methodology.md).**

Run vision on 3–5 representative frames before anything else. State clearly: feasible or infeasible + specific physical reason. If infeasible, name the required hardware change and stop.

**Step 1b — Sub-task decomposition.**

Break the requirement into components. Classify each:

| Component                               | Tool                                 | When                               |
| --------------------------------------- | ------------------------------------ | ---------------------------------- |
| Per-frame detection / classification    | CV model (YOLO, RF-DETR)             | objects identifiable by appearance |
| Aggregation / counting / windowing      | Pure logic (Python)                  | no vision needed                   |
| Threshold + alert trigger               | Pure logic                           | rule-based                         |
| Anomaly / trend reasoning               | Statistics or small ML               | no LLM needed                      |
| Root-cause narrative / exception report | LLM (called on alert, not per-frame) | open-ended reasoning               |

State the decomposition to the user before building:

> "Three components: (1) per-frame defect detection → CV model, (2) rolling 10-min defect rate → Python counter, (3) spike alert + root-cause → LLM called ≤3×/day. LLM never on the inference hot path."

**Step 2b — LLM baseline generation.**

If the user has no labeled data and the task is feasible:

1. Request 20–50 sample frames.
2. Run vision on each. Produce structured output matching the target modality:
   - Detection: `{"image": "path", "objects": [{"class": "defect", "bbox": [x,y,w,h], "confidence": 0.91}]}`
   - Classification: `{"image": "path", "label": "defective", "confidence": 0.88}`
3. Write to `.vision-delivery/llm-baseline-<session>.jsonl`.
4. State the eval: "CV model must agree with LLM on ≥ 80% of these frames."

This replaces human annotation for the eval dataset. Cost: ~$0.50 for 50 frames. Speed: minutes, not days.

**Step 3b — Cheapest CV candidate search.**

Same as `detect-and-analyze` Step 3 (COCO-80 check → Universe search), but with the LLM baseline as the eval target instead of user-provided labels.

Measure candidate model against LLM baseline: agreement rate, not mAP (ground truth is the LLM, not a labeled split).

**Step 4b — Equivalence proof.**

Run CV model on the same 20–50 frames. Compare to LLM baseline:

> "YOLOv11s: 43/50 frames match LLM detections (86%). Threshold is 80%. Passes."

If it passes: CV model is proven equivalent to LLM for this task. LLM is retired from the per-frame inference path.

**Step 5b — Cost + latency table (mandatory before proposing swap).**

Never propose replacing the LLM with a CV model without showing this table:

|                              | LLM per-frame          | CV model (proposed) |
| ---------------------------- | ---------------------- | ------------------- |
| Latency                      | ~2000 ms               | ~15 ms              |
| Cost/inference               | ~$0.010                | ~$0.0003            |
| Cost/month (5 streams, 24/7) | ~$\_\_\_k              | ~$\_\_\_            |
| Agreement with LLM baseline  | 100% (is the baseline) | 86%                 |
| Eval passes?                 | —                      | ✅                  |

Fill in real numbers. Never propose the swap if: latency does not improve OR cost does not improve OR eval fails.

**Step 6b — Pipeline artifact.**

Produce a single runnable `pipeline.py` with three clear sections:

```python
# --- Section 1: Per-frame CV inference (cheap, hot path) ---
# --- Section 2: Aggregation + threshold logic (CPU, free) ---
# --- Section 3: Exception LLM call (expensive, cold path, event-driven) ---
```

Each section independently testable. Section 3 clearly marked with estimated call frequency and cost.

</methodology>

<artifact>

Three user-owned files at Step 6b:

**`pipeline.py`** — three-section runnable pipeline (template above).

**`llm-baseline-<session>.jsonl`** — LLM vision output used as eval target. Written at Step 2b, never deleted.

**`pipeline-cost-comparison.md`** — the Step 5b cost table + equivalence verdict. User keeps this as the proof that the cheaper pipeline is valid.

</artifact>

\<feasibility_blockers>

Common infeasibility reasons — state exactly, do not soften:

| Symptom                              | Root cause                                 | Required fix                                |
| ------------------------------------ | ------------------------------------------ | ------------------------------------------- |
| Frame is dark/underexposed           | Insufficient lighting or wrong camera type | Add lighting, or switch to IR/thermal       |
| Objects are tiny (\<5 px)            | Camera too far or resolution too low       | Move camera closer, or increase resolution  |
| Objects >80% occluded                | Camera angle wrong                         | Reposition camera                           |
| Motion blur                          | Shutter speed too slow                     | Increase shutter speed or reduce frame rate |
| Object crosses full frame in 1 frame | FPS too low for tracking                   | Increase frame rate                         |
| Lens cap on / camera unplugged       | Physical blockage                          | Fix hardware first                          |

Never say "let's try a bigger model" when the blocker is physical. No model fixes a closed lens.

\</feasibility_blockers>

<voice>

Follow voice rules from `skills/_shared/fde-methodology.md`. Additional rules for decomposition:

**State the component split before building.** User must agree on the decomposition before any tool is called.

**Show the cost table before proposing a swap.** Never say "this will be cheaper" without numbers.

**Name the call frequency for every LLM component.** "LLM called on alert, estimated 2–5×/day" — not "called occasionally."

**Infeasibility is not failure.** "Your camera cannot see these objects at this distance — here is what would fix it" is a successful feasibility gate. The user saved the cost of a failed pipeline.

</voice>
