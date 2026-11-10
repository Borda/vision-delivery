#!/usr/bin/env node
// Claude Code PreToolUse gate: a paid or state-changing Roboflow MCP call needs a recorded,
// structured action brief, and then still goes to the user's own permission prompt.
// Never auto-allows.
"use strict";

const crypto = require("crypto");
const fs = require("fs");
const {
  acquireLedgerLock,
  appendLedgerLine,
  classify,
  ledgerFile,
  operation,
  policyRelease,
  prepareLedgerPath,
  releaseLedgerLock,
} = require("./roboflow-ops");

const BRIEF_ACTION = "action_brief_emitted";
const CALL_ACTION = "roboflow_mcp_call";
// Written by this gate before a budget call goes ahead, so calls still in flight and calls
// whose outcome was never recorded count against the budget.
const RESERVE_ACTION = "roboflow_mcp_call_reserved";
const BRIEF_MAX_AGE_MILLISECONDS = 24 * 60 * 60 * 1000;
// A cost estimate dated further back than this is not a current price.
const COST_MAX_AGE_MILLISECONDS = 90 * 24 * 60 * 60 * 1000;
// A brief dated further ahead than this is ignored, so a wrong clock cannot extend its life.
const CLOCK_SKEW_MILLISECONDS = 5 * 60 * 1000;
const MAX_CALL_BUDGET = 1000;
const MAX_FIELD_CHARACTERS = 160;
// Modes where the host never shows a permission prompt. In auto mode a hook's "ask" still
// reaches the user, so auto is not listed here.
const NO_PROMPT_MODES = new Set(["bypassPermissions", "dontAsk"]);
// Outcomes the host reported as not completed. Any other recorded outcome, including
// "unknown", uses the brief: an unproven outcome must not leave a brief open. A failed or
// cancelled call leaves the brief open, and the next prompt says so, because the provider
// may have started the work before the failure.
const NOT_EXECUTED = new Set(["failed", "cancelled"]);
const TEXT_FIELDS = ["scope", "cost_unit", "cost_source", "cost_as_of", "data_movement", "rollback"];
const ISO_DATE = /^\d{4}-\d{2}-\d{2}$/;

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

function validDate(value, now) {
  if (typeof value !== "string" || !ISO_DATE.test(value)) return false;
  const parsed = Date.parse(`${value}T00:00:00Z`);
  if (!Number.isFinite(parsed) || new Date(parsed).toISOString().slice(0, 10) !== value) return false;
  return parsed <= now + BRIEF_MAX_AGE_MILLISECONDS && parsed >= now - COST_MAX_AGE_MILLISECONDS;
}

// Names of the structured fields a brief lacks. The agent writes the brief, so the gate
// accepts only one a person can check at the prompt: scope, sourced and dated cost, data
// movement, rollback, and a call budget where the operation runs under one.
function briefProblems(record, operationClass, now) {
  const brief = record.brief;
  if (!brief || typeof brief !== "object" || Array.isArray(brief)) return ["structured brief fields"];
  const problems = TEXT_FIELDS.filter((field) => typeof brief[field] !== "string" || !brief[field].trim());
  if (typeof brief.cost_amount !== "number" || !Number.isFinite(brief.cost_amount) || brief.cost_amount < 0) {
    problems.push("cost_amount");
  }
  if (!problems.includes("cost_as_of") && !validDate(brief.cost_as_of, now)) problems.push("cost_as_of");
  if (operationClass === "budget") {
    const budget = brief.call_budget;
    if (!Number.isInteger(budget) || budget < 1 || budget > MAX_CALL_BUDGET) problems.push("call_budget");
  }
  return problems;
}

function callLimit(record, operationClass) {
  return operationClass === "budget" ? record.brief.call_budget : 1;
}

// Count one later ledger row against the candidate brief. `executed` counts recorded calls
// that may have run, `reserved` counts budget units this gate handed out, and `interrupted`
// counts calls the host reported as failed or cancelled.
function countUse(candidate, record) {
  if (record.action === RESERVE_ACTION) {
    candidate.reserved += 1;
    candidate.reservedIds.add(record.event_id);
  } else if (NOT_EXECUTED.has(record.status)) {
    candidate.interrupted += 1;
  } else {
    candidate.executed += 1;
  }
  candidate.used = Math.max(candidate.executed, candidate.reserved);
}

// Walk the ledger in append order. The latest fresh, complete brief for this exact operation
// is the candidate; each later recorded call or reservation of the operation uses it.
function briefState(records, observedOperation, operationClass, now) {
  let candidate = null;
  let rejected = null;
  let exhausted = null;
  for (const record of records) {
    if (record.operation !== observedOperation) continue;
    if (record.action === BRIEF_ACTION && record.status === "success") {
      const ts = Date.parse(record.ts);
      // A malformed, stale, or incomplete later brief never cancels an earlier valid one.
      if (!Number.isFinite(ts) || now - ts > BRIEF_MAX_AGE_MILLISECONDS || ts - now > CLOCK_SKEW_MILLISECONDS) continue;
      const problems = briefProblems(record, operationClass, now);
      if (problems.length) {
        rejected = { record, problems };
      } else {
        candidate = {
          record,
          used: 0,
          executed: 0,
          reserved: 0,
          interrupted: 0,
          reservedIds: new Set(),
          limit: callLimit(record, operationClass),
        };
        rejected = null;
        exhausted = null;
      }
    } else if (candidate && (record.action === CALL_ACTION || record.action === RESERVE_ACTION)) {
      countUse(candidate, record);
      if (candidate.used >= candidate.limit) {
        exhausted = candidate;
        candidate = null;
      }
    }
  }
  return { candidate, rejected, exhausted };
}

// Brief text is written by the agent that wants the call. Strip control characters and
// double quotes so a field can be shown inside quotes and cannot pass for another field.
function clean(value) {
  return String(value)
    .replace(/[\u0000-\u001f\u007f]+/g, " ")
    .replace(/["“”]/g, "'")
    .replace(/\s+/g, " ")
    .trim()
    .slice(0, MAX_FIELD_CHARACTERS);
}

function briefCommand(observedOperation, operationClass) {
  const budget = operationClass === "budget" ? " --call-budget <number of calls>" : "";
  return (
    `ledger_append.py --action ${BRIEF_ACTION} --operation ${observedOperation} --status success ` +
    '--scope "<what runs on what>" --cost-amount <upper estimate> --cost-unit <credits|USD> ' +
    '--cost-source "<where the price comes from>" --cost-as-of <YYYY-MM-DD> ' +
    `--data-movement "<what leaves this machine, or none>" --rollback "<how to undo, or not reversible>"${budget}`
  );
}

function denialReason(observedOperation, verdict, state) {
  const label = verdict.listed
    ? `${observedOperation} (${verdict.category})`
    : `${observedOperation} (not in the gate policy from ${policyRelease()}, so it is treated as gated)`;
  let cause = `${label} moves data, spends credits, or changes provider state.`;
  if (state.rejected) {
    const id = clean(state.rejected.record.event_id || "without an event id");
    cause += ` Brief ${id} is missing or has invalid: ${state.rejected.problems.join(", ")}.`;
  } else if (state.exhausted) {
    cause += ` Its brief ${clean(state.exhausted.record.event_id || "")} is used up (${state.exhausted.used} of ${state.exhausted.limit} calls).`;
  }
  return `Sentinel gate: ${cause} Record a sourced action brief first: ${briefCommand(observedOperation, verdict.operationClass)}; then retry.`;
}

function promptReason(observedOperation, verdict, candidate) {
  const brief = candidate.record.brief;
  const parts = [
    `Sentinel action brief "${clean(candidate.record.event_id || "")}" for ${observedOperation} (${verdict.category}).`,
    `Scope: "${clean(brief.scope)}".`,
    `Cost: up to ${brief.cost_amount} "${clean(brief.cost_unit)}" (source: "${clean(brief.cost_source)}", as of ${brief.cost_as_of}).`,
    `Data movement: "${clean(brief.data_movement)}".`,
    `Rollback: "${clean(brief.rollback)}".`,
  ];
  if (verdict.operationClass === "budget") {
    parts.push(
      `Call budget: ${candidate.limit} calls under this brief, ${candidate.used} used so far ` +
        "(every attempt that reaches this gate uses one). After one call has run, later calls " +
        "within the budget follow your normal permission rules; in auto mode each one is asked.",
    );
  }
  if (candidate.interrupted > 0) {
    parts.push(
      `Warning: ${candidate.interrupted} earlier call(s) under this brief ended failed or cancelled; ` +
        "the provider may already have started that work, so its cost may already be spent.",
    );
  }
  if (!verdict.listed) parts.push(`Note: this tool is not in the gate policy from ${policyRelease()}.`);
  return parts.join(" ");
}

function noPromptDenial(observedOperation, mode) {
  return (
    `Sentinel gate: ${observedOperation} needs an interactive human approval; ` +
    `permission mode "${mode}" never shows a prompt. Rerun in default mode.`
  );
}

function reservation(payload, observedOperation, verdict, candidate) {
  const toolUse = typeof payload.tool_use_id === "string" && payload.tool_use_id ? payload.tool_use_id : "";
  return {
    ts: new Date().toISOString(),
    session:
      typeof payload.session_id === "string" && payload.session_id ? payload.session_id.slice(0, 64) : "hook-auto",
    skill: "hook",
    action: RESERVE_ACTION,
    operation: observedOperation,
    category: verdict.category,
    entity_id: "",
    version: "0.5.0",
    status: "attempted",
    source: "hook",
    event_id: `reserve:${(toolUse || crypto.randomUUID()).slice(0, 190)}`,
    brief_event_id: typeof candidate.record.event_id === "string" ? candidate.record.event_id.slice(0, 200) : "",
    notes: "call-budget unit reserved by the PreToolUse gate",
  };
}

// Take one budget unit under the ledger lock, so parallel calls cannot both take the last
// one. A ledger that cannot be written throws, and the caller turns that into a denial.
function reserveBudgetUnit(payload, observedOperation, verdict) {
  const file = ledgerFile();
  prepareLedgerPath(file);
  const lockPath = acquireLedgerLock(file);
  try {
    const state = briefState(readRecords(file), observedOperation, verdict.operationClass, Date.now());
    if (state.candidate) {
      const row = reservation(payload, observedOperation, verdict, state.candidate);
      // The host can run this hook twice for one call; one call takes one unit.
      if (!state.candidate.reservedIds.has(row.event_id)) appendLedgerLine(file, row);
    }
    return state;
  } finally {
    releaseLedgerLock(lockPath);
  }
}

function evaluate(payload) {
  const observedOperation = operation(payload.tool_name);
  if (!observedOperation) return process.exit(0);
  const verdict = classify(observedOperation);
  if (verdict.operationClass === "open") return process.exit(0);

  const budgeted = verdict.operationClass === "budget";
  let state = briefState(readRecords(ledgerFile()), observedOperation, verdict.operationClass, Date.now());
  if (!state.candidate) return decide("deny", denialReason(observedOperation, verdict, state));
  if (NO_PROMPT_MODES.has(payload.permission_mode)) {
    return decide("deny", noPromptDenial(observedOperation, payload.permission_mode));
  }
  if (budgeted) {
    state = reserveBudgetUnit(payload, observedOperation, verdict);
    if (!state.candidate) return decide("deny", denialReason(observedOperation, verdict, state));
    // A recorded call under this brief proves the person accepted the budget prompt. Later
    // calls inside the budget then get no decision from the gate, so the host's own
    // permission rules apply. Auto mode has no such rules a person set, so it is always asked.
    if (state.candidate.executed > 0 && payload.permission_mode !== "auto") return process.exit(0);
  }
  return decide("ask", promptReason(observedOperation, verdict, state.candidate));
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
    return decide(
      "deny",
      `Sentinel gate: could not read the gate policy or read and update the ledger (${error.message}); refusing the provider call.`,
    );
  }
});
