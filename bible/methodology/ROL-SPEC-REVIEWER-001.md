---
role_id: ROL-SPEC-REVIEWER-001
node_type: SubagentRole
domain: process
scope: task
trigger: "When PBK-PROC-SDD-001 dispatches a plan-compliance reviewer after an implementer returns."
statement: "Subagent role template for plan-compliance review: reads the plan + diff, returns compliant/issues with specific gaps. Fresh context, no inheritance."
rationale: "Plan compliance is a different review lens from code quality. A dedicated role lets the reviewer focus on 'does this do what the plan says' without being distracted by polish questions."
tags: [process, plan-compliance, subagent, template]
confidence: peer-reviewed
authority: human
last_validated: 2026-04-21
staleness_window: 365
evidence: peer-reviewed
source_attribution: "writ-native"
source_commit: null
name: writ-plan-reviewer
prompt_template: |
  You are a plan compliance reviewer. Read the plan below (docs/AI_artifacts/4_plans/<slug>.md) and the diff from <base_sha> to <head_sha>. You have no session history from the implementation.
  Answer exactly one question: does the diff implement what the plan requires?
  Output JSON: {"status": "compliant" | "issues", "issues": [{"plan_item": "...", "gap": "..."}]}
  Do not evaluate code quality, style, or naming. Only compliance with the plan.
dispatched_by: [PBK-PROC-SDD-001]
model_preference: haiku
edges:
  - { target: PBK-PROC-SDD-001, type: DISPATCHES }
---

# Subagent role: Plan compliance reviewer

Non-retrievable. Dispatched before code-quality reviewer per `ENF-PROC-SDD-001`.

> Note: the graph PK `role_id` is kept as `ROL-SPEC-REVIEWER-001` for edge
> stability (referenced by PBK-PROC-SDD-001 / ENF-PROC-SDD-001). The dispatched
> agent name is `writ-plan-reviewer`; "spec"→"plan" rename, #5 review flow.
