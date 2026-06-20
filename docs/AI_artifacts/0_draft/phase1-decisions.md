# Phase 1 — Core Storage Swap: Decisions

> Resolved via grill session 2026-06-19. These are binding for implementation.

## Scope

Replace Neo4j async driver in `writ/graph/db.py` with FalkorDBLite embedded graph. Update `config.py`, `writ.toml`, `pyproject.toml`. Identical behavior preservation — every method's inputs/outputs match exactly.

## Decisions

### D1: Python minimum → 3.12

FalkorDBLite requires Python 3.12+. Bump `requires-python` in `pyproject.toml` from `>=3.11` to `>=3.12`. Acceptable — single-user local tool, 3.12 out since Oct 2023.

### D2: Database file location — per-project

FalkorDBLite stores data at `.writ/graph.db` relative to project root. Configurable via `writ.toml [falkordb] path`.

**Why per-project:** Rule corpus is project-specific (bible/ in repo). Runtime state (counters, confidence) belongs to that project. Natural isolation across repos.

**Action:** Add `.writ/` to `.gitignore`.

### D3: Idempotent setup via try/except

FalkorDBLite lacks `IF NOT EXISTS` for indexes and constraints. `apply_constraints()` wraps each creation in try/except, swallowing "already exists" errors, propagating real ones.

**Why not check-then-create:** TOCTOU pattern, more round-trips, same result.

### D4: Strict behavior preservation

Every public method on `Neo4jConnection` (renamed `FalkorDBLiteConnection`) must return identical types and semantics. Rest of codebase stays untouched.

**Post-Phase 1:** Convert this rule into a Writ rule once dogfooding is possible (Phase 4).

## Research Findings (inform implementation)

### FalkorDBLite API shape

| Aspect | Neo4j (current) | FalkorDBLite (target) |
|--------|-----------------|----------------------|
| Package | `neo4j` | `falkordblite` |
| Import | `from neo4j import AsyncGraphDatabase` | `from redislite.async_falkordb_client import AsyncFalkorDB` |
| Connection | `AsyncGraphDatabase.driver(uri, auth=(...))` | `AsyncFalkorDB('/path/to.db')` |
| Graph selection | `session(database="neo4j")` | `db.select_graph('writ')` |
| Query execution | `await session.run(query, **params)` | `await graph.query(query, params={...})` |
| Result access | `record["field"]`, `dict(record["r"])` | `row[0]`, `row[1]` (positional tuples) |
| Read-only query | same as write | `graph.ro_query(...)` |
| Index creation | `CREATE INDEX name IF NOT EXISTS FOR (n:L) ON (n.p)` | `CREATE INDEX FOR (n:L) ON (n.p)` (no name, no IF NOT EXISTS) |
| Constraints | Cypher: `CREATE CONSTRAINT ... REQUIRE ... IS UNIQUE` | Redis cmd: `GRAPH.CONSTRAINT CREATE key UNIQUE NODE Label PROPERTIES 1 prop` |
| Constraint prereq | none | Index must exist first |
| List indexes | `SHOW INDEXES` | `CALL db.indexes()` |
| List constraints | `SHOW CONSTRAINTS` | `CALL db.constraints()` (TBD — verify) |
| Close | `await driver.close()` | `await db.close()` or context manager |

### Cypher compatibility (verified supported)

- MERGE, SET, SET +=, CREATE, MATCH, WHERE, RETURN, ORDER BY
- DETACH DELETE, UNWIND, collect(), count()
- type(), startNode(), endNode(), coalesce()
- datetime() → verify if `datetime()` or `localdatetime()` needed
- Parameterized queries via `params={}` dict

### Cypher gaps (need adaptation)

- No `IF NOT EXISTS` on indexes/constraints
- No named indexes
- No `SHOW CONSTRAINTS` / `SHOW INDEXES` (use CALL procedures)
- `collect(r {.*})` map projection — verify support, may need explicit property list
- Constraint creation is Redis command, not Cypher — need raw connection access

## Config shape (target)

```toml
[falkordb]
path = ".writ/graph.db"    # relative to project root
graph = "writ"             # graph name within the DB
```

## Done-when (from roadmap)

- `writ serve` starts without Neo4j/Docker running
- `writ ingest bible/` loads all rules into FalkorDBLite
- `writ query "security"` returns ranked results
- Graph contains all 12 node types and 10 edge types

### D5: Stay async — do not switch to sync

**Background:** FalkorDBLite is embedded (no network I/O), which tempted a switch to synchronous code for simplicity. However, 80+ callers use `await`, the retrieval pipeline is async and off-limits during this swap, and FalkorDBLite offers an async API (`AsyncFalkorDB`).

**Decision:** Keep all DB methods async. Use FalkorDBLite's async API.

**Tradeoffs:** Slightly more complex than sync for an embedded DB, but avoids rewriting 80+ call sites and touching the forbidden retrieval pipeline. Zero-risk path.

### D6: Add `_execute_query()` helper + refactor IntegrityChecker constructor

**Background:** ~34 call sites across 19 files bypass `Neo4jConnection`'s public API — they reach into `_driver.session()` directly and use Neo4j-specific record access patterns (`record["field"]`, `dict(record["r"])`). These are the hardest migration points because they're coupled to Neo4j's session and result objects. Separately, `IntegrityChecker` (`writ/graph/integrity.py`) takes the raw Neo4j driver in its constructor — it doesn't use `Neo4jConnection` at all.

**Decision:**
1. Add `_execute_query(cypher, params) -> list[dict]` as a private method on the new connection class. All ~25 reach-through call sites swap their 4-line session boilerplate for one call. The method handles session lifecycle + result normalization internally.
2. Refactor `IntegrityChecker.__init__` to accept the connection object instead of a raw driver + database string. One file, one constructor change, eliminates the only code holding a direct driver reference outside `db.py`.

**Tradeoffs:** `_execute_query()` is a private helper, not a public API expansion — no interface bloat. IntegrityChecker refactor is a small scope increase (1 extra file) but eliminates a deep coupling that would otherwise require duplicating the query helper. Alternative was adding 15+ new public methods for one-off queries — rejected as unnecessary API surface.

**Implications:** Phase 2 (seed script updates) and Phase 3 (test suite) will benefit — their raw session calls also go through `_execute_query()`, making those phases mechanical find-and-replace instead of per-site debugging.

### D8: Replace config functions entirely — no backward-compat shims

**Background:** `config.py` exposes `get_neo4j_uri()`, `get_neo4j_user()`, `get_neo4j_password()`. FalkorDBLite doesn't use URI/user/password — it needs a file path and graph name.

**Decision:** Delete `get_neo4j_*()` functions. Replace with `get_falkordb_path()` and `get_falkordb_graph()`. No shims, no re-exports, no "removed" comments. This is a divergent fork — no external consumers.

**Tradeoffs:** Clean break. Every caller importing `get_neo4j_*` will fail at import time (loud, easy to find and fix). Alternative was keeping shims that raise deprecation warnings — rejected as unnecessary complexity for a single-user fork.

**Implications:** Phase 2 (seed scripts) imports these functions in ~12 files. All become mechanical import swaps.

### D7: `apply_constraints()` stays self-contained, `_execute_query()` stays Cypher-only

**Background:** FalkorDBLite uses Cypher for indexes but Redis commands for constraints (`GRAPH.CONSTRAINT CREATE ...`), unlike Neo4j which used Cypher for both. This raised the question of whether `_execute_query()` should support a "raw command" mode.

**Decision:** No. `apply_constraints()` remains its own method and handles both code paths internally (Cypher for indexes, Redis command for constraints). `_execute_query()` stays a clean Cypher-only helper. This matches the original Writ structure — `apply_constraints()` was already a separate method; only its internals change.

**Tradeoffs:** Two code paths inside one method adds a small amount of internal complexity, but it's called once at startup and hidden from all callers. The alternative — making `_execute_query` aware of Redis commands — would pollute a general-purpose helper with setup-only logic.

### D9: Rename `Neo4jConnection` → `FalkorDBLiteConnection` — no alias

**Background:** 139 references to `Neo4jConnection` exist outside `db.py`. The class gets renamed per D4 (strict behavior preservation with new name). Question was whether to keep a backward-compat alias (`Neo4jConnection = FalkorDBLiteConnection`).

**Decision:** No alias. Rename all references in one shot. Same logic as D8 — loud import failure, easy grep-and-replace. Each phase renames the references it owns: Phase 1 handles `db.py` + `config.py` + core `writ/` package, Phase 2 handles `scripts/`, Phase 3 handles `tests/`.

**Tradeoffs:** More files touched per phase, but no ghost aliases polluting the codebase. Every reference is either correct or a clear error.

### D10: Single-accessor lockfile for DB file

**Background:** FalkorDBLite starts a Redis subprocess per `AsyncFalkorDB()` constructor. If `writ serve` is running and user runs `writ ingest` in another terminal, two subprocesses contend on the same `.writ/graph.db` file — potential corruption or cryptic Redis errors.

**Decision:** CLI commands check for a lockfile (`.writ/graph.lock` or similar pidfile). If the server holds it, CLI fails immediately with "server is running — use HTTP API or stop server first." Server acquires lock in lifespan startup, releases on shutdown.

**Tradeoffs:** User must stop server to run CLI ingest/export. Acceptable — single-user local tool, server is long-running dev process. Alternative (CLI routes through server API) adds HTTP client dependency and partial API coverage mapping. Rejected as over-engineering for single-user tool.

### D11: Broad catch + message check for "already exists" errors

**Background:** D3 (idempotent setup via try/except) needs to distinguish "already exists" from real errors. FalkorDBLite communicates via Redis protocol — errors likely come as `redis.exceptions.ResponseError` or FalkorDB subclass with a message string.

**Decision:** `apply_constraints()` catches `Exception`, checks if "already exist" (case-insensitive substring) appears in `str(e)`, re-raises otherwise. Research fills in exact error message string for tighter matching.

**Tradeoffs:** Broad catch with message check is robust against exception class changes across library versions. Slightly less precise than catching a specific class, but the re-raise-if-no-match makes accidental swallowing unlikely. Logging the swallowed "already exists" at DEBUG level for observability.

## Edgecase resolutions (from grill session 2026-06-19)

| EC | Concern | Resolution |
|----|---------|------------|
| EC-1 (concurrency) | Multiple FastAPI handlers hitting graph simultaneously | Safe — Redis serializes commands. Hot retrieval path uses in-process BM25+hnswlib, not graph. Low graph concurrency. |
| EC-2 (multi-process) | CLI + server on same DB file | D10 — lockfile, single accessor |
| EC-3 (atomicity) | Partial ingestion if mid-batch failure | Same as Neo4j — no transaction wrapping in current code. MERGE idempotent. `IngestReport.errors` handles partial failure. Not a regression. |
| EC-4 (constraint timing) | Constraint PENDING during early queries | Non-issue — all writes use MERGE which is idempotent regardless of constraint status |
| EC-5 (error types) | Swallowing wrong errors | D11 — broad catch + message check + re-raise |
| EC-6 (empty results) | `result.result_set` when no rows | Standard `[]` per Redis protocol. Research verifies. |
| EC-7 (param format) | `$param` in Cypher + dict keys | Same convention — mechanical `session.run(q, key=val)` → `g.query(q, params={'key': val})` |
| EC-8 (type round-trip) | Integer/string/None fidelity | `_coerce_neo4j_value()` already handles maps→JSON. Integers preserved by Redis. No regression. |

## Additional Cypher rewrites discovered

1. **`duration()` not supported** — `integrity.py:222` uses `datetime() - duration({days: $window_days})`. Must compute cutoff in Python, pass as `$cutoff` param, use `localdatetime($cutoff)`.
2. **`datetime()` in increment methods** — `db.py:397,410` use `r.last_seen = datetime()`. Must pass current ISO timestamp from Python as param.
3. **IntegrityChecker scope** — 8 methods use Neo4j-specific patterns (`record.data()`, `record["field"]`, `async for record in result`). All move to `_execute_query()` per D6. Larger than "a few call sites" — size-noted for planning.

## Open questions (spec states assumption → research verifies)

- [ ] Does `SET r += $props` work in FalkorDBLite? If not, SET each property individually. No design impact either way — contained in `db.py` methods.
- [ ] Does `collect(r {.*})` map projection work? If not, return specific fields. Used in `get_abstraction()` (db.py:270). No design impact — one query rewrite.
- [ ] Exact error message string for "already exists" on index/constraint creation (D11 pattern needs this).
- [ ] Does `CALL db.constraints()` exist? Documentation unclear. If not, D3 try/except pattern still covers it — create and swallow "already exists."
- [ ] Does the async Graph object expose `create_node_unique_constraint()`? If yes, D7 simplifies — use high-level method instead of raw Redis commands. Prefer high-level if available. If only sync has it, fall back to raw Redis inside `apply_constraints()`. D7 holds either way.
- [ ] How column names are accessible from `QueryResult` — likely `.header`. No design impact — `_execute_query()` encapsulates it per D6.
- [ ] FalkorDBLite lockfile behavior — does redislite already use a pidfile that would reject a second opener? If yes, D10 can leverage it instead of adding custom lockfile logic.
