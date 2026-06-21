"""Phase 3B of the public rulebook expansion: Performance & Caching.

Seeds 14 new PERF-* rules into the graph (1 mandatory: PERF-QUERY-001 N+1).

PERF-LAZY-001 already exists with a PHP-specific Writ statement and
matches the public-rulebook semantics; the existing rule is kept as-is.

The Writ-specific performance rules are retained as project-specific
extensions (different scope from the public set):
  PERF-IO-001       hot-path sync-I/O ban (stricter than PERF-ASYNC-001)
  PERF-QBUDGET-001  Query Budget Plan process rule (complements PERF-QUERY-004)
  PERF-BIGO-001     nested-loop algorithmic complexity (orthogonal to PERF-QUERY-002 indexes)
  PERF-OPT-001      "don't optimize without measure" (no public equivalent)

Idempotent. Re-runs MERGE existing rules with the same rule_id.

Per the public rulebook source: out-of-the-box-rules.md section 8.
"""

from __future__ import annotations

import asyncio
from datetime import date

from writ.config import get_falkordb_path, get_falkordb_graph, get_falkordb_module, get_redis_bin
from writ.graph.db import FalkorDBLiteConnection

TODAY = date.today().isoformat()


def _rule(
    rid: str,
    severity: str,
    scope: str,
    trigger: str,
    statement: str,
    violation: str,
    pass_example: str,
    enforcement: str,
    rationale: str,
    mandatory: bool = False,
    mechanical_enforcement_path: str | None = None,
) -> dict:
    return {
        "rule_id": rid,
        "domain": "performance",
        "severity": severity,
        "scope": scope,
        "trigger": trigger,
        "statement": statement,
        "violation": violation,
        "pass_example": pass_example,
        "enforcement": enforcement,
        "rationale": rationale,
        "mandatory": mandatory,
        "mechanical_enforcement_path": mechanical_enforcement_path,
        "confidence": "production-validated",
        "authority": "human",
        "times_seen_positive": 0,
        "times_seen_negative": 0,
        "last_validated": TODAY,
        "evidence": "doc:public-rulebook-2026-05",
        "staleness_window": 365,
        "always_on": False,
        "body": "",
        "source_attribution": "out-of-the-box-rules.md section 8",
        "source_commit": "",
    }


ANALYZER_PATH = "bin/run-analysis.sh::analyze_performance_n_plus_one"


RULES = [
    _rule("PERF-QUERY-001", "critical", "component",
        "When iterating over a collection and accessing a related entity inside the loop body.",
        "N+1 database query patterns are forbidden. When loading a list of N parents and then accessing each parent's children inside the loop, use joins, eager loading (Django select_related/prefetch_related, SQLAlchemy joinedload, Eloquent with()), or batch fetching. One query per item in a loop is a violation.",
        "```python\norders = Order.query.all()\nfor order in orders:\n    print(order.customer.name)  # N+1: one customer query per order\n```",
        "```python\norders = Order.query.options(joinedload(Order.customer)).all()\nfor order in orders:\n    print(order.customer.name)  # single JOINed query\n```",
        f"Mechanically enforced by {ANALYZER_PATH}: regex flags loop bodies that contain ORM access (`.filter`, `.get`, `.query`, `.find`, `.where`, `.first`, `.fetch`, `.where(...).first`) where the loop variable is referenced in the query. Heuristic; reviewer judgment closes false positives.",
        "N+1 is the single most common database performance bug. A list page with 100 items can issue 100+ extra queries, scaling with traffic. Eager loading or batch fetching is the structural defense.",
        mandatory=True,
        mechanical_enforcement_path=ANALYZER_PATH,
    ),
    _rule("PERF-QUERY-002", "high", "component",
        "When writing database queries that filter (WHERE) or join (JOIN) on a column.",
        "Columns used in WHERE clauses or JOIN conditions for non-trivial table sizes must have indexes. Full-table scans on production-sized tables are violations. The migration that introduces the query is accompanied by the migration that creates the index.",
        "```python\n# WHERE customer_id = ? with no index on orders.customer_id; full scan on 50M rows.\nOrder.query.filter_by(customer_id=cid).all()\n```",
        "```python\n# Migration: CREATE INDEX idx_orders_customer_id ON orders(customer_id);\nOrder.query.filter_by(customer_id=cid).all()\n```",
        "Schema review during migration PRs. Query plans (EXPLAIN) for new queries.",
        "Unindexed queries are O(N) on table size; indexed queries are O(log N). The difference becomes catastrophic as data grows.",
    ),
    _rule("PERF-QUERY-003", "medium", "component",
        "When writing SELECT queries against any table.",
        "Queries specify the columns needed, not `SELECT *`. Wide rows transferred over the network when the consumer needs three fields wastes bandwidth, memory, and ORM hydration time.",
        "```python\nOrder.query.all()  # full row hydration including 30-column BLOB\n```",
        "```python\nOrder.query.with_entities(Order.id, Order.status, Order.total).all()\n```",
        "Code review.",
        "Wide selects compound at scale: 50KB rows fetched 1000 times is 50MB of unused data on the wire. Narrow selects are free wins.",
    ),
    _rule("PERF-QUERY-004", "medium", "component",
        "When implementing list endpoints that return collections.",
        "List endpoints require pagination with a maximum page size. Unbounded result sets are violations. Pagination is parameterized (limit/offset, cursor, or page/per_page); the default page size is small (10-25); the maximum is bounded (100-200).",
        "```python\n@app.get('/api/orders')\ndef list_orders():\n    return Order.query.all()  # could be 10 million rows\n```",
        "```python\n@app.get('/api/orders')\ndef list_orders(page: int = 1, per_page: int = 25):\n    per_page = min(per_page, 200)\n    return paginate(Order.query, page, per_page)\n```",
        "Code review.",
        "An unbounded list endpoint is a database DoS waiting to happen. Bounded pagination caps the worst case at the API layer.",
    ),
    _rule("PERF-CACHE-001", "high", "component",
        "When caching the result of a function or query that varies by user, tenant, locale, or other parameter.",
        "Cache keys include every parameter that affects the cached value. A cache key that omits user_id is a violation: it lets one user's response be returned to another user.",
        "```python\n@cache.memoize()\ndef get_recommendations():\n    return personalize_for(current_user())  # current_user changes; key doesn't\n```",
        "```python\n@cache.memoize(make_name=lambda f: f'{f.__name__}:{current_user().id}')\ndef get_recommendations():\n    return personalize_for(current_user())\n```",
        "Code review.",
        "Stale cross-user cache hits are at best a wrong-data bug and at worst a data-leak vulnerability. Complete cache keys close the gap.",
    ),
    _rule("PERF-CACHE-002", "high", "component",
        "When setting a cache entry.",
        "Cache entries have an explicit TTL. Indefinite caching without an invalidation strategy is a violation. The TTL is short enough that stale data is bounded; the invalidation strategy is short enough that fresh data is bounded.",
        "```python\ncache.set(key, value)  # default behavior may be 'forever'\n```",
        "```python\ncache.set(key, value, ex=300)  # 5-minute TTL; documented invalidation on write\n```",
        "Code review.",
        "Indefinite cache becomes a parallel database that drifts. TTL provides a freshness ceiling even when explicit invalidation fails.",
    ),
    _rule("PERF-CACHE-003", "medium", "component",
        "When writing data that has a cached representation.",
        "Cache invalidation on write is explicit. The write path explicitly invalidates or refreshes the affected cache entries. 'It will expire eventually' is not a strategy.",
        "```python\ndef update_user(user_id, **fields):\n    db.update(User, id=user_id, **fields)\n    # cache key 'user:<id>' still serves the old value for the next TTL window\n```",
        "```python\ndef update_user(user_id, **fields):\n    db.update(User, id=user_id, **fields)\n    cache.delete(f'user:{user_id}')\n```",
        "Code review.",
        "TTL-only invalidation leaves staleness windows that produce visible bugs (user updates name, sees old name). Explicit invalidation closes the window.",
    ),
    _rule("PERF-CACHE-004", "medium", "component",
        "When implementing caches that may be hit by many concurrent requests after an entry expires.",
        "Cache stampede is mitigated: when a popular cache entry expires, many concurrent callers must not all hit the underlying store at once. Mechanisms: short locks on regenerate, probabilistic early expiration, background refresh.",
        "```python\ndef get(key):\n    if cache.has(key):\n        return cache.get(key)\n    value = expensive_compute()  # 1000 concurrent callers all do this\n    cache.set(key, value, ex=300)\n    return value\n```",
        "```python\n@cached(early_expiration_fraction=0.1)  # 10% of callers refresh ahead of TTL\ndef get(key):\n    return expensive_compute()\n```",
        "Code review. Cache libraries (cachetools, django-cacheops) implement stampede protection.",
        "A stampeded cache turns the protected resource into the bottleneck precisely when it most needs protection.",
    ),
    _rule("PERF-MEM-001", "high", "component",
        "When processing collections that may grow with input size: rows from a query, lines from a file, items from an API.",
        "Large collections are processed via streaming/iteration, not loaded entirely into memory. Generator expressions, iterator protocols, server-side cursors, chunked reads. Loading the full result set when the consumer needs one row at a time is a violation.",
        "```python\nrows = db.execute('SELECT * FROM events').fetchall()  # 10M rows in memory\nfor r in rows: process(r)\n```",
        "```python\nfor r in db.execute('SELECT * FROM events').yield_per(1000):\n    process(r)\n```",
        "Code review.",
        "In-memory loading scales with the data size; streaming scales with the working-set size. The difference is the difference between OOM and steady operation.",
    ),
    _rule("PERF-MEM-002", "medium", "component",
        "When writing long-running processes (workers, daemons, web servers, ML training loops).",
        "Object references are released after use. Long-running processes do not retain unbounded structures (caches without eviction, growing dicts, accumulating lists). Memory-leak patterns are reviewed and bounded.",
        "```python\nWORK_LOG = []  # appended forever; never released\ndef process(item):\n    WORK_LOG.append(item)\n    do_work(item)\n```",
        "```python\nfrom collections import deque\nWORK_LOG = deque(maxlen=1000)  # bounded\ndef process(item):\n    WORK_LOG.append(item)\n    do_work(item)\n```",
        "Memory profiling. Code review.",
        "Memory leaks turn long-running processes into delayed crashes. Bounded structures keep memory predictable.",
    ),
    _rule("PERF-ASYNC-001", "high", "component",
        "When implementing I/O-bound operations in a runtime that supports async (Python asyncio, Node, Tokio, Kotlin coroutines).",
        "I/O-bound operations use async / non-blocking calls, not synchronous blocking. The event loop is not stalled waiting for HTTP, DB, or file I/O.",
        "```python\nasync def handle():\n    response = requests.get(url)  # sync HTTP in async fn\n    return response.json()\n```",
        "```python\nasync def handle():\n    response = await httpx.AsyncClient().get(url)\n    return response.json()\n```",
        "Code review. Linter rules (asyncio-blocker check, eslint async-no-floating-promises).",
        "Sync I/O in an async loop stalls every other concurrent request on that worker. Async preserves the concurrency model.",
    ),
    _rule("PERF-BATCH-001", "medium", "component",
        "When making multiple independent I/O calls within a request handler.",
        "Independent I/O calls run in parallel. `Promise.all`, `asyncio.gather`, `tokio::join!`, goroutine + WaitGroup. Serial awaiting of independent calls is a violation.",
        "```javascript\nconst user = await fetchUser(id);\nconst orders = await fetchOrders(id);\nconst notifications = await fetchNotifications(id);\n// 3 sequential round-trips\n```",
        "```javascript\nconst [user, orders, notifications] = await Promise.all([\n    fetchUser(id),\n    fetchOrders(id),\n    fetchNotifications(id),\n]);\n```",
        "Code review.",
        "Sequential awaiting is N*latency when the work is parallelizable. Parallel I/O is max(latency).",
    ),
    _rule("PERF-BUNDLE-001", "medium", "component",
        "When serving JavaScript or CSS to web clients.",
        "Frontend assets are bundled and minified for production. Unminified, un-bundled, or unhashed source files are not served in production. Build tooling (webpack, vite, rollup, esbuild) produces the bundle; CI gates the asset checks.",
        "```\n# Production index.html includes <script src='main.js'> with 30 separate <script> tags.\n```",
        "```\n# Production index.html includes <script src='main.a2c4f8.min.js'> (one bundle).\n```",
        "CI gate (asset-size budget; lighthouse score).",
        "Unbundled assets multiply HTTP round-trips and shipping bytes. Bundling and minification are zero-effort wins at deploy time.",
    ),
    _rule("PERF-IMAGE-001", "low", "component",
        "When serving images to web clients.",
        "Images are served in modern formats (WebP, AVIF) when supported, sized appropriately for the rendered display, and lazy-loaded for off-screen content. Original-resolution PNGs in image elements rendered at 200x200 are violations.",
        "```html\n<img src='/avatars/user.png' width=200 height=200>\n<!-- backend serves 4000x4000 PNG -->\n```",
        "```html\n<picture>\n  <source srcset='/avatars/user-200.avif' type='image/avif'>\n  <source srcset='/avatars/user-200.webp' type='image/webp'>\n  <img src='/avatars/user-200.png' width=200 height=200 loading='lazy'>\n</picture>\n```",
        "Image-optimization pipeline (next/image, Cloudinary, ImgIX).",
        "Image bytes dominate frontend payload. Modern formats and right-sizing cut payload by 50-80%; lazy loading defers off-screen cost.",
    ),
]


async def main() -> None:
    db = FalkorDBLiteConnection(
        get_falkordb_path(), get_falkordb_graph(),
        get_falkordb_module(), get_redis_bin(),
    )
    try:
        created = updated = 0
        for rule in RULES:
            rows = db._execute_query(
                "MATCH (r:Rule {rule_id: $rid}) RETURN r.rule_id AS x", rid=rule["rule_id"]
            )
            exists = bool(rows)
            props = {k: v for k, v in rule.items() if k != "rule_id"}
            db._execute_query(
                """
                MERGE (r:Rule {rule_id: $rid})
                SET r += $props
                """,
                rid=rule["rule_id"], props=props,
            )
            if exists:
                updated += 1
                print(f"UPDATED {rule['rule_id']:30s} {'[M]' if rule['mandatory'] else '   '} {rule['severity']}")
            else:
                created += 1
                print(f"CREATED {rule['rule_id']:30s} {'[M]' if rule['mandatory'] else '   '} {rule['severity']}")

        print()
        print(f"Summary: {created} created, {updated} updated.")

        rows = db._execute_query("MATCH (r:Rule) RETURN count(r) AS n")
        print(f"Total rules: {rows[0]['n']}")
        rows = db._execute_query("MATCH (r:Rule) WHERE r.mandatory = true RETURN count(r) AS n")
        print(f"Mandatory: {rows[0]['n']}")
    finally:
        await db.close()


if __name__ == "__main__":
    asyncio.run(main())
