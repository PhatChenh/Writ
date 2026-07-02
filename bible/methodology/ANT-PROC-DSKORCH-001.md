---
antipattern_id: ANT-PROC-DSKORCH-001
node_type: AntiPattern
domain: process
severity: high
scope: task
trigger: "When a delegated implementer receives the whole plan in one handoff, or one session is reused across implement and review roles."
statement: "Whole-plan handoff and role carryover: giving the implementer everything at once produces one giant unreviewable diff, and carrying an implementation session into review makes it grade its own homework."
rationale: "Review quality depends on bounded diffs and independent eyes. Both failure modes destroy exactly that: the unbounded diff can only be skimmed, and the role-carried session inherits the biases that produced the code it now judges."
tags: [anti-pattern, delegation, orchestration, process, role-carryover, unbounded-diff]
confidence: peer-reviewed
authority: human
last_validated: 2026-07-02
staleness_window: 365
evidence: peer-reviewed
source_attribution: "workflow-adaptation:deepseek-orchestrate"
source_commit: null
counter_nodes: [PBK-PROC-DSKORCH-001]
named_in: "workflow:deepseek-orchestrate"
edges:
  - { target: PBK-PROC-DSKORCH-001, type: COUNTERS }
---

# Anti-pattern: Whole-plan handoff to the delegate

## Counter

One wave at a time, reviewed and merged before the next; one session, one role. See `PBK-PROC-DSKORCH-001`.
