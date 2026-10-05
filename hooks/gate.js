#!/usr/bin/env node
// Claude Code PreToolUse gate: a paid or state-changing Roboflow MCP call needs a recorded
// action brief, and then still goes to the user's own permission prompt. Never auto-allows.
"use strict";

const fs = require("fs");
const { GATED_CATEGORIES, ledgerFile, operation, operationCategory } = require("./roboflow-ops");

const BRIEF_ACTION = "action_brief_emitted";
const BRIEF_MAX_AGE_MILLISECONDS = 24 * 60 * 60 * 1000;
// Modes where an "ask" decision could be skipped or auto-resolved without a human.
const NON_INTERACTIVE_MODES = new Set(["bypassPermissions", "dontAsk", "auto"]);

// Exit only after stdout drains: piped stdout is async on Windows, and a truncated
// decision would parse as "no decision", which fails open.
function decide(permissionDecision, reason) {
  const output = JSON.stringify({
    hookSpecificOutput: { hookEventName: "PreToolUse", permissionDecision, permissionDecisionReason: reason },
  });
  process.stdout.write(output, () => process.exit(0));
}

function readRecords(file) {
  if (!fs.existsSync(file)) return [];
  const records = [];
  for (const row of fs.readFileSync(file, "utf8").split("\n")) {
    if (!row.trim()) continue;
    try {
      const record = JSON.parse(row);
      if (record && typeof record === "object") records.push(record);
    } catch {
      // Malformed historical rows cannot approve anything.
    }
  }
  return records;
}

function briefMatches(record, observedOperation, category) {
  if (record.action !== BRIEF_ACTION || record.status !== "success") return false;
  const target = record.operation;
  return target === observedOperation || target === category;
}

// A brief covers one execution: a later recorded call of the same operation consumes it.
function openBrief(records, observedOperation, category, now) {
  let candidate = null;
  for (const record of records) {
    const ts = Date.parse(record.ts);
    if (briefMatches(record, observedOperation, category)) {
      // A malformed or stale later brief never cancels an earlier valid one.
      if (Number.isFinite(ts) && now - ts <= BRIEF_MAX_AGE_MILLISECONDS) candidate = { record, ts };
    } else if (
      candidate &&
      record.action === "roboflow_mcp_call" &&
      record.operation === observedOperation &&
      record.status === "success" &&
      Date.parse(record.ts) >= candidate.ts
    ) {
      candidate = null;
    }
  }
  return candidate ? candidate.record : null;
}

function evaluate(payload) {
  const observedOperation = operation(payload.tool_name);
  if (!observedOperation) return process.exit(0);
  const category = operationCategory(observedOperation);
  if (!GATED_CATEGORIES.has(category)) return process.exit(0);

  const brief = openBrief(readRecords(ledgerFile()), observedOperation, category, Date.now());
  if (!brief) {
    return decide(
      "deny",
      `Sentinel gate: ${observedOperation} (${category}) moves data, spends credits, or changes provider state. ` +
        `Record a sourced action brief first: ledger_append.py --action ${BRIEF_ACTION} --operation ${observedOperation} ` +
        "--status success with scope, data movement, and sourced cost estimate in --notes; then retry.",
    );
  }
  if (NON_INTERACTIVE_MODES.has(payload.permission_mode)) {
    return decide(
      "deny",
      `Sentinel gate: ${observedOperation} needs an interactive human approval; ` +
        `permission mode "${payload.permission_mode}" cannot provide one. Rerun in default mode.`,
    );
  }
  const summary = String(brief.notes || "").slice(0, 400);
  return decide("ask", `Sentinel action brief ${brief.event_id || ""} for ${observedOperation}: ${summary}`);
}

const chunks = [];
process.stdin.on("data", (chunk) => chunks.push(chunk));
process.stdin.on("end", () => {
  let payload;
  try {
    payload = JSON.parse(Buffer.concat(chunks).toString("utf8"));
  } catch {
    // Unreadable input on a Roboflow matcher fails closed.
    return decide("deny", "Sentinel gate: hook input was unreadable; refusing the provider call.");
  }
  if (!payload || typeof payload !== "object") {
    return decide("deny", "Sentinel gate: hook input was not an object; refusing the provider call.");
  }
  try {
    evaluate(payload);
  } catch (error) {
    return decide("deny", `Sentinel gate: could not read the ledger (${error.message}); refusing the provider call.`);
  }
});
