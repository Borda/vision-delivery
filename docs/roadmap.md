---
description: What Sentinel has built, what needs a live run to prove, what comes next, and what is parked.
title: Roadmap
---

# Roadmap

This page lists direction, not dates. It separates three things that are easy to confuse: code that exists and is tested offline, claims that need a live run to prove, and work that is not started. [Support & Evidence](support-and-scope.md) states what the current evidence shows.

## Built and tested offline (0.5.0, unreleased)

- A spend gate on Claude Code that classifies each Roboflow MCP call from a policy generated from Roboflow's tool catalog, and holds paid or state-changing calls for a written brief and your approval.
- A rung 0 baseline with no Roboflow account, and a scorer that prints a 95% interval and refuses to call a result it cannot support.
- Explore and deliver modes, and a four-rung baseline ladder.
- A delegation map checked against the official Roboflow skill roster.
- A simulated approver, so the mocked plugin-versus-plain comparison can answer the gate's prompt.
- A guided labeling helper, and rung 0 predictions that are frozen in the ledger before they are scored.
- A `status` skill that says where a project stands, and a `report-outcome` skill that drafts a redacted outcome report for you to post.
- A hand-off of the candidate search to the official `workflow-from-eval` skill, inside Sentinel's locked target and held-out labels.
- One skill roster, a route template, and a rule that a published number needs a committed, masked run folder.
- A scorer task for one text value per image (exact match and character error rate), with labeling and freezing, and a converter from detections to counts or flags for the higher rungs.
- A recheck that scores fresh labeled images against the frozen target after delivery and says whether the result holds, drifted, or is uncertain.
- Economics for a batch of images per day, and an optional value at stake from your own error cost and error rates.
- A written threat model for the proof chain, and one read-only command that says whether a delivery passes its checks and what those checks do not show.

## Needs a live run to prove

These need a real account, real images, or paid model calls, so a maintainer runs them. Until a run is recorded and committed, the matching claim stays unproven.

| What                                                                                 | Why it matters                                                                      |
| ------------------------------------------------------------------------------------ | ----------------------------------------------------------------------------------- |
| One recorded session on public, licensed images: rung 0, the gate prompt, a decision | Nothing in the repository yet shows a real session end to end                       |
| The tool names a live Claude Code session receives, checked against the gate policy  | The policy is generated from a catalog Roboflow publishes for another host surface  |
| Live routing re-run on the current skills, at least two repeats, both hosts          | The only routing number predates the current routes                                 |
| The mocked comparison re-run with the gate prompt answered                           | The published comparison says nothing about the gate                                |
| Both plugins installed together, with a routing check                                | The recommended setup has never been tested as a pair                               |
| A first-session study with people new to computer vision                             | The entry-barrier claim has no evidence                                             |
| Rung 0 predictions by a separate subagent, recorded on a live host                   | The isolation step is a written procedure; no session shows a subagent following it |
| The upstream search hand-off, recorded once                                          | Nothing shows the two plugins' skills cooperating in a session                      |
| A text-reading baseline and a recheck on real images                                 | The text task, the recheck, and the delivery check have run on fixtures only        |

## Next

- Scorer coverage for the routes that still have none: box overlap, tracking, masks, and keypoints.
- Records with several text fields in one label file.
- A measured capacity table for the economics model, in place of the screening assumption.
- Fewer deliver-mode steps, where the threat model shows a step can be merged without losing a check.

## Parked

- **A gate on Codex.** Codex has no pre-action hook. Codex stays the methodology tier until it has one.
- **The gate as a general pattern for other MCP servers.** The policy file format is provider-neutral, and nothing else is planned.
- **Renaming.** The repository stays `vision-delivery` and the plugin stays `sentinel` until before 1.0.

## How to influence it

Outcome reports change priorities more than anything else: open one from the [issue chooser](https://github.com/Borda/vision-delivery/issues/new/choose). The [contributing guide](https://github.com/Borda/vision-delivery/blob/main/.github/CONTRIBUTING.md) lists the pull request lanes, and the [developing guide](developing.md) shows how to run the checks.
