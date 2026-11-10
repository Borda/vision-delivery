#!/usr/bin/env node
// Apply the Claude Code hook matchers from hooks/claude-hooks.json to the tool names the
// supported dual-plugin topology produces, and check that the matchers and the JavaScript
// rule in hooks/roboflow-ops.js (used through its exported operation()) agree on every name.
//
// Each matcher is compiled the way a JavaScript host evaluates a regular expression matcher:
// new RegExp(matcher).test(toolName). This file does not run Claude Code, so it does not prove
// that the host applies the matcher exactly this way; it proves what the matcher strings and
// the hook rule say about each name.
import { readFileSync } from "node:fs";
import { createRequire } from "node:module";
import { dirname, join, resolve } from "node:path";
import { fileURLToPath } from "node:url";

const HOOKS_DIR = resolve(dirname(fileURLToPath(import.meta.url)), "../../hooks");
const HOOK_CONFIG = JSON.parse(readFileSync(join(HOOKS_DIR, "claude-hooks.json"), "utf8"));
const POLICY = JSON.parse(readFileSync(join(HOOKS_DIR, "gate-policy.json"), "utf8"));
const { operation } = createRequire(import.meta.url)(join(HOOKS_DIR, "roboflow-ops.js"));
const HOOK_EVENTS = ["PreToolUse", "PostToolUse", "PostToolUseFailure"];
let failures = 0;
let checks = 0;

function fail(message) {
  failures++;
  console.error(`FAIL ${message}`);
}

// Operation names come from the generated gate policy, never guessed.
function policyTool(name, expectedClass) {
  const entry = POLICY.tools[name];
  if (!entry || entry.class !== expectedClass) {
    fail(`policy fixture ${name}: expected class ${expectedClass}, policy has ${entry ? entry.class : "no entry"}`);
  }
  return name;
}

const GATED = policyTool("trainings_create", "brief");
const READ = policyTool("projects_list", "open");

// The supported topology on Claude Code: Sentinel and the official Roboflow plugin installed
// side by side. Each plugin declares an MCP server named "roboflow"; a plugin's server reaches
// tools as plugin_<plugin>_<server>. A bare server and a connector are listed because a user
// can also configure the same service that way.
const MATCHING = [
  ["bare server (user or project configuration)", `mcp__roboflow__${GATED}`, GATED],
  ["bare server, read-only tool", `mcp__roboflow__${READ}`, READ],
  ["upstream Roboflow plugin server", `mcp__plugin_roboflow_roboflow__${GATED}`, GATED],
  ["upstream Roboflow plugin server, read-only tool", `mcp__plugin_roboflow_roboflow__${READ}`, READ],
  ["Sentinel installed as a plugin", `mcp__plugin_sentinel_roboflow__${GATED}`, GATED],
  ["Sentinel installed as a plugin, read-only tool", `mcp__plugin_sentinel_roboflow__${READ}`, READ],
  ["connector-style server name", `mcp__claude_ai_Roboflow__${GATED}`, GATED],
  ["mixed-case server name", `mcp__RoboFlow__${GATED}`, GATED],
  ["upper-case server name", `mcp__ROBOFLOW__${GATED}`, GATED],
  ["server name with roboflow and a suffix", `mcp__roboflow-mcp__${GATED}`, GATED],
];

const NOT_MATCHING = [
  ["another server whose tool mentions roboflow", "mcp__other__roboflow_export"],
  ["another server whose tool starts with roboflow and a separator", "mcp__other__roboflow__export"],
  ["Roboflow service registered under a name without roboflow", `mcp__rf__${GATED}`],
  ["plugin server named without roboflow", `mcp__plugin_sentinel_rf__${GATED}`],
  ["built-in host tool", "Bash"],
  ["roboflow without the MCP prefix", `roboflow__${GATED}`],
  ["Roboflow server with an empty tool name", "mcp__roboflow__"],
];

function collectMatchers() {
  const hooks = HOOK_CONFIG.hooks;
  if (!hooks || typeof hooks !== "object") {
    fail("claude-hooks.json has no hooks object");
    return [];
  }
  const found = [];
  for (const event of HOOK_EVENTS) {
    const entries = hooks[event];
    if (!Array.isArray(entries) || entries.length === 0) {
      fail(`claude-hooks.json registers no ${event} hook`);
      continue;
    }
    for (const entry of entries) {
      if (typeof entry.matcher !== "string" || !entry.matcher) {
        fail(`${event} entry has no matcher string`);
        continue;
      }
      found.push({ event, source: entry.matcher });
    }
  }
  for (const event of Object.keys(hooks)) {
    if (!HOOK_EVENTS.includes(event)) fail(`claude-hooks.json registers an event this test does not cover: ${event}`);
  }
  return found;
}

function compile(matcher) {
  try {
    return new RegExp(matcher.source);
  } catch (error) {
    fail(`${matcher.event} matcher does not compile as a JavaScript regular expression: ${error.message}`);
    return null;
  }
}

function checkName(matchers, label, toolName, expectedOperation) {
  checks++;
  const expectMatch = expectedOperation !== null;
  const observed = operation(toolName);
  if (expectMatch && observed !== expectedOperation) {
    fail(`${label}: roboflow-ops operation(${toolName}) = ${JSON.stringify(observed)}, expected ${expectedOperation}`);
  }
  if (!expectMatch && observed !== "") {
    fail(`${label}: roboflow-ops operation(${toolName}) = ${JSON.stringify(observed)}, expected no match`);
  }
  for (const { event, pattern } of matchers) {
    const matched = pattern.test(toolName);
    if (matched !== expectMatch) {
      fail(`${label}: ${event} matcher ${matched ? "matches" : "misses"} ${toolName}`);
    }
    if (matched !== (observed !== "")) {
      fail(`${label}: ${event} matcher and roboflow-ops disagree on ${toolName}`);
    }
  }
}

const raw = collectMatchers();
const distinct = new Set(raw.map((matcher) => matcher.source));
if (distinct.size !== 1) {
  fail(`hook events use ${distinct.size} different matchers; all three must use the same one`);
}
const compiled = raw
  .map((matcher) => ({ event: matcher.event, pattern: compile(matcher) }))
  .filter((matcher) => matcher.pattern !== null);
const coveredEvents = new Set(compiled.map((matcher) => matcher.event));
for (const event of HOOK_EVENTS) {
  if (!coveredEvents.has(event)) fail(`no compiled matcher for ${event}`);
}

for (const [label, toolName, expectedOperation] of MATCHING) checkName(compiled, label, toolName, expectedOperation);
for (const [label, toolName] of NOT_MATCHING) checkName(compiled, label, toolName, null);

if (failures) {
  console.error(`${failures} matcher topology check(s) failed`);
  process.exit(1);
}
console.log(
  `Hook matcher topology: ${HOOK_EVENTS.length} events share one matcher; ` +
    `${checks} tool names agree between claude-hooks.json and roboflow-ops.`,
);
