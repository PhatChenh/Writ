---
skill_id: SKL-PROC-WORKTREE-001
node_type: Skill
domain: process
severity: medium
scope: task
trigger: "When starting feature work that needs isolation from the current workspace, when the user requests a worktree, or before executing an implementation plan that should not touch the main checkout."
statement: "Use git worktrees for isolated feature work. Apply TEC-PROC-WORKTREE-001's directory-selection priority order and run the safety verification before creating the worktree. Confirm a green baseline test run before proceeding with the plan."
rationale: "A worktree gives the implementer an isolated checkout for the feature without disturbing the main branch's working state. Without the safety verification (gitignore + baseline tests), worktrees become a source of accidental commits and inherited test failures."
tags: [feature-branch, git, isolation, process, worktree]
confidence: battle-tested
authority: human
last_validated: 2026-05-09
staleness_window: 365
evidence: doc:methodology
always_on: false
source_attribution: "writ-native"
source_commit: null
edges:
  - { target: TEC-PROC-WORKTREE-001, type: TEACHES }
  - { target: ENF-PROC-WORKTREE-001, type: GATES }
  - { target: SKL-PROC-EXEC-001, type: PRECEDES }
---

# Skill: Use a worktree for isolated feature work

## When this skill applies

- The user asks for a worktree, OR
- An implementation plan exists that you are about to execute, AND the current checkout has uncommitted state you don't want to disturb, OR
- You are about to dispatch a subagent (writ-implementer, etc.) and want its file writes scoped to a sibling branch.

## What you do

1. Invoke `TEC-PROC-WORKTREE-001` for the procedural how-to (directory selection, safety check, setup commands, baseline run).
2. Confirm the worktree's gitignore-safety per `ENF-PROC-WORKTREE-001` -- the gate denies project-local worktrees that aren't ignored.
3. After creating the worktree, run baseline tests; do not proceed on a red baseline.
4. Hand off to `SKL-PROC-EXEC-001` to execute the plan inside the worktree.

## Why this is its own skill (vs. just the Technique)

The Technique describes the *steps*; this Skill is the *trigger*. It exists so:
- Worktree usage shows up in `analyze-friction --skill-usage` -- otherwise the only signal is the ENF rule firing on a Bash deny, which is a failure-mode metric, not a usage metric.
- The methodology companion can surface "consider a worktree" when the broader query suggests isolation matters.
- The graph has a TEACHES edge to the Technique, so retrieval can hop from "I want isolation" -> Skill -> Technique -> Rule -> Anti-pattern in one Stage-4 traversal.

## Anti-patterns

- Running the implementer directly in the main checkout because "it's a small change." Small changes are how worktrees get accidentally committed in the wrong place.
- Skipping baseline tests because "the worktree is fresh." Fresh from what -- main? main might already be red.
