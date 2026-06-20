# Implementation Plan: Phase 1 — Core Storage Swap (Neo4j to FalkorDBLite)

> Produced 2026-06-19. Inputs: spec (Component IDs 1-8), research (B0, S1-S4, A1-A10), design (D1-D11), FalkorDB reference, live code via CodeGraph.

---

## 1. Architecture Overview

### What changes

Seven Python files in the `writ/` package switch from Neo4j's async driver to FalkorDBLite's embedded async API. Two config files (`pyproject.toml`, `writ.toml`) swap dependency declarations. One ignore file (`.gitignore`) adds the new data directory.

| File | Nature of change |
|------|-----------------|
| `pyproject.toml` | Remove `neo4j` dep, add `falkordblite` + `redis<8` pin, bump Python to 3.12 |
| `writ.toml` | Replace `[neo4j]` section with `[falkordb]` section |
| `.gitignore` | Add `.writ/` |
| `writ/config.py` | Delete 3 Neo4j helpers, add 2 FalkorDB helpers |
| `writ/graph/db.py` | Rename class, new constructor, add `_execute_query()`, rewrite 22 method bodies, add lockfile |
| `writ/graph/integrity.py` | Refactor constructor, rewrite 9 method bodies to use `_execute_query()` |
| `writ/retrieval/pipeline.py` | 2 reach-through sites become `_execute_query()` calls, update import + annotation |
| `writ/retrieval/traversal.py` | 1 reach-through site becomes `_execute_query()` call |
| `writ/server.py` | Swap imports, constructor call, 6 direct session sites become `_execute_query()` |
| `writ/cli.py` | Swap imports at 12 instantiation sites, 1 direct session site, IntegrityChecker constructor call |

### What stays untouched

- **Retrieval pipeline logic** (`writ/retrieval/pipeline.py` lines 201-418) -- pure in-memory, never touches DB at query time.
- **Retrieval support modules** -- `keyword.py`, `vector.py` (embeddings.py), `ranking.py`, `session.py`.
- **Graph schema** -- `writ/graph/schema.py` (Pydantic models).
- **Graph ingest** -- `writ/graph/ingest.py`, `writ/graph/methodology_ingest.py` (call public API, not internals).
- **Rule corpus** -- `bible/` directory.
- **Workflow hooks** -- `.claude/hooks/` (33 scripts, no DB coupling).
- **Scripts** -- `scripts/` directory (Phase 2 scope).
- **Tests** -- `tests/` and `benchmarks/` (Phase 3 scope).

### Key constraints

1. The `GraphConnection` Protocol (5 methods at `db.py:66-76`) stays byte-for-byte identical.
2. The 5-stage retrieval algorithm is off-limits. Only the 3 startup-loading reach-through sites change.
3. All 282 tests are the correctness contract (test adaptation is Phase 3, but no existing behavior may break).
4. No sync I/O in the hot path -- `_execute_query()` is only called at startup and in CLI/server background operations.
5. Ranking weights must sum to 1.0 -- `writ.toml [ranking]` is not touched.
6. No backward-compat shims -- `get_neo4j_*()` deleted outright, `Neo4jConnection` renamed without alias. Loud import failures are desired.
7. Single-accessor lockfile prevents server + CLI from opening the same DB simultaneously.
8. Python >= 3.12 required (FalkorDBLite hard requirement).

---

## 2. Approach

### Sequencing rationale

The steps are ordered by dependency: each step produces something the next step needs. Config functions must exist before the connection class can read them. The connection class must exist before reach-through sites or entry points can reference it. The lockfile is part of the connection class but described separately for clarity.

### Core design pattern

Every Neo4j call site follows this pattern:

```python
# Before (Neo4j)
async with self._driver.session(database=self._database) as session:
    result = await session.run(query, **params)
    record = await result.single()      # or async iteration
    return record["field"]              # or dict(record["r"])

# After (FalkorDBLite)
rows = await self._execute_query(query, params)
if not rows:
    return None
return rows[0]["field"]                 # or rows[0] for full dict
```

The new `_execute_query()` method is the ONLY place that knows about FalkorDB's positional-tuple result format. It maps column headers to values and returns `list[dict]`, so all existing field-name-based extraction continues to work unchanged.

### Research corrections baked in

Five corrections from the research phase affect specific steps. Each is called out where it applies:

- **B0**: `redis<8` must be pinned in `pyproject.toml` (Step 1).
- **S1**: `_execute_query()` must detect Node/Edge objects via `hasattr(val, 'properties')` and use `.properties` (Step 3).
- **S2**: `QueryResult.header` items are `[type_code, name]` pairs -- extract `h[1]` (Step 3).
- **A9**: Error catch in `apply_constraints()` needs BOTH strings: `"already indexed" in msg or "already exist" in msg` (Step 3).
- **A10**: Two `Neo4jConnection` refs in `pipeline.py` -- import at line 48 AND annotation at line 489 (Step 5).

---

## 3. Phase Breakdown

### Step 1: Package dependencies and config files

**Goal.** Declare FalkorDBLite as the graph library, remove Neo4j, pin redis, and update config format so all subsequent imports succeed.

**Spec component:** 1

**Files to touch:**
- `/Users/lap14806/writ/pyproject.toml`
- `/Users/lap14806/writ/writ.toml`
- `/Users/lap14806/writ/.gitignore`

**What to change:**

- `pyproject.toml`:
  - Change `requires-python` from `">=3.11"` to `">=3.12"`.
  - Remove `"neo4j>=5.0,<6"` from `dependencies`.
  - Add `"falkordblite>=0.10,<1"` to `dependencies`.
  - Add `"redis>=5.0,<8"` to `dependencies` (research correction B0: redis 8.0 breaks FalkorDBLite startup with `ValueError: Cannot enable maintenance notifications`).
  - Update `description` string to remove "Neo4j" mention.
  - Update `keywords` list: replace `"neo4j"` with `"falkordb"`.
  - Update `classifiers`: remove `"Programming Language :: Python :: 3.11"` line.

- `writ.toml`:
  - Delete the `[neo4j]` section (lines 11-14: uri, user, password, database).
  - Add in its place:
    ```toml
    [falkordb]
    path = ".writ/graph.db"
    graph = "writ"
    ```
  - Update `[source]` section: change `canonical = "neo4j"` to `canonical = "falkordb"`.

- `.gitignore`:
  - Add `.writ/` entry (so the per-project graph data file and lockfile are not committed).
  - The existing `neo4j-data/` line can stay (harmless, and removing it is optional cleanup).

**Research corrections applied:** B0 (redis pin).

**Verification:**
1. `pip install -e ".[dev]"` in a Python 3.12+ environment succeeds.
2. `python -c "from redislite.async_falkordb_client import AsyncFalkorDB; print('OK')"` prints OK.
3. `python -c "import neo4j"` raises `ModuleNotFoundError`.

---

### Step 2: Config functions

**Goal.** Replace the three Neo4j config helpers with two FalkorDB ones, so subsequent code has a single place to read connection parameters.

**Spec component:** 2

**Files to touch:**
- `/Users/lap14806/writ/writ/config.py`

**What to change:**

- Delete the three default constants (lines 20-22):
  - `DEFAULT_NEO4J_URI = "bolt://localhost:7687"`
  - `DEFAULT_NEO4J_USER = "neo4j"`
  - `DEFAULT_NEO4J_PASSWORD = "writdevpass"`

- Delete the three functions (lines 46-61):
  - `get_neo4j_uri()`
  - `get_neo4j_user()`
  - `get_neo4j_password()`

- Add two new constants:
  - `DEFAULT_FALKORDB_PATH = ".writ/graph.db"`
  - `DEFAULT_FALKORDB_GRAPH = "writ"`

- Add two new functions following the same pattern as the deleted ones:
  ```python
  def get_falkordb_path(path: str | None = None) -> str:
      """Return falkordb.path from config, falling back to DEFAULT_FALKORDB_PATH."""
      cfg = load_config(path)
      return cfg.get("falkordb", {}).get("path", DEFAULT_FALKORDB_PATH)

  def get_falkordb_graph(path: str | None = None) -> str:
      """Return falkordb.graph from config, falling back to DEFAULT_FALKORDB_GRAPH."""
      cfg = load_config(path)
      return cfg.get("falkordb", {}).get("graph", DEFAULT_FALKORDB_GRAPH)
  ```

- Keep `load_config()` (lines 30-43) and `get_hnsw_cache_dir()` (lines 64-73) exactly as-is.

**Verification:**
1. `from writ.config import get_falkordb_path, get_falkordb_graph` succeeds.
2. `from writ.config import get_neo4j_uri` raises `ImportError`.
3. `get_falkordb_path()` returns `".writ/graph.db"` when `writ.toml` has no `[falkordb]` section.
4. `get_falkordb_graph()` returns `"writ"` by default.

---

### Step 3: `FalkorDBLiteConnection` class and `_execute_query()` helper

**Goal.** Replace `Neo4jConnection` with `FalkorDBLiteConnection` -- the load-bearing change. Every DB operation flows through this class.

**Spec component:** 3

**Files to touch:**
- `/Users/lap14806/writ/writ/graph/db.py`

**What to change (high level):**

1. **Imports**: Remove Neo4j imports (`from neo4j import AsyncGraphDatabase, AsyncDriver`). Add FalkorDB import (`from redislite.async_falkordb_client import AsyncFalkorDB`). Add standard library imports needed for lockfile and timestamps (`import os`, `import signal`, `from datetime import datetime, timedelta`, `from pathlib import Path`).

2. **Class rename**: `Neo4jConnection` becomes `FalkorDBLiteConnection`.

3. **Constructor** (currently lines 86-88): Replace `(uri, user, password, database="neo4j")` with `(path: str, graph: str = "writ")`. Body:
   ```python
   self._db = AsyncFalkorDB(path)
   self._graph = self._db.select_graph(graph)
   self._path = path
   ```
   Note: lockfile acquisition is also added here (see Step 4, but implemented in the same file edit).

4. **Add `_execute_query()` method** -- the central bridge. This is the ONLY place that knows about FalkorDB's result format.
   ```python
   async def _execute_query(self, cypher: str, params: dict | None = None) -> list[dict]:
       result = await self._graph.query(cypher, params=params or {})
       if not result.result_set:
           return []
       # S2 correction: header items are [type_code, name] pairs
       names = [h[1] for h in result.header]
       rows = []
       for row in result.result_set:
           converted = []
           for val in row:
               # S1 correction: detect Node/Edge objects and extract .properties
               if hasattr(val, 'properties'):
                   converted.append(val.properties)
               else:
                   converted.append(val)
           rows.append(dict(zip(names, converted)))
       return rows
   ```

5. **Rewrite all 22 method bodies.** Each `async with self._driver.session(database=self._database) as session:` block becomes `rows = await self._execute_query(query, params)`. Specific patterns:

   - **Single-record methods** (`get_rule`, `create_rule`, `create_methodology_node`, `create_abstraction`, `update_rule_authority`, `update_rule_confidence`, `increment_positive`, `increment_negative`, `delete_rule`, `count_rules`, `delete_abstractions`, `get_rule_abstraction`):
     ```python
     rows = await self._execute_query(query, params)
     if not rows:
         return None  # or appropriate default
     return rows[0]["field_name"]
     ```

   - **Multi-record methods** (`get_all_rules`, `get_all_edges`, `traverse_neighbors`, `get_rules_by_authority`, `count_by_authority`):
     ```python
     rows = await self._execute_query(query, params)
     return rows  # or transform as needed
     ```
     For `count_by_authority`: `return {row["authority"]: row["count"] for row in rows}`.

   - **`get_all_abstractions()`**: Queries return `a` (a Node) and `member_ids` (a list). With S1 auto-extraction in `_execute_query`, `rows[i]["a"]` is already a dict (extracted from Node.properties). The method becomes:
     ```python
     rows = await self._execute_query(query)
     abstractions = []
     for row in rows:
         data = row["a"]
         data["member_ids"] = row["member_ids"]
         abstractions.append(data)
     return abstractions
     ```

   - **`get_abstraction()`**: Uses `collect(r {.*})` map projection (validated working per A5). Same mechanical swap.

   - **No-return methods** (`create_edge`, `create_abstracts_edge`, `clear_all`):
     ```python
     await self._execute_query(query, params)
     ```

6. **Special-case rewrites:**

   - **`increment_positive()` and `increment_negative()`** (lines 392-416): Replace `datetime()` with `localdatetime($ts)` and pass the current ISO timestamp from Python:
     ```python
     ts = datetime.now().isoformat()
     query = """
         MATCH (r:Rule {rule_id: $rule_id})
         SET r.times_seen_positive = coalesce(r.times_seen_positive, 0) + 1,
             r.last_seen = localdatetime($ts)
         RETURN r.rule_id AS rule_id
     """
     rows = await self._execute_query(query, {"rule_id": rule_id, "ts": ts})
     ```
     Same pattern for `increment_negative` (changing `times_seen_positive` to `times_seen_negative`).

   - **`apply_constraints()`** (lines 316-342): Complete rewrite. Cannot use `IF NOT EXISTS` or named indexes in FalkorDB. Use the Python API methods with try/except error swallowing:
     ```python
     async def apply_constraints(self) -> None:
         # Unique constraints (must create supporting index first)
         index_specs = [
             ("Rule", "rule_id"), ("Rule", "domain"), ("Rule", "mandatory"),
             ("Abstraction", "abstraction_id"), ("Abstraction", "domain"),
         ]
         # Add methodology label indexes
         for label, id_field in METHODOLOGY_NODE_ID_FIELDS.items():
             index_specs.append((label, id_field))
             index_specs.append((label, "domain"))

         for label, field in index_specs:
             try:
                 self._graph.create_node_range_index(label, field)
             except Exception as e:
                 msg = str(e).lower()
                 # A9 correction: check BOTH error message variants
                 if "already indexed" in msg or "already exist" in msg:
                     pass
                 else:
                     raise

         unique_specs = [
             ("Rule", "rule_id"),
             ("Abstraction", "abstraction_id"),
         ]
         for label, id_field in METHODOLOGY_NODE_ID_FIELDS.items():
             unique_specs.append((label, id_field))

         for label, field in unique_specs:
             try:
                 self._graph.create_node_unique_constraint(label, field)
             except Exception as e:
                 msg = str(e).lower()
                 if "already exist" in msg:
                     pass
                 else:
                     raise
     ```
     Note: constraint/index creation methods may be sync even on the async graph object. If they are async, add `await`. Research confirmed the methods exist on the async graph (A6 validated).

   - **`list_constraints()`** (line 344-348): Replace `SHOW CONSTRAINTS` with `CALL db.constraints()`:
     ```python
     return await self._execute_query("CALL db.constraints()")
     ```

   - **`list_indexes()`** (lines 350-354): Replace `SHOW INDEXES` with `CALL db.indexes()`:
     ```python
     return await self._execute_query("CALL db.indexes()")
     ```

   - **`close()`** (lines 446-448): Replace `await self._driver.close()` with `await self._db.close()`. Also release lockfile (see Step 4).

7. **Unchanged module-level items**: `ALLOWED_EDGE_TYPES`, `METHODOLOGY_NODE_LABELS`, `METHODOLOGY_NODE_ID_FIELDS`, `_coerce_neo4j_value()`, `GraphConnection` Protocol -- all stay byte-for-byte identical.

**Research corrections applied:** S1 (Node object detection via `.properties`), S2 (header `h[1]` extraction), A9 (dual error message check).

**Verification:**
1. `from writ.graph.db import FalkorDBLiteConnection` succeeds.
2. `from writ.graph.db import Neo4jConnection` raises `ImportError`.
3. A smoke test script that creates a `FalkorDBLiteConnection` against a temp path, calls `create_rule({...})`, then `get_rule(rule_id)`, returns the original data.
4. `apply_constraints()` runs twice without error (idempotent).

---

### Step 4: Lockfile mechanism

**Goal.** Prevent the server and CLI from opening the same DB file simultaneously, which would cause data corruption (research confirmed FalkorDBLite does NOT reject concurrent openers -- A8 invalidated).

**Spec component:** 4

**Files to touch:**
- `/Users/lap14806/writ/writ/graph/db.py` (within the `FalkorDBLiteConnection` class -- same file as Step 3, implemented together)

**What to change:**

The lockfile lives at `.writ/graph.lock` (adjacent to `.writ/graph.db`). Logic is added to the `FalkorDBLiteConnection` class:

- **In `__init__()` (constructor)**: After storing `self._path`, derive lockfile path:
  ```python
  self._lock_path = Path(path).parent / "graph.lock"
  self._lock_path.parent.mkdir(parents=True, exist_ok=True)
  self._acquire_lock()
  ```

- **Add `_acquire_lock()` method**:
  ```python
  def _acquire_lock(self) -> None:
      if self._lock_path.exists():
          try:
              pid = int(self._lock_path.read_text().strip())
              # Check if process is still running
              os.kill(pid, 0)
              raise RuntimeError(
                  f"Writ graph DB is locked by PID {pid}. "
                  "Stop the server or use the HTTP API."
              )
          except ProcessLookupError:
              pass  # Stale lockfile from crashed process
          except ValueError:
              pass  # Corrupt lockfile content
      self._lock_path.write_text(str(os.getpid()))
  ```

- **In `close()` method**: After closing the DB, release the lockfile:
  ```python
  async def close(self) -> None:
      await self._db.close()
      try:
          self._lock_path.unlink(missing_ok=True)
      except OSError:
          pass
  ```

- Callers (server.py and cli.py) do not need explicit lock calls -- the constructor handles acquisition, and `close()` handles release.

**Verification:**
1. Start `writ serve`, then run `writ ingest bible/` in a second terminal. The second terminal prints the lock error message and exits with code 1.
2. Stop the server. Run `writ ingest bible/` -- succeeds (lockfile was released).
3. Kill the server process with SIGKILL (simulating crash), then run `writ ingest bible/` -- succeeds (stale lockfile detected via PID check).

---

### Step 5: Reach-through site swaps in `writ/retrieval/`

**Goal.** Replace the 3 Neo4j-specific session-opening calls in the retrieval module with `_execute_query()` calls. These are the ONLY changes to `writ/retrieval/` -- zero logic changes.

**Spec component:** 5

**Files to touch:**
- `/Users/lap14806/writ/writ/retrieval/pipeline.py`
- `/Users/lap14806/writ/writ/retrieval/traversal.py`

**What to change:**

In `writ/retrieval/pipeline.py`:

- **Line 48**: Change import from `from writ.graph.db import Neo4jConnection` to `from writ.graph.db import FalkorDBLiteConnection` (A10 correction: this import line exists and must change).

- **Line 489**: Change type annotation from `db: Neo4jConnection` to `db: FalkorDBLiteConnection` (A10 correction: second reference).

- **Lines 514-517** (rule loading block): Replace the 4-line session block with:
  ```python
  rule_rows = await db._execute_query(query)
  rules = [row["r"] for row in rule_rows]
  ```
  The `dict(record["r"])` conversion is now handled by `_execute_query()`'s S1 Node-to-dict auto-extraction.

- **Lines 532-535** (methodology node loading block): Replace the 4-line session block with:
  ```python
  meth_rows = await db._execute_query(q)
  for row in meth_rows:
      node = row["n"]
      # ... rest of processing stays identical
  ```
  Again, `dict(record["n"])` becomes `row["n"]` (already a dict from S1 auto-extraction).

In `writ/retrieval/traversal.py`:

- **Lines 60-62** (AdjacencyCache.build_from_db): Replace the 3-line session block with:
  ```python
  records = await db._execute_query(query)
  ```
  The subsequent `for rec in records:` loop stays identical -- `rec["source"]`, `rec["edge_type"]`, `rec["target"]` work directly because `_execute_query` returns `list[dict]`.

**Research corrections applied:** A10 (two Neo4jConnection refs in pipeline.py, not one).

**Verification:**
1. `build_pipeline(db)` completes without error when `db` is a `FalkorDBLiteConnection` backed by a populated graph.
2. The adjacency cache populates (non-zero `.size`).
3. `pipeline.query("security injection")` returns ranked results.

---

### Step 6: IntegrityChecker constructor refactor

**Goal.** Make `IntegrityChecker` accept the connection object instead of a raw Neo4j driver, so all its 9 check methods can use `_execute_query()`.

**Spec component:** 6

**Files to touch:**
- `/Users/lap14806/writ/writ/graph/integrity.py`

**What to change:**

- **Imports**: Replace `from neo4j import AsyncDriver` (if present) with `from writ.graph.db import FalkorDBLiteConnection`. Add `from datetime import datetime, timedelta` if not already imported.

- **Constructor** (line 22): Change from:
  ```python
  def __init__(self, driver: AsyncDriver, database: str = "neo4j") -> None:
      self._driver = driver
      self._database = database
  ```
  To:
  ```python
  def __init__(self, db: FalkorDBLiteConnection) -> None:
      self._db = db
  ```

- **All 9 method bodies** rewritten mechanically. Each `async with self._driver.session(database=self._database) as session:` block becomes:
  ```python
  rows = await self._db._execute_query(cypher, params)
  ```

- **Specific method rewrites:**

  - `detect_conflicts()` (line 26): `[record.data() async for record in result]` becomes `rows` directly (already `list[dict]`).

  - `detect_orphans()` (line 38): `[record["rule_id"] async for record in result]` becomes `[row["rule_id"] for row in rows]`.

  - `detect_stale()` (line 50): Iterate `for row in rows:` instead of `async for record in result:`. Replace `data = record.data()` with `data = row`. Rest stays.

  - `detect_redundant()` (line 80): `[record.data() async for record in result]` becomes `rows` directly.

  - `detect_confidence_defaults()` (line 141): Same pattern as `detect_orphans`.

  - `check_query_rule_ratio()` (line 153): `record = await result.single()` becomes `rows[0]` (check `if rows` first).

  - `check_unreviewed_count()` (lines 172-209): The two queries that share one session become two sequential `_execute_query()` calls:
    ```python
    total_rows = await self._db._execute_query(total_query)
    total = total_rows[0]["total"] if total_rows else 0
    unreviewed_rows = await self._db._execute_query(unreviewed_query)
    unreviewed = unreviewed_rows[0]["unreviewed"] if unreviewed_rows else 0
    ```

  - **`detect_frequency_stale()` (lines 211-228)**: The Cypher uses `datetime() - duration({days: $window_days})` which is not supported in FalkorDB. Rewrite: compute the cutoff in Python and pass as a parameter:
    ```python
    cutoff = (datetime.now() - timedelta(days=window_days)).isoformat()
    query = """
        MATCH (r:Rule)
        WHERE (coalesce(r.times_seen_positive, 0) + coalesce(r.times_seen_negative, 0)) = 0
          AND (r.last_seen IS NULL
               OR r.last_seen < localdatetime($cutoff))
        RETURN r.rule_id AS rule_id, r.last_seen AS last_seen
        ORDER BY rule_id
    """
    rows = await self._db._execute_query(query, {"cutoff": cutoff})
    return rows
    ```

  - `detect_graduation_flags()` (line 230): Same mechanical swap. The Cypher uses standard operators only (no `datetime()`), so no query rewrite needed.

  - `run_all_checks()` (line 270): No change -- it only calls the other methods.

**Verification:**
1. `IntegrityChecker(db).run_all_checks()` completes against a populated graph without error.
2. `detect_frequency_stale()` returns expected results (rules with zero frequency beyond window).
3. `check_unreviewed_count()` returns correct counts.

---

### Step 7: Server and CLI entry point updates

**Goal.** Update the entry points (server startup and CLI commands) to use the new connection class and config functions.

**Spec component:** 7

**Files to touch:**
- `/Users/lap14806/writ/writ/server.py`
- `/Users/lap14806/writ/writ/cli.py`

**What to change in `writ/server.py`:**

- **Line 29**: Change import from:
  ```python
  from writ.config import get_neo4j_uri, get_neo4j_user, get_neo4j_password
  ```
  To:
  ```python
  from writ.config import get_falkordb_path, get_falkordb_graph
  ```

- **Line 30**: Change import from:
  ```python
  from writ.graph.db import Neo4jConnection
  ```
  To:
  ```python
  from writ.graph.db import FalkorDBLiteConnection
  ```

- **Line 143** (lifespan constructor): Change from:
  ```python
  _db = Neo4jConnection(get_neo4j_uri(), get_neo4j_user(), get_neo4j_password())
  ```
  To:
  ```python
  _db = FalkorDBLiteConnection(get_falkordb_path(), get_falkordb_graph())
  ```

- **6 direct session sites** (lines 270, 286, 1069, 1081, 1098, 1150): Each `async with _db._driver.session(database=_db._database) as session:` block followed by `result = await session.run(query, ...)` and async iteration becomes:
  ```python
  rows = await _db._execute_query(query, params)
  ```
  Then `[record.data() async for record in result]` becomes `rows` directly, and `record = await result.single()` becomes `rows[0]` with a guard check.

  Specific sites:
  - Line 270 (check_conflicts): `conflicts = rows`
  - Line 286 (health/mandatory count): `mandatory_count = rows[0]["count"] if rows else 0`
  - Line 1069 (always-on rules): `rows = await _db._execute_query(query)` -- already a list
  - Line 1081 (ForbiddenResponse): `frb_rows = await _db._execute_query(frb_query)` -- already a list
  - Line 1098 (methodology always-on, inside a for loop): `meth_result = await _db._execute_query(q)` then `methodology_rows.extend(meth_result)`
  - Line 1150 (subagent-role): `rows = await _db._execute_query(query, {"name": name})` then `row = rows[0] if rows else None`

**What to change in `writ/cli.py`:**

- **Line 11** (top-level import): Change from:
  ```python
  from writ.config import get_neo4j_uri, get_neo4j_user, get_neo4j_password
  ```
  To:
  ```python
  from writ.config import get_falkordb_path, get_falkordb_graph
  ```

- **12 local imports of `Neo4jConnection`** (at lines 368, 446, 536, 655, 746, 791, 850, 886, 914, 946, 988, 1041): Each `from writ.graph.db import Neo4jConnection` becomes `from writ.graph.db import FalkorDBLiteConnection`.

- **12 constructor calls** (at lines 395, 450, 568, 661, 749, 794, 853, 892, 918, 953, 1007, 1044): Each:
  ```python
  db = Neo4jConnection(get_neo4j_uri(), get_neo4j_user(), get_neo4j_password())
  ```
  Becomes:
  ```python
  db = FalkorDBLiteConnection(get_falkordb_path(), get_falkordb_graph())
  ```

- **Line 452** (IntegrityChecker instantiation): Change from:
  ```python
  checker = IntegrityChecker(db._driver, db._database)
  ```
  To:
  ```python
  checker = IntegrityChecker(db)
  ```

- **Line 855** (direct session site in subagent-role fetch): Replace the `async with db._driver.session(database=db._database) as session:` block with `rows = await db._execute_query(query, {"name": name})` and adapt the result reading.

**Verification:**
1. `writ serve` starts without error and responds to `GET /health`.
2. `writ ingest bible/` completes and prints a success report.
3. `writ query "security injection"` returns at least one result.
4. `writ validate` runs all integrity checks without crashing.
5. `writ role writ-explorer` returns the subagent template (or appropriate "not found").

---

### Step 8: End-to-end verification

**Goal.** Confirm all Phase 1 success criteria are met before handing off to Phase 2.

**Spec component:** 8

**Files to touch:** None -- this is manual verification.

**Verification sequence:**

1. **Clean install**: `pip install -e ".[dev]"` -- succeeds with no neo4j, includes falkordblite + redis<8.

2. **Server startup**: `writ serve &` -- server starts. No import errors or startup crashes. `GET /health` returns status "healthy".

3. **Ingest**: `writ ingest bible/` -- loads all rules. Success report shows all rules loaded.

4. **Query**: `writ query "security injection"` -- returns ranked results with scores.

5. **Validate**: `writ validate` -- integrity checks run (no crashes; findings are expected on fresh corpus).

6. **Lockfile**: With server running, `writ ingest bible/` in second terminal prints lock error. After stopping server, the same command succeeds.

7. **No Neo4j references**: `grep -r "Neo4jConnection\|neo4j\|get_neo4j" writ/ --include="*.py"` -- zero hits in production code (comments/docstrings may remain and that is acceptable).

8. **Success criteria from roadmap:**
   - Server starts without Docker: PASS (no Neo4j container needed)
   - Ingest loads rules: PASS
   - Query returns results: PASS
   - Graph contains expected node/edge types: verify via `writ serve` then `GET /health` showing non-zero rule_count

---

## 4. Open Questions

| # | Question | Impact | When to resolve |
|---|----------|--------|----------------|
| 1 | Are `create_node_range_index()` and `create_node_unique_constraint()` sync or async on the async graph object? | Low -- if sync, omit `await`; if async, add `await`. Either way Step 3 works. | During Step 3 implementation. Try `await` first; if `TypeError: object ... is not awaitable`, remove `await`. |
| 2 | Does `writ/export.py` line 24 (`from writ.graph.db import Neo4jConnection` under `TYPE_CHECKING`) need updating? | Low -- it is a type-only import used for annotation in `export_rules_to_markdown()`. Not a runtime failure, but will cause mypy complaints. | Update during Step 7 as a bonus or defer to Phase 2. It is under `if TYPE_CHECKING:` so it does not break at runtime. |

---

## 5. Out of Scope

Phase 1 does NOT touch:

- **`scripts/` directory** (12+ files) -- all import `Neo4jConnection` and `get_neo4j_*()`. These are mechanical import swaps deferred to Phase 2.
- **`tests/` and `benchmarks/`** (16+ files) -- test fixtures mock `Neo4jConnection`. Updating them is Phase 3.
- **`docker-compose.yml`** and bootstrap shell scripts -- removing Docker from the bootstrap flow is Phase 2.
- **Retrieval pipeline logic** -- the 5-stage query algorithm, RRF weights, scoring, BM25 field boosts, and vector search are completely off-limits. The only touches to `writ/retrieval/` are the mechanical 4-lines-to-1-line substitutions at the 3 reach-through sites.
- **`writ/graph/schema.py`** -- Pydantic models are unchanged.
- **`writ/graph/ingest.py`** and **`writ/graph/methodology_ingest.py`** -- these call `db.create_rule()` / `db.create_edge()` (public API), not internals.
- **New public methods on `FalkorDBLiteConnection`** -- only the existing 5 Protocol methods are public. `_execute_query()` is private infrastructure.
- **`writ/gate.py`, `writ/authoring.py`, `writ/export.py`, `writ/frequency.py`** -- none have direct DB coupling beyond type annotations under `TYPE_CHECKING`.
- **Performance tuning** -- FalkorDBLite query performance optimization (if needed) is post-Phase-1.
