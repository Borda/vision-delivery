# Manual End-to-End Specifications

These files define manual acceptance sequences for Sentinel routes. They do not constitute an executable harness or a passing result.

Run a local development checkout with:

```bash
claude --plugin-dir .
```

For live Roboflow steps, authorize the bundled URL-only MCP connection through the host's sign-in flow. Never use an API-key-present condition to bypass that check. Exact current platform execution comes from installed official Roboflow skills or the host's current MCP resources, not from these specifications.

Every run must record the plugin/host versions, input fixture identity, independently produced gold evidence, frozen acceptance ID, upstream capability provenance, artifact/handoff validation, observed result, and unresolved external checks. Until a versioned run record exists, the route remains guided.

The automated repository gates validate structure, routing cases, scripts, hooks, and local artifact contracts separately; they do not execute these live specifications.
