# Writ — Local Adaptation Decisions

> **What this file is.** A running record of *how we chose to set Writ up for my own workflow*, and **why**. This is NOT upstream Writ design — it is the adapt-and-learn layer on top of the vendored fork. Read this first when you (future me / future AI) wonder "why is our Writ wired this way?"
> **Operating mode (locked 2026-06-21):** This repo is a **vendored fork in adapt-and-learn mode**, NOT a development target. We do NOT build new features into Writ. We only (a) learn how it works, (b) make minimal adjustments so it fits the ai_kms workflow, and (c) rewire *our* input skills/hooks to feed it.
> Every change must trace to "make Writ fit my workflow," never "improve Writ."

---

## D4-01 · Graph-canonical authoring

**Decision.** Writ's graph is the canonical store. `bible/*.md` is a *derived, still-committed* export (version control + portability + install seed), never hand-edited. Authoring direction: write *into* the graph (`writ propose` / CLI), then regenerate bible via `writ export`. We will **not** maintain flat `CONSTRAINTS.md` / ADR / `TECH_DEBT.md` docs by hand — our input skills write rule-nodes into the graph instead.

**Why.** Matches the Writ author's stated intent — `writ/graph/ingest.py` docstring: *"bible/*.md is the exported view of the canonical graph, not the source of truth. Use `writ import-markdown` only for initial bootstrap or when re-importing after manual Markdown edits."*

**Consequences / verified mechanics (do not relearn the hard way):**
- The FalkorDB graph is a **binary blob** — not git-diffable/portable. So bible export is mandatory-*after*-authoring for VC/review/machine-moves, but it is downstream of the graph, never the input.
- A newly authored rule is **invisible to `writ query` until the daemon re-warms** (pipeline rebuilt from the graph at startup) — NOT until it is exported to bible. Query reads graph-built in-memory indexes (`build_pipeline`: `MATCH (r:Rule) RETURN r`, `writ/retrieval/pipeline.py`); bible is never on the query path.
- Content enters the graph three ways: `scripts/seed_phase_*.py` (author's dev-time Python literals — NOT run by bootstrap), `writ import-markdown` (bible → graph, the install/bootstrap seed), and `writ propose` (runtime). Bootstrap uses `import-markdown` (`scripts/bootstrap.sh:183`, `scripts/bootstrap-plugin.sh:168`).

**Affects later work:** 4A/4B/4C input-skill rewrites (constraints, ADRs, tech-debt) target the graph, not flat docs.

---

## D4-02 · Per-repo isolation via "A-auto" (deterministic port + on-demand auto-start)

**Problem.** Upstream Writ ships as a **single global daemon** (one `writ serve` on `localhost:8765`) serving **one global graph**. The graph path `.writ/graph.db` is CWD-relative, but the plugin bootstrap starts the daemon with `cd "$WRIT_DIR"` (`scripts/bootstrap-plugin.sh:181`), so all projects share one graph at the plugin install dir. **Cross-contamination is the default.**

This matters because the author's corpus is **100% universal** (security, clean-code, SOLID, testing, perf, framework/language rules) with **no concept of "project"** in the schema (`scope` = code granularity: component/task/session/ entity — verified in `writ/graph/schema.py`). We additionally want to store **project-specific** rules (constraints / ADRs / tech-debt) — a category the author never designed for. Hence we need isolation the upstream model lacks.

**Rejected — query-time filtering ("tag + domain filter").** Unreliable:
- The `domain` filter is single exact-match (`pipeline.py` Stage 1) — cannot express "shared-general OR this-project".
- The **authoring gate bypasses filtering entirely**: `gate.py` `_check_similarity` runs `pipeline._vector.search(...)` across the whole graph with no filter, so redundancy/novelty/conflict checks would compare across projects. No hook to inject a filter there. Fixing it = Writ-core changes → violates adapt-only.

**Rejected — single daemon hot-swapping graphs per request.** Needs Writ-core changes (per-request graph + pipeline rebuild) and destroys the pre-warm perf model.

**Rejected — A-lean (single daemon follows active repo's CWD).** Breaks when multiple repos are open at once (they fight over `:8765` / wrong graph). We work on multiple repos concurrently.

**Chosen — A-auto.** Isolate at the **storage layer**, automated so it stays low-ops even with many concurrent repos:
1. **Port = deterministic from repo path** — e.g. `8765 + (hash(git_root) mod 1000)`. No registry to maintain; the hook recomputes it every time. Stable per repo.
2. **Daemon CWD = repo (git) root** — so `.writ/graph.db` resolves per-repo.
3. **On-demand auto-start** — the RAG hook already healthchecks + auto-starts a daemon; we generalize it to the repo-specific port + start dir.

**Why it is reliable (verified against code, 2026-06-21):**
- `db.py:96` `abs_db_path = os.path.abspath(db_path)` — relative path resolved against the daemon's CWD.
- `db.py:106` `sock_hash = hashlib.md5(self._db_dir.encode())` — socket keyed on the **absolute** db dir. Different repo CWD → different abspath → different md5 → **different socket + graph.db + lockfile. No collision.** (This was the make-or-break risk; it holds.)
- Isolation is storage-level, so **every** code path (retrieval AND the gate similarity/conflict checks) automatically sees only that repo's graph — no filter discipline required.
- One shared `writ.toml` works for all repos (path stays relative, abspath'd per CWD) — no per-repo config file needed.

**Work items (all in OUR RAG hook — `.claude/hooks/writ-rag-inject.sh` — no Writ-core change):**
1. Auto-start currently does `cd "$WRIT_DIR"` + `--port "$WRIT_PORT"` (hook:47-48) → change to `cd` the **repo root** and set a per-repo `WRIT_PORT`.
2. Derive repo root: read `cwd` from the hook's stdin JSON (Claude provides it; currently only mentioned in a comment at hook:74, not used for routing) or `git rev-parse --show-toplevel`.
3. Make the start-lock per-port: `/tmp/writ-server-starting.lock` (hook:23) → `…-$PORT.lock`, so concurrent repos don't block each other's startup.

**Accepted cost.** N active repos = N background daemons (redis + uvicorn) = passive RAM. This is *passive* cost (memory), not *manual* cost (your time), so still low-ops. If RAM ever bites, an idle-timeout auto-shutdown is a later add (would be dev — out of scope now).

**General-knowledge sharing.** Each repo's graph is seeded from the shared `bible/` at bootstrap (universal rules shared *by value*). Update a universal rule in bible → re-import per repo. Project-specific rules layer on top, isolated by storage.

---

## D4-03 · Adopt Writ's full mode system, skill-driven auto-switch (locked 2026-06-21)

**Decision.** Adopt **all** Writ modes — `conversation` / `debug` / `review` / `work` (+ `prototype` bypass). Reverses the earlier "stay out of Work mode" lean: we now opt INTO Work mode, which arms the 9 Work-gated blocking hooks (L3 territory).

**Mode switching = skill-driven (deterministic), NOT heuristic.** Each of our skills sets the mode on entry — `/grill`/`/think-with-me` → conversation, `/build-pipeline` implement step → work, `/code-review` → review, `/tdd-implement` → work. The skill knows the phase, so no prompt-classifier guessing. Rejected: heuristic UserPromptSubmit classifier (fragile, same misfire class as `auto-approve-gate`). Hybrid (skills + fallback classifier) deferred — add only if ad-hoc out-of-skill prompts prove to need it.

**Mechanics (verified):** mode is set via a Bash `mode set <x>` command (`bin/lib/common.sh:306`; `tier set 1|2|3` also maps → work, `inject-tier-workflow.sh:36`), persisted in the session cache. `is_work_mode` (`common.sh:46`) = mode equals `work`; 9 of 11 blockers gate on it. Work mode runs a file-based gate machine in `.claude/gates/` (`phase-a.approved` → `test-skeletons.approved` → code; `writ-rag-inject.sh:608-621`).

**Gate overlap — DIRECTION LOCKED 2026-06-21: Writ gates REPLACE our HITL + /build-pipeline plan/test gates** (option a). Writ's Work-mode gate machine (plan→test→code, unlocked by human "approved") becomes the mechanical lock; `/build-pipeline` becomes the *content producer* feeding it. Our hand-rolled HITL/skill gates that duplicate plan/test approval get retired. First concrete instance accepted: `writ-pre-write-dispatch` (✅ in ledger). **Pending edits, revisit later** — still need to walk the other overlapping gates (`validate-exit-plan`, `enforce-violations`, `validate-test-file`) and reconcile/retire the matching skill-side gates one-by-one.

**Work items (later):** wire `mode set` calls into our skill entry points; retire overlapping skill-side plan/test gates in favor of Writ's; walk remaining overlapping gates individually.

---

## Open / not yet decided

- 4A/4B/4C: exact mapping of constraints / ADRs / tech-debt into graph node types
  + which input skills get rewired.
- 4D: hook coexistence (our PostToolUse grep guards vs Writ's 33 hooks) + which of the 33 hooks we adopt (pick-list pending).
- 4E/4F/4G: process integration, bible process-rules, corpus seeding.
- Plugin activation scope (project-scoped vs global `patch-global-config.sh`, which overwrites global `~/.claude/CLAUDE.md`).

---

## Appendix · Writ graph schema (verified from code 2026-06-21)

Source of truth: `writ/graph/schema.py` (Pydantic models), `writ/graph/db.py:40` (`ALLOWED_EDGE_TYPES`), `writ/graph/ingest.py:79` (`NODE_ID_FIELDS`). FalkorDB stores each node type as a **label**; each node's primary key is a per-type id field (matched in `create_edge`, `db.py:210-221`). Dates → ISO strings, nested dicts → JSON strings (`_coerce_value`, `db.py:50`).

### Node types (13)

| Label | Id field | Id prefix | Retrievable? | Type-specific fields (beyond the shared base) |
| --- | --- | --- | --- | --- |
| **Rule** | `rule_id` | domain-coded (e.g. `ARCH-ORG-001`, `ENF-GATE-FINAL`) | ✅ Stage 1-3 | full field set — see next table |
| **Abstraction** | `abstraction_id` | `ABS-` | ✅ (generated) | `summary`, `rule_ids[]`, `domain`, `compression_ratio` |
| **Skill** | `skill_id` | `SKL-` | ✅ Stage 1-3 | — (base only) |
| **Playbook** | `playbook_id` | `PBK-` | ✅ Stage 1-3 | `phase_ids[]`, `preconditions[]`, `dispatched_roles[]` |
| **Technique** | `technique_id` | `TEC-` | ✅ Stage 1-3 | — (base only) |
| **AntiPattern** | `antipattern_id` | `ANT-` | ✅ Stage 1-3 | `counter_nodes[]`, `named_in?` |
| **ForbiddenResponse** | `forbidden_id` | `FRB-` | ✅ Stage 1-3 | `forbidden_phrases[]`, `what_to_say_instead`, `always_on=True` |
| **Phase** | `phase_id` | `PHA-` | ❌ Stage 4 only | `position`, `name`, `description`, `parent_playbook_id` |
| **Rationalization** | `rationalization_id` | `RAT-` | ❌ Stage 4 only | `thought`, `counter`, `attached_to` |
| **PressureScenario** | `scenario_id` | `PSC-` | ❌ Stage 4 only | `prompt`, `expected_compliance`, `failure_patterns[]`, `rule_under_test`, `difficulty` |
| **WorkedExample** | `example_id` | `EXM-` | ❌ Stage 4 only | `title`, `before`, `applied_skill`, `result`, `linked_skill` |
| **SubagentRole** | `role_id` | `ROL-` | ❌ Stage 4 only | `name`, `prompt_template`, `dispatched_by[]`, `model_preference?`, `tools?`, `description?` |

> **Retrievable** = participates in Stage 1-3 ranking (`RETRIEVABLE_NODE_TYPES`, `schema.py:80`). Non-retrievable nodes surface only via Stage-4 graph bundle expansion.
> **Shared base** (`_MethodologyNodeBase`, all methodology nodes): `domain`, `scope`, `trigger`, `statement`, `rationale`, `tags[]`, `confidence`, `authority`, `last_validated`, `staleness_window`, `evidence`, `times_seen_positive/negative`, `last_seen?`, `source_attribution?`, `source_commit?`, `body`. Retrievable subtypes add required `severity`; non-retrievable make `severity` optional.

### Rule node fields (the type we author project rules into — 4A/4B/4C)

| Field | Type | Default | Notes |
| --- | --- | --- | --- |
| `rule_id` | str | — | must match `RULE_ID_PATTERN` (e.g. `SEC-UNI-001`, `FW-M2-RT-003`) |
| `domain` | str | — | non-empty |
| `severity` | enum | — | `critical` / `high` / `medium` / `low` |
| `scope` | str | — | lowercase `[a-z][a-z0-9_-]*` (code granularity: component/task/session/entity — **no "project" concept**) |
| `trigger` | str | — | non-empty — when the rule fires |
| `statement` | str | — | non-empty — the rule itself |
| `violation` | str | — | non-empty — what breaking it looks like |
| `pass_example` | str | — | non-empty |
| `enforcement` | str | — | non-empty (conventions: human-review/judgment-gate/training-feedback/audit-log/advisory-only) |
| `rationale` | str | — | non-empty — the "why" |
| `mandatory` | bool | `False` | `ENF-*` always-loaded rules |
| `confidence` | enum | `production-validated` | battle-tested / production-validated / peer-reviewed / speculative |
| `authority` | str | `human` | `human` / `ai-provisional` / `ai-promoted` |
| `times_seen_positive` | int | `0` | auto-feedback counter |
| `times_seen_negative` | int | `0` | auto-feedback counter |
| `last_seen` | str? | `None` | |
| `evidence` | str | `doc:original-bible` | |
| `staleness_window` | int | `365` | days |
| `last_validated` | date | — | **required** |
| `rationalization_counters` | list[dict] | `[]` | methodology absorption |
| `red_flag_thoughts` | list[str] | `[]` | |
| `always_on` | bool | `False` | bypass retrieval, load every turn |
| `mechanical_enforcement_path` | str? | `None` | |
| `body` | str | `""` | |
| `source_attribution` | str? | `None` | |
| `source_commit` | str? | `None` | |

### Edge types (17 — `ALLOWED_EDGE_TYPES`)

| Relationship | Source → Target | Meaning |
| --- | --- | --- |
| `DEPENDS_ON` | Rule → Rule | rule depends on another |
| `PRECEDES` | Rule → Rule | ordering |
| `CONFLICTS_WITH` | Rule → Rule | mutual exclusion |
| `SUPPLEMENTS` | Rule → Rule | additive refinement |
| `SUPERSEDES` | Rule → Rule | deprecation (newer replaces older) |
| `RELATED_TO` | Rule → Rule | loose association |
| `APPLIES_TO` | Rule → target (`target_name`, `target_type`) | rule applies to a named code target |
| `ABSTRACTS` | Abstraction → Rule[] | cluster summary covers these rules |
| `JUSTIFIED_BY` | Rule → Evidence | rule backed by evidence node |
| `TEACHES` | Skill/Playbook → Rule/Technique | teaches the enforcement target |
| `COUNTERS` | AntiPattern/Rationalization → Skill/Playbook/Rule | countered by the target |
| `DEMONSTRATES` | WorkedExample/ForbiddenResponse → Skill/Rule | demonstrates the target's discipline |
| `DISPATCHES` | Playbook/Skill → SubagentRole/Technique | target dispatched as sub-invocation |
| `GATES` | Rule → Skill/Playbook | mechanical enforcement of the target |
| `PRESSURE_TESTS` | PressureScenario → Rule/Skill/Playbook | scenario tests compliance |
| `CONTAINS` | Playbook → Phase | phase is structural member |
| `ATTACHED_TO` | Rationalization → Skill/Playbook/Rule | rationalization attached to parent |

> First 9 are pre-existing; last 8 are Phase-1 methodology additions (`db.py:44`). Edge type validated against this set in `create_edge` (`db.py:207`); unknown type → `ValueError`.
> **Enums:** Severity (critical/high/medium/low) · Confidence (battle-tested/production-validated/peer-reviewed/speculative) · EvidenceType (incident/pr/doc/adr) · authority (human/ai-provisional/ai-promoted).

---

## Appendix · The 33 Process Keeper hooks (reference for 4D pick-list)

**How to read the "Effect on agent" column — four behavior classes (verified from each hook's exit code / decision JSON):**
- **🛑 BLOCK** — emits `permissionDecision: deny`/`ask` or `exit 2`. Can stop the tool call or force the agent to keep working. Highest impact on behavior.
- **💉 INJECT** — exit 0, writes `additionalContext` or a stdout directive the agent reads next turn. Steers without blocking.
- **🗃️ STATE** — exit 0, mutates the Writ session cache; changes what *later* hooks do (e.g. domain hint, exclusion list, budget). Invisible directly, shapes RAG.
- **📝 LOG** — exit 0, telemetry only (friction log / metrics). Zero behavior change; observability.

> **Recommendation legend:** layer each hook belongs to under the D4-xx layering still being decided — **L1** RAG-only · **L2** RAG + anti-cheat (recommended) · **L3** full Process Keeper. "Rec" = keep at recommended Layer 2 or drop.

> **Approve column (✓):** left blank. Type `✅` (or your own mark) in the first cell of any row to approve that hook. Empty = undecided/drop. Mirror your picks into the "Decision ledger" at the bottom if you prefer a flat list.


### Group 1 — RAG retrieval (Writ's core value)

| ✓   | Note                                                                                                               | Hook                        | Event                   | What it does (detail)                                                                                                                                                              | Effect on agent                                        | Layer | Rec                                       |
| --- | ------------------------------------------------------------------------------------------------------------------ | --------------------------- | ----------------------- | ---------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | ------------------------------------------------------ | ----- | ----------------------------------------- |
| y   |                                                                                                                    | **writ-rag-inject**         | UserPromptSubmit        | Cleans the user prompt to keywords, queries `/query`, injects the top relevant rules each turn. Also auto-starts the daemon. The hook we edit for D4-02 (A-auto).                  | 💉 INJECT — agent sees relevant rules before answering | L1    | **KEEP**                                  |
| y   | file-context rules - what are those, and are they specific to that file? or it's just file system in general       | **writ-read-rag**           | PreToolUse[Read]        | Before a Read in **Review/Debug mode only**, queries Writ for file-context rules; no-op in other modes.                                                                            | 💉 INJECT (advisory, never blocks)                     | L1    | **KEEP**                                  |
| y   | so this would inform AI about its edit right? does that apply for write/edit .md file? or just code file like .py? | **writ-posttool-rag**       | PostToolUse[Write/Edit] | After a write, queries Writ with patterns derived from the code just written. Gap-only (skips if PreToolUse already queried that file).                                            | 💉 INJECT (advisory)                                   | L1    | **KEEP**                                  |
| ?   | still not get it, explain more: why it overlap my stack. what is dispatcher do?                                    | **writ-pre-write-dispatch** | PreToolUse[Write/Edit]  | Consolidated dispatcher (replaces gate-approval + final-gate + pretool-rag). On repeated gate violation emits `ask`; on hard gate failure emits `deny`. Also returns RAG metadata. | 🛑 BLOCK (deny/ask) + 💉 INJECT                        | L3    | **drop** (gate logic overlaps your stack) |

### Group 2 — Workflow / mode / phase gates (Process Keeper enforcement)

| ✓   | Note                                                                                                                                                                                                                          | Hook                      | Event                    | What it does (detail)                                                                                                                                          | Effect on agent            | Layer | Rec                                            |
| --- | ----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | ------------------------- | ------------------------ | -------------------------------------------------------------------------------------------------------------------------------------------------------------- | -------------------------- | ----- | ---------------------------------------------- |
| n   |                                                                                                                                                                                                                               | **auto-approve-gate**     | UserPromptSubmit         | Pattern-matches "approved"-style phrases; does NOT advance phase — emits an *ask-directive* steering you to the `/writ-approve` tool (tool-confirmed advance). | 💉 INJECT (steer)          | L3    | drop                                           |
| n   |                                                                                                                                                                                                                               | **inject-tier-workflow**  | PostToolUse[Bash]        | Detects `mode set`/`tier set` Bash commands and immediately injects that mode's workflow instructions (closes mid-turn timing gap).                            | 💉 INJECT                  | L3    | drop (you have modes via skills)               |
| ?   | can we rework that to work with our workflow? the  plan quality review is really cool idea                                                                                                                                    | **validate-exit-plan**    | PreToolUse[ExitPlanMode] | Validates `plan.md` quality before allowing exit from plan mode; `deny` if it fails.                                                                           | 🛑 BLOCK                   | L3    | drop (overlaps `/build-pipeline`+ExitPlanMode) |
| ?   | very interesting, tell me more: who do the spec review? does that mean review the spec quality or review if the spec is followed thru carefully by implementor? in our workflow, it is the plan, so we might adapt it to plan | **writ-sdd-review-order** | PreToolUse[Task]         | Enforces spec-review-before-code-quality-review ordering (ENF-PROC-SDD-001); `deny` if out of order.                                                           | 🛑 BLOCK                   | L3    | drop                                           |
| y   |                                                                                                                                                                                                                               | **writ-worktree-safety**  | PreToolUse[Bash]         | Blocks Bash that creates a git worktree without gitignore safety (ENF-PROC-WORKTREE-001).                                                                      | 🛑 BLOCK                   | L2?   | **discuss** (cheap safety win)                 |
| ?   | tell me more. what violation? what exit 2?                                                                                                                                                                                    | **enforce-violations**    | Stop                     | In Work mode, if violations are pending, `exit 2` forces the agent to continue and address them before stopping.                                               | 🛑 BLOCK (forces continue) | L3    | drop                                           |

### Group 3 — File-write validation gates

| ✓   | Note                                                                                                        | Hook                         | Event                   | What it does (detail)                                                                                                                                       | Effect on agent           | Layer | Rec                                         |
| --- | ----------------------------------------------------------------------------------------------------------- | ---------------------------- | ----------------------- | ----------------------------------------------------------------------------------------------------------------------------------------------------------- | ------------------------- | ----- | ------------------------------------------- |
| ?   | what postToolUse guard of mine? also, how the validate of this hook works? and what needed to unblock this? | **pre-validate-file**        | PreToolUse[Write/Edit]  | Validates file *content* before it's written; `deny` with reason if it fails.                                                                               | 🛑 BLOCK                  | L3    | drop (overlaps your PostToolUse guards)     |
| ?   | explain more, i dont get this yet. seems like creating tags/flag for other hooks?                           | **validate-rules**           | PostToolUse[Write/Edit] | Rule-validation; `exit 1` warn or `exit 2` **blocking** (only when an invalidate-gate signal is present).                                                   | 🛑 BLOCK (conditional)    | L3    | drop                                        |
| y   | Use this, tdd skill is not good at enforcing.                                                               | **validate-test-file**       | PreToolUse[Write]       | TDD assertion gate (ENF-PROC-TDD-001) — `deny` writing a test file lacking real assertions.                                                                 | 🛑 BLOCK                  | L3    | drop (your `/tdd-implement` owns this)      |
| ?   | might be useful? in terms of enforcing the template/section lists?                                          | **validate-design-doc**      | PreToolUse[Write]       | Design-doc quality gate; `deny` if a design doc is below bar.                                                                                               | 🛑 BLOCK                  | L3    | drop                                        |
| y   |                                                                                                             | **writ-memory-policy-guard** | PreToolUse[Write]       | Intercepts memory writes that would *weaken* an existing rule; `deny`.                                                                                      | 🛑 BLOCK                  | L2    | **KEEP** (anti-rationalization, no overlap) |
| ?   | explain more, i dont get this yet. seems like creating tags/flag for other hooks?                           | **validate-file**            | PostToolUse[Write/Edit] | General file lint; `exit 1` advisory warning only.                                                                                                          | 📝/⚠️ warn (non-blocking) | L3    | drop                                        |
| ?   | does it cost token? is the validation mechanical or LLM inference                                           | **validate-handoff**         | PostToolUse[Write/Edit] | Handoff-doc completeness; `exit 1` advisory.                                                                                                                | ⚠️ warn                   | L3    | drop (you have `/handoff`)                  |
| y   | sounds good, but walk me through the details, seems like a lot of building on this hook                     | **writ-quality-judge**       | PostToolUse[Write]      | On plan/design/test writes, emits a self-review directive; agent scores the artifact next turn and POSTs the score (enforced later by verify-before-claim). | 💉 INJECT (self-review)   | L2/L3 | **discuss**                                 |

### Group 4 — Test discipline

| ✓   | Note                                  | Hook                       | Event                   | What it does (detail)                                                              | Effect on agent             | Layer | Rec                                     |
| --- | ------------------------------------- | -------------------------- | ----------------------- | ---------------------------------------------------------------------------------- | --------------------------- | ----- | --------------------------------------- |
| ?   | explain more for me, still not get it | **writ-mark-pending-test** | PostToolUse[Write/Edit] | Marks edited src/test files (keyed on parent session) for an end-of-turn test run. | 🗃️ STATE                   | L3    | drop (pairs with run-pending)           |
| y   | explain more for me, still not get it | **writ-run-pending-tests** | Stop                    | Runs tests for marked files; silent on pass, one-line summary on fail (`exit 1`).  | ⚠️ warn (surfaces failures) | L3    | **discuss** (auto-test-on-stop is nice) |
| y   |                                       | **track-failed-writes**    | PostToolUseFailure      | Records failed Write/Edit `{file,reason,ts}` to cache + friction log.              | 📝 LOG                      | L1+   | keep (free telemetry)                   |

### Group 5 — Session / context lifecycle (instrumentation + RAG plumbing)

| ✓   | Note                                                                  | Hook                         | Event                         | What it does (detail)                                                                                                                      | Effect on agent             | Layer | Rec                     |
| --- | --------------------------------------------------------------------- | ---------------------------- | ----------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------ | --------------------------- | ----- | ----------------------- |
| y   |                                                                       | **writ-context-watcher**     | UserPromptSubmit + PreToolUse | Sums last-message token usage / `WRIT_CONTEXT_WINDOW_TOKENS`; proactive context-window pressure warnings.                                  | 💉 INJECT (warn near limit) | L1+   | keep                    |
| y   |                                                                       | **writ-cwd-changed**         | CwdChanged                    | Heuristically detects project *domain* from marker files in new cwd, stores `detected_domain`; RAG hook uses it as a `/query` domain hint. | 🗃️ STATE (sharpens RAG)    | L1    | keep                    |
| y   |                                                                       | **writ-instructions-loaded** | InstructionsLoaded            | Scans loaded CLAUDE.md for rule IDs; stores them so RAG won't re-inject rules already in context.                                          | 🗃️ STATE (dedup)           | L1    | keep                    |
| y   |                                                                       | **writ-precompact**          | PreCompact                    | Clears full rule objects from cache before compaction (shrinks footprint); keeps IDs for exclusion.                                        | 🗃️ STATE                   | L1    | keep                    |
| y   |                                                                       | **writ-postcompact**         | PostCompact                   | After compaction, clears loaded-rule IDs for current phase + resets budget so rules re-inject next turn.                                   | 🗃️ STATE                   | L1    | keep                    |
| y   | When did this trigger? close a chat? also what does the log used for? | **writ-session-end**         | SessionEnd                    | Rollup: auto-feedback (rule↔outcome correlation), coverage report, gate metrics, session totals → friction log.                            | 📝 LOG                      | L1+   | keep                    |
| y   |                                                                       | **friction-logger**          | Stop                          | Appends friction events (e.g. gate denied-then-approved) to `workflow-friction.log` each turn.                                             | 📝 LOG                      | L1+   | keep                    |
| y   |                                                                       | **writ-context-tracker**     | Stop                          | **No-op** — kept only for hook-registration compatibility; real work moved to session-end.                                                 | none                        | —     | keep (harmless) or drop |

### Group 6 — Subagent + anti-cheat

| ✓   | Note | Hook                         | Event                        | What it does (detail)                                                                                                                                     | Effect on agent           | Layer | Rec                                  |
| --- | ---- | ---------------------------- | ---------------------------- | --------------------------------------------------------------------------------------------------------------------------------------------------------- | ------------------------- | ----- | ------------------------------------ |
| y   |      | **writ-subagent-start**      | SubagentStart                | Creates an isolated session cache per worker; injects rules + state via `additionalContext` into the subagent.                                            | 💉 INJECT (into subagent) | L1    | keep (if you use subagents)          |
| y   |      | **writ-subagent-stop**       | SubagentStop                 | Logs subagent completion metrics to friction log.                                                                                                         | 📝 LOG                    | L1+   | keep                                 |
| y   |      | **writ-pressure-audit**      | SessionEnd                   | Summarizes session "pressure" metrics (quality-override count, verification-evidence count, review-ordering violations). Feature-flag gated.              | 📝 LOG                    | L2    | **KEEP** (anti-cheat signal)         |
| y   |      | **writ-verify-before-claim** | PreToolUse[TodoWrite] + Stop | Enforces verification-before-completion (ENF-PROC-VERIFY-001): `deny` marking a todo complete / stopping when claims lack recorded verification evidence. | 🛑 BLOCK                  | L2    | **KEEP** (you lack this; high value) |

### Blocking hooks — exact block / unblock conditions (verified against code 2026-06-21)

**Two cross-cutting facts:**
- **Master switch = Work mode.** 9 of 11 blocking hooks start with `is_work_mode "$SID" || exit 0` (`bin/lib/common.sh:46` — mode must equal `work`). If you never enter Writ Work mode, those 9 never block. Exceptions noted below.
- **"Feature-flag gated" in hook headers is STALE** — that flag was removed 2026-04-21 (`bin/lib/common.sh:39-41`). The real gate is Work mode.

| Hook                                       | Mode gate                        | 🛑 Blocks WHEN                                                                                                                                                                                                                                                                      | ✅ Unblocks WHEN                                                                                                                                      |
| ------------------------------------------ | -------------------------------- | ----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | ---------------------------------------------------------------------------------------------------------------------------------------------------- |
| **writ-verify-before-claim**               | Work only                        | TodoWrite sets a todo `status=completed` AND its id is **not** in session `verification_evidence`; OR an artifact has a Gate-5 quality score `<3` not `overridden`.                                                                                                                 | POST the check result to `/session/{sid}/verification-evidence` for that todo first; OR fix/override the low-scored artifact; OR leave Work mode.    |
| **enforce-violations** (Stop, `exit 2`)    | Work only                        | session cache `pending_violations` is non-empty at end of turn → forces Claude to continue.                                                                                                                                                                                         | resolve/clear `pending_violations`; OR non-Work mode.                                                                                                |
| **writ-worktree-safety**                   | Work only                        | Bash cmd contains `git worktree add` AND target is inside the repo AND (no `.gitignore` OR its top dir isn't matched by a `.gitignore` entry).                                                                                                                                      | add the worktree dir (e.g. `.worktrees/`) to `.gitignore`; OR target a path outside the repo; OR non-Work mode.                                      |
| **writ-sdd-review-order**                  | Work only                        | a `Task` dispatches a subagent whose type contains `code-review` AND `review_ordering_state[task].spec_reviewer_completed` ≠ true.                                                                                                                                                  | run spec-reviewer + record via `/session/{sid}/review-ordering` first; OR dispatch a non-review agent; OR non-Work mode.                             |
| **validate-test-file**                     | Work only (+ `prototype` bypass) | writing a source file (`py/js/ts/php/go/rs/java`) under `src\|lib\|app\|writ/` (tests/ exempt) AND no candidate test file with an assertion marker (`assert\|expect\|should\|test_`) exists.                                                                                        | create the expected `tests/test_X` with assertions; OR `session.mode=prototype`; OR write under `tests/`; OR non-Work mode.                          |
| **validate-design-doc**                    | Work only                        | writing `docs/**/specs/*-design.md` whose content is missing a required `##` section (Goal/Constraints/Alternatives Considered/Chosen Approach/Risks), OR any section `<50` words, OR has a placeholder (TODO/TBD/placeholder…), OR `<2` alternatives, OR Risks lacks "mitigation". | satisfy all checks (sections present, ≥50 words, no placeholders, ≥2 alternatives, risk+mitigation); OR non-Work mode.                               |
| **validate-exit-plan**                     | Work only                        | exiting plan mode while `plan.md` fails `_validate_phase_a` (missing `## Files` / `## Analysis` / `## Rules Applied` / `## Capabilities`).                                                                                                                                          | add the missing plan.md sections; OR non-Work mode. (On pass it still does NOT approve code writes — user must say "approved".)                      |
| **validate-rules** (PostToolUse, `exit 2`) | Work only                        | a sentinel `…/writ-validate-rules-invalidated-<sid>` exists (a prior `/analyze` phase-boundary finding routed to invalidate-gate). Per-write runs only WARN (`exit 1`).                                                                                                             | sentinel auto-consumed on read (next run clean); resolve the violations that invalidated the gate; OR non-Work mode.                                 |
| **writ-memory-policy-guard**               | **ALL modes**                    | a `Write` to `*/.claude/projects/*/memory/*` whose content matches a rule-weakening regex (skip verification/tests, "at face value", override/bypass `ENF-`/rule, PSR-003 phrasing) AND no override marker.                                                                         | add `explicit_rule_override: true` (YAML) or `override authorized by: <name>` (body); OR rewrite to not encode a bypass; OR write a non-memory path. |
| **pre-validate-file**                      | **ALL modes**                    | proposed content (written to a temp file) fails `bin/run-analysis.sh` with an `error`-severity finding (ENF-POST-007). Skips `scripts/seed_*.py` and unknown languages.                                                                                                             | fix content so static analysis passes; OR file is unknown-language / a seed script.                                                                  |
| **writ-pre-write-dispatch**                | server-side                      | server `POST /pre-write-check` returns `deny` (code write before gate approved) or `ask` (repeated gate violation). If server unreachable → allows (`exit 0`).                                                                                                                      | advance the gate (user "approved" / `/writ-approve`) so server returns `allow`.                                                                      |

> **Net for your stack:** keep the session OUT of Writ "Work mode" and only `writ-memory-policy-guard` + `pre-validate-file` + `writ-pre-write-dispatch` can ever block. The other 8 are inert unless you adopt Writ's mode system (Layer 3).

### Quick tally at recommended Layer 2 **KEEP (12):** all of Group 1 except pre-write-dispatch (3), writ-memory-policy-guard, writ-verify-before-claim, writ-pressure-audit, + Group 5 plumbing/telemetry (context-watcher, cwd-changed, instructions-loaded, pre/postcompact, session-end, friction-logger) + subagent pair + track-failed-writes. **DISCUSS (4):** writ-worktree-safety, writ-quality-judge, writ-run-pending-tests (+mark), writ-context-tracker. **DROP (rest):** Group 2 workflow gates + Group 3 write-validation gates that overlap your HITL `CLAUDE.md` / `/build-pipeline` / PostToolUse grep guards.

---

## Decision ledger — per-hook review table

> **Decision:** ✅ keep · ❌ drop · ⬜ undecided (has a user note, not yet walked one-by-one). **Your reasoning** = user's stated rationale; **My reasoning / pending** = AI analysis + deferred work. Layer = L2/L3 hybrid (Work mode adopted, D4-03). No-note `y`/`n` hooks from the appendix are recorded as the user's standing decision; noted hooks are walked individually before marking.

### Group 1 — RAG retrieval
| Hook | Decision | What it does (verified from code) | Your reasoning | My reasoning / pending |
|---|---|---|---|---|
| writ-rag-inject | ✅ | UserPromptSubmit: prompt→keywords, query `/query`, inject top rules each turn; auto-starts daemon. | Core RAG value. | The hook we edit for D4-02 (A-auto per-repo isolation). |
| writ-read-rag | ✅ | PreToolUse[Read], **review/debug only**: builds query from file path/role/name, injects per-file rules. Advisory, never blocks. | Wanted to know "file-context rules" — confirmed per-file (lang/role/name), not generic. | Cheap advisory; safe keep. |
| writ-posttool-rag | ✅ | PostToolUse[Write/Edit], **code files only** (not .md): keywords from written code → inject matching rules. Subagent-aware (suppresses orchestrator). | Want implementor to get rules during implementation. | Advisory **nudge** — can't change the write it follows; helps mid-impl (file 1 informs files 2,3), wasted on last write before subagent returns. Doc-reflection = quality-judge, not this. |
| writ-pre-write-dispatch | ✅ | PreToolUse[Write/Edit]: server `_can_write_check` → no-mode=deny, non-work=allow, work=deny until human "approved" advances plan then test gates; deny→ask after 2+ denials; subagents+plan.md bypass. | **Replace** our HITL + /build-pipeline plan/test gates with this (Writ=lock, build-pipeline=content). | Was "drop" pre-D4-03 (overlapped HITL); now the gate engine. Pending: retire overlapping skill gates. |

### Group 2 — Workflow / mode / phase gates
| Hook | Decision | What it does (verified) | Your reasoning | My reasoning / pending |
|---|---|---|---|---|
| auto-approve-gate | ❌ | UserPromptSubmit: pattern-matches "approved", only NUDGES to `/writ-approve` (does NOT advance). | Table `n`. | Defanged nudge; `/writ-approve` does the real advance. Drop. |
| inject-tier-workflow | ❌ | PostToolUse[Bash]: on `mode/tier set`, injects that mode's workflow text. | Table `n`. | We drive modes via skills (D4-03). Drop. |
| validate-exit-plan | ✅ | PreToolUse[ExitPlanMode], Work mode: **format** check — deny exit if plan.md missing `## Files/## Analysis/## Rules Applied/## Capabilities`. NOT substance quality. | "Plan quality review is cool — rework to our workflow." | Format-only (substance = quality-judge). Pending: **merge** our build-pipeline plan format with Writ's — both solid, cross-learn. |
| writ-sdd-review-order | ✅ | PreToolUse[Task], Work mode: deny code-quality reviewer before spec-compliance reviewer done (ENF-PROC-SDD-001). | Adapt spec≡plan; want forced review ordering. | Uses our writ-spec/code-quality-reviewer agents. Pending: methodology→agent prompts + lightweight orchestrator skill owns order+recording (no bare prompt). |
| writ-worktree-safety | ✅ | PreToolUse[Bash], Work mode: deny `git worktree add` when target project-local AND not gitignored. | Table `y`. | Cheap safety. Caveat: Work-gated → misses worktrees made before `mode set work`. |
| enforce-violations | ✅ | Stop hook, Work mode: `pending_violations` non-empty → `exit 2` forces continue+fix. Recorder/clear/analyze flow already ship. | Wanted to understand violation + exit 2. | "Can't stop with unfixed rule-breaks." Pairs verify-before-claim. Loop-risk if unclearable. |

### Group 3 — File-write validation gates
| Hook | Decision | What it does (verified) | Your reasoning | My reasoning / pending |
|---|---|---|---|---|
| pre-validate-file | ✅ | PreToolUse[Write/Edit], **ALL modes**: writes proposed content to a temp file, runs `bin/run-analysis.sh` static analyzers, **deny on error-severity** ([ENF-POST-007]). **Code files only** (.md skipped); skips `seed_*.py`. | **Really good — build/expand on this later.** | Pre-write real-analyzer gate; blocks the bad write *before* it lands (stronger than post-hoc greps). Overlaps ai_kms PostToolUse guards (can't diff from this repo). **EXPAND LATER — flagged.** |
| validate-rules | ✅ | PostToolUse[Write/Edit], Work mode: thin client → server `POST /analyze` (compliance engine). Per-write = warn + log `pending_violations` (exit 1). Phase-boundary = if a violated rule was loaded at plan time, call `invalidate-gate phase-a` (revoke plan approval) + write sentinel → exit 2 next run. **The enforcement brain** that FEEDS enforce-violations + the gate machine. | Keep — **will study this later.** | Pair/feeder for enforce-violations (✅) — without it that hook is inert. Heaviest L3 piece (needs `/analyze`, plan.md, loaded_rules). Risk: noisy `/analyze` can yank you back to planning mid-impl. |
| validate-test-file | ✅ | PreToolUse[Write], Work mode (prototype bypass): writing a **source** file under `src\|lib\|app\|writ/` → DENY unless a convention-named test file (`tests/test_X.py` etc.) exists containing an assertion marker (`assert\|expect\|should\|test_`). Hard mechanical test-first gate (ENF-PROC-TDD-001). | "Use this — tdd skill weak at enforcing." **Then adjust /tdd-implement to work with this.** | Real `deny`, not a nudge — the enforcement /tdd-implement lacks. Limits: (1) lexical-only → pairs with writ-quality-judge for *meaningful* assertions; (2) fixed test-path conventions + `src\|lib\|app\|writ` anchor → confirm/adapt per project layout so it doesn't false-negative. Pending: wire /tdd-implement to this hook's conventions. |
| validate-design-doc | ✅ | PreToolUse[Write], Work mode, path `docs/**/specs/*-design.md`: mechanical template gate — DENY unless required sections present (`## Goal/Constraints/Alternatives Considered/Chosen Approach/Risks`), each ≥50 words, no placeholders (TODO/TBD/…), ≥2 alternatives, Risks has "mitigation". | Useful for enforcing template/section lists. **Adapt to our design+specs+research+plan templates.** | Anti-boilerplate floor; overlaps quality-judge (mechanical vs LLM, complementary). **Dead until adapted** — path glob (ours = `docs/AI_artifacts/{1_design,2_specs,3_research,4_plans}/`) AND section list must match our /build-pipeline templates or it never fires. Pending: adapt path + per-artifact section lists. |
| writ-memory-policy-guard | ✅ | PreToolUse[Write], **ALL modes**: deny a memory write that weakens an existing rule (rule-weakening regex) unless override marker present. | Table `y`. | Anti-rationalization, no overlap with our stack; ALL-modes. Keep. |
| validate-file | ✅ | PostToolUse[Write/Edit], ALL modes, code files only: re-runs `bin/run-analysis.sh` on the WRITTEN file; records `--add-file-result FILE pass/fail` (feeds session-end coverage report); `exit 1` advisory warn (non-blocking). | Keep — useful telemetry. | Analysis half **duplicates pre-validate-file** (same engine; 2× analyze per write) — unique value is the coverage record + non-blocking second look. Kept for the telemetry. |
| validate-handoff | ✅ | PostToolUse, only on `.claude/handoffs/slice-*.json`: **mechanical** JSON-schema check (required keys, non-empty files, slice int, no "I cannot verify", open_items need justification); `exit 1` advisory. **Zero LLM / ~zero tokens** (fail emits a few error lines). | Keep — **adapt to our /handoff.** | Validates Writ's slice-JSON handoff format, which we don't produce (our /handoff = markdown) → **inert until adapted** (path + schema rewritten to our /handoff). Pending: adapt. |
| writ-quality-judge | ✅ | PostToolUse[Write], Work mode: on plan/design/test writes emits self-review directive + rubric; agent scores & POSTs; enforced by verify-before-claim. | "Sounds good — walk me through." | Rubrics are the asset (anti-boilerplate / anti-mock). Teeth need verify-before-claim. |

### Group 4 — Test discipline
| Hook | Decision | What it does (verified) | Your reasoning | My reasoning / pending |
|---|---|---|---|---|
| writ-mark-pending-test | ✅ | PostToolUse[Write/Edit], Work mode: queue builder — appends edited src/test file paths to `cache/<parent-sid>/pending-tests.txt` (parent-session keyed, subagent-safe). No test run. | Keep (pair). | Half of a pair; feeds run-pending. Path mapping config-driven (`test_paths.py` + `.claude/writ.json`). |
| writ-run-pending-tests | ✅ | Stop hook, Work mode: executor — resolves marked files → test files, groups by runner (pytest/phpunit/go test), runs (60s/runner timeout), clears marker; silent on pass, one-line stderr on real failure (`exit 1`, advisory). | Keep, **and enhance** (below). | Auto regression-catch at turn-end; cost = tests run every Work-mode Stop (latency if slow suite). **ENHANCEMENT (deferred dev build, NOT config tweak): enhance `test_paths.py` with CodeGraph — on each write/edit, `codegraph_callers`/`codegraph_explore` to compute the BLAST RADIUS (all sources+tests the change affects), queue that holistic set → (a) run affected tests/sources, (b) dispatch a subagent for precision review of the affected places. Caveat: a Stop hook can't directly dispatch — it injects a directive for the main thread to dispatch; and transitive-caller test sets can be large → cap/scope.** |
| track-failed-writes | ✅ | PostToolUseFailure: records failed Write/Edit `{file,reason,ts}` to cache + friction log. | Table `y`. | Free telemetry, zero behavior change. Keep. |

### Group 5 — Session / context lifecycle
| Hook | Decision | What it does (verified) | Your reasoning | My reasoning / pending |
|---|---|---|---|---|
| writ-context-watcher | ✅ | UserPromptSubmit+PreToolUse: token usage vs window → context-pressure warnings. | Table `y`. | Useful, low cost. Keep. |
| writ-cwd-changed | ✅ | CwdChanged: detects project domain from marker files, stores `detected_domain` for RAG hint. | Table `y`. | Sharpens RAG. Keep. |
| writ-instructions-loaded | ✅ | InstructionsLoaded: scans loaded CLAUDE.md for rule IDs → RAG won't re-inject them. | Table `y`. | Dedup. Keep. |
| writ-precompact | ✅ | PreCompact: clears full rule objects before compaction, keeps IDs for exclusion. | Table `y`. | Footprint shrink. Keep. |
| writ-postcompact | ✅ | PostCompact: clears loaded-rule IDs + resets budget so rules re-inject next turn. | Table `y`. | Keep. |
| writ-session-end | ✅ | SessionEnd (fires once at session close, 1.5s, all modes): 4 rollups — auto-feedback (correlate in-context rules ↔ analysis outcomes, POST), coverage report, gate metrics, session totals → `workflow-friction.log`. | Keep. | Pure telemetry + the **rule-learning loop** (auto-feedback nudges `times_seen_positive/negative` → feeds ranking/promotion). Zero in-session behavior change, ~free. friction log powers analyze-friction/benchmarks. |
| friction-logger | ✅ | Stop: appends friction events to `workflow-friction.log` each turn. | Table `y`. | Telemetry. Keep. |
| writ-context-tracker | ✅ | Stop: **no-op** (kept for hook-registration compatibility). | Table `y`. | Harmless; keep for registration. |

### Group 6 — Subagent + anti-cheat
| Hook | Decision | What it does (verified) | Your reasoning | My reasoning / pending |
|---|---|---|---|---|
| writ-subagent-start | ✅ | SubagentStart: per-worker isolated cache; injects rules+state into the subagent. | Table `y`. | Keep (we use subagents). |
| writ-subagent-stop | ✅ | SubagentStop: logs subagent completion metrics. | Table `y`. | Telemetry. Keep. |
| writ-pressure-audit | ✅ | SessionEnd: summarizes pressure metrics (quality-override, verification-evidence, review-order violations). | Table `y`. | Anti-cheat signal. Keep. |
| writ-verify-before-claim | ✅ | PreToolUse[TodoWrite]+Stop, Work mode: deny marking a todo complete / stopping when claims lack recorded verification evidence (ENF-PROC-VERIFY-001). | Table `y`. | High value — we lack this; enforces quality-judge scores + completion claims. Keep. |

---

## Phase 4 — Adaptation work plan (ordered by dependency)

> Only hooks/tasks that need WORK are listed. **Kept as-is, no adaptation:** writ-read-rag, writ-posttool-rag, writ-memory-policy-guard, writ-worktree-safety, enforce-violations, validate-file, track-failed-writes, all Group 5 telemetry (context-watcher, cwd-changed, instructions-loaded, pre/postcompact, session-end, friction-logger, context-tracker), subagent-start/stop, pressure-audit, verify-before-claim, validate-rules (study-only, works once `/analyze` runs). Do top-down — later rows assume earlier rows landed.

| # | Item (hook / combo / task) | What it does | What to adapt | Combo / depends on |
|---|---|---|---|---|
| 1 | **writ-rag-inject → A-auto** (D4-02) — ✅ **DONE + smoke-tested** (branch `phase4-adaptation`) | per-repo daemon: prompt→RAG inject each turn + daemon auto-start | DONE: per-repo port + repo-root derivation **centralized in `common.sh`** (cksum, env-override-wins) so ALL hooks inherit one port — the original "3 edits" scope was insufficient (5 hooks + `_writ_session` hardcoded 8765). rag-inject: `cd "$WRIT_REPO_ROOT"`, URLs+per-port lock from inherited `WRIT_PORT`. Verified: this repo→9041, deterministic, override + isolation + inheritance all pass. **✅ LIVE SMOKE-TEST PASSED (2026-06-21):** daemon up on 9041 (CWD=repo root), `/health` `rule_count:276 mandatory:30`, `/query` returns ranked rules ~8ms; **cold-start from disk RDB also 276** (persistence confirmed). All test daemons/redis stopped, state clean. | **FOUNDATION** — every server hook needs the daemon per-repo. No deps. |
| 2 | **Mode auto-switch wiring** (D4-03) — ✅ **DONE + tested** | our skills set Writ mode on entry (deterministic, not heuristic) | DONE: in-repo helper **`bin/writ-mode-set.sh <mode>`** (resolves session-id from `/tmp/writ-current-session` + per-repo port via `common.sh`; verifies via read-back; accepts only server `VALID_MODES` = conversation/debug/review/work — `prototype` is NOT settable). Guarded one-liner wired into **6 GLOBAL skills** (`~/.claude/skills/`, NOT in this repo's git): `grill`+`think-with-me`→conversation, `tdd-implement`+`subagent-driven-development`+`build-pipeline`(at plan-transition)→work, `review-implementation`→review. One-liner `bash "$(git rev-parse --show-toplevel)/bin/writ-mode-set.sh" <m> 2>/dev/null \|\| true` **no-ops outside a Writ repo** (verified). **Mapping changes from original plan:** `/code-review` is a 3rd-party plugin (not ours) → review-mode attached to our `/review-implementation` instead; `/build-pipeline` writes no code → work-mode armed at its plan-transition; added `/subagent-driven-development`. **Also fixed (D4-02 fallout):** `writ-approve.md` + template hardcoded `:8765` → now `source common.sh` for per-repo `$WRIT_SESSION_BASE` + read session-id file. | **FOUNDATION** — every Work-gated hook + the gate machine is inert without it. Touches OUR skills (global) + in-repo helper/command. No Writ-core. Dep: 1. |
| 3 ✅ **DONE 2026-06-21** | **Path / template batch** — quality-judge · validate-design-doc · validate-handoff · validate-test-file · mark/run-pending | these are INERT until their path globs / section lists / test conventions match OUR artifacts | quality-judge: path classify → `docs/AI_artifacts/{4_plans,1_design}` + `tests/`; validate-design-doc: path glob + REQUIRED sections → our design/spec/research/plan templates; validate-handoff: path+schema → markdown `/handoff`; validate-test-file: test-path conventions + `src\|lib\|app` anchors → our layout; mark/run: `.claude/writ.json` test-path config | Makes the gates fire on OUR files. Mostly Work-gated → dep: 2. Independent edits — **batch**. |
| 4 | **Gate reconciliation** — validate-exit-plan + writ-pre-write-dispatch | Writ's plan→test→code gate machine (the mechanical lock) | validate-exit-plan: **merge** our `/build-pipeline` plan format ↔ Writ's `## Files/## Analysis/## Rules Applied/## Capabilities`; pre-write-dispatch: **retire** our HITL + `/build-pipeline` plan/test gates so Writ is the single lock | **GATE-STACK combo** with validate-rules + enforce-violations (record→force-fix) and quality-judge + verify-before-claim (score→enforce). Behavior-replacing → test carefully. Dep: 2, 3. |
| 5 | **Review flow** — writ-sdd-review-order (+ 2 reviewer agents + orchestrator skill) | forces spec/plan-compliance review BEFORE code-quality review | merge `/review-implementation` methodology INTO `writ-spec-reviewer` + `writ-code-quality-reviewer` agent prompts; build a thin **orchestrator skill** = dispatch spec→record via `POST /session/{sid}/review-ordering`→dispatch quality. No bare "review it" prompt. | **3-part combo**: hook + 2 agents + skill. Dep: 1, 2. |
| 6 | **4A / 4B / 4C — author project rules into the graph** (D4-01) | constraints / ADRs / tech-debt as graph rule-nodes (no hand-maintained flat docs) | decide node-type mapping (C-NN→Rule? ADR→Rule + `SUPERSEDES`? tech-debt→friction pattern vs one-off?); rewire our input skills to write into the graph (`writ propose`/CLI); keep flat docs as **exports only** | Dep: 1 (daemon + graph). Independent of the gate work — **parallel-able after step 1**. Node mapping still OPEN (see "Open / not yet decided"). |
| 7 | **Enhancements (deferred DEV — not config)** — pre-validate-file · run-pending-tests | beyond current behavior | pre-validate-file: **expand on** (flagged "build on later") + reconcile vs ai_kms PostToolUse guards; run-pending: **CodeGraph blast-radius** → query affected sources+tests, run them, inject a directive for the main thread to dispatch a precision-review subagent (cap transitive sets) | Real new dev, not a path tweak. Dep: 1-3. Do last. |

---

## Handoff — next AI starts here

**Where we are:** Phase 4 adaptation **implementation** in progress on branch `phase4-adaptation` (off `main`). Hook decisions all locked (ledger above: 31 keep / 2 drop). Working the ordered **Adaptation work plan** (table above). **Work-plan #1 + #2 DONE + tested. #2 then RE-DONE under the plugin model (2026-06-21, see "Plugin-model consolidation" below). Next = #3.**

**⚠️ Distribution model LOCKED 2026-06-21 — PLUGIN model (supersedes the earlier hand-copy approach).** Writ ships as ONE Claude Code plugin (manifest `.claude-plugin/plugin.json`): commands + agents + hooks + `bin/` travel via `claude plugin install`; per-repo isolation is DATA-only (A-auto daemon+graph per repo) — **no Writ source copied into other repos.** The repo (falkor-writ) is the single version-controlled source; a new machine runs the install script once. The earlier AI scattered files into global `~/.claude/{skills,commands}` with no VC — that was the dumpster fire; this consolidation fixes it.

**Plugin-model consolidation (what changed this session):**
- **6 user skills are now version-controlled in-repo** at `skills/<name>/` (grill, think-with-me, tdd-implement, subagent-driven-development, build-pipeline, review-implementation). These are the USER's own skills (predate Writ; their legacy source `~/01_all_projects/vibe-coding/skill_library/` is **left untouched per user** — Writ is canonical going forward). Each got a `version:` frontmatter field.
- **Skills install via `scripts/bootstrap-plugin.sh` step 6b** — version-gated: install if missing, upgrade only when in-repo `version:` is newer, else leave untouched (local edits survive). Installed as PLAIN skills (`~/.claude/skills/<name>`, bare names `/grill` not `/writ:grill`).
- **Commands ride the plugin** from `.claude/commands/`: `write-*` → renamed **`writ-*`** (writ-chat/debug/review/work) + `writ-approve`. Deleted the `templates/commands/` crutch + obsolete `scripts/install-user-commands.sh` + global `~/.claude/commands/write-*` strays.
- **Helper path resolution fixed.** The old one-liner `$(git rev-parse --show-toplevel)/bin/writ-mode-set.sh` only worked INSIDE falkor-writ (other repos lack `bin/`). Now both skills + commands resolve via `WR="${CLAUDE_PLUGIN_ROOT:-$(cat "${CLAUDE_PLUGIN_DATA:-$HOME/.cache/writ}/plugin-root")}"` → `$WR/bin/writ-mode-set.sh`. `CLAUDE_PLUGIN_ROOT` is set for plugin commands but UNSET in standalone-skill bash, so bootstrap writes a **`plugin-root` marker** (`$WRIT_DATA/plugin-root`) as the fallback. `common.sh` still derives the per-repo port from the CWD's git toplevel, so isolation holds.
- **Plugin NOT yet registered/installed** (writ absent from `~/.claude/plugins/installed_plugins.json`; it's been running dormant via repo-local `.claude/`). New-machine sequence: `claude plugin marketplace add <repo>` + `claude plugin install writ@writ`, THEN `bash $(claude plugin path writ)/scripts/bootstrap-plugin.sh`. Registration left as a documented prerequisite (not auto-run by bootstrap — chicken/egg).

**Done:** Work-plan **#1 (A-auto, D4-02)** — per-repo port + repo-root derivation centralized in `bin/lib/common.sh` (cksum of git toplevel, `WRIT_PORT` env override wins); `writ-rag-inject.sh` daemon `cd "$WRIT_REPO_ROOT"` + per-port lock. Verified by logic tests (this repo→9041). **✅ Live daemon smoke-test PASSED 2026-06-21** (9041, rule_count 276, query ranked ~8ms, cold-RDB-reload 276). **Committed** as `1fec5b6`.

**⚠️ Incident during smoke-test (resolved):** 5 orphan `redis-server` from prior runs were piled on the shared socket `/tmp/writ-2d024a5544a9/redis.sock` (the documented CLAUDE.md gotcha). First daemon attach hit an empty orphan → `rule_count:0`; its shutdown BGSAVE clobbered `.writ/graph.db` to an empty-graph RDB. Recovered by killing all writ-socket redis + clearing stale socket/lock + **`writ import-markdown bible`** (342 nodes / 286 Rule / 174 edges re-seeded — D4-01 bible-as-seed path works). graph.db is gitignored/re-creatable, so no data loss of record. **Lesson for any future daemon work: kill orphan `redis-server unixsocket:/tmp/writ-*` + `rm` stale socket/lock BEFORE starting, or you attach to an empty orphan and a shutdown-save can clobber the on-disk graph.**

**#2 — mode auto-switch wiring (D4-03): ✅ DONE + tested, then RE-DONE under the plugin model (see "Plugin-model consolidation" above — that is now authoritative; the paragraph below is the original hand-copy approach, SUPERSEDED).** Committed as `7b697e5` + `3396885`; the plugin-model rework is uncommitted on top. _Original:_ In-repo helper `bin/writ-mode-set.sh` + guarded one-liner in 6 global skills (`~/.claude/skills/`, OUTSIDE this repo's git — see work-plan row #2 for the list/mapping) + writ-approve `:8765`→per-repo fix. Both one-liner paths verified (sets mode in-repo / no-op in `/tmp`). **Manual override:** 4 slash commands `/write-{chat,debug,review,work}` call the same helper. Installed **GLOBALLY** at `~/.claude/commands/` (active in every repo, no-op outside Writ via the guard) for consistency with the global auto-switch skills; **`templates/commands/write-*.md` is the version-controlled source** (the global copies are NOT tracked here — re-install via `cp templates/commands/write-*.md ~/.claude/commands/` if reset). **Vocab:** user-facing mode name is **`chat`** (shorter); the helper maps `chat`→server `conversation` (server VALID_MODES unchanged). **Work-at-design: DEFERRED** — work mode stays at build-pipeline's plan-transition only; revisit enabling it at the design step once `validate-design-doc` is adapted to our templates (#3). **⚠️ Global skill edits are NOT version-controlled here** — if you reinstall/reset `~/.claude/skills`, re-apply them (each = a "Step 0 — Set Writ mode" block running the guarded one-liner; grill/think-with-me use `chat`).

**#3 — path/template batch: ✅ DONE 2026-06-21.** Decisions: (a) **path convention standardized on `docs/AI_artifacts/{0_draft,1_design,2_specs,3_research,4_plans}`** — build-pipeline skill repointed (18 path refs; research 2.5→3, plans 3→4); (b) **config-driven artifact paths** — new `bin/lib/artifact_paths.py` + `artifact-paths-defaults.json` (mirrors `test_paths.py`), per-repo override via `.claude/writ.json` "artifacts"; (c) **fixed design template** (chosen over relax) — required `## Summary/Constraints/Alternatives Considered(≥2)/Chosen Approach/Risks(+mitigation)/Open Questions`, written by build-pipeline design step + enforced by `validate-design-doc`; (d) **handoff rewritten for markdown** (chosen over drop) — `/handoff` now writes `.claude/handoffs/<slug>.md` with required `## Goal/State/Files Touched/Open Items/Suggested Skills`, `validate-handoff` rewritten to check that markdown (was slice-JSON). Also: `writ-quality-judge` repointed via classifier + **3× hardcoded `:8765` fixed** (D4-02 fallout) → `$WRIT_SESSION_BASE`; `/handoff` brought in-repo as 7th versioned skill (`skills/handoff/`); falkor-writ `.claude/writ.json` adds a `writ/`-package test pattern so mark/run-pending recognize the layout (defaults assume `src/`). **Auto-scaffold:** a SessionStart hook (`.claude/hooks/writ-scaffold-config.sh` + `bin/lib/scaffold_writ_json.py`, registered in `hooks/hooks.json`) creates `.claude/writ.json` for non-`src/` layouts on the first session in a repo — conservative (only a single flat Python package, never overwrites). The committed file then travels via git (machine-independent), so it scaffolds once per repo, not per machine. `validate-test-file` already fits (its `src|lib|app|writ` anchor + `tests/test_X.py` match our layout) — no change. Gate logic smoke-tested (BAD→errors, GOOD→PASS for design-doc + handoff); full end-to-end needs a live work-mode daemon. **Next: #4 gate reconciliation**, then #5 review flow, #6 4A/4B/4C, #7 enhancements.

**How to work (learned this session):** read the actual hook/server code before explaining or editing (deny/allow logic for gates is server-side: `writ/server.py` `/pre-write-check` → `bin/lib/writ-session.py` `_can_write_check`); one item at a time; surface scope gaps (the "3 edits" undercount) instead of silently expanding; record decisions in the ledger + work-plan rows. Caveman mode on; no 5-Principles recital (waived). Commit/smoke-test only when the user asks.

**Open before relying on #1:** ~~(a) live daemon smoke-test~~ ✅ done; (b) commit (user must ask). See `STATE.md` "Pending edits" for the full deferred list (8 items).

---

_Last updated: 2026-06-21._
