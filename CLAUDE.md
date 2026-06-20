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

Current phase: **Phase 1 — Core Storage Swap** (not started).

## What AI Gets Wrong

(Starts empty. Add gotchas discovered during work.)
