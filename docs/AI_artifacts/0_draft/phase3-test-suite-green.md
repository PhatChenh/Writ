# Draft — Phase 3: Test Suite Green

_Grill sign-off: 2026-06-20. Source of locked requirements for design step._

## Goal

All 282 tests pass against FalkorDBLite. `grep -ri neo4j tests/` returns zero hits (except incidental comments). **Same behavior verified — no new tests, no changed assertions, no changed test logic.** Pure adaptation of the storage layer in test setup/fixtures/mocks.

## Locked decisions (from grill)

| # | Decision | Choice |
|---|----------|--------|
| D1 | DB access pattern | **Session-scoped real FalkorDBLite** fixture, shared across tests, isolate via `clear_all()` / unique IDs. NOT mocks. Most faithful — exercises real Cypher. |
| D2 | Test DB path | **Throwaway temp DB** (`tmp_path` / session tmp dir), torn down at session end. No lockfile collision with a running `writ serve`; zero risk to prod `.writ/graph.db`. |
| D3 | File scope | **All ~28** neo4j-referencing test files (roadmap's "13" undercounted). Done-when requires zero neo4j hits across `tests/`. |
| D4 | `test_post_suite_neo4j_restoration.py` | **Replace** `_count()` internals → `FalkorDBLiteConnection._execute_query`. Keep the post-suite methodology-restoration behavior contract. Rename file to drop `neo4j`. |
| D5 | `docs/AI_artifacts/0_draft/falkordb-reference.md` | **Delete** (landmine L10 — describes a fake `AsyncFalkorDB`/`pip falkordblite` API Phase 1 never built; could mislead the test-writer subagent). |
| D6 | `test_config.py` + `test_config_integration.py` | **Full rewrite** to test the real FalkorDB config getters (see L1). |
| D7 | `test_integrity.py` | Constructor → `IntegrityChecker(db)` (single arg). |
| D8 | Benchmarks | Run-no-crash. Baselines may drift (done-when permits). Not in correctness scope. |
| D9 | **Assertion-conflict policy** (added post-design review) | "No changed assertions" = don't change assertions verifying *still-valid* behavior. **DO realign** assertions that test *deleted* Docker/Neo4j behavior to assert the shipped FalkorDB/Docker-free reality. Applies to `test_bootstrap.py`, `tests/plugin/test_session_start_bootstrap.py`, the credential-scan meta-test (OQ-2), and docstring-naming tests (OQ-3). This is realignment to what Phase 1–2 already shipped, NOT inventing new checks. |

## Open-question resolutions (post-design review, 2026-06-20)

- **OQ-1 (blocker) → resolved by D9.** Infra-assertion tests realign to shipped product.
- **OQ-2 (credential scan) → D9.** Realign to "no Neo4j password exists" reality.
- **OQ-3 (docstring "Neo4j" assertions) → D9.** Realign to scrubbed/FalkorDB reality. NOTE: any such assertion pointing at frozen `writ/retrieval/` (G1) must only change the TEST's expectation, not the frozen source — those docstrings stay "Neo4j" per G1 until retrieval is legitimately edited. Flag if a test asserts retrieval docstrings are clean.
- **OQ-4 (restoration hook) → keep this phase** (restores prod graph, not vestigial).
- **OQ-5 (CONSTRAINTS.md) → skip.** Out of Phase 3 scope; Phase 4 (4A) carryover. Do NOT scaffold.

## D10 — Phase-2-carryover artifact scrub (added post-spec review, 2026-06-20)

Spec verification (F1–F5) found the live tree contradicts the design's L10 claim that Phase 2 scrubbed everything. User-approved scope expansion to reach fully-clean `grep -ri neo4j tests/` + 282 green with **no carve-out exceptions**:

**IN scope now (Phase-2-carryover cleanup folded into Phase 3):**
- **F1/OQ-6 — `hooks/scripts/session-start-bootstrap.sh`** (production hook): still has live Neo4j:7687 + `docker compose ... neo4j`. **Scrub** to match shipped Docker-free/FalkorDB reality. Then realign `test_session_start_probes_neo4j`. Plan MUST spec exact edits (production script → human review).
- **F2/OQ-7 — `writ-architecture-flowchart.html`** + `test_architecture_flowchart.py:125`: doc names "Neo4j" as a CURRENT pipeline stage (line 410 "Neo4j, cached", line 588 "live in a Neo4j graph"); the test PINS `"Neo4j"` in the required pipeline-terms tuple `("BM25","Tantivy","hnswlib","Neo4j","RRF")`. This is a STALE current-architecture doc, NOT historical reference (confirmed: present-tense, no original/legacy framing). **Scrub** doc Neo4j→FalkorDB (2 lines) + change the test term `"Neo4j"`→`"FalkorDB"`.
- **F4/OQ-8 — `test_import_markdown_unified.py`**: NOT a comment scrub — substantive live test using `docker exec writ-neo4j cypher-shell` + `_writ_config["neo4j"]["password"]` (KeyErrors today). **Real rewrite** to FalkorDB equivalent. (Spec already re-batched.)

**Research must verify (code-fact, not scope):**
- **F5/OQ-9 — `_StubNeo4jSession`**: stubs a deleted Neo4j-driver session shape. Confirm whether migrate/import path still drives it → keep-and-rename vs delete.
- **A8 loop-scope** (top risk): asyncio mode is **strict** (not set in pyproject) → shared async fixtures need `@pytest_asyncio.fixture`; `loop_scope` interaction in `test_graph_proximity.py` / `test_retrieval.py` is R1/R2.

**Resolved non-issues:**
- **F3/OQ-3** — no test asserts `writ/retrieval/` docstrings clean → G1 frozen source untouched, no conflict.
- **OQ-2 (credential-scan meta-test)** → realign per D9 (no Neo4j password exists).

## D11 — Research outcomes (added post-research, 2026-06-20)

Research: **22 validated · 0 invalidated · 0 unverifiable.** No hard stop. Locked Option A fixture design VERIFIED safe.

- **A8 loop-scope (top risk) → SAFE.** `db.py` has zero asyncio primitives; `async def` methods wrap the **sync** `_execute_query` (db.py:162). Connection never binds an event loop → cannot be on the wrong loop → session-scoped `db` fixture is awaitable from module-scoped (`test_graph_proximity.py`, `test_authoring.py`) and function-scoped (`test_integrity.py`) consumers interchangeably. `asyncio_mode=strict` confirmed (absent from pyproject.toml:122-127, pytest-asyncio 0.26.0). Consumer tests are mostly sync `def`; awaits live only in fixture setup.
- **CONSTRAINT to note in plan (A8 caveat):** loop-safety is a property of `db.py`'s SYNC implementation, NOT the fixture design. A future async-redis refactor would silently reintroduce "attached to a different loop" failures. Plan records this; build the Component-2 conftest **smoke test FIRST** and run it against the two module-scoped files to prove "does pass," not "should pass." (CONSTRAINTS.md scaffold stays out of scope per OQ-5 — capture as a plan note + TECH_DEBT candidate, do not scaffold.)
- **SCOPE 28 → 33 files (D11 decision, within roadmap):** research found 4 more neo4j-carrying files in `benchmarks/`: `bench_targets.py` (own `Neo4jConnection` fixture :88, `NEO4J_*` consts, deleted imports :28-29, **two-arg** `IntegrityChecker(db._driver, db._database)` :120, `pytestmark loop_scope="module"` :42) + `methodology_bench.py`, `run_benchmarks.py`, `scale_benchmark.py`. Roadmap done-when already requires "benchmark tests run no-crash" → these were always in Phase 3. **Folded in.** Benchmarks get full Component-4 treatment, not a comment scrub.
- **F5 → `_StubNeo4jSession` is DEAD CODE** (defined, never instantiated; migration path uses no `.session()` shape). Delete, don't rename.
- **Done-when grep widened:** `grep -ri neo4j tests/ benchmarks/` zero hits (benchmarks now in scope).

## Out of scope (explicit)

- Adding new tests, changing what tests verify, changing assertions.
- Modifying `writ/retrieval/` (frozen, G1) and any production code beyond what a constructor/import swap in tests requires.
- The pure-`AsyncMock` test family (`test_authority.py`, `test_analysis.py`, …) that mocks the `GraphConnection` protocol and carries **no** neo4j ref — leave untouched (L5).

## Deferred to design (flagged, not decided)

- **Temp-DB choice may make `pytest_sessionfinish` restoration hook + the restoration test partly vestigial** (nothing touches prod graph anymore). That is a *logic* change → out of Phase 3 scope. Design resolves: keep hook as-is unless provably dead. Do NOT silently rip it out.

## Landmines uncovered (codegraph scan, 2026-06-20)

| # | Landmine | Evidence | Plan impact |
|---|----------|----------|-------------|
| L1 | `get_neo4j_uri/user/password` **gone**; real config API = `get_falkordb_path` / `get_falkordb_graph` / `get_falkordb_module` (config.py:49-64) + `get_redis_bin` (config.py:67-89, has arch-error path). **None have covering tests.** | codegraph config.py | `test_config*` rewrite targets these 4 getters + the x86_64 RuntimeError path |
| L2 | `test_post_suite_neo4j_restoration._count()` imports `get_neo4j_*` → `ImportError` → `pytest.skip("neo4j driver not installed")`. **Silently skipping today, not failing.** | test_post_suite file:38-45 | "Replace" un-skips it → may surface NEW live failures. Expect it. |
| L3 | **Zero `from neo4j` / `import neo4j`.** Every ref is `Neo4jConnection` (deleted from writ.graph.db) + per-file module-level `NEO4J_URI/USER/PASSWORD` constants. | grep | Fix = swap class → `FalkorDBLiteConnection`, delete those constants, repoint fixture to temp DB |
| L4 | Each live-DB test file defines its **own duplicated `db()` fixture** (`Neo4jConnection(NEO4J_URI,...)` + `clear_all()`, function-scoped). ~10 files. | test_infrastructure:24-31, test_authoring:31, test_compression:233 | Real work = consolidate into ONE session-scoped conftest fixture, not 28 isolated edits |
| L5 | Two families: live-DB (swap fixture) vs pure-`AsyncMock` (mock `GraphConnection`, no neo4j ref). | test_authority:245 `mock_db = AsyncMock()` | Scope guard — don't touch mock-only files |
| L6 | `clear_all()` exists (db.py:479). | codegraph db.py | Isolation primitive ready |
| L7 | `detect_redundant` **raises RuntimeError** without `sentence-transformers` (integrity.py:101). | codegraph integrity.py | `test_integrity` must pass `skip_redundancy=True` or install `.[fallback]` |
| L8 | `IntegrityChecker(db)` single-arg (integrity.py:22); methods `async def` but call **sync** `_execute_query` (no inner await). | codegraph integrity.py | Tests `await` the public methods; never `await _execute_query` |
| L9 | Lockfile = one holder per session (db.py:147 `_acquire_lock`). | codegraph db.py | Serial pytest assumed; no `pytest-xdist` unless per-worker temp DB |

## Connection construction facts (for fixture design)

- `FalkorDBLiteConnection(db_path, graph="writ", module_path="vendor/falkordb.so", redis_bin=...)` spawns a `redis-server` subprocess + loads `vendor/falkordb.so`, waits up to ~5s for the unix socket (db.py:86-145). Per-test = ~5s × N → unacceptable. Session-scope amortizes to one startup.
- Socket dir = `/tmp/writ-<md5(db_dir)[:12]>` → unique per db_dir, so a unique `tmp_path` gives a clean socket (db.py:104-109).
- `redis_bin` default is the arm64 Homebrew literal; production callers pass `get_redis_bin()`. Fixture should pass `get_redis_bin()` + `get_falkordb_module()` so it resolves on the dev machine.

## Done when

- `pytest` passes all 282 tests.
- Benchmark tests run without crashing.
- `grep -ri neo4j tests/` returns zero hits (except incidental comments).
