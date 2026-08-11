#!/usr/bin/env python3
"""Exercise an installed Sentinel plugin against the deterministic mock MCP.

This is an on-demand host acceptance gate, not a CI check. It needs a
separately authenticated, disposable host home for each requested host; the
runner never reads, copies, or changes a developer's normal configuration.

Examples:
    python evals/e2e/run_dual_host_smoke.py --self-test
    python evals/e2e/run_dual_host_smoke.py --host codex --codex-home /tmp/codex-home
    python evals/e2e/run_dual_host_smoke.py --host claude --claude-config /tmp/claude-config
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
import tempfile
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
MOCK_SERVER = ROOT / "evals" / "ab" / "mock_mcp" / "server.py"
BUILD_PACKAGE = ROOT / "scripts" / "build_package.py"
PACKAGE_NAME = "sentinel"
CODEX_MARKETPLACE = "sentinel-e2e-codex"
CLAUDE_MARKETPLACE = "sentinel-e2e-claude"
PROMPT = (
    "$solve-cv-task: call the registered Roboflow MCP projects_list tool exactly once, "
    "then write a concise proof brief to proof-brief.md. Do not upload data, train, "
    "deploy, or make any paid action."
)
HOOK_LEDGER_WAIT_SECONDS = 5.0
HOOK_LEDGER_POLL_SECONDS = 0.1


@dataclass(frozen=True)
class Observation:
    """Host-side evidence required by the mock smoke contract."""

    returncode: int
    tool_calls: tuple[str, ...]
    ledger_statuses: tuple[str, ...]
    proof_brief_exists: bool


def run(command: list[str], environment: dict[str, str], cwd: Path) -> subprocess.CompletedProcess[str]:
    """Run one bounded host command and retain output for the result artifact."""
    return subprocess.run(
        command,
        capture_output=True,
        check=False,
        cwd=cwd,
        env=environment,
        text=True,
        timeout=300,
        stdin=subprocess.DEVNULL,
    )


def replace_mock_mcp(candidate: Path, log_dir: Path) -> None:
    """Inject the deterministic test server into a disposable candidate only."""
    mock_server = {
        "command": sys.executable,
        "args": [str(MOCK_SERVER)],
        "env": {"MOCK_AB_LOG": str(log_dir)},
    }
    claude_config = candidate / ".mcp.json"
    claude_config.write_text(
        json.dumps({"mcpServers": {"roboflow": mock_server}}, indent=2) + "\n",
        encoding="utf-8",
    )
    codex_manifest = candidate / ".codex-plugin" / "plugin.json"
    manifest = json.loads(codex_manifest.read_text(encoding="utf-8"))
    # Codex caches installed plugins by version. A unique build metadata suffix
    # guarantees this temporary candidate cannot reuse the real MCP definition.
    manifest["version"] = f"{manifest['version']}+e2e.{time.time_ns()}"
    manifest["mcpServers"] = {"roboflow": {"type": "stdio", **mock_server}}
    codex_manifest.write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")


def read_observation(process: subprocess.CompletedProcess[str], workspace: Path) -> Observation:
    """Extract MCP and hook evidence without depending on host transcript schemas."""
    tools_log = workspace / "mock-log" / "tools.jsonl"
    tool_calls: list[str] = []
    if tools_log.is_file():
        for line in tools_log.read_text(encoding="utf-8").splitlines():
            try:
                row = json.loads(line)
            except json.JSONDecodeError:
                continue
            tool = row.get("tool")
            if isinstance(tool, str):
                tool_calls.append(tool)
    ledger_path = workspace / ".vision-delivery" / "ledger.jsonl"
    statuses: list[str] = []
    if ledger_path.is_file():
        for line in ledger_path.read_text(encoding="utf-8").splitlines():
            try:
                row = json.loads(line)
            except json.JSONDecodeError:
                continue
            if row.get("operation") == "projects_list":
                statuses.append(str(row.get("status", "")))
    return Observation(
        returncode=process.returncode,
        tool_calls=tuple(tool_calls),
        ledger_statuses=tuple(statuses),
        proof_brief_exists=(workspace / "proof-brief.md").is_file(),
    )


def wait_for_hook_ledger(process: subprocess.CompletedProcess[str], workspace: Path) -> Observation:
    """Wait briefly for the asynchronously launched PostToolUse hook to write."""
    deadline = time.monotonic() + HOOK_LEDGER_WAIT_SECONDS
    observation = read_observation(process, workspace)
    while observation.tool_calls and not observation.ledger_statuses:
        if time.monotonic() >= deadline:
            break
        time.sleep(HOOK_LEDGER_POLL_SECONDS)
        observation = read_observation(process, workspace)
    return observation


def smoke_result(host: str, observation: Observation, process: subprocess.CompletedProcess[str]) -> dict[str, Any]:
    """Return an auditable pass/fail result without exposing host environment data."""
    core_checks = {
        "host_command_succeeded": observation.returncode == 0,
        "mock_mcp_exactly_once": observation.tool_calls == ("projects_list",),
        "proof_brief_written": observation.proof_brief_exists,
    }
    hook_checks = {
        "hook_success_row": observation.ledger_statuses.count("success") == 1,
    }
    checks = {**core_checks, **hook_checks}
    detail_source = (process.stderr or process.stdout).strip().replace("\n", " ")
    # Streaming hosts emit setup first and their useful refusal/error last.
    detail = detail_source[-500:]
    return {
        "host": host,
        "status": "ok" if all(checks.values()) else "failed",
        "core_status": "ok" if all(core_checks.values()) else "failed",
        "hook_status": "ok" if all(hook_checks.values()) else "failed",
        "checks": checks,
        "ledger_statuses": list(observation.ledger_statuses),
        "mock_tool_calls": list(observation.tool_calls),
        "detail": detail,
    }


def codex_marketplace() -> dict[str, Any]:
    """Return the one-plugin local marketplace used only by this smoke run."""
    return {
        "name": CODEX_MARKETPLACE,
        "interface": {"displayName": "Sentinel e2e smoke"},
        "plugins": [
            {
                "name": PACKAGE_NAME,
                "source": {"source": "local", "path": "./plugins/sentinel"},
                "policy": {"installation": "AVAILABLE", "authentication": "ON_USE"},
                "category": "Developer Tools",
            }
        ],
    }


def claude_marketplace() -> dict[str, Any]:
    """Return the one-plugin Claude marketplace used only by this smoke run."""
    return {
        "name": CLAUDE_MARKETPLACE,
        "owner": {"name": "Sentinel e2e smoke"},
        "plugins": [
            {
                "name": PACKAGE_NAME,
                "description": "Sentinel e2e smoke",
                "source": "./plugins/sentinel",
            }
        ],
    }


def install_codex(candidate: Path, home: Path, workspace: Path) -> dict[str, Any]:
    """Install, execute, and remove one disposable Codex plugin candidate."""
    environment = {**os.environ, "CODEX_HOME": str(home)}
    with tempfile.TemporaryDirectory(prefix="sentinel-e2e-codex-") as temporary:
        root = Path(temporary)
        marketplace = root / "marketplace"
        shutil.copytree(candidate, marketplace / "plugins" / PACKAGE_NAME)
        manifest = marketplace / ".agents" / "plugins" / "marketplace.json"
        manifest.parent.mkdir(parents=True)
        manifest.write_text(json.dumps(codex_marketplace(), indent=2) + "\n", encoding="utf-8")
        added_marketplace = run(
            ["codex", "plugin", "marketplace", "add", str(marketplace), "--json"],
            environment,
            workspace,
        )
        if added_marketplace.returncode:
            return {
                "host": "codex",
                "status": "failed",
                "detail": added_marketplace.stderr.strip()[:500],
            }
        installed = run(
            ["codex", "plugin", "add", f"{PACKAGE_NAME}@{CODEX_MARKETPLACE}", "--json"],
            environment,
            workspace,
        )
        if installed.returncode:
            return {
                "host": "codex",
                "status": "failed",
                "detail": installed.stderr.strip()[:500],
            }
        try:
            process = run(
                [
                    "codex",
                    "exec",
                    "--json",
                    "--sandbox",
                    "workspace-write",
                    "--dangerously-bypass-hook-trust",
                    "--skip-git-repo-check",
                    "--cd",
                    str(workspace),
                    PROMPT,
                ],
                environment,
                workspace,
            )
            return smoke_result("codex", wait_for_hook_ledger(process, workspace), process)
        finally:
            run(
                [
                    "codex",
                    "plugin",
                    "remove",
                    f"{PACKAGE_NAME}@{CODEX_MARKETPLACE}",
                    "--json",
                ],
                environment,
                workspace,
            )
            run(
                [
                    "codex",
                    "plugin",
                    "marketplace",
                    "remove",
                    CODEX_MARKETPLACE,
                    "--json",
                ],
                environment,
                workspace,
            )


def install_claude(candidate: Path, config_dir: Path, workspace: Path) -> dict[str, Any]:
    """Install, execute, and remove one disposable Claude plugin candidate."""
    environment = {**os.environ, "CLAUDE_CONFIG_DIR": str(config_dir)}
    with tempfile.TemporaryDirectory(prefix="sentinel-e2e-claude-") as temporary:
        root = Path(temporary)
        marketplace = root / "marketplace"
        installed_candidate = marketplace / "plugins" / PACKAGE_NAME
        shutil.copytree(candidate, installed_candidate)
        manifest = marketplace / ".claude-plugin" / "marketplace.json"
        manifest.parent.mkdir(parents=True)
        manifest.write_text(json.dumps(claude_marketplace(), indent=2) + "\n", encoding="utf-8")
        added_marketplace = run(
            [
                "claude",
                "plugin",
                "marketplace",
                "add",
                str(marketplace),
                "--scope",
                "user",
            ],
            environment,
            workspace,
        )
        if added_marketplace.returncode:
            return {
                "host": "claude",
                "status": "failed",
                "detail": added_marketplace.stderr.strip()[:500],
            }
        installed = run(
            [
                "claude",
                "plugin",
                "install",
                f"{PACKAGE_NAME}@{CLAUDE_MARKETPLACE}",
                "--scope",
                "user",
            ],
            environment,
            workspace,
        )
        if installed.returncode:
            return {
                "host": "claude",
                "status": "failed",
                "detail": installed.stderr.strip()[:500],
            }
        try:
            process = run(
                [
                    "claude",
                    "--plugin-dir",
                    str(installed_candidate),
                    "--setting-sources",
                    "project",
                    "--allowedTools",
                    "Skill,Write,mcp__roboflow__*",
                    "--max-turns",
                    "12",
                    "--output-format",
                    "stream-json",
                    "--verbose",
                    "-p",
                    PROMPT,
                ],
                environment,
                workspace,
            )
            return smoke_result("claude", wait_for_hook_ledger(process, workspace), process)
        finally:
            run(
                [
                    "claude",
                    "plugin",
                    "uninstall",
                    f"{PACKAGE_NAME}@{CLAUDE_MARKETPLACE}",
                    "--scope",
                    "user",
                    "--yes",
                ],
                environment,
                workspace,
            )
            run(
                [
                    "claude",
                    "plugin",
                    "marketplace",
                    "remove",
                    CLAUDE_MARKETPLACE,
                    "--scope",
                    "user",
                ],
                environment,
                workspace,
            )


def self_test() -> int:
    """Test parser and pass criteria without a host account or model call."""
    with tempfile.TemporaryDirectory(prefix="sentinel-e2e-self-test-") as temporary:
        workspace = Path(temporary)
        ledger = workspace / ".vision-delivery" / "ledger.jsonl"
        ledger.parent.mkdir()
        ledger.write_text(
            json.dumps({"operation": "projects_list", "status": "success"}) + "\n",
            encoding="utf-8",
        )
        (workspace / "proof-brief.md").write_text("fixture\n", encoding="utf-8")
        mock_log = workspace / "mock-log" / "tools.jsonl"
        mock_log.parent.mkdir()
        mock_log.write_text('{"tool": "projects_list"}\n', encoding="utf-8")
        process = subprocess.CompletedProcess(
            args=["fixture"],
            returncode=0,
            stdout='{"tool":"mcp__roboflow__projects_list"}',
            stderr="",
        )
        result = smoke_result("fixture", read_observation(process, workspace), process)
    print(json.dumps(result, indent=2))
    return 0 if result["status"] == "ok" else 1


def main() -> int:
    """Build a disposable candidate and run requested authenticated host checks."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--host", choices=("codex", "claude", "both"), default="both")
    parser.add_argument("--codex-home", type=Path, help="Pre-authenticated disposable CODEX_HOME.")
    parser.add_argument(
        "--claude-config",
        type=Path,
        help="Pre-authenticated disposable CLAUDE_CONFIG_DIR.",
    )
    parser.add_argument("--report", type=Path, help="Write redacted JSON result here.")
    parser.add_argument(
        "--self-test",
        action="store_true",
        help="Run parser criteria without a host session.",
    )
    args = parser.parse_args()
    if args.self_test:
        return self_test()
    requested = ("codex", "claude") if args.host == "both" else (args.host,)
    missing = [
        host for host in requested if getattr(args, "codex_home" if host == "codex" else "claude_config") is None
    ]
    if missing:
        parser.error(f"{', '.join(missing)} requires its explicitly supplied authenticated disposable home")
    if not MOCK_SERVER.is_file():
        parser.error(f"missing mock MCP server: {MOCK_SERVER}")

    results: list[dict[str, Any]] = []
    with tempfile.TemporaryDirectory(prefix="sentinel-e2e-candidate-") as temporary:
        candidate = Path(temporary) / "candidate"
        build = subprocess.run(
            [sys.executable, str(BUILD_PACKAGE), "--out", str(candidate)],
            capture_output=True,
            check=False,
            cwd=ROOT,
            text=True,
            timeout=120,
        )
        if build.returncode:
            results.append(
                {
                    "host": "package",
                    "status": "failed",
                    "detail": build.stderr.strip()[:500],
                }
            )
        else:
            for host in requested:
                workspace = Path(tempfile.mkdtemp(prefix=f"sentinel-e2e-workspace-{host}-"))
                log_dir = workspace / "mock-log"
                candidate_copy = workspace / "candidate"
                shutil.copytree(candidate, candidate_copy)
                replace_mock_mcp(candidate_copy, log_dir)
                try:
                    if host == "codex":
                        results.append(install_codex(candidate_copy, args.codex_home.resolve(), workspace))
                    else:
                        results.append(install_claude(candidate_copy, args.claude_config.resolve(), workspace))
                finally:
                    shutil.rmtree(workspace)
    payload = {
        "status": "ok" if all(result["status"] == "ok" for result in results) else "failed",
        "results": results,
    }
    print(json.dumps(payload, indent=2))
    if args.report:
        args.report.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    return 0 if payload["status"] == "ok" else 1


if __name__ == "__main__":
    raise SystemExit(main())
