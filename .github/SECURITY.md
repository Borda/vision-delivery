# Security

## Report a vulnerability

Do not open a public issue for a suspected vulnerability. Use a private [GitHub Security Advisory](https://github.com/Borda/vision-delivery/security/advisories/new) or contact the [maintainer](https://github.com/Borda) privately through GitHub.

Include the affected version, impact, reproduction steps, and a minimal public-safe fixture. Do not include a real credential, private customer media, or unrelated personal data. This community project does not promise a fixed acknowledgement or remediation time.

## Trust boundary

Sentinel combines agent instructions, host-provided filesystem and shell tools, a local Node.js hook, repository scripts, and the third-party Roboflow MCP service. Installing the plugin does not create a security sandbox.

The task skills may request permission to read, write, edit, search, and run shell commands in the active project. Exact enforcement belongs to the host. Review the host permission prompt and the plugin source before granting access.

The Roboflow MCP server at `https://mcp.roboflow.com/mcp` is operated by Roboflow. Requests and task data sent through MCP leave the local machine and are governed by the authorized hosted account/session and upstream terms. Sentinel does not control Roboflow service behavior, retention, billing, or availability.

## Authentication and credentials

The repository `.mcp.json` contains only the Roboflow MCP URL. Plugin installation does not require a credential environment variable. Codex marketplace metadata requests authorization on use; the actual host-managed sign-in, account, and scope must be reviewed and verified in the live host.

Never paste authentication tokens or other credentials into chat, prompts, issues, transcripts, or tracked files. If Sentinel generates a standalone hosted client that requires credentials, follow current official Roboflow guidance and store them outside source control. Use least privilege, rotate exposed credentials through the upstream service, and prefer a non-production workspace for evaluation.

The repository hook does not intentionally read authentication material or write it to the ledger. That narrow statement is not a guarantee that the host, MCP service, shell commands, generated code, or third-party dependencies cannot expose data.

## Paid and state-changing actions

Skills instruct the agent to explain the action and expected cost, then wait for explicit confirmation before credit-spending training or deployment-class operations. This is a prose instruction, not a hard runtime authorization block. A model error, prompt injection, host defect, or changed upstream tool surface can bypass it.

Use host-level tool approvals, least-privilege credentials, account budgets, and a non-production workspace as the real control boundary. Review the target workspace/project and expected action in every approval prompt.

## Hook and ledger

Claude Code hook configuration under `hooks/` observes selected Roboflow tool lifecycle events. The hook can append local JSONL records under `.vision-delivery/ledger.jsonl`, read that file to deduplicate stable event IDs, and print a deployment link after an event it classifies as successful. It does not intentionally make network calls or spawn subprocesses.

New lifecycle records can include an outcome, event identifier, sanitized entity identifier, and digest of the host-provided result. Outcome quality depends on the host event and result fields. Records with missing result evidence remain unknown; the ledger must not be treated as an independent receipt from Roboflow.

The ledger is best-effort activity evidence, not complete telemetry, an authorization log, proof that every skill step ran, or proof that an artifact is correct. Manual skill writes and hook writes can differ. Host configurations may disable hooks, omit events, or change payloads.

Workspace, project, session, and free-form note fields can still be sensitive even when credentials are excluded. Add `.vision-delivery/` to `.gitignore`, minimize identifiers, inspect records before sharing, and delete them according to your retention policy.

## Sensitive computer-vision uses

Faces, license plates, people tracking, forms, medical imagery, worker monitoring, and location-linked media can expose personal or regulated data. Before using them, document:

1. authority and allowed purpose,
2. minimum necessary collection and retention,
3. who can access local artifacts and Roboflow resources,
4. representative evaluation and bias checks,
5. a named human reviewer and appeal/override path,
6. applicable legal, privacy, security, and domain review.

Do not use Sentinel as the sole decision-maker for medical care, employment, law enforcement, access control, or physical safety. Generated measurements require calibration and domain validation before they can support physical-world claims.

## Generated artifacts and dependencies

Treat generated scripts, dependency instructions, model identifiers, URLs, and commands as untrusted until reviewed and executed in an isolated environment. Pin and scan dependencies according to your organization's policy. Do not run generated code against private data or production systems merely because an eval file or ledger row exists.

## Known limitations

- Paid-action consent is not machine-enforced.
- The ledger is local, partial, and dependent on host payload semantics.
- MCP operations send data to an upstream service.
- Skills can request broad project filesystem and shell access.
- No formal threat model, penetration test, signed release process, or verified remote branch-protection claim is published.
- Benchmarks do not certify security, privacy, fairness, or production safety.
