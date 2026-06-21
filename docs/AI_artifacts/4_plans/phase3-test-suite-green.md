# Plan: Phase 3 — Test Suite Green
_Last updated: 2026-06-20_
_Status: [ ] pending_

_Spec: `docs/AI_artifacts/2_specs/phase3-test-suite-green.md` (components 1–9). Research: `docs/AI_artifacts/3_research/phase3-test-suite-green.md` (22 validated, 0 invalidated). Locked decisions: `docs/AI_artifacts/0_draft/phase3-test-suite-green.md` (D1–D11, L1–L9, F1–F5)._

> This plan owns HOW and the ordering. It references spec component IDs and does not restate the spec's Build/Done-when/file-inventory. Open the spec for those.

---

## Architecture

**Plain English.** Phases 1–2 swapped Writ's database from Neo4j (a Docker container) to FalkorDBLite (an embedded, file-based engine that runs out of a single `.so` file plus a local `redis-server`). Production already runs on the new engine. The *tests* were left behind: ~33 files across `tests/` and `benchmarks/` still import classes and config getters that were deleted, build connections to a database that no longer exists, or assert that Docker infrastructure (which Phase 2 deleted) is still present. Many of those files can no longer even load. This phase makes the suite green again **without changing what any still-valid test checks** — it is plumbing, not new behavior.

**The one new piece of infrastructure** is a small set of shared fixtures added to `tests/conftest.py` (spec Component 2). Today every database-touching test file builds its *own* connection to Neo4j from its own copy-pasted `NEO4J_URI/USER/PASSWORD` constants. The new design replaces all of that duplication with:
1. **One** real FalkorDBLite database, started **once** for the whole test run, living in a throwaway temp folder (so it never touches or locks the real `.writ/graph.db`).
2. A reset step that wipes that database clean before **every** individual test — automatically, so no test can forget.
3. A single named handle (`db`) that every database test asks for instead of building its own.

**Why this is safe (the load-bearing fact).** The database client's methods *look* asynchronous (`async def clear_all`, `async def close`) but underneath they call a fully **synchronous** redis client — `_execute_query` (`writ/graph/db.py:162`) has no `await` and binds to no event loop. Research (A8 deep-dive) confirmed the client contains zero asyncio primitives. This is *the* reason one shared session-scoped database can be safely awaited from the two test files that run on their own per-module timers (`test_graph_proximity.py`, `test_authoring.py`) without the classic "attached to a different loop" crash. **This safety is a property of `db.py` staying synchronous, not of the fixture design** — see the A8 CONSTRAINT note below.

**How it connects to existing code.** The shared fixtures conform to existing project conventions, not new ones:
- pytest-asyncio runs in **strict** mode (no `asyncio_mode` key in `pyproject.toml:122-127`), so async fixtures MUST be `@pytest_asyncio.fixture`, not `@pytest.fixture` — matching the existing live-DB fixtures (e.g. `test_integrity.py:53`, `test_authoring.py:26` with `loop_scope="module"`).
- The fixtures call the real, already-shipped config getters in `writ/config.py` (`get_falkordb_path/_graph/_module/get_redis_bin`) and the real connection class `FalkorDBLiteConnection` (`writ/graph/db.py:79`) — the same ones production callers use (`writ/cli.py:871-874`, `scripts/migrate.py:30-33`).
- The end-of-suite restoration hook `pytest_sessionfinish` (`tests/conftest.py:8`) is KEPT unchanged (it restores the *production* corpus, independent of the test DB) — only one stale comment is scrubbed.

**Components introduced and their extension posture:**
- The shared `db` fixture + session connection + autouse reset (Component 2) — `[extensible: config]`. The single seam for DB construction. Future per-worker DBs (for `pytest-xdist`) change only `conftest.py`; the one-lockfile-holder rule (`db.py:147`) blocks parallelism until each worker gets its own temp dir, but that is a later phase. No other file constructs a connection after this lands.

**No production source changes** except the two Phase-2-carryover scrubs folded into scope by D10 (the `session-start-bootstrap.sh` hook and the `writ-architecture-flowchart.html` doc). `writ/retrieval/` stays frozen (G1). `writ/graph/`, `writ/config.py` are read, not edited.

---

## Approach

Build the shared fixture FIRST and **prove** it green against the two module-scoped consumers with a throwaway smoke test before migrating anything else — research's explicit de-risking step (convert "should pass" to "does pass"). Then migrate the remaining ~30 files in independently-verifiable batches, each runnable green before the next starts, ordered so every batch's prerequisite already exists. End with one full-suite run plus benchmarks-no-crash plus a zero-hit `grep -ri neo4j tests/ benchmarks/`. Two batches (Component 8c) are folded into scope by D10 and touch one production script + one doc — those are called out for human review.

**A8 CONSTRAINT (plan note + TECH_DEBT candidate — not scaffolded per OQ-5).** The loop-safety that makes one session-scoped DB usable by module-scoped and function-scoped tests is an *implementation property of `db.py`*: its `async def` methods wrap the **synchronous** `_execute_query` (`db.py:162`), so the connection never binds an event loop. **If `db.py` is ever refactored to use a real async redis client (loop-bound transport), a session-scoped fixture consumed by module/function loops would immediately reintroduce "attached to a different loop" failures.** Record this as a constraint candidate (a future `docs/CONSTRAINTS.md` entry) and a TECH_DEBT candidate. Do NOT scaffold `CONSTRAINTS.md`/`TECH_DEBT.md` this phase (OQ-5 out of scope) — capture as this plan note only.

---

## Phases

### Phase 0 — Delete the misleading reference doc
**Goal**: Remove a fake-API doc so the implementer can't be misled into wrong wiring. (Implements spec **Component 1 / Batch 0**, D5/L10.)

**Design**: `docs/AI_artifacts/0_draft/falkordb-reference.md` describes a `pip falkordblite` / `AsyncFalkorDB` / `redislite.falkordb_client` API that Phase 1 never built (the real connection spawns a raw `redis-server` + vendored `vendor/falkordb.so`). Deleting it removes a trap before any wiring work begins.

**Steps**:
1. Delete `docs/AI_artifacts/0_draft/falkordb-reference.md`.
2. Confirm nothing imports/links it (grep the repo for the filename).

**Files to modify**:
- `docs/AI_artifacts/0_draft/falkordb-reference.md` — delete.

**Test criteria**:
- [ ] The file no longer exists on disk.
- [ ] `grep -rn "falkordb-reference" .` (excluding this plan + the spec/research/draft that name it historically) returns no live import/link.

**Status**: [ ] pending

---

### Phase 1 — Shared conftest fixtures + smoke test + module-scope proof (DE-RISK GATE)
**Goal**: One real test database, started once, wiped clean before every test, shared by name — proven green against the two module-scoped consumers BEFORE any other file is migrated. (Implements spec **Component 2 / Batch 1**.)

**Design (before → after)**:
- *Before*: ~10 files each build their own `FalkorDBLiteConnection` from their own `NEO4J_*` constants; the two module-scoped files run on per-module event-loop timers.
- *After*: `tests/conftest.py` owns three new fixtures (added alongside the existing data-dict fixtures `:51-115`, which stay verbatim):
  - **session connection** — `@pytest_asyncio.fixture(scope="session", loop_scope="session")`. Creates a unique session temp dir, builds `FalkorDBLiteConnection(<tmp>/graph.db, graph=get_falkordb_graph(), module_path=get_falkordb_module(), redis_bin=get_redis_bin())`, `yield`s it, then on teardown `await conn.close()` and removes the temp dir.
  - **autouse reset** — `@pytest_asyncio.fixture(autouse=True)` (function-scoped) depending on the session connection; `await db.clear_all()` before each test. Replaces the per-fixture `clear_all()` pairs the old `db()` fixtures each carried — no test can opt out.
  - **shared `db`** — yields the session connection. The 1-line interface every migrated file consumes.
- One stale comment in `pytest_sessionfinish` (`tests/conftest.py:44`, "Neo4j may not be running") is scrubbed to reference "the server"; the body is otherwise unchanged (KEEP per D4/OQ-4).

**Steps** (TDD: write the smoke test, watch it pass, then prove module-scope coexistence):
1. Add the three fixtures + scrub the `:44` comment in `tests/conftest.py`. Never `await _execute_query` (G4); only the public `async` methods (`clear_all`, `close`) are awaited.
2. Add a **throwaway** smoke test (temporary, deleted at the end of this phase — it is scaffolding, not a new permanent test, so it does not violate G3): test A requests `db`, writes a node, asserts it is present; test B asserts the graph is empty (proves the autouse reset ran between A and B).
3. Run `pytest <smoke>` — expect both pass; expect exactly ONE `redis-server` subprocess for the session; expect the temp dir gone afterward and `.writ/graph.db` untouched.
4. **DE-RISK GATE**: run `pytest <smoke> tests/test_graph_proximity.py tests/test_authoring.py` in ONE invocation. Expect NO `ScopeMismatch` / "attached to a different loop" error at module-fixture teardown. (Research A8 says this passes because the connection binds no loop; this step converts "should" to "does." `test_graph_proximity.py` / `test_authoring.py` still build their own connections at this point — that is fine; the gate proves the *session fixture coexists* with their module loops, not that they are migrated yet.)
5. Delete the throwaway smoke test once the gate is green.

**Files to modify**:
- `tests/conftest.py` — add 3 fixtures, scrub one comment.
- (temporary) a smoke-test file — added then deleted within this phase.

**Risks**:
- If the de-risk gate fails (loop error), STOP — do not migrate the other files. The fixture shape (loop scope) is wrong and must be fixed first. (Research rates this very low risk; the gate exists to catch a surprise, not because one is expected.)
- The ~5s redis startup happens once per session; if it exceeds the wait window on the dev box, the session fixture errors — that is a machine/env problem surfaced here, before 30 files depend on it.

**Test criteria**:
- [ ] `tests/conftest.py` imports cleanly.
- [ ] Smoke test passes: node written in test A is absent in test B (autouse reset proven).
- [ ] Exactly one `redis-server` subprocess for the session; temp dir gone after; `.writ/graph.db` untouched.
- [ ] `pytest <smoke> tests/test_graph_proximity.py tests/test_authoring.py` runs with no loop/scope error (DE-RISK GATE green).
- [ ] Smoke test deleted; conftest left with the 3 permanent fixtures only.

**Maps to**: P3-TEST-01, P3-TEST-03 (one startup, shared DB), P3-TEST-04 (no prod lock).

**Status**: [ ] pending

---

### Phase 2 — Config-test full rewrite
**Goal**: The two config-test files protect the database settings that actually exist, instead of skipping over deleted Neo4j settings. (Implements spec **Component 3 / Batch 2**, D6/L1. Self-contained — needs no DB fixture; independent of Phase 1, but sequenced here for a clean run order.)

**Design**: Both files currently top-skip via `try: from writ.config import get_neo4j_* … except ImportError: pytest.skip` — so they protect nothing. Rewrite them against the four real getters per the spec's behavior-parity mapping table (Component 3). Replace the skip guard with direct imports of the real getters.

**Steps** (TDD RED→GREEN: the rewritten tests fail against missing assertions, then pass against the real getters):
1. `tests/test_config.py`: replace `[neo4j]` fixtures with `[falkordb]` (path/graph/module); rewrite default + override tests against `get_falkordb_path/_graph/_module` → `DEFAULT_FALKORDB_*`; add `get_redis_bin` coverage: (a) explicit `redis_bin` override wins, (b) `shutil.which("redis-server")` result returned, (c) arm64 Homebrew default `/opt/homebrew/opt/redis/bin/redis-server`, (d) **x86_64 raises `RuntimeError`** — assert the raise via `monkeypatch`/patch on `platform.machine` + `shutil.which` (G6, do NOT skip). KEEP the `get_hnsw_cache_dir` and `load_config` tests verbatim (unchanged getters). Re-point `TestConsumers` to the falkordb getters.
2. `tests/test_config_integration.py`: re-point `[neo4j]` fixtures to `[falkordb]`; retire the credential-literal assertions per Component 8 / OQ-2 (the broken `DEFAULT_NEO4J_PASSWORD` import currently breaks collection). See Phase 7 for the credential-scan meta-test treatment.
3. Run both files — expect no skip, all getters exercised including the x86_64 raise.

**Files to modify**:
- `tests/test_config.py` — full rewrite (keep hnsw + load_config tests).
- `tests/test_config_integration.py` — re-point fixtures; credential-scan handled in Phase 7.

**Risks**:
- The x86_64 raise path must be patched, not run on real hardware (dev box is arm64). Wrong patch target = test silently never hits the raise. Patch `platform.machine` AND `shutil.which` together.

**Test criteria**:
- [ ] Both files collect with NO skip.
- [ ] All four getters exercised; the x86_64 `RuntimeError` path asserted (not skipped).
- [ ] `get_hnsw_cache_dir` tests pass unchanged.
- [ ] No `get_neo4j_*` / `DEFAULT_NEO4J_*` / `[neo4j]` reference remains in either file.

**Maps to**: P3-TEST-05.

**Status**: [ ] pending

---

### Phase 3 — Top-level live-DB fixture files
**Goal**: Files that declare their own top-level `db()` fixture inherit the one shared `db` instead. (Implements spec **Component 4 / Batch 3**. Depends on Phase 1.)

**Design**: For each file: delete the local `db()` fixture, delete the `NEO4J_URI/USER/PASSWORD` constants, delete the dead imports (`Neo4jConnection`, `get_neo4j_*`), repoint type hints `db: Neo4jConnection` → `db: FalkorDBLiteConnection`. The file then receives `db` from conftest. Where construction is inline, replace with the shared `db` fixture.

**Steps** (migrate and verify ONE file at a time — never batch the run):
1. `tests/test_infrastructure.py` (constants `:19-21`; local fixture `:27`) → migrate, run, green.
2. `tests/test_authoring.py` (constants `:21-23`; module-scoped fixture `:26` → `:31`) → migrate, run, green. (This is one of the two module-scope files the Phase-1 gate already proved coexist with the session DB.)
3. `tests/test_ingest.py` (constants `:23-25`; fixture `:289` → `:291`) → migrate, run, green.
4. `tests/test_graph_proximity.py` (constants `:25-27`; module-scoped fixtures `:37,63,70,77` → `:40`) → migrate, run, green. **Module-scope caveat**: confirm the session-scoped shared `db` satisfies its `scope="module", loop_scope="module"` consumers (Phase-1 gate already de-risked this; if a fixture genuinely needs module scope, keep a thin module-scoped wrapper that yields the shared connection rather than re-building one).
5. `tests/test_retrieval.py` (constants `:28-30`; module-scoped fixtures `:33,93` → `:49`; inline `:248,258`) → migrate (swap inline construction to the shared `db`), run, green. Same module-scope caveat.

**Files to modify**:
- `tests/test_infrastructure.py`, `tests/test_authoring.py`, `tests/test_ingest.py`, `tests/test_graph_proximity.py`, `tests/test_retrieval.py`.

**Risks**:
- The two module-scoped files (`test_graph_proximity.py`, `test_retrieval.py`) are the only loop-scope risk; Phase-1 gate already proved coexistence. If a module-scoped fixture is dropped in favor of the function-scoped autouse reset, confirm no test in that module depends on cross-test state inside the module (the autouse reset gives each test a clean graph — any test relying on accumulated state breaks). Read each module's tests before dropping its fixture.

**Test criteria** (per file):
- [ ] File collects with no `Neo4jConnection` / `get_neo4j_*` / `NEO4J_*` symbol.
- [ ] Its tests pass against the shared throwaway DB.
- [ ] Verified one file at a time (not a batched run).

**Maps to**: P3-TEST-01, P3-TEST-02, P3-TEST-03.

**Status**: [ ] pending

---

### Phase 4 — Class-nested live-DB fixture files
**Goal**: Same consolidation, for files whose `db` fixture is nested inside a test class. (Implements spec **Component 5 / Batch 4**. Depends on Phase 1.)

**Design**: Delete or repoint the class-nested fixture in favor of the shared conftest `db`; delete constants/imports; repoint type hints. Leaning "drop and inherit" because the function-scoped autouse reset gives each test a clean graph — confirm per class that no test relies on class-local accumulated state before dropping.

**Steps**:
1. `tests/test_compression.py` (nested `@pytest_asyncio.fixture()` `:230` → builds `Neo4jConnection` `:235`) → drop/repoint to shared `db`, run, green.
2. `tests/test_export.py` (class-nested fixture `:349` → `:354`) → drop/repoint to shared `db`, run, green.

**Files to modify**:
- `tests/test_compression.py`, `tests/test_export.py`.

**Risks**:
- A class that shares state across its own tests would break under the autouse reset. Read each class's tests; if shared state exists, keep a thin class fixture that yields the shared connection instead of dropping it.

**Test criteria** (per file):
- [ ] File collects; no nested `db` fixture builds a connection.
- [ ] Tests pass against the shared DB; no neo4j symbols remain.

**Maps to**: P3-TEST-01, P3-TEST-02.

**Status**: [ ] pending

---

### Phase 5 — Integrity tests
**Goal**: Construct the checker with the real single-arg API and never mis-await the sync query method. (Implements spec **Component 6 / Batch 5**, D7/A4/A5/L7/L8. Depends on Phase 1.)

**Design**: `tests/test_integrity.py` currently uses the two-arg Neo4j shape `IntegrityChecker(db._driver, db._database)` (`:64`) and builds its own `db()` fixture. Collapse to the single-arg `IntegrityChecker(db)` (`integrity.py:22`) consuming the shared `db`. The redundancy check needs an optional ML library; pass `skip_redundancy=True` where `run_all_checks` is exercised so `detect_redundant` does not raise `RuntimeError`.

**Steps**:
1. Delete `NEO4J_*` constants (`:19-21`) and `Neo4jConnection`/`get_neo4j_*` imports (`:15-16`).
2. Delete the local `db()` fixture (`:53-59`) in favor of the shared `db`.
3. Change the `checker` fixture (`:62-64`) from `IntegrityChecker(db._driver, db._database)` → **`IntegrityChecker(db)`** (single arg, A4).
4. Ensure any `run_all_checks` call passes `skip_redundancy=True` (L7/A5). Public methods stay awaited; `_execute_query` is NEVER awaited (G4).
5. Run the file — green.

**Files to modify**:
- `tests/test_integrity.py`.

**Risks**:
- Forgetting `skip_redundancy=True` makes `detect_redundant` raise `RuntimeError` on a box without `sentence-transformers` — a false failure. Audit every `run_all_checks` call site.

**Test criteria**:
- [ ] File collects; checker built with ONE argument.
- [ ] Redundancy-touching tests pass via `skip_redundancy=True`.
- [ ] No neo4j symbols remain.

**Maps to**: P3-TEST-01.

**Status**: [ ] pending

---

### Phase 6 — Inline-construction + post-suite restoration + substantive rewrites
**Goal**: Repoint the remaining files that build connections inline or via deleted Neo4j-driver shapes; re-point the post-suite restoration test while keeping its behavior contract; do the two REAL rewrites (not comment scrubs). (Implements spec **Component 7 / Batches 6–7**, D4/L2/F4/F5.)

**Design (sub-parts)**:

**6a — inline swaps** (depends on Phase 1): repoint inline `Neo4jConnection(get_neo4j_*())` to the shared `db`.
- `tests/test_session.py` — inline `:129,195,280`; fixtures `:119,190,271`.
- `tests/test_embeddings.py` — inline `:436,498,536`.

**6b — post-suite restoration** (D4/L2): `tests/test_post_suite_neo4j_restoration.py`.
- **Rename** the file to drop `neo4j` → `test_post_suite_restoration.py`.
- Re-point `_count()` (`:34-55`): delete the `try: import get_neo4j_*/Neo4jConnection except ImportError: pytest.skip` block (`:37-45`) and the inline `Neo4jConnection(...)` query (`:48-52`). Replace with a direct `FalkorDBLiteConnection` against the **production** graph (`get_falkordb_path()/_graph()/_module()/get_redis_bin()`) that runs `MATCH (n:<label>) RETURN count(n) AS c` via `_execute_query` (sync — NO await) and closes. It must NOT use the test fixture — it observes prod state, which is the contract.
- **KEEP the behavior contract**: `test_migrate_restores_skill_nodes` still asserts Skill/Playbook/ForbiddenResponse counts > 0 after `writ import-markdown bible/`; `test_conftest_sessionfinish_does_not_gate_on_count_zero` still pins the no-`if count == 0` gate.
- Scrub the module docstring's "in Neo4j" wording.
- **Expected fallout (document, do NOT suppress)**: un-skipping runs this LIVE for the first time (it silently skipped for years — L2). If methodology ingest has any FalkorDB-specific gap it fails loudly HERE — that is the first-real-failure site, NOT a fixture-migration regression. Flag to the implementer.

**6c — `test_import_markdown_unified.py` REAL rewrite** (F4/OQ-8, NOT a comment scrub): reads `_writ_config["neo4j"]["password"]` (`:36` — `KeyError` today) and `_cypher()` shells out to `docker exec writ-neo4j cypher-shell` (`:44-58`). Rewrite: drop the `[neo4j]` config read; replace the `docker exec` cypher helper with `_execute_query` against the relevant graph (or a `writ` CLI count), preserving the existing behavior matrix (default / `--only` / `--dry-run` / idempotency / version-bump). Add NO new assertions (G3). Treat as its own verify step.

**6d — `_StubNeo4jSession` DELETE** (F5/D11): `test_phase6bcd_verification.py:300` defines `_StubNeo4jSession` and it is **never instantiated or referenced anywhere** (research confirmed: dead code; `run_migration`→`_ingest`→`ingest_path` uses no `.session()` shape; idempotency rides on the source-level `test_migration_uses_merge_not_create` at `:348`). **Delete the class** (do NOT rename — it is dead). The docstring/comment "Neo4j" mentions at `:5,15,18,80,349` are scrubbed in Phase 7 (8a).

**Steps** (verify each sub-part independently):
1. 6a: migrate `test_session.py`, run, green; migrate `test_embeddings.py`, run, green.
2. 6b: rename file, rewrite `_count()`, run — document any live fallout as expected, not a migration bug.
3. 6c: rewrite `test_import_markdown_unified.py`, run its matrix — green without `docker exec`/`[neo4j]`.
4. 6d: delete `_StubNeo4jSession`, run `test_phase6bcd_verification.py`, green.

**Files to modify**:
- `tests/test_session.py`, `tests/test_embeddings.py` (6a).
- `tests/test_post_suite_neo4j_restoration.py` → renamed `tests/test_post_suite_restoration.py` (6b).
- `tests/test_import_markdown_unified.py` (6c).
- `tests/test_phase6bcd_verification.py` (6d — delete the class only; docstrings scrubbed in Phase 7).

**Risks**:
- 6b un-skip surfaces a real pre-existing methodology-ingest gap → expected, flagged. Do not paper over it; report it as a finding if it fires.
- 6c: the rewrite must produce the SAME counts the matrix needs — confirm `_execute_query` (or the CLI) returns the same downstream shape (`list[dict]` with string keys, the same contract the old `record.data()` produced). Invent no new assertions.

**Test criteria**:
- [ ] 6a: both files collect and pass; no inline Neo4j construction.
- [ ] 6b: renamed file runs LIVE (no skip); behavior contract assertions intact; any fallout documented as a first-real-failure, not a migration bug.
- [ ] 6c: import-markdown matrix runs without `docker exec`/`[neo4j]`; no new assertions.
- [ ] 6d: `_StubNeo4jSession` deleted; `test_phase6bcd_verification.py` passes.

**Maps to**: P3-TEST-01, P3-TEST-02, P3-TEST-07.

**Status**: [ ] pending

---

### Phase 7 — D9 assertion realignment + comment/string scrubs (incl. PRODUCTION edits)
**Goal**: Realign assertions that test *deleted* Docker/Neo4j behavior to the shipped Docker-free/FalkorDB reality (D9), and scrub comment-only "Neo4j" mentions — without changing assertions on still-valid behavior (G3). Includes the two D10 production/doc carryover scrubs. (Implements spec **Component 8 / Batches 8–9**, D9/D10/F1/F2.)

**Design**:

**7a — pure comment/docstring scrubs** (mechanical, no assertion change):
- `tests/test_hook_perf_floors.py:46`, `tests/test_methodology_ingest.py:4`, `tests/test_phase4_analyze_friction.py:7`, `tests/test_phase4_friction_delta.py:7`, `tests/test_phase6efg_corpus_promotion.py:6,20`, `tests/fixtures/methodology_loader.py:3`, `tests/plugin/test_fresh_install_smoke.py:9` — scrub "Neo4j"/"Docker" comment wording.
- `tests/test_phase3b_export_subagent_roles.py:83,90,92,106` — skip-message strings "Neo4j not reachable" → FalkorDB equivalent.
- `tests/test_pyproject_packaging.py:106` — **comment-only** (docstring "(FastAPI, Pydantic v2, neo4j)"); the assertion checks the `>=3.11` Python floor, NOT a dep name. Scrub the comment to "falkordb". (Research confirmed this is not a dependency assertion.)
- `tests/test_phase6bcd_verification.py:5,15,18,80,349` — scrub docstring/comment "Neo4j" wording (the `_StubNeo4jSession` deletion was done in Phase 6/6d).

**7b — D9 realignment of deleted-infra assertions**: `tests/test_bootstrap.py`. For each test below, realign to the shipped behavior OR delete as obsolete (the artifact it inspects is gone):
- `test_docker_compose_exists` (`:39-40`) — `docker-compose.yml` was deleted; realign to assert ABSENT, or delete.
- `test_bootstrap_checks_docker_prerequisite` (`:70-75`) — bootstrap now checks `brew`/`redis`/`envsubst`/`git`/`python3` (`scripts/bootstrap.sh:61-64,99-107`); realign or delete the Docker case.
- `test_bootstrap_starts_neo4j_via_compose` (`:131-134`) + `test_bootstrap_waits_for_neo4j` (`:136-138`, port 7687) — bootstrap now ensures Redis + downloads `falkordb.so` (`bootstrap.sh:82-107,169-178`); realign or delete.
- `TestDockerCompose` (`:163-187`) — all five read the deleted `docker-compose.yml`; **delete the class** (obsolete).
- `TestEnsureServerMigration` (`:195-207`) — `ensure-server.sh` now `nohup writ serve` (`:37`), not `docker compose`; realign or delete.
- `test_fails_cleanly_when_docker_missing` (`:244-248`) — realign to a prerequisite the bootstrap actually checks (brew/redis), or delete the Docker case.
- **KEEP unchanged**: every still-valid assertion — strict-mode, python3 prereq, envsubst, venv, `pip install -e '.[dev]'`, `export_onnx.py`, `install-harness-config.sh`, symlinks, `import-markdown`, `writ serve`, `/health`, ready banner, README tests.

**7c — PRODUCTION/DOC carryover scrubs (D10 — HUMAN REVIEW REQUIRED before commit)**:

**(i) `hooks/scripts/session-start-bootstrap.sh` — PRODUCTION SCRIPT.** Phase 2 missed it; it still probes Neo4j bolt 7687 and hints `docker compose`. Exact edits for human review:
- **Delete lines 24-25** (the `NEO4J_HOST`/`NEO4J_PORT` variable definitions):
  ```
  NEO4J_HOST="${WRIT_NEO4J_HOST:-localhost}"
  NEO4J_PORT="${WRIT_NEO4J_PORT:-7687}"
  ```
- **Delete the entire Neo4j probe block, lines 38-49** (the comment "# 3. Probe Neo4j bolt port 7687…", the `/dev/tcp` probe `if ! (exec 3<>/dev/tcp/…)`, the `[Writ] Neo4j not reachable…` / `docker compose … up -d neo4j` heredoc, and the `exec 3<&-` / `exec 3>&-` fd-close lines). FalkorDBLite is embedded — the server's own startup (step 5) loads it via `vendor/falkordb.so`; there is no separate bolt port to probe. Renumber the remaining comment steps (the `# 4.`/`# 5.` headers) for readability.
- After the edit the script flows: probe venv → probe server health → start `writ serve` → wait for health. No external DB probe.
- **This is production code, NOT a test. Surface the exact diff to the human; do not commit without sign-off.**

**(ii) `writ-architecture-flowchart.html` — DOC.** Still names "Neo4j" as a current pipeline stage at `:410` ("Neo4j, cached") and `:588` ("live in a Neo4j graph"); 0× "FalkorDB". Scrub both to "FalkorDB" (2 lines).

**(iii) The two tests that pin the carryover artifacts** — realign AFTER (i)/(ii) land:
- `tests/plugin/test_session_start_bootstrap.py::test_session_start_probes_neo4j` (`:66-80`, asserts `"7687" in content`) — after the script scrub, realign to assert NO Neo4j/7687 probe (and rename the test to drop `probes_neo4j`). It must match the scrubbed script.
- `tests/test_architecture_flowchart.py:125` — change the required-terms tuple `("BM25","Tantivy","hnswlib","Neo4j","RRF")` → swap `"Neo4j"` → `"FalkorDB"` to match the scrubbed HTML.

**7d — credential-scan meta-test** (OQ-2): `tests/test_config_integration.py::TestRepoWideNoHardcodedCreds` (`:179`) scans `tests/` for `DEFAULT_NEO4J_PASSWORD` — a secret that no longer exists; the import driving it (`:19-27`) breaks collection. **Retire the credential-literal assertions** (lowest-risk under the locks; the secret is gone). Do NOT write a new "no raw-connection-in-tests" guard this phase (G3) — note it as a later-phase follow-up.

**Steps** (verify each sub-part):
1. 7a: scrub all listed comment/string sites; run each touched file — green (mechanical, no assertion change).
2. 7b: realign/delete the `test_bootstrap.py` deleted-infra assertions; keep all still-valid ones; run — green.
3. 7c(i): edit `session-start-bootstrap.sh` per the exact diff above → **present diff to human, await sign-off**. 7c(ii): scrub the 2 HTML lines. 7c(iii): realign the two tests to match; run both — green.
4. 7d: retire the credential-literal assertions in `test_config_integration.py`; run — green (also finishes Phase 2's `test_config_integration.py` work).

**Files to modify**:
- 7a: `tests/test_hook_perf_floors.py`, `tests/test_methodology_ingest.py`, `tests/test_phase4_analyze_friction.py`, `tests/test_phase4_friction_delta.py`, `tests/test_phase6efg_corpus_promotion.py`, `tests/fixtures/methodology_loader.py`, `tests/plugin/test_fresh_install_smoke.py`, `tests/test_phase3b_export_subagent_roles.py`, `tests/test_pyproject_packaging.py`, `tests/test_phase6bcd_verification.py`.
- 7b: `tests/test_bootstrap.py`.
- 7c: `hooks/scripts/session-start-bootstrap.sh` (PRODUCTION), `writ-architecture-flowchart.html` (DOC), `tests/plugin/test_session_start_bootstrap.py`, `tests/test_architecture_flowchart.py`.
- 7d: `tests/test_config_integration.py`.

**Risks**:
- 7c(i) is PRODUCTION code — a wrong edit changes hook behavior for real sessions. The edit only removes a dead external-DB probe; the server-start path is untouched. Still requires human sign-off (HITL contract: infra/CI/hooks change).
- 7b: over-deleting a still-valid assertion would silently drop coverage. Only the enumerated deleted-infra tests change; the KEEP list is exhaustive — touch nothing on it.

**Test criteria**:
- [ ] 7a: every scrubbed file passes; `grep -ri neo4j` over them reaches incidental-only.
- [ ] 7b: `test_bootstrap.py` collects; every retained assertion describes shipped behavior; no test asserts deleted Docker infra exists.
- [ ] 7c: human signed off on the `session-start-bootstrap.sh` diff; script + HTML scrubbed; the two pinning tests realigned and green.
- [ ] 7d: credential-literal assertions retired; `test_config_integration.py` collects and passes (no broken `DEFAULT_NEO4J_PASSWORD` import).

**Maps to**: P3-TEST-01, P3-TEST-02.

**Status**: [ ] pending

---

### Phase 8 — Benchmark migration (33-file total scope)
**Goal**: The four benchmark files run without crashing — they carry the SAME deleted Neo4j wiring as the test files and fail at collection today. (Implements spec **Component 9 benchmark portion**, D8/D11/R4. Full Component-4 treatment, NOT a one-arg tweak — research corrected the spec's under-scoping.)

**Design**: `benchmarks/bench_targets.py` has its own `Neo4jConnection` db fixture (`:88`), `NEO4J_*` constants, deleted `get_neo4j_*` imports (`:28-29`), a **two-arg** `IntegrityChecker(db._driver, db._database)` (`:120`), and a module-level `pytestmark loop_scope="module"` (`:42`). Three more benchmark files carry neo4j refs: `methodology_bench.py`, `run_benchmarks.py`, `scale_benchmark.py`. Migrate all four the same way as the test files: drop the local Neo4j fixture/constants/imports, consume the shared `db` (or build a FalkorDB connection where a benchmark legitimately needs its own), fix the two-arg `IntegrityChecker` → single-arg `IntegrityChecker(db)`. Scope is run-no-crash (D8) — baseline timing drift is acceptable, a crash/collection-error is not.

**Steps** (one file at a time):
1. `benchmarks/bench_targets.py` — drop `Neo4jConnection` fixture (`:88`) + `NEO4J_*` consts + deleted imports (`:28-29`); fix two-arg `IntegrityChecker` (`:120`) → `IntegrityChecker(db)`; repoint to the shared `db`. Run — no collection error, no crash.
2. `benchmarks/methodology_bench.py` — scrub/migrate neo4j refs; run-no-crash.
3. `benchmarks/run_benchmarks.py` — scrub/migrate neo4j refs; run-no-crash.
4. `benchmarks/scale_benchmark.py` — scrub/migrate neo4j refs; run-no-crash.

**Files to modify**:
- `benchmarks/bench_targets.py`, `benchmarks/methodology_bench.py`, `benchmarks/run_benchmarks.py`, `benchmarks/scale_benchmark.py`.

**Risks**:
- A benchmark may need its own DB (e.g. scale_benchmark with bulk data) rather than the shared reset-every-test `db` — if so, build a dedicated FalkorDB connection on a temp dir there, do NOT force the shared fixture. Read each benchmark's intent.
- Benchmarks live under `benchmarks/`, separate wiring from `tests/` — migrating tests does not fix these (research Dependencies note).

**Test criteria** (per file):
- [ ] `pytest benchmarks/<file>` collects with no ImportError/collection error.
- [ ] Runs to completion without crashing (timing drift acceptable, D8).
- [ ] No neo4j symbols; `IntegrityChecker` is single-arg.

**Maps to**: P3-TEST-06.

**Status**: [ ] pending

---

### Phase 9 — Full-suite verification + zero-hit grep
**Goal**: Prove the whole suite is green, benchmarks don't crash, and no neo4j surface remains anywhere under `tests/` or `benchmarks/`. (Implements spec **Component 9 final run**, D11 widened done-when.)

**Design**: Final gate. Run the full suite with the Writ server stopped; run benchmarks + perf-marked tests for no-crash; run the widened grep; confirm the post-suite restoration left the production corpus loaded.

**Steps**:
1. Stop any running `writ serve`. Run `pytest` from repo root — expect exit 0, full count passes (target 282, minus any pre-existing by-design skips, modulo the documented 6b live fallout if it fires — report it, do not hide it).
2. Run `pytest tests/benchmarks/` and `pytest -m perf` — no crash, no collection error (D8).
3. Run `grep -ri neo4j tests/ benchmarks/` — expect ZERO hits except the two known incidental ones: `tests/conftest.py` (none — scrubbed Phase 1) and `tests/fixtures/ground_truth_queries.json` (a natural-language query string, not wiring). Any other hit is a miss — go back and scrub it.
4. P3-TEST-07: after the run, count Skill/Playbook/ForbiddenResponse nodes in the production graph (or hit `/always-on?mode=work`) — confirm the methodology corpus is present (the `pytest_sessionfinish` restoration ran).
5. Optional P3-TEST-04 spot-check: with a separate `writ serve` holding `.writ/graph.lock`, run `pytest` again — expect no "graph DB is locked by PID" error (unique temp dir + own socket).

**Files to modify**:
- None (verification only).

**Risks**:
- The 6b restoration test may fail live (documented expected fallout). If it does, that is a real pre-existing methodology-ingest gap surfaced — report it as a finding; it is NOT a Phase-3 fixture-migration regression and does not mean the migration is wrong.

**Test criteria**:
- [ ] P3-TEST-01: `pytest` exits 0; full count green (modulo documented L2 fallout, reported).
- [ ] P3-TEST-02: `grep -ri neo4j tests/ benchmarks/` is incidental-only (zero wiring hits).
- [ ] P3-TEST-06: benchmarks + `-m perf` run without crashing.
- [ ] P3-TEST-07: methodology corpus present in the production graph after the run.
- [ ] P3-TEST-04 (spot-check): suite runs green alongside a live `writ serve`, no lock collision.

**Maps to**: P3-TEST-01, P3-TEST-02, P3-TEST-06, P3-TEST-07.

**Status**: [ ] pending

---

## Phase → behavior-inventory (P3-TEST) mapping

| Phase | P3-TEST criteria advanced |
|---|---|
| 0 · Delete reference doc | 01 (removes a wiring trap) |
| 1 · Shared conftest fixtures + smoke + gate | 01, 03, 04 |
| 2 · Config rewrite | 05 |
| 3 · Top-level fixture files | 01, 02, 03 |
| 4 · Class-nested fixture files | 01, 02 |
| 5 · Integrity tests | 01 |
| 6 · Inline + restoration + substantive rewrites | 01, 02, 07 |
| 7 · D9 realignment + scrubs (+ production edits) | 01, 02 |
| 8 · Benchmark migration | 06 |
| 9 · Full-suite verification + grep | 01, 02, 06, 07 |

> P3-TEST-02 ("no neo4j surface") is fully met only once Phases 3–8 land **and** the Phase-7c carryover edits (`session-start-bootstrap.sh`, `writ-architecture-flowchart.html`) ship — those two artifacts still carry live "Neo4j" until then.

---

## Open Questions

These are deferred per the dispatch (NON-INTERACTIVE) and the spec's OQ list. They do NOT block planning; the locked decisions (D9/D10/D11) already resolve the in-scope direction. Surface to the human at implementation:

- **OQ-6 / Phase 7c(i) — `session-start-bootstrap.sh` is PRODUCTION code.** D10 folds the scrub into Phase 3 and the exact diff is specified above, but it is production, not a test. **Requires human sign-off on the diff before commit** (HITL contract: hooks/infra change). The alternative (leave it) yields a suite that documents a not-yet-removed Neo4j probe — rejected by D10.
- **OQ-7 / Phase 7c(ii) — `writ-architecture-flowchart.html` doc edit.** D10 folds the 2-line scrub + test term change into scope. It is a doc, low-risk, but a non-test artifact — flag in the same review as OQ-6.
- **OQ-8 / Phase 6c — `test_import_markdown_unified.py` rewrite path.** The counts the matrix needs can come from `_execute_query` against the relevant graph OR a `writ` CLI count — both supported. Plan picks `_execute_query` (same `list[dict]` contract as the old helper); confirm at implementation that it preserves the matrix without inventing assertions (G3).
- **OQ-2 / Phase 7d — credential-scan meta-test.** Plan retires the credential-literal assertions (lowest-risk; the secret is gone). A follow-up "no raw-connection-in-tests" guard is noted for a later phase but NOT written here (G3). Confirm retire-vs-reaim with the user.
- **A8 CONSTRAINT (recorded as a plan note + TECH_DEBT candidate, NOT scaffolded — OQ-5).** Loop-safety depends on `db.py` staying synchronous; a future async-redis refactor of `db.py` would reintroduce wrong-loop failures for the session-scoped fixture. Capture in a future `docs/CONSTRAINTS.md`/`TECH_DEBT.md` — do not scaffold those files this phase.
- **ADR candidate (flag only).** Option A (session-scoped real DB + autouse reset) meets ADR gates (hard to reverse once ~10 files depend on it; surprising without the ~5s-startup context; real alternatives existed). Author in the `/architecture-docs` step, not here.

---

## Out of Scope (explicit)

- **New tests / new assertions / changed verification intent on still-valid behavior** — D3/G3. Only the storage layer in setup/fixtures changes. The one exception is the D9 realignment carve-out (deleted Docker/Neo4j behavior only) in Phase 7. The Phase-1 smoke test is temporary scaffolding deleted before that phase ends — not a permanent new test.
- **Modifying `writ/retrieval/` source** — frozen (G1). Its docstrings still say "Neo4j" (`traversal.py`, `pipeline.py`); no test asserts they are clean (research found none — F3/OQ-3). If one surfaces, change only the TEST's expectation, never the frozen source.
- **The pure-`AsyncMock` test family** — `test_authority.py`, `test_analysis.py` (and any zero-neo4j file mocking `GraphConnection` via `AsyncMock`). Grep-clean (L5). Leave UNTOUCHED.
- **`pytest-xdist` / parallel execution** — one session DB = one lockfile holder (L9). Suite is serial; parallelism deferred, no phase assigned.
- **Scaffolding `docs/CONSTRAINTS.md` / `TECH_DEBT.md` / `OPEN_QUESTIONS.md`** — OQ-5, explicitly skipped (Phase 4A carryover). The A8 constraint is recorded as a plan note only.
- **Deciding whether the post-suite restoration hook is still load-bearing** — OQ-4, a logic judgement. Keep `pytest_sessionfinish` as-is; do not remove. Recorded as a later-phase cleanup candidate.
- **Production code beyond the constructor/import swap in tests + the two D10 carryover scrubs** — G2. The only production/doc edits are `session-start-bootstrap.sh` and `writ-architecture-flowchart.html` (Phase 7c), both human-reviewed.
