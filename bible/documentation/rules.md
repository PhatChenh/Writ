<!-- RULE START: DOC-API-001 -->
## Rule DOC-API-001

**Domain**: documentation
**Severity**: High
**Scope**: Component
**Mandatory**: false

### Trigger
When adding or modifying a public API endpoint.

### Statement
Public API endpoints have request/response documentation that is updated with each change. The documentation source lives alongside the code (OpenAPI generated from Pydantic, GraphQL SDL, framework decorators) and ships with every release.

### Violation
```
# /api/orders was changed last quarter; the README still describes the old shape.
```

### Pass
```
# /api/orders has FastAPI response_model + tags; /docs reflects the change automatically.
```

### Enforcement
CI gate: spec generation runs on every PR; diffs are visible.

### Rationale
Drifting API docs erode trust in the documentation overall. Generated docs solve this by construction.

<!-- RULE END: DOC-API-001 -->
---

<!-- RULE START: DOC-ARCH-001 -->
## Rule DOC-ARCH-001

**Domain**: documentation
**Severity**: Medium
**Scope**: Component
**Mandatory**: false

### Trigger
When making a non-trivial architectural decision (choice of database, framework, design pattern, integration approach).

### Statement
Architecture decisions are recorded in ADRs (Architecture Decision Records) or an equivalent decision log. The ADR documents the context, decision, alternatives considered, and trade-offs.

### Violation
```
# 'We chose Postgres' lives in someone's head; the next team rediscovers the same trade-offs.
```

### Pass
```
# docs/adrs/ADR-0017-database-choice.md captures the context (read-heavy, ACID needs),
# the choice (Postgres over MySQL), the alternatives, and the trade-offs accepted.
```

### Enforcement
Code review. Repository structure includes an ADR directory.

### Rationale
Undocumented decisions cost twice: the original deliberation is lost, and the next change repeats the analysis.

<!-- RULE END: DOC-ARCH-001 -->
---

<!-- RULE START: DOC-CONFIG-001 -->
## Rule DOC-CONFIG-001

**Domain**: documentation
**Severity**: Medium
**Scope**: Component
**Mandatory**: false

### Trigger
When introducing or modifying configuration options.

### Statement
Configuration options are documented with their defaults, valid ranges, and effects. A new env var or settings flag is accompanied by an entry in the config docs (or in `.env.example` with comments).

### Violation
```
# .env.example: API_TIMEOUT=5
# No explanation of units, range, or what changes.
```

### Pass
```
# .env.example:
# API_TIMEOUT=5     # seconds (default 5; range 1-30). Timeout for upstream calls.
```

### Enforcement
Code review.

### Rationale
Undocumented config is dark magic: nobody knows what to tune in an incident, and the wrong value causes silent failure.

<!-- RULE END: DOC-CONFIG-001 -->
---

<!-- RULE START: DOC-INLINE-001 -->
## Rule DOC-INLINE-001

**Domain**: documentation
**Severity**: Medium
**Scope**: Component
**Mandatory**: false

### Trigger
When implementing non-obvious algorithms: graph traversals, ranking formulas, bit manipulation, cryptography, optimization tricks.

### Statement
Complex algorithms have inline comments explaining the approach (the why and the how at a level above the syntax). Comments do not restate the code line by line; they explain the strategy and the constraints.

### Violation
```python
for i in range(n):
    for j in range(i + 1, n):
        if a[i] + a[j] == target:
            return (i, j)
```

### Pass
```python
# Two-pointer: O(n) after sort. Move the pointers inward until the
# sum matches; correctness follows from the sort + monotonicity.
left, right = 0, len(a) - 1
while left < right:
    s = a[left] + a[right]
    if s == target: return (left, right)
    elif s < target: left += 1
    else: right -= 1
```

### Enforcement
Code review.

### Rationale
Algorithmic intent is opaque from syntax alone. A short why-comment saves the next reader the derivation.

<!-- RULE END: DOC-INLINE-001 -->
---

<!-- RULE START: DOC-ONBOARD-001 -->
## Rule DOC-ONBOARD-001

**Domain**: documentation
**Severity**: Low
**Scope**: Component
**Mandatory**: false

### Trigger
When establishing onboarding processes for new developers.

### Statement
Advisory only. New-developer onboarding (local setup, test run, deploy to staging, common-task walkthroughs) is documented. Enforced at the repository-integrity-check level rather than per-file (the docs may live across multiple files).

### Violation
```
# Onboarding is verbal: someone shows you the system over a week.
```

### Pass
```
# docs/onboarding/: getting-started.md, common-tasks.md, deploy.md.
# Updated by the most recent new hire as the artifact of their onboarding.
```

### Enforcement
Repository-level integrity check (writ validate). Onboarding feedback as the trigger to update.

### Rationale
Documented onboarding compounds: each new hire improves it. Tribal onboarding stays expensive every cycle.

<!-- RULE END: DOC-ONBOARD-001 -->
---

<!-- RULE START: DOC-README-001 -->
## Rule DOC-README-001

**Domain**: documentation
**Severity**: Medium
**Scope**: Component
**Mandatory**: false

### Trigger
When opening a repository for the first time as a new developer.

### Statement
The repository README includes setup instructions that work on a clean machine: prerequisites, installation, environment setup, how to run tests, how to start the dev server. A new developer can be productive without tribal knowledge.

### Violation
```
# README contains 'see Confluence' and a list of acronyms.
```

### Pass
```
# README:
# Prerequisites: Python 3.12, Node 20, Docker.
# Setup: pip install -r requirements.txt; cp .env.example .env
# Test: pytest
# Run: python -m app
```

### Enforcement
Code review on the README. Onboarding checklist verifies the README works.

### Rationale
A working README is the cheapest onboarding investment; tribal knowledge is the most expensive.

<!-- RULE END: DOC-README-001 -->
---

<!-- RULE START: DOC-TYPE-001 -->
## Rule DOC-TYPE-001

**Domain**: documentation
**Severity**: High
**Scope**: Component
**Mandatory**: false

### Trigger
When writing public functions, methods, or exported APIs.

### Statement
Public functions have type annotations on every parameter and the return value. TypeScript types, Python type hints, Go function types, Rust signatures are the default. Untyped public APIs are violations.

### Violation
```python
def get_user(id):
    return User.query.get(id)
```

### Pass
```python
def get_user(id: int) -> User | None:
    return User.query.get(id)
```

### Enforcement
Type checker (mypy strict, pyright, tsc strict). CI gate.

### Rationale
Types are the most compact, machine-checked documentation available. They catch bugs at edit time and document the contract for free.

<!-- RULE END: DOC-TYPE-001 -->
---

<!-- RULE START: DOC-TYPE-002 -->
## Rule DOC-TYPE-002

**Domain**: documentation
**Severity**: Medium
**Scope**: Component
**Mandatory**: false

### Trigger
When declaring function or method signatures.

### Statement
Return types are explicit. Implicit `Any`, `unknown`, `interface{}`, or unset return types are violations -- the contract is invisible to callers and the type checker.

### Violation
```typescript
function loadUsers() {
    return fetch('/api/users').then(r => r.json());
}
```

### Pass
```typescript
function loadUsers(): Promise<User[]> {
    return fetch('/api/users').then(r => r.json());
}
```

### Enforcement
Type checker config (mypy `disallow_untyped_defs`, tsc `noImplicitAny`).

### Rationale
Implicit Any defeats the type system. Explicit return types ensure the checker actually validates the contract.

<!-- RULE END: DOC-TYPE-002 -->

<!-- RULE START: DOC-SYNC-001 -->
## Rule DOC-SYNC-001

**Domain**: documentation
**Severity**: Medium
**Scope**: Component
**Mandatory**: false

### Trigger
When a decision is locked or changed mid-work: scope cut or added, a plan resequenced, a frozen contract superseded, a new domain term coined, an open question resolved, or any choice that contradicts or adds to what a written project doc currently states.

### Statement
Immediately run a two-pass doc check: a contradiction pass (which docs now state something FALSE?) and an omission pass (what is now TRUE but ABSENT? — especially a new or changed domain term, which belongs in the glossary). Update the diverged docs now, or — if a fuller sweep is deferred to a checkpoint — record the divergence with a breadcrumb pointing at the deferred work. Do not silently continue with docs that now disagree with the decision.

### Violation
```
# A decision changes the model (e.g. "the screen is now a feed, not a canvas").
# The author keeps coding, leaves a doc asserting the old model (contradiction),
# and never records the newly-coined term (omission). The next reader hits a
# false statement plus a missing term.
```

### Pass
```
# On locking the decision: rewrite every now-false claim AND add the new term to
# the glossary, then resume. Contradiction pass + omission pass, both run.
```

### Enforcement
advisory

### Rationale
The dangerous failure is attention-under-load: mid-work a decision diverges from the docs and the author keeps going, leaving stale claims (contradiction) or missing terms (omission) for the next reader. Omissions slip especially easily because a missing glossary entry is not a false statement, so a find-what-is-wrong pass never surfaces it. An ambient reminder at the divergence moment recovers the doc sync that would otherwise be deferred and forgotten.

<!-- RULE END: DOC-SYNC-001 -->
