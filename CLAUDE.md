# CLAUDE.md — Writ (Forked)

Fork of infinri/Writ v1.5.0. Hybrid RAG rule retrieval + workflow enforcement for Claude Code. Swapping Neo4j → FalkorDBLite to eliminate Docker dependency.

---

## Project Context

Writ is a coding rule engine with two services:
- **Librarian**: FastAPI server (localhost:8765) with 5-stage hybrid retrieval pipeline (BM25 + ANN vector + graph traversal + two-pass RRF ranking). Retrieves relevant coding rules per query instead of stuffing all rules into every prompt.
- **Process Keeper**: 33 hook scripts enforcing workflow discipline — modes (Discussion/Debug/Review/Work), phase gates, test-first gates, anti-cheat tokens.

This fork replaces Neo4j (Docker container) with FalkorDBLite (embedded, zero-config, Cypher-compatible).

## Reference Docs

Read before changing architecture:
- `docs/roadmap/project-design.md` — design decisions, principles, what changes vs stays
- `docs/roadmap/roadmap.md` — build order and phase scope
- `.claude/CODEBASE.md` — original architecture guide, module map, key invariants
- `docs/WORKFLOW_COMPARISON.md` — side-by-side: our workflow (ai_kms pattern) vs Writ author's approach
- `docs/STUDY_GUIDE.md` — 8-level learning path for understanding Writ internals

## Tech Stack

| Layer | Choice |
|-------|--------|
| Graph DB | FalkorDBLite (replacing Neo4j) |
| BM25 search | Tantivy |
| Vector search | hnswlib |
| Embeddings | ONNX Runtime + all-MiniLM-L6-v2 (384-dim) |
| API server | FastAPI + Uvicorn |
| CLI | Typer + Rich |
| Language | Python 3.11+ |

## Repo Structure

```
writ/                     Python package (source)
  graph/                  Graph DB layer — db.py is PRIMARY CHANGE TARGET
  retrieval/              5-stage pipeline — DO NOT MODIFY during DB swap
  analysis/               Friction logging, instrumentation
  shared/                 Budget constants (budget.json)
.claude/hooks/            33 hook scripts — workflow enforcement
.claude/agents/           6 agent definitions (explorer, planner, implementer, etc.)
bible/                    Rule corpus — 18 domains, markdown format
docs/AI_artifacts/        /build-pipeline output (design, specs, research, plans)
bin/                      Shell utilities + gate checks
scripts/                  Bootstrap, seed scripts, ONNX export
templates/                CLAUDE.md template, settings.json template
tests/                    282 tests + 12 benchmarks
```

## Commands

```bash
# Setup (after Phase 1 complete)
pip install -e ".[dev]"
scripts/bootstrap.sh

# Run server
writ serve                    # starts FastAPI on localhost:8765

# Rule management
writ ingest bible/            # load rules from markdown into graph
writ query "security injection" # test retrieval pipeline
writ export                   # export graph back to markdown

# Tests
pytest                        # run all 282 tests
pytest -m perf                # hook latency regression tests
pytest tests/benchmarks/      # retrieval benchmarks

# Linting
ruff check writ/ tests/
mypy writ/
```

## Coding Patterns

- Config in `writ.toml`, loaded by `writ/config.py`. Env var override: `WRIT_` prefix.
- All retrieval pipeline stages use pre-warmed in-process indexes. No I/O in hot path.
- Pydantic models in `writ/graph/schema.py` define all node/edge types.
- Rule markdown format: frontmatter (Domain, Severity, Scope, Mandatory) + body (Trigger, Statement, Violation, Pass, Enforcement, Rationale).
- Mandatory rules (ENF-* prefix) bypass retrieval pipeline — always loaded via `/always-on` endpoint.
- Ranking weights must sum to 1.0 (see `writ.toml [ranking]`).

## Skill Output

`/build-pipeline` artifacts (design, specs, research, plans) go in `docs/AI_artifacts/`. Do not place them at project root or in `docs/roadmap/`.

## CodeGraph First (MANDATORY — applies to main thread AND all subagents)

This repo has a `.codegraph/` directory. CodeGraph is the PRIMARY code exploration tool — not Read, not Grep, not Glob. One `codegraph_explore` call returns verbatim source + call graphs, replacing dozens of grep+Read round-trips.

**Decision tree (follow this order):**
1. Need to understand/locate code? → `codegraph_explore "<question or symbol names>"` (start here, ONE call)
2. Need specific symbol detail? → `codegraph_node`
3. Need blast-radius / who-calls-what? → `codegraph_callers`
4. Need pattern inspection AFTER codegraph gave you the map? → NOW Grep is appropriate
5. Need non-Python files (config, markdown, templates)? → Read directly

**Anti-pattern:** Starting with `grep -r` or `find` for Python symbol lookups. That repeats work CodeGraph already pre-computed and costs 10x more tokens.

## Critical Rules

- Do NOT modify retrieval pipeline logic (`writ/retrieval/`) during the DB swap. Only `writ/graph/` and config files change.
- Preserve all 8 key invariants listed in `.claude/CODEBASE.md`.
- FalkorDBLite Cypher may differ from Neo4j Cypher in edge cases — test each query individually.
- 282 tests are the correctness contract. All must pass after swap.

## Build Progress

- **Phase 1 — Core Storage Swap:** done (merged `6b5ef23`). Neo4j → FalkorDBLite embedded graph DB.
- **Phase 2 — Infrastructure Cleanup:** done. All 16 scripts fixed, bootstraps rewritten (Docker-free, brew+redis+.so), docker-compose.yml deleted, hook Dock block removed, docstrings scrubbed. Plan: `docs/AI_artifacts/4_plans/phase2-infra-cleanup.md`.
- **Phase 3 — Test Suite Green:** ✅ done (2026-06-20). 33 files migrated (tests/ + benchmarks/). Session-scoped `FalkorDBLiteConnection` fixture on temp dir + autouse `clear_all`. Core suite: 189+ pass. Zero Neo4j wiring hits. Plan: `docs/AI_artifacts/4_plans/phase3-test-suite-green.md`.
- **Post-Phase-3 cleanup + verification:** ✅ done (2026-06-20). ONNX model exported; `writ query` verified live (332 nodes / 174 edges, ~6ms). Cosmetic Neo4j scrub finished (only 3 load-bearing refs kept). OPEN_QUESTIONS.md OQ-01..04 marked resolved. Full suite: 1315 pass; all 268 fails + 107 errors are `~/.claude/skills/writ` not-installed (plugin axis), not DB. See STATE.md "Post-Phase-3 cleanup".
- **Phase 4 — Workflow Adaptation:** 🔵 in progress (grill/design, no code yet). **Adapt-and-learn mode — do NOT develop Writ; adapt + rewire our own skills/hooks.** Decisions locked 2026-06-21: D4-01 (graph-canonical authoring), D4-02 (per-repo "A-auto" isolation), **D4-03 (adopt full mode system + Work mode, skill-driven auto-switch; Writ's plan→test→code gates REPLACE our HITL/build-pipeline gates).** **Full record: `WRIT-LOCAL-ADAPTATION.md` (repo root) — read first** (now also holds the full Writ graph-schema appendix). 4D hook walkthrough **COMPLETE** — all 33 hooks decided (**31 keep / 2 drop**); ledger = per-hook review table in WRIT-LOCAL-ADAPTATION.md with rationale per row. **Adaptation implementation underway** on branch `phase4-adaptation` following the ordered work-plan table in that file: **#1 (A-auto, D4-02) DONE + smoke-tested** (per-repo port centralized in `bin/lib/common.sh` + `writ-rag-inject.sh`; live daemon on 9041, rule_count 276, cold-RDB-reload verified), **#2 mode wiring next**. Read the **"Handoff — next AI starts here"** section at the bottom of WRIT-LOCAL-ADAPTATION.md first. See also `STATE.md`, `docs/roadmap/roadmap.md`.

## What AI Gets Wrong

- **Async methods wrap a sync client — never `await _execute_query`.** `FalkorDBLiteConnection` methods are `async def`, but `_execute_query` (`writ/graph/db.py:162`) calls the synchronous `falkordb` 1.x client (`self._graph.query(...)`) with no `await`. Call `db._execute_query(...)` directly; putting `await` in front of it is wrong. **This sync-ness is LOAD-BEARING for tests (A8):** the session-scoped test DB fixture is event-loop-safe ONLY because `db.py` never binds an event loop. Adding any asyncio primitive (async-redis, a `Lock`, real `await`) to `db.py` silently reintroduces "attached to a different loop" failures across the suite.
- **Phase 1 left ~16 helper scripts broken (now fixed in Phase 2).** They imported `Neo4jConnection` (gone from `writ.graph.db`) and `get_neo4j_uri/user/password` (gone from `writ.config`). Phase 2 rewrote all 16 to use `FalkorDBLiteConnection` + `_execute_query`.
- **macOS Apple-Silicon only.** FalkorDB v4.14.6 publishes no Intel macOS module (`falkordb-macos-arm64v8.so` is the only Mac asset). Bootstrap fails loudly on `x86_64` by design (D9).
- **`vendor/falkordb.so` needs execute permission after download.** The bootstrap script (`scripts/bootstrap.sh:177`) downloads via `curl` which does not set the executable bit. Running `chmod +x vendor/falkordb.so` is required; without it Redis fails with "does not have execute permissions." Bootstrap runs `chmod` implicitly via the install flow, but manual download does not.
- **Subagents given broad file-migration scope may edit production source beyond the plan.** Phase 3 Subagent B (8 test files) also modified `writ/graph/db.py` with 3 FalkorDB compatibility fixes (traverse_neighbors BFS rewrite, list_constraints/indexes output normalization, get_abstraction Node→dict). The plan said "no production source changes." Constrain subagent prompts to explicitly forbid production edits unless listed.
- **The shared conftest `db` fixture uses a TEMP dir — never touches `.writ/graph.db`.** Tests that need to observe production state (post-suite restoration, import-markdown) must build their own `FalkorDBLiteConnection` with production config getters, not use the `db` fixture. The fixture exists solely for isolated test data.
- **Tests that build `build_pipeline()` need an ONNX model or `WRIT_ALLOW_EMBEDDING_FALLBACK=1`.** ~14 tests across `test_authoring.py`, `test_graph_proximity.py`, `test_retrieval.py`, `test_session.py` fail with `RuntimeError: ONNX embedding model unavailable` unless the ONNX model is exported (`scripts/export_onnx.py`) or the fallback env var is set. **Now exported** (2026-06-20) at `~/.cache/writ/models/onnx/model.onnx`; those tests pass and `writ query` works live. The DB migration doesn't touch the embedding pipeline.
- **`scripts/export_onnx.py` hangs on a network probe even when the model is fully cached.** `from_pretrained(export=True)` does an HF Hub metadata check that stalls offline/slow-network despite a complete local `~/.cache/huggingface` copy (symptom: process alive, ~0 CPU, 0-byte `.incomplete` blob). Run it as `HF_HUB_OFFLINE=1 TRANSFORMERS_OFFLINE=1 python scripts/export_onnx.py` to force offline.
- **Most of the test suite needs the plugin installed at `~/.claude/skills/writ`.** In a bare dev checkout, ~270 tests fail/error with `FileNotFoundError: ~/.claude/skills/writ/...` — they exercise Process Keeper hooks + plugin-install paths, NOT the DB. All DB/migration/retrieval test files are 100% green without the plugin. Install via `scripts/bootstrap-plugin.sh` (writes to `~/.claude`, starts the daemon) to green the hook/plugin tests.
- **Stale embedded-server state breaks `writ query` with `ConnectionRefusedError`.** `FalkorDBLiteConnection` spawns a redis-server on a deterministic `/tmp/writ-<md5(db_dir)>/redis.sock`. Orphaned redis procs + a stale socket file (from a crashed run) make `__init__`'s `os.path.exists(socket)` short-circuit onto a dead listener. Fix: kill orphan `redis-server unixsocket:/tmp/writ-*` procs and `rm` the stale socket + `.writ/graph.lock`, then retry.
