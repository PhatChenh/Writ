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

**Scripts and infrastructure (→ Phase 2):**
- 19 files in `scripts/` reference Neo4j or Docker — all seed scripts, bootstrap, ensure-server, profile/instrument scripts need updating
- `vendor/falkordb.so` is gitignored and platform-specific (macOS .so) — needs distribution/bootstrap strategy for other platforms and CI

**Cosmetic (→ Phase 2 or 3):**
- `_coerce_neo4j_value()` function name in `writ/graph/db.py` still says "neo4j" — rename to `_coerce_value()`
- Docstrings in `writ/authoring.py` and `writ/compression/abstractions.py` still reference "Neo4j" — update to "FalkorDB" or generic "graph"
- Comments referencing Neo4j scattered throughout production code

**Cypher dialect (→ Phase 3, verified during Phase 1):**
- `datetime()` and `duration()` Cypher functions not available in FalkorDB — already resolved in production code (compute in Python, pass as params), but test code using these patterns needs same treatment
- FalkorDB returns `QueryResult` with positional tuples + `[type_code, name]` headers — `_execute_query()` bridge handles this, but tests mocking old `record.data()` pattern need updating

**Tooling:**
- CodeGraph index empty — run `codegraph index .` after Phase 1 merge to rebuild
- Stale hook: `~/.claude/settings.json:58` references `impact_analyzer.py` which doesn't exist — blocks `Read` tool calls

---

### Phase 2 — Infrastructure Cleanup

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

**Done when:**
- `scripts/bootstrap.sh` completes on machine without Docker
- All seed scripts run successfully against FalkorDBLite
- `grep -r neo4j scripts/ bin/ hooks/` returns zero hits (except comments noting the migration)

**Open questions:**
- [Technical research] FalkorDBLite data directory location — where should default DB file live?

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
- `grep -r neo4j tests/` returns zero hits (except comments)

**Open questions:**
- [Technical research] FalkorDBLite test isolation — can we create/destroy DBs per test without file system cleanup?
- [Technical research] Mock strategy — tests currently mock `neo4j.AsyncDriver`; need equivalent mock for `FalkorDBLiteConnection._execute_query()`

### Phase 4 — Workflow Adaptation

**Feature description/requirements:**
Adapt Writ to integrate with the existing development workflow used across projects (ai_kms pattern). This phase bridges the gap between Writ's author's workflow and ours. See `docs/WORKFLOW_COMPARISON.md` for the full side-by-side analysis.

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

**Open questions:**
- [Human-judgment] Should constraint IDs change from C-NN to Writ-style domain IDs (e.g., C-01 → WS-VAULT-001)?
- [Human-judgment] Should ADR rules be mandatory (ENF-*) or domain rules with high confidence?
- [Human-judgment] How should Writ's plan gate path be configured — look in `docs/AI_artifacts/` or root `plan.md` or both?
- [Technical research] Hook execution ordering — do UserPromptSubmit hooks (Writ RAG) fire before or after PostToolUse hooks (our grep guards)? Any timing conflicts?
- [Human-judgment] Which TECH_DEBT.md entries map to Writ rules vs stay as one-off tasks?
