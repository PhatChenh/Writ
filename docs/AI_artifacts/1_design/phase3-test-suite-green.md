# Phase 3 — Test Suite Green — Design

_Tier: MEDIUM. Origin: design. Behavior-inventory prefix: **P3-TEST** (entries P3-TEST-01..07 in `behavior_inventory.yaml`, granularity: outcome)._
_Source of locked requirements: `docs/AI_artifacts/0_draft/phase3-test-suite-green.md` (grill sign-off 2026-06-20)._

---

## In plain terms

Phase 1 and 2 swapped the database engine under Writ from Neo4j (a Docker container) to FalkorDBLite (an embedded, file-based engine). The production code already runs on the new engine. But the **test suite was left behind**: ~28 of the test files still try to connect to the old Neo4j, import functions that no longer exist, and start a Docker container that was deleted. So the tests can't even load, let alone pass.

This phase is plumbing, not new behavior. We are NOT changing what any test checks. We are repointing every test's database connection at the new engine and deleting the dead Neo4j wiring. The core design question is *how* to share one real test database across all the tests safely, and *how* to migrate ~28 files in an order where each step can be verified before the next — so a mistake is caught early, not at the end.

One surprise the draft did not flag: a handful of tests assert that the bootstrap script *starts Docker/Neo4j* and that `docker-compose.yml` *exists* — but Phase 2 deliberately deleted exactly those things. Those tests cannot pass as written. That collision is the main open question below.

---

## Cast of characters

| Name | Plain-English role |
|---|---|
| `FalkorDBLiteConnection` | The new database client. Starts a `redis-server` subprocess + loads a graph module, talks over a Unix socket. |
| `_execute_query` | The one method that actually runs a query and returns rows as a list of dicts. Synchronous (no `await`). |
| `clear_all` | Wipes every node/edge from the graph. The between-test reset button. |
| `get_falkordb_path` / `_graph` / `_module` / `get_redis_bin` | The four real config getters that replaced the deleted `get_neo4j_*` getters. |
| `IntegrityChecker` | Runs corpus health checks (conflicts, orphans, stale, redundancy) against the graph. |
| `conftest.py` | pytest's shared-setup file. Where session fixtures and the end-of-suite restoration hook live. |
| `pytest_sessionfinish` | End-of-suite hook in conftest that re-loads the rule corpus into the production graph. |
| `db()` fixture | The per-test handle to a clean database. Currently duplicated across ~10 files; this phase consolidates it. |

---

## Guardrail Checklist

`/guardrail-check Review` was run for this change (domains touched: **DB Integrity**, **Testing Patterns**, **Architecture**). Result: **`docs/CONSTRAINTS.md` does not exist** in this repo — there are no structured Constraint Cards to filter against. The skill's Review mode requires that file and stops without it.

The de-facto constraints for this phase therefore come from `CLAUDE.md` ("Critical Rules") and the locked draft, restated here as the checklist each option is scored against:

- **G1 · Freeze `writ/retrieval/`** — do not modify retrieval pipeline logic during the DB swap.
- **G2 · No production code change beyond a constructor/import swap** — tests adapt; behavior does not.
- **G3 · 282 tests are the correctness contract** — same assertions, same logic. No new tests, no changed assertions.
- **G4 · Never `await _execute_query`** — it is synchronous (`db.py:162`); only the public `async` methods are awaited.
- **G5 · Throwaway temp DB only** — tests never touch or lock `.writ/graph.db` (D1+D2).
- **G6 · Apple-Silicon-only** — `get_redis_bin` raises on x86_64 by design (D9); the config test must assert that path, not skip it.

> Recommendation flagged in Open Questions: this repo has no `docs/CONSTRAINTS.md`/`TECH_DEBT.md`/`OPEN_QUESTIONS.md`. Consider scaffolding them so future phases get real guardrail filtering. Not done here (out of Phase 3 scope).

---

## Landmine verification (against current code, 2026-06-20)

Each draft landmine was re-checked against the live tree, not taken on faith.

| # | Status | What I found |
|---|---|---|
| L1 | **Confirmed** | `get_neo4j_*` / `DEFAULT_NEO4J_*` are gone. Real getters are `get_falkordb_path` (`config.py:49`), `get_falkordb_graph` (`:55`), `get_falkordb_module` (`:61`), `get_redis_bin` (`:67`, with the x86_64 `RuntimeError` at `:85`). Codegraph confirms **none have covering tests**. |
| L2 | **Confirmed + sharpened** | `test_post_suite_neo4j_restoration._count()` (`:34-55`) imports `get_neo4j_*`/`Neo4jConnection` inside a `try`, and on `ImportError` calls `pytest.skip("neo4j driver not installed")` (`:45`). It is **silently skipping today**. Un-skipping (D4) will run it live for the first time — see "Expected fallout" below. |
| L3 | **Confirmed** | Zero `from neo4j` / `import neo4j`. Every reference is `Neo4jConnection` (deleted from `writ.graph.db`) + module-level `NEO4J_URI/USER/PASSWORD = get_neo4j_*()` constants. |
| L4 | **Confirmed — this is the real work** | ~10 files each define their **own** `db()` fixture that builds `Neo4jConnection(NEO4J_URI,...)` + `clear_all()`, function-scoped. Two shapes: top-level fixtures (`test_infrastructure:25`, `test_authoring:27`, `test_ingest:290`, `test_graph_proximity:38`, `test_integrity:54`, `test_retrieval:48`) and class-nested fixtures (`test_compression:231`, `test_export:349`). Plus inline construction in `test_session` (`:124,192`), `test_embeddings:431`, `test_retrieval:248,258`. Consolidation, not 28 isolated edits. |
| L5 | **Confirmed** | `test_authority.py` and `test_analysis.py` have **zero** neo4j references (grep clean). They mock the `GraphConnection` protocol via `AsyncMock()`. Leave untouched. |
| L6 | **Confirmed** | `clear_all` exists (`db.py:479`), runs `MATCH (n) DETACH DELETE n`. Isolation primitive ready. |
| L7 | **Confirmed** | `detect_redundant` (`integrity.py:71`) raises `RuntimeError` without `sentence-transformers` (`:101`). `run_all_checks(skip_redundancy=True)` is the supported opt-out (`:248`). |
| L8 | **Confirmed** | `IntegrityChecker(db)` is single-arg (`integrity.py:22`). Its methods are `async def` but call **sync** `_execute_query` with no inner await. Tests `await` the public methods; never `await _execute_query`. |
| L9 | **Confirmed** | Lockfile = one holder per `db_dir` (`db.py:147` `_acquire_lock`, writes the PID). Serial pytest assumed; `pytest-xdist` would need per-worker temp DBs (not in scope). |

### NEW landmine (draft missed) — L10 · Infra-assertion tests contradict shipped Phase 2

Three test groups assert the **existence of infrastructure Phase 2 deleted**:

- `test_bootstrap.py` — asserts `docker-compose.yml` exists (`:40`), that `bootstrap.sh` contains `docker compose up` (`:131`), waits for Neo4j bolt port `7687` (`:136`), and that a `docker-compose.yml` neo4j service block exists (`:168+`); also `TestEnsureServerMigration` asserts `ensure-server.sh` uses `docker compose` (`:196`).
- `tests/plugin/test_session_start_bootstrap.py` — asserts the session-start script probes Neo4j bolt port `7687` (`:66`).

Verified against disk: `docker-compose.yml` **does not exist**; `bootstrap.sh`, `ensure-server.sh`, and the session-start script contain **zero** docker/neo4j/7687 references (Phase 2 scrubbed them). So these tests are **currently failing or erroring**, and they assert the *opposite* of the shipped product. They cannot pass without changing their assertions — which collides head-on with locked decision G3 ("no changed assertions"). This is escalated as **OQ-1** (the central blocker) rather than silently resolved.

---

## Decision

**Adopt Option A — one session-scoped `FalkorDBLiteConnection` in `conftest.py` on a session temp dir, plus a function-scoped autouse `clear_all` reset, and a single shared `db()` fixture that all live-DB files consume.** Chosen because it pays the ~5-second engine startup **once** instead of ~10× (per-file) or ~40× (per-test), gives every test a guaranteed-clean graph, and is the only shape that lets the ~10 duplicated fixtures collapse into one place — turning "28 isolated edits" into "1 fixture + N import-line deletions."

---

## Implications

- **Every live-DB test will share one real database that lives in a throwaway temp folder.** Nothing the tests do can touch or lock the production graph, so you can run the suite while the server is up.
  - One session-scoped fixture builds `FalkorDBLiteConnection(<session tmp>/graph.db, get_falkordb_graph(), get_falkordb_module(), get_redis_bin())`. The unique temp dir yields a unique `/tmp/writ-<md5>[:12]` socket (`db.py:104-109`), so it never collides with a running `writ serve` (G5, P3-TEST-04).
- **The database is wiped clean before each test, automatically.** Tests don't have to remember to reset; a shared autouse step does it.
  - A function-scoped `autouse=True` fixture calls `await db.clear_all()` (`db.py:479`). This replaces the per-fixture setup+teardown `clear_all()` pairs that the old `db()` fixtures each carried.
- **About ten near-identical `db()` fixtures collapse into one.** Less duplicated code, one place to change connection wiring ever again.
  - The shared `db()` fixture in `conftest.py` yields the session connection. Files that declared their own (`test_infrastructure`, `test_authoring`, `test_ingest`, `test_graph_proximity`, `test_integrity`, `test_compression`, `test_export`, `test_retrieval`) delete their local fixture + `NEO4J_*` constants + the two dead imports. Type hints `db: Neo4jConnection` become `db: FalkorDBLiteConnection`.
- **The two config-test files get rewritten to test the database settings that actually exist.** They currently test deleted Neo4j settings and are skipping entirely, so they protect nothing.
  - `test_config.py` + `test_config_integration.py` re-target `get_falkordb_path/_graph/_module` (default + `writ.toml` override) and `get_redis_bin` (override → PATH → arm64 default → x86_64 `RuntimeError`). The `[neo4j]` TOML fixtures become `[falkordb]`. The `TestRepoWideNoHardcodedCreds` meta-test (`test_config_integration.py:179`) that scans all of `tests/` for the old password literal must be re-pointed or retired — there is no longer a secret credential to scan for (FalkorDBLite has no password). [UNVERIFIED: whether the team wants that meta-test re-aimed at a new invariant or dropped — see OQ-2.]
- **The integrity tests construct the checker with one argument and never await the raw query method.** Matches the real API; mis-awaiting the sync method would raise at runtime.
  - `IntegrityChecker(db)` (single arg, `integrity.py:22`). Tests pass `skip_redundancy=True` to `run_all_checks` **or** the suite installs `.[fallback]`, because `detect_redundant` raises without `sentence-transformers` (L7). Public methods are awaited; `_execute_query` is not (G4/L8).
- **The end-of-suite restoration hook keeps running and stays meaningful — with one caveat.** After tests wipe data around, the hook re-loads the real corpus so the live server works immediately afterward.
  - `pytest_sessionfinish` (`conftest.py:8`) shells out to `writ import-markdown bible/` against the **production** graph (it does not use the test fixture). That is unchanged by a throwaway *test* DB — the hook restores prod, the tests use temp. The restoration **test** (`test_post_suite_neo4j_restoration.py`) is renamed and its `_count()` re-pointed to `FalkorDBLiteConnection._execute_query` (D4). See "Deferred item resolved" below.
- **Module-depth read.** `conftest.py` is currently *shallow* — it holds only data-dict fixtures and one hook, with the real DB-fixture logic scattered across ~10 files. Option A **deepens** it: the connection lifecycle lives behind a 1-line interface (`db` fixture) with a meaningful implementation (session DB + autouse reset). Deletion test: removing the shared fixture would re-scatter `Neo4jConnection`-style construction back into ~10 files — it earns its keep, it is not a pass-through.

---

## Known tradeoffs

- **We give up per-test database isolation-by-construction in favor of isolation-by-reset.** A fresh connection per test would be bulletproof but costs ~5s × N (unacceptable). We accept that a test which forgets the corpus depends on `clear_all` running — mitigated by making the reset `autouse` so no test can forget it.
- **We give up parallel test execution (`pytest-xdist`) for now.** One session DB = one lockfile holder (L9). Parallelism would need per-worker temp DBs. The suite is serial today, so nothing is lost immediately; it is deferred, not designed out.
- **Consolidating ~10 fixtures is higher-touch per-step than 28 isolated edits**, but lower total risk: one fixture definition to get right, then mechanical import/constant deletions whose correctness is "does the file still collect."

---

## Migration ordering (batched so each step is independently verifiable)

The migration is sequenced so every batch can be run green before the next starts. "Verify" = `pytest <files in batch>` collects and passes (or the documented expected fallout).

1. **Batch 0 — delete the misleading reference doc.** Remove `docs/AI_artifacts/0_draft/falkordb-reference.md` (D5/L-draft-10). No test impact; prevents the implementer subagent reading a fake API. Verify: file gone.
2. **Batch 1 — build the shared fixture in `conftest.py`.** Add session `db` fixture (temp dir + `FalkorDBLiteConnection` + `get_*` getters), the function-scoped autouse `clear_all`, and a session-finalizer that closes the connection and removes the temp dir. Do not yet touch the per-file fixtures. Verify: `conftest` imports clean; a throwaway one-test smoke collects.
3. **Batch 2 — config tests (D6/L1).** Rewrite `test_config.py` + `test_config_integration.py` against the four real getters. Self-contained (no DB fixture). Verify in isolation. This unblocks anything importing config.
4. **Batch 3 — top-level `db()` fixture files.** `test_infrastructure`, `test_authoring`, `test_ingest`, `test_graph_proximity`, `test_retrieval`: delete local fixture + `NEO4J_*` constants + dead imports, repoint type hints, let them inherit the conftest `db`. One file at a time; verify each.
5. **Batch 4 — class-nested fixture files.** `test_compression`, `test_export`: same, but the fixture is nested in a class — repoint or delete in favor of the shared one. Verify each.
6. **Batch 5 — integrity (D7/L7/L8).** `test_integrity`: `IntegrityChecker(db)` single-arg; ensure `skip_redundancy=True` or `.[fallback]` installed. Verify.
7. **Batch 6 — inline-construction files.** `test_session` (`:124,192`), `test_embeddings:431`: swap inline `Neo4jConnection(...)` → shared `db` fixture (preferred) or `FalkorDBLiteConnection(...)` with getters. Verify.
8. **Batch 7 — post-suite restoration (D4/L2).** Rename `test_post_suite_neo4j_restoration.py` → drop `neo4j`; re-point `_count()` to `FalkorDBLiteConnection._execute_query`; remove the `pytest.skip` on ImportError. **Expect new live failures here** (see fallout). Verify, document any surfaced failure.
9. **Batch 8 — comment/string-only scrubs.** `test_hook_perf_floors` (comment), `test_architecture_flowchart` (asserts the string "Neo4j" appears in a doc — **assertion-bearing, escalate as OQ-3**), `test_pyproject_packaging` (comment + a `neo4j` dependency-name check — escalate), `test_methodology_ingest`/`test_phase4_*`/`test_phase6efg`/`test_phase6bcd` (comments + `_StubNeo4jSession` mock class name), `test_phase3b_export_subagent_roles` (skip-message strings), `tests/fixtures/methodology_loader.py` (comment), `tests/plugin/test_fresh_install_smoke.py` (comment). Verify suite-wide `grep -ri neo4j tests/` reaches incidental-only.
10. **Batch 9 — infra-assertion collision (OQ-1, BLOCKER).** `test_bootstrap.py` + `tests/plugin/test_session_start_bootstrap.py`. **Do not edit until OQ-1 is resolved** — these assert deleted infrastructure and cannot pass under G3 without an explicit decision.
11. **Batch 10 — full run + benchmarks (D8).** `pytest` green; `pytest tests/benchmarks/` + `pytest -m perf` run-no-crash.

---

## Expected fallout (document, don't suppress)

- **L2 un-skip:** `test_post_suite_neo4j_restoration` stops skipping and runs live for the first time against FalkorDBLite. It shells out to `writ import-markdown bible/` and then counts `Skill`/`Playbook`/`ForbiddenResponse` nodes in the **production** graph. If methodology ingest has any FalkorDB-specific gap, this test will now *fail loudly* where it used to *skip silently*. That is the intended exposure — but flag it as a likely first-real-failure site to the implementer, not a regression in this phase's wiring.
- **OQ-1 infra tests:** until resolved, `test_bootstrap` + `test_session_start_bootstrap` keep failing. They are **not** counted as "fixture migration failed."

---

## Deferred item resolved — restoration hook keep/adjust

**Resolution: KEEP both the `pytest_sessionfinish` hook and the renamed restoration test. Do not remove either in Phase 3.**

Reasoning, plain English: the draft worried the hook might be vestigial now that tests use a throwaway DB. It is **not** vestigial. The hook restores the **production** graph (`.writ/graph.db`), not the test DB — it always did. The throwaway-temp-DB decision changes only what the *tests* connect to; it does not change what the *hook* restores. The hook's job — "after a `pytest` run, the live `/always-on?mode=work` endpoint still returns the methodology corpus" — is independent of where test data lived. Removing it would re-introduce the exact symptom its docstring describes (`conftest.py:8-22`): an empty methodology corpus after a test run.

One honest caveat for the open questions: with a throwaway test DB, **most tests no longer wipe the production graph at all**, so the *blast radius* the hook guards against is smaller than under Neo4j (where every test hit the one shared prod DB). Whether the hook is now strictly necessary or merely defensive is a *logic* judgement, which the draft explicitly puts out of Phase 3 scope. So: keep it, re-point its sibling test's `_count()` to FalkorDBLite (D4), and record the "is it still load-bearing?" question as **OQ-4** — do not delete.

---

## Risks (for research / planning to verify)

- **R1 · Session-scoped connection + autouse async reset interaction.** The autouse `clear_all` is `async`; needs `pytest-asyncio` wiring consistent with how the existing `@pytest_asyncio.fixture` (`test_session:118`) and `@pytest.fixture async def db` patterns are configured. Research should confirm the project's asyncio mode (auto vs strict) before writing the fixture.
- **R2 · Class-nested fixtures shadowing the shared one.** `test_compression`/`test_export` define `db` *inside a class*. Simply deleting them and relying on conftest works only if no class-local setup depends on fixture scope. Verify each.
- **R3 · `TestRepoWideNoHardcodedCreds` self-reference.** That meta-test scans `tests/` for a literal it imports from `writ.config`. Once `DEFAULT_NEO4J_PASSWORD` is deleted, the import breaks before the scan runs. The rewrite must remove the import, not just the scan (OQ-2).
- **R4 · Benchmarks may reference the old fixture shape.** `benchmarks/bench_targets.py` instantiates `IntegrityChecker` (codegraph blast radius). D8 says run-no-crash; confirm benchmarks construct with the single-arg API.
- **R5 · `grep -ri neo4j tests/` false "incidental" calls.** `test_architecture_flowchart` and `test_pyproject_packaging` *assert on* the string "neo4j" — they are not incidental comments. Classifying them as "comment-only" would be wrong (OQ-3).

---

## Open questions

**OQ-1 — Infra-assertion tests contradict the shipped product (BLOCKER)**

Right now, a handful of tests demand that the setup script start a Docker database and that a `docker-compose.yml` file exist. Phase 2 deliberately deleted both — the product no longer uses Docker at all. So these tests currently fail, and they describe the opposite of what was built.

The question: do we change these tests' assertions to match the Docker-free reality, even though Phase 3 is locked as "no changed assertions"?

**If we change the assertions:** the tests pass and describe the real product; but we breach the locked "no changed assertions" rule, so it needs explicit sign-off as a scoped exception (it is arguably Phase-2 cleanup that leaked into Phase 3).
**If we leave them as-is:** we cannot reach "all 282 green"; the done-when is unmet. Skipping/xfail-ing them is itself a test-logic change requiring the same sign-off.

Recommendation: treat these specific files as a **Phase-2 carryover exception** and update their assertions to match the Docker-free bootstrap (or delete the now-obsolete `TestDockerCompose`/`docker compose` assertions). Reason a non-coder can weigh: the alternative is a permanently red suite that lies about how the product is installed. Needs your explicit yes because it touches the "no changed assertions" lock.

**OQ-2 — What happens to the repo-wide credential-scan meta-test?**

Right now, a meta-test scans every test file for a hardcoded Neo4j password to prevent secrets leaking into code. FalkorDBLite has no password, so there is no secret to scan for.

The question: re-aim that meta-test at a new invariant, or retire it?

**If we re-aim it** (e.g. "no test file constructs a raw connection bypassing the shared fixture"): we keep a useful guard, but we are writing *new* test logic, which brushes against the "no new tests" lock.
**If we retire it:** simplest, honest (the thing it guarded no longer exists), but we lose a drift guard with no replacement.

Recommendation: retire the credential-specific assertions (the secret they guarded is gone) and note a follow-up to add a "no raw-connection-in-tests" guard in a later phase. Lowest-risk under the locks.

**OQ-3 — Documentation-string assertions that mention "Neo4j".**

`test_architecture_flowchart.py:125` asserts the architecture doc contains the word "Neo4j" among its tech terms; `test_pyproject_packaging.py` checks a `neo4j` dependency name. These are assertion-bearing, not comments.

The question: update the expected strings to "FalkorDB", or leave the docs/deps as historical?
Recommendation: update them to match reality (the architecture is FalkorDB now). This is the same "carryover" judgement as OQ-1; bundle the decision.

**OQ-4 — Is the post-suite restoration hook still load-bearing? (do not act in Phase 3)**

With a throwaway test DB, most tests no longer wipe the production graph, so the hook's safety net guards a smaller blast radius than before. Whether it is now strictly necessary or merely defensive is a logic question the draft puts out of scope.
Recommendation: **keep as-is this phase**; record this as a candidate cleanup for a later phase. Do not remove.

**OQ-5 — Scaffold the missing guardrail docs?**

`docs/CONSTRAINTS.md` / `TECH_DEBT.md` / `OPEN_QUESTIONS.md` do not exist, so guardrail-check Review has nothing to filter. Recommendation: scaffold them in a process pass (out of Phase 3 scope) so future design phases get real constraint filtering.

---

## ADR candidate (flag only — not written here)

The **fixture-architecture choice (Option A: session-scoped real DB + autouse reset)** meets all three ADR gates:
1. **Hard to reverse** — once ~10 files depend on the shared conftest fixture, switching back to per-file or per-test connections is a wide change.
2. **Surprising without context** — a future reader will wonder why tests share one mutable DB instead of isolating per test; the ~5s startup cost is the non-obvious reason.
3. **Real trade-off** — per-test isolation, per-file fixtures, and a fixture factory were all genuine alternatives (see Options explored).

Recommend writing an ADR for this decision in the `/architecture-docs` step. **Not authored here** per instruction.

---

## Options explored

### Option A — session-scoped connection in conftest + function-scoped autouse `clear_all` + one shared `db()` (Recommended)

**What this means:** One real test database starts once, every test gets it wiped clean automatically, and the ~10 duplicated connection fixtures collapse into a single shared one.

**Approach:** Session `db` fixture builds `FalkorDBLiteConnection(<tmp>/graph.db, get_falkordb_graph(), get_falkordb_module(), get_redis_bin())`; function-scoped `autouse` fixture awaits `clear_all()`; session finalizer closes + removes the temp dir.

**Files touched:** `conftest.py` (add fixtures + finalizer); ~10 live-DB files (delete local `db()`, `NEO4J_*` constants, dead imports; repoint type hints); 2 config files (rewrite); 1 post-suite file (rename + re-point); comment/string scrubs; (OQ-gated) 2 infra files.

**Cost:** Dev effort medium. Runtime: one ~5s engine startup per session. Maintenance: one fixture to own.

**Risk:** Shared mutable DB — a test that depends on stale data could pass falsely; mitigated by `autouse` reset (no test can opt out). Async-fixture wiring must match the project's `pytest-asyncio` mode (R1).

**Module depth:** New boundary = the `db` fixture (1-line interface, real DB-lifecycle implementation) — passes deletion test (removing it re-scatters connection code into ~10 files). Deepens the currently-shallow `conftest.py`. Real seam: 2+ adapters (every live-DB file consumes it).

**What it defers:** Parallel execution (`pytest-xdist`) — would need per-worker temp DBs (L9).

**Constraints check:** G1 ✓ (retrieval untouched) · G2 ✓ (tests only) · G3 ✓ for fixtures; **OQ-1 carve-out for infra tests** · G4 ✓ (never await `_execute_query`) · G5 ✓ (temp dir → unique socket, no prod lock) · G6 ✓ (config test asserts x86_64 raise).

### Option B — per-file fixtures repointed in place (Not recommended)

**What this means:** Keep each file's own `db()` fixture but change Neo4j → FalkorDBLite inside each.
**Why not:** Pays ~10× engine startup (each file's function-scoped fixture spins a new ~5s subprocess unless also made session/module-scoped), and leaves the duplication L4 calls out as the real work. Higher total edits, higher drift. One-line dismissal: solves imports, not the actual duplication problem.

### Option C — fixture factory (`make_db()` returning fresh connections) (Not recommended)

**What this means:** A helper that any test calls to build a connection on demand.
**Why not:** Speculative seam — only one adapter (tests), no second consumer. Re-introduces per-call startup cost or pushes lifecycle management onto each caller. Adds an abstraction for single-use code (violates scope discipline). One-line dismissal: more machinery than the problem needs.

### Rejected alternatives (one line each)

- **Mock the `GraphConnection` protocol everywhere (AsyncMock the whole live-DB family):** rejected by D1 — loses real-Cypher fidelity, the whole point of the swap; also a behavior change to what tests verify.
- **Point tests at the production `.writ/graph.db`:** rejected by D2/G5 — lockfile collision with a running server and risk to prod data.
- **Delete `test_post_suite_neo4j_restoration.py` outright:** rejected by D4 — it pins a real post-suite contract; rename + re-point instead.
