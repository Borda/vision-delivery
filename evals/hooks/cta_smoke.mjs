#!/usr/bin/env node
// Smoke test for hooks/cta.js — pipes synthetic PostToolUse payloads and asserts ledger writes.
// This bug class (dead matcher / wrong prefix / phantom tool names) is invisible to structural evals.
import { spawnSync } from "node:child_process";
import { mkdtempSync, readFileSync, existsSync, rmSync } from "node:fs";
import { tmpdir } from "node:os";
import { join, dirname, resolve } from "node:path";
import { fileURLToPath } from "node:url";

const CTA = resolve(dirname(fileURLToPath(import.meta.url)), "../../hooks/cta.js");
let failures = 0;

function runCase(name, payload, expect) {
  const cwd = mkdtempSync(join(tmpdir(), "cta-smoke-"));
  const res = spawnSync("node", [CTA], { cwd, input: JSON.stringify(payload), encoding: "utf8" });
  const ledgerPath = join(cwd, ".vision-delivery", "ledger.jsonl");
  const wrote = existsSync(ledgerPath);
  let record = null;
  if (wrote) record = JSON.parse(readFileSync(ledgerPath, "utf8").trim().split("\n").pop());

  const problems = [];
  if (res.status !== 0) problems.push(`exit ${res.status}`);
  if (expect.write !== wrote) problems.push(`ledger write=${wrote}, expected ${expect.write}`);
  if (expect.write && wrote) {
    if (record.action !== expect.action) problems.push(`action=${record.action}, expected ${expect.action}`);
    if (expect.session && record.session !== expect.session) problems.push(`session=${record.session}, expected ${expect.session}`);
    if (expect.entity && record.entity_id !== expect.entity) problems.push(`entity_id=${record.entity_id}, expected ${expect.entity}`);
  }
  if (expect.stdoutIncludes && !res.stdout.includes(expect.stdoutIncludes)) problems.push(`stdout missing "${expect.stdoutIncludes}"`);

  if (problems.length) {
    failures++;
    console.error(`FAIL ${name}: ${problems.join("; ")}`);
  } else {
    console.log(`ok   ${name}`);
  }
  rmSync(cwd, { recursive: true, force: true });
}

// 1. Hosted-MCP prefix, training call → ledger row with real session id
runCase("trainings_create via mcp__roboflow__ prefix",
  { session_id: "smoke-1", tool_name: "mcp__roboflow__trainings_create", tool_input: { project_id: "ws/proj" } },
  { write: true, action: "trainings_create", session: "smoke-1", entity: "ws/proj" });

// 2. Installed-plugin prefix, deploy call → ledger row + CTA line
runCase("deploy via mcp__plugin_sentinel_roboflow__ prefix",
  { session_id: "smoke-2", tool_name: "mcp__plugin_sentinel_roboflow__project_deployment_launch", tool_input: { workspace: "ws" } },
  { write: true, action: "project_deployment_launch", session: "smoke-2", entity: "ws", stdoutIncludes: "Deployment launched" });

// 3. Eval fetch → baseline_measured
runCase("model_evals_get_map_results maps to baseline_measured",
  { session_id: "smoke-3", tool_name: "mcp__roboflow__model_evals_get_map_results", tool_input: {} },
  { write: true, action: "baseline_measured", session: "smoke-3" });

// 4. Non-ledger tool → no write
runCase("unlisted tool writes nothing",
  { session_id: "smoke-4", tool_name: "mcp__roboflow__universe_search", tool_input: {} },
  { write: false });

// 5. Missing session_id → hook-auto fallback
runCase("missing session_id falls back to hook-auto",
  { tool_name: "mcp__roboflow__trainings_create", tool_input: {} },
  { write: true, action: "trainings_create", session: "hook-auto" });

// 6. Phantom legacy name must NOT be tracked (regression guard for the phantom-tool-name bug class)
runCase("legacy models_train is not a tracked tool",
  { session_id: "smoke-6", tool_name: "mcp__roboflow__models_train", tool_input: {} },
  { write: false });

if (failures) {
  console.error(`${failures} case(s) failed`);
  process.exit(1);
}
console.log("cta_smoke: all cases pass");
