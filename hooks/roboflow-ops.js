// Shared helpers for Sentinel hooks: project-root ledger path, Roboflow operation naming,
// and the gate policy lookup.
"use strict";

const fs = require("fs");
const path = require("path");

// Any MCP server whose name contains "roboflow", in any letter case: the bare server, a
// plugin-provided one (plugin_<plugin>_roboflow), or a connector (claude_ai_Roboflow). The
// hook matchers in claude-hooks.json use the same rule. A server registered under a name
// without "roboflow" never reaches these hooks.
const ROBOFLOW_TOOL = /^mcp__(?:(?!__).)*roboflow(?:(?!__).)*__(.+)$/i;
const LOCK_TIMEOUT_MILLISECONDS = 5000;
const LOCK_RETRY_MILLISECONDS = 10;
// Generated from the provider's published tool catalog by scripts/build_gate_policy.py.
const POLICY_FILE = path.join(__dirname, "gate-policy.json");
// open: no brief needed. brief: one action brief per execution.
// budget: one action brief with a stated call budget covers that many calls.
const OPERATION_CLASSES = new Set(["open", "brief", "budget"]);
const UNLISTED_CLASS = "brief";

let cachedPolicy = null;

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

// Throws when the policy is missing or malformed; the gate turns that into a denial.
function loadPolicy() {
  if (cachedPolicy) return cachedPolicy;
  const policy = JSON.parse(fs.readFileSync(POLICY_FILE, "utf8"));
  if (!policy || typeof policy !== "object" || !policy.tools || typeof policy.tools !== "object") {
    throw new Error("gate policy has no tools table");
  }
  cachedPolicy = policy;
  return policy;
}

// A tool that is not in the policy, or carries an unknown class, is gated: the gate fails closed.
// "open" also needs the provider's own read-only flag, so an entry edited to open alone stays gated.
function classify(name) {
  const policy = loadPolicy();
  const entry = Object.prototype.hasOwnProperty.call(policy.tools, name) ? policy.tools[name] : null;
  if (!entry || typeof entry !== "object") {
    return { operationClass: UNLISTED_CLASS, category: "unlisted", listed: false };
  }
  let operationClass = OPERATION_CLASSES.has(entry.class) ? entry.class : UNLISTED_CLASS;
  if (operationClass === "open" && entry.read_only !== true) operationClass = UNLISTED_CLASS;
  return {
    operationClass,
    category: typeof entry.category === "string" && entry.category ? entry.category : "other",
    listed: true,
  };
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

function prepareLedgerPath(ledgerPath) {
  rejectSymlinkPath(ledgerPath);
  fs.mkdirSync(path.dirname(ledgerPath), { recursive: true });
  rejectSymlinkPath(ledgerPath);
  if (!fs.existsSync(ledgerPath)) return;
  const entry = fs.lstatSync(ledgerPath);
  if (entry.isSymbolicLink() || !entry.isFile()) {
    throw new Error(`ledger path must be a regular file: ${ledgerPath}`);
  }
}

function waitForLock() {
  Atomics.wait(new Int32Array(new SharedArrayBuffer(4)), 0, 0, LOCK_RETRY_MILLISECONDS);
}

function acquireLedgerLock(ledgerPath) {
  const lockPath = `${ledgerPath}.lock`;
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

function releaseLedgerLock(lockPath) {
  try {
    if (fs.lstatSync(lockPath).isDirectory()) fs.rmdirSync(lockPath);
  } catch {
    // A replaced lock path is left untouched rather than risking a victim delete.
  }
}

// Call only while holding the ledger lock.
function appendLedgerLine(ledgerPath, record) {
  const flags = fs.constants.O_WRONLY | fs.constants.O_APPEND | fs.constants.O_CREAT;
  const noFollow = fs.constants.O_NOFOLLOW || 0;
  const descriptor = fs.openSync(ledgerPath, flags | noFollow, 0o600);
  try {
    fs.writeFileSync(descriptor, JSON.stringify(record) + "\n", "utf8");
  } finally {
    fs.closeSync(descriptor);
  }
}

// Reporting label only; never decides whether a call is gated.
function operationCategory(name) {
  try {
    return classify(name).category;
  } catch {
    return "unlisted";
  }
}

function policyRelease() {
  try {
    const source = loadPolicy().source;
    return source && typeof source.release === "string" ? source.release : "unknown release";
  } catch {
    return "unknown release";
  }
}

module.exports = {
  acquireLedgerLock,
  appendLedgerLine,
  classify,
  ledgerFile,
  operation,
  operationCategory,
  policyRelease,
  prepareLedgerPath,
  projectRoot,
  releaseLedgerLock,
};
