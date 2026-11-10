# evals/trigger/

Structural trigger coverage — verifies each skill's `SKILL.md` description declares the right TRIGGER/SKIP surface against labeled prompt cases.

## Run

```bash
make eval-trigger
# or directly:
python3 evals/trigger/run.py                     # all skills
python3 evals/trigger/run.py detect-and-analyze  # one skill
```

## Files

- `run.py` — runner; parses frontmatter, keyword-matches prompts against clauses
- `*.cases.json` — labeled prompts per skill (`should_fire` / `should_not_fire`)

## Add a new skill

1. Run `python3 scripts/new_route.py <skill-name> --kind <router|flagship|preview|guided|utility> --use "<one-line use>"` from the repository root; a flagship route also needs `--scorer count` or `--scorer flag`. It creates `claude-skills/<skill-name>/SKILL.md` from `templates/route/`, creates an empty `evals/trigger/<skill-name>.cases.json`, and registers the skill in `shared/skill-roster.json`. A name that already exists is refused and nothing is written.
2. Replace every `TODO(template)` line in the new `SKILL.md`, keeping `TRIGGER when:` and `SKIP when:` in the `description` field.
3. Add at least 4 `should_fire` and 4 `should_not_fire` cases to `evals/trigger/<skill-name>.cases.json`.
4. Run `python3 scripts/sync_codex_skills.py` to generate `codex-skills/<skill-name>/SKILL.md`. Never create or edit `codex-skills/` by hand; it is generated.
5. Name the skill in each listing the scaffold printed, then run `make eval-roster` and `make eval-trigger`; each exits 0 when the skill is complete.

## Limitation

Keyword match only — does not call an LLM. A description that mentions the right words but fires on the wrong prompts will pass here and fail only in a live session. Live-judged eval deferred to M-later.
