#!/usr/bin/env node
// Tool lifecycle hook: records every Roboflow MCP outcome without freezing its API schema.
"use strict";

const crypto = require("crypto");
const fs = require("fs");
const path = require("path");

const LEDGER_DIR = path.join(process.cwd(), ".vision-delivery");
const LEDGER_FILE = path.join(LEDGER_DIR, "ledger.jsonl");

function extractEntityId(toolInput) {
  if (!toolInput || typeof toolInput !== "object") return "";
  const raw = toolInput.project_id || toolInput.workspace || toolInput.project || "";
  // Allow only safe Roboflow path chars; clamp to prevent unbounded ledger growth.
  return String(raw)
    .replace(/[^a-zA-Z0-9_./-]/g, "")
    .slice(0, 200);
}

function operation(toolName) {
  const match = toolName.match(/^mcp__(?:plugin_[A-Za-z0-9_-]+_)?roboflow__(.+)$/);
  if (!match) return "";
  return match[1].replace(/[^a-zA-Z0-9_-]/g, "").slice(0, 200);
}

function operationCategory(name) {
  if (/deploy/i.test(name)) return "deployment";
  if (/train/i.test(name)) return "training";
  if (/upload|image.*(?:add|create)|data.*(?:add|create)/i.test(name)) return "data-movement";
  if (/version|generate/i.test(name)) return "dataset-version";
  if (/eval|infer|predict/i.test(name)) return "evaluation";
  return "other";
}

function eventId(payload) {
  if (typeof payload.tool_use_id === "string" && payload.tool_use_id) {
    return payload.tool_use_id.slice(0, 200);
  }
  const evidence = {
    session_id: payload.session_id || "hook-auto",
    hook_event_name: payload.hook_event_name || "legacy",
    tool_name: payload.tool_name || "",
    tool_input: payload.tool_input,
    tool_response: payload.tool_response,
    tool_result: payload.tool_result,
    error: payload.error,
    is_interrupt: payload.is_interrupt,
  };
  const digest = crypto.createHash("sha256").update(JSON.stringify(evidence)).digest("hex").slice(0, 24);
  return `hook-fallback:${digest}`;
}

function resultSignalsFailure(result) {
  if (!result || typeof result !== "object") return false;
  if (result.is_error === true || result.isError === true || result.success === false) {
    return true;
  }
  return typeof result.error === "string" && result.error.length > 0;
}

function outcome(payload) {
  if (payload.hook_event_name === "PostToolUseFailure") {
    return payload.is_interrupt === true ? "cancelled" : "failed";
  }
  if (payload.hook_event_name === "PostToolUse") {
    return resultSignalsFailure(payload.tool_response) ? "failed" : "success";
  }

  const legacyResult = payload.tool_response || payload.tool_result;
  if (!legacyResult) return "unknown";
  return resultSignalsFailure(legacyResult) ? "failed" : "success";
}

function hasEvent(ledgerFile, id) {
  if (!id || !fs.existsSync(ledgerFile)) return false;
  try {
    return fs
      .readFileSync(ledgerFile, "utf8")
      .split("\n")
      .some((line) => {
        if (!line.trim()) return false;
        try {
          return JSON.parse(line).event_id === id;
        } catch {
          return false;
        }
      });
  } catch {
    return false;
  }
}

function resultDigest(payload) {
  const result = payload.tool_response || payload.tool_result;
  if (result === undefined) return "";
  try {
    return crypto.createHash("sha256").update(JSON.stringify(result)).digest("hex").slice(0, 16);
  } catch {
    return "";
  }
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

      const observedOperation = operation(toolName);
      if (!observedOperation) process.exit(0);

      const id = eventId(payload);
      const status = outcome(payload);

      const record = {
        ts: new Date().toISOString(),
        session:
          typeof payload.session_id === "string" && payload.session_id ? payload.session_id.slice(0, 64) : "hook-auto",
        // Fixed placeholder: PostToolUse hooks can't see which skill invoked the tool.
        skill: "hook",
        action: "roboflow_mcp_call",
        operation: observedOperation,
        category: operationCategory(observedOperation),
        entity_id: extractEntityId(payload.tool_input),
        version: "0.2.0",
        status,
        source: "hook",
        event_id: id,
        result_digest: resultDigest(payload),
        notes: `auto via ${payload.hook_event_name || "legacy hook payload"}`,
      };

      fs.mkdirSync(LEDGER_DIR, { recursive: true });
      if (!hasEvent(LEDGER_FILE, id)) {
        fs.appendFileSync(LEDGER_FILE, JSON.stringify(record) + "\n", "utf8");
      }

      // The hook intentionally emits no success CTA. Tool names and result
      // schemas are upstream-owned, so the active workflow interprets them.
    } catch {
      // never block
    }
    process.exit(0);
  });
  process.stdin.on("error", () => process.exit(0));
} catch {
  process.exit(0);
}
