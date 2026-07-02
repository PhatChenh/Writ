---
antipattern_id: ANT-PROC-INITDOCS-001
node_type: AntiPattern
domain: process
severity: medium
scope: repo
trigger: "When a design spec or roadmap written before any code exists starts naming exact file paths, function signatures, or library call sequences."
statement: "HOW leakage into foundational docs: pinning implementation detail in the design spec or roadmap before real code exists bakes guesses into documents that later phases treat as authority."
rationale: "Implementation detail is only trustworthy when verified against real code — that is what per-phase build planning does. Detail pinned earlier is unverified, goes stale silently, and later phases inherit it as if it were decided."
tags: [anti-pattern, design-spec, how-leakage, premature-detail, process, roadmap]
confidence: peer-reviewed
authority: human
last_validated: 2026-07-02
staleness_window: 365
evidence: peer-reviewed
source_attribution: "workflow-adaptation:init-project"
source_commit: null
counter_nodes: [PBK-PROC-INITDOCS-001]
named_in: "workflow:init-project"
edges:
  - { target: PBK-PROC-INITDOCS-001, type: COUNTERS }
---

# Anti-pattern: HOW leakage into foundational docs

## Counter

Foundational docs stop at WHAT, WHY, and WHAT ORDER. Implementation detail enters only through the per-phase pipeline, where factual-code-verification checks it against real code. See `PBK-PROC-INITDOCS-001`.
