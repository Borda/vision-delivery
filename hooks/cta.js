#!/usr/bin/env node
// Tool lifecycle hook: records every Roboflow MCP outcome without freezing its API schema.
"use strict";

const crypto = require("crypto");
const fs = require("fs");
const path = require("path");
const { ledgerFile, operation, operationCategory } = require("./roboflow-ops");

const LEDGER_FILE = ledgerFile();
const DIAGNOSTIC_FILE = "sentinel-hook-diagnostics.jsonl";
const MAX_DIAGNOSTIC_BYTES = 4096;
const LOCK_TIMEOUT_MILLISECONDS = 5000;
const LOCK_RETRY_MILLISECONDS = 10;

function writeDiagnostic(code) {
  const pluginData = process.env.PLUGIN_DATA || process.env.CLAUDE_PLUGIN_DATA;
  if (!pluginData || !path.isAbsolute(pluginData)) return;

  const diagnosticPath = path.join(path.resolve(pluginData), DIAGNOSTIC_FILE);
  const line = JSON.stringify({ ts: new Date().toISOString(), code }) + "\n";
  try {
    fs.mkdirSync(path.dirname(diagnosticPath), { recursive: true });
    const existing = fs.existsSync(diagnosticPath) ? fs.readFileSync(diagnosticPath, "utf8") : "";
    const rows = existing.split("\n").filter(Boolean);
    rows.push(line.trim());
    while (rows.length && Buffer.byteLength(`${rows.join("\n")}\n`) > MAX_DIAGNOSTIC_BYTES) {
      rows.shift();
    }
    fs.writeFileSync(diagnosticPath, `${rows.join("\n")}\n`, "utf8");
  } catch {
    // Hook diagnostics are best-effort and must never interrupt the host tool call.
  }
}

function extractEntityId(toolInput) {
  if (!toolInput || typeof toolInput !== "object") return "";
  const raw = toolInput.project_id || toolInput.workspace || toolInput.project || "";
  // Allow only safe Roboflow path chars; clamp to prevent unbounded ledger growth.
  return String(raw)
    .replace(/[^a-zA-Z0-9_./-]/g, "")
    .slice(0, 200);
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

function resultSignalsSuccess(result) {
  if (!result || typeof result !== "object" || Array.isArray(result)) return false;
  if (result.success === true || result.ok === true) return true;
  if (result.is_error === false || result.isError === false) return true;
  return result.status === "success" || result.status === "completed";
}

function outcome(payload) {
  if (payload.hook_event_name === "PostToolUseFailure") {
    return payload.is_interrupt === true ? "cancelled" : "failed";
  }
  if (payload.hook_event_name === "PostToolUse") {
    if (resultSignalsFailure(payload.tool_response)) return "failed";
    return resultSignalsSuccess(payload.tool_response) ? "success" : "unknown";
  }

  const legacyResult = payload.tool_response || payload.tool_result;
  if (!legacyResult) return "unknown";
  if (resultSignalsFailure(legacyResult)) return "failed";
  return resultSignalsSuccess(legacyResult) ? "success" : "unknown";
}

function rejectSymlinkPath(target) {
  for (let current = path.resolve(target); ; current = path.dirname(current)) {
    try {
      if (fs.lstatSync(current).isSymbolicLink()) {
        throw new Error(`ledger path may not contain a symlink: ${current}`);
      }
    } catch (error) {
      if (error.code !== "ENOENT") throw error;
    }
    if (current === path.dirname(current)) return;
  }
}

function prepareLedgerPath(ledgerFile) {
  rejectSymlinkPath(ledgerFile);
  fs.mkdirSync(path.dirname(ledgerFile), { recursive: true });
  rejectSymlinkPath(ledgerFile);
  if (!fs.existsSync(ledgerFile)) return;
  const entry = fs.lstatSync(ledgerFile);
  if (entry.isSymbolicLink() || !entry.isFile()) {
    throw new Error(`ledger path must be a regular file: ${ledgerFile}`);
  }
}

function waitForLock() {
  Atomics.wait(new Int32Array(new SharedArrayBuffer(4)), 0, 0, LOCK_RETRY_MILLISECONDS);
}

function acquireLedgerLock(ledgerFile) {
  const lockPath = `${ledgerFile}.lock`;
  const deadline = Date.now() + LOCK_TIMEOUT_MILLISECONDS;
  for (;;) {
    rejectSymlinkPath(lockPath);
    try {
      fs.mkdirSync(lockPath);
      return lockPath;
    } catch (error) {
      if (error.code !== "EEXIST") throw error;
      rejectSymlinkPath(lockPath);
      if (Date.now() >= deadline) {
        throw new Error(`timed out waiting for ledger lock: ${lockPath}`);
      }
      waitForLock();
    }
  }
}

function comparableRecord(record) {
  return Object.fromEntries(Object.entries(record).filter(([key]) => key !== "ts"));
}

function recordsMatch(first, second) {
  return JSON.stringify(comparableRecord(first)) === JSON.stringify(comparableRecord(second));
}

function appendLedgerRecord(record) {
  prepareLedgerPath(LEDGER_FILE);
  const lockPath = acquireLedgerLock(LEDGER_FILE);
  try {
    prepareLedgerPath(LEDGER_FILE);
    const rows = fs.existsSync(LEDGER_FILE) ? fs.readFileSync(LEDGER_FILE, "utf8").split("\n") : [];
    for (const row of rows) {
      if (!row.trim()) continue;
      try {
        const existing = JSON.parse(row);
        if (existing.event_id !== record.event_id) continue;
        if (!recordsMatch(existing, record)) writeDiagnostic("ledger-integrity-conflict");
        return;
      } catch {
        // Malformed historical rows do not prevent a separately identified event.
      }
    }
    const flags = fs.constants.O_WRONLY | fs.constants.O_APPEND | fs.constants.O_CREAT;
    const noFollow = fs.constants.O_NOFOLLOW || 0;
    const descriptor = fs.openSync(LEDGER_FILE, flags | noFollow, 0o600);
    try {
      fs.writeFileSync(descriptor, JSON.stringify(record) + "\n", "utf8");
    } finally {
      fs.closeSync(descriptor);
    }
  } finally {
    try {
      if (fs.lstatSync(lockPath).isDirectory()) fs.rmdirSync(lockPath);
    } catch {
      // A replaced lock path is left untouched rather than risking a victim delete.
    }
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

      let payload;
      try {
        payload = JSON.parse(raw);
      } catch {
        writeDiagnostic("invalid-json");
        process.exit(0);
      }
      if (!payload || typeof payload !== "object") {
        writeDiagnostic("invalid-payload");
        process.exit(0);
      }
      const toolName = typeof payload.tool_name === "string" ? payload.tool_name : "";

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
        version: "0.5.0",
        status,
        source: "hook",
        event_id: id,
        result_digest: resultDigest(payload),
        notes: `auto via ${payload.hook_event_name || "legacy hook payload"}`,
      };

      appendLedgerRecord(record);

      // The hook intentionally emits no success CTA. Tool names and result
      // schemas are upstream-owned, so the active workflow interprets them.
    } catch {
      writeDiagnostic("processing-error");
    }
    process.exit(0);
  });
  process.stdin.on("error", () => {
    writeDiagnostic("stdin-error");
    process.exit(0);
  });
} catch {
  writeDiagnostic("initialization-error");
  process.exit(0);
}
