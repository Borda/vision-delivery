# evals/e2e/

End-to-end reproducibility specs — each file documents the full sequence from cold prompt to eval-passing model for one skill vertical.

No executable harness yet. Run manually against a real Claude Code session with the plugin loaded.

## Run (manual)

```bash
claude --plugin-dir .
```

Then follow the numbered steps in the relevant `.e2e.md` file.

## Files

| File                         | Skill                 | Fixture                            |
| ---------------------------- | --------------------- | ---------------------------------- |
| `detect-and-analyze.e2e.md`  | `detect-and-analyze`  | `sandbox-ibs0b/cars-jnnoy-mmrcu/1` |
| `classify-or-flag.e2e.md`    | `classify-or-flag`    | TBD (M4)                           |
| `track-and-count.e2e.md`     | `track-and-count`     | TBD (M4)                           |
| `read-text.e2e.md`           | `read-text`           | TBD (M4)                           |
| `segment-and-analyze.e2e.md` | `segment-and-analyze` | TBD (M4)                           |

## Executable harness

Deferred to M-later. Will feed each `.e2e.md` spec to a headless session and assert the correct skill fires, eval threshold is met, and the deploy CTA appears exactly once.
