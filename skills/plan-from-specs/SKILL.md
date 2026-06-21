---
name: plan-from-specs
version: 1.0.0
description: Use when generating a phased implementation plan from a detailed spec + research doc. Triggers on "write the plan", "plan this feature", "make a plan for", "/plan", after running /research. Requires both a detailed spec and research doc to exist. Never writes code.
---

> **Coupling note (Writ):** the plan's gate-bearing sections (`## Files`, `## Analysis`, `## Rules Applied`, `## Capabilities`) are enforced by `_validate_phase_a` (`bin/lib/writ-session.py`; run on `/writ-approve` advance + the `validate-exit-plan` hook). Change the plan template here and you MUST update `_validate_phase_a` — they must agree or the work gate blocks.

# Plan From Specs

> The global HITL behavioral contract in CLAUDE.md applies in full.
> The specific rules below govern the planning workflow only.

Your ONLY job in this session is to produce a written plan. Do NOT write or modify any code.

Write comprehensive implementation plans assuming the engineer has zero context for the codebase and questionable taste. Document everything they need to know: which files to touch for each task, how to test it, relevant code to reference. Give them the whole plan as bite-sized tasks. DRY. YAGNI. TDD. Frequent commits.

Assume they are a skilled developer, but know almost nothing about the toolset or problem domain. Assume they don't know good test design very well.

**Voice rule:** Non-coder readable is the default. Lead every section with plain-English purpose before technical detail. Code references in parentheses or sub-bullets. If caller passes `engineer-mode`, strip the plain-English leads — but plan must still be logically followable without code knowledge.

## Code exploration — CodeGraph first (mandatory when the repo is indexed)

When the repo has a `.codegraph/` directory, CodeGraph is the PRIMARY tool for locating and reading code — not Read, Grep, Glob, or bash. Mandatory whether this skill runs interactively or as a dispatched subagent. (When a `repomix-output.xml` is the only available source, grep it as below; prefer CodeGraph whenever the `.codegraph/` index exists.)

- **Start every code question with `codegraph_explore "<symbols or question>"`** — one call returns the verbatim source plus the call graph. Use `codegraph_node` for one symbol's full body, `codegraph_callers` for blast radius. If the tools are deferred, load them first via ToolSearch: `select:mcp__codegraph__codegraph_explore,mcp__codegraph__codegraph_node,mcp__codegraph__codegraph_callers`.
- **Use grep / bash / Read ONLY to view raw code AFTER CodeGraph has located it**, for non-code files (shell, yaml, config, markdown), or when there is no `.codegraph/` index.
- **Anti-pattern:** opening with `grep -r` / `find` / Read for a code-symbol lookup — it repeats work CodeGraph already pre-computed and costs far more tokens.

## Non-interactive mode

When the dispatch prompt contains `NON-INTERACTIVE: true`, this skill is running as a subagent with no human in the loop. In this mode:

- **All `AskUserQuestion` gates become auto-select:** choose the recommended option (A) and proceed. Do not call `AskUserQuestion`.
- **Architecture step (Step 3) auto-proceeds:** write the architecture section AND proceed directly to Step 4. Do not stop after it.
- **File-write gates auto-proceed:** write to the path specified in the dispatch prompt. Do not ask for confirmation.
- **Deferred questions go into the doc's "Open questions" section** instead of blocking.
- **Big-disagreement and tier-escalation gates still fire** — those are correctness gates, not confirmation gates. If triggered, report the issue in the summary instead of calling `AskUserQuestion`.
- **All other rules remain in force.** Non-interactive mode skips interactive gates — it does not skip analysis or file writes.
- **CRITICAL: the architecture section is NOT the end of your task.** After writing it, you MUST proceed to Step 4 and write the COMPLETE plan file. A response that only contains the architecture section is INCOMPLETE.

## Input

Feature to plan: $ARGUMENTS

The feature name is used as the filename slug.

---

## Step 0 — Load context, then verify inputs

Execute in this exact order. Do not skip ahead.

### 0a. Read `CLAUDE.md` ⛔ Hard prerequisite

Locate `CLAUDE.md` in the project root. If not found: **stop**.

> "No CLAUDE.md found. Cannot write a plan that respects project rules without it. Add CLAUDE.md or point me to your conventions file."

### 0b. Discover and read all referenced context files

Scan the CLAUDE.md you just read for any file paths mentioned as "read before changing", "reference docs", "reference", or similar. Common examples: `docs/roadmap.md`, `CONSTRAINTS.md`, `TECH_DEBT.md`, `STATE.md`, `docs/decisions/`. Read every referenced file that exists on disk. Do not hardcode assumptions about which files a project has — let CLAUDE.md tell you.

For each recommended file that is missing, warn:
- No `STATE.md` (or equivalent): ⚠️ "Plan may conflict with prior architecture decisions. Do you have architecture decision records elsewhere?"
- No tech debt file: ⚠️ "Cannot flag debt intersections. Continuing without them."

**Read ALL sources before proceeding to 0c.**

### 0c. Find the detailed spec ⛔ Hard prerequisite (standard mode) | Soft prerequisite (tiny mode)

**Standard mode (medium / heavy tier):**

The spec is the output of `/writing-detailed-specs`. Look in this order:

1. `docs/AI_artifacts/2_specs/$FEATURE.md`
2. Any path for specs mentioned in CLAUDE.md
3. Any `.md` file in `docs/` whose name contains the feature slug

If not found at any location: call `AskUserQuestion`:
- A) Paste the spec content here or provide the file path
- B) I want to write the plan without a spec

**If user chooses B or cannot provide a spec: hard stop.**

> "Cannot write a trustworthy plan without a spec. A plan written without a spec is really just a spec + plan bundled together, with no separation between 'what we decided to build' and 'how to build it.' Run /writing-detailed-specs first."

No strawman, no rough sketch, no workaround. Stop completely.

**Tiny mode (dispatched by orchestrator with `mode: tiny`):**

The orchestrator provides a **mini-spec** — a structured summary from the grill interview containing: restated requirement, scope boundaries, done-when criteria. This replaces the full spec. Accept it as the "spec" input. The mini-spec is passed in the dispatch prompt or written to `docs/AI_artifacts/2_specs/$FEATURE-mini.md`. Do NOT demand a full spec in tiny mode.

### 0d. Find the research doc ⛔ Hard prerequisite (standard mode) | Skipped (tiny mode)

**Standard mode (medium / heavy tier):**

The research doc is the output of `/research`. Look in this order:

1. `docs/AI_artifacts/3_research/$FEATURE.md`
2. Any path for research mentioned in CLAUDE.md
3. Any `.md` file in `docs/AI_artifacts/3_research/` whose name contains the feature slug

If not found: call `AskUserQuestion`:
- A) Provide the research file path or paste findings here
- B) I want to write the plan without research

**If user chooses B or cannot provide research: hard stop.**

> "Cannot write a trustworthy plan without research. Research maps spec assumptions to actual code — without it, the plan will reference files, functions, and patterns that may not exist or may work differently than expected. Run /research $FEATURE first."

No workarounds. Stop completely.

**Check for invalidated assumptions:** Once the research doc is found, read its `## Invalidated Assumptions` section. If it exists and is non-empty: **hard stop.**

> "Research found invalidated assumptions that have not been resolved: [list assumption IDs and labels]. The spec must be updated before planning can begin. Open a new design/spec session to resolve them, then re-run /research to confirm all assumptions are validated."

**Tiny mode:** No research doc required. Plan reads code directly during Step 3 (architecture) and Step 4 (phase writing). The tier escalation trigger in Step 3 is the safety net — if code reveals unexpected complexity, plan escalates to medium instead of producing a bad plan.

---

## Step 1 — Read all inputs with intent

Read each source with a specific question in mind. Do not read passively.

**1. The detailed spec** — Read for: *What is being built? What are the constraints? What is explicitly out of scope? What is the build order?*

**2. The research doc** — Read for: *Which spec assumptions are verified vs unverified? What files and functions will be touched? What risks and edge cases were flagged? What ambiguities remain unresolved from the spec?*

**3. `docs/AI_artifacts/4_plans/$FEATURE.md`** — Check if it exists.
- **Exists**: Read it fully. Look for `# QUESTION:` and `# COMMENT:` annotations left by the human. These are your primary task for this run — address every one of them. Preserve all completed phases.
- **Does not exist**: Writing the plan for the first time.

**4. The current conversation** — Check if the human has pasted a spec or additional context. If yes, it takes priority over the research file for design decisions — it reflects the human's latest intent.

**5. `STATE.md`** — If it exists, read it in full:
- Any "Architecture Decision" relevant to this feature is a hard constraint — the plan must conform to it, not re-litigate it
- Any "Open Question" tagged as blocking this feature must be resolved in the plan's "Open Questions" section or escalated to the human
- Any "Technical Debt" that this feature is responsible for retiring should appear as an explicit phase step

**6. `repomix-output.xml` — only if needed.** If resolving an annotation requires verifying an actual interface or function signature, grep surgically:
```
grep -n "<file path" repomix-output.xml | grep -i <relevant-keyword>
```
Do not read this file in full.

---

## Step 1b — Surface ambiguities before doing any work

After reading all inputs, before any annotation work:

Identify every open question or ambiguity in the spec/research. For each one that has 2 or more reasonable answers, call `AskUserQuestion` with:
- A one-line description of what the decision is
- 2–4 options, each with a one-line tradeoff
- Your recommendation first, labeled "(Recommended)"

**Do not proceed to Step 2 until every blocking ambiguity is resolved by the human.**

If no blocking ambiguities exist, state: "No blocking ambiguities found — proceeding."

---

## Step 1c — Disagreement protocol

During Steps 1 and 1b, you may find that the spec or research made a claim that the current codebase contradicts. You are **allowed — and required** to push back when you have codebase evidence. Research operates at a zoomed-out level and may miss things. The spec may have been written before edge cases were discovered. Planning is where those gaps surface.

**When you find a disagreement:**

Classify it before acting:

**Small disagreement** — ALL of the following must be true:
- The fix is local to code being newly built (does not touch existing public APIs, existing schemas, or existing cross-module contracts)
- The fix does not contradict a decision recorded in STATE.md or any ADR
- You can see the correct answer from existing code alone, with no ambiguity

→ Present the disagreement to the human with your proposed fix. Proceed only after confirmation. Do not silently fix.

**Big disagreement** — ANY of the following is true:
- Touches an existing public API, data schema, or cross-module contract
- Contradicts a decision recorded in STATE.md or any ADR
- You cannot determine the correct answer from existing code alone

→ **Stop immediately.** Do not write the plan. Produce a brief:

```
⛔ Planning blocked — spec/research conflict found

**What the spec/research says:** [description]

**What the codebase shows:** [description — cite the file and line or pattern]

**Why this matters:** [what breaks or becomes inconsistent if ignored]

**What needs investigation before planning can continue:**
[specific questions or files that need to be examined in a new session]

Recommended next step: Open a new session, paste this brief, and resolve the conflict before returning to plan.
```

Do NOT attempt to resolve big disagreements inline or present "options" to pick from. The planning session stops here.

---

## Step 2 — Handle human annotations

If `docs/AI_artifacts/4_plans/$FEATURE.md` already exists, scan it for any lines starting with `# QUESTION:` or `# COMMENT:`.

### 2a. Read all annotations before acting

Read every annotation first. Do not start addressing the first one before reading the last one. Annotations may be related — partial understanding leads to wrong revisions.

### 2b. Clarify anything unclear before revising

If any annotation is ambiguous or you cannot determine the human's intent:

- Do NOT revise the plan yet — not even the items you do understand.
- Call `AskUserQuestion` for each unclear annotation with:
  - The quoted annotation text
  - 2–3 interpretations as options
  - Your best-guess interpretation labeled "(Recommended)"

Then STOP. Do not partially revise.

### 2c. Verify before adopting

For each `# COMMENT:` that suggests a design change:

1. Check it against `CLAUDE.md` and `STATE.md` constraints. Does it conflict with an existing architecture decision?
2. If verifiable against the codebase, grep `repomix-output.xml` to confirm the suggestion is technically sound.
3. If it contradicts a prior architecture decision in `STATE.md`, do not silently adopt it — call `AskUserQuestion` with:

```
⚠️ Conflict: Your comment on Phase 2 suggests [X], but STATE.md
records an architecture decision for [Y] (decided on <date>).
```

Options to present:
- A) Revise the plan to follow [X] — this overrides the prior decision
- B) Keep [Y] — I'll note why in the plan

Then STOP and wait.

### 2d. Push back when warranted

The human's annotations are trusted input, but trust does not mean blind compliance. Push back with technical reasoning when:

- The suggestion would break an existing interface or contract
- It contradicts a STATE.md architecture decision
- It adds scope that violates YAGNI
- It would make a phase untestable or too large to verify independently
- You can see a better approach the human may not have considered

How to push back:
- State the technical concern, not an opinion
- Offer an alternative via `AskUserQuestion`
- Let the human decide

### 2e. Respond without performance

When addressing annotations, never write:
- "Great point!" / "Excellent suggestion!" / "You're absolutely right!"

Instead: restate the requirement in your own words, state what changed and why. If the annotation was correct, just fix it — the revision speaks for itself.

### 2f. Mark resolved

After addressing each annotation, change its prefix:
- `# QUESTION:` → `# RESOLVED:` with your answer on the next line
- `# COMMENT:` → `# RESOLVED:` with a note on what changed

---

## Step 3 — Write the architecture

> Diagrams are temporarily disabled (the draw-diagram skill is being reworked). Write the architecture as plain-English prose — no diagrams, no `/draw-diagram` calls.

### Standard mode (medium / heavy tier — spec and design doc exist)

Write a short **Architecture** section in plain English: what the build adds, how it connects to existing components, and which existing interfaces/patterns it must conform to and why. Reference the design doc and spec for detail — do not restate them.

### Tiny mode (no design doc or spec — plan is standalone)

Write the same Architecture section from your own code reading: what happens inside, how it connects, and why it's built this way. Keep it short — a paragraph, not a treatise. If writing it reveals unexpected complexity, trigger the **tier escalation** (see below).

### Write

Write the architecture to `docs/AI_artifacts/4_plans/$FEATURE.md` immediately — create the file now with just the plan header and `## Architecture` section:

```markdown
# Plan: <Feature>
_Last updated: <date>_
_Status: [ ] pending_

## Analysis

[Plain-English: what the build adds, how it connects to existing components, and why it's built this way. The remaining gate sections (## Files, ## Rules Applied, ## Capabilities, ## Phases, ## Open Questions, ## Out of Scope) are written in Step 4.]
```

Then proceed directly to Step 4 and write the complete plan. Do NOT stop to present the architecture, do NOT call `AskUserQuestion`, do NOT wait for approval — it is already written to the file. The dispatching orchestrator reviews it in the main thread after you return; an interactive human (if any) reviews it there, not here.

### Tier escalation (tiny only)

If during code reading you discover complexity beyond tiny scope — touches 3+ modules, crosses a public API boundary, hits a CONSTRAINTS.md constraint, or you find more than 4 integration points — **hard stop:**

```
Classified as tiny but found [specific complexity]. 
Recommend re-running as medium tier (adds design analysis + spec + research).
Work done so far (mini-spec, code findings) carries forward as input.
```

Do NOT attempt to produce a plan over hidden complexity. The orchestrator re-enters at design-lite.

### Extension point marking

For every component this plan introduces, mark whether it is open or closed to extension:
- `[extensible: registry]` — new variants self-register
- `[extensible: config]` — behavior changes through config/yaml
- `[extensible: protocol]` — implements a Protocol; callers don't depend on the concrete class
- `[closed]` — adding a variant requires modifying this file

Any component marked `[closed]` that the spec implies will need variants must be flagged as a design question before the plan is written.

---

## Step 4 — Write the plan

Fill out `docs/AI_artifacts/4_plans/$FEATURE.md` (already created in Step 3) using this structure:

```
# Plan: <Feature>
_Last updated: <date>_
_Status: [ ] pending | [~] in progress | [x] done_

## Analysis

[From Step 3 — already written. What the build adds, how it connects to existing
components, the contracts/interfaces/patterns it must conform to and why, plus the
overall implementation strategy (why this approach, not another). Plain-English
prose, diagrams disabled. Reference the design doc + spec — do not restate them.]

## Files
[Every file to create or modify — aggregate of the per-phase "Files to modify".]
- `path/to/file.py` — [what changes]

## Rules Applied
[Cite rule IDs from the injected --- WRIT RULES --- block that govern this work
(e.g. ARCH-ORG-001). If none matched, write "No matching rules". Do not invent IDs.]

## Capabilities
[Each testable behavior this plan delivers, as an UNCHECKED checkbox — aggregate of
the per-phase Test criteria. Checked only after implementation (feeds
verify-before-claim). Do not pre-check.]
- [ ] [Specific, verifiable behavior]

## Phases

### Phase 1 — <Short name>
**Goal**: [What this phase delivers, in one sentence]

**Design**:
[Plain-English description of what this phase changes and why — describe the
before/after behavior in words. (Diagrams temporarily disabled.)]

**Steps**:
1. [Concrete step]
2. [Concrete step]
...

**Files to modify**:
- `path/to/file.py` — [what changes]

**Test criteria**:
- [ ] [Specific, runnable verification]
- [ ] [Another check]

**Status**: [ ] pending

---

### Phase 2 — <Short name>
[same structure]

---

## Open Questions
[Any decisions not yet made — things the human needs to decide before implementation]

## Out of Scope
[Things explicitly NOT included in this plan]
```

## Rules for writing phases

- **Reference the spec — do not restate it.** The spec is the source of truth for WHAT to build; the plan owns HOW. For each phase, name the spec component IDs it implements (e.g. "implements spec components 1–3") and let the reader open the spec for the Build description, file inventory, and Done-when criteria. The plan adds ONLY what the spec lacks: the architecture section, TDD RED→GREEN ordering, exact line numbers (from research), commit boundaries, and status. Do NOT copy the spec's Build steps, Files-to-modify, Done-when, or Out-of-scope verbatim — link to them. A plan that is ~35% duplicated spec text is wrong; trim it.
- Each phase must be independently testable before moving on
- No phase should touch more than 3–4 files at once
- Tests come BEFORE the next phase starts — never at the end
- If a phase feels too large, split it
- If a phase introduces a new handler, classifier, or processing step, Phase 1 of that feature must define the Protocol (the socket) as a standalone step — before any concrete class. The interface is the deliverable, not the first working implementation.
- No phase may implement behavior hardcoded to a specific source type, AI provider, or output format without flagging it explicitly as known coupling in the phase's Notes.

---

## Step 5 — Verification

After writing the plan, critically review it:

1. Identify potential problems (missing steps, untestable phases, scope creep, dependency gaps)
2. Check if edge cases from `docs/AI_artifacts/3_research/$FEATURE.md` have been accounted for
3. Check for unintentional violations of cross-phase constraints in `STATE.md`
4. Verify that every file, method, or dependency referenced in the plan actually exists — flag anything critical that is missing before writing
5. Call `/guardrail-check Review` once per output phase, passing that phase's concrete steps as input. For each phase, the checklist flags which constraints are at risk. Any violation → call `AskUserQuestion` with options before finalizing the phase. If a phase's steps surface an undocumented constraint or tech debt, call `/guardrail-check Write` to record it immediately before continuing.

For each real problem that requires a design decision, call `AskUserQuestion` with options. Do not silently resolve.

Only revise the plan after the human responds to any open questions raised in this step.

---

## Step 6 — Confirm

After writing the file, run the mid-session STATE.md write from `update-project-docs`:
- Read `STATE.md` from project root. If it does not exist: skip silently.
- Find or create the section for active/in-progress work.
- Add a pending checklist block for the new feature's phases:
  ```
  **[$FEATURE — Plan written <date>]** _(PENDING implementation)_:
  - [ ] Phase 1 — <name>
  - [ ] Phase 2 — <name>
  ...
  ```
- Update `_Last updated_` date at top of STATE.md.
- Write the file.

Do NOT run the full `/update-project-docs` session-end sweep here — this is a targeted STATE.md write only.

Then output exactly:

```
✅ Plan written → docs/AI_artifacts/4_plans/$FEATURE.md

Phases: <count>
Open questions: <count>

NEXT STEP — Review the plan:
  - Add "# QUESTION: ..." for anything unclear
  - Add "# COMMENT: ..." to redirect the approach
  - When satisfied, run: /tdd-implement $FEATURE
```

Do NOT proceed to implementation. Your job ends here.

---

## Red Flags — You're Doing It Wrong

| Thought | Reality |
|---------|---------|
| "I'll write a rough sketch since they have no spec" | No spec = hard stop. No workarounds. |
| "I'll just fix this small conflict in the research" | Surface it. Even small fixes need user confirmation. |
| "The research is probably right about the return type" | Check the actual codebase. Research can be wrong. |
| "This is a big conflict but I can resolve it with options" | Big = stop + brief. No options menu. Suggest separate session. |
| "I'll write the plan and note the conflict in Open Questions" | No. Unresolved big conflicts block the plan entirely. |
