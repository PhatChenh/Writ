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
---

<!-- RULE START: PROC-BRANCH-001 -->
## Rule PROC-BRANCH-001

**Domain**: process
**Severity**: Low
**Scope**: Component
**Mandatory**: false

### Trigger
When creating a feature branch.

### Statement
Feature branches are named with a ticket/issue reference: `bug/ORD-1234-negative-quantity`, `feat/ORD-1500-tenant-scoping`. Ad-hoc branch names without a tracking reference are violations.

### Violation
```
branch: lucio-fix-2
```

### Pass
```
branch: fix/ORD-1421-tenant-scoping
```

### Enforcement
Repository branch-naming convention. PR template checks.

### Rationale
Traceable branch names link code to issue tracker to release notes. Untraceable names break the audit trail.

<!-- RULE END: PROC-BRANCH-001 -->
---

<!-- RULE START: PROC-CHANGELOG-001 -->
## Rule PROC-CHANGELOG-001

**Domain**: process
**Severity**: Medium
**Scope**: Component
**Mandatory**: false

### Trigger
When releasing user-facing changes.

### Statement
User-facing changes are documented in a changelog or release-notes file. The audience is end users / API consumers / customers, not engineers. Behavior changes, new features, breaking changes, deprecations are all logged.

### Violation
```
# CHANGELOG.md last updated 6 months ago; production has shipped 50 features since.
```

### Pass
```
# CHANGELOG.md:
# ## v2.5.0 (2026-05-10)
# - Added: tenant scoping on /api/orders.
# - Fixed: negative-quantity bypass on order creation.
# - Deprecated: /v1/legacy-orders (sunset 2026-09-01).
```

### Enforcement
Release-process tooling (changesets, conventional-changelog, knope) generates from commits.

### Rationale
Changelogs are the contract with consumers: they can plan integrations from a written record, not from reverse-engineering deploys.

<!-- RULE END: PROC-CHANGELOG-001 -->
---

<!-- RULE START: PROC-COMMIT-001 -->
## Rule PROC-COMMIT-001

**Domain**: process
**Severity**: Medium
**Scope**: Component
**Mandatory**: false

### Trigger
When writing commit messages.

### Statement
Commit messages follow a conventional format: a short subject line (`type: subject` or just a clear summary), and a body for non-trivial changes describing the why. Single-line drive-by messages on substantive changes are violations.

### Violation
```
fix stuff
```

### Pass
```
fix: reject negative quantities in /api/orders

Negative quantities bypassed the existing balance check and produced
double-credit refunds. Adds SEC-VAL-RANGE-001 guard plus regression test.
```

### Enforcement
Code review.

### Rationale
Commit messages are read by every future engineer and during every incident. The 30 seconds spent writing a clear message saves hours later.

<!-- RULE END: PROC-COMMIT-001 -->
---

<!-- RULE START: PROC-DEPLOY-001 -->
## Rule PROC-DEPLOY-001

**Domain**: process
**Severity**: High
**Scope**: Component
**Mandatory**: false

### Trigger
When deploying code to production.

### Statement
Production deploys go through a CI/CD pipeline. Manual deploys (scp, ssh, kubectl apply) are forbidden for production. The pipeline runs tests, builds artifacts, applies migrations, and rolls out via the deployment strategy.

### Violation
```
# Engineer SSHes into prod and runs `git pull && systemctl restart`.
# No record, no rollback path, no test gate.
```

### Pass
```
# `git push origin main` triggers CI; CI runs tests, builds image, applies
# migrations, deploys to staging, promotes to prod after smoke tests pass.
```

### Enforcement
CI/CD platform (GitHub Actions, GitLab CI, ArgoCD, Spinnaker).

### Rationale
Pipelined deploys are reproducible, gated, and auditable. Manual deploys produce drift, skip checks, and have no rollback.

<!-- RULE END: PROC-DEPLOY-001 -->
---

<!-- RULE START: PROC-ENV-001 -->
## Rule PROC-ENV-001

**Domain**: process
**Severity**: Medium
**Scope**: Component
**Mandatory**: false

### Trigger
When handling production credentials.

### Statement
Production credentials are never shared in code, chat (Slack, Teams, email), tickets, or other text artifacts. They live exclusively in the secret management service. Sharing a credential is a security incident; the credential is rotated.

### Violation
```
Slack DM: 'here is the prod DB password: hunter2'
```

### Pass
```
Slack DM: 'request access via 1Password vault: production-database'
```

### Enforcement
Slack DLP scanning. Security training. Incident response on credential exposure.

### Rationale
Once a credential is in a chat scroll, it lives forever in every chat client, every backup, and every export. Secret managers eliminate the durable exposure.

<!-- RULE END: PROC-ENV-001 -->
---

<!-- RULE START: PROC-INCIDENT-001 -->
## Rule PROC-INCIDENT-001

**Domain**: process
**Severity**: Medium
**Scope**: Component
**Mandatory**: false

### Trigger
When an incident occurs in production.

### Statement
Post-incident review produces action items with owners and deadlines. Action items are tracked to completion; the incident is not closed until they are. Blameless: the review focuses on systemic causes, not individual error.

### Violation
```
# Incident retro: 'we'll do better next time'; no tracked actions; same incident next month.
```

### Pass
```
# Postmortem doc: timeline, root cause, action items.
# Action: 'Add retry budget to upstream call (@alice, due 2026-05-24)'.
# Tracked in ticket system; reviewed weekly.
```

### Enforcement
Postmortem template + tracking. Incident-management platform (PagerDuty, Incident.io, FireHydrant).

### Rationale
Untracked retro actions guarantee the incident repeats. Tracked actions are the difference between learning and re-learning.

<!-- RULE END: PROC-INCIDENT-001 -->
---

<!-- RULE START: PROC-INTEG-001 -->
## Rule PROC-INTEG-001

**Domain**: process
**Severity**: High
**Scope**: Component
**Mandatory**: false

### Trigger
When about to write or modify code that integrates a third-party library, SDK, platform, or external service — specifically when choosing an API call, endpoint, config flag, version, or syntax for that integration.

### Statement
Before writing the integration, verify the ACTUAL current API shape (endpoints, parameters, version, config flags, syntax) against an authoritative source — official docs, the installed package's own type definitions, or a written research note — NOT from model memory. If no verified note exists, create one (pin the version, record the shape + pitfalls + source) before coding. Integration decisions with cascading downstream effect must rest on checked facts. Precedence on conflict: a task-local verified research note > a durable project research doc > model memory.

### Violation
```
# Instantiating an ORM client with no driver adapter from a prior-major-version
# memory, or importing a renamed/deprecated SDK symbol — emitted from training
# memory without checking — then discovering at boot/build that the API moved.
```

### Pass
```
# Open the verified note (or the package's own type defs) -> confirm the current
# signature -> code against it. No note for a new lib -> check official docs + the
# INSTALLED version, write a short note (version + shape + pitfalls + source), THEN code.
```

### Enforcement
advisory-only

### Rationale
Model training lags reality by months; fast-moving libraries (ORMs, AI SDKs, framework majors, cloud clients) ship breaking changes after the cutoff. Coding an integration from memory emits stale or legacy patterns that fail at boot or build — costly when the decision has cascading downstream effect. Verifying against live docs / installed types and recording the fact makes every later integration rest on checked information, not a confident guess.

<!-- RULE END: PROC-INTEG-001 -->
---

<!-- RULE START: PROC-PLAN-001 -->
## Rule PROC-PLAN-001

**Domain**: process
**Severity**: High
**Scope**: Component
**Mandatory**: false

### Trigger
When starting any task that involves modifying code.

### Statement
Work mode requires a written plan before any production code is written. The plan covers files to be touched, an analysis of constraints, the rules that apply, and the capabilities to be tested. ENF-PROC-PLAN-001 and ENF-PROC-BRAIN-001 mechanically enforce this for the Writ workflow; the policy itself is universal.

### Violation
```
# Developer starts editing main.py directly; no plan written. Code lands
# scope-creeping into adjacent concerns; reviewer cannot tell what the
# author intended versus what they touched incidentally.
```

### Pass
```
# plan.md written first. Files: orders/service.py, orders/repo.py.
# Analysis: existing patterns for tenant scoping; constraint: no schema
# change. Rules applied: SEC-AUTHZ-TENANT-001, ARCH-LAYER-001.
# Capabilities: list orders for current tenant; reject cross-tenant access.
```

### Enforcement
ENF-PROC-PLAN-001 (format check) + ENF-PROC-BRAIN-001 (design before code) gates. Code review.

### Rationale
A written plan exposes scope creep before code lands. The plan is also the artifact a reviewer reads first to know what to evaluate against.

<!-- RULE END: PROC-PLAN-001 -->
---

<!-- RULE START: PROC-PLAN-002 -->
## Rule PROC-PLAN-002

**Domain**: process
**Severity**: Medium
**Scope**: Component
**Mandatory**: false

### Trigger
When writing or revising an implementation plan document (e.g. the artifact produced by plan-from-specs / build-pipeline, or any equivalent plan) for a medium or heavy change.

### Statement
A plan's implementation sub-units are named **Steps** (`## Steps`, `### Step N`), never "Phases" — "Phase" is reserved for roadmap phases (P0/P1/…); the concrete-action list inside a Step is `**Actions**:`. Beyond the gate sections (Files / Rules Applied / Capabilities), a medium/heavy plan also carries three sections, each derived from facts not inference: (1) **Implementation Order** — a step dependency graph + parallel waves, built from the real call graph (codegraph `codegraph_callers`/`codegraph_explore` where the repo is indexed, else the equivalent dependency trace) on each step's touched symbols, not guessed; (2) **Delegation Authority** — the exact file set the implementer may touch (= the Files list) + the off-limits coupling, with a rule that any out-of-scope touch stops and is reported with reasoning; (3) **E2E Done Criteria** — a real end-user/QC walkthrough on the LIVE stack with observed signals (logs/DB/UI) mapped to the capability IDs, not a restatement of unit tests. (E2E is optional for a tiny 1–2-file plan with no observable end-user effect.)

### Violation
```
# Plan headed "## Phases / ### Phase 1"; dependency order implied prose only;
# no statement of which files the implementer may touch; "Done when: unit tests
# pass." Implementer parallelizes wrong, edits a frozen contract, and calls it
# done without ever running the feature like a user.
```

### Pass
```
# "## Steps / ### Step N" with "**Actions**:" lists. ## Implementation Order
# has a dependency table (each edge cites a codegraph caller fact) + parallel
# waves over disjoint files. ## Delegation Authority lists the allowed file set
# + hard off-limits. ## E2E Done Criteria is a live walkthrough: log in, type a
# prompt, observe the worker log + DB row + rendered UI.
```

### Enforcement
advisory (surfaces at plan-write; plan-from-specs + build-pipeline templates carry it). Not a hard plan-gate section — tier-dependent.

### Rationale
The gate sections prove a plan *exists*; they do not prove it is *executable in parallel without collision*, *bounded in what it may touch*, or *verified the way a user would verify it*. Implementation order built from real call-graph edges (codegraph) prevents wrong parallelization and forward-dependency stalls; an explicit file-touch boundary makes scope creep and frozen-contract edits visible instead of silent; a live E2E walkthrough catches the class of bug where every unit test is green but the assembled feature does not actually work for a user. "Phases" in a plan collides with roadmap-phase terminology and misleads readers.

<!-- RULE END: PROC-PLAN-002 -->
---

<!-- RULE START: PROC-REVIEW-001 -->
## Rule PROC-REVIEW-001

**Domain**: process
**Severity**: Medium
**Scope**: Component
**Mandatory**: false

### Trigger
When merging a change to a shared branch.

### Statement
Code is reviewed by at least one other person or a reviewer agent before merge. Auto-merge on green CI is permitted only for trivial mechanical changes (dependency updates, formatter pushes) and is configured per-repo.

### Violation
```
# Author merges their own PR moments after opening.
```

### Pass
```
# PR requires a reviewer approval; reviewer reads the diff and the plan;
# explicitly approves or requests changes.
```

### Enforcement
Repository branch protection rule.

### Rationale
A second pair of eyes catches scope errors, missing tests, and security oversights that the author normalized to. The check is cheap relative to the cost of fixing in production.

<!-- RULE END: PROC-REVIEW-001 -->
---

<!-- RULE START: PROC-ROLLBACK-001 -->
## Rule PROC-ROLLBACK-001

**Domain**: process
**Severity**: High
**Scope**: Component
**Mandatory**: false

### Trigger
When designing the deployment system.

### Statement
Deployment strategy supports rollback within minutes: blue-green, canary, feature flag, or `helm rollback` / `kubectl rollout undo`. A deploy that cannot be reverted produces extended outages on every bad change.

### Violation
```
# Deployment overwrites the previous image; rollback requires rebuilding
# the prior commit, taking minutes-to-hours.
```

### Pass
```
# Blue-green: both versions running; LB switches; rollback is an LB flip.
# Or: image versions in registry; rollback redeploys the prior tag.
```

### Enforcement
Deployment-platform config review.

### Rationale
Rollback is the most important property of the deployment system. Without it, every deploy is a one-way bet.

<!-- RULE END: PROC-ROLLBACK-001 -->
---

<!-- RULE START: PROC-TEST-001 -->
## Rule PROC-TEST-001

**Domain**: process
**Severity**: High
**Scope**: Component
**Mandatory**: false

### Trigger
When implementing production code that is not a one-shot script.

### Statement
Test skeletons are written and approved before the implementation. Tests carry the contract; the implementation conforms to them. ENF-PROC-TDD-001 mechanically enforces this in the Writ workflow.

### Violation
```
# Implementation lands first; tests added afterwards to match what was
# built. Tests validate the implementation, not the intent.
```

### Pass
```
# tests/test_orders_cancellation.py written first with failing tests.
# Implementation iterates until tests pass. Tests document intent.
```

### Enforcement
ENF-PROC-TDD-001 (failing test before src/ write) gate. Code review.

### Rationale
Test-first ensures tests describe the contract independent of the implementation. Test-after risks tests that codify whatever the implementation happens to do.

<!-- RULE END: PROC-TEST-001 -->
