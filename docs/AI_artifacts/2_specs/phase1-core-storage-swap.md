# Phase 1 — Core Storage Swap (Neo4j → FalkorDBLite)

> Produced 2026-06-19. Input: design doc `docs/AI_artifacts/1_design/phase1-core-storage-swap.md`, decisions D1–D11 (`docs/AI_artifacts/0_draft/phase1-decisions.md`), FalkorDB reference (`docs/AI_artifacts/0_draft/falkordb-reference.md`), live code via CodeGraph.

---

## Purpose

Replace the Neo4j database driver with FalkorDBLite — an embedded Python graph database that requires no Docker, no ports, and no separate process. After this phase, Writ can start, load rules, and answer queries using a single `.writ/graph.db` file stored inside the project. The retrieval pipeline, API endpoints, and CLI produce identical outputs — only the storage engine underneath changes.

This phase covers the `writ/` package core (7 files). Scripts (`scripts/`), tests (`tests/`), and benchmarks are not in scope — those are Phases 2 and 3.

---

## Already Built (reuse, do not rebuild)

These exist today and must be used as-is. The downstream planner should not duplicate or rewrite them.

| Symbol / Module | Location | What it does | How Phase 1 uses it | Depth |
|-----------------|----------|--------------|---------------------|-------|
| `GraphConnection` Protocol | `writ/graph/db.py:66` | 5-method interface: `get_rule`, `create_rule`, `create_edge`, `traverse_neighbors`, `close` | `FalkorDBLiteConnection` implements this unchanged; all callers type-hint against the Protocol, not the concrete class | shallow |
| `_coerce_neo4j_value()` | `writ/graph/db.py:~50` | Serializes Python dicts/lists to JSON strings so they can be stored as graph node properties | Still called by every `create_rule` and `create_methodology_node` method body; FalkorDB also cannot store nested maps | deep |
| `ALLOWED_EDGE_TYPES`, `METHODOLOGY_NODE_LABELS`, `METHODOLOGY_NODE_ID_FIELDS` | `writ/graph/db.py` module-level | Validation sets for edge types and methodology node labels | Identical validation logic in new class — constants stay | shallow |
| `load_config()` | `writ/config.py:30` | Loads `writ.toml` via `tomllib`; returns dict; returns `{}` if file missing | New `get_falkordb_path()` and `get_falkordb_graph()` call this, just as old `get_neo4j_*()` did | shallow |
| `get_hnsw_cache_dir()` | `writ/config.py:64` | Reads `[hnsw] cache_dir` from config with path expansion | Unchanged — `build_pipeline` still calls it; no Neo4j coupling | shallow |
| `AdjacencyCache` | `writ/retrieval/traversal.py:23` | In-memory cache of all graph edges, loaded once at startup | `build_from_db()` at line 60 has one reach-through site — gets the mechanical `_execute_query()` swap | deep |
| `RetrievalPipeline` | `writ/retrieval/pipeline.py:175` | 5-stage in-memory query engine (BM25 + ANN + graph proximity + RRF) | Completely unchanged — receives pre-built indexes, never touches DB at query time | deep |
| `build_pipeline()` | `writ/retrieval/pipeline.py:488` | Startup loader: reads rules and methodology nodes from DB, builds BM25/vector indexes, warms adjacency cache | Has 2 reach-through sites (lines 514, 532) and calls `adjacency_cache.build_from_db(db)` — those 3 get mechanical swaps; everything else unchanged | deep |
| `IntegrityChecker` | `writ/graph/integrity.py:19` | Runs 8 integrity checks (conflicts, orphans, stale, redundant, etc.) against the graph | Constructor changes from `(driver, database)` to `(db: FalkorDBLiteConnection)`. All 9 raw-session call sites become `_execute_query()` calls | deep |
| `lifespan()` context manager | `writ/server.py:135` | FastAPI startup/shutdown — creates DB connection, builds pipeline, closes DB | Constructor call changes from `Neo4jConnection(uri, user, pwd)` to `FalkorDBLiteConnection(path, graph)`. Lockfile acquire/release added here (D10) | shallow |
| `writ.toml` config file | `writ.toml` | Runtime tunable parameters for retrieval, authority, context budget, ranking | `[neo4j]` section replaced with `[falkordb]` section — all other sections (`[ranking]`, `[authority]`, `[context_budget]`, etc.) unchanged | shallow |

---

## Q1 Diagram — What changes inside Phase 1

```
┌─────────────────────────────────────────────────────────────────────┐
│ Phase 1 Scope                                                       │
│                                                                     │
│  writ.toml            pyproject.toml          .gitignore            │
│  [neo4j] ──────►  [falkordb]   neo4j pkg ──► falkordblite  add .writ/│
│                                                                     │
│  writ/config.py                                                     │
│  get_neo4j_*() ──────────────────────► get_falkordb_path/graph()   │
│                                                                     │
│  writ/graph/db.py                                                   │
│  Neo4jConnection ────────────────────► FalkorDBLiteConnection       │
│  + _execute_query() [NEW]                                           │
│  + lockfile logic [NEW]                                             │
│  22 internal method bodies rewritten                                │
│                                                                     │
│  writ/graph/integrity.py                                            │
│  __init__(driver, db) ───────────────► __init__(db: FalkorDBLiteConn)│
│  9 raw-session bodies ───────────────► _execute_query() calls       │
│  duration() query ───────────────────► localdatetime($cutoff) param │
│                                                                     │
│  writ/retrieval/pipeline.py   (3 reach-through sites)              │
│  db._driver.session(...) ────────────► db._execute_query(...)       │
│  (lines 514, 532 in build_pipeline, plus adjacency_cache.build)     │
│                                                                     │
│  writ/retrieval/traversal.py  (1 reach-through site)               │
│  db._driver.session(...) ────────────► db._execute_query(...)       │
│  (line 60 in AdjacencyCache.build_from_db)                         │
│                                                                     │
│  writ/server.py               (constructor + lockfile)              │
│  Neo4jConnection(uri,u,p) ───────────► FalkorDBLiteConnection(path) │
│  6 session sites ────────────────────► db._execute_query()          │
│                                                                     │
│  writ/cli.py                  (constructor + 2 sites)               │
│  IntegrityChecker(driver,db) ────────► IntegrityChecker(db)         │
│  1 direct session site ──────────────► db._execute_query()          │
│                                                                     │
│  NOT TOUCHED: retrieval/ranking.py, keyword.py, embeddings.py,      │
│               session.py, graph/schema.py, graph/ingest.py,         │
│               gate.py, .claude/hooks/, bible/                       │
└─────────────────────────────────────────────────────────────────────┘
```

## Q2 Diagram — How Phase 1 connects to the system

```
                    ┌────────────────────┐
                    │  bible/ (corpus)   │
                    │  (unchanged)       │
                    └────────┬───────────┘
                             │ writ ingest
                             ▼
 ┌──────────────┐    ┌──────────────────────────────────┐
 │ writ.toml    │───►│  writ/graph/db.py                │
 │ [falkordb]   │    │  FalkorDBLiteConnection           │◄── Phase 1
 │ path/graph   │    │  + _execute_query()              │
 └──────────────┘    └─────────────┬────────────────────┘
                                   │ DB ops
                      ┌────────────▼───────────┐
                      │  .writ/graph.db         │◄── Phase 1
                      │  (FalkorDBLite file)    │
                      └────────────────────────┘
                                   │
              ┌────────────────────▼────────────────────┐
              │  build_pipeline() [retrieval/pipeline.py]│
              │  + AdjacencyCache.build_from_db()        │
              │  (3 reach-through sites: mech. swap)     │◄── Phase 1 touches
              └────────────┬────────────────────────────-┘
                           │ in-memory indexes
                           ▼
              ┌────────────────────────────┐
              │  RetrievalPipeline         │
              │  (5-stage, pure in-memory) │ ◄── UNTOUCHED
              └────────────┬───────────────┘
                           │
              ┌────────────▼────────────────┐
              │  writ/server.py (FastAPI)   │◄── Phase 1: constructor
              │  lifespan + 6 query sites   │    + lockfile + 6 sites
              └────────────────────────────-┘
                           │
              ┌────────────▼────────────────┐
              │  writ/cli.py                │◄── Phase 1: constructor
              │  IntegrityChecker + 1 site  │    + 2 sites
              └─────────────────────────────┘
                           │
              ┌────────────▼────────────────┐
              │  scripts/ + tests/          │◄── Phase 2 + Phase 3
              │  (out of scope here)        │    (import swaps)
              └─────────────────────────────┘
```

---

## Feature Overview

The core idea is: everywhere Neo4j was opened as a network session (`async with driver.session(...)`), those 4 lines become one call (`await db._execute_query(cypher, params)`). The new `_execute_query()` method handles the FalkorDB-specific result format internally — FalkorDB returns positional tuples, not named records, so the method normalizes everything into `list[dict]` before returning. All existing code that reads `rows[0]["field_name"]` then continues to work unchanged.

**Happy path — server startup:**

1. Server reads `[falkordb]` from `writ.toml` to get the DB file path.
2. `FalkorDBLiteConnection` acquires a lockfile (`.writ/graph.lock`), then opens the DB file (starting FalkorDB's managed Redis subprocess), selects the graph, and applies constraints/indexes (idempotent via try/except — no `IF NOT EXISTS` in FalkorDB).
3. `build_pipeline()` calls `_execute_query()` to load rules and methodology nodes into memory, builds BM25 and vector indexes, warms the adjacency cache. (This replaces the three `async with db._driver.session(...)` blocks at lines 514, 532, and inside `AdjacencyCache.build_from_db()`.)
4. All five retrieval stages run purely in-memory from that point on — the graph DB is not touched during query time.

**Happy path — server shutdown:**

1. FastAPI lifespan exits: `await db.close()` shuts down the FalkorDB subprocess.
2. Lockfile is released.

**Happy path — CLI command while server is not running:**

1. CLI checks lockfile — not held, proceeds.
2. Opens `FalkorDBLiteConnection`, does work (ingest/export/validate), closes.

**Edge case — CLI command while server is running:**

1. CLI checks lockfile — held by server. Prints "server is running — stop it or use HTTP API." Exits with code 1.

**Cypher rewrites needed (special cases beyond mechanical swap):**

- Methods using `datetime()` (Neo4j native) must pass the current timestamp as a Python-computed ISO string param and use `localdatetime($ts)` in the Cypher.
- Methods using `SHOW INDEXES` / `SHOW CONSTRAINTS` become `CALL db.indexes()` / `CALL db.constraints()`.
- Constraint creation uses FalkorDB's Python API (`create_node_range_index()`, `create_node_unique_constraint()`) or Redis commands — not Cypher.
- Index creation drops `IF NOT EXISTS` and named-index syntax; each creation is wrapped in try/except that swallows "already exists" errors.

---

## Out of Scope

- **`scripts/` directory** — all seed scripts and instrumentation tools import `Neo4jConnection` and `get_neo4j_*()`. These are a mechanical import swap deferred to Phase 2.
- **`tests/` and `benchmarks/`** — test fixtures mock Neo4j today. Updating them is Phase 3's entire scope.
- **`docker-compose.yml` and bootstrap shell scripts** — removing Docker from the bootstrap flow is Phase 2.
- **Retrieval pipeline logic** — the 5-stage query algorithm, RRF weights, scoring, BM25 field boosts, and vector search are completely off-limits during Phase 1. The only touches to `writ/retrieval/` are mechanical 4-line-to-1-line substitutions at the 3 reach-through sites.
- **`writ/graph/schema.py`** — Pydantic models define all node/edge types and are unchanged.
- **`writ/graph/ingest.py`** — Markdown parser calls `db.create_rule()` / `db.create_edge()` (public API), not internals. Unchanged.
- **New public methods on `FalkorDBLiteConnection`** — only the existing 5 Protocol methods are public. `_execute_query()` is private infrastructure.
- **`writ/gate.py`, `writ/authoring.py`, `writ/export.py`, `writ/frequency.py`** — none have DB coupling. Unchanged.

---

## Constraints

From CLAUDE.md, CODEBASE.md, and the decisions registry:

- **Do not touch retrieval logic** — only the 3 reach-through startup-loading sites in `writ/retrieval/` change. Zero changes to the 5-stage query algorithm. Source: CLAUDE.md Critical Rules.
- **All 282 tests must pass** — the test suite is the correctness contract. Source: CLAUDE.md Critical Rules, project-design.md principle 4.
- **No sync I/O in hot path** — all retrieval stages use pre-warmed in-process indexes. `_execute_query()` is only called at startup and in CLI/server background operations. Source: invariant PERF-IO-001 in CODEBASE.md.
- **GraphConnection Protocol stays unchanged** — 5 methods, identical signatures. Source: D4 (strict behavior preservation), design doc.
- **Stay async** — 80+ callers use `await`. FalkorDBLite's async API must be used (`AsyncFalkorDB`). Source: D5.
- **No backward-compat shims** — `get_neo4j_*()` functions are deleted outright; `Neo4jConnection` is renamed without alias. Loud import failures on any missed reference are the desired behavior. Source: D8, D9.
- **Single accessor via lockfile** — CLI and server must not open the same DB file simultaneously. Source: D10.
- **`_execute_query()` is Cypher-only** — constraint creation (which uses Redis commands, not Cypher) stays encapsulated inside `apply_constraints()`. Source: D7.
- **Python ≥3.12** — FalkorDBLite hard requirement. `pyproject.toml` must bump `requires-python`. Source: D1.
- **Ranking weights must sum to 1.0** — `writ.toml [ranking]` section is untouched. Source: invariant 7 in CODEBASE.md.

---

## Assumptions

Claims about existing code this spec depends on. Research verifies each one before planning proceeds.

| ID | Assumption | Source implication | What would prove it wrong |
|----|-----------|-------------------|--------------------------|
| A1 | `AsyncFalkorDB` is the correct async import path (`from redislite.async_falkordb_client import AsyncFalkorDB`) | FalkorDB reference doc, D5 | A different module path in the installed `falkordblite` package |
| A2 | `QueryResult.header` exposes column names as a list in the same order as `RETURN` aliases, enabling `dict(zip(header, row))` in `_execute_query()` | FalkorDB reference doc ("likely via result.header") | Header is None, absent, or uses a different attribute name |
| A3 | `SET r += $props` (bulk property update) works in FalkorDBLite Cypher | decisions doc open question; falkordb-reference marks it "VERIFY" | FalkorDBLite rejects `+=` — would require per-property `SET r.field = $val` statements |
| A4 | `RETURN r` (returning a full node) gives a Node object from which properties can be extracted, OR explicit property listing is required | design doc "Returning Full Nodes" section | Affects `get_rule()`, `get_all_rules()`, `get_rules_by_authority()`, and `build_pipeline()` lines 516/535 — shapes whether `_execute_query()` auto-extracts or queries change |
| A5 | `collect(r {.*})` map projection works in FalkorDBLite | design doc open question 2; falkordb-reference marks it "VERIFY" | Would require rewriting `get_abstraction()` to list properties explicitly |
| A6 | The async `Graph` object (returned by `db.select_graph()`) exposes `create_node_unique_constraint()` and `create_node_range_index()` methods | FalkorDB reference doc (sync API confirmed; async assumed) | Only the sync `FalkorDB` has these methods — `apply_constraints()` must fall back to raw Redis commands |
| A7 | `CALL db.constraints()` procedure exists and returns constraint status | FalkorDB reference doc procedures table | Procedure absent — `list_constraints()` must use a different approach or return empty |
| A8 | FalkorDBLite does NOT already maintain a pidfile that rejects a second opener | decisions doc D10 research question | FalkorDBLite/redislite uses a pidfile — D10 lockfile can be simplified to just checking that file |
| A9 | The "already exists" error message from FalkorDBLite on duplicate index/constraint creation contains the substring "already exist" (case-insensitive) | D11 | A different message string — D11's broad catch + message check swallows wrong errors |
| A10 | `build_pipeline()` receives `db: Neo4jConnection` type-annotated — changing the type annotation to `db: GraphConnection` (or `FalkorDBLiteConnection`) is the only annotation change needed in `writ/retrieval/pipeline.py` | CodeGraph: `build_pipeline` signature at line 488–492 | Other annotation references to `Neo4jConnection` exist in pipeline.py |

---

## Component Dependency Order

Build these in order. Each component unlocks the next.

---

### 1. Python version and package dependency

**Goal.** Declare FalkorDBLite as the graph library and remove Neo4j. This is a prerequisite for any import to succeed.

**Build.** In `pyproject.toml`:
- Change `requires-python` from `>=3.11` to `>=3.12`.
- Remove `neo4j` from `dependencies`.
- Add `falkordblite` (latest available version, currently v0.10.0) to `dependencies`.

In `writ.toml`:
- Delete the `[neo4j]` section (uri, user, password).
- Add `[falkordb]` section with `path = ".writ/graph.db"` and `graph = "writ"`.

In `.gitignore`:
- Add `.writ/` so the per-project graph data file and lockfile are not committed.

**Depends on.** None — first change.

**Done when.** Running `pip install -e ".[dev]"` in a Python 3.12 environment succeeds. Running `python -c "from redislite.async_falkordb_client import AsyncFalkorDB"` succeeds. Running `python -c "import neo4j"` fails (neo4j not installed).

---

### 2. Config functions

**Goal.** Replace the three Neo4j config helpers with two FalkorDB ones, so the rest of the codebase has a single place to read the new connection parameters.

**Build.** In `writ/config.py`:
- Delete `DEFAULT_NEO4J_URI`, `DEFAULT_NEO4J_USER`, `DEFAULT_NEO4J_PASSWORD` constants.
- Delete `get_neo4j_uri()`, `get_neo4j_user()`, `get_neo4j_password()` functions.
- Add `DEFAULT_FALKORDB_PATH = ".writ/graph.db"` and `DEFAULT_FALKORDB_GRAPH = "writ"` constants.
- Add `get_falkordb_path(path=None) -> str` that reads `cfg["falkordb"]["path"]` with fallback to the default constant.
- Add `get_falkordb_graph(path=None) -> str` that reads `cfg["falkordb"]["graph"]` with fallback to the default.
- Keep `load_config()` and `get_hnsw_cache_dir()` exactly as-is.

**Depends on.** Component 1 (package installed so imports work).

**Assumes.** None — config functions have no DB-level behavior.

**Interface shape.** Two new functions with the same signature pattern as the old ones. Callers swap `get_neo4j_uri()` → `get_falkordb_path()`, `get_neo4j_user()` / `get_neo4j_password()` → `get_falkordb_graph()`. No other interface changes.

**Done when.** `from writ.config import get_falkordb_path, get_falkordb_graph` succeeds. `from writ.config import get_neo4j_uri` raises `ImportError`. `get_falkordb_path()` returns `".writ/graph.db"` when `writ.toml` has no `[falkordb]` section.

---

### 3. `FalkorDBLiteConnection` class and `_execute_query()` helper

**Goal.** Replace `Neo4jConnection` with `FalkorDBLiteConnection` — the load-bearing change. Every DB operation flows through this class.

**Build.** In `writ/graph/db.py`:

- Remove the Neo4j import block (`from neo4j import AsyncGraphDatabase, AsyncDriver`).
- Add FalkorDB import (`from redislite.async_falkordb_client import AsyncFalkorDB`).
- Rename `Neo4jConnection` to `FalkorDBLiteConnection`.
- Replace the constructor: old `(uri, user, password, database="neo4j")` becomes `(path: str, graph: str = "writ")`. Constructor body: `self._db = AsyncFalkorDB(path)`, `self._graph = self._db.select_graph(graph)`.
- Add `_execute_query(cypher, params=None) -> list[dict]` private async method (see design doc for exact implementation). This is the ONLY place that knows about FalkorDB's positional-tuple result format. It maps column headers to values and returns `list[dict]`.
- Rewrite all 22 internal method bodies. Each `async with self._driver.session(...) as session` block becomes `rows = await self._execute_query(query, params)`. Extraction changes from `record["field"]` to `rows[0]["field"]`.
- Special-case rewrites (see design doc "Method-by-Method Migration Pattern"):
  - `increment_positive()` / `increment_negative()`: pass current ISO timestamp from Python as `$ts` param; Cypher uses `localdatetime($ts)`.
  - `apply_constraints()`: index creation via `self._graph.create_node_range_index(...)` wrapped in try/except; constraint creation via `self._graph.create_node_unique_constraint(...)` wrapped in try/except. Error swallowing matches D11 pattern: catch `Exception`, check `"already exist" in str(e).lower()`, re-raise otherwise.
  - `list_constraints()`: use `CALL db.constraints()` procedure.
  - `list_indexes()`: use `CALL db.indexes()` procedure.
  - `get_abstraction()`: if `collect(r {.*})` map projection is verified unsupported (see A5), rewrite to explicit property list.
  - Node-returning queries (`get_rule()`, `get_all_rules()`, etc.): behavior depends on A4 verification — either `_execute_query` auto-extracts Node properties, or queries list properties explicitly.
- `GraphConnection` Protocol at line 66 stays byte-for-byte identical (5 methods, same signatures).
- Module-level constants (`ALLOWED_EDGE_TYPES`, `METHODOLOGY_NODE_LABELS`, `METHODOLOGY_NODE_ID_FIELDS`, `_coerce_neo4j_value()`) stay unchanged.

**Depends on.** Components 1 and 2.

**Assumes.** A1 (import path), A2 (header attribute), A3 (SET +=), A4 (full-node RETURN), A5 (map projection), A6 (async constraint API), A7 (CALL db.constraints), A9 (error message string).

**Interface shape.**
- Public interface (Protocol): unchanged — 5 methods with identical signatures.
- Private addition: `_execute_query(cypher: str, params: dict | None = None) -> list[dict]` (async). Not in Protocol — internal bridge only.
- Constructor: callers now pass `path` and `graph` instead of `uri`, `user`, `password`.

**Dependency category.** Local-substitutable — tests can pass a FalkorDBLiteConnection backed by a temp file path; no network dependency.

**Decisions.**
- Q: If `RETURN r` (full node) doesn't return a dict-compatible object, should `_execute_query` detect Node objects and auto-extract properties, or should all affected queries be rewritten to list properties explicitly? Options: auto-detect in `_execute_query` (one fix, zero query changes) / explicit field list per query (more surgery, but transparent). Leaning auto-detect because it contains the change to one method. Research confirms which path applies.
- Q: Does `SET r += $props` work? If not, `create_rule()` and `create_methodology_node()` must unroll `$props` to individual `SET r.field = $val` statements. No design impact — contained in these two methods.

**Done when.** `FalkorDBLiteConnection` can be imported from `writ.graph.db`. A test that creates a connection to a temp path, calls `create_rule({...})`, then calls `get_rule(rule_id)`, returns the original rule data. All 22 public method paths execute without raising (against an empty graph for creates, and against a populated graph for reads).

---

### 4. Lockfile mechanism

**Goal.** Prevent the server and CLI from opening the same database file simultaneously, which would cause data corruption.

**Build.** The lockfile lives at `.writ/graph.lock` (adjacent to `.writ/graph.db`).

In `writ/graph/db.py` (the `FalkorDBLiteConnection` class):
- On construction (or in a dedicated `acquire_lock()` method): write the current process PID to `.writ/graph.lock`. If the file already exists and the PID in it is still running, raise a clear error: "Writ graph DB is locked by PID N. Stop the server or use the HTTP API."
- On `close()`: delete the lockfile.

In `writ/server.py` (`lifespan`):
- The `FalkorDBLiteConnection` constructor handles lock acquisition. `lifespan` calls `db = FalkorDBLiteConnection(get_falkordb_path(), get_falkordb_graph())` — lock acquired.
- On shutdown: `await db.close()` — lock released.

In `writ/cli.py` (before any command that opens a DB connection):
- Construct `FalkorDBLiteConnection` — if lockfile is held, the constructor raises the clear error. CLI catches it, prints the message, exits with code 1.

**Depends on.** Component 3 (class exists).

**Assumes.** A8 (FalkorDBLite doesn't already have its own pidfile that handles this).

**Decisions.**
- Q: Should lock acquisition be in the constructor (always on) or in an explicit `acquire_lock()` call? Options: constructor (simpler, no one forgets) / explicit call (more control in tests). Leaning constructor — tests that use a temp path won't conflict with each other anyway. Research verifies if FalkorDBLite's own subprocess startup already prevents double-open (A8).

**Done when.** Starting `writ serve`, then running `writ ingest bible/` in a second terminal, produces a human-readable error message in the second terminal mentioning the server is running. After stopping the server, `writ ingest bible/` in the same terminal succeeds.

---

### 5. Reach-through site swaps in `writ/retrieval/`

**Goal.** Replace the 3 Neo4j-specific session-opening calls in the retrieval module with `_execute_query()` calls. These are the only changes to `writ/retrieval/` — no logic changes.

**Build.** Two files. All changes are mechanical 4-lines-to-1-line substitutions:

In `writ/retrieval/pipeline.py` (`build_pipeline` function, lines 514 and 532):
- Line 514 block: `async with db._driver.session(...) as session: result = await session.run(query)` → `rows = await db._execute_query(query)`. Iterate `rows` directly (already a list).
- Line 532 block: same pattern, inside the methodology-node loading loop.
- Update the type annotation of `build_pipeline`'s `db` parameter from `Neo4jConnection` to `GraphConnection` (the Protocol). This is the only annotation change in this file.

In `writ/retrieval/traversal.py` (`AdjacencyCache.build_from_db()`, line 60):
- The `async with db._driver.session(...) as session: ...` block → `records = await db._execute_query(query)`.
- The subsequent `records` list iteration is identical — result shape is already `list[dict]` after `_execute_query`.

**Depends on.** Component 3 (`_execute_query()` exists).

**Assumes.** A10 (no other `Neo4jConnection` annotation in pipeline.py).

**Done when.** `build_pipeline(db)` completes without error when `db` is a `FalkorDBLiteConnection`. The adjacency cache populates (non-zero size). Retrieval pipeline returns results for a test query.

---

### 6. `IntegrityChecker` constructor refactor

**Goal.** Make `IntegrityChecker` accept the connection object instead of a raw Neo4j driver, so all its 9 check methods can use `_execute_query()`.

**Build.** In `writ/graph/integrity.py`:

- Replace `__init__(self, driver: AsyncDriver, database: str = "neo4j")` with `__init__(self, db: FalkorDBLiteConnection)`.
- Store `self._db = db`. Remove `self._driver` and `self._database`.
- Rewrite all 9 method bodies: `async with self._driver.session(database=self._database) as session: result = await session.run(...)` → `rows = await self._db._execute_query(cypher, params)`.
- `detect_stale()`: the date-comparison logic (lines 66–78) uses Python-side date arithmetic and checks ISO strings — that logic stays. The query itself is unchanged (uses `IS NULL` / `IS NOT NULL` checks, no `datetime()` call).
- `detect_frequency_stale()` (line 222): the Cypher uses `datetime() - duration({days: $window_days})`. Rewrite: compute `cutoff = (datetime.now() - timedelta(days=window_days)).isoformat()` in Python, pass as `$cutoff` param, change Cypher to `r.last_seen < localdatetime($cutoff)`.
- `check_unreviewed_count()` (lines 188–195): two queries in one session (total + unreviewed). These become two sequential `_execute_query()` calls.
- All `record.data()` patterns become dict access on rows directly — `rows[0]["field"]` or `[row["field"] for row in rows]`.

**Depends on.** Component 3 (`FalkorDBLiteConnection` and `_execute_query()` exist).

**Done when.** `IntegrityChecker(db).run_all_checks()` completes against a populated graph without error. The `detect_frequency_stale()` method returns the same results as before (comparing by ISO timestamp string with `localdatetime()` in Cypher).

---

### 7. `writ/server.py` and `writ/cli.py` updates

**Goal.** Update the entry points (server startup and CLI commands) to use the new connection class and config functions.

**Build.** In `writ/server.py`:

- Replace import: `from writ.config import get_neo4j_uri, get_neo4j_user, get_neo4j_password` → `from writ.config import get_falkordb_path, get_falkordb_graph`.
- Replace import: `from writ.graph.db import Neo4jConnection` → `from writ.graph.db import FalkorDBLiteConnection`.
- In `lifespan()`: `Neo4jConnection(get_neo4j_uri(), get_neo4j_user(), get_neo4j_password())` → `FalkorDBLiteConnection(get_falkordb_path(), get_falkordb_graph())`.
- The 6 remaining direct `db._driver.session(...)` sites (at lines 270, 286, 1069, 1081, 1098, 1150) each become `await _db._execute_query(cypher, params)`. Results are already `list[dict]`.

In `writ/cli.py`:

- Replace imports (same pattern as server.py).
- `IntegrityChecker` instantiation: `IntegrityChecker(db._driver, db._database)` → `IntegrityChecker(db)`.
- 1 remaining direct session site → `db._execute_query()`.

**Depends on.** Components 2, 3, 4, and 6 (config functions, connection class, lockfile, and integrity checker all exist).

**Done when.** `writ serve` starts without error and responds to `GET /health`. `writ ingest bible/` completes and prints a success report. `writ query "security injection"` returns at least one result. `writ validate` runs all integrity checks without crashing.

---

### 8. End-to-end verification

**Goal.** Confirm all Phase 1 success criteria are met before handing off to Phase 2.

**Build.** No code changes — this is manual verification.

Run in order:
1. `pip install -e ".[dev]"` — clean install with new deps.
2. `writ serve &` — server starts. Verify no import errors or startup crashes.
3. `writ ingest bible/` — loads all rules. Verify success report shows all rules loaded.
4. `writ query "security injection"` — returns ranked results.
5. `writ validate` — integrity checks pass (no conflicts in a freshly ingested corpus).
6. Stop server. Run `writ ingest bible/` again — should succeed (lockfile released).
7. `grep -r "Neo4jConnection\|neo4j\|get_neo4j" writ/ --include="*.py"` — zero hits (excluding comments).

**Depends on.** All prior components.

**Done when.** All 7 steps complete without error. The four roadmap done-when criteria are met: server starts without Docker, ingest loads rules, query returns results, graph contains node/edge types.

---

## Handoff Notes

**Contract with Phase 2 (Infrastructure Cleanup):** Phase 1 delivers a working `FalkorDBLiteConnection` class and updated config functions. Phase 2's `scripts/seed_phase_*.py` files do a mechanical import swap: `from writ.graph.db import Neo4jConnection` → `FalkorDBLiteConnection`, `get_neo4j_*()` → `get_falkordb_*()`, constructor call shape. Phase 2 does NOT need `_execute_query()` — seed scripts access the public API (`create_rule()`, `create_edge()`).

**Contract with Phase 3 (Test Suite Green):** Tests currently mock `Neo4jConnection`. Phase 3 updates `tests/conftest.py` to create `FalkorDBLiteConnection` against a temp file path per test. The `_execute_query()` bridge makes test mocking simpler — tests can mock at the `_execute_query` level rather than mocking Neo4j's async session protocol.

**Open uncertainty — full-node RETURN behavior (A4):** This is the highest-impact unknown. If `RETURN r` doesn't give a usable object, `get_rule()`, `get_all_rules()`, `get_rules_by_authority()`, and both `build_pipeline()` loading blocks all need explicit property lists. Research should verify this first — it determines the shape of 6+ query rewrites.

**Open uncertainty — `SET r += $props` (A3):** If unsupported, `create_rule()` and `create_methodology_node()` must build individual SET statements for each property. Manageable but adds ~10 lines per method.

**Suggested research before detailed planning:**

1. **A4 first** (full-node RETURN): create a test script that opens FalkorDBLite, creates a node with 5 properties, `RETURN n`, and inspect `result.result_set[0][0]`. Is it a dict-like object or an opaque Node?
2. **A2** (header attribute): inspect `result.header` on the same query. Confirm column name ordering matches `RETURN` alias order.
3. **A3** (`SET +=`): run `MERGE (r:Rule {rule_id: 'test'}) SET r += {domain: 'security'}` and check for errors.
4. **A9** (error message string): run index creation twice, capture the exception, inspect `str(e)` for exact phrasing.
5. **A6** (async constraint API): check if `AsyncFalkorDB.select_graph()` returns an object with `create_node_unique_constraint()`. If not, identify the raw Redis command equivalent.
6. **A8** (lockfile): start `AsyncFalkorDB('/tmp/test.db')`, then start another `AsyncFalkorDB('/tmp/test.db')` from the same process. Does it error, block, or succeed silently?
