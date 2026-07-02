---
playbook_id: PBK-PROC-DSKORCH-001
node_type: Playbook
domain: process
severity: high
scope: task
trigger: "When implementation is delegated to a second model (deepseek via the dsk CLI) with Claude as sole orchestrator and reviewer."
statement: "Hand the implementer ONE wave of parallel-safe plan tasks at a time; review and merge each wave before the next starts; keep every implementer session single-purpose and fresh — the fast model implements, the strong model reviews and fixes."
rationale: "Wave gating bounds the blast radius of a wrong turn to one reviewable diff. A whole-plan handoff produces one giant unreviewable diff, and a session that switches roles carries implementation bias into its own review."
tags: [deepseek, delegation, orchestration, playbook, process, wave-gated]
confidence: peer-reviewed
authority: human
last_validated: 2026-07-02
staleness_window: 365
evidence: peer-reviewed
always_on: false
source_attribution: "workflow-adaptation:deepseek-orchestrate"
source_commit: null
phase_ids: []
preconditions: [PBK-PROC-PLAN-001]
dispatched_roles: []
edges: []
---

# Playbook: Orchestrate a second-model implementer

## Order of operations

1. Split the approved plan into waves — groups of parallel-safe tasks. No waves in the plan → the whole plan is one wave.
2. Dispatch one wave to a fresh fast-model implementer session via `dsk`.
3. Review the wave's diff yourself (orchestrator, strong model) before anything merges.
4. Fixes go to a strong-model session; never reuse the implementation session for review or fixes.
5. Merge, then and only then start the next wave.

## Boundaries

The orchestrator never implements alongside the delegate, and the delegate spawns no subagents. One session, one role, one wave.
