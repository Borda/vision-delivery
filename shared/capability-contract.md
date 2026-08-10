# Sentinel dual-host capability contract

## Skill roster

Both hosts expose these thirteen capabilities:

- `auth-setup`
- `check-sentinel-setup`
- `classify-or-flag`
- `decision-report`
- `decompose-to-pipeline`
- `deliver-cv-project`
- `detect-and-analyze`
- `estimate-economics`
- `read-text`
- `recognize-pose-or-gesture`
- `segment-and-analyze`
- `solve-cv-task`
- `track-and-count`

## Routing and workflow invariants

Every capability declares a concise `TRIGGER when:` and `SKIP when:` boundary. The host-specific files keep equivalent user intent, clarification, safety stop, evidence, evaluation, and cost-gate behavior. Codex direct invocation is `$<skill-name>`; Claude direct invocation is `/sentinel:<skill-name>`. A direct invocation chooses a workflow but does not bypass its clarification, credential, or safety checks.

## MCP and authentication boundary

Roboflow MCP remains URL-only at `https://mcp.roboflow.com/mcp`. Authentication is requested only at the live platform boundary; skills never request, print, or persist credentials. Codex declares the Roboflow MCP dependency in `auth-setup` metadata. The setup-check workflow remains safe to run without a live connection.

## Acceptance and artifact boundary

Build workflows retain their frozen evaluation, cost, acceptance, and artifact gates. Decision/report workflows preserve evidence provenance and uncertainty. Each host-specific implementation links the same shared methodology and reference resources where that workflow requires them.

## Allowed host differences

Codex skills use only Codex-compatible `name` and `description` frontmatter and optional `agents/openai.yaml` metadata. Claude skills retain Claude tool allowlists and slash-command wording. The two thin Claude agents remain Claude only; no duplicate Codex agents are created. Host adaptation may change invocation spelling or metadata, but not a capability's routing, safety, acceptance, artifact, or platform-boundary contract.
