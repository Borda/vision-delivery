#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

python3 - "$ROOT" <<'PY'
import json
import sys
from pathlib import Path

root = Path(sys.argv[1])
manifest_path = root / ".codex-plugin" / "plugin.json"
marketplace_path = root / ".agents" / "plugins" / "marketplace.json"

manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
marketplace = json.loads(marketplace_path.read_text(encoding="utf-8"))

assert manifest["name"] == "sentinel"
assert manifest["skills"] == "./codex-skills/"
assert manifest["mcpServers"] == {
    "roboflow": {"type": "http", "url": "https://mcp.roboflow.com/mcp"}
}
assert (root / "codex-skills" / "solve-cv-task" / "SKILL.md").is_file()
assert (root / "codex-skills" / "estimate-economics" / "SKILL.md").is_file()

entries = [p for p in marketplace["plugins"] if p["name"] == manifest["name"]]
assert len(entries) == 1
assert entries[0]["source"] == {"source": "local", "path": "./"}

print("Codex package metadata is present and internally consistent.")
print()
print("Install from a clone:")
print(f"  codex plugin marketplace add {root}")
print("  codex plugin add sentinel@sentinel")
print()
print("Install from GitHub:")
print("  codex plugin marketplace add https://github.com/Borda/vision-delivery")
print("  codex plugin add sentinel@sentinel")
PY
