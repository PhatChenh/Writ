# Design: Phase 1 — Core Storage Swap (Neo4j → FalkorDBLite)

> Produced 2026-06-19. Inputs: grill session (D1–D11), code survey via CodeGraph.

## Summary

Replace the Neo4j async driver in `writ/graph/db.py` with FalkorDBLite (embedded graph DB, zero Docker dependency). Every public method keeps identical inputs/outputs. The class rename + config change propagate to 38 files across 4 phases.

## The Core Design Tension

CLAUDE.md says: "Do NOT modify retrieval pipeline logic (`writ/retrieval/`) during the DB swap."

But `build_pipeline()` and `AdjacencyCache.build_from_db()` reach directly into `db._driver.session()` — Neo4j-specific internals that won't exist after the swap. This code MUST change for the swap to work.

**Resolution:** The rule protects retrieval *logic* (the 5-stage query algorithm, ranking, scoring). The startup *loading* code that pre-warms indexes is infrastructure, not logic. It reads nodes/edges into memory — what changes is HOW it reads, not WHAT it reads or how results are used.

The design adds `_execute_query()` (D6) as the bridge: all reach-through sites swap their 4-line `async with _driver.session(...)` boilerplate for one `await db._execute_query(cypher, params)` call. Retrieval pipeline files get a mechanical 4-lines-to-1-line replacement — no behavioral change.

## Architecture: What Changes vs. Stays

### Changes (Phase 1 scope)

| Component | What happens |
|-----------|-------------|
| `writ/graph/db.py` | Rewrite all 22 internal method bodies. New constructor, new `_execute_query()` helper, lockfile logic (D10) |
| `writ/graph/integrity.py` | Refactor constructor to accept connection object. All 9 methods → `_execute_query()`. Rewrite `duration()` query. |
| `writ/config.py` | Delete `get_neo4j_*()`. Add `get_falkordb_path()`, `get_falkordb_graph()`. Keep `load_config()` and `get_hnsw_cache_dir()` unchanged. |
| `writ/retrieval/pipeline.py` | 2 sites: `db._driver.session(...)` → `db._execute_query(...)`. Zero logic change. |
| `writ/retrieval/traversal.py` | 1 site: same mechanical swap. Zero logic change. |
| `writ/server.py` | 6 direct session sites → `_execute_query()`. Constructor call changes (uri/user/pass → path). |
| `writ/cli.py` | 2 sites: IntegrityChecker instantiation, 1 direct session. Constructor call changes. |
| `pyproject.toml` | `requires-python >=3.12`. Swap `neo4j` dep for `falkordblite`. |
| `writ.toml` | Replace `[neo4j]` section with `[falkordb]` section. |
| `.gitignore` | Add `.writ/` |

### Stays Untouched

| Component | Why |
|-----------|-----|
| `writ/retrieval/pipeline.py` query logic (lines 201–418) | Pure in-memory, never touches DB at query time |
| `writ/retrieval/keyword.py`, `vector.py`, `ranking.py` | In-process indexes, no DB coupling |
| `writ/graph/schema.py` | Pydantic models — data layer, not DB layer |
| `writ/graph/methodology_ingest.py` | Calls `db.create_rule()` / `db.create_edge()` — uses public API, not internals |
| `bible/` corpus | Rule content unchanged |
| `.claude/hooks/` | Workflow enforcement, no DB coupling |

## Reach-Through Sites: Full Inventory

Code that bypasses `Neo4jConnection`'s public methods by accessing `_driver` directly:

| File | Sites | What they do |
|------|-------|-------------|
| `writ/retrieval/pipeline.py:514,532` | 2 | Load rules + methodology nodes at startup |
| `writ/retrieval/traversal.py:60` | 1 | Load all edges for adjacency cache at startup |
| `writ/server.py:270,286,1069,1081,1098,1150` | 6 | Conflict queries, session endpoints, ad-hoc queries |
| `writ/cli.py:452,855` | 2 | IntegrityChecker init, one ad-hoc query |
| `writ/graph/integrity.py:34–249` | 9 | All checker methods use raw session |
| **Total outside db.py** | **20** | |

All 20 become `await db._execute_query(cypher, params)` calls — same Cypher, same params, result comes back as `list[dict]` instead of async record streams.

## `_execute_query()` Design

```python
async def _execute_query(self, cypher: str, params: dict | None = None) -> list[dict]:
    """Execute Cypher, return results as list of dicts keyed by RETURN aliases.
    
    Maps FalkorDBLite's positional tuples to named dicts using QueryResult.header.
    """
    result = await self._graph.query(cypher, params=params or {})
    if not result.result_set:
        return []
    headers = result.header  # column names from RETURN clause
    return [dict(zip(headers, row)) for row in result.result_set]
```

This is the ONLY place that knows about FalkorDB's positional-tuple result format. Everything else works with `list[dict]` — identical to what Neo4j record.data() returned.

## Method-by-Method Migration Pattern

Every method in `Neo4jConnection` follows the same pattern today:

```python
async with self._driver.session(database=self._database) as session:
    result = await session.run(query, **params)
    record = await result.single()  # or async iteration
    return record["field"]          # or dict(record["r"])
```

Becomes:

```python
rows = await self._execute_query(query, params)
if not rows:
    return None
return rows[0]["field"]  # or rows[0] for full node
```

### Special cases requiring more than mechanical swap:

| Method | Issue | Fix |
|--------|-------|-----|
| `increment_positive/negative` | Uses `datetime()` — not supported | Pass `localdatetime($ts)` with ISO timestamp param |
| `apply_constraints` | Uses `IF NOT EXISTS` + named constraints | Try/except per D3+D11, use FalkorDB constraint API per D7 |
| `list_constraints` | Uses `SHOW CONSTRAINTS` | `CALL db.constraints()` |
| `list_indexes` | Uses `SHOW INDEXES` | `CALL db.indexes()` |
| `get_abstraction` | Uses `collect(r {.*})` map projection | May need explicit property list — open question for research |
| `count_by_authority` | Uses dict comprehension over async iter | Becomes `{row["authority"]: row["count"] for row in rows}` |
| `get_all_rules` / `get_rules_by_authority` | Returns `dict(record["r"])` (full node) | Need to SELECT all properties explicitly or verify RETURN n pattern |

### IntegrityChecker `duration()` rewrite:

```python
# Before (Neo4j):
r.last_seen < datetime() - duration({days: $window_days})

# After (FalkorDBLite):
cutoff = (datetime.now() - timedelta(days=window_days)).isoformat()
# Cypher: r.last_seen < localdatetime($cutoff)
```

## Returning Full Nodes

Neo4j pattern: `RETURN r` then `dict(record["r"])` gives all node properties as a dict.

FalkorDBLite: `RETURN r` — need to verify if this returns a Node object with properties accessible, or requires explicit property listing. Two possibilities:

1. **Node object with `.properties`** — `_execute_query` extracts properties from Node objects in result_set
2. **Must list properties explicitly** — queries like `MATCH (r:Rule) RETURN r` change to `RETURN r.rule_id, r.domain, r.severity, ...`

This is an **open question for research**. Design handles both: if Node objects work, `_execute_query` detects Node type in result_set and auto-extracts properties. If not, affected queries get explicit RETURN clauses.

## Lifecycle + Lockfile (D10)

```
Server startup:
  1. Acquire lockfile (.writ/graph.lock) — fail if held
  2. AsyncFalkorDB('.writ/graph.db') — starts subprocess
  3. select_graph('writ') → self._graph
  4. apply_constraints()
  5. [serve requests]
  
Server shutdown (FastAPI lifespan exit):
  1. await db.close() — stops subprocess
  2. Release lockfile

CLI command:
  1. Check lockfile — if held, print "server running, use HTTP API" and exit(1)
  2. Open DB, do work, close DB
```

## Constructor Change

```python
# Before:
Neo4jConnection(uri, user, password, database="neo4j")

# After:
FalkorDBLiteConnection(path=".writ/graph.db", graph="writ")
```

38 files import `Neo4jConnection` or `get_neo4j_*`. Phased:
- Phase 1: `writ/` package (db.py, config.py, server.py, cli.py, retrieval/pipeline.py, retrieval/traversal.py, integrity.py) — **~10 files**
- Phase 2: `scripts/` — **~12 files** (mechanical import swap)
- Phase 3: `tests/` + `benchmarks/` — **~16 files** (mechanical + test fixture changes)

## Config Shape

```toml
# writ.toml — before
[neo4j]
uri = "bolt://localhost:7687"
user = "neo4j"
password = "writdevpass"

# writ.toml — after
[falkordb]
path = ".writ/graph.db"
graph = "writ"
```

## Success Criteria (from roadmap done-when)

1. `writ serve` starts without Neo4j/Docker running
2. `writ ingest bible/` loads all rules into FalkorDBLite
3. `writ query "security"` returns ranked results
4. Graph contains all 12 node types and 10 edge types
5. All 282 tests pass (Phase 3 scope — tests adapt to new connection)

## Decisions Registry

| ID | Decision | Rationale |
|----|----------|-----------|
| D1 | Python ≥3.12 | FalkorDBLite hard requirement |
| D2 | DB at `.writ/graph.db` per-project | Rule corpus is project-specific |
| D3 | Idempotent setup via try/except | No IF NOT EXISTS in FalkorDBLite |
| D4 | Strict behavior preservation | Public API unchanged |
| D5 | Stay async | 80+ callers use await, async API available |
| D6 | `_execute_query()` + IntegrityChecker refactor | Bridge for 20 reach-through sites |
| D7 | `apply_constraints()` self-contained | Cypher for indexes, Redis cmd for constraints |
| D8 | Delete config functions, no shims | Loud import failure > silent compat |
| D9 | Rename class, no alias | Same reasoning as D8 |
| D10 | Single-accessor lockfile | Prevent multi-process file corruption |
| D11 | Broad catch + message check | Robust "already exists" handling |

## Open Questions (for research to verify)

1. Does `SET r += $props` work? (contained in db.py)
2. Does `collect(r {.*})` map projection work? (one query in `get_abstraction`)
3. Exact "already exists" error message string
4. Does `CALL db.constraints()` exist?
5. Does async Graph expose `create_node_unique_constraint()`?
6. How `QueryResult.header` exposes column names
7. Does `RETURN r` (full node) give a usable object or require explicit properties?
8. Does redislite already reject second openers via pidfile? (simplifies D10)

## Risks

| Risk | Likelihood | Impact | Mitigation |
|------|-----------|--------|------------|
| `SET +=` unsupported | Low | Low — rewrite to individual SET | Contained in db.py, one method |
| Full-node RETURN doesn't work | Medium | Medium — many queries need explicit fields | `_execute_query` can handle both patterns |
| Constraint API only on sync Graph | Medium | Low — fall back to raw Redis command per D7 | `apply_constraints()` encapsulates |
| FalkorDBLite subprocess crash | Low | Medium — corrupt .db file | Research: check if Redis AOF/RDB journaling protects |
