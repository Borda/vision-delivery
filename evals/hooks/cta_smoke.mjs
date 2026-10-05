#!/usr/bin/env node
// Smoke every generic Roboflow hook outcome without copying an upstream tool registry.
import { spawnSync } from "node:child_process";
import { existsSync, mkdirSync, mkdtempSync, readFileSync, rmSync, symlinkSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { dirname, join, resolve } from "node:path";
import { fileURLToPath } from "node:url";

const HOOK = resolve(dirname(fileURLToPath(import.meta.url)), "../../hooks/cta.js");
const HOOKS_DIR = resolve(dirname(fileURLToPath(import.meta.url)), "../../hooks");
let failures = 0;

function assertHookConfiguration() {
  for (const [filename, scripts, rootVariable] of [
    ["hooks.json", { PostToolUse: "cta.js" }, "PLUGIN_ROOT"],
    ["claude-hooks.json", { PostToolUse: "cta.js", PostToolUseFailure: "cta.js", PreToolUse: "gate.js" }, "CLAUDE_PLUGIN_ROOT"],
  ]) {
    try {
      const config = JSON.parse(readFileSync(join(HOOKS_DIR, filename), "utf8"));
      const events = Object.keys(scripts).sort();
      const actualEvents = Object.keys(config.hooks || {}).sort();
      if (JSON.stringify(actualEvents) !== JSON.stringify(events)) {
        throw new Error(`events=${actualEvents.join(",")}`);
      }
      for (const eventName of events) {
        const handler = config.hooks[eventName]?.[0]?.hooks?.[0];
        const script = scripts[eventName];
        if (
          handler?.command !== `node "\${${rootVariable}}/hooks/${script}"` ||
          handler?.commandWindows !== `node "$env:${rootVariable}\\hooks\\${script}"`
        ) {
          throw new Error(`${eventName} command is not host-native`);
        }
      }
      console.log(`ok   ${filename} host-native hook configuration`);
    } catch (error) {
      failures++;
      console.error(`FAIL ${filename} hook configuration: ${error.message}`);
    }
  }
}

function runCase(name, payload, expect) {
  const cwd = mkdtempSync(join(tmpdir(), "sentinel-hook-"));
  const pluginData = expect.pluginData ? join(cwd, "plugin-data") : "";
  const env = { ...process.env, ...(expect.env || {}) };
  // A real session's project dir would redirect the ledger out of the sandbox.
  if (!expect.env?.CLAUDE_PROJECT_DIR) delete env.CLAUDE_PROJECT_DIR;
  if (expect.pluginData) env[expect.pluginData] = pluginData;
  expect.setup?.(cwd);
  const results = [];
  for (let i = 0; i < (expect.repeat || 1); i++) {
    results.push(
      spawnSync("node", [HOOK], {
        cwd,
        env,
        input: expect.rawInput ?? JSON.stringify(payload),
        encoding: "utf8",
      }),
    );
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
    if (expect.maxEntityLength && record.entity_id.length > expect.maxEntityLength) {
      problems.push(`entity_id length=${record.entity_id.length}, expected <= ${expect.maxEntityLength}`);
    }
  }
  if (expect.diagnostic) {
    const diagnosticPath = join(pluginData, "sentinel-hook-diagnostics.jsonl");
    if (!existsSync(diagnosticPath)) {
      problems.push("missing diagnostic");
    } else {
      const diagnosticText = readFileSync(diagnosticPath, "utf8");
      const diagnosticRows = diagnosticText.trim().split("\n");
      const diagnostic = JSON.parse(diagnosticRows.at(-1));
      if (diagnostic.code !== expect.diagnostic.code) {
        problems.push(`diagnostic code=${diagnostic.code}, expected ${expect.diagnostic.code}`);
      }
      if (Buffer.byteLength(diagnosticText) > expect.diagnostic.maxBytes) {
        problems.push(`diagnostic bytes exceed ${expect.diagnostic.maxBytes}`);
      }
      if (diagnosticText.includes(expect.diagnostic.redacted)) {
        problems.push("diagnostic leaked malformed payload content");
      }
    }
  }
  if (expect.noPath && existsSync(join(cwd, expect.noPath))) {
    problems.push(`unsafe relative plugin data path created: ${expect.noPath}`);
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

const unknown = (operation, category, extra = {}) => ({
  write: true,
  fields: { action: "roboflow_mcp_call", operation, category, status: "unknown", ...extra },
});

assertHookConfiguration();

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
  unknown("anything_read", "other", { session: "hook-auto" }),
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
    unknown(operation, category),
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
  "Claude cancellation is recorded once as cancelled",
  {
    hook_event_name: "PostToolUseFailure",
    tool_use_id: "tool-cancelled",
    tool_name: "mcp__roboflow__deployment_create",
    is_interrupt: true,
  },
  { write: true, fields: { action: "roboflow_mcp_call", category: "deployment", status: "cancelled" } },
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
  "modern missing result is unknown",
  { hook_event_name: "PostToolUse", tool_name: "mcp__roboflow__training_start" },
  unknown("training_start", "training"),
);

runCase(
  "modern string result is unknown",
  { hook_event_name: "PostToolUse", tool_name: "mcp__roboflow__training_start", tool_response: "unrecognized" },
  unknown("training_start", "training"),
);

runCase(
  "entity identifiers are bounded",
  {
    hook_event_name: "PostToolUse",
    tool_name: "mcp__roboflow__training_start",
    tool_input: { project_id: "p".repeat(500) },
    tool_response: { success: true },
  },
  { ...success("training_start", "training"), maxEntityLength: 200 },
);

runCase(
  "malformed Codex payload records a bounded redacted diagnostic",
  null,
  {
    write: false,
    rawInput: '{"tool_name":"mcp__roboflow__training_start","token":"secret-value-must-not-log"',
    repeat: 80,
    pluginData: "PLUGIN_DATA",
    diagnostic: { code: "invalid-json", maxBytes: 4096, redacted: "secret-value-must-not-log" },
  },
);

runCase(
  "relative plugin data is ignored for path safety",
  null,
  {
    write: false,
    rawInput: "{",
    env: { CLAUDE_PLUGIN_DATA: "relative-plugin-data" },
    noPath: "relative-plugin-data",
  },
);

runCase(
  "host event ID deduplicates redelivery",
  {
    hook_event_name: "PostToolUse",
    tool_use_id: "tool-duplicate",
    tool_name: "mcp__roboflow__training_start",
    tool_response: { success: true },
  },
  { ...success("training_start", "training"), repeat: 2, rows: 1 },
);

runCase(
  "fallback event ID deduplicates exact legacy redelivery",
  { hook_event_name: "PostToolUse", tool_name: "mcp__roboflow__training_start", tool_input: {}, tool_response: { success: true } },
  { ...success("training_start", "training"), repeat: 2, rows: 1 },
);

runCase(
  "symlinked ledger directory is refused without victim mutation",
  {
    hook_event_name: "PostToolUse",
    tool_use_id: "tool-symlink-directory",
    tool_name: "mcp__roboflow__training_start",
    tool_response: { success: true },
  },
  {
    write: false,
    pluginData: "PLUGIN_DATA",
    setup(cwd) {
      const victim = join(cwd, "victim");
      mkdirSync(victim);
      writeFileSync(join(victim, "preserve-me.txt"), "unchanged\n", "utf8");
      symlinkSync(victim, join(cwd, ".vision-delivery"));
    },
    diagnostic: { code: "processing-error", maxBytes: 4096, redacted: "never-present" },
  },
);

runCase(
  "conflicting hook redelivery is reported without replacement",
  {
    hook_event_name: "PostToolUse",
    tool_use_id: "tool-conflict",
    tool_name: "mcp__roboflow__training_start",
    tool_response: { success: true },
  },
  {
    write: true,
    rows: 1,
    pluginData: "PLUGIN_DATA",
    setup(cwd) {
      const ledgerDir = join(cwd, ".vision-delivery");
      mkdirSync(ledgerDir);
      writeFileSync(join(ledgerDir, "ledger.jsonl"), `${JSON.stringify({ event_id: "tool-conflict", status: "failed" })}\n`, "utf8");
    },
    diagnostic: { code: "ledger-integrity-conflict", maxBytes: 4096, redacted: "never-present" },
  },
);

if (failures) {
  console.error(`${failures} case(s) failed`);
  process.exit(1);
}
console.log("cta_smoke: all cases pass");
