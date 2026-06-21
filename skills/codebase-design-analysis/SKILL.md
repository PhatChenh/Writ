---
name: codebase-design-analysis
version: 1.0.0
description: Use when asked for implications, options, or implementation approach for a design decision in an existing codebase. Triggers on "what are the implications", "what are my options", "how should we implement X", "analyze this change", "what would it take to add X", or any design question requiring code-grounded answers. Also use when user describes a desired outcome and wants to think through how to achieve it.
---

> **Coupling note (Writ):** the design doc's `##` section template is enforced by the `validate-design-doc` hook (`.claude/hooks/validate-design-doc.sh`; required: Summary / Constraints / Alternatives Considered / Chosen Approach / Risks / Open Questions). If you change the template here, update that hook too — they must agree or the gate false-denies.

# Codebase Design Analysis

## Overview

Analyze a codebase, unpack implications of a proposed change, and generate multiple concrete options — each grounded in actual code, each explained so a non-technical reader can evaluate tradeoffs.

**Voice rule (scoped).** Write as if the reader is a smart manager who cannot read code. The plain-English LEAD — a sentence of what it means and why it matters before any code citation — applies to the **Decision**, each **Option's "What this means"**, and **Known tradeoffs**. Code references (`file:line`) for those go in parentheses or sub-bullets, never as the lead sentence; the reader should understand those sections WITHOUT reading the citations. **Implications** follow the same plain-English-lead rule: each bullet opens with a non-coder sentence (what changes and why it matters), followed by technical detail as a sub-bullet. Code symbols stay in the sub-bullet, never in the lead.

**Symbol-gloss rule (always on).** Every code symbol — function, class, constant, including ones built in earlier phases — gets a 3–5 word plain-English gloss on its first mention in a section, and the sentence must still read correctly if every `code`-formatted token were deleted. The symbol is a parenthetical anchor for an engineer, never a thing the reader is assumed to already know. Language/library primitives (e.g. `rglob`, `SHA256`, Pydantic) are explained in plain words inline ("walks the folder top-to-bottom", "content fingerprint") — never list these in a glossary.

## Non-interactive mode

When the dispatch prompt contains `NON-INTERACTIVE: true`, this skill is running as a subagent with no human in the loop. In this mode:

- **All `AskUserQuestion` gates become auto-select:** choose the recommended option (A) and proceed. Do not call `AskUserQuestion`.
- **File-write gates auto-proceed:** write to the path specified in the dispatch prompt. Do not ask for confirmation.
- **Deferred questions go into the doc's "Open questions" section** instead of blocking.
- **All other rules remain in force.** Non-interactive mode skips interactive gates — it does not skip analysis or file writes.

## Code exploration — CodeGraph first (mandatory when the repo is indexed)

When the repo has a `.codegraph/` directory, CodeGraph is the PRIMARY tool for locating and reading code — not Read, Grep, Glob, or bash. Mandatory whether this skill runs interactively or as a dispatched subagent.

- **Start every code question with `codegraph_explore "<symbols or question>"`** — one call returns the verbatim source plus the call graph. Use `codegraph_node` for one symbol's full body, `codegraph_callers` for blast radius. If the tools are deferred, load them first via ToolSearch: `select:mcp__codegraph__codegraph_explore,mcp__codegraph__codegraph_node,mcp__codegraph__codegraph_callers`.
- **Use grep / bash / Read ONLY to view raw code AFTER CodeGraph has located it**, for non-code files (shell, yaml, config, markdown), or when there is no `.codegraph/` index.
- **Anti-pattern:** opening with `grep -r` / `find` / Read for a code-symbol lookup — it repeats work CodeGraph already pre-computed and costs far more tokens.

## Reader modes

**Default (non-coder readable):** Every section gets all three treatments below. This is the permanent default — the audience is non-technical managers and teammates.
1. **Per task/section "In plain terms" lead** — 2–3 sentences, ZERO bare code symbols: what changes for the user, what could go wrong.
2. **Doc-top "Cast of characters" glossary** — lists ONLY project symbols referenced 3+ times across the doc (`name` : one-line role). One-off symbols stay inline-glossed; language primitives never go in the table.
3. **file:line citations demoted to sub-bullets** so the prose line stays clean.

**`engineer-mode`** — opt-in override when a developer explicitly requests dense output. Strips the "In plain terms" leads, drops the glossary table, promotes file:line citations inline. The Symbol-gloss rule still applies (always on). Engage only when caller passes `engineer-mode` flag.

## Design Lens

These principles shape how options are generated — not verified after. When evaluating module boundaries, interfaces, and abstractions, think through this lens:

| Principle | Question to ask |
|---|---|
| **Depth** | Does this option produce modules where interface is smaller than implementation? Shallow module = design smell. |
| **Deletion test** | Delete the proposed module — does complexity vanish (pass-through, bad) or reappear in N callers (earning keep, good)? |
| **Seam discipline** | Does this new interface have 2+ adapters (real seam) or just 1 (speculative — don't introduce)? |
| **Dependency category** | What kind of dependency? in-process / local-substitutable / remote-owned / true-external → determines test strategy. |

Use these four questions to generate options, not to score them after.

---

## Protocol (follow in order — do not skip steps)

### Phase -1 — Requirement Interview

Before reading any code, nail down what the user actually wants. Fuzzy requests produce options for the wrong problem.

**One question at a time. Provide your recommended answer. Wait for response. Repeat.**

Work through these in order, stopping when each is resolved:

1. **Restate** — Rephrase the request in your own words. Ask: "Is this what you mean?" Get explicit confirmation before continuing.

2. **Term sharpening** — Identify every fuzzy or overloaded term in the request. For each, propose a precise canonical name. Example: "You said 'domain tag' — do you mean a YAML frontmatter key, a filename prefix, or something else?"

3. **Scope probe** — Ask what's in scope and what's out. Example: "Does 'inside a project/domain' mean: any file under that folder, or only files explicitly registered in a config?"

4. **Edge-case scenarios** — Invent 2–3 concrete scenarios that stress-test the boundaries. Force precision. Example: "What if a file sits in a shared folder used by two domains? Which tag wins, or is that an error?"

5. **Success criteria** — Ask what "done" looks like. How would you verify the change is working correctly? What's the failure mode we're preventing?

6. **Sign-off** — Summarize your understanding in plain English. Ask: "Proceed with this understanding?" Only move to Step 0 after explicit confirmation.

7. **ID prefix** — Ask: "What ID prefix should I use for behavior inventory entries? Format: phase number + 3-letter feature slug (e.g. `P2-CLS`). Check with teammates if working across parallel phases." Store the answer as `$ID_PREFIX` for Step 3.5.

**Inline CONTEXT.md update:** When a term is resolved during the interview, update or create `CONTEXT.md` immediately. Do not batch. Use format in [CONTEXT-FORMAT.md](./CONTEXT-FORMAT.md).

**Soft-block:** If the user says "skip" or "just analyze", proceed — but flag which terms remain ambiguous and note that options may be misaligned with intent.

---

### Step 0 — Context gate

Before reading any code, locate and read these documents. Each serves a different purpose. **Check every item — raise a separate warning for each missing or stale source.**

#### Required sources

| Source | Purpose | If missing |
|--------|---------|------------|
| `CLAUDE.md` | Coding patterns, enforcement rules, layout, conventions | ⛔ Stop. Cannot proceed safely. Ask user to create or point to it. |
| Caller-specified files | The actual code to analyze | ⛔ Stop. Ask which files are in scope. |

#### Adaptive discovery from CLAUDE.md

After reading CLAUDE.md, **scan it for references to other context documents** — any file paths mentioned as "read before changing", "reference docs", or similar. Common examples: `docs/roadmap.md`, `CONSTRAINTS.md`, `TECH_DEBT.md`, `docs/decisions/`. Read every referenced file that exists on disk. Do not hardcode assumptions about which files a project has — let CLAUDE.md tell you.

#### Architecture & debt sources

Actively look for these. Check common locations: `STATE.md`, `docs/decisions/`, `docs/adr/`, `architecture/`, `docs/architecture/`, `CLAUDE.md` (architecture decisions section).

| Source | Purpose | If missing |
|--------|---------|------------|
| Architecture decisions | Prior design choices that constrain options | ⚠️ Warn: "No architecture decisions found. My options may contradict prior choices. Do you have architecture decision records? If so, where?" |
| Technical debt list | Known debt that this change might touch or retire | ⚠️ Warn: "No tech debt records found. I may suggest approaches that duplicate known debt. Do you track tech debt? If so, where?" |
| `STATE.md` or equivalent | Current phase, open questions, recent context | ⚠️ Warn: "No STATE.md found. I cannot check current phase or open questions. Continuing — suggestions may be out of sync with recent work." |

**If user points you to doc locations, remember them for the rest of the session.**

#### Staleness checks (run after reading each source)

- **CLAUDE.md layout drift:** Compare described folder structure against actual disk. Flag mismatches.
- **STATE.md age:** If `_Last updated:_` is older than 30 days or phase described doesn't match recent commits, warn.
- **Architecture decisions:** If a decision is marked "superseded" or "revisit", flag it — it may not constrain options anymore.

**All warnings fire every session.** "Proceed" from a previous session does not carry over.

---

### Step 1 — Read first, say nothing

Read all files the caller lists plus their imports/dependencies. If no files listed, ask which files are in scope. Do not output anything until you have read the relevant code.

---

### Step 2 — Gather constraints

Call `/guardrail-check Review` with the proposed change description and the domains it touches. This produces a filtered danger checklist of constraints that apply to this specific change.

Write the checklist output into the design doc under a `## Guardrail Checklist` section — it is required input for `/writing-detailed-specs`.

If this step surfaces a constraint or tech debt not yet recorded in `docs/CONSTRAINTS.md` or `docs/TECH_DEBT.md`, call `/guardrail-check Write` to record it before proceeding.

List the checklist explicitly before proposing any options.

---

### Step 3 — Implications unpacking

**Goal:** Surface everything the reader needs to know about what this change actually means — including things that aren't obvious from the request.

**Output format:** Implications is a bullet list where each entry has two layers:
- **Lead (required):** One plain-English sentence — what changes and why it matters. No bare code symbols. A non-coder must understand this line alone.
- **Technical sub-bullet (required):** The code-verified fact — function name, file:line, signature, constraint. For the spec writer.

Do NOT emit 3a–3f as section headers.

Example:
- The system will now remember which folder each file came from, so it can group files from the same folder together later.
  - `find_by_folder_path(folder_path, db_path)` added to `storage/batches.py` — queries `batches` by vault-relative folder path, returns the most recent batch_id or None.

**Coverage checklist (internal — confirm the flat list covers, don't print as headers):** (a) what each key term means in this codebase; (b) guards/constraints touched; (c) files touched — directly vs indirectly; (d) downstream effects; (e) runtime dependencies; (f) module depth / deletion test.

For (f): map existing modules being touched — for each, is it deep (small interface, big implementation) or shallow? A shallow module being extended is a signal — consider deepening it. Apply the deletion test: would removing this module concentrate complexity (good — earning its keep) or just eliminate a pass-through?

Flag any assumption you cannot verify: write `[UNVERIFIED: <what you assumed>]` inline.

---

### Step 3.5 — Generate success criteria

After implications are mapped, enumerate success criteria before generating options. Criteria define what "working correctly" looks like from the outside — independent of which option is chosen.

**Internal enumeration (do not output — use to classify entries):**

1. List every side-effect the proposed change produces: files created, DB rows written, vault state changed, events emitted, notes moved
2. For each side-effect: what breaks if it goes wrong? → invert into a "must not happen" criterion
3. What positive evidence must confirm the feature ran? → at least one positive criterion per vault-observable outcome
4. Are there concurrent actors (watcher + pipeline, watcher + user editing)? → flag each pair; route to `tier: full`

**Tier classification (internal):**

- `tier: smoke` or `tier: phase` — vault-visible outcomes only: file paths, frontmatter fields, inbox/folder state. Format each as Given / When / Then with exact paths and field names. Cap: happy path + top 2 failure/edge cases, max 5 scenarios total.
- `tier: full` — requires terminal, logs, or DB access: audit log rows, DB rows, log lines, Result types, non-interference pairs.

**Write directly to `docs/system_behavior/behavior_inventory.yaml`** — no prose output, no confirmation gate. Read the existing file first to determine the next sequential number for `$ID_PREFIX`.

Every new entry MUST use this schema exactly:

```yaml
- id: $ID_PREFIX-NN                    # e.g. P2-CLS-01; $ID_PREFIX from Phase -1 question 7
  behavior: "one-line description"
  tier: smoke                          # smoke | phase | full
  phase: N                             # current phase number
  trigger: "kms <command> <args>"      # CLI command or event
  fixtures: []                         # left empty — /update-behavior-guide Link job fills this
  steps: "plain-English tester action"
  expected: "exact vault path / field / log pattern that must be true"
  spec_ref: "docs/AI_artifacts/1_design/<slug>.md §Success criteria"  # design doc that produced this criterion
  human_reviewed: no
  pytest_ref: null
  status: planned                      # planned — not built yet; implementer flips to active when phase ships
  retired: null
```

After writing, output ONE line in chat:
```
✓ N smoke/phase, N full entries appended to behavior_inventory.yaml
```

Do NOT write a separate file to `docs/AI_artifacts/1.5_usability_test/`. The inventory IS the success criteria system.

---

### Step 4 — Options grid

**Present every viable option. No padding, no minimum.** If only 1 option is genuinely viable, present that 1 with full treatment. If 5 are viable, present all 5. The test for "viable" is: a reasonable person could pick this option and succeed. Options you considered but rejected go in a **"Rejected alternatives"** section after the grid — one line each with the reason it's not viable.

**Exploration obligation:** Before concluding there's only one viable option, you must have considered at least: a conservative approach (flag only, no mutation), a moderate approach (act with safeguards), and an aggressive approach (full automation). If all but one fail the viability test, document why in the rejected alternatives.

**At least one option must consider deepening an existing shallow module** instead of creating new ones. For every new module boundary in an option, state why it passes the deletion test. For every new interface, state whether the seam is real (2+ adapters) or speculative (1 adapter).

For each option, use this structure:

```
### Option A — [short name] (Recommended / Not recommended)

**What this means:** [1-2 sentences a non-coder can understand. What changes 
for the user? What's the practical effect?]

**Approach:** [Technical summary — what code does]

**Files touched:** [list with brief reason for each]

**Cost:**
- Dev effort: low / medium / high
- Runtime cost: [LLM calls? Vault scans? DB migrations?]
- Maintenance: [new code to maintain? New config to manage?]

**Risk:**
- [Risk type]: [plain-English description of what could go wrong]

**Module depth:**
- New module boundaries: [list each, with deletion test result]
- New interfaces: [list each — real seam (2+ adapters) or speculative?]
- Existing modules affected: [deep / shallow — if shallow, does this option deepen it?]

**What it defers:** [What does a future phase inherit if we pick this?]

**Constraints check:**
For each item in the Step 2 guardrail checklist, mark whether this option satisfies or violates it:
- [ ] C-XX · [rule name] — satisfies / violates / not applicable + one-line reason
```

**After all options, state your recommendation with ONE reason:**
> Recommended: Option A. [One sentence why — framed as a tradeoff the reader can evaluate, not a technical assertion.]

**ADR offer:** After the options grid, check each option against these three gates:
1. Hard to reverse — cost of changing your mind later is meaningful
2. Surprising without context — a future reader would wonder "why did they do it this way?"
3. Result of a real trade-off — genuine alternatives existed and you picked one for specific reasons

If any option the user selects meets all three, offer to write an ADR. Use format in [ADR-FORMAT.md](./ADR-FORMAT.md). Do not offer if any gate is false.

---

### Step 5 — Cross-check

Before finalizing:

1. **Scope check:** Remove any suggestion that adds features, flags, or abstractions not explicitly requested. Scope creep is not "being thorough."
2. **Constraint check:** Re-verify every option against Step 2 constraints. Mark any option that violates a constraint with ⚠️ and explain the violation.
3. **Debt check:** If any option touches known tech debt, note whether it retires, worsens, or is neutral to each item.
4. **Decision check:** If any option contradicts a prior architecture decision, flag it explicitly: "⚠️ This option contradicts DECISION-NNN. Proceeding would require revisiting that decision."
5. **Dependency check:** If any option requires features/phases not yet built, label it `[REQUIRES: Phase N]` or `[REQUIRES: <component>]`.

---

### Step 6 — Write design doc and recommend next step

**Writing the design doc is mandatory.** Do not skip this regardless of scope.

**Before writing — confirm with user:**

Call `AskUserQuestion` with:
- Proposed file path (derived from `CLAUDE.md` docs folder, or ask if not specified)
- One-line summary of what will be written

Options:
- A) Write to `[proposed path]` (Recommended)
- B) Write to a different path — user specifies
- C) Skip file write — show doc in chat only

Do not write any file until the user selects A or B. If C, output the doc as markdown in the response instead. **Non-interactive mode:** skip this gate — write to the path specified in the dispatch prompt and proceed.

**Where to write:**

| Input mode | Where to write |
|-----------|---------------|
| User typed request in chat | Write to the design folder `docs/AI_artifacts/1_design/` (derive sub-path from `CLAUDE.md` repo structure). If unclear, propose `docs/AI_artifacts/1_design/[feature].md` and confirm with user before writing. |
| User pointed to an existing file | Write the output back into that file, under the relevant feature section. |

**What to write:** A design doc structured as follows:

- **Decision** — which option was chosen and in one sentence, why
- **Implications** — what this option means for the codebase (from Step 3), plain English first, code refs in sub-bullets
- **Known tradeoffs** — what we are giving up by picking this over the alternatives
- **Risks** — anything later stages (research, planning, implementation) should verify or watch out for
- **Open questions** — questions this option raises but does not yet resolve; note if any are blockers. Each open question MUST follow this format:

  **OQ-[ID] — [Plain-English title: what the decision is about]**

  Right now, [current state in plain English — no code jargon].

  The question: [one sentence, still plain English].

  **If [option A]:** [concrete consequence — what breaks or what works, plain English].
  **If [option B]:** [concrete consequence — what breaks or what works, plain English].

  Recommendation: [option]. [One sentence reason a non-coder can evaluate — no jargon].
- **ADR references** — link to any relevant ADR if this option was constrained by or creates one
- **Options explored** — one entry per viable option not chosen + rejected alternatives: (1) one-sentence summary, (2) main reasons it was not selected

**Next step** (output after writing the doc):

"Design doc written. Run `/architecture-docs` to update the main architecture designs, and then run `/writing-detailed-specs` to structure the chosen option into build steps."


---

## Red Flags — stop and re-read the code

| Thought | Problem |
|---------|---------|
| "Typically in Python you would..." | Training-data guess. Find it in the actual file. |
| "We could also add a --flag for..." | Out of scope. Remove it. |
| "This property should exist..." | Verify at file:line before citing it. |
| "The pattern is..." | Read the pattern in this repo, not from memory. |
| "There are basically two approaches..." | Did you explore conservative, moderate, and aggressive? If all but one fail viability, document why in rejected alternatives. |
| "The user will understand this code reference..." | They won't. Gloss it (3-5 words); don't make a symbol carry the sentence. |

## Quick Reference

| Need | Where to look |
|------|---------------|
| Project layout | `CLAUDE.md` → Repository layout section |
| Config / thresholds | `CLAUDE.md` → Tech stack or Automated enforcement |
| Entry points | `CLAUDE.md` → Commands section |
| Coding patterns | `CLAUDE.md` → Coding patterns section |
| Architecture decisions | `STATE.md`, `docs/decisions/`, `docs/adr/`, or ask user |
| Technical debt | `STATE.md`, `docs/tech-debt/`, or ask user |
| Current phase / progress | `STATE.md` or `CLAUDE.md` → Build progress |
