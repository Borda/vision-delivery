#!/usr/bin/env python3
"""Deterministic mock of the Roboflow MCP surface for the plugin-vs-plain A/B benchmark (see evals/ab/README.md).

Exposes the real tool names with scripted, stateful responses so both arms
(plugin and plain agent) face an identical, zero-credit, zero-latency world:

- ``trainings_create`` returns a job; ``trainings_get`` advances a scripted
  state machine (pending → running → finished after 3 polls). The FIRST model
  finishes mediocre (mAP@50 = 0.42) to force the improve loop; a second
  training launched after ``versions_generate`` (augmentation) finishes at
  0.85.
- Every paid call decrements a simulated credit balance.
- EVERY tool call is appended to ``$MOCK_AB_LOG/tools.jsonl`` — the analyzers'
  ground truth (server-side, independent of transcript parsing).

Run (stdio): ``MOCK_AB_LOG=/tmp/run1 python3 evals/ab/mock_mcp/server.py``
"""

from __future__ import annotations

import json
import os
import time
from pathlib import Path
from typing import Any

from mcp.server.fastmcp import FastMCP

FIXTURES = json.loads(
    (Path(__file__).parent / "fixtures" / "live_traces.json").read_text()
)
LOG_DIR = Path(os.environ.get("MOCK_AB_LOG", "/tmp/mock-ab"))
LOG_DIR.mkdir(parents=True, exist_ok=True)
TOOLS_LOG = LOG_DIR / "tools.jsonl"
STATE_FILE = LOG_DIR / "state.json"

PAID_CREDITS = {
    "trainings_create": 5,
    "project_deployment_launch": 3,
    "autolabel_start": 2,
}
FIRST_MAP50 = 0.42
IMPROVED_MAP50 = 0.85
POLLS_TO_FINISH = 3

STATE: dict[str, Any] = {
    "credits": 50,
    "call_index": 0,
    "trainings": {},  # job_id -> {polls, map50, model_id}
    "versions": 1,
    "augmented": False,
    "training_count": 0,
    "deployed": False,
}

# The harness relaunches this server as a fresh subprocess on every user turn
# (see evals/ab/runner.py:claude_turn) — an in-memory-only STATE loses jobs
# mid-training whenever a poll loop crosses a turn boundary. Persist to a
# per-run file so state survives across the process restarts.
if STATE_FILE.exists():
    try:
        STATE.update(json.loads(STATE_FILE.read_text()))
    except json.JSONDecodeError:
        pass

mcp = FastMCP("roboflow-mock")


def _log(tool: str, args: dict[str, Any]) -> None:
    STATE["call_index"] += 1
    # user-turn index written by the runner before each turn — lets the
    # analyzer compute blind spend in the right index space (mining fix)
    try:
        turn = int((LOG_DIR / "current_turn.txt").read_text().strip())
    except (OSError, ValueError):
        turn = -1
    spend = PAID_CREDITS.get(tool, 0)
    STATE["credits"] -= spend
    row = {
        "i": STATE["call_index"],
        "ts": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "tool": tool,
        "args": args,
        "turn": turn,
        "credits_spent": spend,
        "credits_balance": STATE["credits"],
    }
    with TOOLS_LOG.open("a") as fh:
        fh.write(json.dumps(row) + "\n")
    STATE_FILE.write_text(json.dumps(STATE))


@mcp.tool()
def universe_search(query: str, limit: int = 12, page: int = 1) -> dict:
    """Search Roboflow Universe for datasets or models."""
    _log("universe_search", {"query": query})
    return FIXTURES["universe_search"]


@mcp.tool()
def projects_list(limit: int = 50, offset: int = 0) -> dict:
    """List projects in the workspace."""
    _log("projects_list", {})
    return FIXTURES["projects_list"]


@mcp.tool()
def projects_create(
    name: str, project_type: str = "object-detection", annotation: str = "objects"
) -> dict:
    """Create a project in the workspace."""
    _log("projects_create", {"name": name, "type": project_type})
    return {
        "id": f"mock-ws/{name.lower().replace(' ', '-')}",
        "name": name,
        "type": project_type,
    }


@mcp.tool()
def image_upload(
    project_id: str, path: str = "", url: str = "", split: str = "train"
) -> dict:
    """Upload an image to a project (mock: accepts and acks)."""
    _log("image_upload", {"project_id": project_id, "split": split})
    return {"success": True, "id": f"img-{STATE['call_index']}"}


@mcp.tool()
def versions_generate(
    project_id: str, preprocessing: dict | None = None, augmentation: dict | None = None
) -> dict:
    """Generate a new dataset version (mock: instant; augmentation unlocks the improved model)."""
    STATE["versions"] += 1
    if augmentation:
        STATE["augmented"] = True
    _log(
        "versions_generate",
        {"project_id": project_id, "augmentation": bool(augmentation)},
    )
    return {"version": STATE["versions"], "generating": False, "ready": True}


@mcp.tool()
def versions_get(project_id: str, version_number: int) -> dict:
    """Get dataset version info including splits and readiness."""
    _log("versions_get", {"project_id": project_id, "version": version_number})
    out = dict(FIXTURES["versions_get_shape"])
    out["version"] = version_number
    return out


@mcp.tool()
def trainings_create(
    project_id: str,
    version_number: int,
    model_id: str = "rfdetr-medium",
    checkpoint: str = "coco",
) -> dict:
    """Start a training run (PAID: 5 simulated credits)."""
    STATE["training_count"] += 1
    job = f"mock-job/{version_number}/training/{STATE['training_count']}"
    map50 = (
        IMPROVED_MAP50
        if (STATE["training_count"] > 1 and STATE["augmented"])
        else FIRST_MAP50
    )
    STATE["trainings"][job] = {
        "polls": 0,
        "map50": map50,
        "model_id": f"conveyor-defects/{STATE['training_count']}",
    }
    _log(
        "trainings_create",
        {"project_id": project_id, "version": version_number, "model_id": model_id},
    )
    return {"trainingId": job, "status": "pending"}


@mcp.tool()
def trainings_get(
    project_id: str, version_number: int, training_id: str | None = None
) -> dict:
    """Get a training's status and metrics (mock: pending → running → finished over 3 polls)."""
    _log("trainings_get", {"project_id": project_id, "training_id": training_id})
    jobs = STATE["trainings"]
    if not jobs:
        return {"result": []}
    job = training_id if training_id in jobs else list(jobs)[-1]
    st = jobs[job]
    st["polls"] += 1
    if st["polls"] < 2:
        status = "pending"
    elif st["polls"] < POLLS_TO_FINISH:
        status = "running"
    else:
        status = "finished"
    out: dict[str, Any] = {
        "trainingId": job,
        "status": status,
        "modelType": "rfdetr-medium",
        "modelCount": 1,
    }
    if status == "finished":
        out["models"] = [
            {
                "modelId": st["model_id"],
                "status": "finished",
                "metrics": {
                    "map50": round(st["map50"] * 100, 2),
                    "precision": 90.9,
                    # keep consistent with model_evals_get — a hardcoded
                    # stale recall here caused a false recall-plateau read
                    "recall": 67.0 if st["map50"] < 0.5 else 81.0,
                },
            }
        ]
    return out


@mcp.tool()
def trainings_list(project_id: str, version_number: int) -> dict:
    """List trainings on a dataset version."""
    _log("trainings_list", {"project_id": project_id})
    return {
        "result": [
            {
                "trainingId": j,
                "status": "finished" if s["polls"] >= POLLS_TO_FINISH else "running",
                "modelType": "rfdetr-medium",
                "modelIds": [s["model_id"]],
            }
            for j, s in STATE["trainings"].items()
        ]
    }


@mcp.tool()
def model_evals_get(eval_id: str) -> dict:
    """Get the top-level summary for a model evaluation."""
    _log("model_evals_get", {"eval_id": eval_id})
    out = dict(FIXTURES["model_evals_get_shape"])
    latest = list(STATE["trainings"].values())[-1] if STATE["trainings"] else None
    map50 = latest["map50"] if latest else FIRST_MAP50
    out["evalId"] = eval_id
    out["summary"] = {
        "mAP": map50,
        "mIoU": None,
        "precision": 0.91,
        "recall": 0.67 if map50 < 0.5 else 0.81,
    }
    return out


@mcp.tool()
def model_evals_list(project_id: str | None = None, limit: int = 50) -> dict:
    """List model evaluations in the workspace."""
    _log("model_evals_list", {"project_id": project_id})
    evals = []
    for i, (_job, st) in enumerate(STATE["trainings"].items(), 1):
        if st["polls"] >= POLLS_TO_FINISH:
            evals.append(
                {
                    "evalId": f"mock-eval-{i}",
                    "status": "done",
                    "project": "conveyor-defects",
                    "versionId": str(i),
                    "modelUrl": st["model_id"],
                }
            )
    return {"evals": evals}


@mcp.tool()
def models_infer(model_id: str, image_url: str = "", confidence: float = 0.4) -> dict:
    """Run inference with a model on an image (mock: canned detections)."""
    _log(
        "models_infer",
        {"model_id": model_id, "image_url": image_url, "confidence": confidence},
    )
    return {
        "predictions": [
            {
                "class": "defect",
                "confidence": 0.83,
                "x": 120,
                "y": 88,
                "width": 40,
                "height": 32,
            },
            {
                "class": "box",
                "confidence": 0.94,
                "x": 200,
                "y": 150,
                "width": 180,
                "height": 120,
            },
        ]
    }


@mcp.tool()
def project_deployment_launch(project_id: str, model_id: str = "") -> dict:
    """Launch a managed deployment (PAID: 3 simulated credits)."""
    STATE["deployed"] = True
    _log("project_deployment_launch", {"project_id": project_id, "model_id": model_id})
    return {
        "id": "mock-deploy-1",
        "status": "deployable",
        "url": "https://mock.roboflow.app/deploy/1",
    }


@mcp.tool()
def devices_list() -> dict:
    """List edge devices registered in the workspace."""
    _log("devices_list", {})
    return FIXTURES["devices_list"]


@mcp.tool()
def annotation_jobs_create(
    project_id: str, batch_name: str = "", images: list | None = None
) -> dict:
    """Create an annotation job (mock: instant ack; counts toward improve-loop)."""
    STATE["augmented"] = True  # hard-negative batch also unlocks the improved model
    _log("annotation_jobs_create", {"project_id": project_id, "batch_name": batch_name})
    return {"jobId": f"mock-annjob-{STATE['call_index']}", "status": "created"}


if __name__ == "__main__":
    mcp.run()
