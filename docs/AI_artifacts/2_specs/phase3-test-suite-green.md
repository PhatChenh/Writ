# Phase 3 — Test Suite Green — Spec

_Tier: MEDIUM. Behavior-inventory prefix: **P3-TEST** (P3-TEST-01..07 in `behavior_inventory.yaml`, granularity: outcome)._
_Design source: `docs/AI_artifacts/1_design/phase3-test-suite-green.md` (Option A LOCKED). Locked decisions D1–D9 + landmines L1–L10 + OQ resolutions: `docs/AI_artifacts/0_draft/phase3-test-suite-green.md`._
_Verified against the live tree on 2026-06-20 via CodeGraph + raw reads. Where this spec contradicts the design/draft, the contradiction is called out as a numbered finding and escalated to Open Questions — it is NOT silently resolved._

---

## Purpose

Phases 1–2 swapped Writ's database engine from Neo4j (a Docker container) to FalkorDBLite (an embedded, file-based engine). Production code already runs on the new engine. The **test suite was left behind**: ~28 test files still import classes/getters that were deleted, build connections to a database that no longer exists, and assert that Docker infrastructure (which Phase 2 deleted) is present. Many of those files can no longer even load.

This phase makes the suite green again **without changing what any still-valid test verifies**. It is plumbing: repoint every test's database handle at one shared throwaway FalkorDBLite instance, delete the dead Neo4j wiring, and realign the small set of tests that assert *deleted Docker/Neo4j behavior* to the Docker-free reality the product actually shipped (decision D9). After this phase, `pytest` is green, `grep -ri neo4j tests/` returns only incidental hits, and the live server still works immediately after a test run.

---

## Already built (reuse, do not rebuild)

| Function / Module | Location | What it does | How this spec uses it | Depth |
|---|---|---|---|---|
| `FalkorDBLiteConnection` | `writ/graph/db.py:79` | New DB client. Constructor `(db_path, graph="writ", module_path="vendor/falkordb.so", redis_bin=...)` spawns a `redis-server` subprocess, loads the FalkorDB module, connects over a Unix socket, waits ~5s. | The single session fixture builds exactly one of these. | deep |
| `FalkorDBLiteConnection._execute_query` | `writ/graph/db.py:162` | The ONLY method that runs a Cypher query and returns `list[dict]`. **Synchronous — never `await` it** (G4/L8). | The post-suite restoration test's `_count()` re-points here. | shallow (1-line interface) |
| `FalkorDBLiteConnection.clear_all` | `writ/graph/db.py:479` | Runs `MATCH (n) DETACH DELETE n`. The between-test reset. `async def`. | The function-scoped autouse reset awaits this. | shallow |
| `FalkorDBLiteConnection.close` | `writ/graph/db.py:483` | Closes the client, terminates the redis subprocess, unlinks the lockfile. `async def`. | The session finalizer awaits this. | shallow |
| `_acquire_lock` | `writ/graph/db.py:147` | Writes the holder PID to `<db_dir>/graph.lock`; raises if a live PID already holds it. One holder per `db_dir` (L9). | Confirms the throwaway temp dir gets its own lock — no collision with prod (G5). | shallow |
| Socket-dir hashing | `writ/graph/db.py:104-109` | Socket path = `/tmp/writ-<md5(db_dir)[:12]>/redis.sock` — unique per `db_dir`. | A unique session temp dir ⇒ a unique socket ⇒ no collision with a running `writ serve` (P3-TEST-04). | — |
| `get_falkordb_path` | `writ/config.py:49` | Returns `falkordb.path` from `writ.toml`, default `".writ/graph.db"` (`DEFAULT_FALKORDB_PATH`, `:22`). | Target of rewritten config tests. **No covering tests today** (L1). | shallow |
| `get_falkordb_graph` | `writ/config.py:55` | Returns `falkordb.graph`, default `"writ"` (`DEFAULT_FALKORDB_GRAPH`, `:23`). | Passed to the session fixture; tested by config rewrite. | shallow |
| `get_falkordb_module` | `writ/config.py:61` | Returns `falkordb.module`, default `"vendor/falkordb.so"` (`DEFAULT_FALKORDB_MODULE`, `:24`). | Passed to the session fixture; tested by config rewrite. | shallow |
| `get_redis_bin` | `writ/config.py:67` | Resolves the redis binary: override → `shutil.which` → arm64 Homebrew default (`:83`) → **`RuntimeError` on x86_64** (`:85`). | Passed to the session fixture; the x86_64 raise path is asserted, not skipped (G6). | shallow |
| `get_hnsw_cache_dir` | `writ/config.py:92` | Returns `hnsw.cache_dir`, expands `~`. **This getter is unchanged and still has live tests** — keep its existing assertions. | Config rewrite KEEPS the hnsw tests verbatim. | shallow |
| `load_config` | `writ/config.py:33` | Parses `writ.toml`, returns `{}` on missing/empty/invalid. Unchanged. | Config rewrite keeps the `load_config` tests, re-pointing the `[neo4j]` section to `[falkordb]`. | shallow |
| `IntegrityChecker` | `writ/graph/integrity.py:19` | Corpus health checks. Constructor is **single-arg** `IntegrityChecker(db)` (`:22`). Public methods are `async def` but call the sync `_execute_query` with no inner await (L8). | `test_integrity.py` constructs with one arg. | deep |
| `IntegrityChecker.run_all_checks` | `writ/graph/integrity.py:248` | Runs all checks. `detect_redundant` raises `RuntimeError` without `sentence-transformers`; `run_all_checks(skip_redundancy=True)` is the supported opt-out (`:248-274`, L7). | `test_integrity.py` passes `skip_redundancy=True` where it exercises `run_all_checks`. | deep |
| `pytest_sessionfinish` | `tests/conftest.py:8` | End-of-suite hook: shells out to `writ import-markdown bible/` against the **production** graph so the live server has the corpus after a run. Already FalkorDB-correct (no Neo4j in its body). | KEEP unchanged (D4/OQ-4). One stale comment ("Neo4j may not be running", `:44`) is scrubbed to "the server". | deep |
| `WRIT_CMD_PREFIX` | `tests/_writ_cmd.py` | Canonical way to invoke the `writ` CLI from a test. | Reused as-is by the rewritten restoration + import-markdown tests. | shallow |
| Existing data-dict fixtures | `tests/conftest.py:51-115` | `valid_rule_data`, `valid_enf_rule_data`, `minimal_rule_data`, etc. No DB, no Neo4j. | Keep verbatim. New fixtures are added alongside them. | shallow |

---

## Feature overview (plain English, happy path then edges)

**Happy path.** One database starts once for the whole test run. A new shared fixture in `tests/conftest.py` builds a single `FalkorDBLiteConnection` pointed at a throwaway temp folder, using the real config getters. Before every individual test, a second fixture (which every test gets automatically) wipes that database clean. Every test that needs a live database asks for the same shared handle by name (`db`). When the run ends, a finalizer closes the connection and the temp folder is discarded. Because the temp folder is unique, the database lives on its own socket and its own lockfile — it never touches or locks the production graph, so you can run the suite while the real server is up.

**The migration.** Today, ~10 test files each build their **own** Neo4j connection fixture and declare their own `NEO4J_URI/USER/PASSWORD` constants; several more build connections inline. The work is to delete all of that duplicated wiring and let each file inherit the one shared `db`. A handful of other files only mention "Neo4j" in comments or docstrings — those get scrubbed. Two config-test files test database settings that no longer exist (they currently skip entirely, protecting nothing) and get rewritten against the four real getters.

**Edge cases.**
- The redundancy integrity check needs an optional ML library; tests opt out with `skip_redundancy=True` (L7).
- The post-suite restoration test was silently *skipping* for years because it imported deleted Neo4j symbols (L2). Re-pointing it un-skips it — it will run live for the first time and may surface a real, pre-existing methodology-ingest gap. That exposure is intended, not a regression of this phase.
- A small group of tests assert that Docker/Neo4j infrastructure **exists** — but Phase 2 deleted it. Those assertions describe the opposite of the shipped product. They are realigned to the Docker-free reality per D9. **Two of these did NOT get scrubbed in Phase 2 and still contain live Neo4j wiring** (the session-start hook script and the architecture-flowchart HTML) — see Findings F1/F2 and Open Questions.

---

## Out of scope

- **New tests / new assertions / changed verification intent on still-valid behavior** — D3/G3. We adapt the storage layer in setup/fixtures only. Handled by: nothing; explicitly excluded.
- **Modifying `writ/retrieval/` source** — frozen (G1). Its docstrings still say "Neo4j" (e.g. `writ/retrieval/traversal.py:1,4,7,26,34`; `pipeline.py:467,507`). Any test that asserts retrieval source is Neo4j-clean must adjust the *test*, never the frozen source (OQ-3 carve-out). Handled by: Finding F3 / OQ-7.
- **The pure-`AsyncMock` test family** — `test_authority.py`, `test_analysis.py` (and any other file with **zero** neo4j references that mocks the `GraphConnection` protocol via `AsyncMock()`). Confirmed grep-clean (L5). Leave untouched.
- **`pytest-xdist` / parallel execution** — one session DB = one lockfile holder (L9). Suite is serial today; parallelism deferred, no phase assigned.
- **Scaffolding `docs/CONSTRAINTS.md` / `TECH_DEBT.md` / `OPEN_QUESTIONS.md`** — OQ-5, explicitly skipped this phase (Phase 4A carryover).
- **Deciding whether the post-suite restoration hook is still load-bearing** — a logic judgement, OQ-4. Keep as-is; do not remove.
- **Re-scrubbing Phase-2 infrastructure that was missed** (the session-start hook's live Neo4j probe, the flowchart HTML's "Neo4j" labels) — these are *production/doc* artifacts, not tests. Whether to scrub them now is escalated (F1/F2/OQ-6/OQ-7); the spec does not assume it.

---

## Constraints

- **G1 · Freeze `writ/retrieval/`** — source: CLAUDE.md "Critical Rules" + draft. Do not edit retrieval source, including its Neo4j-mentioning docstrings.
- **G2 · No production-code change beyond a constructor/import swap** — source: draft. Tests adapt; behavior does not.
- **G3 · Same assertions for still-valid behavior** — source: D3/draft. No new tests, no changed assertions, except the D9 realignment carve-out (deleted Docker/Neo4j behavior only).
- **G4 · Never `await _execute_query`** — source: CLAUDE.md "What AI Gets Wrong" + `db.py:162`. It is synchronous; only the public `async` methods are awaited.
- **G5 · Throwaway temp DB only** — source: D1+D2. Tests never touch or lock `.writ/graph.db`.
- **G6 · Apple-Silicon-only** — source: D9 + `config.py:85`. The config test asserts the x86_64 `RuntimeError` path; it does not skip it.
- **D5 · Delete the misleading reference doc** — `docs/AI_artifacts/0_draft/falkordb-reference.md` describes a fake API Phase 1 never built.
- **asyncio mode is "strict"** (NOT set in `pyproject.toml [tool.pytest.ini_options]`, lines 125-129). Async fixtures MUST be declared `@pytest_asyncio.fixture`, not `@pytest.fixture`. Existing live-DB fixtures already follow this (e.g. `test_integrity.py:53`, `test_authoring.py:26` with explicit `loop_scope="module"`). The shared fixtures must match this convention — source: verified, see Assumptions A8.

---

## Assumptions (research verifies each)

| ID | Assumption | Source | What would prove it wrong |
|----|-----------|--------|---------------------------|
| A1 | `FalkorDBLiteConnection(path, graph, module_path, redis_bin)` is the full constructor signature; passing `get_falkordb_graph()`, `get_falkordb_module()`, `get_redis_bin()` resolves on the dev machine. | db.py:86-92; design "Connection construction facts" | Constructor rejects those args, or the redis subprocess fails to start within 5s on the dev box. |
| A2 | A unique session temp dir yields a unique `/tmp/writ-<hash>` socket + its own lockfile, so the test DB never collides with a running `writ serve`. | db.py:104-109,147 | Two `FalkorDBLiteConnection`s on different dirs share a socket or lockfile. |
| A3 | `clear_all()` (sync `MATCH (n) DETACH DELETE n` under an `async def`) fully resets the graph between tests. | db.py:479-481 | A test sees stale nodes/edges from a prior test after the autouse reset ran. |
| A4 | `IntegrityChecker(db)` is single-arg; the old `IntegrityChecker(db._driver, db._database)` call in `test_integrity.py:64` is the two-arg Neo4j shape that must collapse to one arg. | integrity.py:22; test_integrity.py:64 | The checker requires a second argument, or `db` lacks the attributes its methods use. |
| A5 | `run_all_checks(skip_redundancy=True)` runs the other checks without `sentence-transformers`; `detect_redundant()` raises `RuntimeError` otherwise. | integrity.py:101,248-274 | `skip_redundancy=True` still imports/loads the ML model, or the other checks fail independently. |
| A6 | `writ.toml` has **no** `[neo4j]` section and a `[falkordb]` section; `get_neo4j_*` and `DEFAULT_NEO4J_*` are gone from `writ.config`. | config.py (no neo4j symbols); pyproject.toml:17,44 (`falkordb` dep, no `neo4j` dep) | `from writ.config import get_neo4j_uri` succeeds, or `writ.toml` still has `[neo4j]`. |
| A7 | `pytest_sessionfinish` already targets FalkorDB (no Neo4j in its body); only a stale comment mentions Neo4j. | conftest.py:8-48 | The hook body constructs a Neo4j connection or imports a deleted symbol. |
| A8 | asyncio mode is "strict"; async fixtures need `@pytest_asyncio.fixture`. | pyproject.toml:125-129 (no `asyncio_mode`); existing usage | A `@pytest.fixture async def` collects and runs without warning/error suite-wide. |
| A9 | `test_import_markdown_unified.py` currently fails to *import* because `_writ_config["neo4j"]["password"]` (`:36`) `KeyError`s against the `[neo4j]`-less `writ.toml`, and its live path shells out to `docker exec writ-neo4j cypher-shell` (`:48`). | test_import_markdown_unified.py:33-58 | `writ.toml` still has `[neo4j]`, or that file collects cleanly today. |
| A10 | The architecture-flowchart HTML (`writ-architecture-flowchart.html`) still literally contains "Neo4j" (×2), so `test_architecture_flowchart.py:125` currently **passes**; realigning the test to "FalkorDB" requires also editing the HTML, or the assertion fails. | grep: HTML has 2× "Neo4j", 0× "FalkorDB" | The HTML already says "FalkorDB". |
| A11 | `hooks/scripts/session-start-bootstrap.sh` still contains live `NEO4J_HOST/PORT`, port `7687`, a `/dev/tcp` Neo4j probe, and a `docker compose ... neo4j` hint (`:24-44`) — i.e. Phase 2 did **not** scrub it, contradicting design L10. | grep on the active script | The active script has zero neo4j/7687/docker references. |

> **Three of these (A9, A10, A11) directly contradict claims in the design/draft.** They are escalated as Findings F1/F2 + Open Questions OQ-6/OQ-7/OQ-8 below, not silently absorbed.

---

## Findings that contradict the design/draft (read before planning)

- **F1 — The session-start hook was NOT scrubbed in Phase 2.** Design L10 asserts `session-start-bootstrap.sh` contains "zero docker/neo4j/7687 references." The live `hooks/scripts/session-start-bootstrap.sh` still defines `NEO4J_HOST`/`NEO4J_PORT=7687`, probes bolt via `/dev/tcp`, and prints `docker compose -f .../docker-compose.yml up -d neo4j` (`:24-44`). So `tests/plugin/test_session_start_bootstrap.py::test_session_start_probes_neo4j` (`:66`, asserts `7687` present) **currently passes** against a script that lies about the shipped product. Realigning the *test* to "no Neo4j probe" would make it fail unless the *script* is also scrubbed — which is production-code work D9 did not authorize. → **OQ-6.**
- **F2 — The flowchart HTML still says "Neo4j".** `test_architecture_flowchart.py:125` asserts the doc contains `"Neo4j"` among tech terms, and `writ-architecture-flowchart.html` still contains "Neo4j" ×2 (0× "FalkorDB"). So that test **currently passes**. Realigning it to "FalkorDB" (D9/OQ-3) requires editing the HTML doc too. → **OQ-7.**
- **F3 — `writ/retrieval/` docstrings still say "Neo4j" and are frozen (G1).** No test currently asserts retrieval source is Neo4j-clean (grep found none). If research surfaces one, it must adjust only the test's expectation, never the frozen source. → **OQ-3 carve-out, recorded as OQ flag per instruction.**
- **F4 — `test_import_markdown_unified.py` is a substantive live-DB test the design batched as "comment scrub."** Design Batch 8 lists it among "comment/string-only scrubs," but it reads `_writ_config["neo4j"]["password"]` (`:36` — a `KeyError` today) and its `_cypher()` helper shells out to `docker exec writ-neo4j cypher-shell` (`:44-58`). It needs a real rewrite (read FalkorDB config or use the shared `db`; replace `docker exec` cypher with `_execute_query` or the CLI), not a comment scrub. → handled in Component 7, flagged **OQ-8.**
- **F5 — `_StubNeo4jSession` (`test_phase6bcd_verification.py:300`) stubs a Neo4j-driver `session().run()` shape that no longer exists.** It records Cypher calls to assert migration idempotency (MERGE-not-CREATE). Research must confirm whether `scripts/migrate.py`'s current `run_migration` still drives anything resembling this session shape, or whether the test's idempotency assertion now reads `migrate.py` source directly (the sibling `test_migration_uses_merge_not_create` at `:348` already does source-level audit). → handled in Component 7, flagged **OQ-9.**

---

## Component dependency order

> Components are grouped into the design's verifiable batches. "Verify" = `pytest <files>` collects and passes (or the documented expected fallout). Each component lists what must already exist before it can work — not the order a developer types code (that's `/plan`'s job).

### 1. Delete the misleading reference doc (Batch 0)
**Goal.** Remove a fake-API doc so the implementer subagent can't be misled.
**Build.** Delete `docs/AI_artifacts/0_draft/falkordb-reference.md` (D5/L10).
**Depends on.** None.
**Done when.** The file no longer exists; nothing imports or references it.
→ supports P3-TEST-01 (removes a trap that causes wrong wiring).

### 2. Shared fixture infrastructure in `tests/conftest.py` (Batch 1)
**Goal.** One real test database, started once, wiped clean before every test, shared by name — living in a throwaway folder that never touches production.
**Build.** Add to `tests/conftest.py`, alongside the existing data-dict fixtures:
- A **session-scoped** connection fixture that creates a unique session temp dir and builds `FalkorDBLiteConnection(<tmp>/graph.db, graph=get_falkordb_graph(), module_path=get_falkordb_module(), redis_bin=get_redis_bin())`. Because the public DB methods are `async`, this fixture is async and must be declared `@pytest_asyncio.fixture(scope="session")` with a session-consistent loop scope (per A8; mirror the existing `loop_scope=` usage). It must yield the connection, then on teardown `await conn.close()` and remove the temp dir.
- A **function-scoped, `autouse=True`** reset fixture (also `@pytest_asyncio.fixture`) that depends on the session connection and `await db.clear_all()` before each test. This replaces the per-fixture setup/teardown `clear_all()` pairs the old `db()` fixtures each carried — no test can opt out (mitigates the shared-mutable-DB risk).
- A **shared `db` fixture** (the name every live-DB file already uses) that simply yields the session connection. This is the 1-line interface every migrated file consumes.
- Scrub the one stale comment in `pytest_sessionfinish` (`:44`, "Neo4j may not be running") to reference "the server" — body is otherwise unchanged (KEEP per D4/OQ-4).

**Teardown order (explicit).** Per-test: autouse reset runs at function setup only (clean slate before the test). Session end: `pytest_sessionfinish` runs the prod-graph restoration (independent of the test DB), then the session connection finalizer closes the connection + removes the temp dir. The session fixture's finalizer and `pytest_sessionfinish` are independent; restoration targets prod, teardown targets the temp DB.

**Lockfile handling.** No special handling needed: the unique temp dir gives the test DB its own `graph.lock` and its own `/tmp/writ-<hash>` socket (A2), so a running `writ serve` holding `.writ/graph.lock` does not collide (G5/P3-TEST-04).

**Depends on.** Component 1 (so the implementer isn't reading the fake API).
**Assumes.** A1, A2, A3, A8.
**Interface shape.** Callers see one fixture name, `db`. Hidden behind it: the session connection lifecycle + the autouse reset. Deletion test: removing `db` re-scatters `FalkorDBLiteConnection` construction back into ~10 files — it earns its keep (2+ consumers, real seam).
**Dependency category.** in-process (the real DB is exercised directly, by design D1).
**Done when.** `conftest.py` imports cleanly; a throwaway one-test smoke that requests `db`, writes a node, and asserts it's present collects and passes; running it twice in one session shows the second test starts with an empty graph (autouse reset proved). The temp dir is gone after the session; `.writ/graph.db` is untouched.
→ supports P3-TEST-01, P3-TEST-03 (one startup, shared DB), P3-TEST-04 (no prod lock).

### 3. Config-test full rewrite (Batch 2)
**Goal.** The two config-test files protect the database settings that actually exist, instead of skipping over deleted Neo4j settings.
**Build.** Full rewrite of `tests/test_config.py` and `tests/test_config_integration.py` (D6) against the four real getters. Behavior parity mapping (old Neo4j test → new FalkorDB test):

| Old test (deleted-symbol target) | New rewritten test (real getter) |
|---|---|
| `load_config` returns `[neo4j]` section (`test_config.py:77`) | `load_config` returns `[falkordb]` section (fixtures write `[falkordb]\npath=...\ngraph=...\nmodule=...` instead of `[neo4j]\nuri=...`). |
| `get_neo4j_uri/user/password` default (`:106-119`) | `get_falkordb_path/_graph/_module` default → `DEFAULT_FALKORDB_PATH/_GRAPH/_MODULE` when file missing. |
| `get_neo4j_*` override (`:140-154`) | `get_falkordb_path/_graph/_module` override → values from a `[falkordb]` `writ.toml`. |
| (none — new coverage of an existing untested getter) | `get_redis_bin`: (a) explicit `redis_bin` override in `writ.toml` wins; (b) with no override, `shutil.which("redis-server")` result is returned; (c) on arm64 with neither, the Homebrew default `/opt/homebrew/opt/redis/bin/redis-server` is returned; (d) on x86_64 with neither, it **raises `RuntimeError`** (G6 — assert the raise, do not skip; use `monkeypatch`/patch on `platform.machine` + `shutil.which`). |
| `get_hnsw_cache_dir` default/override/tilde-expand (`:121-175`) | **KEEP verbatim** — this getter is unchanged and still valid. |
| `TestConsumers` importing `get_neo4j_*` (`:183-211`) | Re-point to importing `get_falkordb_path/_graph/_module` + `get_redis_bin` (the surface consumers now read). |
| `test_config_integration.py` "no hardcoded Neo4j URI/password in cli.py/server.py/conftest.py" (`:60-136`) | These guarded a secret that no longer exists. See Component 8 (credential-scan) — retire the credential-literal assertions; the rewrite removes the broken `DEFAULT_NEO4J_PASSWORD` import that currently breaks collection (R3). |
| `TestMissingConfigFallback` / `TestOverridingTomlChangesLoadedValues` (`:214-266`, `[neo4j]` fixtures) | Re-point fixtures to `[falkordb]`; assert path/graph/module fallback + override parity. |

The top-of-file `try: from writ.config import get_neo4j_* … except ImportError: skip` guard (currently making the whole file skip) is replaced by direct imports of the real getters (they exist; no skip).

**Depends on.** None (no DB fixture; self-contained). Independent of Component 2.
**Assumes.** A6.
**Done when.** Both files collect with no skip; running them exercises all four getters including the x86_64 raise; `get_hnsw_cache_dir` tests still pass unchanged; no reference to any `get_neo4j_*` / `DEFAULT_NEO4J_*` / `[neo4j]` remains.
→ supports P3-TEST-05.

### 4. Top-level live-DB fixture files (Batch 3)
**Goal.** Files that declare their own top-level `db()` fixture inherit the one shared `db` instead.
**Build.** For each file below: delete the local `db()` fixture, delete the module-level `NEO4J_URI/USER/PASSWORD = get_neo4j_*()` constants, delete the now-dead imports (`Neo4jConnection`, `get_neo4j_*`), and repoint type hints `db: Neo4jConnection` → `db: FalkorDBLiteConnection`. The file then receives `db` from conftest (Component 2). Where construction is inline rather than a fixture, replace the inline `Neo4jConnection(...)` with the shared `db` fixture (preferred) per file.

In-scope files + their wiring sites (verified):
- `tests/test_infrastructure.py` — constants `:19-21`; local fixture builds `Neo4jConnection(...)` `:27`.
- `tests/test_authoring.py` — constants `:21-23`; module-scoped fixture `:26` builds `Neo4jConnection(...)` `:31`.
- `tests/test_ingest.py` — constants `:23-25`; fixture `:289` builds `Neo4jConnection(...)` `:291`.
- `tests/test_graph_proximity.py` — constants `:25-27`; module-scoped fixtures `:37,63,70,77` build `Neo4jConnection(...)` `:40`. **Note:** these fixtures are `scope="module", loop_scope="module"` — research must confirm a session-scoped shared `db` satisfies their module-scoped consumers, or whether they keep a module-scoped wrapper that yields the shared connection (R1/R2).
- `tests/test_retrieval.py` — constants `:28-30`; module-scoped fixtures `:33,93` build `Neo4jConnection(...)` `:49`; inline construction `:248,258`. Same module-scope caveat.

**Depends on.** Component 2 (shared `db` must exist).
**Assumes.** A1, A2, A3, A8.
**Done when.** Each file collects with no `Neo4jConnection`/`get_neo4j_*`/`NEO4J_*` symbols; its tests pass against the shared throwaway DB; verify one file at a time.
→ supports P3-TEST-01, P3-TEST-02, P3-TEST-03.

### 5. Class-nested live-DB fixture files (Batch 4)
**Goal.** Same consolidation, for files whose `db` fixture is nested inside a test class.
**Build.** For each: delete or repoint the class-nested fixture in favor of the shared conftest `db`; delete constants/imports; repoint type hints.
- `tests/test_compression.py` — `@pytest_asyncio.fixture()` nested at `:230`, builds `Neo4jConnection(get_neo4j_*())` `:235`.
- `tests/test_export.py` — class-nested fixture `:349`, builds `Neo4jConnection(...)` `:354`.

**Depends on.** Component 2.
**Assumes.** A1, A3, A8. **Decisions.** Q: Does either class rely on class-local fixture scope (e.g. shared state across that class's tests) that the function-scoped autouse reset would break? Options: drop entirely / keep a thin class fixture yielding the shared conn. Leaning "drop and inherit" because the autouse reset gives each test a clean graph; confirm per-class (R2).
**Done when.** Both files collect and pass against the shared DB; no nested `db` fixture builds a connection; no neo4j symbols remain.
→ supports P3-TEST-01, P3-TEST-02.

### 6. Integrity tests (Batch 5)
**Goal.** Construct the checker with the real single-arg API and never mis-await the sync query method.
**Build.** In `tests/test_integrity.py`: delete the `NEO4J_*` constants (`:19-21`) and `Neo4jConnection`/`get_neo4j_*` imports (`:15-16`); delete the local `db()` fixture (`:53-59`) in favor of the shared `db`; change the `checker` fixture (`:62-64`) from `IntegrityChecker(db._driver, db._database)` to **`IntegrityChecker(db)`** (single arg, A4); ensure any `run_all_checks` call passes `skip_redundancy=True` (or document that `.[fallback]` is installed) so `detect_redundant` doesn't raise (L7/A5). Public methods stay awaited; `_execute_query` is never awaited (G4).
**Depends on.** Component 2.
**Assumes.** A4, A5, A8.
**Done when.** `test_integrity.py` collects; the checker is built with one argument; redundancy-touching tests pass via `skip_redundancy=True`; no neo4j symbols remain.
→ supports P3-TEST-01.

### 7. Inline-construction + restoration + stub/substantive files (Batches 6–7)
**Goal.** Repoint the remaining files that build connections inline or via deleted Neo4j-driver shapes, and re-point the post-suite restoration test while keeping its behavior contract.

**7a — inline `Neo4jConnection(...)` swaps:**
- `tests/test_session.py` — inline at `:129,195,280` (each `Neo4jConnection(get_neo4j_*())`); fixtures `:119,190,271`. Swap to the shared `db` (preferred).
- `tests/test_embeddings.py` — inline at `:436,498,536`. Swap to the shared `db`.

**7b — post-suite restoration (D4/L2):** `tests/test_post_suite_neo4j_restoration.py`
- **Rename the file** to drop `neo4j` (e.g. `test_post_suite_restoration.py`).
- Re-point `_count()` (`:34-55`): delete the `try: import get_neo4j_*/Neo4jConnection except ImportError: pytest.skip` block (`:37-45`) and the inline `Neo4jConnection(...)` query (`:48-52`). Replace with a direct `FalkorDBLiteConnection` against the **production** graph (`get_falkordb_path()/_graph()/_module()/get_redis_bin()`) that runs `MATCH (n:<label>) RETURN count(n) AS c` via `_execute_query` (sync — no await) and closes. It must NOT use the test fixture — it observes prod state, which is the contract.
- **KEEP the behavior contract:** `test_migrate_restores_skill_nodes` still asserts Skill/Playbook/ForbiddenResponse counts > 0 after `writ import-markdown bible/`; `test_conftest_sessionfinish_does_not_gate_on_count_zero` still pins the no-`if count == 0` gate.
- Scrub the module docstring's "in Neo4j" wording.
- **Expected fallout (document, don't suppress):** un-skipping runs this live for the first time against FalkorDB. If methodology ingest has any FalkorDB-specific gap, it fails loudly here. Flag it to the implementer as a likely first-real-failure site — NOT a fixture-migration failure.

**7c — `test_import_markdown_unified.py` (F4/OQ-8):** This file reads `_writ_config["neo4j"]["password"]` (`:36` — `KeyError` today) and `_cypher()` shells out to `docker exec writ-neo4j cypher-shell` (`:44-58`). Rewrite: drop the `[neo4j]` config read; replace the `docker exec` cypher helper with either `_execute_query` against the relevant graph or a `writ` CLI count, preserving the existing import-markdown behavior matrix (default / `--only` / `--dry-run` / idempotency / version-bump). **This is a substantive rewrite, not a comment scrub** — flagged OQ-8; planner should treat it as its own verify step.

**7d — `_StubNeo4jSession` (F5/OQ-9):** `test_phase6bcd_verification.py:300` stubs a Neo4j-driver `session().run()` shape. Research must confirm what `scripts/migrate.py::run_migration` drives now and whether the stub is still wired into any code path, or whether the idempotency check should lean on the existing source-level `test_migration_uses_merge_not_create` (`:348`). Rename the stub to drop `Neo4j`; repoint or retire its body per that finding. Flagged OQ-9.

**Depends on.** Component 2 (7a uses shared `db`); 7b/7c construct prod-graph connections directly.
**Assumes.** A1, A6, A9.
**Done when.** All listed files collect; inline Neo4j construction is gone; the renamed restoration test runs live (fallout documented); `test_import_markdown_unified` exercises its matrix without `docker exec`/`[neo4j]`; the stub no longer carries the `Neo4j` name or a dead Neo4j-driver shape.
→ supports P3-TEST-01, P3-TEST-02, P3-TEST-07.

### 8. D9 assertion realignment + comment/string scrubs (Batch 8 + Batch 9-gated)
**Goal.** Realign assertions that test *deleted* Docker/Neo4j behavior to the shipped Docker-free/FalkorDB reality (D9), and scrub comment-only "Neo4j" mentions — without changing assertions on still-valid behavior (G3).

**8a — pure comment/docstring scrubs (no assertion change, mechanical):**
- `tests/test_hook_perf_floors.py:46` (comment "warm Neo4j connection pool").
- `tests/test_methodology_ingest.py:4`, `tests/test_phase4_analyze_friction.py:7`, `tests/test_phase4_friction_delta.py:7`, `tests/test_phase6efg_corpus_promotion.py:6,20` (docstring/comment mentions).
- `tests/test_phase3b_export_subagent_roles.py:83,90,92,106` (skip-message strings: "Neo4j not reachable" → FalkorDB equivalent).
- `tests/fixtures/methodology_loader.py:3` (comment).
- `tests/plugin/test_fresh_install_smoke.py:9` (comment "Ensure Docker is running (for Neo4j)").
- `tests/test_pyproject_packaging.py:106` — **comment-only**, not an assertion. The docstring says "(FastAPI, Pydantic v2, neo4j)"; pyproject has a `falkordb` dep and **no** `neo4j` dep. Scrub the comment to "falkordb". (Design R2 over-flagged this as a dependency-name assertion; it is not — the assertion checks the Python floor, not a dep name.)
- `tests/test_phase6bcd_verification.py` docstring/comment mentions at `:5,15,18,80,349` — scrub wording; the `_StubNeo4jSession` rename is handled in 7d.

**8b — D9 realignment of deleted-infra assertions:** `tests/test_bootstrap.py`
- `test_docker_compose_exists` (`:39-40`) asserts `docker-compose.yml` exists — it does NOT (Phase 2 deleted it). Realign to assert it is **absent**, or delete the test as obsolete (it now describes deleted infra).
- `test_bootstrap_checks_docker_prerequisite` (`:70-75`) — bootstrap no longer checks Docker; it checks `brew`/`redis`/`envsubst`/`git`/`python3` (verified in `scripts/bootstrap.sh:61-64,99-107`). Realign to the shipped prerequisites (brew + redis + falkordb.so download), or delete the Docker-specific assertion.
- `test_bootstrap_starts_neo4j_via_compose` (`:131-134`) + `test_bootstrap_waits_for_neo4j` (`:136-138`, port 7687) — bootstrap now ensures Redis + downloads `falkordb.so` (`bootstrap.sh:82-107,169-178`). Realign to assert the Redis-ensure / FalkorDB-module steps, or delete.
- `TestDockerCompose` (`:163-187`, all five tests read the deleted `docker-compose.yml`) — delete the class (obsolete; the file it inspects is gone).
- `TestEnsureServerMigration` (`:195-207`) asserts `ensure-server.sh` uses `docker compose` — it no longer does (it `nohup writ serve`, `ensure-server.sh:37`). Realign to the shipped `writ serve` launch, or delete.
- `test_fails_cleanly_when_docker_missing` (`:244-248`) — the prerequisite list changed; realign to a prerequisite the bootstrap actually checks (e.g. brew or redis), or delete the Docker-specific case.
- **KEEP unchanged:** every still-valid assertion — strict-mode, python3 prerequisite, envsubst, venv, `pip install -e '.[dev]'`, `export_onnx.py`, `install-harness-config.sh`, symlinks, `import-markdown`, `writ serve`, `/health`, ready banner, README tests (all describe shipped behavior).

**8c — D9 realignment, gated on Findings (was Batch 9, the design's BLOCKER):**
- `tests/plugin/test_session_start_bootstrap.py::test_session_start_probes_neo4j` (`:66-80`) — **F1/OQ-6.** The active hook script STILL probes Neo4j 7687, so this test passes today. Realigning the test to "no Neo4j probe" requires scrubbing the script (production work). **Do not edit until OQ-6 is resolved.**
- `tests/test_architecture_flowchart.py:125` — **F2/OQ-7.** Asserts the HTML contains "Neo4j"; the HTML still says "Neo4j", so it passes today. Realigning to "FalkorDB" requires editing the HTML doc. **Do not edit until OQ-7 is resolved.**

**Depends on.** None for 8a (mechanical). 8b depends on the shipped `bootstrap.sh`/`ensure-server.sh` shape (already verified). 8c is BLOCKED on OQ-6/OQ-7.
**Assumes.** A10, A11.
**Done when.** 8a/8b: `grep -ri neo4j tests/` over the scrubbed files reaches incidental-only; `test_bootstrap.py` collects and every retained assertion describes shipped behavior; no test asserts deleted Docker infra exists. 8c: deferred pending OQ resolution.
→ supports P3-TEST-01, P3-TEST-02.

### 9. Full run + benchmarks (Batch 10)
**Goal.** Prove the whole suite is green and the benchmarks don't crash.
**Build.** Run `pytest` (all collect + pass, modulo OQ-6/OQ-7-gated tests and the documented L2 fallout); run `pytest tests/benchmarks/` and `pytest -m perf` run-no-crash (D8). Confirm `benchmarks/bench_targets.py` constructs `IntegrityChecker` with the single-arg API (R4) — if it uses the two-arg shape, that's a benchmark-construction fix (run-no-crash scope, not correctness).
**Depends on.** Components 2–8.
**Assumes.** A4.
**Done when.** P3-TEST-01: `pytest` is green. P3-TEST-02: `grep -ri neo4j tests/` is incidental-only. P3-TEST-06: benchmarks + perf run without crashing. P3-TEST-07: after a run, counting Skill nodes in the production graph (or `/always-on?mode=work`) returns the methodology corpus.
→ supports P3-TEST-01, P3-TEST-02, P3-TEST-06, P3-TEST-07.

---

## Behavior-inventory mapping (every component → success criteria)

| Component | P3-TEST criteria it advances |
|---|---|
| 1 · Delete reference doc | 01 (removes a wiring trap) |
| 2 · Shared conftest fixtures | 01, 03, 04 |
| 3 · Config rewrite | 05 |
| 4 · Top-level fixture files | 01, 02, 03 |
| 5 · Class-nested fixture files | 01, 02 |
| 6 · Integrity tests | 01 |
| 7 · Inline + restoration + stub/substantive | 01, 02, 07 |
| 8 · D9 realignment + scrubs | 01, 02 |
| 9 · Full run + benchmarks | 01, 02, 06, 07 |

P3-TEST-02 ("no neo4j surface") is only fully met once Components 4–8 land **and** OQ-6/OQ-7 resolve (the two carryover artifacts still carry live "Neo4j"). Flag in plan.

---

## Handoff notes

- **Contract with Phase 2 (carryover leak):** Phase 2 was supposed to scrub all Docker/Neo4j infra, but the session-start hook script (F1) and the architecture-flowchart HTML (F2) still carry live Neo4j references. Phase 3 cannot reach a fully clean `grep -ri neo4j tests/` + truthful infra tests without touching those production/doc artifacts — which exceeds "tests only." This is the central decision for the user (OQ-6/OQ-7).
- **Open uncertainty — module-scoped fixtures vs session-scoped shared DB (R1/R2):** `test_graph_proximity.py` and `test_retrieval.py` use `@pytest_asyncio.fixture(scope="module", loop_scope="module")`. A session-scoped shared `db` with a function-scoped reset may interact with their module-scoped consumers and module-level event loops. Research must confirm the asyncio loop-scope wiring before the fixture shape is finalized.
- **Suggested research:**
  1. Confirm the project's `pytest-asyncio` loop-scope behavior (A8) by writing the smoke test in Component 2 and observing whether a session async fixture + module-scoped consumers share a loop without "attached to a different loop" errors.
  2. Trace `scripts/migrate.py::run_migration` to resolve F5/OQ-9 — does anything still consume a Neo4j-driver session shape?
  3. Confirm `test_import_markdown_unified.py`'s behavior matrix can be expressed without `docker exec` (F4/OQ-8) — what counts does it need, and can `_execute_query` or a `writ` CLI subcommand supply them?
  4. Confirm `benchmarks/bench_targets.py` constructs `IntegrityChecker` single-arg (R4).
- **Data-format note:** `_execute_query` returns `list[dict]` with string keys (`db.py:162-184`) — the same contract the old Neo4j `record.data()` produced, so count-style helpers (`_count`, `_cypher`) keep the same downstream shape after re-pointing.

---

## Open questions (deferred — resolve in research/planning or with the user)

- **OQ-3 (carve-out flag, per instruction):** No test currently asserts `writ/retrieval/` docstrings are Neo4j-clean (grep found none). If research surfaces one, adjust only the **test's** expectation — the frozen retrieval source keeps its "Neo4j" docstrings (G1). Flagged as required by the task.
- **OQ-6 (was the design's BLOCKER, now sharpened by F1):** The active `hooks/scripts/session-start-bootstrap.sh` still probes Neo4j bolt 7687 and hints `docker compose ... neo4j` — Phase 2 did NOT scrub it. `test_session_start_bootstrap.py::test_session_start_probes_neo4j` therefore passes today against a script that contradicts the shipped Docker-free product. D9 authorizes realigning the *test*, but the test can only assert "no Neo4j probe" if the *script* is scrubbed first — production-code work outside "tests only." Decision needed: (a) scrub the script too (Phase-2 carryover) and realign the test, or (b) leave both and accept the suite documents a not-yet-removed Neo4j probe. Recommendation: bundle with OQ-7 as a Phase-2 carryover and scrub both, since the alternative is a suite that asserts the product still uses Neo4j.
- **OQ-7 (F2):** `writ-architecture-flowchart.html` still lists "Neo4j"; `test_architecture_flowchart.py:125` passes asserting it. Realign to "FalkorDB" (per D9/OQ-3) → requires editing the HTML doc. Same carryover judgement as OQ-6. Recommendation: update the HTML doc to "FalkorDB" and the test expectation together.
- **OQ-8 (F4):** `test_import_markdown_unified.py` is a substantive live test (reads `[neo4j]` config — `KeyError` today — and `docker exec writ-neo4j cypher-shell`), not the comment scrub the design batched it as. Confirm the rewrite path (FalkorDB `_execute_query` vs `writ` CLI counts) preserves its behavior matrix without inventing new assertions (G3).
- **OQ-9 (F5):** `_StubNeo4jSession` stubs a Neo4j-driver session shape. Confirm whether `run_migration` still drives anything resembling it, or whether the idempotency contract now rides entirely on the source-level `test_migration_uses_merge_not_create`. Rename + repoint/retire accordingly without changing the idempotency intent.
- **OQ-2 (credential-scan meta-test, from design):** `TestRepoWideNoHardcodedCreds` (`test_config_integration.py:179`) scans `tests/` for `DEFAULT_NEO4J_PASSWORD` — a secret that no longer exists; the import that drives it (`:19-27`) breaks collection (R3). Design recommends **retiring** the credential-specific assertions (lowest-risk under the locks) and noting a follow-up "no raw-connection-in-tests" guard for a later phase. Confirm retire-vs-reaim with the user; do not write a new guard this phase (G3).
- **OQ-4 (do NOT act this phase):** Is `pytest_sessionfinish` still load-bearing now that most tests use a throwaway DB? Logic judgement, out of scope. Keep as-is; record as a later-phase cleanup candidate.
- **OQ-5 (skip this phase):** Scaffolding `docs/CONSTRAINTS.md` / `TECH_DEBT.md` / `OPEN_QUESTIONS.md` — Phase 4A carryover. Do not scaffold.
- **ADR candidate (flag only):** Option A (session-scoped real DB + autouse reset) meets the ADR gates (hard to reverse once ~10 files depend on it; surprising without the ~5s-startup context; genuine alternatives existed). Recommend authoring in the `/architecture-docs` step — not here.
