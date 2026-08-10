# End-to-End Specifications and Host Smoke

The route files define manual acceptance sequences. The deterministic mock-MCP smoke has an executable harness, but it is intentionally on-demand because it uses one model turn per host and requires separately authenticated disposable host homes.

Run the no-account parser contract locally:

```bash
make eval-e2e-self-test
```

For a host session, create and sign in to an isolated home yourself, then pass its exact path. The runner builds a disposable candidate, installs it through a local marketplace, injects only the deterministic test MCP, invokes `$solve-cv-task`, requires exactly one `projects_list` call in the mock server's independent log, and verifies one successful hook-ledger row plus `proof-brief.md`. The runner removes the plugin after the run and does not read, copy, or mutate a normal host configuration.

```bash
python evals/e2e/run_dual_host_smoke.py --host codex --codex-home /path/to/isolate
python evals/e2e/run_dual_host_smoke.py --host claude --claude-config /path/to/isolate
```

Do not treat a parser self-test or an unauthenticated-host failure as host acceptance. Preserve the redacted JSON result outside the repository or under ignored `.reports/` and attach it to the release evidence.

Run a local development checkout with:

```bash
claude --plugin-dir .
```

For live Roboflow steps, authorize the bundled URL-only MCP connection through the host's sign-in flow. Never use an API-key-present condition to bypass that check. Exact current platform execution comes from installed official Roboflow skills or the host's current MCP resources, not from these specifications.

Every run must record the plugin/host versions, input fixture identity, independently produced gold evidence, frozen acceptance ID, upstream capability provenance, artifact/handoff validation, observed result, and unresolved external checks. Until a versioned run record exists, the route remains guided.

The automated repository gates validate structure, routing cases, scripts, hooks, and local artifact contracts separately; they do not execute these live specifications.
