---
name: writing-detailed-specs
version: 1.0.0
description: Use when a design decision has been made and needs to be turned into a buildable spec — after codebase-design-analysis or equivalent brainstorm, when user says "write the spec", "spec this out", "structure this into build steps", or provides a design decision with selected option and implications. Does NOT trigger for "make me a plan" when a spec already exists — those go to /plan. Does NOT trigger for open-ended "what would it take" questions where no option is selected — those go to codebase-design-analysis.
---

> **Coupling note (Writ):** the spec has no mechanical Writ gate today. If you add a required-section gate, wire it like `validate-design-doc` and keep the template + hook in sync.

# Writing Detailed Specs

Turn a design decision (with selected option and implications) into a phase spec that another AI or developer can pick up for research and detailed planning.

**This skill writes SPECS, not plans.** A spec says WHAT to build, in what order, and what's already done. A plan says HOW to build each piece (exact code, tests, commits). Specs feed into `/factual-code-verification` and `/plan` — they don't replace them.

**REQUIRED UPSTREAM:** Uses codebase-design-analysis (or equivalent brainstorm output) as input. Does not run design analysis itself — expects the option to be already selected and implications already explored.

**Voice rule (applies to ALL output):** Non-coder readable is the default. Lead every section with plain-English purpose before any technical detail. Code references go in parentheses or sub-bullets. The reader should understand the spec's intent without reading code. If caller passes `engineer-mode`, strip the plain-English leads and promote code refs inline — but the spec must still be logically followable without code knowledge.

---

## Code exploration — CodeGraph first (mandatory when the repo is indexed)

When the repo has a `.codegraph/` directory, CodeGraph is the PRIMARY tool for locating and reading code — not Read, Grep, Glob, or bash. Mandatory whether this skill runs interactively or as a dispatched subagent.

- **Start every code question with `codegraph_explore "<symbols or question>"`** — one call returns the verbatim source plus the call graph. Use `codegraph_node` for one symbol's full body, `codegraph_callers` for blast radius. If the tools are deferred, load them first via ToolSearch: `select:mcp__codegraph__codegraph_explore,mcp__codegraph__codegraph_node,mcp__codegraph__codegraph_callers`.
- **Use grep / bash / Read ONLY to view raw code AFTER CodeGraph has located it**, for non-code files (shell, yaml, config, markdown), or when there is no `.codegraph/` index.
- **Anti-pattern:** opening with `grep -r` / `find` / Read for a code-symbol lookup — it repeats work CodeGraph already pre-computed and costs far more tokens.

---

## Protocol

### Step 0 — Load context, then verify input

Execute in this exact order. Do not check for design docs before completing the reads.

**0a. Read `CLAUDE.md`** ⛔ Hard prerequisite

Locate `CLAUDE.md` in the project root. If not found: stop. "No CLAUDE.md found. Cannot write a spec that respects project rules without it. Add CLAUDE.md or point me to your conventions file."

**0b. Discover and read all referenced context files**

Scan the `CLAUDE.md` you just read for any file paths mentioned as "read before changing", "reference docs", "reference", or similar. Common examples: `docs/roadmap.md`, `CONSTRAINTS.md`, `TECH_DEBT.md`, `STATE.md`, `docs/decisions/`. Read every referenced file that exists on disk. Do not hardcode assumptions about which files a project has — let `CLAUDE.md` tell you.

For each recommended file that is missing, warn:
- No `STATE.md` (or equivalent): ⚠️ "Spec may conflict with prior architecture decisions. Do you have architecture decision records elsewhere?"
- No tech debt file: ⚠️ "Cannot flag debt intersections. Continuing without them."

**Guardrail checklist from design doc:** Locate the `## Guardrail Checklist` section in the design doc (written by `/codebase-design-analysis`). If found, read it — every component you define must not introduce a violation flagged there. Treat flagged constraints as hard stops, not warnings.

**Read ALL sources before proceeding.** Do not start the spec before this step is complete.

**0c. Check for design docs and implications**

After reading all context files: look for a design document — output from `codebase-design-analysis`, a brainstorm artifact, or equivalent — that identifies WHAT to build and WHICH approach was chosen.

| Required | What it is | If missing |
|----------|-----------|------------|
| Design docs | What we're building + which approach was chosen | ⛔ Stop. "No design docs found after reading all context files. Run codebase-design-analysis first, or paste the design decision here." |
| Implications | What the chosen option means — guards, files touched, downstream effects, runtime deps | ⛔ Stop. "Design docs found but no implications. Run codebase-design-analysis to explore implications, or list them yourself." |
| Relevant source files | The code this spec will modify or extend | ⛔ Stop. Ask which files are in scope. |

**If user pushes back ("just wing it"):** Proceed with a degraded spec, but mark every build step that lacks implication backing with `[UNGROUNDED — no implication analysis]`. Warn at the top: "This spec was written without full design analysis. Build steps marked [UNGROUNDED] may miss constraints or edge cases. Run codebase-design-analysis to fill gaps."

---

### Step 1 — Inventory what exists

Scan the codebase for everything relevant to this spec. Build two lists:

**Already built (reuse):** Functions, classes, modules, config files (YAML, thresholds, prompts), and patterns that this spec should use, not rebuild. For each item:
- Name + location (`module.function` or `file:line`)
- One-line plain-English description of what it does
- Why it's relevant to this spec
- Depth: `deep` / `shallow` / `unknown` — is interface smaller than implementation? Shallow modules flagged: planner should consider restructuring before depending on them.

**Partially built (extend):** Code that exists but needs modification. For each:
- What exists now
- What needs to change
- Why

**Not built (create):** Things this spec introduces that don't exist yet.

This inventory prevents the downstream planner from rebuilding what exists or missing extension points.

---

### Step 2 — Determine phase boundaries

A spec covers ONE phase. If the design decision spans multiple phases, write one spec per phase.

To determine phase boundaries, ask:
1. What is the smallest deliverable that provides value on its own?
2. What can be tested independently?
3. What do later phases depend on from this phase?

If the design input already specifies a phase number, use it. If not, ask the user:
> "This design spans multiple concerns. Should I spec it as one phase or split it? Here's what I'd suggest: [split rationale]"

---

### Step 3 — Write the spec

Use this exact output structure. Every section is required unless marked optional.

**Deriving assumptions:** Scan the design-analysis implications list. Every implication that makes a claim about existing code (an interface, a file location, a behavior, a module contract) becomes an assumption entry. Label each with its source implication number so research can trace it back. Write each assumption as a falsifiable claim — state what would prove it wrong. Vague beliefs ("the system is stable") are not assumptions; they're noise.

```markdown
# Phase <n> — <what we build>

## Purpose
[2-3 sentences. What does this phase deliver? What can the system do 
after this phase that it couldn't before? Written for someone who 
hasn't read the design analysis.]

## Already built (reuse, do not rebuild)
[Inventory from Step 1. Grouped by module. Each item: name, location, 
what it does, why this spec uses it.]

| Function/Module | Location | What it does | How this spec uses it | Depth |
|-----------------|----------|--------------|----------------------|-------|
| ... | ... | ... | ... |

## Feature overview
[Plain-English explanation of the general logic. No code. Describe 
the happy path first, then edge cases.]

## Out of scope
[What this phase explicitly does NOT do. List concrete things the 
reader might assume are included. For each, note which future phase 
handles it, or "deferred — no phase assigned yet."]

- **[thing]** — [why it's out of scope]. [Handled by Phase N / deferred.]

## Constraints
[Non-negotiable rules from CLAUDE.md, architecture decisions, and 
enforcement hooks that the build must respect. List each with source.]

- [constraint] — source: [CLAUDE.md / DECISION-NNN / hook]

## Assumptions
[Claims about existing code this spec depends on. Research verifies each one.
Each must be a falsifiable claim — what would prove it wrong? Vague beliefs don't belong here.]

| ID | Assumption | Source implication | What would prove it wrong |
|----|-----------|-------------------|--------------------------|
| A1 | [Falsifiable claim about existing code or interface] | implication #N | [specific condition that invalidates it] |

## Component dependency order

[Documents what must exist before each component can work — not the order a developer writes code. Execution order is owned by `/plan-from-specs`.]

### 1. <component to build>
**Goal.** [One sentence: what this component delivers, in plain English.]

**Build.** [What to create or modify. Name the files/modules. Describe 
the behavior, not the implementation. The downstream planner decides 
exact code.]

**Depends on.** [Which previous components must exist first. 
"None" if independent.]

**Assumes.** [Optional — assumption IDs from the `## Assumptions` table this component depends on. E.g., A1, A3. Omit if none.]

**Interface shape.** [Optional — only for steps creating/modifying module 
boundaries. What do callers see (the interface)? What's hidden behind it 
(the implementation)? If introducing a new seam, how many adapters exist 
— 1 (speculative) or 2+ (real)?]

**Dependency category.** [Optional — only for steps introducing new 
interfaces. One of: in-process (test directly) / local-substitutable 
(test with stand-in) / remote-owned (define port, test with in-memory 
adapter) / true-external (inject port, test with mock). Determines test 
strategy for downstream planner.]

**Decisions.** [Optional. Open questions that need resolving during 
detailed planning or research. Frame as questions, not assertions.]
- Q: [question]? Options: [A / B]. Leaning [X] because [reason].

**Done when.** [Observable criteria. What would a non-coder check to 
verify this step is complete? Avoid "tests pass" — describe the 
behavior being tested.]

Example good: "When a file inside Projects/Alpha/ is captured, its 
frontmatter contains a location_confidence score. When that score 
is below the threshold, frontmatter also contains location_review: true."

Example bad: "assert location_confidence >= threshold passes"

---

### 2. <next thing to build>
[same structure]

---

## Handoff notes
[What the next stage (research/planning) needs to know that doesn't 
fit in any build step. Cross-phase contracts, data format agreements, 
things the spec author is uncertain about.]

- **Contract with Phase <N>:** [what this phase promises to deliver 
  that Phase N depends on]
- **Open uncertainty:** [thing you're not sure about + why]
- **Suggested research:** [specific topic to investigate before 
  detailed planning, e.g., "research how existing reconcile pipeline 
  handles batch operations — may affect step 3"]
```

---

### Step 4 — Cross-check before finalizing

1. **Constraint check:** Verify every component definition against the guardrail checklist loaded in Step 0b. Any violation → fix or flag with ⚠️. Do not re-derive constraints — use the checklist.
2. **Scope check:** Remove anything not in the design decision. If a build step introduces features, flags, or abstractions the user didn't ask for, cut it.
3. **Dependency check:** Verify build order makes sense — no step depends on something built later. If circular, flag and restructure.
4. **Debt check:** If any build step touches known tech debt, note it in that step's **Decisions** section. If the debt is not yet recorded in `docs/TECH_DEBT.md`, call `/guardrail-check Write` to record it before finalizing.
5. **Completeness check:** Walk through the design decision's implications one by one. Each implication must map to at least one build step or an "Out of scope" entry. If an implication is orphaned, either add a build step or explicitly defer it.

---

### Step 5 — Write spec doc and recommend next step

**Writing the spec doc is mandatory.** Do not skip this regardless of scope.

**Where to write:** Write to the specs folder `docs/AI_artifacts/2_specs/` (derive sub-path from `CLAUDE.md` repo structure). If the folder does not exist, ask: "Where should I save spec docs for this project?" Write a new file there.

**What to write:** The full spec from Step 3, verbatim — purpose, already built inventory, feature overview, out of scope, constraints, assumptions, component dependency order, and handoff notes. Do not summarize.

**Next step** (output after writing the doc):

"Spec written. Run `/factual-code-verification` to verify spec assumptions against real code before planning."

---

## Red Flags — stop and re-read

| Thought | Problem |
|---------|---------|
| "The planner can figure out the build order..." | No. Build order is YOUR job. Specify it. |
| "This is obvious, no need to list it in Already Built..." | If the downstream AI doesn't know it exists, it will rebuild it. List everything. |
| "I'll add a helper function for..." | You write specs, not code. Describe the behavior. |
| "There are basically two steps..." | You probably missed a step. Decompose further. |
| "The user will understand this implies..." | They won't. Make it explicit in Out of Scope or Constraints. |
| "This config already exists so I won't mention it..." | Mention it in Already Built. The planner needs to know. |
| "I'll just do the design analysis myself to save time..." | No. Design analysis is a separate skill with its own protocol. Running it inline produces shallow analysis and skips important steps. Stop and redirect to codebase-design-analysis. |

---

## Quick Reference

| Need | Where to look |
|------|---------------|
| Design decision + implications | codebase-design-analysis output or user brainstorm |
| Project patterns + enforcement | `CLAUDE.md` |
| Prior decisions | `STATE.md`, `docs/decisions/`, `docs/adr/` |
| Current build progress | `CLAUDE.md` → Build progress, `STATE.md` |
| What exists in codebase | `codegraph_explore` first; grep/read raw source only after it locates the code |
