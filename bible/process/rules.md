<!-- RULE START: ENF-PROC-BRAIN-001 -->
## Rule ENF-PROC-BRAIN-001

**Domain**: process
**Severity**: Critical
**Scope**: Session
**Mandatory**: true
**Mechanical_Enforcement_Path**: .claude/hooks/validate-exit-plan.sh + writ-session.py phase state machine

### Trigger
In Work mode: when the agent attempts any code-producing tool call (Write, Edit, Bash with destructive verbs) before a design has been approved for the current task.

### Statement
In Work mode, no code-producing action is permitted before a design artifact exists and has been approved by the user. Applies to every project regardless of perceived simplicity.

### Violation
Agent in Work mode receives 'refactor this function to use async.' Without presenting approaches or waiting for approval, emits Write(src/api.py, ...). Gate denies the write; friction log records the attempt.

### Pass
Agent in Work mode receives 'refactor this function to use async.' Presents 3 approaches with trade-offs, asks clarifying questions, waits for user to say 'approved — go with option A,' then emits Write. Gate permits the write because session.design_approved = true.

### Enforcement
.claude/hooks/validate-exit-plan.sh + writ-session.py phase state machine check session.mode == 'work' AND session.design_approved == true before any code-producing tool call.

### Rationale
The canonical failure mode of agentic coding is premature implementation on tasks the agent considered simple. This rule makes 'too simple' impossible as a rationalization — the gate fires regardless of task size.

<!-- RULE END: ENF-PROC-BRAIN-001 -->
---

<!-- RULE START: ENF-PROC-DEBUG-001 -->
## Rule ENF-PROC-DEBUG-001

**Domain**: process
**Severity**: High
**Scope**: Task
**Mandatory**: false

### Trigger
When the agent is actively debugging (session.mode == 'debug') and proposes a fix without documented root-cause evidence.

### Statement
Advisory rule: fixes during debug mode should cite root-cause evidence in the same response. No mechanical enforcement path — advisory because lexical detection of 'evidence' is unreliable.

### Violation
Agent in debug mode says 'let me try changing X' without having explained why X is the cause. Advisory warning surfaced to agent in response bundle.

### Pass
Agent in debug mode says 'The failure appears at line 42 when request.body is empty. Fix: validate body before accessing. Evidence: traceback shows KeyError at line 42.' Advisory passes.

### Enforcement
Advisory only — surfaced as part of debug-mode always-on bundle. No deny condition. Friction-logged when agent claims success on fix without evidence.

### Rationale
Symptom-patching is the canonical debug-mode failure. Forcing evidence-cite discipline reduces it, but no reliable lexical detector exists for 'is this evidence?' so the rule stays advisory.

<!-- RULE END: ENF-PROC-DEBUG-001 -->
---

<!-- RULE START: ENF-PROC-PLAN-001 -->
## Rule ENF-PROC-PLAN-001

**Domain**: process
**Severity**: High
**Scope**: Task
**Mandatory**: true
**Mechanical_Enforcement_Path**: .claude/hooks/validate-exit-plan.sh (Tier 1) + writ-quality-judge.sh (Tier 2)

### Trigger
When a plan.md artifact is written and contains placeholder content (TBD, TODO, 'similar to N') or fails structural quality gate.

### Statement
plan.md artifacts must contain no placeholder content, exact file paths, and complete code blocks. Gate 5 Tier 1 (structural) denies writes with placeholder text in any plan section.

### Violation
plan.md contains 'Step 5: implement appropriate error handling, similar to Step 3.' Gate 5 Tier 1 matches 'appropriate' and 'similar to' in the blocklist, denies the write, logs to friction log.

### Pass
plan.md Step 5: 'In src/api.py line 42, wrap the fetch() call in try/except OrderNotFoundError, log the error with order_id context, re-raise.' Concrete path, concrete change, concrete reasoning. Gate passes.

### Enforcement
Gate 5 Tier 1 via validate-exit-plan.sh: lexical match against placeholder blocklist (TBD, TODO, fill in, appropriate, similar to, as needed, placeholder). Gate 5 Tier 2 via Haiku judge rubric on PostToolUse for semantic-level boilerplate.

### Rationale
Placeholder plans transfer design decisions to the implementer as interpretation. They are the canonical failure mode of AI-generated planning.

<!-- RULE END: ENF-PROC-PLAN-001 -->
---

<!-- RULE START: ENF-PROC-SDD-001 -->
## Rule ENF-PROC-SDD-001

**Domain**: process
**Severity**: High
**Scope**: Task
**Mandatory**: true
**Mechanical_Enforcement_Path**: .claude/hooks/writ-sdd-review-order.sh

### Trigger
When subagent-driven development is active and reviewers are dispatched out of order (code-quality before spec-compliance, or either review skipped).

### Statement
Spec-compliance review must complete before code-quality review starts. Out-of-order dispatch denied by gate.

### Violation
Agent dispatches ROL-CODE-REVIEWER-001 before ROL-SPEC-REVIEWER-001 has returned findings. Gate denies the Task dispatch.

### Pass
Agent dispatches ROL-SPEC-REVIEWER-001, waits for findings, resolves any, then dispatches ROL-CODE-REVIEWER-001. Gate permits.

### Enforcement
writ-sdd-review-order.sh on PreToolUse Task: checks session.review_ordering_state for the current task. Denies if code-reviewer dispatched before spec-reviewer has completed.

### Rationale
Spec-first catches wrong-thing-built. Polishing wrong code is wasted work.

<!-- RULE END: ENF-PROC-SDD-001 -->
---

<!-- RULE START: ENF-PROC-TDD-001 -->
## Rule ENF-PROC-TDD-001

**Domain**: process
**Severity**: Critical
**Scope**: Task
**Mandatory**: true
**Mechanical_Enforcement_Path**: .claude/hooks/validate-test-file.sh

### Trigger
In Work mode: when a Write or Edit to a production source file is attempted without a corresponding test file containing assertions.

### Statement
Production code requires a failing test before implementation. Gate denies Write/Edit to src/** paths without corresponding tests/** file containing lexical test markers.

### Violation
Agent in Work mode attempts Write(src/api.py, 'def fetch(url): ...') without tests/test_api.py existing or containing assertions. Gate denies. Friction log records 'gate_denied: ENF-PROC-TDD-001'.

### Pass
Agent writes tests/test_api.py with test_fetch_returns_json (containing assert statement), runs pytest (fails as expected — function doesn't exist), then Write(src/api.py, 'def fetch(url): ...'). Gate permits because test exists.

### Enforcement
validate-test-file.sh: on PreToolUse Write matching src/**/*.{py,js,ts,php}, find corresponding test file, check for lexical assertion markers (assert|expect|should|test_). Deny if missing.

### Rationale
Test-first discipline is what the skill teaches. Mechanical enforcement makes the discipline impossible to rationalize around.

<!-- RULE END: ENF-PROC-TDD-001 -->
---

<!-- RULE START: ENF-PROC-VERIFY-001 -->
## Rule ENF-PROC-VERIFY-001

**Domain**: process
**Severity**: Critical
**Scope**: Session
**Mandatory**: true
**Mechanical_Enforcement_Path**: .claude/hooks/writ-verify-before-claim.sh

### Trigger
When the agent attempts to mark a TodoWrite item complete, or when the session's Stop hook fires and completion claims exist without verification evidence.

### Statement
Completion claims require fresh verification evidence in the same message. TodoWrite completion denied without verification_evidence set in session state.

### Violation
Agent marks todo 'implement fetch()' as completed in TodoWrite without running pytest in the current message. Gate denies. Friction log records 'gate_denied: ENF-PROC-VERIFY-001'.

### Pass
Agent runs pytest tests/test_api.py, output shows '1 passed', quotes the output, then TodoWrite marks todo completed with verification_evidence='pytest tests/test_api.py: 1 passed'.

### Enforcement
writ-verify-before-claim.sh on PreToolUse TodoWrite + Stop: checks session.verification_evidence for the claimed item. Deny if missing or stale.

### Rationale
Completion claims without evidence erode user trust. Mechanical enforcement prevents the confidence-as-evidence failure mode.

<!-- RULE END: ENF-PROC-VERIFY-001 -->
---

<!-- RULE START: ENF-PROC-WORKTREE-001 -->
## Rule ENF-PROC-WORKTREE-001

**Domain**: process
**Severity**: High
**Scope**: Task
**Mandatory**: true
**Mechanical_Enforcement_Path**: .claude/hooks/writ-worktree-safety.sh

### Trigger
When the agent runs git worktree add <path> where <path> is inside the repo tree and is not listed in .gitignore.

### Statement
Project-local worktree directories must be gitignored. Bash gate denies 'git worktree add' commands targeting non-ignored repo-local paths.

### Violation
Agent runs 'git worktree add ./work_trees/feature-x' without adding './work_trees/' to .gitignore. Gate denies the Bash call.

### Pass
Agent confirms .gitignore contains '.worktrees/' or equivalent, then runs 'git worktree add .worktrees/feature-x'. Gate permits.

### Enforcement
writ-worktree-safety.sh on PreToolUse Bash matching 'git worktree add': parse target path, check .gitignore, deny if project-local and not ignored.

### Rationale
Non-ignored project-local worktrees pollute the main branch's working tree and cause accidental commits. The safety check is absolute, not advisory.

<!-- RULE END: ENF-PROC-WORKTREE-001 -->
