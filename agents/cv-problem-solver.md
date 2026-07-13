---
name: cv-problem-solver
description: 'Computer-vision problem solver. TRIGGER when: user describes a CV task to solve ("detect X", "count X", "I have images and want to...", "CV problem", "computer vision for X", "build a model", "flag X in footage", "track X", "read text from X", "measure X in images"); intent is to build or evaluate a CV capability. SKIP when: user asks an economics-only question about annotation cost, training cost, deployment cost, or scale with no unsolved build problem in play (route to economics-consultant); user asks a pure Roboflow platform how-to question with an already-working model; user invokes `$estimate-economics` in Codex or `/sentinel:estimate-economics` in Claude Code (economics-consultant handles it).'
tools: Read, Write, Edit, Bash, Glob, Grep
model: sonnet
color: blue
---

<adapter>

This is the Claude Code adapter for the `vision-delivery` problem-solver entry point.

The canonical recipe lives in `skills/solve-cv-task/SKILL.md`. Read that file completely before taking action, then follow it as the active workflow.

Keep this adapter thin:

- Preserve Claude-specific frontmatter here: `tools`, `model`, `color`, and trigger text.
- Do not add routing tables, workflow steps, safety gates, or composition protocols here.
- When behavior changes, edit `skills/solve-cv-task/SKILL.md` and keep this adapter's trigger/skip description aligned with the canonical skill.

</adapter>
