# Tech Debt

## Active

### TD-01 · Test loop-safety couples to db.py staying synchronous
**Status:** OPEN
**Phase:** Revisit if/when `writ/graph/db.py` moves to async-redis or any async I/O.
**Risk if triggered early:** A db.py async refactor silently breaks the entire test suite with "attached to a different loop" / "got Future attached to a different loop" errors across modules — failures look unrelated to the refactor.
**What:** The Phase 3 session-scoped test DB fixture (one `FalkorDBLiteConnection` shared across the suite) is event-loop-safe ONLY because `db.py`'s `async def` methods wrap a SYNCHRONOUS `_execute_query` (`writ/graph/db.py:162`) — the connection never binds to an asyncio event loop, so it can be awaited from session-, module-, and function-scoped consumers interchangeably. This is invisible coupling between a production-code implementation choice and test-suite correctness.
**Why deferred:** db.py is sync today and there is no reason to make it async (no I/O in the hot path per PERF-IO-001). Recording the landmine rather than pre-emptively guarding it.
**Source:** docs/AI_artifacts/3_research/phase3-test-suite-green.md (A8), docs/AI_artifacts/4_plans/phase3-test-suite-green.md

## Archive

_(none)_
