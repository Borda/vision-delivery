#!/usr/bin/env bash
# ponytail: Codex bundled-install mechanism is unavailable in this repository.
# When verified: copy skills/ agents/ .mcp.json into dist/<plugin-name>/ in Codex's expected shape
echo "build-codex-pkg: Codex bundled install mechanism is not available in this repository; install the Claude Code plugin directly"
echo "Standalone install works now: Codex can consume root skills/ directly via --skills flag"
exit 0
