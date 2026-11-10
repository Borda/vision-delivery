#!/usr/bin/env node
// Smoke the Claude PreToolUse gate and project-root ledger resolution without a live host.
// Every operation name used here is read from the generated gate policy, never guessed.
import { execFile, spawnSync } from "node:child_process";
import { existsSync, mkdirSync, mkdtempSync, readFileSync, rmSync, writeFileSync } from "node:fs";
import { createRequire } from "node:module";
import { tmpdir } from "node:os";
import { dirname, join, resolve } from "node:path";
import { fileURLToPath } from "node:url";

const HOOKS_DIR = resolve(dirname(fileURLToPath(import.meta.url)), "../../hooks");
const GATE = join(HOOKS_DIR, "gate.js");
const CTA = join(HOOKS_DIR, "cta.js");
const POLICY = JSON.parse(readFileSync(join(HOOKS_DIR, "gate-policy.json"), "utf8"));
const { classify } = createRequire(import.meta.url)(join(HOOKS_DIR, "roboflow-ops.js"));
const SWEEP_PARALLELISM = 16;
let failures = 0;

function fail(message) {
  failures++;
  console.error(`FAIL ${message}`);
}

// A named operation must exist in the policy with the class the case relies on.
function policyTool(name, expectedClass) {
  const entry = POLICY.tools[name];
  if (!entry || entry.class !== expectedClass) {
    fail(`policy fixture ${name}: expected class ${expectedClass}, policy has ${entry ? entry.class : "no entry"}`);
  }
  return name;
}

const READ = policyTool("projects_list", "open");
const EVAL_READ = policyTool("model_evals_get", "open");
const TRAIN = policyTool("trainings_create", "brief");
const TRAIN_POLL = policyTool("trainings_get", "open");
const UPLOAD = policyTool("image_upload", "brief");
const DELETE = policyTool("projects_delete", "brief");
const DEPLOY = policyTool("project_deployment_launch", "brief");
const WORKFLOW_RUN = policyTool("workflows_run", "brief");
const BATCH_RUN = policyTool("batch_processing_run", "brief");
const KEY_CREATE = policyTool("api_keys_create", "brief");
const INFER = policyTool("models_infer", "budget");
// Read-only upstream, but billed per call and able to take video: one brief per execution.
const MEDIA = policyTool("media_analyze", "brief");
const ENDPOINT_RUN = policyTool("project_deployment_run", "brief");
const RESERVED = "roboflow_mcp_call_reserved";

function sandbox(rows) {
  const root = mkdtempSync(join(tmpdir(), "sentinel-gate-"));
  mkdirSync(join(root, ".vision-delivery"));
  const lines = rows.map((row) => JSON.stringify(row)).join("\n");
  writeFileSync(join(root, ".vision-delivery", "ledger.jsonl"), lines ? `${lines}\n` : "", "utf8");
  return root;
}

function hookEnv() {
  const env = { ...process.env };
  delete env.CLAUDE_PROJECT_DIR;
  return env;
}

function run(script, cwd, payload, rawInput) {
  return spawnSync("node", [script], { cwd, env: hookEnv(), input: rawInput ?? JSON.stringify(payload), encoding: "utf8" });
}

function output(stdout) {
  if (!stdout.trim()) return { decision: "none", reason: "" };
  const specific = JSON.parse(stdout).hookSpecificOutput ?? {};
  return { decision: specific.permissionDecision ?? "invalid", reason: specific.permissionDecisionReason ?? "" };
}

function ledgerRows(root) {
  return readFileSync(join(root, ".vision-delivery", "ledger.jsonl"), "utf8")
    .split("\n")
    .filter(Boolean)
    .map((row) => JSON.parse(row));
}

// `reservations` is the number of budget reservation rows the ledger must hold afterwards.
function check(name, rows, payload, expected, { rawInput, reasonIncludes = [], reasonExcludes = [], reservations } = {}) {
  const root = sandbox(rows);
  const res = run(GATE, root, payload, rawInput);
  const { decision, reason } = res.status === 0 ? output(res.stdout) : { decision: `exit ${res.status}`, reason: "" };
  const problems = [];
  if (decision !== expected) problems.push(`decision=${decision}, expected ${expected}`);
  for (const text of reasonIncludes) if (!reason.includes(text)) problems.push(`reason lacks "${text}"`);
  for (const text of reasonExcludes) if (reason.includes(text)) problems.push(`reason leaks "${text}"`);
  const reservedRows = ledgerRows(root).filter((row) => row.action === RESERVED).length;
  if (reservedRows !== (reservations ?? rows.filter((row) => row.action === RESERVED).length)) {
    problems.push(`ledger holds ${reservedRows} reservation row(s)`);
  }
  if (problems.length) {
    fail(`${name}: ${problems.join("; ")}; reason=${reason}; stderr=${res.stderr.trim()}`);
  } else {
    console.log(`ok   ${name}`);
  }
  rmSync(root, { recursive: true, force: true });
}

const now = new Date().toISOString();
const today = now.slice(0, 10);
const hoursAgo = (hours) => new Date(Date.now() - hours * 60 * 60 * 1000).toISOString();
const stale = hoursAgo(48);
const fields = (extra = {}) => ({
  scope: "train detection model on conveyor v3",
  cost_amount: 10,
  cost_unit: "credits",
  cost_source: "Roboflow plans-and-pricing skill, training table",
  cost_as_of: today,
  data_movement: "none; the dataset is already in the workspace",
  rollback: "cancel the job; spent credits are not refunded",
  ...extra,
});
const brief = (operation, { ts = now, extra = {}, id = "manual:s:brief:1" } = {}) => ({
  ts,
  action: "action_brief_emitted",
  status: "success",
  operation,
  event_id: id,
  brief: fields(extra),
});
const called = (operation, status = "success") => ({ ts: now, action: "roboflow_mcp_call", operation, status });
const reserved = (operation, id) => ({ ts: now, action: RESERVED, operation, status: "attempted", event_id: `reserve:${id}` });
const daysAgo = (days) => new Date(Date.now() - days * 24 * 60 * 60 * 1000).toISOString().slice(0, 10);
const call = (tool, mode = "default") => ({
  hook_event_name: "PreToolUse",
  tool_name: `mcp__roboflow__${tool}`,
  tool_input: {},
  permission_mode: mode,
});
const without = (field) => {
  const row = brief(TRAIN);
  delete row.brief[field];
  return row;
};

// Open operations.
check("read-only call passes untouched", [], call(READ), "none");
check("evaluation read passes untouched", [], call(EVAL_READ), "none");
check("training status poll passes untouched", [], call(TRAIN_POLL), "none");
check("non-Roboflow tool passes untouched", [], { ...call("x"), tool_name: `mcp__other__${TRAIN}` }, "none");

// Gated operations without a brief.
check("training without brief is denied", [], call(TRAIN), "deny", { reasonIncludes: ["--cost-source", "--rollback"] });
check("upload without brief is denied", [], call(UPLOAD), "deny");
check("delete without brief is denied", [], call(DELETE), "deny");
check("deployment without brief is denied", [], call(DEPLOY), "deny");
check("workflow run without brief is denied", [], call(WORKFLOW_RUN), "deny");
check("batch run without brief is denied", [], call(BATCH_RUN), "deny");
check("API key creation without brief is denied", [], call(KEY_CREATE), "deny");
check("inference without brief is denied", [], call(INFER), "deny", { reasonIncludes: ["--call-budget"] });
check("tool missing from the policy is denied", [], call("future_capability_execute"), "deny", {
  reasonIncludes: ["not in the gate policy"],
});
check("plugin-prefixed tool name is gated", [], { ...call(TRAIN), tool_name: `mcp__plugin_sentinel_roboflow__${TRAIN}` }, "deny");
check("differently cased tool name is gated", [], call(READ.toUpperCase()), "deny");
// Any server whose name contains "roboflow" is gated; a server under another name never
// reaches the hook, which the docs state as a limit.
for (const server of ["Roboflow", "ROBOFLOW", "claude_ai_Roboflow", "roboflow-mcp", "plugin_roboflow_roboflow"]) {
  check(`server named ${server} is gated`, [], { ...call(TRAIN), tool_name: `mcp__${server}__${TRAIN}` }, "deny");
  check(`server named ${server} passes a read-only tool`, [], { ...call(READ), tool_name: `mcp__${server}__${READ}` }, "none");
}
check("server under an unrelated name is not seen by the gate", [], { ...call(TRAIN), tool_name: `mcp__rf__${TRAIN}` }, "none");
check("another server's tool that mentions roboflow is not matched", [], { ...call(TRAIN), tool_name: "mcp__other__roboflow_export" }, "none");

// Billed media analysis accepts video, and an endpoint run can take several inputs: both
// need a brief for every execution, never a call budget.
check("media analysis without brief is denied", [], { ...call(MEDIA), tool_input: { media_type: "video" } }, "deny");
check("media analysis with brief escalates to user", [brief(MEDIA)], { ...call(MEDIA), tool_input: { media_type: "video" } }, "ask");
check("second media analysis needs a new brief", [brief(MEDIA), called(MEDIA)], { ...call(MEDIA), tool_input: { media_type: "video" } }, "deny");
check("a call budget does not widen media analysis", [brief(MEDIA, { extra: { call_budget: 5 } }), called(MEDIA)], call(MEDIA), "deny");
check("second endpoint run needs a new brief", [brief(ENDPOINT_RUN), called(ENDPOINT_RUN)], call(ENDPOINT_RUN), "deny");

// A complete brief escalates to the user.
check("brief for operation escalates to user", [brief(TRAIN)], call(TRAIN), "ask", {
  reasonIncludes: ['Scope: "train detection model', 'Cost: up to 10 "credits"', `as of ${today}`, "Data movement:", "Rollback:"],
  reasonExcludes: ["Warning:"],
});
check("brief for unlisted tool escalates to user", [brief("future_capability_execute")], call("future_capability_execute"), "ask", {
  reasonIncludes: ["not in the gate policy"],
});
check("brief for other operation does not approve", [brief(UPLOAD)], call(TRAIN), "deny");
check("brief naming a category does not approve", [brief("training")], call(TRAIN), "deny");
check("stale brief is ignored", [brief(TRAIN, { ts: stale })], call(TRAIN), "deny");
check("future-dated brief is ignored", [brief(TRAIN, { ts: hoursAgo(-48) })], call(TRAIN), "deny");
check("stale later brief does not cancel a valid earlier one", [brief(TRAIN), brief(TRAIN, { ts: stale })], call(TRAIN), "ask");
check("failed brief is ignored", [{ ...brief(TRAIN), status: "failed" }], call(TRAIN), "deny");
check("control characters are stripped from the prompt", [brief(TRAIN, { extra: { scope: "line one\nline two\u0007" } })], call(TRAIN), "ask", {
  reasonIncludes: ['Scope: "line one line two".'],
  reasonExcludes: ["\n", "\u0007"],
});
// A field cannot close its own quotes and pose as another field.
check(
  "a brief field cannot pose as another field",
  [brief(TRAIN, { extra: { scope: 'x". Cost: up to 0 "credits" (source: "Roboflow pricing' } })],
  call(TRAIN),
  "ask",
  { reasonIncludes: [`Scope: "x'. Cost: up to 0 'credits' (source: 'Roboflow pricing".`, 'Cost: up to 10 "credits"'], reasonExcludes: ['Scope: "x".'] },
);

// Structured fields are mandatory.
check("brief with notes only is rejected", [{ ...brief(TRAIN), brief: undefined, notes: "train v3; ~10 credits" }], call(TRAIN), "deny", {
  reasonIncludes: ["structured brief fields"],
});
for (const field of ["scope", "cost_amount", "cost_unit", "cost_source", "cost_as_of", "data_movement", "rollback"]) {
  check(`brief without ${field} is rejected`, [without(field)], call(TRAIN), "deny", { reasonIncludes: [field] });
}
check("brief with a blank cost source is rejected", [brief(TRAIN, { extra: { cost_source: "  " } })], call(TRAIN), "deny");
check("brief with a negative cost is rejected", [brief(TRAIN, { extra: { cost_amount: -1 } })], call(TRAIN), "deny");
check("brief with a text cost is rejected", [brief(TRAIN, { extra: { cost_amount: "10" } })], call(TRAIN), "deny");
check("brief with an impossible date is rejected", [brief(TRAIN, { extra: { cost_as_of: "2026-02-31" } })], call(TRAIN), "deny");
check("brief with a future price date is rejected", [brief(TRAIN, { extra: { cost_as_of: "2999-01-01" } })], call(TRAIN), "deny");
check("brief with a price date over 90 days old is rejected", [brief(TRAIN, { extra: { cost_as_of: daysAgo(120) } })], call(TRAIN), "deny", {
  reasonIncludes: ["cost_as_of"],
});
check("brief with a price date 60 days old is accepted", [brief(TRAIN, { extra: { cost_as_of: daysAgo(60) } })], call(TRAIN), "ask");
check("incomplete later brief does not cancel a valid earlier one", [brief(TRAIN), without("rollback")], call(TRAIN), "ask");

// One brief, one execution.
check("consumed brief is not reused", [brief(TRAIN), called(TRAIN)], call(TRAIN), "deny", { reasonIncludes: ["used up"] });
check("unknown outcome consumes the brief", [brief(TRAIN), called(TRAIN, "unknown")], call(TRAIN), "deny");
check("failed call does not consume brief, and the prompt warns", [brief(TRAIN), called(TRAIN, "failed")], call(TRAIN), "ask", {
  reasonIncludes: ["Warning: 1 earlier call(s) under this brief ended failed or cancelled"],
});
check("cancelled call does not consume brief", [brief(TRAIN), called(TRAIN, "cancelled")], call(TRAIN), "ask");
check("call of another operation does not consume brief", [brief(TRAIN), called(UPLOAD)], call(TRAIN), "ask");
check("call recorded before the brief does not consume it", [called(TRAIN), brief(TRAIN)], call(TRAIN), "ask");
check("new brief after a consumed one escalates again", [brief(TRAIN), called(TRAIN), brief(TRAIN, { id: "manual:s:brief:2" })], call(TRAIN), "ask");
check("call budget does not widen a per-execution operation", [brief(TRAIN, { extra: { call_budget: 5 } }), called(TRAIN)], call(TRAIN), "deny");

// Budget operations: one brief with a stated call budget.
const budgetBrief = brief(INFER, { extra: { call_budget: 3 } });
check("budget brief without a call budget is rejected", [brief(INFER)], call(INFER), "deny", { reasonIncludes: ["call_budget"] });
check("budget brief above the cap is rejected", [brief(INFER, { extra: { call_budget: 100000 } })], call(INFER), "deny");
check("first call under a budget escalates to user and reserves a unit", [budgetBrief], call(INFER), "ask", {
  reasonIncludes: ["Call budget: 3 calls"],
  reservations: 1,
});
check("later call inside the budget defers to host rules and reserves a unit", [budgetBrief, reserved(INFER, "a"), called(INFER)], call(INFER), "none", {
  reservations: 2,
});
check("a ledger without reservations still counts recorded calls", [budgetBrief, called(INFER)], call(INFER), "none", { reservations: 1 });
check("unknown outcomes count against the budget", [budgetBrief, called(INFER, "unknown"), called(INFER, "unknown")], call(INFER), "none", {
  reservations: 1,
});
check(
  "failed calls alone do not prove the budget was accepted",
  [budgetBrief, called(INFER, "failed"), called(INFER, "failed"), called(INFER, "failed")],
  call(INFER),
  "ask",
  { reasonIncludes: ["Warning: 3 earlier call(s)"], reservations: 1 },
);
check("exhausted budget is denied", [budgetBrief, called(INFER), called(INFER), called(INFER)], call(INFER), "deny", {
  reasonIncludes: ["3 of 3 calls"],
});
// Calls still in flight, or calls whose outcome was never recorded, hold their units.
check("an attempt with no recorded call is asked again", [budgetBrief, reserved(INFER, "a")], call(INFER), "ask", { reservations: 2 });
check(
  "reservations alone exhaust the budget",
  [budgetBrief, reserved(INFER, "a"), reserved(INFER, "b"), reserved(INFER, "c")],
  call(INFER),
  "deny",
  { reasonIncludes: ["3 of 3 calls"] },
);
check(
  "a repeated hook run for one call takes one unit",
  [budgetBrief, reserved(INFER, "toolu_1"), called(INFER)],
  { ...call(INFER), tool_use_id: "toolu_1" },
  "none",
);
check("a reservation of another operation does not count", [budgetBrief, reserved(TRAIN, "a"), reserved(TRAIN, "b"), reserved(TRAIN, "c")], call(INFER), "ask", {
  reservations: 4,
});
check("a new budget brief starts a new count", [budgetBrief, reserved(INFER, "a"), reserved(INFER, "b"), reserved(INFER, "c"), brief(INFER, { extra: { call_budget: 2 }, id: "manual:s:brief:2" })], call(INFER), "ask", {
  reservations: 4,
});
check("a per-execution operation writes no reservation", [brief(TRAIN)], call(TRAIN), "ask", { reservations: 0 });

// A ledger that cannot be updated fails closed: the unit could not be reserved.
{
  const root = sandbox([budgetBrief, reserved(INFER, "a"), called(INFER)]);
  mkdirSync(join(root, ".vision-delivery", "ledger.jsonl.lock"));
  const res = run(GATE, root, call(INFER));
  const { decision, reason } = res.status === 0 ? output(res.stdout) : { decision: `exit ${res.status}`, reason: "" };
  if (decision === "deny" && reason.includes("ledger lock")) {
    console.log("ok   a budget call is denied when the ledger cannot be locked");
  } else {
    fail(`locked ledger: decision=${decision}, expected deny naming the ledger lock; reason=${reason}`);
  }
  rmSync(root, { recursive: true, force: true });
}

// Parallel calls cannot both take the last unit: with one of three units used, six calls at
// once get exactly two passes.
async function parallelBudget() {
  const root = sandbox([budgetBrief, reserved(INFER, "first"), called(INFER)]);
  const decisionFor = (index) =>
    new Promise((resolveDecision) => {
      const child = execFile("node", [GATE], { cwd: root, env: hookEnv() }, (error, stdout) => {
        resolveDecision(error ? `error ${error.code}` : output(stdout).decision);
      });
      child.stdin.end(JSON.stringify({ ...call(INFER), tool_use_id: `toolu_parallel_${index}` }));
    });
  const decisions = await Promise.all([0, 1, 2, 3, 4, 5].map(decisionFor));
  const passed = decisions.filter((decision) => decision === "none").length;
  const denied = decisions.filter((decision) => decision === "deny").length;
  const reservedRows = ledgerRows(root).filter((row) => row.action === RESERVED).length;
  if (passed === 2 && denied === 4 && reservedRows === 3) {
    console.log("ok   six parallel calls with two units left: two pass, four are denied");
  } else {
    fail(`parallel budget: decisions=${decisions.join(",")}, reservation rows=${reservedRows}; expected 2 none, 4 deny, 3 rows`);
  }
  rmSync(root, { recursive: true, force: true });
}
await parallelBudget();

// Permission modes.
check("auto mode asks for every call inside a budget", [budgetBrief, reserved(INFER, "a"), called(INFER)], call(INFER, "auto"), "ask", {
  reservations: 2,
});
check("auto mode still escalates to user", [brief(TRAIN)], call(TRAIN, "auto"), "ask");
check("auto mode without brief is denied", [], call(TRAIN, "auto"), "deny");
check("acceptEdits mode escalates to user", [brief(TRAIN)], call(TRAIN, "acceptEdits"), "ask");
check("bypass mode cannot satisfy approval", [brief(TRAIN)], call(TRAIN, "bypassPermissions"), "deny");
check("dontAsk mode cannot satisfy approval", [brief(TRAIN)], call(TRAIN, "dontAsk"), "deny");
check("bypass mode denies a call inside a budget", [budgetBrief, called(INFER)], call(INFER, "bypassPermissions"), "deny");
check("dontAsk mode denies a call inside a budget", [budgetBrief, called(INFER)], call(INFER, "dontAsk"), "deny");
check("unreadable input fails closed", [], null, "deny", { rawInput: "{" });

// Contract over the whole policy, in process: the class the hook applies matches the
// provider's read-only annotation unless a documented override says otherwise.
{
  const documented = new Set((POLICY.overrides ?? []).filter((row) => row.reason).map((row) => row.tool));
  const names = Object.keys(POLICY.tools);
  let gatedReads = 0;
  let openWrites = 0;
  for (const name of names) {
    const { operationClass, listed } = classify(name);
    if (!listed) fail(`policy tool ${name} is not classified as listed`);
    if (POLICY.tools[name].read_only === true && operationClass !== "open" && !documented.has(name)) gatedReads++;
    if (POLICY.tools[name].read_only !== true && operationClass === "open") openWrites++;
  }
  if (names.length !== POLICY.source.tool_count || names.length < 1) fail(`policy lists ${names.length} tools, source says ${POLICY.source.tool_count}`);
  if (gatedReads || openWrites) {
    fail(`policy contract: ${gatedReads} read-only tools gated, ${openWrites} write tools open, without a documented override`);
  } else {
    console.log(`ok   policy contract holds over ${names.length} tools: 0 read-only gated, 0 write open`);
  }
  for (const name of ["__proto__", "constructor", "toString"]) {
    if (classify(name).operationClass !== "brief") fail(`object-prototype name ${name} is not gated`);
  }
}

// The same contract at the decision level: run the real hook once per policy tool with an
// empty ledger. Open tools get no decision; every other tool is denied.
async function sweep() {
  const root = sandbox([]);
  const names = Object.keys(POLICY.tools);
  const wrong = [];
  const decisionFor = (name) =>
    new Promise((resolveDecision) => {
      const child = execFile("node", [GATE], { cwd: root, env: hookEnv() }, (error, stdout) => {
        resolveDecision(error ? `error ${error.code}` : output(stdout).decision);
      });
      child.stdin.end(JSON.stringify(call(name)));
    });
  for (let start = 0; start < names.length; start += SWEEP_PARALLELISM) {
    const batch = names.slice(start, start + SWEEP_PARALLELISM);
    const decisions = await Promise.all(batch.map(decisionFor));
    batch.forEach((name, index) => {
      const expected = POLICY.tools[name].class === "open" ? "none" : "deny";
      if (decisions[index] !== expected) wrong.push(`${name}=${decisions[index]} (expected ${expected})`);
    });
  }
  rmSync(root, { recursive: true, force: true });
  if (wrong.length) {
    fail(`gate decision sweep: ${wrong.slice(0, 10).join(", ")}${wrong.length > 10 ? ` and ${wrong.length - 10} more` : ""}`);
  } else {
    console.log(`ok   gate decision sweep over ${names.length} policy tools`);
  }
}
await sweep();

// A missing policy file fails closed, even for a tool that would be open.
{
  const copy = mkdtempSync(join(tmpdir(), "sentinel-gate-nopolicy-"));
  for (const file of ["gate.js", "roboflow-ops.js"]) writeFileSync(join(copy, file), readFileSync(join(HOOKS_DIR, file)));
  const root = sandbox([]);
  const res = run(join(copy, "gate.js"), root, call(READ));
  const { decision } = res.status === 0 ? output(res.stdout) : { decision: `exit ${res.status}` };
  if (decision === "deny") {
    console.log("ok   missing gate policy fails closed");
  } else {
    fail(`missing gate policy: decision=${decision}, expected deny`);
  }
  rmSync(root, { recursive: true, force: true });
  rmSync(copy, { recursive: true, force: true });
}

// A policy entry edited to "open" stays gated unless it also carries the provider's
// read-only flag, and an entry with an unknown class is gated.
{
  const copy = mkdtempSync(join(tmpdir(), "sentinel-gate-edited-"));
  for (const file of ["gate.js", "roboflow-ops.js"]) writeFileSync(join(copy, file), readFileSync(join(HOOKS_DIR, file)));
  const edited = JSON.parse(JSON.stringify(POLICY));
  edited.tools[TRAIN].class = "open";
  edited.tools[UPLOAD].class = "allow";
  writeFileSync(join(copy, "gate-policy.json"), JSON.stringify(edited));
  for (const tool of [TRAIN, UPLOAD]) {
    const root = sandbox([]);
    const res = run(join(copy, "gate.js"), root, call(tool));
    const { decision } = res.status === 0 ? output(res.stdout) : { decision: `exit ${res.status}` };
    if (decision === "deny") {
      console.log(`ok   edited policy entry for ${tool} stays gated`);
    } else {
      fail(`edited policy entry for ${tool}: decision=${decision}, expected deny`);
    }
    rmSync(root, { recursive: true, force: true });
  }
  rmSync(copy, { recursive: true, force: true });
}

// F13: a session started in a nested directory must write the project-root ledger.
{
  const root = sandbox([]);
  const nested = join(root, "src", "deep");
  mkdirSync(nested, { recursive: true });
  run(CTA, nested, {
    hook_event_name: "PostToolUse",
    tool_use_id: "nested-1",
    tool_name: `mcp__roboflow__${TRAIN}`,
    tool_response: { success: true },
  });
  const rootLedger = readFileSync(join(root, ".vision-delivery", "ledger.jsonl"), "utf8");
  if (rootLedger.includes("nested-1") && !existsSync(join(nested, ".vision-delivery"))) {
    console.log("ok   nested working directory writes the project-root ledger");
  } else {
    fail("nested working directory did not write the project-root ledger");
  }
  rmSync(root, { recursive: true, force: true });
}

if (failures) {
  console.error(`${failures} case(s) failed`);
  process.exit(1);
}
console.log("gate_smoke: all cases pass");
