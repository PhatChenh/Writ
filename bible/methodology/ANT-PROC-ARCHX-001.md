---
antipattern_id: ANT-PROC-ARCHX-001
node_type: AntiPattern
domain: process
severity: high
scope: repo
trigger: "When an architecture map, module list, or design spec is being written without having researched any comparable project."
statement: "Architecting from memory: skipping comparable-project research and drawing the system from general knowledge produces generic architectures with the same gaps every from-scratch design has."
rationale: "The field has already paid for the lessons — module splits that failed, seams that had to exist, scope that had to be cut. A design that never looks at comparables re-buys those lessons during implementation, when they are most expensive."
tags: [anti-pattern, architecture, exploration, process, vacuum-design]
confidence: peer-reviewed
authority: human
last_validated: 2026-07-02
staleness_window: 365
evidence: peer-reviewed
source_attribution: "workflow-adaptation:architecture-exploration"
source_commit: null
counter_nodes: [PBK-PROC-ARCHX-001]
named_in: "workflow:architecture-exploration"
edges:
  - { target: PBK-PROC-ARCHX-001, type: COUNTERS }
---

# Anti-pattern: Architecting from memory

## Counter

Research 2+ comparable projects before drawing anything. Every module in the map either matches a proven pattern or carries an explicit reason for deviating. See `PBK-PROC-ARCHX-001`.
