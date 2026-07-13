#!/usr/bin/env node
// Smoke every generic Roboflow hook outcome without copying an upstream tool registry.
import { spawnSync } from "node:child_process";
import { existsSync, mkdtempSync, readFileSync, rmSync } from "node:fs";
import { tmpdir } from "node:os";
import { dirname, join, resolve } from "node:path";
import { fileURLToPath } from "node:url";

const HOOK = resolve(dirname(fileURLToPath(import.meta.url)), "../../hooks/cta.js");
let failures = 0;

function runCase(name, payload, expect) {
  const cwd = mkdtempSync(join(tmpdir(), "sentinel-hook-"));
  const results = [];
  for (let i = 0; i < (expect.repeat || 1); i++) {
    results.push(spawnSync("node", [HOOK], { cwd, input: JSON.stringify(payload), encoding: "utf8" }));
  }
  const res = results.at(-1);
  const ledgerPath = join(cwd, ".vision-delivery", "ledger.jsonl");
  const wrote = existsSync(ledgerPath);
  const rows = wrote ? readFileSync(ledgerPath, "utf8").trim().split("\n") : [];
  const record = wrote ? JSON.parse(rows.at(-1)) : null;
  const problems = [];
  if (res.status !== 0) problems.push(`exit ${res.status}`);
  if (expect.write !== wrote) problems.push(`write=${wrote}, expected ${expect.write}`);
  if (expect.rows && rows.length !== expect.rows) problems.push(`rows=${rows.length}, expected ${expect.rows}`);
  if (record) {
    for (const [field, value] of Object.entries(expect.fields || {})) {
      if (record[field] !== value) problems.push(`${field}=${record[field]}, expected ${value}`);
    }
    if (!record.event_id) problems.push("event_id is empty");
  }
  if (res.stdout) problems.push(`unexpected success output: ${res.stdout.trim()}`);
  if (problems.length) {
    failures++;
    console.error(`FAIL ${name}: ${problems.join("; ")}`);
  } else {
    console.log(`ok   ${name}`);
  }
  rmSync(cwd, { recursive: true, force: true });
}

const success = (operation, category, extra = {}) => ({
  write: true,
  fields: { action: "roboflow_mcp_call", operation, category, status: "success", ...extra },
});

runCase(
  "unknown future operation is recorded",
  {
    hook_event_name: "PostToolUse",
    session_id: "future",
    tool_use_id: "tool-future",
    tool_name: "mcp__roboflow__future_capability_execute",
    tool_input: { project_id: "ws/proj" },
    tool_response: { success: true },
  },
  success("future_capability_execute", "other", { session: "future", entity_id: "ws/proj" }),
);

runCase(
  "installed-plugin prefix is supported",
  {
    hook_event_name: "PostToolUse",
    tool_name: "mcp__plugin_sentinel_roboflow__anything_read",
    tool_input: {},
    tool_response: {},
  },
  success("anything_read", "other", { session: "hook-auto" }),
);

for (const [name, operation, category] of [
  ["training", "training_job_start", "training"],
  ["dataset generation", "dataset_version_generate", "dataset-version"],
  ["upload", "image_upload", "data-movement"],
  ["deployment", "deployment_create", "deployment"],
  ["evaluation", "prediction_evaluate", "evaluation"],
]) {
  runCase(
    `${name} category`,
    { hook_event_name: "PostToolUse", tool_name: `mcp__roboflow__${operation}`, tool_input: {}, tool_response: {} },
    success(operation, category),
  );
}

runCase(
  "non-Roboflow tool is ignored",
  { hook_event_name: "PostToolUse", tool_name: "mcp__other__deployment_create", tool_response: {} },
  { write: false },
);

runCase(
  "failure is never success",
  {
    hook_event_name: "PostToolUseFailure",
    tool_use_id: "tool-failed",
    tool_name: "mcp__roboflow__deployment_create",
    error: "quota exceeded",
  },
  { write: true, fields: { action: "roboflow_mcp_call", category: "deployment", status: "failed" } },
);

runCase(
  "result-free legacy event is unknown",
  { tool_name: "mcp__roboflow__deployment_create", tool_input: {} },
  { write: true, fields: { action: "roboflow_mcp_call", status: "unknown" } },
);

runCase(
  "error-shaped success event is failed",
  { hook_event_name: "PostToolUse", tool_name: "mcp__roboflow__training_start", tool_response: { isError: true } },
  { write: true, fields: { action: "roboflow_mcp_call", status: "failed" } },
);

runCase(
  "host event ID deduplicates redelivery",
  {
    hook_event_name: "PostToolUse",
    tool_use_id: "tool-duplicate",
    tool_name: "mcp__roboflow__training_start",
    tool_response: {},
  },
  { ...success("training_start", "training"), repeat: 2, rows: 1 },
);

runCase(
  "fallback event ID deduplicates exact legacy redelivery",
  { hook_event_name: "PostToolUse", tool_name: "mcp__roboflow__training_start", tool_input: {}, tool_response: {} },
  { ...success("training_start", "training"), repeat: 2, rows: 1 },
);

if (failures) {
  console.error(`${failures} case(s) failed`);
  process.exit(1);
}
console.log("cta_smoke: all cases pass");
