"""Phase 4 of the public rulebook expansion: Scaling + API Design + Documentation.

Seeds 29 new SCALE-*, API-*, and DOC-* rules into the graph (1 mandatory:
SCALE-STATELESS-001) and renames the legacy ARCH-TYPE-001 -> DOC-TYPE-001.

Idempotent. Re-runs MERGE existing rules with the same rule_id.

Per the public rulebook source: out-of-the-box-rules.md sections 9, 10, 12.
"""

from __future__ import annotations

import asyncio
from datetime import date

from writ.config import get_falkordb_path, get_falkordb_graph, get_falkordb_module, get_redis_bin
from writ.graph.db import FalkorDBLiteConnection

TODAY = date.today().isoformat()


def _rule(
    rid: str,
    domain: str,
    severity: str,
    scope: str,
    trigger: str,
    statement: str,
    violation: str,
    pass_example: str,
    enforcement: str,
    rationale: str,
    source_section: str,
    mandatory: bool = False,
    mechanical_enforcement_path: str | None = None,
) -> dict:
    return {
        "rule_id": rid,
        "domain": domain,
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
        "source_attribution": f"out-of-the-box-rules.md section {source_section}",
        "source_commit": "",
    }


# ============================================================================
# 9. Scaling & Infrastructure (10 rules, 1 mandatory)
# ============================================================================
SCALE_RULES = [
    _rule("SCALE-STATELESS-001", "scaling", "high", "component",
        "When implementing application processes that handle multiple requests (web servers, API handlers, queue workers).",
        "Application processes are stateless. Session data, user state, in-progress workflows, and any data that must survive across requests is stored in an external store (Redis, database, cache service), not in process memory. Module-level mutable globals that hold per-user state are violations.",
        "```python\nUSER_CARTS = {}  # module-level dict; lost on restart; not shared across workers\n@app.post('/cart/add')\ndef add(item_id):\n    USER_CARTS.setdefault(current_user.id, []).append(item_id)\n```",
        "```python\n@app.post('/cart/add')\ndef add(item_id):\n    cart = redis_client.get(f'cart:{current_user.id}') or []\n    cart.append(item_id)\n    redis_client.set(f'cart:{current_user.id}', cart, ex=3600)\n```",
        "Code review. Look for module-level mutable dicts/lists that grow with users.",
        "Stateless processes scale horizontally: any worker can serve any request. Stateful processes pin the user to one machine, lose state on restart, and fail to scale beyond one node.",
        "9",
        mandatory=True,
        mechanical_enforcement_path="bin/run-analysis.sh::analyze_scaling_stateless",
    ),
    _rule("SCALE-STATELESS-002", "scaling", "medium", "component",
        "When persisting user-uploaded files or generated artifacts.",
        "File storage uses object storage (S3, GCS, Azure Blob, MinIO), not the local filesystem. Files written to local disk are not durable across deploys and are not shared across workers.",
        "```python\n@app.post('/avatar')\ndef upload(file):\n    file.save('/var/uploads/' + file.filename)\n```",
        "```python\n@app.post('/avatar')\ndef upload(file):\n    s3_client.put_object(Bucket='avatars', Key=f'{user.id}/{file.filename}', Body=file.read())\n```",
        "Code review.",
        "Local filesystem storage is invisible to other workers and disappears on container restart. Object storage is the structural fix.",
        "9"),
    _rule("SCALE-QUEUE-001", "scaling", "high", "component",
        "When implementing operations that take longer than the request timeout: video transcoding, large reports, batch emails, ML inference, external-API fan-out.",
        "Long-running operations are dispatched to a background queue (Celery, Sidekiq, RQ, BullMQ, SQS+worker), not executed inside the request cycle. The request returns a job ID; status is polled or pushed.",
        "```python\n@app.post('/reports')\ndef generate_report():\n    report = generate_huge_report()  # 60 seconds; request times out\n    return report\n```",
        "```python\n@app.post('/reports')\ndef generate_report():\n    job = queue.enqueue('generate_huge_report', user_id=current_user.id)\n    return {'job_id': job.id}, 202\n```",
        "Code review.",
        "Long-running synchronous work blocks the worker, hits client timeouts, and risks loss on deploy. Background queues decouple submission from completion.",
        "9"),
    _rule("SCALE-QUEUE-002", "scaling", "medium", "component",
        "When implementing background-queue consumers.",
        "Queue consumers are idempotent: receiving the same message twice does not corrupt state. Messages may be redelivered (worker crash mid-job, broker retry). Use idempotency keys, conditional writes, or upserts to absorb duplicates.",
        "```python\n@worker.task\ndef charge_user(user_id, amount):\n    stripe.charge(user_id, amount)  # duplicate delivery = double charge\n```",
        "```python\n@worker.task\ndef charge_user(user_id, amount, idempotency_key):\n    if PaymentLog.exists(idempotency_key):\n        return  # already processed\n    stripe.charge(user_id, amount, idempotency_key=idempotency_key)\n    PaymentLog.create(idempotency_key)\n```",
        "Code review.",
        "Message redelivery is normal in distributed queues. Idempotent consumers handle it; non-idempotent consumers produce silent data corruption.",
        "9"),
    _rule("SCALE-DB-001", "scaling", "high", "component",
        "When establishing database connections from application code.",
        "Database connections are pooled with size limits. Per-request connection creation is forbidden; the pool is initialized at startup. Pool size is bounded so that the application cannot exhaust the database's connection limit.",
        "```python\ndef get_user(id):\n    conn = psycopg2.connect(DATABASE_URL)  # new connection per call\n    ...\n    conn.close()\n```",
        "```python\npool = ConnectionPool(DATABASE_URL, min_size=2, max_size=10)\ndef get_user(id):\n    with pool.connection() as conn:\n        ...\n```",
        "Code review.",
        "Per-request connections are slow (handshake overhead), exhaust the DB's connection limit at peak, and fail under load. Pooling is the structural defense.",
        "9"),
    _rule("SCALE-DB-002", "scaling", "medium", "component",
        "When implementing read-heavy queries against a database that supports replication.",
        "Read replicas serve read-heavy queries where eventual consistency is acceptable (analytics, dashboards, list pages). Writes go to the primary; reads route to the closest healthy replica.",
        "```python\n# Every query, read or write, hits the primary.\nUser.query.all()\n```",
        "```python\nuser = User.query.all()  # reads to replica\nuser.update(...)  # writes to primary\n```",
        "Code review. ORM router config (Django DATABASES + DATABASE_ROUTERS, SQLAlchemy multiple binds).",
        "Reads dominate most workloads. Routing them to replicas offloads the primary and lets read capacity scale independently.",
        "9"),
    _rule("SCALE-HEALTH-001", "scaling", "high", "component",
        "When implementing health-check endpoints for orchestration systems (Kubernetes, ECS, load balancers).",
        "Health-check endpoints verify actual service readiness: DB connection, critical downstream dependencies, ability to serve a request. A 200 OK that doesn't check downstream dependencies is a violation.",
        "```python\n@app.get('/health')\ndef health():\n    return 'ok'  # serves OK even when DB is down\n```",
        "```python\n@app.get('/health')\ndef health():\n    db.execute('SELECT 1')\n    redis.ping()\n    return 'ok'\n```",
        "Code review.",
        "A trivial health check turns 'service ready' into 'process running' -- the load balancer keeps sending traffic to a worker that cannot serve.",
        "9"),
    _rule("SCALE-HEALTH-002", "scaling", "medium", "component",
        "When implementing health endpoints alongside Kubernetes-style readiness/liveness probes.",
        "Readiness (`/ready`) and liveness (`/live`) probes are distinct. Ready = can serve traffic now (deps healthy, warmup done). Live = process is responsive but not necessarily ready. A liveness failure restarts the pod; a readiness failure removes it from rotation.",
        "```python\n# Single /health endpoint used for both probes.\n```",
        "```python\n@app.get('/live')\ndef live(): return 'ok'\n@app.get('/ready')\ndef ready():\n    db.execute('SELECT 1')\n    return 'ok'\n```",
        "Code review.",
        "Conflating ready and live causes spurious pod restarts (DB blip restarts every replica) or zombie rotation (process is hung but health says ok). Separation matches Kubernetes semantics.",
        "9"),
    _rule("SCALE-CONFIG-001", "scaling", "medium", "component",
        "When introducing configurable behavior.",
        "Configuration supports environment-based overrides without code changes. Defaults live in code; per-environment values come from env vars, config files, or a secrets manager. New deployment targets do not require code edits.",
        "```python\nAPI_URL = 'https://api.prod.example.com'  # hardcoded\n```",
        "```python\nAPI_URL = os.environ.get('API_URL', 'https://api.example.com')\n```",
        "Code review.",
        "Hardcoded environment values force a build per environment and produce drift between staging and prod. Config-driven behavior eliminates the rebuild.",
        "9"),
    _rule("SCALE-MIGRATE-001", "scaling", "high", "component",
        "When deploying schema changes alongside rolling code deploys.",
        "Database migrations are backwards-compatible across the deployment window: old code can run against the new schema until the deploy completes. Destructive changes (drop column, rename column) are split into multiple deploys: 1) deploy code that stops using the column; 2) drop in a later deploy.",
        "```python\n# Single deploy: drop_column('users', 'legacy_email') + new code that uses 'email'.\n# Old pods still query 'legacy_email' during rollout -> errors.\n```",
        "```python\n# Deploy 1: new code reads/writes 'email'; migration adds 'email'.\n# Deploy 2 (later): migration drops 'legacy_email' once confirmed unused.\n```",
        "Code review.",
        "Forward-only migrations break rolling deploys: half the pods see the new schema, half the old. Phased migrations preserve the invariant that any code version works.",
        "9"),
]


# ============================================================================
# 10. API Design (12 rules)
# ============================================================================
API_RULES = [
    _rule("API-REST-001", "api-design", "medium", "component",
        "When defining HTTP endpoints in a REST-style API.",
        "HTTP methods match semantics: GET for reads (idempotent, no side effects), POST for creates, PUT/PATCH for updates, DELETE for deletes. A GET that mutates state is a violation.",
        "```python\n@app.get('/users/<id>/delete')\ndef delete_user(id): User.query.get(id).delete()\n```",
        "```python\n@app.delete('/users/<id>')\ndef delete_user(id): User.query.get(id).delete()\n```",
        "Code review.",
        "Method semantics drive correctness for caches, retries, and CSRF protections. A GET that deletes can be triggered by a link preview.",
        "10"),
    _rule("API-REST-002", "api-design", "medium", "component",
        "When defining URL paths for REST endpoints.",
        "Resource URLs are nouns. `/users`, `/orders/123`, `/orders/123/cancel`. Verb-style URLs (`/getUsers`, `/deleteOrder`) are violations except for explicit action endpoints (`/orders/123/cancel` is acceptable because it's an action on a noun).",
        "```\nGET /api/getUsers\nPOST /api/deleteOrder?id=123\n```",
        "```\nGET /api/users\nDELETE /api/orders/123\n```",
        "Code review.",
        "Noun-based URLs let the method carry the verb. The URL identifies the resource; the method says what to do with it.",
        "10"),
    _rule("API-STATUS-001", "api-design", "high", "component",
        "When returning responses from API endpoints.",
        "Response status codes match the outcome: 201 for created, 204 for no-content, 400 for client error, 401 unauth, 403 forbidden, 404 not found, 409 conflict, 422 validation, 5xx for server errors. Returning 200 for failures or 500 for validation is a violation.",
        "```python\nreturn {'error': 'not found'}, 200\n```",
        "```python\nreturn {'error': 'not found'}, 404\n```",
        "Code review.",
        "Status codes are the integration contract for clients, monitors, and load balancers. Mismatched codes break retries, alerts, and circuit breakers.",
        "10"),
    _rule("API-STATUS-002", "api-design", "medium", "component",
        "When deciding the status code for a handled error.",
        "5xx codes are never caused by invalid user input. Bad input produces 4xx (typically 400 or 422). 5xx is reserved for server-side faults the user could not have caused (DB down, dependency failure, unhandled exception).",
        "```python\nif not is_valid(payload):\n    return error('invalid'), 500  # 4xx-class problem, but tagged as server error\n```",
        "```python\nif not is_valid(payload):\n    return error('invalid'), 422\n```",
        "Code review. Monitoring should track 5xx separately from 4xx.",
        "5xx tagging triggers paging and dashboard alerts. Misclassifying 4xx as 5xx floods the incident channel with non-incidents.",
        "10"),
    _rule("API-VERSION-001", "api-design", "medium", "component",
        "When designing an API that may change over time.",
        "API versioning strategy is defined and enforced: URL path (`/v1/`, `/v2/`), header (`Accept: application/vnd.api.v2+json`), or query param. Mixing strategies or omitting versioning is a violation; a documented choice is consistently applied.",
        "```python\n# /api/users returns one shape today, another after a refactor; no version mechanism.\n```",
        "```python\n# /api/v1/users frozen; /api/v2/users for new shape.\n```",
        "Code review.",
        "Versioning lets the API evolve without breaking existing clients. Unversioned APIs make every change a coordinated client upgrade.",
        "10"),
    _rule("API-PAGINATION-001", "api-design", "high", "component",
        "When implementing list endpoints.",
        "List endpoints are paginated with a consistent scheme across the API: cursor-based (preferred for large/changing sets) or offset-based with total count. The pagination metadata (next, prev, total) is included in the response envelope.",
        "```python\n@app.get('/orders')\ndef list_orders():\n    return Order.query.all()  # unbounded\n```",
        "```python\n@app.get('/orders')\ndef list_orders(cursor: str | None = None, limit: int = 25):\n    items, next_cursor = paginate(Order.query, cursor, limit)\n    return {'items': items, 'next_cursor': next_cursor}\n```",
        "Code review.",
        "Pagination contains the API's worst-case response size. Consistent schemes let one client library work across every endpoint.",
        "10"),
    _rule("API-PAGINATION-002", "api-design", "medium", "component",
        "When parameterizing page-size on list endpoints.",
        "Default page size is small (10-25). Maximum page size is enforced server-side. Clients cannot bypass the limit by passing a larger `per_page`.",
        "```python\nper_page = int(request.args.get('per_page', 100))  # client can pass 1000000\n```",
        "```python\nper_page = min(int(request.args.get('per_page', 25)), 200)\n```",
        "Code review.",
        "Server-side caps prevent a single request from exhausting capacity. The default keeps responses fast for the common case.",
        "10"),
    _rule("API-ERROR-001", "api-design", "high", "component",
        "When returning error responses from API endpoints.",
        "Error responses follow a consistent schema: error code (machine-readable), message (human-readable), and field-level details where applicable. The schema is documented and applied across every endpoint.",
        "```python\n# Some endpoints return 'error': 'msg'; others return 'message': 'msg'; others return a string body.\n```",
        "```python\nclass ErrorResponse(BaseModel):\n    error: str            # machine-readable code\n    message: str          # human-readable description\n    details: list[FieldError] | None = None\n# All handlers return ErrorResponse on failure.\n```",
        "Code review. Pydantic-based response models enforce the shape.",
        "Consistent error schemas let one client error-handler work everywhere. Inconsistent schemas force per-endpoint parsing.",
        "10"),
    _rule("API-ERROR-002", "api-design", "medium", "component",
        "When writing error messages returned to API consumers.",
        "Error messages are actionable: they tell the caller what to fix, not just what failed. 'Invalid input' is a violation; 'Field `email` must be a valid email address' is the structure.",
        "```python\nreturn {'error': 'Bad request'}, 400\n```",
        "```python\nreturn {'error': 'INVALID_FIELD', 'message': 'Field `quantity` must be a positive integer; received -5'}, 400\n```",
        "Code review.",
        "Actionable errors halve the time-to-fix for integration partners. Bare messages force them to grep the source.",
        "10"),
    _rule("API-CONTRACT-001", "api-design", "high", "component",
        "When designing or modifying an API endpoint.",
        "API request/response schemas are documented via OpenAPI, JSON Schema, GraphQL SDL, or framework-native equivalent. The documentation is generated from the source of truth (Pydantic models, TypeScript types, etc.), not hand-written.",
        "```\n# API doc is a wiki page maintained separately from code; drifts immediately.\n```",
        "```\n# FastAPI generates /docs from Pydantic models. Spec is always in sync.\n```",
        "CI gate: generated spec is committed; CI verifies it matches code.",
        "Hand-written docs drift. Generated docs stay in sync because they are the code.",
        "10"),
    _rule("API-BREAKING-001", "api-design", "high", "component",
        "When modifying an existing API endpoint or schema.",
        "Breaking changes (removed field, renamed field, changed type, removed endpoint, narrowed accepted input) are versioned. Silent contract changes are violations: the old version stays usable until clients migrate.",
        "```\n# /v1/users used to return {'name': '...'}; today returns {'first_name', 'last_name'}; clients break silently.\n```",
        "```\n# /v1/users still returns {'name'} (computed from first/last);\n# /v2/users returns {'first_name', 'last_name'}.\n# v1 deprecated; sunset date communicated.\n```",
        "Code review. API diff tools (openapi-diff) detect breaking changes in CI.",
        "Silent breakage is invisible to the team that ships and disastrous to the team that consumes. Versioning makes the contract visible.",
        "10"),
    _rule("API-IDEMPOTENT-001", "api-design", "medium", "component",
        "When implementing PUT and DELETE endpoints.",
        "PUT and DELETE are idempotent: calling the same endpoint twice produces the same final state. PUT replaces; DELETE removes (deleting an already-deleted resource is not an error). Repeated calls do not produce duplicate side effects.",
        "```python\n@app.delete('/users/<id>')\ndef delete_user(id):\n    user = User.query.get_or_404(id)  # 404 on second call -> not idempotent\n    user.delete()\n    return '', 204\n```",
        "```python\n@app.delete('/users/<id>')\ndef delete_user(id):\n    user = User.query.get(id)\n    if user:\n        user.delete()\n    return '', 204  # 204 whether or not the user existed\n```",
        "Code review.",
        "Network retries are universal. Idempotent PUT/DELETE makes retries safe; non-idempotent versions risk duplicate-state bugs.",
        "10"),
]


# ============================================================================
# 12. Documentation (8 rules; 1 rename ARCH-TYPE-001 -> DOC-TYPE-001)
# ============================================================================
DOC_RULES = [
    _rule("DOC-API-001", "documentation", "high", "component",
        "When adding or modifying a public API endpoint.",
        "Public API endpoints have request/response documentation that is updated with each change. The documentation source lives alongside the code (OpenAPI generated from Pydantic, GraphQL SDL, framework decorators) and ships with every release.",
        "```\n# /api/orders was changed last quarter; the README still describes the old shape.\n```",
        "```\n# /api/orders has FastAPI response_model + tags; /docs reflects the change automatically.\n```",
        "CI gate: spec generation runs on every PR; diffs are visible.",
        "Drifting API docs erode trust in the documentation overall. Generated docs solve this by construction.",
        "12"),
    _rule("DOC-README-001", "documentation", "medium", "component",
        "When opening a repository for the first time as a new developer.",
        "The repository README includes setup instructions that work on a clean machine: prerequisites, installation, environment setup, how to run tests, how to start the dev server. A new developer can be productive without tribal knowledge.",
        "```\n# README contains 'see Confluence' and a list of acronyms.\n```",
        "```\n# README:\n# Prerequisites: Python 3.12, Node 20, Docker.\n# Setup: pip install -r requirements.txt; cp .env.example .env\n# Test: pytest\n# Run: python -m app\n```",
        "Code review on the README. Onboarding checklist verifies the README works.",
        "A working README is the cheapest onboarding investment; tribal knowledge is the most expensive.",
        "12"),
    _rule("DOC-ARCH-001", "documentation", "medium", "component",
        "When making a non-trivial architectural decision (choice of database, framework, design pattern, integration approach).",
        "Architecture decisions are recorded in ADRs (Architecture Decision Records) or an equivalent decision log. The ADR documents the context, decision, alternatives considered, and trade-offs.",
        "```\n# 'We chose Postgres' lives in someone's head; the next team rediscovers the same trade-offs.\n```",
        "```\n# docs/adrs/ADR-0017-database-choice.md captures the context (read-heavy, ACID needs),\n# the choice (Postgres over MySQL), the alternatives, and the trade-offs accepted.\n```",
        "Code review. Repository structure includes an ADR directory.",
        "Undocumented decisions cost twice: the original deliberation is lost, and the next change repeats the analysis.",
        "12"),
    _rule("DOC-INLINE-001", "documentation", "medium", "component",
        "When implementing non-obvious algorithms: graph traversals, ranking formulas, bit manipulation, cryptography, optimization tricks.",
        "Complex algorithms have inline comments explaining the approach (the why and the how at a level above the syntax). Comments do not restate the code line by line; they explain the strategy and the constraints.",
        "```python\nfor i in range(n):\n    for j in range(i + 1, n):\n        if a[i] + a[j] == target:\n            return (i, j)\n```",
        "```python\n# Two-pointer: O(n) after sort. Move the pointers inward until the\n# sum matches; correctness follows from the sort + monotonicity.\nleft, right = 0, len(a) - 1\nwhile left < right:\n    s = a[left] + a[right]\n    if s == target: return (left, right)\n    elif s < target: left += 1\n    else: right -= 1\n```",
        "Code review.",
        "Algorithmic intent is opaque from syntax alone. A short why-comment saves the next reader the derivation.",
        "12"),
    _rule("DOC-TYPE-001", "documentation", "high", "component",
        "When writing public functions, methods, or exported APIs.",
        "Public functions have type annotations on every parameter and the return value. TypeScript types, Python type hints, Go function types, Rust signatures are the default. Untyped public APIs are violations.",
        "```python\ndef get_user(id):\n    return User.query.get(id)\n```",
        "```python\ndef get_user(id: int) -> User | None:\n    return User.query.get(id)\n```",
        "Type checker (mypy strict, pyright, tsc strict). CI gate.",
        "Types are the most compact, machine-checked documentation available. They catch bugs at edit time and document the contract for free.",
        "12"),
    _rule("DOC-TYPE-002", "documentation", "medium", "component",
        "When declaring function or method signatures.",
        "Return types are explicit. Implicit `Any`, `unknown`, `interface{}`, or unset return types are violations -- the contract is invisible to callers and the type checker.",
        "```typescript\nfunction loadUsers() {\n    return fetch('/api/users').then(r => r.json());\n}\n```",
        "```typescript\nfunction loadUsers(): Promise<User[]> {\n    return fetch('/api/users').then(r => r.json());\n}\n```",
        "Type checker config (mypy `disallow_untyped_defs`, tsc `noImplicitAny`).",
        "Implicit Any defeats the type system. Explicit return types ensure the checker actually validates the contract.",
        "12"),
    _rule("DOC-CONFIG-001", "documentation", "medium", "component",
        "When introducing or modifying configuration options.",
        "Configuration options are documented with their defaults, valid ranges, and effects. A new env var or settings flag is accompanied by an entry in the config docs (or in `.env.example` with comments).",
        "```\n# .env.example: API_TIMEOUT=5\n# No explanation of units, range, or what changes.\n```",
        "```\n# .env.example:\n# API_TIMEOUT=5     # seconds (default 5; range 1-30). Timeout for upstream calls.\n```",
        "Code review.",
        "Undocumented config is dark magic: nobody knows what to tune in an incident, and the wrong value causes silent failure.",
        "12"),
    _rule("DOC-ONBOARD-001", "documentation", "low", "component",
        "When establishing onboarding processes for new developers.",
        "Advisory only. New-developer onboarding (local setup, test run, deploy to staging, common-task walkthroughs) is documented. Enforced at the repository-integrity-check level rather than per-file (the docs may live across multiple files).",
        "```\n# Onboarding is verbal: someone shows you the system over a week.\n```",
        "```\n# docs/onboarding/: getting-started.md, common-tasks.md, deploy.md.\n# Updated by the most recent new hire as the artifact of their onboarding.\n```",
        "Repository-level integrity check (writ validate). Onboarding feedback as the trigger to update.",
        "Documented onboarding compounds: each new hire improves it. Tribal onboarding stays expensive every cycle.",
        "12"),
]


RULES = SCALE_RULES + API_RULES + DOC_RULES


async def main() -> None:
    db = FalkorDBLiteConnection(
        get_falkordb_path(), get_falkordb_graph(),
        get_falkordb_module(), get_redis_bin(),
    )
    try:
        # Rename ARCH-TYPE-001 -> DOC-TYPE-001.
        db._execute_query("MATCH (r:Rule {rule_id: 'ARCH-TYPE-001'}) DETACH DELETE r")
        print("DELETED ARCH-TYPE-001 (absorbed into DOC-TYPE-001)")

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
