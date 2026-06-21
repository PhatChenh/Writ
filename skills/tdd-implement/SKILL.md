---
name: tdd-implement
version: 1.0.0
description: Use when executing implementation phases from a plan file using TDD. Triggers on "implement phase", "build next phase", "implement feature", "tdd implement", or when user wants to start coding against an existing plan.
---

# TDD Implementation

Execute ONE phase at a time from a plan file. Stop after each phase for human verification. All production code written test-first using Red-Green-Refactor.

> The global HITL behavioral contract in CLAUDE.md applies in full.

**REQUIRED BACKGROUND:** Read [tdd-reference.md](tdd-reference.md) before first use. It defines the testing philosophy, mocking rules, and refactoring guidance this skill assumes you know.

## Input

Feature to implement: $ARGUMENTS

---

## Step 0 — Project Discovery

### 0pre. Set Writ mode (silent; no-op outside a Writ repo)

This skill writes production code, so arm Writ Work mode (test-first + gate machine):

```bash
WR="${CLAUDE_PLUGIN_ROOT:-$(cat "${CLAUDE_PLUGIN_DATA:-$HOME/.cache/writ}/plugin-root" 2>/dev/null)}"; [ -x "$WR/bin/writ-mode-set.sh" ] && bash "$WR/bin/writ-mode-set.sh" work 2>/dev/null || true
```

### 0a. Hard requirements — refuse to start if missing

Two files are mandatory. Check both before anything else:

1. **`CLAUDE.md`** — project root, then user-level (`~/.claude/CLAUDE.md`). Contains conventions, coding patterns, build progress, and repo layout.
2. **Plan file for `$ARGUMENTS`** — path discovered in Step 0b below.

If `CLAUDE.md` cannot be found anywhere: call `AskUserQuestion`:
```
❌ CLAUDE.md not found. Cannot start without it.
```
Options:
- A) It's at [path] — point me to it
- B) This project has no CLAUDE.md — I'll paste the key conventions now

If user cannot provide `CLAUDE.md` or equivalent: **refuse to proceed**. Implementation without project conventions produces non-conforming code.

### 0b. Adaptive discovery from CLAUDE.md

Read `CLAUDE.md` in full. Then **scan it for references to other context documents** — any file paths mentioned as "read before changing", "reference docs", "essential docs", or similar. Common examples: `docs/roadmap.md`, `CONSTRAINTS.md`, `TECH_DEBT.md`, `STATE.md`, `docs/decisions/`. Read every referenced file that exists on disk.

Do not hardcode assumptions about which files a project has — let `CLAUDE.md` tell you. If a referenced file is missing, note it but do not block on it unless it is explicitly marked as essential.

From `CLAUDE.md`, also identify:
- Where plans are stored (e.g. `docs/plans/`) → `$PLAN_DIR`
- How to run tests (e.g. `uv run pytest`, `npm test`) → `$TEST_CMD`

If `CLAUDE.md` does not mention either, call `AskUserQuestion`:
```
⚠️ CLAUDE.md does not specify [plans location / test command].
```
Options:
- A) It's at / the command is [X]
- B) Skip — not applicable for this project

### 0c. Locate the plan file

Look for `$PLAN_DIR/$ARGUMENTS.md` (or equivalent slug). If not found, call `AskUserQuestion`:
```
❌ No plan found for "$ARGUMENTS" in $PLAN_DIR.
```
Options:
- A) It's at [path] — point me to it
- B) Create a plan first — run /plan_v5 $ARGUMENTS

**Refuse to start if plan file cannot be located.** Implementation without a plan is out of scope for this skill.

---

## Step 1 — Load and validate the plan

Read in order:

**1. Context docs discovered in Step 0b** — any state file, constraint doc, ADR directory, or roadmap referenced by `CLAUDE.md`. Architecture Decisions are hard constraints. Cross-Phase Constraints must be respected. Note relevant Technical Debt entries.

**2. `$PLAN_DIR/$ARGUMENTS.md`** — Already located in Step 0c. Read in full.

- **Has unresolved `# QUESTION:` annotations** → Stop:
  ```
  ⚠️ Plan has unresolved questions. Resolve them before implementing.
  ```

- **All phases `[x] done`** → Stop:
  ```
  ✅ All phases complete for "$ARGUMENTS". Nothing left to implement.
  ```

**3. Codebase verification** — For any file, method, or dependency referenced in the current phase, verify it exists using `grep -rn` or `find`. Do not trust the plan blindly — it may reference things that were renamed or removed since planning.

---

## Step 2 — Identify the current phase

Find first phase with status `[ ] pending`. That is your target.
Do not skip ahead. Do not implement multiple phases.

---

## Step 2b — Pre-implementation confirmation gate

Before writing any code or test, call `AskUserQuestion`:

```
▶ Ready to implement: Phase <N> — <Phase name>
  Goal: <phase goal>

  Files I will create or modify:
  - <file> — <what changes>

  Tracer bullet test:
  - <the ONE test that proves this phase works end-to-end>

  Remaining behaviors to verify:
  - <behavior 1>
  - <behavior 2>
```

Options:
- A) Proceed with implementation (Recommended)
- B) Adjust scope before starting — describe adjustment
- C) Skip this phase

Do not write code until human selects A.

If test criteria in the plan are ambiguous — where two reasonable implementations would both satisfy them — surface the ambiguity here via additional `AskUserQuestion`. Do not silently pick an interpretation.

---

## Step 3 — Implement with TDD (Red-Green-Refactor)

**Iron law: No production code without a failing test first.**

Wrote code before the test? Delete it. Start over. No exceptions.

### The Anti-Pattern: Horizontal Slicing

**DO NOT write all tests first, then all implementation.** This is the #1 mistake.

```
WRONG (horizontal):
  RED:   test1, test2, test3, test4, test5
  GREEN: impl1, impl2, impl3, impl4, impl5

RIGHT (vertical):
  RED→GREEN: test1→impl1
  RED→GREEN: test2→impl2
  RED→GREEN: test3→impl3
```

Tests written in bulk test _imagined_ behavior. Each test must respond to what you learned implementing the previous one.

### 3a. Tracer Bullet — First Test

Write ONE test that proves the path works end-to-end for this phase's core behavior. This is your tracer bullet — if this passes, the architecture is sound.

Run it. Watch it fail. Confirm it fails because the feature is missing, not because of typos or import errors.

```bash
$TEST_CMD path/to/test_file.py::test_name -x
```

Write minimal code to make it pass. Nothing more.

### 3b. Incremental Loop — Remaining Behaviors

For each remaining behavior in this phase:

**RED** — Write one test. Requirements:
- Tests one behavior only. Name contains "and" → split it.
- Clear name describing expected behavior, not implementation.
- Assertions check specific expected values, not just type/presence/non-None.
- Uses real code paths. Mocks only at system boundaries (see [tdd-reference.md](tdd-reference.md#when-to-mock)).

Run it. Watch it fail. Paste actual test output — do not paraphrase.

If test passes immediately → you're testing existing behavior. Rewrite.
If test errors (import/syntax) → fix error, re-run until it fails for the right reason.

**GREEN** — Write minimal production code to pass.
- Do not add features the test doesn't require.
- Do not anticipate future tests.
- Never hardcode return values to satisfy a test.
- Do not refactor yet.

Run test + full suite for affected files. All must pass.

### 3c. Refactor — After All Green

After all behaviors pass, and only then:
- Remove duplication in production code
- Improve names and structure
- Look for deep module opportunities (small interface, lots of implementation hidden inside — see [tdd-reference.md](tdd-reference.md#deep-modules))
- Run full suite after every refactor change — must stay green
- Do not add new behavior during refactor

**Never refactor while RED.** Get to GREEN first.

### 3d. Per-Cycle Checklist

After each RED→GREEN cycle, verify:
```
[ ] Test describes behavior, not implementation
[ ] Test uses public interface only
[ ] Test would survive internal refactor
[ ] Code is minimal for this test
[ ] No speculative features added
```

For detailed testing rules, mocking guidelines, and red flags, see [tdd-reference.md](tdd-reference.md).

---

## Step 4 — Final verification

Run full test suite:

```bash
$TEST_CMD
```

If a test fails within this phase's scope → fix and re-run.

If a test fails outside scope or reveals a plan flaw → call `AskUserQuestion`:
- Describe failure and why it can't be fixed within scope
- Options: A) revise plan, B) document as known issue and proceed, C) expand phase scope

### Verification checklist

Before marking phase done:

- [ ] Every new function/method has at least one test
- [ ] Watched each test fail before writing its production code
- [ ] Each test failed for the expected reason (feature missing, not typo/import)
- [ ] Wrote minimal code to pass each test — no speculative features
- [ ] All tests pass, output clean
- [ ] Tests use real code — mocks only at system boundaries
- [ ] Edge cases and error paths covered
- [ ] No test-only methods in production classes
- [ ] No surprises resolved unilaterally — all surfaced and approved

**Project-specific checks:** Read CLAUDE.md for additional verification requirements (type checking, linting, coding patterns). Apply them here.

---

## Step 4b — Guardrail Audit (conditional)

**Skip this step if the plan file has NO guardrail/constraint checklist section.**

If the plan contains a guardrail checklist (e.g. `## Guardrail Checklist`, `## Constraints`, or similar):

### 4b-1. Spawn audit subagent

Dispatch a subagent with:
- The guardrail checklist content from the plan
- The list of files modified/created in this phase
- Instruction: invoke `/guardrail-check` in **audit mode** against the modified files, scoped to the constraints listed in the plan's checklist
- Report format: per-constraint `✅ ENFORCED` / `⚠️ PARTIAL` / `❌ UNGUARDED` with `file:line`

### 4b-2. Receive and evaluate report

If all `✅` or `⚠️` only → proceed to Step 5.

If any `❌ UNGUARDED` findings → call `AskUserQuestion`:

```
🛡️ Guardrail audit found <N> unguarded constraint(s):
- C-XX · [rule name] — no mechanical enforcement in [file]
- C-XX · [rule name] — ...
```

Options:
- A) Fix all before marking phase done (Recommended)
- B) Fix critical only, log rest as tech debt
- C) Defer all — log as tech debt for later phase

### 4b-3. Act on decision

- **A or B**: Fix gaps, re-run tests (Step 4), re-run audit subagent. Loop until clean.
- **C**: Append deferred items to plan's `## Surprises` section with `TD:` prefix.

---

## When you encounter something the plan did not anticipate

If you discover something mid-phase the plan didn't account for (missing interface, unexpected dependency, conflicting constraint):

1. **Stop immediately.** Do not implement a workaround.
2. Document in the plan under `## Surprises`:
   ```
   ## Surprises
   - Phase <N>: [what was found, why it wasn't in the plan, what it blocks]
   ```
3. Call `AskUserQuestion`:
   - What you found
   - Options: A) minimal workaround and continue, B) stop and rethink this phase, C) revise the plan
   - Your recommendation labeled "(Recommended)"
4. Wait for human's decision before writing any code for the surprise.

---

## Step 5 — Update the plan file

After all checks pass:

1. Change phase status: `[ ] pending` → `[x] done`
2. Add implementation note:
   ```
   **Completed**: <date>
   **Notes**: [What was actually done — deviations, surprises, tech debt introduced]
   ```
3. Update top-level `_Status_` to `[~] in progress` (or `[x] done` if last phase)

---

## Step 5b — Update project docs

Invoke `/update-project-docs` (session-end sweep). It is the single post-phase doc orchestrator — handles everything:
- **STATE.md** — mark completed phase `[x]`, update current position, last-updated date
- **CLAUDE.md** — "Build Progress" section, any new "What AI Gets Wrong" gotchas
- **roadmap.md** — if phase scope changed (skip otherwise)
- **guardrail-check** — any new constraints, tech debt, or open questions
- **`/update-behavior-guide`** — Reconcile + regenerate behavior inventory and testing guide
- **`/update-arch-story`** — update architecture diagrams if architecture changed

`/update-project-docs` has its own proposal/approval gate — proceed through it normally.

---

## Step 6 — Hard stop

Output:

```
✅ Phase <N> complete — plan updated

What was done:
- [bullet summary]

Files modified:
- [list]

Please verify before continuing:
- [restate test criteria from plan]

When verified, run: /tdd_implement $FEATURE for Phase <N+1>.
```

Then STOP. Do not continue to next phase. Wait for human to run command again.
