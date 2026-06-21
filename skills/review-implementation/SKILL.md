---
name: review-implementation
version: 2.0.0
description: Use when completing tasks, implementing major features, or before merging to verify work meets requirements
---

# Review Implementation

Orchestrate a **two-stage** review of a diff: **plan compliance first, then code quality** (Writ/SDD review ordering, `ENF-PROC-SDD-001`). Each stage is a fresh-context reviewer subagent — it never inherits your session history, so it judges the work product, not your thought process. This preserves your own context for continued work.

**Core principle:** Review early, review often — and review plan-compliance BEFORE quality, so you do not polish code that does not yet do what the plan required.

## Step 0 — Set Writ mode (silent; no-op outside a Writ repo)

This is a review pass. Set Writ review mode so file-context review rules surface and Work-gated write blockers stay off:

```bash
WR="${CLAUDE_PLUGIN_ROOT:-$(cat "${CLAUDE_PLUGIN_DATA:-$HOME/.cache/writ}/plugin-root" 2>/dev/null)}"; [ -x "$WR/bin/writ-mode-set.sh" ] && bash "$WR/bin/writ-mode-set.sh" review 2>/dev/null || true
```

> Ordering is guaranteed **by construction** here (this skill dispatches plan-review before quality-review). In Work mode (inside `/subagent-driven-development` or `/tdd-implement`) the `writ-sdd-review-order` hook also backstops it — it denies a code-quality dispatch until plan-review completion is recorded (Step 3). The hook is Work-mode-gated, so during a standalone `/review-implementation` (review mode) it stays quiet and the skill's own ordering is the guarantee.

## When to Request Review

**Mandatory:**
- After each task in subagent-driven development
- After completing a major feature
- Before merge to main

**Optional but valuable:** when stuck (fresh perspective), before refactoring (baseline), after a complex bug fix.

## How to Request

**1. Get git SHAs:**
```bash
BASE_SHA=$(git rev-parse HEAD~1)   # or origin/main, or the task's start commit
HEAD_SHA=$(git rev-parse HEAD)
```

**2. Stage 1 — dispatch the plan-compliance reviewer** (Task tool, `subagent_type: writ-plan-reviewer`).

Give it the **plan path** + the SHAs in the dispatch prompt:
- `plan`: `docs/AI_artifacts/4_plans/<slug>.md` (the plan the implementer executed)
- `base_sha`, `head_sha`

It returns JSON `{"status": "compliant"|"issues", "issues": [...]}`.
- If `issues`: surface each gap. For deviations, confirm whether intentional (justified) or a problem; for `plan_defect`, fix the plan. Re-dispatch until `compliant` (or the gaps are explicitly accepted).

> **Ad-hoc review with no plan** (e.g. "review before merge", a quick diff): skip Stage 1 and go straight to Stage 3 — plan-compliance has nothing to check. The quality reviewer still runs.

**3. Record plan-review completion** (unlocks the quality reviewer under the Work-mode gate):
```bash
WR="${CLAUDE_PLUGIN_ROOT:-$(cat "${CLAUDE_PLUGIN_DATA:-$HOME/.cache/writ}/plugin-root" 2>/dev/null)}"
SID=$(cat /tmp/writ-current-session 2>/dev/null)
[ -n "$SID" ] && [ -n "$WR" ] && python3 "$WR/bin/lib/writ-session.py" update "$SID" --set-plan-reviewed "<task_id>" 2>/dev/null || true
```
`<task_id>` = the phase/task name you are reviewing (matches the gate's task key; use `default` if your flow does not track one).

**4. Stage 3 — dispatch the code-quality reviewer** (Task tool, `subagent_type: writ-code-quality-reviewer`).

Give it `base_sha` + `head_sha`. It returns JSON `{"status": "approved"|"changes_requested", "critical": [...], "important": [...], "minor": [...]}`.

**5. Act on feedback:**
- Fix Critical issues immediately
- Fix Important issues before proceeding
- Note Minor issues for later
- Push back if a reviewer is wrong — with code/tests that prove it

## Integration with Workflows

- **Subagent-Driven Development:** review after EACH task; the Work-mode hook enforces the plan→quality order mechanically.
- **Executing plans:** review at each task or natural checkpoint.
- **Ad-hoc:** quality review before merge / when stuck (Stage 1 skipped if no plan).

## Red Flags

**Never:** skip review because "it's simple"; ignore Critical issues; proceed with unfixed Important issues; dispatch the quality reviewer before plan-compliance passes; argue with valid technical feedback.

**If a reviewer is wrong:** push back with technical reasoning; show code/tests that prove it works; request clarification.

The reviewer subagents are defined at `.claude/agents/writ-plan-reviewer.md` and `.claude/agents/writ-code-quality-reviewer.md` — dispatch them by `subagent_type`, do not hand-write a reviewer prompt.
