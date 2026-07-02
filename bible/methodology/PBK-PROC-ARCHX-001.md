---
playbook_id: PBK-PROC-ARCHX-001
node_type: Playbook
domain: process
severity: high
scope: repo
trigger: "When starting a new project, evaluating build-vs-buy, or planning system architecture before any spec exists."
statement: "Research 2+ comparable projects first, map the user's intended approach, gap-analyze it against the field, then produce a structured architecture map (blocks, modules, per-module concerns table) as the input to project docs."
rationale: "Architecture drawn from memory produces generic, gap-filled designs. Grounding in what the field has already proven surfaces missing modules and rejected-for-a-reason patterns before anything is committed to a roadmap."
tags: [architecture, exploration, playbook, process, research-first]
confidence: peer-reviewed
authority: human
last_validated: 2026-07-02
staleness_window: 365
evidence: peer-reviewed
always_on: false
source_attribution: "workflow-adaptation:architecture-exploration"
source_commit: null
phase_ids: []
preconditions: []
dispatched_roles: []
edges:
  - { target: PBK-PROC-INITDOCS-001, type: PRECEDES }
---

# Playbook: Architecture exploration before specs

## Order of operations

1. Research comparable projects — at least 2, noting their module splits and what they deliberately left out.
2. Map the user's intended approach as modules.
3. Gap-analyze: what does the field have that the approach lacks, and vice versa? Every gap gets a keep/add/drop decision.
4. Produce `architecture.md`: block diagram, one section per block, per-module concerns table (what it does, key decisions, dependencies, build phase).
5. Present for review — this document is the input to `/init-project`, not a spec.

## Boundaries

Exploration decides WHAT blocks exist and how they relate. It never pins HOW a block is implemented — that belongs to per-phase build planning against real code.
