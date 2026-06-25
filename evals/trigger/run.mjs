#!/usr/bin/env node
/**
 * Trigger-eval runner for vision-delivery skills — STRUCTURAL proxy.
 *
 * This runner checks that a skill's YAML frontmatter `description` field
 * DECLARES the right trigger surface (TRIGGER/SKIP clauses) to cover each
 * labeled test case. It does NOT call an LLM or verify that the model actually
 * fires on a given prompt — that requires a live-judged eval.
 *
 * TODO(M-later): live-judged trigger eval — feed cases to a real session and
 * assert the correct skill fires (or doesn't). This structural check is a
 * fast, deterministic CI gate; the live check is the faithful one.
 *
 * Exit codes: 0 = all cases covered, 1 = one or more cases uncovered.
 *
 * Usage:
 *   node evals/trigger/run.mjs                          # runs all skills
 *   node evals/trigger/run.mjs detect-and-analyze        # runs one skill
 */

import { readFileSync, readdirSync, existsSync } from 'fs';
import { join, dirname } from 'path';
import { fileURLToPath } from 'url';

const __dir = dirname(fileURLToPath(import.meta.url));
const ROOT = join(__dir, '../..');

// ── helpers ──────────────────────────────────────────────────────────────────

function parseFrontmatter(md) {
  const m = md.match(/^---\n([\s\S]+?)\n---/);
  if (!m) return {};
  // Naive YAML parser for the subset we use: key: value and key: |\n  ...
  const block = m[1];
  const result = {};
  const lines = block.split('\n');
  let currentKey = null;
  let multilineValue = [];
  let inMultiline = false;

  for (const line of lines) {
    if (inMultiline) {
      if (/^  /.test(line) || line.trim() === '') {
        multilineValue.push(line.replace(/^  /, ''));
      } else {
        result[currentKey] = multilineValue.join('\n').trim();
        inMultiline = false;
        multilineValue = [];
        currentKey = null;
      }
    }
    if (!inMultiline) {
      // multi before scalar — "key: |" would match scalar regex first otherwise
      const multi = line.match(/^(\w[\w-]*):\s*\|/);
      if (multi) { currentKey = multi[1]; inMultiline = true; multilineValue = []; continue; }
      const scalar = line.match(/^(\w[\w-]*):\s+(.+)$/);
      if (scalar) { result[scalar[1]] = scalar[2].trim(); continue; }
    }
  }
  if (inMultiline && currentKey) result[currentKey] = multilineValue.join('\n').trim();
  return result;
}

function extractClauses(description) {
  const triggerMatch = description.match(/TRIGGER when:\s*([\s\S]+?)(?=\s*SKIP when:|$)/i);
  const skipMatch    = description.match(/SKIP when:\s*([\s\S]+?)$/i);
  return {
    trigger: (triggerMatch?.[1] ?? '').toLowerCase(),
    skip:    (skipMatch?.[1]    ?? '').toLowerCase(),
  };
}

function tokenize(text) {
  // Split on non-alpha, keep tokens ≥3 chars; handles phrases like "detect and count"
  return text.split(/[^a-z]+/).filter(t => t.length >= 3);
}

function promptKeywords(prompt) {
  // Return the meaningful words from a prompt (drop stop-words)
  const stop = new Set(['the','and','or','in','on','of','a','an','to','from','for','with','my','this','me','i','is','it','are','was','how','can','do','what','have','has','need','want','build','just','tell','give','help','already']);
  return tokenize(prompt.toLowerCase()).filter(t => !stop.has(t));
}

function isCovered(keywords, clauseText) {
  // At least ONE keyword from the prompt appears in the clause text
  return keywords.some(kw => clauseText.includes(kw));
}

// ── core runner ───────────────────────────────────────────────────────────────

function runSkill(skillName) {
  const skillPath = join(ROOT, 'skills', skillName, 'SKILL.md');
  const casesPath = join(ROOT, 'evals/trigger', `${skillName}.cases.json`);

  if (!existsSync(skillPath)) {
    console.error(`  ✗ SKILL.md not found: ${skillPath}`);
    return false;
  }
  if (!existsSync(casesPath)) {
    console.error(`  ✗ cases file not found: ${casesPath}`);
    return false;
  }

  const fm = parseFrontmatter(readFileSync(skillPath, 'utf8'));
  const description = fm.description ?? '';
  if (!description) {
    console.error(`  ✗ No description in frontmatter for ${skillName}`);
    return false;
  }

  const { trigger, skip } = extractClauses(description);
  const cases = JSON.parse(readFileSync(casesPath, 'utf8'));

  let pass = 0, fail = 0;
  const rows = [];

  for (const c of (cases.should_fire ?? [])) {
    const kws = promptKeywords(c.prompt);
    const covered = isCovered(kws, trigger);
    rows.push({ type: 'should_fire', prompt: c.prompt.slice(0, 60), covered, kws: kws.slice(0, 4) });
    covered ? pass++ : fail++;
  }

  for (const c of (cases.should_not_fire ?? [])) {
    const kws = promptKeywords(c.prompt);
    const covered = isCovered(kws, skip);
    rows.push({ type: 'should_not_fire', prompt: c.prompt.slice(0, 60), covered, kws: kws.slice(0, 4) });
    covered ? pass++ : fail++;
  }

  // Print table
  console.log(`\nSkill: ${skillName}`);
  console.log(`${'TYPE'.padEnd(16)} ${'COVERED'.padEnd(8)} PROMPT`);
  console.log('─'.repeat(80));
  for (const r of rows) {
    const icon = r.covered ? '✓' : '✗';
    const hint = r.covered ? '' : `  ← keywords: [${r.kws.join(', ')}]`;
    console.log(`${r.type.padEnd(16)} ${icon.padEnd(8)} ${r.prompt}${hint}`);
  }
  console.log(`\n  ${pass} passed, ${fail} failed`);

  return fail === 0;
}

// ── main ──────────────────────────────────────────────────────────────────────

const arg = process.argv[2];

let skillNames;
if (arg) {
  skillNames = [arg];
} else {
  // Auto-discover: any skill with a matching cases file
  skillNames = readdirSync(join(ROOT, 'evals/trigger'))
    .filter(f => f.endsWith('.cases.json'))
    .map(f => f.replace('.cases.json', ''));
}

let allPassed = true;
for (const name of skillNames) {
  const passed = runSkill(name);
  if (!passed) allPassed = false;
}

if (!allPassed) {
  console.error('\n✗ One or more skills have uncovered trigger cases — update SKILL.md description.');
  process.exit(1);
}

console.log('\n✓ All trigger cases covered structurally.');
