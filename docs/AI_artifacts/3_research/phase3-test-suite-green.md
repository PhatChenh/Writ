# Research: Phase 3 — Test Suite Green
_Last updated: 2026-06-20_

## Overview

Plain English: Phases 1–2 swapped Writ's database from Neo4j (a Docker container) to FalkorDBLite (an embedded, file-based engine). The production code already runs on the new engine, but the test suite was left behind — roughly 30 test/benchmark files still import deleted Neo4j classes, build connections to a database that no longer exists, or assert that Docker infrastructure (which Phase 2 deleted) is still present. Phase 3 makes the suite green again without changing what any still-valid test verifies.

This research verifies, against the actual on-disk code, every assumption the spec makes — with special attention to the one decision that could sink the whole locked fixture design: whether a single session-scoped async database fixture can coexist with the module-scoped event loops that two test files already declare.

**Headline result: the locked fixture design (Option A) is SAFE.** The reason the "attached to a different loop" failure does not bite here is specific and verifiable: `FalkorDBLiteConnection` contains **zero asyncio primitives**. Its `async def` methods are thin coroutine wrappers around a fully synchronous redis client (`_execute_query` is sync). A connection object that never binds to an event loop cannot be "attached to the wrong loop." Every assumption the spec listed validated. Two assumptions validated with a scope caveat the plan must absorb (the benchmark migration is bigger than the spec framed, and the loop-scope safety rests on an implementation detail that must be stated explicitly so a future async refactor of `db.py` doesn't silently reintroduce the risk).

## Key Components

Plain English: these are the real code locations the spec's claims rest on. All were read at the depth their claim required — behavior claims (clear_all, detect_redundant, loop scope) were read as full bodies, not signature greps.

- **`writ/graph/db.py`** — `FalkorDBLiteConnection`. Constructor `:86-145`, `_acquire_lock :147-160`, `_execute_query :162-184` (sync), socket hashing `:104-109`, `clear_all :479-481`, `close :483-499`. No `asyncio`/`await`/`Lock`/`Event`/loop usage anywhere in the class.
- **`writ/config.py`** — the four real getters: `get_falkordb_path :49`, `get_falkordb_graph :55`, `get_falkordb_module :61`, `get_redis_bin :67` (x86_64 `RuntimeError` at `:85`), `get_hnsw_cache_dir :92`, `load_config :33`. Defaults `DEFAULT_FALKORDB_* :22-24`. No `get_neo4j_*` / `DEFAULT_NEO4J_*` symbols exist.
- **`writ/graph/integrity.py`** — `IntegrityChecker(db)` single-arg `:22`; `detect_redundant :71` raises `RuntimeError` without sentence-transformers (`:101-112`); `run_all_checks(skip_redundancy=False) :248`.
- **`tests/conftest.py`** — `pytest_sessionfinish` (FalkorDB-correct body; one stale comment), data-dict fixtures.
- **Module-scoped loop files** — `tests/test_graph_proximity.py`, `tests/test_retrieval.py`, `tests/test_authoring.py`, `benchmarks/bench_targets.py`.
- **Carryover artifacts** — `hooks/scripts/session-start-bootstrap.sh`, `writ-architecture-flowchart.html`.

## How It Works

Plain English: when the suite runs today, most live-DB test files each build their own Neo4j connection from module-level `NEO4J_URI/USER/PASSWORD` constants, which call deleted `get_neo4j_*` getters — so those files fail to even import. The config-test files skip entirely (their top-of-file import of deleted symbols triggers an `ImportError → pytest.skip`). The post-suite restoration test silently skips for the same reason. A handful of bootstrap/flowchart/hook tests still *pass* because they assert Neo4j/Docker is present — and the artifacts they read still literally contain "Neo4j" (Phase 2 missed them).

The locked fix: one session-scoped `FalkorDBLiteConnection` in `conftest.py` on a throwaway temp dir, a function-scoped autouse `clear_all()` reset, and a shared `db` fixture every file inherits. Because the connection's methods do synchronous work under an async signature, the session connection can be safely awaited from fixtures and tests running on *any* loop scope.

## Spec Verification

Plain English: every assumption the spec flagged held up against the real code. The table below gives one row per assumption ID plus the extra risks the task asked about (loop-scope, the AsyncMock family, benchmarks). Two rows are marked "Validated (with caveat)" — the claim is true but the plan needs an extra note.

| ID | Spec Claim | Verdict | Evidence |
|----|-----------|---------|----------|
| A1 | `FalkorDBLiteConnection(path, graph, module_path, redis_bin)` is the full constructor; passing the getters resolves on the dev box | ✅ Validated | `writ/graph/db.py:86-92` — exact 4-arg signature; production callers pass the getters (`writ/cli.py:871-874`, `scripts/migrate.py:30-33`) |
| A2 | Unique temp dir → unique `/tmp/writ-<hash>` socket + own lockfile, no collision with `writ serve` | ✅ Validated | `db.py:104-109` socket = `/tmp/writ-<md5(db_dir)[:12]>/redis.sock`; `db.py:101,147-160` lockfile = `<db_dir>/graph.lock`. Both keyed on `db_dir` |
| A3 | `clear_all()` resets the whole graph (all labels) between tests | ✅ Validated | `db.py:479-481` — `MATCH (n) DETACH DELETE n` (no label filter; clears every node type, not just Rule) |
| A4 | `IntegrityChecker(db)` single-arg; `test_integrity.py:64` two-arg shape must collapse | ✅ Validated | `integrity.py:22` `def __init__(self, db)`; `tests/test_integrity.py:64` `IntegrityChecker(db._driver, db._database)` (two-arg Neo4j shape, confirmed) |
| A5 | `run_all_checks(skip_redundancy=True)` runs other checks; `detect_redundant()` raises `RuntimeError` without sentence-transformers | ✅ Validated | `integrity.py:101-112` raises `RuntimeError` on `ImportError`; `:259/273-274` `skip_redundancy=True` sets `redundant=[]` and skips the call |
| A6 | No `[neo4j]` in writ.toml; `[falkordb]` present; `get_neo4j_*`/`DEFAULT_NEO4J_*` gone | ✅ Validated | `writ.toml:11` `[falkordb]`, zero neo4j hits; `config.py` exports only falkordb getters; `pyproject.toml:46` `falkordb` dep, no `neo4j` dep |
| A7 | `pytest_sessionfinish` already targets FalkorDB; only a stale comment mentions Neo4j | ✅ Validated | `tests/conftest.py` — body shells `writ import-markdown bible/` (no connection, no Neo4j); one stale comment "Neo4j may not be running" in the `except` block |
| A8 (TOP RISK) | asyncio mode is "strict"; async fixtures need `@pytest_asyncio.fixture` | ✅ Validated | `pyproject.toml:122-127` `[tool.pytest.ini_options]` has ONLY `markers` — no `asyncio_mode` key → pytest-asyncio defaults to **strict**. pytest-asyncio 0.26.0 resolved (`uv.lock:1307`). Existing live-DB fixtures already use `@pytest_asyncio.fixture` |
| A9 | `test_import_markdown_unified.py` KeyErrors on `_writ_config["neo4j"]["password"]` at import; live path shells `docker exec writ-neo4j cypher-shell` | ✅ Validated | `test_import_markdown_unified.py:36` `_writ_config["neo4j"]["password"]` at module load (KeyError today); `:45-58` `_cypher()` runs `docker exec writ-neo4j cypher-shell` |
| A10 | Flowchart HTML still literally contains "Neo4j" ×2 (0× FalkorDB); `test_architecture_flowchart.py:125` pins "Neo4j" | ✅ Validated | `writ-architecture-flowchart.html:410` "Neo4j, cached", `:588` "live in a Neo4j graph" (present-tense, no legacy framing); `test_architecture_flowchart.py:125` tuple `("BM25","Tantivy","hnswlib","Neo4j","RRF")` |
| A11 | `session-start-bootstrap.sh` still has live `NEO4J_HOST/PORT`, 7687, `/dev/tcp` probe, `docker compose ... neo4j` | ✅ Validated | `hooks/scripts/session-start-bootstrap.sh:24-25` `NEO4J_HOST`/`NEO4J_PORT=7687`, `:39` `/dev/tcp` bolt probe, `:43` `docker compose -f .../docker-compose.yml up -d neo4j` |
| F1 | Session-start hook NOT scrubbed in Phase 2; `test_session_start_probes_neo4j` passes today asserting 7687 | ✅ Validated | script as A11; `tests/plugin/test_session_start_bootstrap.py:66-79` asserts `"7687" in content` — passes against the still-Neo4j script |
| F2 | Flowchart HTML still says "Neo4j"; that test passes today | ✅ Validated | same as A10 — present-tense current-architecture labels, not historical |
| F4 | `test_import_markdown_unified.py` is a substantive live test, not a comment scrub | ✅ Validated | `:36` config KeyError + `:45-58` `docker exec` cypher helper drive a real count matrix — rewrite, not scrub |
| F5 | `_StubNeo4jSession` stubs a deleted Neo4j-driver `session().run()` shape; confirm whether migrate still drives it | ✅ Validated | `tests/test_phase6bcd_verification.py:300` defines the class; it is **never instantiated/referenced** anywhere (dead code). `run_migration`→`_ingest`→`ingest_path` uses no `.session()` (none in `methodology_ingest.py`/`db.py`). Idempotency rides on source-level `test_migration_uses_merge_not_create :348` (reads `migrate.py` text) |
| L1 | `get_neo4j_*` gone; real getters are `get_falkordb_path/_graph/_module` + `get_redis_bin`, none with covering tests | ✅ Validated | `config.py:49-89` (the four getters); CodeGraph blast-radius reports "no covering tests found" for all four |
| L2 | Restoration `_count()` imports `get_neo4j_*`→ImportError→`pytest.skip`, silently skipping today | ✅ Validated | `test_post_suite_neo4j_restoration.py:37-45` try-import → `pytest.skip("neo4j driver not installed")`; `:48-52` uses `db._driver.session()` |
| L7 | `detect_redundant` raises without sentence-transformers → test needs `skip_redundancy=True` | ✅ Validated | `integrity.py:88-112` (same as A5) |
| L8/G4 | `_execute_query` is synchronous — never `await` it | ✅ Validated | `db.py:162` `def _execute_query` (no `async`); calls sync `self._graph.query(...)` |
| AsyncMock family (L5) | `test_authority.py`, `test_analysis.py` have ZERO neo4j refs and mock via AsyncMock — leave untouched | ✅ Validated | `grep -ci neo4j` = 0 for both; `test_authority.py:245` `mock_db = AsyncMock()`, `test_analysis.py:356` `AsyncMock(spec=LlmAnalyzer)` |
| 8b targets | `test_bootstrap.py` asserts deleted Docker infra (compose exists, docker prereq, starts/waits-for-neo4j, ensure-server compose) | ✅ Validated | `test_bootstrap.py:39-40,70-73,131-138,163-206,244-248`; shipped reality: `bootstrap.sh:61-64,99-107,172-178` (brew/redis/.so), `ensure-server.sh:37` `nohup writ serve` |
| 8a R2-correction | `test_pyproject_packaging.py` "neo4j" is a docstring word, NOT a dependency assertion | ✅ Validated | The assertion (`~:108-112`) checks `requires-python` floor `>=3.11`; "neo4j" appears only in the docstring "(FastAPI, Pydantic v2, neo4j)" |
| A8 loop-scope / R1-R2 (session DB vs module loops) | A session-scoped async `db` can coexist with the module-scoped `loop_scope="module"` consumers in `test_graph_proximity.py` / `test_retrieval.py` | ✅ Validated (with caveat) | See "How loop scope actually resolves here" below. Safe **because** `db.py` has no loop-bound asyncio state; caveat must be recorded so a future async refactor of `db.py` re-opens the risk |
| R4 benchmarks | `bench_targets.py` constructs `IntegrityChecker` single-arg (a construction fix) | ✅ Validated (with caveat) | `bench_targets.py:120` uses the **two-arg** `IntegrityChecker(db._driver, db._database)` AND `:88` builds its own `Neo4jConnection` db fixture + `:28-29` deleted imports + `:42` `pytestmark loop_scope="module"`. Scope is bigger than the spec's one-line framing — see caveat |

**No ❌ Invalidated assumptions.** All 22 rows validated; two carry a plan-affecting caveat (not an invalidation).

## How loop scope actually resolves here (the A8/R1-R2 deep dive)

Plain English: the worry was that one shared database created "once for the whole session" would live on a different internal timer than the two test files that declare their own per-file timers — and that mixing them would crash with "attached to a different loop." This is the classic failure for session-scoped async fixtures. It does **not** happen here, and the reason is concrete enough to state with confidence.

What the code shows:
- **The connection touches no event loop.** `writ/graph/db.py` contains no `asyncio` import, no `await`, no `asyncio.Lock/Event/Queue`, no `get_event_loop`. The only "lock" is a filesystem lockfile (`:100-160`). Its `async def` methods (`clear_all`, `close`, `create_rule`, …) immediately call the **synchronous** `_execute_query` (`:162`, no `async`) → synchronous `self._graph.query(...)`. The "attached to a different loop" error comes from asyncio primitives bound to a specific loop at creation; there are none to bind. So the session connection can be awaited from a fixture/test running on the module loop, the function loop, or the session loop interchangeably.
- **The two module-scoped files barely use the loop anyway.** In `test_graph_proximity.py` the `db`/`cache`/`pipeline_*` fixtures are `@pytest_asyncio.fixture(scope="module", loop_scope="module")`, but every test that consumes them is a **sync `def`** (`:99-271`); the `await`s happen only in fixture setup. `test_retrieval.py` is the same — `pipeline_db` is `scope="module"` (no explicit `loop_scope`), and the pipeline tests are sync `def` (`:103-235`); only two async tests (`:246-257`) build their own inline connection with plain `@pytest.mark.asyncio` (function loop).
- **The function-scoped async tests (e.g. `test_integrity.py`) `await db.create_rule(...)` directly on the function loop.** Still safe for the same reason — no loop affinity on the connection.

The locked design (session-scoped `@pytest_asyncio.fixture(scope="session", loop_scope="session")` connection + function-scoped autouse reset + shared `db`) therefore works. The pragmatic recommendation the plan should carry: build the Component-2 smoke test FIRST (write a node, assert present; run twice, assert empty on the second) and run it together with `test_graph_proximity.py` and `test_retrieval.py` in one invocation to empirically confirm no `ScopeMismatch`/loop error at module-fixture teardown before migrating the other ~10 files. The static evidence says it will pass; the smoke test converts "should" to "does."

**Caveat for the plan (and a future ADR):** this safety is an *implementation property of `db.py`*, not a guarantee of the fixture design. If `db.py` is ever refactored to use a real async redis client (loop-bound transport), a session-scoped fixture consumed by module/function loops would immediately reintroduce the "different loop" failure. Record this as a constraint so the assumption isn't silently broken later.

## Edge Cases & Silent Failure Modes

- **The restoration test un-skips and may fail live (L2).** `test_post_suite_neo4j_restoration.py:37-45` skips today via ImportError. Re-pointing it to FalkorDB runs it for the first time; if methodology ingest has any FalkorDB-specific gap, it fails loudly there. That exposure is intended (spec Component 7b), not a fixture-migration regression.
- **Benchmark files fail at import today** (`bench_targets.py:28-29` import deleted `get_neo4j_*` and `Neo4jConnection`). `pytest tests/benchmarks/` cannot even collect until migrated — relevant to Component 9's "run-no-crash."
- **`docker exec` test silently skips, never asserts.** `test_import_markdown_unified.py:_cypher` calls `pytest.skip` when `docker exec` fails (`:57`) — so on a Docker-free machine the whole matrix skips and protects nothing, while the module-level KeyError (`:36`) blocks collection outright. Both must go.
- **conftest restoration targets PRODUCTION graph, not the temp DB.** `pytest_sessionfinish` runs `writ import-markdown bible/` against `.writ/graph.db`. It is independent of the throwaway test DB and must stay that way (D4/OQ-4).

## Dependencies & Coupling

- The shared `db` fixture is consumed (by name) in ~10 live-DB test files today, each currently building its own `Neo4jConnection`. Consolidating earns its keep (real seam, 2+ consumers).
- `IntegrityChecker` is coupled to `_execute_query`'s `list[dict]` return shape — the same contract the old Neo4j `record.data()` produced (`db.py:162-184`), so count-style helpers keep their downstream shape after re-pointing.
- `benchmarks/` depends on the SAME deleted symbols as `tests/` — migrating one does not fix the other. The benchmark `db` fixture is its own separate wiring.

## Extension Points

- The session fixture is the single seam for DB construction. Future work (e.g. per-worker DBs for `pytest-xdist`) changes only `conftest.py` — but note the one-lockfile-holder constraint (`db.py:147`, L9) blocks parallelism until each worker gets its own temp dir.
- The autouse reset is the isolation primitive. Any test needing cross-test state would have to opt out of it — currently impossible by design (function-scoped autouse), which is the intended safety.

## Open Questions

These are escalated to the user/planner, not resolvable from code alone (carried from the spec's OQ list; code facts that inform them are filled in):

- **OQ-6 (F1):** The active `session-start-bootstrap.sh` still probes Neo4j 7687 and hints `docker compose ... neo4j`. Realigning `test_session_start_probes_neo4j` to "no Neo4j probe" requires scrubbing the **production script** first. The draft's D10 (2026-06-20) folds this into Phase 3 scope ("scrub to match shipped Docker-free reality, then realign the test"). Decision is whether to execute that production edit now — escalated.
- **OQ-7 (F2):** `writ-architecture-flowchart.html` names Neo4j as a *current* pipeline stage (`:410`, `:588`, present-tense). D10 folds the 2-line HTML scrub + the test term change (`"Neo4j"`→`"FalkorDB"`) into Phase 3. Same execute-now judgement.
- **OQ-8 (F4):** Confirm the FalkorDB rewrite of `test_import_markdown_unified.py` preserves its behavior matrix (default / `--only` / `--dry-run` / idempotency / version-bump) without inventing new assertions (G3). The counts it needs can come from `_execute_query` against the relevant graph or a `writ` CLI count — code supports both; which to use is a plan choice.
- **OQ-2 (credential-scan meta-test):** `test_config_integration.py` scans `tests/` for `DEFAULT_NEO4J_PASSWORD` (a secret that no longer exists) and its top-level import of that symbol breaks collection. Retire-vs-reaim is a user call (draft leans retire per D9).
- **OQ-4 (do not act):** Whether `pytest_sessionfinish` is still load-bearing now most tests use a throwaway DB — logic judgement, out of scope. Keep as-is.

## Technical Debt Spotted

- **Benchmark migration is under-scoped in the spec (R4).** Spec Component 9 mentions only `bench_targets.py`'s `IntegrityChecker` construction. In reality `bench_targets.py` also has its own `Neo4jConnection` db fixture (`:88`), `NEO4J_*` constants (`:44-46` region), deleted `get_neo4j_*` imports (`:28-29`), and a module-level `pytestmark loop_scope="module"` (`:42`) — i.e. it needs the full Component-4 treatment, not a one-arg tweak. And **three more benchmark files** carry neo4j refs: `methodology_bench.py`, `run_benchmarks.py`, `scale_benchmark.py`. The plan's "run-no-crash" step must budget for migrating all four, or they fail at collection.
- **Total neo4j surface is 33 files** across `tests/` + `benchmarks/` (vs the spec's "~28" which counts `tests/` only, and STATE.md's stale "13"). Two are incidental: `tests/conftest.py` (the one stale comment) and `tests/fixtures/ground_truth_queries.json` (a query string). The "incidental-only" done-when must scope `grep -ri neo4j` over both `tests/` and `benchmarks/` to be truthful.
- **The loop-scope safety is undocumented and fragile to a future `db.py` async refactor** — see the A8 caveat. Worth an ADR note (the spec already flags Option A as an ADR candidate).

## Invalidated Assumptions

None. All 22 verified assumptions validated. Two carry caveats (A8 loop-scope safety rests on a `db.py` implementation detail; R4 benchmark scope is larger than framed) — recorded above as Technical Debt and in the A8 deep-dive, but neither contradicts a spec claim, so neither is an invalidation. **Planning is not blocked.**
