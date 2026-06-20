# Phase 1 Research — Spec Assumption Verification

> Verified 2026-06-19 against `falkordblite==0.10.0`, `FalkorDB==1.6.1`, `redis==7.4.1` (downgraded from 8.0.0; see Blocker B0).

---

## Blocker B0 — redis 8.0.0 incompatibility

**Before any assumption could be tested**, the installed `redis==8.0.0` package broke FalkorDBLite startup with:

```
ValueError: Cannot enable maintenance notifications for connection object
that doesn't have a host attribute.
```

Redis 8.0.0 added a `maintenance_notifications` feature that calls `_enable_maintenance_notifications` during connection setup. Redislite's `SyncRedis` subclass uses Unix-domain sockets (no `host` attribute), so the check crashes.

**Fix:** `pip install "redis<8"` (resolved to 7.4.1). The `pyproject.toml` must pin `redis<8` (or `falkordblite` must be updated upstream). Without this pin, `pip install -e .` on a fresh env will pull redis 8.x and nothing works.

---

## Spec Verification Table

| ID | Assumption | Status | Evidence |
|----|-----------|--------|----------|
| A1 | `from redislite.async_falkordb_client import AsyncFalkorDB` is correct | **VALIDATED** | Import succeeds. |
| A2 | `QueryResult.header` exposes column names enabling `dict(zip(header, row))` | **VALIDATED** (with nuance) | `.header` exists but returns `[[type_code, name], ...]` not bare strings. Must extract `h[1]` per item: `names = [h[1] for h in result.header]`. Then `dict(zip(names, row))` works correctly. |
| A3 | `SET r += $props` works | **VALIDATED** | Tested: `SET n += $props` with `params={'props': {'a': 1, 'b': 2}}` — properties merged onto existing node successfully. |
| A4 | `RETURN r` (full node) gives extractable properties | **VALIDATED** (with nuance) | Returns `falkordb.node.Node` object with `.properties` dict. **Critical:** `dict(node)` FAILS (`TypeError: 'Node' object is not iterable`). Code must use `node.properties` not `dict(node)`. The existing `build_pipeline` at line 517 does `dict(record["r"])` which will break. `_execute_query()` must auto-detect Node objects and call `.properties` on them. |
| A5 | `collect(r {.*})` map projection works | **VALIDATED** | Returns `list[OrderedDict]` (not plain dicts). `OrderedDict` is dict-compatible, so downstream code works unchanged. |
| A6 | Async Graph exposes `create_node_unique_constraint()` and `create_node_range_index()` | **VALIDATED** | Both methods present on the async graph object. Also found: `create_node_fulltext_index`, `create_edge_range_index`. |
| A7 | `CALL db.constraints()` procedure exists | **VALIDATED** | Procedure exists. Returns columns: `type, label, properties, entitytype, status`. Returns empty `result_set` when no constraints exist. |
| A8 | FalkorDBLite rejects a second opener on the same file | **INVALIDATED** | Second `AsyncFalkorDB` on the same DB path succeeds — queries work from both connections. Redislite maintains a pidfile in a temp directory (`/var/folders/.../redis.pid`), not alongside the DB file, and it does NOT prevent concurrent access. **The spec's lockfile approach (D10) is necessary and correct.** |
| A9 | Duplicate index/constraint error contains "already exist" | **INVALIDATED** (partially) | **Indexes:** error message is `"Attribute 'id' is already indexed"` — does NOT contain "already exist". **Constraints:** error message is `"Constraint already exists"` — DOES contain "already exist". Error type is `ResponseError` for both. The catch pattern must handle both message formats. |
| A10 | `build_pipeline()` has only one `Neo4jConnection` type annotation in pipeline.py | **INVALIDATED** (minor) | There are TWO references: (1) `from writ.graph.db import Neo4jConnection` at line 48, and (2) the parameter annotation `db: Neo4jConnection` at line 489. Both must change. The spec says "the only annotation change needed" — the import line is also needed. |

---

## Invalidated Assumptions — Resolutions

### A8 — FalkorDBLite allows concurrent openers

**Impact:** Low — the spec already prescribes a lockfile (D10). This just confirms D10 is mandatory, not optional.

**Resolution:** No spec change needed. D10's lockfile design is correct. The lockfile MUST be implemented because FalkorDBLite provides no built-in mutual exclusion.

### A9 — Error messages differ between index and constraint duplication

**Impact:** Medium — the D11 error-swallowing pattern `"already exist" in str(e).lower()` will NOT catch duplicate index errors.

**Resolution:** Change the catch pattern to check for EITHER message:
```python
msg = str(e).lower()
if "already exist" in msg or "already indexed" in msg:
    pass  # Idempotent — swallow
else:
    raise
```

### A10 — Two Neo4jConnection references in pipeline.py, not one

**Impact:** Low — trivially fixable. Both the import (line 48) and the type annotation (line 489) must change.

**Resolution:** Change both:
- Line 48: `from writ.graph.db import Neo4jConnection` becomes `from writ.graph.db import FalkorDBLiteConnection` (or `GraphConnection` Protocol)
- Line 489: `db: Neo4jConnection` becomes `db: FalkorDBLiteConnection` (or `db: GraphConnection`)

---

## Supplemental Findings (not in assumption list)

### S1 — `dict(node)` does not work on FalkorDB Node objects

The existing `build_pipeline` code (line 517, 535) does `dict(record["r"])` to convert Neo4j Node objects to dicts. FalkorDB's `Node` object is NOT iterable — `dict(node)` raises `TypeError`. The `_execute_query()` method must detect `Node` objects in result rows and auto-extract `.properties`. The `Node` class is `falkordb.node.Node` with attributes: `alias`, `id`, `labels`, `properties`, `to_string`.

### S2 — `QueryResult.header` format is `[[type_code, name], ...]`

Each header item is a two-element list: `[1, 'column_alias']`. The type code appears to always be `1` for scalar column types. The `_execute_query()` implementation must use `h[1]` to extract column names, not index `h` directly.

### S3 — `redis>=8.0.0` breaks FalkorDBLite

`pyproject.toml` must add an upper bound on redis: either `redis>=5.0,<8` or let `falkordblite` handle the pin. Without this, fresh installs will fail silently.

### S4 — `collect(r {.*})` returns `OrderedDict`, not plain `dict`

This is functionally compatible but worth noting for type checkers or assertions that explicitly check `isinstance(x, dict)`. `OrderedDict` is a `dict` subclass, so `isinstance` checks pass.

---

## Deferred Questions

None. All 10 assumptions were testable and verified.
