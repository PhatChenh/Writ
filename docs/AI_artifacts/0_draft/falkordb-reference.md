# FalkorDBLite — Implementation Reference for Writ Phase 1

> Compiled 2026-06-19 from official docs + source inspection.
> This doc gives a future AI everything needed to implement the Neo4j → FalkorDBLite swap without re-researching.

## Source Links (trace these if anything below is outdated)

- [FalkorDBLite GitHub repo](https://github.com/FalkorDB/falkordblite) — README, examples, async API
- [FalkorDBLite PyPI](https://pypi.org/project/falkordblite/) — latest version, install instructions
- [FalkorDBLite official docs](https://docs.falkordb.com/operations/falkordblite/falkordblite-py.html) — Python usage guide
- [FalkorDB Cypher coverage](https://docs.falkordb.com/cypher/cypher-support.html) — supported/unsupported Cypher features
- [FalkorDB functions](https://docs.falkordb.com/cypher/functions.html) — all functions by category
- [FalkorDB data types](https://docs.falkordb.com/datatypes.html) — type system, temporal types, limitations
- [FalkorDB procedures](https://docs.falkordb.com/cypher/procedures.html) — db.indexes(), db.constraints(), etc.
- [FalkorDB constraint creation](https://docs.falkordb.com/commands/graph.constraint-create.html) — GRAPH.CONSTRAINT CREATE command
- [falkordb-py (Python client)](https://github.com/FalkorDB/falkordb-py) — upstream client that FalkorDBLite mirrors

## Requirements

- **Python 3.12+** (hard requirement)
- **macOS:** install OpenMP runtime: `brew install libomp`
- **Package:** `pip install falkordblite` (latest v0.10.0, May 2026)

## How It Works Internally

FalkorDBLite starts a local Redis server process with the FalkorDB module loaded. It's a managed subprocess — not in-process. Data persists in the DB file between sessions. The Python API communicates with this subprocess via Redis protocol. Secure by default — only accessible to the creating user.

## Connection + Lifecycle

### Sync API

```python
from redislite.falkordb_client import FalkorDB

db = FalkorDB('/tmp/falkordb.db')     # starts subprocess, creates file if not exists
g = db.select_graph('writ')           # select/create named graph
result = g.query('MATCH (n) RETURN n')
db.close()                            # or use context manager
```

### Async API (what Writ uses)

```python
from redislite.async_falkordb_client import AsyncFalkorDB

db = AsyncFalkorDB('/path/to.db')     # starts subprocess immediately on construction
g = db.select_graph('writ')           # returns async graph handle
result = await g.query('MATCH (n:Rule) RETURN n.rule_id, n.domain', params={'key': 'val'})
await db.close()
```

**Context manager (preferred for cleanup):**

```python
async with AsyncFalkorDB('/path/to.db') as db:
    g = db.select_graph('writ')
    result = await g.query(...)
    # auto-closes on exit
```

**Concurrent operations supported:**

```python
await asyncio.gather(
    g.query('CREATE ...', params={...}),
    g.query('CREATE ...', params={...}),
)
```

## Query Results — CRITICAL DIFFERENCE FROM NEO4J

**Neo4j returns named records:** `record["field"]`, `dict(record["r"])`

**FalkorDB returns positional tuples:** `row[0]`, `row[1]`

Results come as `QueryResult` with a `result_set` attribute containing rows:

```python
result = await g.query('MATCH (r:Rule) RETURN r.rule_id AS id, r.domain AS dom')
for row in result.result_set:
    rule_id = row[0]   # positional — maps to first RETURN column
    domain = row[1]    # maps to second RETURN column
```

**This is why `_execute_query()` must normalize results to `list[dict]`** — map RETURN column aliases to positions. Verify how `QueryResult` exposes column names (likely via `result.header`).

### Read-only queries

```python
result = await g.ro_query('MATCH (r:Rule) RETURN r.rule_id')
```

Uses `GRAPH.RO_QUERY` internally. Same result format. Use for reads in hot path.

## Cypher Compatibility

### Confirmed supported (safe to use as-is)

| Feature | Notes |
|---------|-------|
| MERGE | Works |
| SET | Works |
| SET += $props | **VERIFY** — not explicitly confirmed |
| CREATE | Works |
| MATCH, WHERE, RETURN, ORDER BY | Work |
| DETACH DELETE | Works — auto-deletes relationships |
| UNWIND | Works |
| collect() | Works for non-null elements |
| count() | Works |
| type(rel) | Returns relationship type string |
| startNode(rel), endNode(rel) | Return source/destination node |
| coalesce() | Returns first non-null argument |
| Parameterized queries | `params={'key': value}` dict |
| toInteger(), toString(), toFloat() | Work |
| collect(r {.*}) map projection | **VERIFY** — not confirmed in docs |

### NOT supported or different from Neo4j

| Feature | Neo4j | FalkorDB | Impact |
|---------|-------|----------|--------|
| `datetime()` | Native function | **NOT a native function.** Use `localdatetime("2025-06-29T13:45:00")` for DateTime type. UDF `date.*` functions available. | Queries using `datetime()` must change to `localdatetime()` |
| `duration()` | Native function | **NOT a native function** | `increment_positive`/`increment_negative` queries that use `datetime()` must be rewritten |
| `IF NOT EXISTS` on indexes | Supported | **NOT supported** | Use try/except per D3 |
| Named indexes | `CREATE INDEX name ...` | **No named indexes** | Drop index names from DDL |
| `SHOW INDEXES` | Cypher command | **NOT supported** — use `CALL db.indexes()` procedure | |
| `SHOW CONSTRAINTS` | Cypher command | **NOT supported** — use `CALL db.constraints()` procedure | |
| `CREATE CONSTRAINT` via Cypher | Cypher | **Redis command only** — `GRAPH.CONSTRAINT CREATE` | Use Python API `create_node_unique_constraint()` or raw Redis command |
| Maps as node properties | Supported | **NOT supported** — "Maps cannot be stored as property values" | `_coerce_neo4j_value()` JSON-serializes dicts. Verify FalkorDB stores JSON strings OK |

### Temporal types (important detail)

FalkorDB has temporal types but uses **different constructor functions** than Neo4j:

```
Neo4j:       datetime()           → FalkorDB: localdatetime("YYYY-MM-DDTHH:MM:SS")
Neo4j:       date()               → FalkorDB: date("YYYY-MM-DD")
Neo4j:       time()               → FalkorDB: localtime("HH:MM:SS")
```

Temporal values support comparison operators and component extraction (`.year`, `.month`, `.day`, `.hour`, `.minute`, `.second`).

**Impact on Writ queries:** `increment_positive()` and `increment_negative()` use `r.last_seen = datetime()`. Must change to `r.last_seen = localdatetime(...)` with current timestamp passed as param, or store as ISO string instead.

## Index Creation

```python
# Via Cypher (no name, no IF NOT EXISTS)
await g.query('CREATE INDEX FOR (n:Rule) ON (n.domain)')

# Via Python API
g.create_node_range_index('Rule', 'domain')
```

No `IF NOT EXISTS` — wrap in try/except, catch "already exists" error (verify exact error type).

## Constraint Creation

Constraints use Redis commands, not Cypher. The Python client exposes high-level methods:

```python
# Must create supporting index FIRST for unique constraints
g.create_node_range_index('Rule', 'rule_id')

# Then create unique constraint
g.create_node_unique_constraint('Rule', 'rule_id')
```

**Constraint lifecycle:**
1. Command returns `PENDING` immediately
2. Status → `UNDER CONSTRUCTION` (gradual enforcement)
3. Status → `OPERATIONAL` (all nodes conform) or `FAILED` (conflict found)

**Check constraint status:**

```python
result = await g.ro_query('CALL db.constraints()')
# Returns: type, label, properties, entitytype, status
```

**Synchronous failure cases (immediate error):**
- Syntax error
- Constraint already exists
- Missing supporting index (unique constraints)

## Available Procedures

| Procedure | Returns | Purpose |
|-----------|---------|---------|
| `db.labels()` | label | All node labels |
| `db.relationshipTypes()` | relationshipType | All relationship types |
| `db.propertyKeys()` | propertyKey | All property keys |
| `db.indexes()` | label, properties, types, options, language, stopwords, entitytype, status, info | All indexes with status |
| `db.constraints()` | type, label, properties, entitytype, status | All constraints with status |
| `db.meta.stats()` | labels, relTypes, relCount, nodeCount, labelCount, relTypeCount, propertyKeyCount | Graph statistics |
| `db.idx.fulltext.createNodeIndex()` | (none) | Create full-text index |
| `db.idx.fulltext.queryNodes()` | node, score | Full-text search |

## Data Type Gotchas

1. **Maps cannot be stored as node properties.** Writ's `_coerce_neo4j_value()` already JSON-serializes dicts to strings — verify FalkorDB stores/retrieves these strings correctly.
2. **Lists can be stored** if elements are serializable (no nodes, no nulls).
3. **Strict type comparison:** `1 = true` → false. Boolean stored as numeric internally but types differ.
4. **Strings, integers, floats, booleans, arrays, points, temporal types** all supported as properties.

## Neo4j → FalkorDBLite Migration Cheat Sheet

| Neo4j pattern | FalkorDBLite equivalent |
|---------------|----------------------|
| `AsyncGraphDatabase.driver(uri, auth=(...))` | `AsyncFalkorDB('/path/to.db')` |
| `driver.session(database="neo4j")` | `db.select_graph('writ')` |
| `await session.run(query, **params)` | `await graph.query(query, params={...})` |
| `record["field"]` | `row[0]` (positional) |
| `dict(record["r"])` | Need custom extraction from result_set |
| `record.data()` | Row is already a tuple, convert to dict via header |
| `[rec.data() async for rec in result]` | `result.result_set` (already a list) |
| `await result.single()` | `result.result_set[0]` if `len(result.result_set) > 0` else None |
| `await driver.close()` | `await db.close()` |
| `SHOW INDEXES` | `CALL db.indexes()` |
| `SHOW CONSTRAINTS` | `CALL db.constraints()` |
| `CREATE CONSTRAINT name IF NOT EXISTS FOR (r:Rule) REQUIRE r.rule_id IS UNIQUE` | `graph.create_node_unique_constraint('Rule', 'rule_id')` (must create index first) |
| `CREATE INDEX name IF NOT EXISTS FOR (r:Rule) ON (r.domain)` | `graph.create_node_range_index('Rule', 'domain')` (no name, wrap in try/except) |
| `datetime()` | `localdatetime("ISO-string")` or store as ISO string |

## What We Don't Know Yet (verify during implementation)

See "Open implementation questions" in `docs/AI_artifacts/0_draft/phase1-decisions.md`.
