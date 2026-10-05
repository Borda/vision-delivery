#!/usr/bin/env node
// Smoke the Claude PreToolUse gate and project-root ledger resolution without a live host.
import { spawnSync } from "node:child_process";
import { existsSync, mkdirSync, mkdtempSync, readFileSync, rmSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { dirname, join, resolve } from "node:path";
import { fileURLToPath } from "node:url";

const HOOKS_DIR = resolve(dirname(fileURLToPath(import.meta.url)), "../../hooks");
const GATE = join(HOOKS_DIR, "gate.js");
const CTA = join(HOOKS_DIR, "cta.js");
let failures = 0;

function sandbox(rows) {
  const root = mkdtempSync(join(tmpdir(), "sentinel-gate-"));
  mkdirSync(join(root, ".vision-delivery"));
  const lines = rows.map((row) => JSON.stringify(row)).join("\n");
  writeFileSync(join(root, ".vision-delivery", "ledger.jsonl"), lines ? `${lines}\n` : "", "utf8");
  return root;
}

function run(script, cwd, payload, rawInput) {
  const env = { ...process.env };
  delete env.CLAUDE_PROJECT_DIR;
  return spawnSync("node", [script], { cwd, env, input: rawInput ?? JSON.stringify(payload), encoding: "utf8" });
}

function decision(res) {
  if (!res.stdout.trim()) return "none";
  return JSON.parse(res.stdout).hookSpecificOutput?.permissionDecision ?? "invalid";
}

function check(name, rows, payload, expected, rawInput) {
  const root = sandbox(rows);
  const res = run(GATE, root, payload, rawInput);
  const actual = res.status === 0 ? decision(res) : `exit ${res.status}`;
  if (actual === expected) {
    console.log(`ok   ${name}`);
  } else {
    failures++;
    console.error(`FAIL ${name}: decision=${actual}, expected ${expected}; stderr=${res.stderr.trim()}`);
  }
  rmSync(root, { recursive: true, force: true });
}

const now = new Date().toISOString();
const stale = new Date(Date.now() - 48 * 60 * 60 * 1000).toISOString();
const brief = (operation, ts = now) => ({
  ts,
  action: "action_brief_emitted",
  status: "success",
  operation,
  event_id: "manual:s:brief:1",
  notes: "train v3; ~10 credits (roboflow.com/pricing 2026-10-05)",
});
const call = (tool, mode = "default") => ({
  hook_event_name: "PreToolUse",
  tool_name: `mcp__roboflow__${tool}`,
  tool_input: {},
  permission_mode: mode,
});

check("read-only call passes untouched", [], call("project_list"), "none");
check("evaluation call passes untouched", [], call("prediction_evaluate"), "none");
check("non-Roboflow tool passes untouched", [], { ...call("x"), tool_name: "mcp__other__training_start" }, "none");
check("training without brief is denied", [], call("training_start"), "deny");
check("upload without brief is denied", [], call("image_upload"), "deny");
check("delete without brief is denied", [], call("project_delete"), "deny");
check("brief for operation escalates to user", [brief("training_start")], call("training_start"), "ask");
check("brief for category escalates to user", [brief("deployment")], call("deployment_create"), "ask");
check("brief for other operation does not approve", [brief("image_upload")], call("training_start"), "deny");
check("stale brief is ignored", [brief("training_start", stale)], call("training_start"), "deny");
check(
  "stale later brief does not cancel a valid earlier one",
  [brief("training_start"), brief("training_start", stale)],
  call("training_start"),
  "ask",
);
check("failed brief is ignored", [{ ...brief("training_start"), status: "failed" }], call("training_start"), "deny");
check(
  "consumed brief is not reused",
  [brief("training_start"), { ts: now, action: "roboflow_mcp_call", operation: "training_start", status: "success" }],
  call("training_start"),
  "deny",
);
check(
  "failed call does not consume brief",
  [brief("training_start"), { ts: now, action: "roboflow_mcp_call", operation: "training_start", status: "failed" }],
  call("training_start"),
  "ask",
);
check("bypass mode cannot satisfy approval", [brief("training_start")], call("training_start", "bypassPermissions"), "deny");
check("dontAsk mode cannot satisfy approval", [brief("training_start")], call("training_start", "dontAsk"), "deny");
check("unreadable input fails closed", [], null, "deny", "{");

// F13: a session started in a nested directory must write the project-root ledger.
{
  const root = sandbox([]);
  const nested = join(root, "src", "deep");
  mkdirSync(nested, { recursive: true });
  run(CTA, nested, {
    hook_event_name: "PostToolUse",
    tool_use_id: "nested-1",
    tool_name: "mcp__roboflow__training_start",
    tool_response: { success: true },
  });
  const rootLedger = readFileSync(join(root, ".vision-delivery", "ledger.jsonl"), "utf8");
  if (rootLedger.includes("nested-1") && !existsSync(join(nested, ".vision-delivery"))) {
    console.log("ok   nested working directory writes the project-root ledger");
  } else {
    failures++;
    console.error("FAIL nested working directory did not write the project-root ledger");
  }
  rmSync(root, { recursive: true, force: true });
}

if (failures) {
  console.error(`${failures} case(s) failed`);
  process.exit(1);
}
console.log("gate_smoke: all cases pass");
