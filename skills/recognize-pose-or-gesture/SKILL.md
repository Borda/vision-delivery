---
name: recognize-pose-or-gesture
description: |
  Keypoint-based human pose estimation, gesture recognition, and action classification. Covers: body skeleton tracking (17-keypoint COCO), gesture classification from keypoints (hand raise, squat, fall, bend), ergonomics and posture analysis via joint angles, action recognition from keypoint sequences, fall detection.
  TRIGGER when: user wants keypoint-based analysis ("detect pose", "recognize gesture", "hand gesture", "body pose", "action recognition", "is the worker bending", "ergonomics", "posture analysis", "fall detection", "sign language", "raise hand detection", "squat detection", "skeleton tracking", "joint angle", "keypoints", "posture compliance", "bend detection", "gesture control", "body landmark", "person falling", "falls in footage", "raising hand", "raise their hand", "worker bending", "posture ergonomics", "squat form", "sign language detection", "skeleton", "joint angles", "keypoint"); build a pose or gesture pipeline for any of the above.
  SKIP when: user wants pixel-precise segmentation or body contour area measurement (→ segment-and-analyze); user wants image-level classification without keypoints, e.g. detecting whether a person is wearing PPE or hard hat, pass/fail image verdict (→ classify-or-flag); user wants identity tracking or path tracking across frames without pose analysis (→ track-and-count); user wants text or label extraction from images, e.g. safety sign reading (→ read-text); cost, scale, or self-hosting vs managed deployment question with no unsolved pose problem (→ deployment-consultant); user already has a working pose model and asks only about export, optimization, active learning, or integration.
allowed-tools: Bash, Read, Write, Edit, Glob, Grep, AskUserQuestion
---

<objective>

Build a working pose/gesture pipeline for the user's specific action classes and footage. The exit criterion is a model (or pretrained candidate) that passes the user's own eval and produces per-person keypoint output and derived gesture/action labels the user can act on.

**What this skill covers:**
- **Human pose estimation** — 17-keypoint COCO body skeleton; per-person keypoint coordinates and confidence
- **Gesture classification from keypoints** — hand raise, squat, fall, bend, custom actions defined by joint angle rules
- **Action recognition** — classify sequences of keypoint positions into action labels (standing, walking, falling, bending)
- **Ergonomics analysis** — joint angle computation from keypoints (spine angle, knee flexion, shoulder elevation) for posture compliance
- **Fall detection** — person in non-standing configuration inferred from skeleton orientation

**What this skill does NOT cover:**
- Identity-linked tracking across frames without pose → `track-and-count` (M4)
- Image-level classification without keypoints (e.g. PPE detection, pass/fail) → `classify-or-flag` (M4)
- Pixel-precise body contour or area measurement → `segment-and-analyze` (M4)
- Text or label extraction from images → `read-text` (M4)

</objective>

<methodology>

Steps 1, 2, 5, 7, and 8 follow the generic sequence in `skills/_shared/fde-methodology.md`. Read that file first. This section documents only the pose/gesture-specific additions.

**Step 3 — Foundation-model-first (pose-specific).**

Pose estimation has strong pretrained baselines — try before labeling or training.

**For full-body skeleton (COCO 17 keypoints):**
- Use YOLO11-pose or YOLO26-pose — pretrained on COCO; zero annotation needed for body skeleton.
- Check Universe for domain-specific pose datasets if footage is unusual (underwater, PPE-obscured body, non-standing workers):
  ```
  universe_search: "<domain> pose keypoints images>200 sort:stars"
  ```

**For hands:**
- Use MediaPipe Hand via Roboflow Workflows — zero-shot, no training, no annotation required.
- Route via `roboflow://skills/inference` for Workflows composition.

**For custom gesture classes from keypoints:**
- Prefer a rule-based classifier on top of pretrained YOLO-pose output.
- No additional model training needed for simple gestures (hand raise, squat, fall, bend).
- Define rules from joint angles computed from keypoints — see Step 4b.

**Step 4 — Measure against the eval (pose-specific metrics).**

Run inference via `models_infer` on the user's footage samples. Report these metrics when ground-truth is available:

- **OKS mAP** (Object Keypoint Similarity) — keypoint localization accuracy; primary pose metric
- **Gesture recall / precision** — when action classes are defined
- **Per-class action recall** vs the user's recall threshold

Non-negotiable format:
> "YOLO11-pose on 40 of your factory images: OKS mAP = 78%, fall-detection recall = 91%. Threshold is recall ≥ 85% — passes."

**Step 4b — Joint angle computation (when ergonomics or gesture rules requested).**

Derive gesture labels from keypoints without a second inference pass:

```python
import math

def joint_angle(a: tuple, b: tuple, c: tuple) -> float:
    """Angle at joint b formed by points a-b-c (in pixels)."""
    ba = (a[0] - b[0], a[1] - b[1])
    bc = (c[0] - b[0], c[1] - b[1])
    dot = ba[0] * bc[0] + ba[1] * bc[1]
    mag = (ba[0]**2 + ba[1]**2)**0.5 * (bc[0]**2 + bc[1]**2)**0.5
    return math.degrees(math.acos(max(-1.0, min(1.0, dot / mag)))) if mag > 0 else 0.0

# COCO 17-keypoint indices (0-indexed)
# 5=left_shoulder, 6=right_shoulder, 7=left_elbow, 8=right_elbow
# 11=left_hip, 12=right_hip, 13=left_knee, 14=right_knee
# 15=left_ankle, 16=right_ankle

def classify_pose(keypoints: list[dict]) -> str:
    """Rule-based gesture label from YOLO-pose keypoints."""
    kp = {kp["name"]: (kp["x"], kp["y"]) for kp in keypoints if kp["confidence"] > 0.4}
    # Fall: nose below hips
    if "nose" in kp and "left_hip" in kp and "right_hip" in kp:
        hip_y = (kp["left_hip"][1] + kp["right_hip"][1]) / 2
        if kp["nose"][1] > hip_y:
            return "fall"
    # Squat: knee flexion < 120°
    if all(k in kp for k in ("left_hip", "left_knee", "left_ankle")):
        angle = joint_angle(kp["left_hip"], kp["left_knee"], kp["left_ankle"])
        if angle < 120:
            return "squat"
    # Raise hand: wrist above shoulder
    if "left_wrist" in kp and "left_shoulder" in kp:
        if kp["left_wrist"][1] < kp["left_shoulder"][1]:
            return "raise_hand"
    return "standing"
```

State the precision limit: joint angle rules are geometry-based proxies. Threshold values (120°, etc.) must be calibrated on the user's footage — the defaults above are starting points.

**Step 5 — Levers (pose-specific ordering).**

Same generic order as `fde-methodology.md` (threshold sweep → fine-tune → full train), plus:

1. **Keypoint confidence threshold sweep** — filter low-confidence keypoints before angle computation; often closes recall gaps without training.
2. **Rule-based gesture classifier tuning** — adjust joint angle thresholds (no training, no annotation); fastest lever for simple gesture classes.
3. **Fine-tune YOLO-pose on domain images** — requires keypoint-annotated data, not box-annotated. If user has only box annotations, the rule-based approach (lever 2) remains the fastest path. Always show credit estimate; wait for explicit yes before calling `models_train`.

Note: fine-tuning pose requires keypoint annotations per person. Guide through Roboflow annotation UI for keypoint projects if user has unannotated footage.

**Step 6 — Artifacts.**

See `<artifact>` section for `pose_analyze.py` and `eval_definition.md` templates.

</methodology>

<artifact>

Produce these two user-owned, portable files at Step 6.

**`pose_analyze.py`** — keypoint extraction + gesture rule classifier:
```python
import requests, json, base64, sys, math
from pathlib import Path

# ponytail: no SDK — stdlib + requests only
WORKSPACE = "<workspace>"
PROJECT   = "<project>"
VERSION   = "<version>"
API_KEY   = "<from ROBOFLOW_API_KEY env>"

def joint_angle(a, b, c):
    ba = (a[0] - b[0], a[1] - b[1])
    bc = (c[0] - b[0], c[1] - b[1])
    dot = ba[0]*bc[0] + ba[1]*bc[1]
    mag = (ba[0]**2+ba[1]**2)**0.5 * (bc[0]**2+bc[1]**2)**0.5
    return math.degrees(math.acos(max(-1.0, min(1.0, dot/mag)))) if mag > 0 else 0.0

def classify_pose(keypoints):
    kp = {k["name"]: (k["x"], k["y"]) for k in keypoints if k["confidence"] > 0.4}
    if "nose" in kp and "left_hip" in kp and "right_hip" in kp:
        hip_y = (kp["left_hip"][1] + kp["right_hip"][1]) / 2
        if kp["nose"][1] > hip_y:
            return "fall"
    if all(k in kp for k in ("left_hip","left_knee","left_ankle")):
        if joint_angle(kp["left_hip"], kp["left_knee"], kp["left_ankle"]) < 120:
            return "squat"
    if "left_wrist" in kp and "left_shoulder" in kp:
        if kp["left_wrist"][1] < kp["left_shoulder"][1]:
            return "raise_hand"
    return "standing"

def analyze_image(image_path):
    with open(image_path, "rb") as f:
        img_b64 = base64.b64encode(f.read()).decode()
    resp = requests.post(
        f"https://detect.roboflow.com/{WORKSPACE}/{PROJECT}/{VERSION}",
        params={"api_key": API_KEY},
        json={"image": img_b64},
    )
    resp.raise_for_status()
    data = resp.json()
    results = []
    for pred in data.get("predictions", []):
        gesture = classify_pose(pred.get("keypoints", []))
        results.append({"person_id": pred.get("detection_id"), "gesture": gesture, "bbox": pred})
    return {"path": image_path, "persons": results}

if __name__ == "__main__":
    for path in sys.argv[1:]:
        print(json.dumps(analyze_image(path)))
```

**`eval_definition.md`**:
```markdown
# Eval — <problem-title>
Date: <ISO8601>
Action class(es): <list of gesture/pose labels>
OKS mAP threshold: <N>%
Gesture recall floor: <N>% per class
Dataset split: <N> images/clips, source: <fixture or user footage>
Keypoint confidence cutoff: <N> (default 0.4)
Threshold logic: max(baseline OKS mAP, business recall floor)
```

Also write a `.vision-delivery/detections.jsonl` append per inference run (format in `cv-problem-solver` composition protocol) — downstream skills consume this.

</artifact>

<model_pick>

See `skills/_shared/model-selection.md` — Keypoint/Pose section (M4 placeholder IDs). Verify exact `model_id` values from `roboflow://skills/training-and-evaluation` before calling `models_train` — training fails silently on a wrong ID.

Quick reference for pose:
- Full-body skeleton, first PoC → YOLO11-pose (balance of speed and accuracy)
- Higher accuracy, no latency constraint → YOLO26-pose larger variant
- Hands only → MediaPipe Hand via Roboflow Workflows (zero-shot, no training)
- Custom domain skeleton → YOLO11-pose fine-tune on keypoint-annotated dataset

</model_pick>

<safe_actions>

Follow the safe-action gates in `skills/_shared/fde-methodology.md` exactly. Quick reference:
- `models_train` → credit estimate + explicit yes required, same turn; note: pose training requires keypoint-annotated data, not box annotations
- `versions_generate` → free but irreversible; state augmentation config before calling
- Image upload → state destination; offer local path if user declines
- `project_deployment_launch` → not in this skill; seam offer hands to deployment-consultant

</safe_actions>

<ledger>

Follow the write protocol in `skills/_shared/ledger-protocol.md`. Write one record per action, append-only to `.vision-delivery/ledger.jsonl`.

Action triggers for this skill:

| Trigger | `action` value | What to put in `notes` |
|---------|---------------|------------------------|
| `eval_definition.md` written and user confirmed | `eval_definition` | action classes, OKS mAP threshold, gesture recall floor |
| First `models_infer` call returns OKS mAP result | `baseline_measured` | `OKS mAP=X%, gesture_recall=Y%` |
| `models_train` MCP call submitted | `models_train` | model name, checkpoint, dataset version |
| Deployment launched (via seam offer → deployment-consultant) | `project_deployment_launch` | deployment_id, endpoint URL |

`entity_id` format: `<workspace>/<project>` for projects; `<workspace>/<project>/<version>` when version is known.

</ledger>

<voice>

Follow voice rules from `skills/_shared/fde-methodology.md`. Short reference:

**Do:**
- "YOLO11-pose on 40 of your factory clips: OKS mAP = 78%, fall-detection recall = 91%. Threshold is recall ≥ 85% — passes."
- "Bend angle threshold at 150° gives 88% recall — threshold was 85%. Passes without retraining."
- "Gesture rule-based classifier tuned: squat recall = 92%. No annotation needed — angle threshold adjustment only."

**Do not:**
- "Looks good!" / "This should work!" / "Great use case!"
- Report passing when threshold not cleared.
- Jump to "label 500 keypoint images" when angle threshold tuning might close the gap.
- Mention managed deployment, pricing, or cost in Phase 1 (seam offer fires once at eval-pass only).

</voice>
