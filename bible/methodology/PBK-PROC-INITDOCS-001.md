---
playbook_id: PBK-PROC-INITDOCS-001
node_type: Playbook
domain: process
severity: high
scope: repo
trigger: "When a new project needs its foundational documents: design spec, engineering roadmap, and CLAUDE.md."
statement: "Produce exactly three artifacts — design spec (WHAT and WHY), engineering roadmap (WHAT ORDER), CLAUDE.md (orients AI assistants) — grounded in the architecture map, then cross-check them against each other. None of the three contains HOW."
rationale: "Each artifact answers one question; mixing them produces documents that are wrong twice — a design spec polluted with implementation detail goes stale the moment real code exists, and a roadmap that re-explains WHAT drifts from the spec it duplicates."
tags: [claude-md, design-spec, foundational-docs, playbook, process, roadmap]
confidence: peer-reviewed
authority: human
last_validated: 2026-07-02
staleness_window: 365
evidence: peer-reviewed
always_on: false
source_attribution: "workflow-adaptation:init-project"
source_commit: null
phase_ids: []
preconditions: [PBK-PROC-ARCHX-001]
dispatched_roles: []
edges:
  - { target: PBK-PROC-GRILL-001, type: PRECEDES }
---

# Playbook: Initialize project docs

## Order of operations

1. Require project intent (problem, target user, stack, features) — refuse to write from nothing.
2. Ground in the architecture map from exploration; do not re-architect from memory.
3. Design spec: Overview, Rules & Design Principles, Stack, Project Structure, Features, Out of Scope.
4. Roadmap: Project Context, Feature Inventory, Build Order with `### Phase N` entries; leave the build-order handoff placeholder for the grill step.
5. CLAUDE.md: orient a cold AI — context, commands, patterns, critical rules, build progress.
6. Cross-check: every feature in the spec appears in the roadmap; nothing in either contradicts CLAUDE.md.

## Boundaries

HOW belongs to per-phase build planning against real code. A design spec that names exact functions before code exists is guessing, not designing.
