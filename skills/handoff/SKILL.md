---
name: handoff
version: 1.0.0
description: Compact the current conversation into a handoff document for another agent to pick up.
argument-hint: "What will the next session be used for?"
---

Write a handoff document summarising the current conversation so a fresh agent can continue the work.

## Where to save

Save to `.claude/handoffs/<slug>.md` in the current repo (create the dir if
missing). `<slug>` = a short kebab-case name for the work. In a non-repo /
throwaway context, fall back to the OS temp directory.

> Why the workspace, not temp: a stable path lets the `validate-handoff` hook
> check the doc, and lets the next session find it. Per-repo location is
> config-driven (`.claude/writ.json` "artifacts.handoff"; default
> `.claude/handoffs/`).

## Keep it short

A handoff is a pointer, not a report. Aim for under ~1 page. Each section is a
few tight bullets, not prose. If you are tempted to explain something at length,
link the artifact that already explains it instead. Brevity is mandatory — a
long handoff will not be read.

## Required structure

Write these `## ` sections in this order (the `validate-handoff` hook checks
they exist and are non-empty):

- `## Goal` — what the next session should accomplish. If the user passed an
  argument, lead with it. One or two sentences.
- `## Read First` — orientation docs to read before starting (e.g. `CLAUDE.md`,
  `STATE.md`, the active plan/design doc). Pointers only. This is NOT the list
  of files you changed.
- `## State` — where things stand now: what is done, what is in flight. Bullets.
- `## Next Steps` — the concrete, ordered immediate actions for the fresh agent.
- `## Open Items` — unresolved decisions, blockers, follow-ups. Use "None" if
  truly none.
- `## Files Touched` — files this session changed, by reference (path or
  `file:line`), not pasted content.
- `## Suggested Skills` — skills the next agent should invoke.

## Rules

- Do not duplicate content already captured in other artifacts (PRDs, plans,
  ADRs, issues, commits, diffs). Reference them by path or URL instead.
- Redact sensitive information (API keys, passwords, PII).
- Do not write "I cannot verify ..." claims — verify them, get human sign-off,
  or drop the claim (the hook flags this phrase).
