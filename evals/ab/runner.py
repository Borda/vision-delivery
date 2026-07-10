#!/usr/bin/env python3
"""A/B benchmark runner: plugin arm vs plain arm against the mock Roboflow MCP (§8 B-03).

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

import yaml

ROOT = Path(__file__).resolve().parents[2]
AB = Path(__file__).resolve().parent
RUNS = AB / "runs"
PER_TURN_TIMEOUT_S = 300
ALLOWED_TOOLS = "Skill,Read,Write,Edit,Bash,mcp__roboflow__*"


def load_yaml(path: Path) -> dict:
    return yaml.safe_load(path.read_text())


def persona_reply(persona: dict, agent_text: str, context: dict) -> str:
    low = agent_text.lower()
    for rule in persona["rules"]:
        if any(kw in low for kw in rule["match"]):
            return rule["reply"].format(**context)
    return persona["fallback"]


def claude_turn(
    prompt: str, arm: str, model: str, mcp_config: Path, session_id: str | None
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
            cmd, capture_output=True, text=True, timeout=PER_TURN_TIMEOUT_S, cwd=ROOT
        )
    except subprocess.TimeoutExpired:
        return "", session_id
    try:
        payload = json.loads(res.stdout)
        return payload.get("result", "") or "", payload.get("session_id", session_id)
    except json.JSONDecodeError:
        return res.stdout.strip(), session_id


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

    # Fixture images the persona can point the agent at (agents ask for a path).
    images_dir = run_dir / "images"
    images_dir.mkdir(exist_ok=True)
    for i in range(12):
        (images_dir / f"frame_{i:03d}.jpg").write_bytes(b"\xff\xd8\xff\xe0mock")
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
            fh.write(json.dumps({"role": "user", "turn": turn, "text": prompt}) + "\n")
            fh.flush()
            agent_text, session_id = claude_turn(
                prompt, arm, model, mcp_config, session_id
            )
            fh.write(
                json.dumps({"role": "agent", "turn": turn, "text": agent_text}) + "\n"
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

    (run_dir / "meta.json").write_text(
        json.dumps(
            {
                "scenario": scenario["id"],
                "arm": arm,
                "model": model,
                "persona": persona["name"],
                "turns_cap": max_user_turns,
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
    args = ap.parse_args()

    scenario = load_yaml(AB / "scenarios" / f"{args.scenario}.yaml")
    persona = load_yaml(AB / "personas" / f"{scenario['persona']}.yaml")

    for n in range(args.runs):
        ts = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H-%M-%SZ")
        run_dir = RUNS / f"{ts}-{scenario['id']}-{args.arm}-r{n}"
        print(f"→ {run_dir.name}")
        run_once(scenario, persona, args.arm, args.model, run_dir)
        print("  transcript + tools.jsonl written")
    return 0


if __name__ == "__main__":
    sys.exit(main())
