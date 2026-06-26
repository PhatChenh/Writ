---
name: reasonix-review-implementation
version: 2.0.0
description: Use when completing tasks, implementing major features, or before merging to verify work meets requirements (Reasonix port — dispatches reasonix-* reviewer skills via run_skill)
---

# Review Implementation (Reasonix)

> **Reasonix port.** Reviewers are dispatched as **`runAs: subagent` skills via `run_skill`** (Reasonix has no `subagent_type`/`Task`-agent mechanism). Writ's `writ-sdd-review-order` hook does **not** fire on Reasonix — review ordering is guaranteed **by construction** (this skill dispatches plan-review before quality-review). The `writ-mode-set` / `--set-plan-reviewed` bash is a harmless no-op here; left in for Claude Code parity.

Orchestrate a **two-stage** review of a diff: **plan compliance first, then code quality** (Writ/SDD review ordering, `ENF-PROC-SDD-001`). Each stage is a fresh-context reviewer subagent skill — it never inherits your session history, so it judges the work product, not your thought process. This preserves your own context for continued work.

**Core principle:** Review early, review often — and review plan-compliance BEFORE quality, so you do not polish code that does not yet do what the plan required.

## Step 0 — Set Writ mode (silent; no-op outside a Writ repo)

This is a review pass. Set Writ review mode so file-context review rules surface and Work-gated write blockers stay off:

```bash
WR="${CLAUDE_PLUGIN_ROOT:-$(cat "${CLAUDE_PLUGIN_DATA:-$HOME/.cache/writ}/plugin-root" 2>/dev/null)}"; [ -x "$WR/bin/writ-mode-set.sh" ] && bash "$WR/bin/writ-mode-set.sh" review 2>/dev/null || true
```

> Ordering is guaranteed **by construction** here (this skill dispatches plan-review before quality-review). On Reasonix there is no backstop hook — the skill's own ordering IS the guarantee. (Under Claude Code, the Work-mode `writ-sdd-review-order` hook additionally backstops it; that hook does not exist on Reasonix.)

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

**2. Stage 1 — dispatch the plan-compliance reviewer** via `run_skill`:
```
run_skill({ name: "reasonix-plan-reviewer",
            arguments: "repo: <absolute repo path — the output of `pwd`>\nPlan: docs/AI_artifacts/4_plans/<slug>.md (or full plan text)\nbase_sha: <BASE_SHA>\nhead_sha: <HEAD_SHA>" })
```
The subagent skill has no other context (not even the cwd) — `arguments` MUST carry the absolute `repo:` path, the plan path/text, and both SHAs. Without `repo:` the subagent guesses its location.

It returns JSON `{"status": "compliant"|"issues", "issues": [...]}`.
- If `issues`: surface each gap. For deviations, confirm whether intentional (justified) or a problem; for `plan_defect`, fix the plan. Re-dispatch until `compliant` (or the gaps are explicitly accepted).

> **Ad-hoc review with no plan** (e.g. "review before merge", a quick diff): skip Stage 1 and go straight to Stage 3 — plan-compliance has nothing to check. The quality reviewer still runs.

**3. Record plan-review completion (Claude Code only — no-op on Reasonix).** Reasonix has no review-order gate to unlock, so ordering holds because Stage 1 ran before Stage 3. Left in for Claude Code parity:
```bash
WR="${CLAUDE_PLUGIN_ROOT:-$(cat "${CLAUDE_PLUGIN_DATA:-$HOME/.cache/writ}/plugin-root" 2>/dev/null)}"
source "$WR/bin/lib/common.sh" 2>/dev/null && SID=$(cat "$WRIT_CURRENT_SESSION_FILE" 2>/dev/null)
[ -n "$SID" ] && python3 "$WR/bin/lib/writ-session.py" update "$SID" --set-plan-reviewed default 2>/dev/null || true
```

**4. Stage 3 — dispatch the code-quality reviewer** via `run_skill`:
```
run_skill({ name: "reasonix-code-quality-reviewer",
            arguments: "repo: <absolute repo path — the output of `pwd`>\nbase_sha: <BASE_SHA>\nhead_sha: <HEAD_SHA>" })
```
It returns JSON `{"status": "approved"|"changes_requested", "critical": [...], "important": [...], "minor": [...]}`.

**5. Act on feedback:**
- Fix Critical issues immediately
- Fix Important issues before proceeding
- Note Minor issues for later
- Push back if a reviewer is wrong — with code/tests that prove it

## Integration with Workflows

- **Reasonix Subagent-Driven Development:** review after EACH task; ordering is by-construction (this skill dispatches plan-review before quality-review — no enforcing hook on Reasonix).
- **Executing plans:** review at each task or natural checkpoint.
- **Ad-hoc:** quality review before merge / when stuck (Stage 1 skipped if no plan).

## Red Flags

**Never:** skip review because "it's simple"; ignore Critical issues; proceed with unfixed Important issues; dispatch the quality reviewer before plan-compliance passes; argue with valid technical feedback.

**If a reviewer is wrong:** push back with technical reasoning; show code/tests that prove it works; request clarification.

The reviewer subagents are the skills `reasonix-plan-reviewer` and `reasonix-code-quality-reviewer` (`runAs: subagent`) — dispatch them via `run_skill` with the `arguments` shown above, do not hand-write a reviewer prompt.
