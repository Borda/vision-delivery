#!/usr/bin/env python3
"""A/B benchmark runner: plugin arm vs plain arm against the mock Roboflow MCP (see evals/ab/README.md).

One run = one scenario × one arm × the U0 scripted persona:
1. Starts a fresh headless session (``claude -p``) with the mock MCP substituted
   via ``--mcp-config + --strict-mcp-config`` (server name "roboflow" so tool
   names match the live surface in both arms). Arm P adds ``--plugin-dir .``.
2. Drives the conversation: the U0 persona (YAML keyword rules, zero LLM)
   answers each agent turn via ``--resume <session>`` until a cap is hit or
   the agent stops asking/acting.
3. Persists ``transcript.jsonl`` (turns) beside the mock server's
   ``tools.jsonl`` (server-side ground truth) under ``evals/ab/runs/<run-id>/``.

Usage:
    python3 evals/ab/runner.py --scenario s1-conveyor-detect --arm P [--model sonnet] [--runs 1]
    python3 evals/ab/analyze.py evals/ab/runs/<run-id>
"""

from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import yaml

ROOT = Path(__file__).resolve().parents[2]
AB = Path(__file__).resolve().parent
RUNS = AB / "runs"
PER_TURN_TIMEOUT_S = 300


def write_fixture_images(
    images_dir: Path, count: int = 3, seed: int = 7, quality: str = "good"
) -> dict[str, Any]:
    """Write deterministic, distinct, inspectable JPEGs (640x480) + return ground truth.

    Agents forensically inspect fixture data (dimensions, hashes) before
    acting — identical 1x1 stubs get correctly rejected as "no data". These
    survive: real size, per-file distinct content, fixed seed for determinism.

    Hardened against the classical-CV shortcut (smoke-5 finding): the old
    generator's defects were high-contrast dark blobs on items — a ~30-line
    threshold script solved the task and both arms skipped the platform path.
    Now (a) defects are low-contrast cracks/dents in the ITEM's own shade,
    (b) the belt carries dark stain distractors with the old defect signature,
    (c) per-frame lighting varies — so a naive dark-blob threshold counts
    stains, misses cracks, and its counts disagree with ground truth. The
    ground truth stays ANALYZER-side (the simulated user has no labels);
    an arm shipping an unvalidated heuristic gets scored against it.
    """
    import numpy as np
    from PIL import Image, ImageDraw

    rng = np.random.default_rng(seed)
    frames: list[dict[str, Any]] = []
    for i in range(count):
        light = float(rng.uniform(0.8, 1.2))  # per-frame lighting drift

        def shade(
            r: int,
            g: int,
            b: int,
            f: float = 1.0,
            light_scale: float = light,
        ) -> tuple[int, int, int]:
            values = [min(255, max(0, int(c * light_scale * f))) for c in (r, g, b)]
            return values[0], values[1], values[2]

        arr = rng.integers(90, 150, size=(240, 320, 3), dtype="uint8")
        arr = np.clip(arr * light, 0, 255).astype("uint8")
        img = Image.fromarray(arr)
        draw = ImageDraw.Draw(img)
        draw.rectangle([0, 100, 320, 210], fill=shade(70, 70, 75))
        # distractor belt stains — dark blobs NOT on items, NOT defects
        for _ in range(int(rng.integers(1, 4))):
            sx, sy = int(rng.integers(5, 290)), int(rng.integers(105, 195))
            draw.ellipse(
                [sx, sy, sx + int(rng.integers(8, 16)), sy + 8],
                fill=shade(22, 14, 12),
            )
        items = []
        for _ in range(int(rng.integers(2, 6))):
            x = int(rng.integers(10, 280))
            base = (
                int(rng.integers(140, 180)),
                int(rng.integers(100, 140)),
                int(rng.integers(60, 100)),
            )
            draw.rectangle([x, 125, x + 30, 165], fill=shade(*base))
            defective = bool(rng.random() < 0.35)
            if defective:
                # low-contrast crack: thin polyline in a darker shade of the item color
                cx = x + int(rng.integers(4, 20))
                pts = [(cx, 129)]
                for _ in range(4):
                    pts.append(
                        (
                            pts[-1][0] + int(rng.integers(-3, 5)),
                            pts[-1][1] + int(rng.integers(6, 10)),
                        )
                    )
                draw.line(pts, fill=shade(*base, 0.7), width=1)
            items.append({"bbox": [x, 125, x + 30, 165], "defective": defective})
        if quality == "degraded":
            # capture-time QC scenario (s6): frames unusable for training —
            # heavy blur + overexposure. Ground truth still recorded
            # analyzer-side; the probe is whether an arm flags the data
            # quality BEFORE any paid step instead of training on garbage.
            from PIL import ImageEnhance, ImageFilter

            img = img.filter(ImageFilter.GaussianBlur(radius=4))
            img = ImageEnhance.Brightness(img).enhance(1.9)
        img.save(images_dir / f"frame_{i:03d}.jpg", quality=85)
        frames.append(
            {
                "file": f"frame_{i:03d}.jpg",
                "items": len(items),
                "defective": sum(it["defective"] for it in items),
                "boxes": items,
            }
        )
    return {
        "frames": frames,
        "total_items": sum(f["items"] for f in frames),
        "total_defective": sum(f["defective"] for f in frames),
    }


# Schema v2 (2026-07-10, affordability): no local-exec tools — the expensive
# token sinks were local CV script iteration and bulk image reads. The agent
# can look at data (Read) and drive the platform (MCP); process metrics are
# unchanged. Determinism levers for the N=1 default: U0 scripted persona,
# seeded fixtures, deterministic mock world, tight caps.
ALLOWED_TOOLS = "Skill,Read,mcp__roboflow__*"


def load_yaml(path: Path) -> dict:
    return yaml.safe_load(path.read_text())


def persona_reply(persona: dict, agent_text: str, context: dict) -> str:
    if persona.get("tier") == "llm":
        return persona_reply_llm(persona, agent_text, context)
    low = agent_text.lower()
    for rule in persona["rules"]:
        if any(kw in low for kw in rule["match"]):
            return rule["reply"].format(**context)
    return persona["fallback"]


def persona_reply_llm(persona: dict, agent_text: str, context: dict) -> str:
    """U1 tier: rigid weak-LLM user sim (Haiku) — stateless single call per turn.

    Statelessness is deliberate: the persona cannot accumulate CV knowledge
    across turns, keeping the novice boundary fixed. Fidelity is enforced
    post-hoc by the banned-vocabulary audit in analyze.py (leaking runs are
    discarded and the rerun flagged — benchmark plan U1 rule).
    """
    system = persona["system_prompt"].format(**context)
    prompt = (
        "The assistant you hired said this — reply as the user, nothing else:\n\n"
        + agent_text[:4000]
    )
    cmd = [
        "claude",
        "--model",
        persona.get("model", "haiku"),
        "--setting-sources",
        "project",
        "--output-format",
        "json",
        "--allowedTools",
        "",
        "--max-turns",
        "1",
        "--append-system-prompt",
        system,
        "-p",
        prompt,
    ]
    try:
        res = subprocess.run(
            cmd, capture_output=True, text=True, timeout=120, stdin=subprocess.DEVNULL
        )
        reply = (json.loads(res.stdout).get("result") or "").strip()
    except (subprocess.TimeoutExpired, json.JSONDecodeError):
        reply = ""
    return reply or persona["fallback"]


def claude_turn(
    prompt: str,
    arm: str,
    model: str,
    mcp_config: Path,
    session_id: str | None,
    workdir: Path,
) -> tuple[str, str | None]:
    """Run one headless turn; return (agent_text, session_id)."""
    cmd = [
        "claude",
        "--model",
        model,
        "--setting-sources",
        "project",
        "--output-format",
        "json",
        "--mcp-config",
        str(mcp_config),
        "--strict-mcp-config",
        "--allowedTools",
        ALLOWED_TOOLS,
        "--max-turns",
        "15",
    ]
    if arm == "P":
        cmd += ["--plugin-dir", str(ROOT)]
    if session_id:
        cmd += ["--resume", session_id]
    cmd += ["-p", prompt]
    try:
        res = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=PER_TURN_TIMEOUT_S,
            cwd=workdir,
            stdin=subprocess.DEVNULL,
        )
    except subprocess.TimeoutExpired:
        return "", session_id
    try:
        payload = json.loads(res.stdout)
        text = payload.get("result", "") or ""
        if not text and payload.get("subtype") and payload["subtype"] != "success":
            text = f"[harness: session ended subtype={payload['subtype']} num_turns={payload.get('num_turns')}]"
        return text, payload.get("session_id", session_id)
    except json.JSONDecodeError:
        err = (res.stderr or "").strip()[:200]
        return (
            res.stdout.strip()
            or (f"[harness: non-json output; stderr={err}]" if err else "")
        ), session_id


AGENT_DONE_RE = re.compile(
    r"(deployed|deployment).{0,40}(live|launched|complete)|mock\.roboflow\.app", re.I
)


def run_once(
    scenario: dict, persona: dict, arm: str, model: str, run_dir: Path
) -> None:
    run_dir.mkdir(parents=True, exist_ok=True)
    mcp_config = run_dir / "mcp.json"
    mcp_config.write_text(
        json.dumps(
            {
                "mcpServers": {
                    "roboflow": {
                        "command": sys.executable,
                        "args": [str(AB / "mock_mcp" / "server.py")],
                        "env": {"MOCK_AB_LOG": str(run_dir)},
                    }
                }
            },
            indent=2,
        )
    )

    # Fresh workspace per run — sessions must not see other runs' artifacts
    # (ledger files, eval definitions) or the repo itself as cwd.
    workspace = run_dir / "workspace"
    workspace.mkdir(exist_ok=True)
    # Fixture images the persona can point the agent at — must survive agent
    # inspection (real dimensions, distinct hashes).
    images_dir = workspace / "line-photos"
    images_dir.mkdir(exist_ok=True)
    truth = write_fixture_images(
        images_dir, quality=scenario.get("fixture_quality", "good")
    )
    # Ground truth lives in run_dir (analyzer-side), NOT the workspace — the
    # simulated user has no labels; the analyzer scores unvalidated shortcuts
    # against it.
    (run_dir / "ground_truth.json").write_text(json.dumps(truth, indent=2))
    context = {"images_dir": str(images_dir)}

    transcript = run_dir / "transcript.jsonl"
    caps = scenario.get("caps", {})
    max_user_turns = min(
        persona.get("caps", {}).get("max_user_turns", 8),
        caps.get("max_agent_turns", 12),
    )

    session_id: str | None = None
    prompt = scenario["cold_prompt"].strip()
    with transcript.open("w") as fh:
        for turn in range(max_user_turns):
            (run_dir / "current_turn.txt").write_text(str(turn))
            fh.write(json.dumps({"role": "user", "turn": turn, "text": prompt}) + "\n")
            fh.flush()
            agent_text, session_id = claude_turn(
                prompt, arm, model, mcp_config, session_id, workspace
            )
            fh.write(
                json.dumps({"role": "agent", "turn": turn, "text": agent_text}) + "\n"
            )
            fh.flush()
            if not agent_text:
                # One retry: empty result with a live session usually means the
                # inner turn cap cut the final message — nudge to continue.
                if session_id:
                    agent_text, session_id = claude_turn(
                        "Please continue from where you stopped.",
                        arm,
                        model,
                        mcp_config,
                        session_id,
                        workspace,
                    )
                    fh.write(
                        json.dumps(
                            {
                                "role": "agent",
                                "turn": turn,
                                "text": agent_text,
                                "retry": True,
                            }
                        )
                        + "\n"
                    )
                    fh.flush()
                if not agent_text:
                    break
            if AGENT_DONE_RE.search(agent_text):
                break
            reply = persona_reply(persona, agent_text, context)
            # Repeat-breaker: a stuck loop (same canned answer twice) degrades
            # to the fallback so the arm must self-resolve — that IS the metric.
            if reply == prompt:
                reply = persona["fallback"]
            prompt = reply

    try:
        git_head = subprocess.run(
            ["git", "-C", str(ROOT), "rev-parse", "--short", "HEAD"],
            capture_output=True,
            text=True,
            timeout=5,
            stdin=subprocess.DEVNULL,
        ).stdout.strip()
        dirty = bool(
            subprocess.run(
                ["git", "-C", str(ROOT), "status", "--porcelain", "--", "evals/ab"],
                capture_output=True,
                text=True,
                timeout=5,
                stdin=subprocess.DEVNULL,
            ).stdout.strip()
        )
    except Exception:
        git_head, dirty = "unknown", True
    (run_dir / "meta.json").write_text(
        json.dumps(
            {
                "scenario": scenario["id"],
                "arm": arm,
                "model": model,
                "persona": persona["name"],
                "turns_cap": max_user_turns,
                # world provenance (matrix-taint lesson): heterogeneous
                # matrices must be detectable post-hoc
                "harness_git": git_head + ("-dirty" if dirty else ""),
            },
            indent=2,
        )
    )


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument(
        "--scenario", required=True, help="Scenario id (file stem in scenarios/)."
    )
    ap.add_argument(
        "--arm", choices=["P", "B"], required=True, help="P=plugin, B=plain."
    )
    ap.add_argument("--model", default="sonnet")
    ap.add_argument("--runs", type=int, default=1)
    ap.add_argument(
        "--persona",
        default=None,
        help="Persona file stem override (default: scenario's persona).",
    )
    ap.add_argument(
        "--run-offset",
        type=int,
        default=0,
        help="Start index for the rN suffix (matrix sharding).",
    )
    args = ap.parse_args()

    if "fable" in args.model.lower():
        sys.exit("benchmark arms run sonnet or opus only — never fable (owner rule)")

    scenario = load_yaml(AB / "scenarios" / f"{args.scenario}.yaml")
    persona = load_yaml(AB / "personas" / f"{args.persona or scenario['persona']}.yaml")

    for n in range(args.run_offset, args.run_offset + args.runs):
        ts = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H-%M-%SZ")
        run_dir = RUNS / f"{ts}-{scenario['id']}-{args.arm}-{persona['name']}-r{n}"
        print(f"→ {run_dir.name}")
        run_once(scenario, persona, args.arm, args.model, run_dir)
        print("  transcript + tools.jsonl written")
    return 0


if __name__ == "__main__":
    sys.exit(main())
