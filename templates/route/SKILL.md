---
name: ROUTE_NAME
description: |-
  ROUTE_USE. TRIGGER when: TODO(template) list the user phrases and outcomes that should start this skill. SKIP when: TODO(template) list the neighbouring requests that belong to another Sentinel skill, and name that skill.
allowed-tools: Bash, Read
---

# ROUTE_TITLE

TODO(template) Say in one paragraph what this ROUTE_KIND skill delivers and where it sits in the delivery loop.

## Before you start

Follow `../../resources/fde-methodology.md`. Read the user's files before asking anything, and ask at most the questions no file can answer.

## Workflow

1. TODO(template) First step.
2. TODO(template) Measure or check against the locked target before any recommendation.
3. TODO(template) Report the exact result and the one next action.

## Safety

- Never invoke a paid, data-moving, or state-changing provider action outside the host-gated path; record a sourced action brief and stop.
- Never ask for, print, or store a credential.

## Ledger

Follow `../../resources/ledger-protocol.md`. TODO(template) Name the local action this skill records, or say that it records none.
