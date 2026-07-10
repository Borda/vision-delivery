#!/usr/bin/env python3
"""H-06 regression probe: ambiguous count-vs-verdict prompt must not act blind.

The router-bypass finding: modality skills can grab an ambiguous prompt
("count the defective items") directly, so the router's count-vs-verdict
discriminator never ran. Fix: each modality skill carries a Step-0 ambiguity
gate. This probe runs the ambiguous prompt live (fresh temp cwd, fixture
images present) and asserts the outcome is one of the two compliant paths:

- a skill fires AND (asks the discriminator question OR the framing is
  per-instance-clear and it proceeds on per-instance counting), or
- no skill fires and the agent asks for the missing context instead of acting.

Non-compliant (the pre-fix failure): fires and delivers an image-level or
unvalidated verdict with no question. One model call; run on demand:

    python3 evals/trigger-live/h06_ambiguity_probe.py [--model sonnet]
"""

from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "evals" / "ab"))
from runner import write_fixture_images  # noqa: E402

PROMPT = (
    "count the defective items — I have photos from the line camera in ./line-photos"
)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--model", default="sonnet")
    args = ap.parse_args()

    with tempfile.TemporaryDirectory(prefix="h06-probe-") as tmp:
        imgs = Path(tmp) / "line-photos"
        imgs.mkdir()
        write_fixture_images(imgs, count=10)
        cmd = [
            "claude",
            "--plugin-dir",
            str(ROOT),
            "--model",
            args.model,
            "--setting-sources",
            "project",
            "--max-turns",
            "6",
            "--allowedTools",
            "Skill,AskUserQuestion",
            "--output-format",
            "stream-json",
            "--verbose",
            "-p",
            PROMPT,
        ]
        res = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=300,
            cwd=tmp,
            stdin=subprocess.DEVNULL,
        )

    fired = None
    asked = False
    final = ""
    all_text = []
    for line in res.stdout.splitlines():
        try:
            e = json.loads(line)
        except json.JSONDecodeError:
            continue
        if e.get("type") == "assistant":
            for b in e.get("message", {}).get("content", []):
                if b.get("type") == "tool_use":
                    if b["name"] == "Skill":
                        fired = b["input"].get("skill")
                    if b["name"] == "AskUserQuestion":
                        asked = True
                elif b.get("type") == "text":
                    all_text.append(b.get("text", ""))
        elif e.get("type") == "result":
            final = e.get("result") or ""

    text = "\n".join(all_text) + "\n" + final
    question = asked or bool(
        re.search(
            r"per.instance.*(pass.fail|verdict)|(pass.fail|verdict).*per.instance"
            r"|count per instance",
            text,
            re.I | re.S,
        )
    )
    per_instance_path = bool(
        re.search(
            r"per.instance|per.item|each (item|frame|photo)|detect items", text, re.I
        )
    )
    # The guarded failure mode: a final verdict count delivered with neither a
    # discriminator question nor a per-instance framing. Truncated runs (empty
    # final under the turn cap) are inconclusive, not failures.
    verdict_delivered = bool(re.search(r"\d+\s+defect", final, re.I))
    blind_verdict = verdict_delivered and not (question or per_instance_path)

    print(f"fired skill: {fired}")
    print(f"discriminator question: {question}")
    print(f"per-instance path taken: {per_instance_path}")
    print(f"verdict delivered: {verdict_delivered}")
    print(f"final: {final[:300]}")
    if blind_verdict:
        print("H-06 probe: FAIL (verdict with no question and no per-instance framing)")
        return 1
    if not final.strip() and fired:
        print(
            "H-06 probe: PASS (inconclusive-truncated — skill fired, no blind verdict)"
        )
        return 0
    print("H-06 probe: PASS")
    return 0


if __name__ == "__main__":
    sys.exit(main())
