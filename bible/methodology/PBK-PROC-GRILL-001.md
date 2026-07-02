---
playbook_id: PBK-PROC-GRILL-001
node_type: Playbook
domain: process
severity: high
scope: repo
trigger: "When a roadmap has WHAT-level phases and cross-phase contracts must be locked before per-phase build planning starts."
statement: "Freeze exactly the set of contracts a LATER phase imports — global seams plus cross-phase data shapes — pin each with an explicit frozen-now-vs-deferred split, emit the build-order handoff once, then stop."
rationale: "The freeze-set criterion is imports, not risk or depth. A risky but self-contained phase needs no freezing; an innocuous data shape three phases read absolutely does. Freezing only imports keeps early pinning minimal and prevents a late phase from discovering an early phase under-specified what it needed."
tags: [contracts, freeze-set, grill, playbook, process, seams]
confidence: peer-reviewed
authority: human
last_validated: 2026-07-02
staleness_window: 365
evidence: peer-reviewed
always_on: false
source_attribution: "workflow-adaptation:architecture-grill"
source_commit: null
phase_ids: []
preconditions: [PBK-PROC-INITDOCS-001]
dispatched_roles: []
edges:
  - { target: PBK-PROC-BRAIN-001, type: PRECEDES }
---

# Playbook: Grill the architecture — freeze the import set

## Order of operations

1. Identify the freeze set (breadth, once): walk the roadmap asking one question per block — does a LATER phase import this? Yes → freeze list. No → leave WHAT-level.
2. Pin each freeze-set item (depth): read, internalize silently, ask one question per message, confirm, write to the contracts doc with its frozen-now-vs-deferred/PENDING split.
3. Offer an ADR when a pinned decision is hard to reverse, surprising, and a real trade-off.
4. Emit the build-order handoff once — dependency data already computed, not new grilling — then stop.

## Boundaries

Everything outside the freeze set defers to per-phase build planning. The grill step is the only holder of the whole-roadmap view; the handoff is where that view is recorded.
