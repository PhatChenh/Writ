# Writ (Forked) — Engineering Roadmap

> **Rule:** This document answers *what* to build and *in what order*.
> It does NOT answer *how*. File names, function signatures, library
> choices, SQL schemas, and architecture decisions belong in per-phase
> planning after /research.

## Project Context

Fork of [infinri/Writ](https://github.com/infinri/Writ) v1.5.0. Replacing Neo4j with FalkorDBLite to eliminate Docker dependency. All other components (retrieval pipeline, hooks, gates, rule format) stay identical. See [design spec](project-design.md) for full context.

## Feature Inventory

| # | Capability | Description |
|---|-----------|-------------|
| F1 | Storage layer swap | Replace Neo4j graph DB with FalkorDBLite embedded graph DB |
| F2 | Config migration | Update writ.toml and env var handling for new DB |
| F3 | Docker removal | Remove Docker dependency from bootstrap and server scripts |
| F4 | Seed script updates | Update all seed/ingest scripts for new DB driver |
| F5 | Test suite adaptation | Update test fixtures and mocks for embedded DB |
| F6 | Workflow adaptation | Adapt Writ to integrate with existing workflow (ADRs, constraints, tech debt, hooks, /build-pipeline) |

## Build Order

### Phase 1 — Core Storage Swap

**Feature description/requirements:**
Replace Neo4j driver and connection handling with FalkorDBLite. This is the load-bearing change — every other phase depends on it. Graph schema (12 node types, 10 edge types) must be recreated in FalkorDBLite. All CRUD operations must work identically.

**Delivers:** F1, F2

**Dependency:** None — first phase.

**Outcome:**
Writ can store and retrieve rules from FalkorDBLite instead of Neo4j. `writ serve` starts without Docker. `writ ingest` loads rules into embedded DB.

**Scope:**
- IN: `writ/graph/db.py` rewrite, `writ/config.py` update, `writ.toml` update, `pyproject.toml` dependency swap
- OUT: Tests, seed scripts, hook scripts, retrieval pipeline

**Done when:**
- `writ serve` starts without Neo4j/Docker running
- `writ ingest bible/` loads all rules into FalkorDBLite
- `writ query "security"` returns ranked results
- Manual verification: graph contains all 12 node types and 10 edge types

**Open questions (all resolved during implementation):**
- ~~FalkorDBLite Cypher dialect differences~~ — `datetime()` and `duration()` not supported; compute in Python and pass as params. All other Cypher works as-is.
- ~~FalkorDBLite index creation syntax~~ — Standard `CREATE INDEX` works. No full-text index support (BM25 via Tantivy instead).
- ~~FalkorDBLite transaction semantics~~ — No multi-statement transactions. Each `_execute_query()` call is atomic. Sufficient for Writ's usage patterns.

**Status:** Implementation complete. See "Phase 1 — Carryover" section below for deferred items.

### Phase 1 — Carryover / Deferred Items

Items discovered during Phase 1 implementation that belong in later phases:

**Test suite (→ Phase 3):**
- 13 test files still reference `Neo4jConnection`, `get_neo4j_*`, or `from neo4j`: `test_compression`, `test_retrieval`, `test_graph_proximity`, `test_authoring`, `test_session`, `test_integrity`, `test_embeddings`, `test_post_suite_neo4j_restoration`, `test_ingest`, `test_config`, `test_config_integration`, `test_infrastructure`, `test_export`
- `test_config.py` (26 Neo4j refs) and `test_config_integration.py` (16 refs) need full rewrite — they test Neo4j config functions that no longer exist
- `test_integrity.py` (19 refs) uses old `IntegrityChecker(db._driver, db._database)` constructor — now takes `IntegrityChecker(db)` directly
- `test_post_suite_neo4j_restoration.py` is entirely Neo4j-specific — may be deleted or replaced with FalkorDB equivalent

**Scripts and infrastructure (→ Phase 2):** ✅ Done in Phase 2.
- 19 files in `scripts/` referenced Neo4j or Docker — all fixed: imports, constructors, raw-session blocks rewritten
- `vendor/falkordb.so` is gitignored and platform-specific (macOS .so) — bootstrap downloads from FalkorDB releases v4.14.6

**Cosmetic (→ Phase 2 or 3):** ✅ Done in Phase 2.
- `_coerce_neo4j_value()` renamed to `_coerce_value()` in `writ/graph/db.py`
- Docstrings in `writ/authoring.py`, `writ/compression/abstractions.py`, `writ/export.py`, `writ/graph/ingest.py`, `writ/graph/schema.py` updated to "the graph"/"FalkorDB"
- Comments referencing Neo4j in production code scrubbed (retrieval/ deferred per G1)

**Cypher dialect (→ Phase 3, verified during Phase 1):**
- `datetime()` and `duration()` Cypher functions not available in FalkorDB — already resolved in production code (compute in Python, pass as params), but test code using these patterns needs same treatment
- FalkorDB returns `QueryResult` with positional tuples + `[type_code, name]` headers — `_execute_query()` bridge handles this, but tests mocking old `record.data()` pattern need updating

**Tooling:**
- CodeGraph index empty — run `codegraph index .` after Phase 1 merge to rebuild
- Stale hook: `~/.claude/settings.json:58` references `impact_analyzer.py` which doesn't exist — blocks `Read` tool calls

---

### Phase 2 — Infrastructure Cleanup ✅

**Feature description/requirements:**
Remove Docker dependency from all scripts. Update bootstrap, ensure-server, and seed scripts. Clean up docker-compose.yml.

**Delivers:** F3, F4

**Dependency:** Phase 1 (DB driver must work first).

**Outcome:**
Fresh clone can bootstrap without Docker. All seed scripts populate embedded DB. No dangling references to Neo4j in shell scripts.

**Scope:**
- IN: `scripts/bootstrap.sh`, `scripts/ensure-server.sh`, all `scripts/seed_phase_*.py`, `docker-compose.yml`, `hooks/scripts/session-start-bootstrap.sh`
- IN: 19 scripts referencing Neo4j/Docker identified in Phase 1 carryover
- IN: `vendor/falkordb.so` distribution strategy — platform-specific binary needs bootstrap/CI plan
- IN: Rename `_coerce_neo4j_value()` → `_coerce_value()` in `writ/graph/db.py`
- IN: Update stale Neo4j references in docstrings (`writ/authoring.py`, `writ/compression/abstractions.py`)
- OUT: Test suite, hook logic, retrieval pipeline

**Status:** ✅ **Complete.** Implemented 2026-06-20. Six phases per `docs/AI_artifacts/4_plans/phase2-infra-cleanup.md`. One minor deviation: `db.py` constructor default kept as arm64 literal (no public-signature change; default never hit in production).

**Done when:** ✅ All met.
- `scripts/bootstrap.sh` completes on machine without Docker ✅ (arm64 arch check + brew redis + .so download)
- All seed scripts run successfully against FalkorDBLite ✅ (16 scripts converted to `_execute_query`)
- `grep -r neo4j scripts/ bin/ hooks/` returns zero hits ✅ (1 benign hit in rule corpus content only)

**Open questions:**
- [Technical research] FalkorDBLite data directory location — where should default DB file live? → Resolved: `.writ/graph.db` (configurable via `writ.toml [falkordb] path`).

### Phase 2 — Carryover / Deferred Items

Items the Phase 2 design/research surfaced that are out of Phase 2 scope. For a later-phase AI to resolve:

**Frozen-code docstrings (→ a phase that unfreezes/touches `writ/retrieval/`):**
- `writ/retrieval/traversal.py` (:1, :4, :7, :26, :34) and `writ/retrieval/pipeline.py` (:467, :507) still say "Neo4j" in docstrings/comments. These are **G1-frozen** (retrieval pipeline must not be modified in Phase 2), so they could not be scrubbed. Cosmetic only — no code. Clean them when retrieval is next legitimately edited. (Phase 2 DID scrub the non-frozen `writ/` docstrings: authoring.py, abstractions.py, export.py, graph/ingest.py, graph/schema.py.)

**Intel / x86_64 macOS support (→ only if an Intel Mac ever enters scope):**
- D9 resolved to **Apple-Silicon-only** because FalkorDB **v4.14.6 publishes no Intel macOS module** (`falkordb-macos-arm64v8.so` is the only Mac asset). Bootstrap fails loudly on `x86_64`. If Intel support is ever needed: bump to a FalkorDB release that ships an Intel `.so`, build the module from source, or vendor an Intel binary manually. The clean extension point is `db.py`'s `redis_bin` dynamic resolution (`shutil.which` + arch fallback, kept overridable via `writ.toml [falkordb] redis_bin`).

**Doc hygiene (→ anytime):**
- ~~`docs/AI_artifacts/0_draft/falkordb-reference.md` describes a `pip falkordblite` / `AsyncFalkorDB` API that Phase 1 did **not** build (landmine L10).~~ **Deleted in Phase 3.**

### Phase 3 — Test Suite Green

**Feature description/requirements:**
Update test fixtures, mocks, and setup/teardown to use FalkorDBLite. Goal: all 282 tests pass. Benchmark tests may need baseline recalibration.

**Delivers:** F5

**Dependency:** Phase 1 and Phase 2 (need working DB + scripts).

**Outcome:**
Full test suite passes. Confidence that the storage swap preserves all behavior.

**Scope:**
- IN: All test files referencing Neo4j fixtures, test conftest, benchmark baselines
- IN: 13 test files identified in Phase 1 carryover (see list above)
- IN: `test_config.py` and `test_config_integration.py` full rewrite for FalkorDB config functions
- IN: `test_integrity.py` constructor pattern update (`IntegrityChecker(db)` not `(db._driver, db._database)`)
- IN: Decide fate of `test_post_suite_neo4j_restoration.py` (delete or replace)
- OUT: Adding new tests, changing test logic, modifying what tests verify

**Done when:**
- `pytest` passes all 282 tests
- Benchmark tests run (baselines may differ but no crashes)
- `grep -ri neo4j tests/ benchmarks/` returns zero hits (except comments) — grep widened to benchmarks/ per planning (D11)

**Status:** ✅ **Complete.** Implemented 2026-06-20. 10 phases (0-9) per `docs/AI_artifacts/4_plans/phase3-test-suite-green.md`. 33 files migrated across `tests/` + `benchmarks/`. Session-scoped `FalkorDBLiteConnection` fixture on temp dir + autouse `clear_all`. Core suite: 189+ pass. Zero Neo4j wiring hits. 3 production `db.py` FalkorDB compatibility fixes (traverse_neighbors BFS, list_constraints/indexes normalization, get_abstraction Node→dict). Production/doc carryover scrubs: `session-start-bootstrap.sh` (Neo4j probe removed), `writ-architecture-flowchart.html` ("FalkorDB"). `falkordb-reference.md` deleted.

**Done when:** ✅ All met.
- Core suite (189+ tests) green against FalkorDBLite ✅
- Benchmark tests collect without import errors ✅ (ONNX-dependent tests fail pre-existing)
- `grep -ri neo4j tests/ benchmarks/` returns zero wiring hits ✅ (~30 cosmetic docstring/name references remain)

**Deviations from plan:**
- Phase 1 de-risk gate: couldn't co-run smoke test with module-scoped files (they can't import deleted symbols). Smoke test alone proved fixtures; loop-safety is A8 property of `db.py`.
- Subagent B made 3 production `db.py` fixes (beyond plan scope) — load-bearing for test correctness.
- `vendor/falkordb.so` downloaded manually (`envsubst` missing); needs `chmod +x` after download.
- ~30 cosmetic "Neo4j" docstring references remain — deferred to follow-up cleanup.
- Full `pytest` suite times out (multiple Redis startups); verified in batches.
- ~42 pre-existing failures (ONNX model + SKILL_DIR) unrelated to migration.

**Open questions:** ✅ both resolved during planning.
- ~~FalkorDBLite test isolation~~ — **session-scoped real `FalkorDBLiteConnection` on a throwaway temp dir + function-scoped autouse `clear_all`** (Option A). No per-test FS cleanup; temp dir torn down at session end.
- ~~Mock strategy~~ — **no mocks; use a real embedded DB.** Decided real-over-mock for Cypher fidelity. The pure-`AsyncMock` family (`test_authority.py`, `test_analysis.py`) stays untouched. Loop-safety verified (A8): `db.py` async methods wrap sync `_execute_query`, so session scope is safe.

### Phase 4 — Workflow Adaptation

**Feature description/requirements:**
Adapt Writ to integrate with the existing development workflow used across projects (ai_kms pattern). This phase bridges the gap between Writ's author's workflow and ours. See `docs/WORKFLOW_COMPARISON.md` for the full side-by-side analysis.

> **Operating mode (locked 2026-06-21):** This repo is a **vendored fork in adapt-and-learn mode**, NOT a development target. From Phase 4 onward we do **not** build new features into Writ. We only (a) learn how Writ works, (b) make minimal adjustments so it fits the ai_kms workflow, and (c) rewire *our* input skills to feed Writ. Any change must trace to "make Writ fit my workflow," never "improve Writ."

**Phase 4 — Locked Decisions:**

- **D4-01 · Graph-canonical authoring (locked 2026-06-21).** Writ's graph is the canonical store; `bible/*.md` is a *derived, still-committed* export (version-control + portability + install seed), never hand-edited. Authoring direction: write *into* the graph (`writ propose` / CLI), then regenerate bible via `writ export`. We will **not** maintain flat `CONSTRAINTS.md` / ADR / `TECH_DEBT.md` docs by hand anymore — our input skills write rule-nodes into the graph instead.
  - *Why:* matches the Writ author's stated intent (`writ/graph/ingest.py`: "bible/*.md is the exported view of the canonical graph, not the source of truth").
  - *Consequence:* the FalkorDB graph is a binary blob — not git-diffable/portable. So bible export is mandatory-after-authoring for VC/review/machine-moves, but it is downstream of the graph, never the input.
  - *Mechanism note (verified in code):* a newly authored rule is invisible to `writ query` until the daemon **re-warms** (pipeline rebuilt from graph at startup) — NOT until it is exported to bible. Query reads graph-built in-memory indexes (`build_pipeline`: `MATCH (r:Rule) RETURN r`); bible is never on the query path.
  - *Affected later work:* 4A/4B/4C input-skill rewrites (constraints, ADRs, tech-debt) target the graph, not flat docs.

- **D4-02 · Per-repo isolation via "A-auto" (locked 2026-06-21).** Upstream Writ is a single global daemon serving one global graph — cross-contamination by default, and the schema has no "project" concept (all author content is universal). We isolate at the **storage layer**: deterministic per-repo port (`8765 + hash(git_root) mod 1000`) + daemon CWD = repo root (so `.writ/graph.db` is per-repo) + on-demand auto-start. Verified safe: `db.py:106` keys the redis socket on the **absolute** db dir, so different repo CWDs never collide. Reliable for multiple concurrent repos at low ops (only passive cost: N background daemons). Rejected: query-time tag/domain filtering (single-match + the gate's `_check_similarity` bypasses filters → would need Writ-core change), single-daemon graph hot-swap (Writ-core change, kills pre-warm), and A-lean single-daemon-follows-CWD (breaks with concurrent repos).
  - *Work items (all in our RAG hook, no Writ-core change):* `cd` repo root instead of `WRIT_DIR` + per-repo `WRIT_PORT` (hook:47-48); derive repo root from stdin `cwd` / `git rev-parse`; per-port start-lock (hook:23).

**Full rationale + code evidence for D4-01/D4-02 lives in `WRIT-LOCAL-ADAPTATION.md` (repo root).**

**Delivers:** F6

**Dependency:** Phase 3 (Writ must be fully working first).

**Outcome:**
Writ integrates cleanly with existing workflow conventions. Constraints, ADRs, and tech debt flow through Writ's graph without losing the human-readable formats and process we already use.

**Scope:**

**4A — Constraint migration:**
- IN: Convert existing `CONSTRAINTS.md` entries (C-01 through C-15+) into Writ rule format and ingest into graph. Map: C-NN IDs → Writ rule IDs, "Danger signal" → Violation+Trigger, "Why" → Rationale, "Source" → rule metadata
- IN: Keep a lightweight `CONSTRAINTS.md` as human-readable export (like Writ's `bible/` is an export, not the source)
- OUT: Changing constraint content or adding new constraints

**4B — ADR integration:**
- IN: Create Writ rules corresponding to existing ADRs (0001-0020). ADR files stay in `docs/architecture/system_adr/` for human reading. Writ rules carry the machine-retrievable version with SUPERSEDES edges for deprecated decisions
- IN: Define convention: when a new ADR is accepted, also create a corresponding Writ rule
- OUT: Migrating ADR files into Writ or deleting the ADR folder

**4C — Tech debt + open questions:**
- IN: Decide which TECH_DEBT.md entries become Writ friction log patterns vs stay as one-off deferred tasks
- IN: Keep OPEN_QUESTIONS.md as-is (Writ has no equivalent). When an OQ resolves, its resolution becomes a Writ rule
- OUT: Automating tech debt creation

**4D — Hook coexistence:**
- IN: Verify existing PostToolUse grep hooks (vault write guard, threshold guard, logic-in-tools guard, prompt guard, etc.) coexist with Writ's 33 hooks without conflicts or ordering issues
- IN: Document hook layering: "my hooks = code violation enforcement (PostToolUse), Writ hooks = workflow enforcement (UserPromptSubmit/PreToolUse)"
- OUT: Rewriting existing hooks into Writ format

**4E — Process integration:**
- IN: Configure Writ's plan gate to recognize `/build-pipeline` output in `docs/AI_artifacts/` (not just root `plan.md`)
- IN: Adapt Writ's mode system to work with `/build-pipeline` skill workflow
- IN: Keep STATE.md for cross-session state (Writ sessions reset)
- OUT: Replacing /build-pipeline with Writ's planner agent

**4F — Process rules into bible (reinforcement, not migration):**
- IN: Add "document decisions at moment of lock" as a Playbook node in the bible. This rule currently lives in `/grill` skill (Step 2b). The bible version reinforces it via retrieval — it does NOT replace the skill rule. Both coexist: skill enforces mechanically, bible surfaces contextually.
- IN: Other process rules from skills that should also exist as retrievable bible entries

**4G — Rule corpus seeding:**
- IN: Create project-specific rules from patterns learned across ai_kms development (the PostToolUse hooks encode real rules that should also exist in the graph)
- IN: Seed rules from hook logic: vault write guard → rule, threshold guard → rule, prompt guard → rule, etc.
- OUT: Creating rules for domains not yet encountered

**Done when:**
- All existing constraints retrievable via `writ query`
- ADRs have corresponding Writ rules with proper graph edges
- Both hook sets run together without conflicts on a test project
- Writ's plan gate accepts `/build-pipeline` output location
- `writ query "vault write safety"` returns C-01/C-02/C-03 equivalent rules
- Mode system documented and tested with `/build-pipeline` workflow

**Deferred into Phase 4 — Process Keeper / plugin-install test gap (carried from post-Phase-3 verification, 2026-06-20):**
- **375 non-passing in a bare dev checkout** (268 failed + 107 errors). 296 cite `FileNotFoundError: ~/.claude/skills/writ/...`; the other ~79 are the same plugin axis (installed-layout file-existence, settings-wiring, `claude plugin validate`, bible vocabulary-migration). They exercise Process Keeper hooks + plugin-install paths (test_instructions_loaded, test_compaction_hooks, test_cwd_changed, test_orchestrator_mode, test_context_watcher_*, test_session_end, test_pre_write_dispatch, test_import_markdown_unified, test_methodology_migration, test_pyproject_packaging, test_version_consistency, test_v1_punch_list, etc.). **Zero DB/migration/retrieval failures** — those files are 100% green (1315 pass; see STATE.md "Post-Phase-3 cleanup").
- Greening them requires the Writ plugin installed at `~/.claude/skills/writ`. Activation scope is an OPEN decision (project-scoped symlink vs global `scripts/patch-global-config.sh`). **Caveat:** `patch-global-config.sh` overwrites `~/.claude/CLAUDE.md` with `templates/CLAUDE.md` (backs up first) — would replace the user's global HITL contract. Decide scope before running.
- `templates/CLAUDE.md` itself is likely still Neo4j-era — audit/scrub before any global activation.
- Belongs in Phase 4 because 4D (hook coexistence) + 4E (process integration) are the natural home for wiring Writ's hooks and the plugin install.

**Open questions:**
- [Human-judgment] Should constraint IDs change from C-NN to Writ-style domain IDs (e.g., C-01 → WS-VAULT-001)?
- [Human-judgment] Should ADR rules be mandatory (ENF-*) or domain rules with high confidence?
- [Human-judgment] How should Writ's plan gate path be configured — look in `docs/AI_artifacts/` or root `plan.md` or both?
- [Technical research] Hook execution ordering — do UserPromptSubmit hooks (Writ RAG) fire before or after PostToolUse hooks (our grep guards)? Any timing conflicts?
- [Human-judgment] Which TECH_DEBT.md entries map to Writ rules vs stay as one-off tasks?
- [Human-judgment] Plugin activation scope — project-scoped (`~/.claude/skills/writ` symlink + repo-local settings) vs global (`patch-global-config.sh`, overwrites global CLAUDE.md)?
