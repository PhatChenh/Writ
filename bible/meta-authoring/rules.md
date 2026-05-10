<!-- RULE START: META-AUTH-001 -->
## Rule META-AUTH-001

**Domain**: meta-authoring
**Severity**: High
**Scope**: Task
**Mandatory**: false
**Mechanical_Enforcement_Path**: writ/authoring.py: lint on add/edit warns if trigger contains action verbs rather than trigger conditions.

### Trigger
When the agent authors a new Writ Skill, Playbook, or Technique node, and is about to populate the trigger or description field.

### Statement
The trigger field of a node must describe WHEN the node should activate, not WHAT the node does. Description-as-workflow-summary causes Claude to follow descriptions instead of reading skill bodies, fragmenting methodology retrieval at scale.

### Violation
New skill authored with trigger: 'This skill performs systematic debugging by gathering evidence, forming hypotheses, testing them, and implementing fixes in four phases.' Field describes what; agent sees the summary at retrieval and skips the body. Authoring-gate warns on action verbs in trigger text.

### Pass
New skill authored with trigger: 'When a bug is reported, a test fails, an error is observed, or the same fix attempt has failed three times.' Field describes when; agent retrieves the node and reads the body for the how. Authoring-gate passes.

### Enforcement
writ add and writ edit lint the trigger field, warn on action verbs (does, performs, executes) that indicate workflow-summary rather than triggering-condition content.

### Rationale
At scale (>30 skills), agent-side selection of which skill to use becomes the bottleneck. If descriptions summarize workflow, the agent has enough information to act without reading the body — and it acts on the summary, which is incomplete. Triggering-conditions descriptions force the agent to the body, where the actual methodology lives.

<!-- RULE END: META-AUTH-001 -->
---

<!-- RULE START: META-AUTH-002 -->
## Rule META-AUTH-002

**Domain**: meta-authoring
**Severity**: High
**Scope**: Task
**Mandatory**: false
**Mechanical_Enforcement_Path**: writ/authoring.py: warn on add/edit if node lacks linked PressureScenario.

### Trigger
When the agent authors a new Writ Skill, Playbook, or Technique and is about to mark it ready for use without running a pressure test against the rule's target behavior.

### Statement
Skills must pass a pressure test before deployment: apply the baseline scenario, confirm RED (agent violates), write or refine the skill, re-run, confirm GREEN (agent complies). No skill ships without RED-GREEN-REFACTOR applied to itself.

### Violation
Agent authors a new skill SKL-PROC-FOO-001 and commits without running pressure-test. Advisory warning surfaced during writ add; friction-logged.

### Pass
Agent authors draft skill, runs writ test-pressure --scenario PSC-FOO-001, confirms agent violates the rule (RED), refines skill text, re-runs, confirms agent now complies (GREEN). Then commits.

### Enforcement
writ add advisory check: warns if a new SKL-/PBK-/TEC-/ENF- node is added without a linked PressureScenario. Does not block.

### Rationale
Untested skills deploy with unknown effectiveness. The RED-GREEN-REFACTOR discipline that applies to code also applies to methodology content.

<!-- RULE END: META-AUTH-002 -->
