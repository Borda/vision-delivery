---
name: auth-setup
description: |
  Connect or troubleshoot Sentinel's URL-only Roboflow MCP sign-in. TRIGGER when: the user asks to connect Roboflow, sign in, authorize OAuth, configure the plugin, or diagnose unavailable/unauthorized Roboflow MCP tools; the user asks whether a Roboflow API key is required for plugin installation. SKIP when: Roboflow MCP tools already work; the task is purely local, such as discussing a labeling approach for raw footage, and needs no Roboflow operation; a generated standalone client needs credentials (delegate its exact auth shape to the current official Roboflow API/inference skill).
allowed-tools: Bash, Read, AskUserQuestion
---

<objective>

Connect the bundled URL-only Roboflow MCP through the host-managed sign-in flow without asking for, reading, writing, or logging an API key. Keep useful local CV work moving when sign-in is declined or unavailable.

The repository `.mcp.json` contains only `https://mcp.roboflow.com/mcp`. Do not add headers, edit host configuration, create `.env`, or copy a remembered account/API-key recipe.

</objective>

<flow>

## 1 — Do useful work before auth

Authentication is needed only at a live Roboflow action seam. Continue local intake, media inspection, eval definition, architecture, artifact scaffolding, and economics work without blocking on account connection.

## 2 — Start host-managed sign-in

When a Roboflow operation is needed:

1. Explain the specific read or action the connection enables and whether data may leave the machine.
2. Invoke the least-invasive required Roboflow MCP read. The host should open the Roboflow sign-in/authorization flow.
3. Ask the user to review the account and requested scope in the host UI. Never ask them to paste a token or key into chat.
4. After authorization, retry one read-only operation and report only the connected workspace/account identifier needed for the task.
5. Return to the active Sentinel workflow and its frozen acceptance gate.

If the user declines, continue with local evidence or a candid `scaffold`. Do not ask again in the same session unless they request a live platform action.

## 3 — Diagnose without guessing

Use read-only host inspection first:

- Claude Code: `claude plugin list --json`
- Codex: `codex plugin list`

Confirm that `sentinel@sentinel` is enabled and the Roboflow MCP URL is present. Do not edit marketplace or MCP configuration automatically.

| Symptom                                                      | Action                                                                                                                                                                    |
| ------------------------------------------------------------ | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| Plugin missing or disabled                                   | Reinstall with the two documented marketplace commands, start a new session, and retry.                                                                                   |
| Sign-in UI never appears                                     | Preserve the host error; check host/network support against current official host and Roboflow guidance. Do not fall back to a guessed key header.                        |
| Unauthorized after sign-in                                   | Ask the user to review the selected Roboflow account/scope, then retry one read-only operation. Do not request credentials in chat.                                       |
| Duplicate `roboflow` server after installing official skills | Ask the user to retain one server registration for the session; do not mutate host config without explicit direction. Sentinel still delegates platform recipes upstream. |
| Host reports auth unsupported                                | State the exact limitation. Continue locally or use a separately verified upstream client flow; do not claim the plugin is authenticated.                                 |
| MCP unavailable or schema changed                            | Stop at the platform seam, retain local work, and consult the installed official Roboflow skill/resource for the current recovery path.                                   |

</flow>

<security>

- Plugin installation and MCP registration require no credential environment variable.
- Never ask for or expose an API key, bearer token, browser code, cookie, or signed URL.
- Never infer that an account connection authorizes upload, paid training, deployment, or sensitive-data processing. Those actions keep their own data-movement, spend, and purpose gates.
- A generated standalone hosted client has a separate auth contract. Obtain it from current official Roboflow guidance and keep secrets outside source control.
- Host permissions, account budgets, and least-privilege scopes are the real enforcement boundary; Sentinel's confirmation text is not a hard authorization control.

</security>

<voice>

Follow `../../resources/fde-methodology.md`.

Use direct language:

- "Plugin installation is complete. The first live Roboflow action should open the host sign-in flow; no API-key shell command is required."
- "Roboflow is not connected in this host. I can still define the eval and prepare a local scaffold."
- "The host reports authentication as unsupported. I will not call this connected."

Do not promise that OAuth works merely because the URL is registered. Do not invent UI paths, account plan behavior, or retry timing.

</voice>
