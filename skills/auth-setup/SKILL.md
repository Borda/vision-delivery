---
name: auth-setup
description: |
  API key detection, .env onboarding, gitignore guard, account creation funnel, key validation.
  TRIGGER when: ROBOFLOW_API_KEY is absent from env at session start AND a Universe-dependent action is requested (universe_search, projects_list, model search); or when user explicitly asks about "setup", "api key", "account", "roboflow key", "connect roboflow", "how do I configure".
  SKIP when: key already present in env — proceed silently with the main task, do not mention setup at all; any purely local CV task that requires no Roboflow account (labeling discussion, eval definition, approach description) — do partial work first without blocking.
allowed-tools: Bash, Read, Write, Edit, AskUserQuestion
---

<objective>

Govern all Roboflow API key handling and first-time onboarding. This skill implements the motivation-first unlock pattern: never block partial work, never pitch generics, never ask for the key twice in one session, never let the key value appear in chat or logs.

**Security invariants — non-negotiable:**

- Never ask the user to paste an API key into chat. The key is written by the user to `.env`; the plugin never reads or logs the value.
- Never include the key value in error messages, bash output, or any file other than `.env`.
- Never commit `.env`. Assert `.gitignore` includes the entry before any other file is written.
- Confirm before any spend: training/batch operations consume credits — always give an explicit cost preview and require confirmation before calling them. A key with billing access is elevated risk; warn the user once.

</objective>

<flows>

## FLOW A — Key already in env at session start

MCP connected at startup. **Do nothing.** Do not mention setup, configuration, or the key. Proceed directly with the user's task.

Detection: `ROBOFLOW_API_KEY` present in environment → MCP is already authenticated → silent proceed.

______________________________________________________________________

## FLOW B — Key missing, user has not yet asked for a Universe-dependent feature

**Do not block. Do not ask for the key.**

Continue working: describe the approach, define the eval criteria, ask what sample data the user has, present path options. The key becomes relevant only when the user opts into a Universe action. Until that moment, every question you ask should move the task forward, not gate on account creation.

______________________________________________________________________

## FLOW C — Natural unlock moment

Fires when the user asks to search Universe, see available models, or take any action that requires the MCP connection — and the key is not present.

**Step 1: Explain, then ask.**

State what the Universe search will fetch for their specific problem (not a generic pitch). Ask whether they want to proceed or work without it.

Example phrasing:

> "To search Universe I need a free Roboflow account. While you set that up I can tell you what I expect to find: [specific dataset types relevant to their problem]. You can decide if any match before committing to anything. Want me to walk you through setup, or keep going without Universe?"

If the user skips: say "Fine — [continue with the local/label-first path]." Do not ask again this session.

**Step 2: If user opts in — run the gitignore guard first.**

```bash
# Assert .gitignore covers .env before giving any key instructions.
# timeout: 5000
if [ -f ".gitignore" ]; then
    grep -qxF ".env" .gitignore || echo "MISSING"
else
    echo "NO_GITIGNORE"
fi
```

- If output is `MISSING`: add `.env` to `.gitignore` using Edit — append the line `.env` to the file. Report: "Added `.env` to `.gitignore`."
- If output is `NO_GITIGNORE`: create `.gitignore` with the single line `.env`. Report: "Created `.gitignore` with `.env` entry."
- If already present: no action, no comment.

**Step 3: Give account and key instructions.**

Deliver these four instructions as a numbered list — no extra prose:

1. Create account: `app.roboflow.com` — free, ~1 min, no credit card required.
2. Copy your private key: `app.roboflow.com/<workspace>/settings/api` → click **Private API Key** → Copy.
3. Open `./.env` in this project directory and add the line:
   ```
   ROBOFLOW_API_KEY=your_key_here
   ```
   Key stays local. **Never paste it into this chat.**
4. Restart the host app — Claude Code reads the project `.env` when launched; Codex must be launched with `ROBOFLOW_API_KEY` in its environment. The key does **not** take effect mid-session; restart is required.

**Step 4: Resume instruction.**

> "Come back and say 'continue' to resume here."

______________________________________________________________________

## FLOW D — User returns after restart ("continue")

**Step 1: Validate the key via a lightweight MCP call.**

Call `universe_search` with a generic query, or `projects_list`. Do not show the raw response. The goal is only to confirm the connection works.

**Step 2: On success.**

Report the connected workspace name — nothing else:

> "Connected to [workspace-name]. Searching Universe..."

Then resume from where the session left off (whatever Universe action the user originally requested).

**Step 3: On failure — diagnose clearly.**

| Symptom                       | Likely cause                                 | Instruction                                                                                                                                                                     |
| ----------------------------- | -------------------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `401 Unauthorized`            | Wrong key or wrong workspace key copied      | "The key was rejected — check you copied the **Private** API key (not the Publishable key) from the correct workspace settings page."                                           |
| `key not found` after restart | `.env` not in project root or env not loaded | "Check that `.env` exists at the project root (same directory as this session) and contains exactly: `ROBOFLOW_API_KEY=your_key_here` with no extra spaces or quotes."          |
| MCP tools unavailable         | MCP server not started / network issue       | "MCP did not start. Open a fresh terminal, navigate to this project directory, and relaunch Claude Code or Codex. If behind a VPN, check that `api.roboflow.com` is reachable." |

After giving the correction hint, repeat FLOW C Step 3 (key instruction) only if the user needs to re-write the key. Do not repeat the full onboarding; give only the specific corrective step.

______________________________________________________________________

## FLOW E — Second run in same project

`.env` already exists and MCP started authenticated → identical to FLOW A. Silent proceed. No re-prompt.

</flows>

<security>

## Key handling rules (enforced at every step)

- **Gitignore-first invariant:** `.gitignore` entry for `.env` is asserted and added (if missing) before any key instruction is delivered. Order matters — never instruct key write before gitignore is confirmed.
- **User writes the key:** the plugin never receives, stores, echoes, or logs the key value. The instruction is to write it to `.env` manually.
- **No mid-session effect:** writing `.env` after MCP has started does nothing until the host app restarts. For Codex, make sure `ROBOFLOW_API_KEY` is exported in the environment that launches Codex. Always communicate this. Never imply the key takes effect immediately.
- **Billing warning:** if the user's key has billing/training access (cannot be determined by the plugin — assume it may), surface this once when first connecting: "Keys with billing access can trigger paid operations — the plugin will always ask for confirmation before training or batch jobs."
- **Confirm before spend:** any tool call that consumes credits (training, batch inference, dataset upload that triggers a training run) requires an explicit confirmation step with a cost estimate before the call is made. This is a hard requirement, not optional UX.

</security>

<voice>

Follow the shared voice rules (Forward-Deployed-Engineer model, `skills/_shared/fde-methodology.md`) at every step.

**Do:**

- "Key not connected yet — you can still define your eval and describe your data while I look up Universe options."
- "Added `.env` to `.gitignore`. Now: open `./.env` and add `ROBOFLOW_API_KEY=your_key_here` — never paste it here."
- "Connected to [workspace-name]. Searching Universe..."
- "The key was rejected — check you copied the Private key, not the Publishable key."

**Do not:**

- "Sorry, I can't help without a Roboflow API key." (blocks; wrong)
- "Would you like to configure your API key?" (weak; non-committal)
- "Great news — you can get a free account!" (sycophancy)
- "I apologize for the inconvenience." (filler)

</voice>

<troubleshooting>

## Troubleshooting reference

### Key not found after restart

**Symptom:** MCP tools unavailable or returning auth errors despite the user restarting.

**Checks (in order):**

1. Does `.env` exist at the project root? Run `ls -la .env` — if absent, the file was not created or was saved elsewhere.
2. Is the variable name exactly `ROBOFLOW_API_KEY` (no typos, no extra spaces)?
3. Is the value unquoted? Some editors add quotes: `ROBOFLOW_API_KEY="abc"` — Roboflow MCP expects an unquoted value.
4. Was the host app restarted (not just the terminal)? The MCP server starts fresh when Claude Code or Codex launches; a reload of the chat window is not sufficient.

### 401 Unauthorized

**Symptom:** MCP returns `401` on any tool call.

**Causes:**

- Wrong key type: Publishable key used instead of Private API key. The Private key is the one under "Private API Key" in workspace settings — not the workspace API key shown on the overview page.
- Wrong workspace: copied key from a different workspace. Ensure the workspace slug in the settings URL matches the project you are working in.
- Key revoked or expired: generate a new key from workspace settings.

### MCP unreachable / tools unavailable

**Symptom:** Roboflow MCP tools do not appear or every call returns a connection error.

**Checks:**

1. Network: `curl -s https://api.roboflow.com` from the terminal — if it hangs or returns a network error, the host is unreachable (VPN, firewall, or DNS issue).
2. Plugin scope: for Claude Code, confirm the Roboflow MCP is installed with `--scope local` for this project, or globally. Check `~/.claude/settings.json` or `.claude/settings.json` for the MCP entry. For Codex, run `codex plugin list` and confirm `sentinel` is installed.
3. Fresh terminal: open a new terminal window, export `ROBOFLOW_API_KEY`, navigate to the project directory, and relaunch Claude Code or Codex. MCP servers inherit the environment from the process that starts the host app — a stale shell may not have loaded the updated key.

### Tools unavailable in a fresh session

**Symptom:** Universe search and other Roboflow tools are not in scope even after restart.

**Cause:** the Roboflow plugin may be installed globally but not activated for this project directory (scope mismatch), or the MCP server failed to start silently.

**Fix:** for Claude Code, run `claude plugin list` to verify the Roboflow MCP entry appears. If missing, reinstall: `claude plugin install sentinel --scope local` (project-local) or `claude plugin install sentinel` (global). For Codex, run `codex plugin list` and reinstall with `codex plugin add sentinel@sentinel` if needed. Then restart the host app.

</troubleshooting>
