"""Phase 3A of the public rulebook expansion: Testing + Error Handling.

Seeds 30 new TEST-* and ERR-* rules into the graph (0 mandatory) and renames
2 legacy TEST-* rules:

  TEST-TDD-001 -> TEST-EXIST-001  (every public function has a test)
  TEST-ISO-001 -> TEST-ISOLATE-001 (no cross-test state)

TEST-INT-001 is retained as a Writ-specific integration-test rule (the
public TEST-EDGE-001 covers error-path testing, which is a different
concept). PHP-TRY-001 / PHP-ERR-001 / PHP-ERR-002 are retained as PHP
language extensions of the language-agnostic ERR-* rules.

Idempotent. Re-runs MERGE existing rules with the same rule_id.

Per the public rulebook source: out-of-the-box-rules.md sections 6, 7.
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
        "mandatory": False,
        "mechanical_enforcement_path": None,
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
# Testing (20 rules; 2 renames preserved)
# ============================================================================
TEST_RULES = [
    _rule("TEST-EXIST-001", "testing", "high", "component",
        "When adding or modifying a public function, method, or class.",
        "Every public function or method has at least one test. New public APIs are not committed without a test covering at least the happy path.",
        "```python\n# orders.py adds a new public method:\ndef cancel_order(order_id): ...\n# No test in tests/test_orders.py.\n```",
        "```python\n# tests/test_orders.py:\ndef test_cancel_order_marks_status():\n    order = make_order(status='paid')\n    cancel_order(order.id)\n    assert reload(order).status == 'cancelled'\n```",
        "Code review. Coverage tools report public-function coverage.",
        "Untested public APIs are unverified APIs: every caller is the first to find the bug. The test is the executable contract.",
        "6"),
    _rule("TEST-EXIST-002", "testing", "high", "component",
        "When adding or modifying an API endpoint (REST, GraphQL, RPC).",
        "Every API endpoint has at least one integration test that exercises it end-to-end (request -> response). Unit tests on the handler function are not a substitute.",
        "```python\n# /api/orders POST added; only the service function is unit-tested.\n```",
        "```python\ndef test_create_order_endpoint(client):\n    resp = client.post('/api/orders', json={...})\n    assert resp.status_code == 201\n    assert resp.json['id']\n```",
        "Code review.",
        "Integration tests catch the bugs that unit tests cannot: middleware ordering, request parsing, response shape, status codes, content negotiation.",
        "6"),
    _rule("TEST-NAME-001", "testing", "medium", "component",
        "When naming a test function.",
        "Test names describe the scenario and the expected outcome. `test_method_name` is insufficient; `test_method_name_returns_X_when_Y` or BDD-style `should_X_when_Y` is the structure.",
        "```python\ndef test_cancel(): ...\ndef test_cancel_2(): ...\n```",
        "```python\ndef test_cancel_marks_status_cancelled_for_paid_orders(): ...\ndef test_cancel_raises_when_order_already_shipped(): ...\n```",
        "Code review.",
        "Failing test names are read in CI output, in incident timelines, in stack traces. Descriptive names diagnose the failure without opening the test file.",
        "6"),
    _rule("TEST-ASSERT-001", "testing", "high", "component",
        "When writing a test function.",
        "Every test has at least one assertion. Tests that exercise code without asserting an outcome are smoke tests at best and false-positive guarantees at worst.",
        "```python\ndef test_create_order():\n    create_order(payload)  # no assert\n```",
        "```python\ndef test_create_order():\n    order = create_order(payload)\n    assert order.id is not None\n    assert order.status == 'pending'\n```",
        "Linter rule (pytest-style assertion check; pylint custom rule).",
        "An assertion-free test silently passes regardless of what the code does. The bug it claims to cover is invisible.",
        "6"),
    _rule("TEST-ASSERT-002", "testing", "medium", "component",
        "When writing test assertions.",
        "Assertions are specific. `assertEqual(actual, 5)` beats `assertTrue(actual == 5)`; `assertGreater(x, y)` beats `assertTrue(x > y)`. Specific assertions produce specific failure messages.",
        "```python\nassert result == expected, 'failed'\n```",
        "```python\nassert result == expected\n# pytest auto-diffs the values on failure; specific matchers (.contains, .matches) give richer messages.\n```",
        "Code review.",
        "Specific assertions print diffs on failure: actual vs expected. Boolean assertions print only 'False is not True', which says nothing.",
        "6"),
    _rule("TEST-ISOLATE-001", "testing", "high", "component",
        "When writing tests that share modules, fixtures, or process-level state.",
        "Tests do not depend on execution order. State is set up per-test and torn down per-test. Cross-test mutable state (module globals modified by one test, read by another) is a violation.",
        "```python\nCACHE = {}\ndef test_first_writes_to_cache():\n    CACHE['key'] = 'value'\ndef test_second_reads_cache():\n    assert CACHE['key'] == 'value'  # depends on test order\n```",
        "```python\ndef test_writes_and_reads_cache():\n    cache = {}\n    cache['key'] = 'value'\n    assert cache['key'] == 'value'\n```",
        "Test framework config (pytest's randomize order plugin catches this). Code review.",
        "Order-dependent tests pass in CI and fail in parallel runs (or vice versa). The flake is structural and the fix is per-test isolation.",
        "6"),
    _rule("TEST-ISOLATE-002", "testing", "high", "component",
        "When writing tests that exercise code with external dependencies (HTTP APIs, third-party services, payment gateways).",
        "Tests do not make real network calls. External dependencies are mocked, stubbed, or replaced with a local fake (VCR, MSW, responses, requests-mock). Tests do not hit a real Stripe sandbox, Slack webhook, or third-party API.",
        "```python\ndef test_charge_card():\n    response = stripe.Charge.create(amount=1000)  # real API call\n    assert response.status == 'succeeded'\n```",
        "```python\ndef test_charge_card(stripe_mock):\n    stripe_mock.expect_charge(amount=1000).returns(succeeded_response)\n    result = payment_service.charge(amount=1000)\n    assert result.status == 'succeeded'\n```",
        "Code review. Network-blocking pytest fixtures (pytest-socket).",
        "Tests that hit real services are slow, flaky, and side-effect-laden. Mocking is the structural defense.",
        "6"),
    _rule("TEST-ISOLATE-003", "testing", "medium", "component",
        "When writing tests that read or write a database.",
        "Test database state is reset between tests: transaction rollback after each test, fixture reload, or a fresh ephemeral database. Tests do not leak rows that affect other tests.",
        "```python\ndef test_create_user_first():\n    User.create(email='alice@example.com')\ndef test_create_user_again():\n    User.create(email='alice@example.com')  # IntegrityError from prior test\n```",
        "```python\n@pytest.fixture\ndef db():\n    with engine.begin() as conn:\n        yield conn\n        conn.rollback()\n```",
        "Test framework config. Pytest fixtures with transactional scope.",
        "Leaked state between tests is the canonical source of order-dependent flakiness. Per-test isolation removes the entire class of bug.",
        "6"),
    _rule("TEST-FIXTURE-001", "testing", "medium", "component",
        "When writing test setup code.",
        "Test fixtures or factories are used for object setup. Constructing the same domain object inline across many tests is a violation; factory functions (factory_boy, FactoryBot, pytest fixtures) own the construction logic.",
        "```python\ndef test_a():\n    user = User(name='Alice', email='alice@example.com', age=30, ...)  # 20 fields\n    ...\ndef test_b():\n    user = User(name='Bob', email='bob@example.com', age=25, ...)\n```",
        "```python\n@pytest.fixture\ndef user_factory():\n    def make(**overrides):\n        defaults = {'name': 'Alice', 'email': 'alice@example.com', ...}\n        return User(**{**defaults, **overrides})\n    return make\n\ndef test_a(user_factory):\n    user = user_factory()\ndef test_b(user_factory):\n    user = user_factory(name='Bob')\n```",
        "Code review.",
        "Inline-constructed objects drift across tests; one new required field updates twenty tests. Factories centralize the construction.",
        "6"),
    _rule("TEST-FIXTURE-002", "testing", "medium", "component",
        "When writing test setup code.",
        "Fixtures are minimal: each test sets up only what it actually needs. Kitchen-sink setup that creates 10 related objects when the test only uses 2 is a violation. The test reads as 'given these inputs, expect this outcome' without noise.",
        "```python\ndef test_cancel_order():\n    customer = create_customer()\n    addresses = [create_address(customer) for _ in range(3)]\n    payment_methods = [create_payment_method(customer) for _ in range(2)]\n    order = create_order(customer)\n    cancel_order(order.id)\n    assert order.status == 'cancelled'\n```",
        "```python\ndef test_cancel_order():\n    order = create_order(status='pending')\n    cancel_order(order.id)\n    assert reload(order).status == 'cancelled'\n```",
        "Code review.",
        "Bloated setup obscures intent and slows the suite. Minimal fixtures keep the test legible and fast.",
        "6"),
    _rule("TEST-EDGE-001", "testing", "high", "component",
        "When testing a public function.",
        "Error paths are tested alongside the happy path: invalid input, missing data, permission denied, timeout, downstream failure. The test suite proves the code handles failure as well as success.",
        "```python\ndef test_charge_card_success(): ...\n# No test for declined-card, network-failure, or invalid-amount.\n```",
        "```python\ndef test_charge_card_success(): ...\ndef test_charge_card_raises_on_decline(): ...\ndef test_charge_card_retries_on_transient_network_error(): ...\ndef test_charge_card_rejects_negative_amount(): ...\n```",
        "Code review. Coverage tools that report branch coverage.",
        "Happy-path-only test suites prove the code works when nothing goes wrong, which is the easiest case. Error paths are where most production bugs live.",
        "6"),
    _rule("TEST-EDGE-002", "testing", "medium", "component",
        "When testing a function that operates on collections, numeric values, or string inputs.",
        "Boundary values are tested: empty collection, zero, one, max int, max length, empty string, None/null. Off-by-one bugs and overflow bugs live at the boundaries.",
        "```python\ndef test_sum_items():\n    assert sum_items([1, 2, 3]) == 6\n# No empty-list, no overflow case.\n```",
        "```python\ndef test_sum_items_empty(): assert sum_items([]) == 0\ndef test_sum_items_single(): assert sum_items([5]) == 5\ndef test_sum_items_large(): assert sum_items([10**9] * 100) == 10**11\n```",
        "Code review.",
        "Boundary bugs are the canonical source of off-by-one errors and overflow surprises. Explicit boundary tests are the structural defense.",
        "6"),
    _rule("TEST-EDGE-003", "testing", "medium", "component",
        "When implementing concurrent code (locks, async coroutines, shared state, queues).",
        "Concurrent access paths are tested where applicable: race conditions, lock contention, deadlocks. The test suite includes scenarios that exercise multiple parallel callers.",
        "```python\n# concurrent_writes(file) tested only single-caller.\n```",
        "```python\nasync def test_concurrent_writes_serialize():\n    await asyncio.gather(*[concurrent_writes(file, i) for i in range(50)])\n    assert correctly_ordered(file.read())\n```",
        "Code review.",
        "Concurrency bugs only surface under contention. A single-threaded test of concurrent code proves nothing about correctness under load.",
        "6"),
    _rule("TEST-MOCK-001", "testing", "medium", "component",
        "When using mocks in tests.",
        "Mocks verify behavior: that the mock was called with specific arguments, the right number of times, in the right order. Mocks that exist purely to suppress a dependency without assertions on the call are weak tests.",
        "```python\ndef test_send_welcome():\n    send_welcome(user)\n    # mailer is mocked but never inspected\n```",
        "```python\ndef test_send_welcome(mailer_mock):\n    send_welcome(user)\n    mailer_mock.send.assert_called_once_with(\n        to=user.email, template='welcome', context={'name': user.name},\n    )\n```",
        "Code review.",
        "A mock without behavior assertions only proves 'no exception thrown'. Behavior assertions prove the integration with the mocked collaborator.",
        "6"),
    _rule("TEST-MOCK-002", "testing", "medium", "component",
        "When stubbing return values for mocked dependencies.",
        "Mock return values match the actual API/service response shape. A mock that returns `{'ok': True}` when the real service returns `{'data': {...}, 'status': 'success'}` produces tests that pass while real integration fails.",
        "```python\nstripe_mock.charge.return_value = True\n```",
        "```python\nstripe_mock.charge.return_value = StripeChargeResponse(\n    id='ch_test', status='succeeded', amount=1000, currency='usd',\n    customer='cus_test', metadata={},\n)\n```",
        "Code review. Contract tests verify mock shapes against real responses.",
        "Drift between mock and reality lets tests pass while production breaks. Realistic mocks keep the gap closed.",
        "6"),
    _rule("TEST-COVERAGE-001", "testing", "medium", "component",
        "When measuring test coverage.",
        "Critical business logic paths have at least 80% branch coverage. Coverage targets apply where the code's correctness matters (billing, auth, data integrity); UI and trivial accessors are exempted.",
        "```\n# pricing module: 23% line coverage; no branch coverage tracking.\n```",
        "```\n# pricing module: 92% line coverage, 87% branch coverage.\n# Coverage report is a CI artifact; threshold is enforced.\n```",
        "Coverage tool (pytest-cov, jest --coverage, istanbul, JaCoCo) with CI gate.",
        "Coverage targets create a baseline that prevents tests from being silently abandoned. 80% branch is enough to catch most regression; chasing 100% wastes effort on trivial code.",
        "6"),
    _rule("TEST-PERF-001", "testing", "low", "component",
        "When implementing performance-sensitive code (hot paths, query pipelines, retrieval, ranking, real-time loops).",
        "Performance-sensitive paths have benchmark tests with a documented baseline. The baseline is checked in CI (or nightly) and regressions exceeding a threshold fail the build.",
        "```\n# Latency-critical retrieval pipeline has no perf assertion.\n```",
        "```python\n@pytest.mark.benchmark\ndef test_query_latency(benchmark, pipeline):\n    result = benchmark(pipeline.query, 'sql injection')\n    assert benchmark.stats.median < 0.050  # 50ms baseline\n```",
        "Benchmark framework (pytest-benchmark, criterion, JMH).",
        "Performance regressions slip in silently as features land. Benchmarks turn 'feels slow' into a measurable, gateable signal.",
        "6"),
    _rule("TEST-REGRESSION-001", "testing", "high", "component",
        "When fixing a bug.",
        "Every bug fix is accompanied by a regression test that reproduces the bug. The test fails before the fix and passes after. The bug ticket / commit message references the test.",
        "```\n# Commit: 'fix: null pointer in /api/orders'\n# No accompanying test.\n```",
        "```\n# Commit:\n# fix: null pointer in /api/orders when shipping address missing\n# test_create_order_handles_missing_shipping_address verifies fix\n```",
        "Code review. Bug-tracker template requires a 'test added' field.",
        "Bug fixes without regression tests guarantee the bug returns. The test is the structural defense against re-introduction.",
        "6"),
    _rule("TEST-SNAPSHOT-001", "testing", "low", "component",
        "When using snapshot testing (Jest snapshots, React Testing Library snapshots, Storybook visual snapshots).",
        "Snapshot updates are explicitly reviewed; blind snapshot regeneration (-u flag in commits without review) is forbidden. The PR description explains why the snapshot changed.",
        "```\n# CI runs `jest -u` automatically and commits.\n```",
        "```\n# Developer runs jest -u locally, inspects diff, includes it in the PR.\n# Reviewer specifically reviews the snapshot diff.\n```",
        "Pre-commit hook. PR template requires snapshot diff acknowledgment.",
        "Blind snapshot updates erode the value of the test: it becomes a record of what the code does, not a check that it does the right thing.",
        "6"),
    _rule("TEST-CI-001", "testing", "medium", "component",
        "When merging code.",
        "All tests pass in CI before merge. 'Known failing' tests are not left in the suite; flaky tests are quarantined with a tracked ticket and fixed or removed, not silently skipped.",
        "```\n# 3 tests marked @pytest.mark.skip('flaky') with no ticket reference.\n```",
        "```\n# 3 tests removed and tracked as PR-1234 to repair or replace.\n# Skips that remain reference active tickets and have an owner.\n```",
        "CI gate. Code review.",
        "A green-with-skips suite is a yellow signal that gets ignored. Either the test is meaningful (fix it) or it is not (remove it).",
        "6"),
]


# ============================================================================
# Error Handling & Resilience (12 rules)
# ============================================================================
ERR_RULES = [
    _rule("ERR-HANDLE-001", "code-quality", "high", "component",
        "When making any call to an external system: HTTP, database, file I/O, message queue, third-party SDK, IPC.",
        "Every external call is wrapped in error handling with an explicit timeout. Bare network or file calls without try/except + timeout are violations. The handler logs, maps to a domain error, or retries deliberately.",
        "```python\nresponse = requests.get('https://api.example.com/data')  # no timeout, no handling\n```",
        "```python\ntry:\n    response = requests.get('https://api.example.com/data', timeout=5.0)\n    response.raise_for_status()\nexcept (requests.Timeout, requests.ConnectionError) as e:\n    logger.warning('upstream failure', extra={'service': 'example'})\n    raise UpstreamUnavailable('example') from e\n```",
        "Code review.",
        "Unhandled external failures propagate as raw library exceptions to callers that cannot recover or even identify them. Wrapping is the structural defense.",
        "7"),
    _rule("ERR-HANDLE-002", "code-quality", "high", "component",
        "When re-raising or wrapping caught exceptions.",
        "Errors propagate with context: the wrapping exception preserves the original via `raise ... from e` (Python), `cause:` (JS), `Throwable.initCause` (Java), `wrap` (Go errors.Is/As). Bare re-raise that loses the chain is a violation.",
        "```python\ntry:\n    pay(order)\nexcept StripeError:\n    raise PaymentFailed()  # original cause lost\n```",
        "```python\ntry:\n    pay(order)\nexcept StripeError as e:\n    raise PaymentFailed(order.id) from e\n```",
        "Code review.",
        "Unchained exceptions hide the root cause behind a generic wrapper. The original stack trace is the most valuable artifact in an incident.",
        "7"),
    _rule("ERR-HANDLE-003", "code-quality", "medium", "component",
        "When constructing error messages returned to end users.",
        "User-facing error messages are helpful and human-readable but never expose internal details: file paths, stack traces, SQL fragments, library names, internal IDs. A correlation ID lets support map the user-facing message to the internal log.",
        "```python\nreturn {'error': str(traceback.format_exc())}, 500\n```",
        "```python\nreturn {'error': 'We could not process your request. Reference: ABCD-1234', 'reference': correlation_id}, 500\n```",
        "Code review.",
        "Internal-detail leaks aid reconnaissance and confuse legitimate users. A clear public message + an internal correlation ID balances both audiences.",
        "7"),
    _rule("ERR-RETRY-001", "code-quality", "high", "component",
        "When implementing retry logic for external calls or transient failures.",
        "Retries use exponential backoff with jitter, not fixed intervals. Backoff base is at least 100ms; jitter is random within a window to avoid thundering herd; growth multiplier is 2-3x.",
        "```python\nfor attempt in range(5):\n    try:\n        return call()\n    except TransientError:\n        time.sleep(1)  # fixed interval; thundering herd at scale\n```",
        "```python\nfor attempt in range(5):\n    try:\n        return call()\n    except TransientError:\n        delay = min(30, (2 ** attempt) * 0.1) * (0.5 + random.random())\n        time.sleep(delay)\n```",
        "Code review. Retry libraries (tenacity, retry, polly) implement this correctly.",
        "Fixed-interval retries synchronize and amplify upstream failures. Exponential backoff with jitter spreads the retry load and gives upstream room to recover.",
        "7"),
    _rule("ERR-RETRY-002", "code-quality", "medium", "component",
        "When implementing retry logic.",
        "Retry attempts are capped (typically 3-5). Infinite retry loops are forbidden. After the cap, the call fails through to the next layer of error handling (fallback, circuit break, error response).",
        "```python\nwhile True:\n    try: return call()\n    except TransientError: continue\n```",
        "```python\nfor attempt in range(5):\n    try: return call()\n    except TransientError: continue\nraise ServiceUnavailable()\n```",
        "Code review.",
        "Unbounded retries hang the request, consume the worker, and never surface the failure to the caller.",
        "7"),
    _rule("ERR-CIRCUIT-001", "code-quality", "medium", "component",
        "When an external dependency fails repeatedly.",
        "Repeated failures to an external service trigger a circuit breaker: the breaker opens, subsequent calls fail fast with a fallback or error, the breaker half-opens after a cooldown to probe recovery. Libraries: resilience4j, polly, py-breaker, opossum.",
        "```python\n# Every request continues to call the failing upstream, exhausting threads.\n```",
        "```python\n@breaker(failure_threshold=5, recovery_timeout=30)\ndef call_upstream(): ...\n```",
        "Code review. Breaker libraries with metrics.",
        "Without a breaker, every request waits the timeout before failing; the failing service drags down everything that calls it. The breaker turns a slow failure into a fast failure.",
        "7"),
    _rule("ERR-FALLBACK-001", "code-quality", "medium", "component",
        "When implementing critical paths that depend on optional or recoverable inputs (cache, secondary service, personalization).",
        "Critical paths have defined fallback behavior, documented in code or comments. The fallback path is tested. 'If the cache is down, use the database' is explicit, not implicit.",
        "```python\ndata = cache.get(key) or db.fetch(key)  # what if both fail?\n```",
        "```python\ntry:\n    data = cache.get(key)\nexcept CacheError:\n    logger.warning('cache miss; using DB fallback')\n    data = db.fetch(key)\n# If DB also fails, the error propagates to the caller.\n```",
        "Code review.",
        "Fallback decisions are part of the design, not an emergent property. Documented fallback paths preserve the critical workflow under partial outage.",
        "7"),
    _rule("ERR-TIMEOUT-001", "code-quality", "high", "component",
        "When making any external call (HTTP, DB, RPC, lock acquisition, queue receive).",
        "All external calls have explicit timeouts. Unbounded waits are forbidden. The library default is not acceptable as documentation: the timeout is passed at the call site or set via shared client config.",
        "```python\nresponse = requests.get('https://api.example.com/data')  # no timeout\n```",
        "```python\nresponse = requests.get('https://api.example.com/data', timeout=5.0)\n```",
        "Code review. Linter rule (ruff S113 for requests without timeout).",
        "Bare external calls inherit library defaults that are often 'no timeout' or 'minutes'. One slow upstream stalls the whole worker pool.",
        "7"),
    _rule("ERR-TIMEOUT-002", "code-quality", "medium", "component",
        "When configuring timeout values for external calls.",
        "Timeout values are configurable (env var, config file, settings module). Hardcoded timeouts spread across the codebase are violations; one config controls them by environment and downstream-service.",
        "```python\nresponse = requests.get(url, timeout=5)  # hardcoded everywhere\n```",
        "```python\nresponse = requests.get(url, timeout=settings.UPSTREAM_TIMEOUT_SECONDS)\n```",
        "Code review.",
        "Tuning timeouts during an incident is a 1-line config change when timeouts are configurable. Otherwise it is a code change, a deploy, and a delay.",
        "7"),
    _rule("ERR-GRACEFUL-001", "code-quality", "high", "component",
        "When implementing long-running processes (web servers, workers, daemons, CLI tools that accept signals).",
        "The application handles SIGTERM and SIGINT gracefully: stops accepting new work, drains in-flight requests within a deadline, flushes buffers, exits cleanly. Hard-kill on signal is a violation.",
        "```python\n# default behavior: SIGTERM kills the process mid-request.\n```",
        "```python\nshutdown_event = threading.Event()\nsignal.signal(signal.SIGTERM, lambda *a: shutdown_event.set())\nwhile not shutdown_event.is_set():\n    serve_one_request(timeout=1.0)\ndrain_in_flight(deadline=30)\nlogger.info('shut down cleanly')\n```",
        "Code review.",
        "Graceful shutdown preserves in-flight requests and avoids dropped writes on deployment. Hard-kill turns every deploy into a small outage.",
        "7"),
    _rule("ERR-GRACEFUL-002", "code-quality", "medium", "component",
        "When implementing background jobs, queue workers, or scheduled tasks.",
        "Workers have shutdown hooks that complete in-progress work or requeue it. A worker killed mid-job leaves either a half-done state or a re-runnable job; never a silently dropped job.",
        "```python\n# Worker yanked mid-job; the message is gone (auto-acked at receive).\n```",
        "```python\n# Worker acks message only after job completes. SIGTERM triggers\n# wait_for_current_job_to_finish(timeout) then exit.\n```",
        "Code review.",
        "Dropped jobs on shutdown produce silent data inconsistency. Acknowledgement-after-complete plus shutdown hooks preserve the at-least-once contract.",
        "7"),
    _rule("ERR-VALIDATION-001", "code-quality", "high", "component",
        "When returning validation errors from an API.",
        "Validation errors are returned as structured responses with field-level errors and error codes. A flat string like 'Validation failed' is a violation; the response identifies which field failed, why, and a machine-readable code.",
        "```python\nreturn {'error': 'Validation failed'}, 400\n```",
        "```python\nreturn {'errors': [\n    {'field': 'email', 'code': 'INVALID_FORMAT', 'message': 'Not a valid email'},\n    {'field': 'age', 'code': 'OUT_OF_RANGE', 'message': 'Must be 0-150'},\n]}, 400\n```",
        "Code review. Pydantic + FastAPI produces this shape automatically.",
        "Structured validation errors let UIs highlight the bad field and let integrations handle errors programmatically. A bare string forces every consumer to parse.",
        "7"),
]


RULES = TEST_RULES + ERR_RULES


async def main() -> None:
    db = FalkorDBLiteConnection(
        get_falkordb_path(), get_falkordb_graph(),
        get_falkordb_module(), get_redis_bin(),
    )
    try:
        renames = [
            ("TEST-TDD-001", "TEST-EXIST-001"),
            ("TEST-ISO-001", "TEST-ISOLATE-001"),
        ]
        for old, new in renames:
            db._execute_query("MATCH (r:Rule {rule_id: $old}) DETACH DELETE r", old=old)
            print(f"DELETED {old:20s} (absorbed into {new})")

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
                print(f"UPDATED {rule['rule_id']:30s} {rule['severity']}")
            else:
                created += 1
                print(f"CREATED {rule['rule_id']:30s} {rule['severity']}")

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
