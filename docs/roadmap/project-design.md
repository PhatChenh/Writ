# Writ (Forked) — Design Spec

## 1. Overview

**Problem:** Original Writ requires Neo4j (Docker container, 7474/7687 ports, separate process). Heavy for local dev, blocks usage on machines without Docker, adds operational complexity for a single-user tool.

**Vision:** A fully embedded, zero-infrastructure Writ that keeps the entire 5-stage hybrid RAG pipeline, process enforcement, and rule evolution system — but runs from a single process with no external dependencies.

**What we're building:** Fork of [infinri/Writ](https://github.com/infinri/Writ) v1.5.0 with Neo4j replaced by FalkorDBLite (embedded Python graph DB, Cypher-compatible, subprocess-based, zero-config).

## 2. Rules & Design Principles

1. **Preserve Writ's retrieval pipeline exactly.** The 5-stage pipeline (domain filter → BM25 → ANN vector → graph traversal → two-pass RRF) must produce identical results. Only the storage layer changes.
2. **Zero external services.** No Docker, no containers, no separate database processes. Everything embeds in the Python process or a managed subprocess.
3. **Cypher compatibility.** FalkorDBLite supports Cypher — rewrite queries only where dialect differs, not the query logic.
4. **All 282 tests must pass.** The test suite is the contract. If tests pass after swap, the swap is correct.
5. **Minimal diff from upstream.** Touch only files that reference Neo4j. Easier to cherry-pick upstream improvements later.

## 3. Stack

| Layer | Choice | Reason |
|-------|--------|--------|
| Graph DB | FalkorDBLite | Embedded, Cypher-native, Python, zero-config. Replaces Neo4j. |
| BM25 search | Tantivy (unchanged) | Already embedded, no change needed |
| Vector search | hnswlib (unchanged) | Already embedded, no change needed |
| Embeddings | ONNX Runtime + all-MiniLM-L6-v2 (unchanged) | Already local inference |
| API server | FastAPI + Uvicorn (unchanged) | |
| CLI | Typer (unchanged) | |
| Language | Python 3.11+ (unchanged) | |

## 4. Project Structure

```
writ/                         ← forked repo root
├── writ/                     ← Python package (source)
│   ├── graph/
│   │   ├── db.py             ← PRIMARY CHANGE: Neo4j driver → FalkorDBLite
│   │   ├── schema.py         ← Pydantic models (unchanged)
│   │   ├── ingest.py         ← Markdown parser (unchanged)
│   │   └── integrity.py      ← May need Cypher dialect fixes
│   ├── retrieval/
│   │   ├── pipeline.py       ← Orchestrator (unchanged)
│   │   ├── ranking.py        ← RRF scoring (unchanged)
│   │   ├── embeddings.py     ← ONNX + hnswlib (unchanged)
│   │   ├── keyword.py        ← Tantivy BM25 (unchanged)
│   │   ├── traversal.py      ← Adjacency cache (unchanged)
│   │   └── session.py        ← Client-side tracker (unchanged)
│   ├── server.py             ← FastAPI endpoints (minor: startup/shutdown)
│   ├── cli.py                ← Typer CLI (minor: connection config)
│   ├── config.py             ← Config loader (neo4j section → falkordb)
│   ├── gate.py               ← Structural gate (unchanged)
│   └── ...
├── .claude/hooks/            ← 33 hook scripts (unchanged)
├── .claude/agents/           ← 6 agent definitions (unchanged)
├── bible/                    ← Rule corpus, 18 domains (unchanged)
├── bin/                      ← Shell utilities
├── scripts/                  ← Seed scripts, bootstrap (Neo4j refs to update)
├── templates/                ← CLAUDE.md, settings.json templates
├── tests/                    ← 282 tests + 12 benchmarks
├── writ.toml                 ← Config (neo4j section → falkordb)
├── pyproject.toml            ← Dependencies (neo4j pkg → falkordb pkg)
└── docker-compose.yml        ← DELETE or repurpose
```

## 5. Features

### F1 — Neo4j → FalkorDBLite Storage Swap

Replace `neo4j` Python driver with `falkordb` package in `writ/graph/db.py`. FalkorDBLite runs as managed subprocess — no Docker, no ports, no config. Connection pool → single embedded connection. Cypher queries stay mostly same, fix dialect differences (property syntax, MERGE behavior, index creation).

**Decision:** Use FalkorDBLite over alternatives (Kuzu archived, GraphQLite too new, SparrowDB no Python-native).

**Tradeoff:** FalkorDBLite is newer than Neo4j — less battle-tested. Acceptable for single-user local tool.

### F2 — Config Migration

`writ.toml` `[neo4j]` section becomes `[falkordb]` with local DB path instead of bolt URI. Environment variable overrides (`WRIT_NEO4J_*` → `WRIT_FALKORDB_*`).

### F3 — Docker Removal

Delete or gut `docker-compose.yml`. Update `scripts/bootstrap.sh` and `scripts/ensure-server.sh` to skip Docker checks. FalkorDBLite auto-creates its data directory.

### F4 — Seed Script Updates

All `scripts/seed_phase_*.py` files use Neo4j driver directly. Update imports and connection handling to FalkorDBLite.

### F5 — Test Suite Adaptation

282 tests reference Neo4j fixtures/mocks. Update test infrastructure to use FalkorDBLite. Most test logic stays identical — only setup/teardown changes.

## 6. Out of Scope

- **Retrieval pipeline changes** — no tuning weights, no adding stages. Deferred.
- **New rule domains** — use existing bible corpus. Add project-specific rules later.
- **Hook modifications** — all 33 hooks stay as-is.
- **Agent definition changes** — all 6 agents stay as-is.
- **Upstream feature parity tracking** — not tracking infinri/Writ changes. This is a divergent fork.
- **Multi-user or remote deployment** — this is a local single-user tool.
