#!/usr/bin/env node
// PostToolUse hook: logs ledger-worthy Roboflow MCP events and emits a deploy CTA.
"use strict";

const fs = require("fs");
const path = require("path");

const LEDGER_DIR = path.join(process.cwd(), ".vision-delivery");
const LEDGER_FILE = path.join(LEDGER_DIR, "ledger.jsonl");

const TOOL_ACTIONS = {
  project_deployment_launch: "project_deployment_launch",
  trainings_create: "trainings_create",
  model_evals_get: "baseline_measured",
  model_evals_get_map_results: "baseline_measured",
};

function extractEntityId(toolInput) {
  if (!toolInput || typeof toolInput !== "object") return "";
  const raw = toolInput.project_id || toolInput.workspace || toolInput.project || "";
  // Allow only safe Roboflow path chars; clamp to prevent unbounded ledger growth.
  return String(raw)
    .replace(/[^a-zA-Z0-9_\-\.\/]/g, "")
    .slice(0, 200);
}

try {
  const chunks = [];
  process.stdin.on("data", (chunk) => chunks.push(chunk));
  process.stdin.on("end", () => {
    try {
      const raw = Buffer.concat(chunks).toString("utf8").trim();
      if (!raw) process.exit(0);

      const payload = JSON.parse(raw);
      const toolName = payload.tool_name || "";

      // Strip any harness MCP prefix: mcp__roboflow__X or mcp__plugin_<name>_roboflow__X -> X
      const bare = toolName.replace(/^mcp__(?:plugin_[A-Za-z0-9_-]+_)?roboflow__/, "");

      const action = TOOL_ACTIONS[bare];
      if (!action) process.exit(0);

      const record = {
        ts: new Date().toISOString(),
        session:
          typeof payload.session_id === "string" && payload.session_id ? payload.session_id.slice(0, 64) : "hook-auto",
        skill: "hook",
        action,
        entity_id: extractEntityId(payload.tool_input),
        version: "0.1.0",
        notes: "auto via PostToolUse",
      };

      fs.mkdirSync(LEDGER_DIR, { recursive: true });
      fs.appendFileSync(LEDGER_FILE, JSON.stringify(record) + "\n", "utf8");

      if (action === "project_deployment_launch") {
        process.stdout.write("🚀 Deployment launched — track it at https://app.roboflow.com\n");
      }
    } catch (_) {
      // never block
    }
    process.exit(0);
  });
  process.stdin.on("error", () => process.exit(0));
} catch (_) {
  process.exit(0);
}
