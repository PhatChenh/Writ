---
antipattern_id: ANT-PROC-GRILL-001
node_type: AntiPattern
domain: process
severity: high
scope: repo
trigger: "When contract-freezing expands beyond the import set: deep-grilling every roadmap phase upfront, or pinning internals no later phase reads."
statement: "Over-grilling: freezing detail that no later phase imports pins unstable, not-yet-code-grounded decisions that per-phase build planning will redo against real code — the pin becomes either dead weight or a false authority."
rationale: "Pinned detail carries the authority of a contract. When the pinned thing was never imported by anyone, that authority is unearned: build-pipeline either wastes effort honoring it or silently contradicts it, and both outcomes are worse than having left it WHAT-level."
tags: [anti-pattern, contracts, over-grilling, premature-pinning, process]
confidence: peer-reviewed
authority: human
last_validated: 2026-07-02
staleness_window: 365
evidence: peer-reviewed
source_attribution: "workflow-adaptation:architecture-grill"
source_commit: null
counter_nodes: [PBK-PROC-GRILL-001]
named_in: "workflow:architecture-grill"
edges:
  - { target: PBK-PROC-GRILL-001, type: COUNTERS }
---

# Anti-pattern: Over-grilling the roadmap

## Counter

One criterion decides freezing: does a later phase import it? Depth, dependency order, and risk are not the criterion. See `PBK-PROC-GRILL-001`.
