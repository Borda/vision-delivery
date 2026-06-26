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

1. Create `skills/<skill-name>/SKILL.md` with `TRIGGER when:` and `SKIP when:` in the `description` field.
2. Add `evals/trigger/<skill-name>.cases.json` with at least 4 `should_fire` and 4 `should_not_fire` cases.
3. Run `make eval-trigger` — exits 0 if all cases covered.

## Limitation

Keyword match only — does not call an LLM. A description that mentions the right words but fires on the wrong prompts will pass here and fail only in a live session. Live-judged eval deferred to M-later.
