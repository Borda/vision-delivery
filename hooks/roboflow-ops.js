// Shared helpers for Sentinel hooks: project-root ledger path and Roboflow operation naming.
"use strict";

const fs = require("fs");
const path = require("path");

const ROBOFLOW_TOOL = /^mcp__(?:plugin_[A-Za-z0-9_-]+_)?roboflow__(.+)$/;
// Categories that move data, spend credits, or change provider state.
const GATED_CATEGORIES = new Set(["deployment", "training", "data-movement", "dataset-version", "destructive"]);

function projectRoot() {
  const declared = process.env.CLAUDE_PROJECT_DIR;
  if (declared && path.isAbsolute(declared)) return path.resolve(declared);
  const start = process.cwd();
  for (let current = start; ; current = path.dirname(current)) {
    if (fs.existsSync(path.join(current, ".vision-delivery")) || fs.existsSync(path.join(current, ".git"))) {
      return current;
    }
    if (current === path.dirname(current)) return start;
  }
}

function ledgerFile() {
  return path.join(projectRoot(), ".vision-delivery", "ledger.jsonl");
}

function operation(toolName) {
  const match = String(toolName || "").match(ROBOFLOW_TOOL);
  if (!match) return "";
  return match[1].replace(/[^a-zA-Z0-9_-]/g, "").slice(0, 200);
}

function operationCategory(name) {
  if (/delete|remove|destroy/i.test(name)) return "destructive";
  if (/deploy/i.test(name)) return "deployment";
  if (/train/i.test(name)) return "training";
  if (/upload|image.*(?:add|create)|data.*(?:add|create)/i.test(name)) return "data-movement";
  if (/version|generate/i.test(name)) return "dataset-version";
  if (/eval|infer|predict/i.test(name)) return "evaluation";
  return "other";
}

module.exports = { GATED_CATEGORIES, ledgerFile, operation, operationCategory, projectRoot };
