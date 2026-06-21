# Phase 2 — Infrastructure Cleanup: Locked Decisions
> From grill interview, 2026-06-20
> Re-grilled 2026-06-20 (code-verified pass) — added D7–D10, landmine register, doc corrections.
> Code is the source of truth; `falkordb-reference.md` describes an API Phase 1 did NOT build (see L10).

## Requirement (restated)
Remove all Docker/Neo4j dependencies from scripts, bootstrap, and CI so the project
runs entirely on embedded FalkorDBLite with zero Docker requirement on macOS.

---

## Locked Decisions

### D1 — DB file location
`.writ/writ.db` at project root. Gitignored. Per-project isolation (each repo has its own
graph, no cross-contamination). Configurable via `WRIT_DB_PATH` env var or `writ.toml [falkordb]`
for overrides.

**Rationale:** Matches how `.git/`, `.venv/` work. Project-local. Survives repo wipes means
nothing — local tooling state. Original author used per-project Neo4j databases; same
intent with embedded file.

### D2 — Platform scope
macOS only. No Linux support. CI on Linux dropped.

**Rationale:** Single dev on macOS. Removing Docker was about local simplicity, not
cross-platform portability. Linux CI adds complexity for zero personal benefit.

### D3 — CI
Delete/disable `.github/workflows/pr.yml` (Neo4j service blocks, Linux runners).
Keep `.github/workflows/publish.yml` (PyPI publish on tags — no DB dependency).

### D4 — docker-compose.yml
Delete entirely. No role after Phase 2. History preserved in git.

### D5 — vendor/falkordb.so distribution
Auto-download in `bootstrap.sh` from FalkorDB GitHub releases. Version: `v4.14.6`
(pinned from Phase 1 vendor dir). macOS only — detect arch (x86_64 vs ARM64) for
correct binary URL.

**Rationale:** Manual download defeats zero-config goal. One script = full setup.

### D6 — Bootstrap idempotency
Fully idempotent — skip steps already done:
- `vendor/falkordb.so` exists → skip download
- Redis installed (Homebrew) → skip `brew install`
- `.writ/writ.db` exists → skip ingest
- `.venv/` exists → skip venv creation

Preserves original contract: "Idempotent — safe to re-run."

**Carve-out (D10):** ingest is NOT skipped on existing DB — see D10.

---

## Re-grill Decisions (2026-06-20, code-verified)

### D7 — Scope: all Docker/Neo4j carriers
Phase 2 covers *every* file still carrying Docker/Neo4j, not just the originally-named ones.
Code scan found two the first grill missed:
- `scripts/bootstrap-plugin.sh` — second bootstrap path (plugin-install mode), full Docker/Neo4j flow.
- `.claude/hooks/writ-rag-inject.sh` — runtime RAG hook, `docker start writ-neo4j` on every prompt injection.

Test suite stays deferred to Phase 3. Everything on a runtime or bootstrap path is in scope now.

**Rationale:** "Done When: zero docker/neo4j in scripts/ bin/ hooks/" already demands the hook.
The plugin path is a real install entry. Leaving them = "zero Docker" false on plugin load / first prompt.

### D8 — Fix all ~16 broken scripts in one pass
All Python scripts importing the dead symbols get fixed together, not just bootstrap-critical ones:
- Corpus seeders (10): `seed_phase_1a…5`
- Subagent ingest/export (2): `ingest_subagent_roles`, `export_subagent_roles`
- Migration shim (1): `migrate.py`
- Instrumentation/profiling (4): `instrument-cold-start`, `instrument-corpus-stats`, `profile_hotpath`, `friction-log-delta`

**Rationale:** all share the same two dead imports — any left unfixed = ImportError landmine resurfacing.
Cheap mechanical swaps for high-level-method scripts; raw-session ones need rewriting eventually anyway.

### D9 — Both macOS arches IF cheap, else Apple-Silicon-only
Target both x86_64 + ARM64 *if* arch-handling stays near-free (a few lines). If design/research finds it
messy, fall back to Apple-Silicon-only and break loudly on Intel. Either way, fix the hardcoded ARM
`redis_bin` path (L5) so it is not silently Apple-Silicon-assuming.

**Rationale:** honors D5's "detect arch" letter without contradicting D2 (still macOS-only). Cost-gated —
not worth complexity for a machine that may never exist.

**RESOLVED 2026-06-20 (research):** FalkorDB v4.14.6 ships only an arm64 macOS module — no Intel binary exists at this pin. D9's cost-gate therefore resolves to Apple-Silicon-only: download `falkordb-macos-arm64v8.so`, fail loudly on x86_64.

### D10 — Always ingest (MERGE-idempotent)
On re-run with existing `.writ/writ.db`, bootstrap ALWAYS runs ingest (it is MERGE-based, so a no-op when
nothing changed). Skip-on-exists is kept ONLY for expensive steps: venv create, ONNX export, brew install,
`.so` download.

**Rationale:** skip-ingest-on-exists silently misses new/edited bible rules and breaks "safe to re-run."
MERGE makes re-ingest free when unchanged; sub-second at 80 rules when it isn't.

---

## Landmine Register (verified against code, re-grill)

| # | Landmine | Evidence | Carry-into |
|---|----------|----------|-----------|
| L1 | Scripts ALREADY broken post-Phase-1 (ImportError). `Neo4jConnection` gone from `db.py`; `get_neo4j_uri/user/password` gone from `config.py`. ~16 scripts import both. Phase 2 = resurrect, not swap. | grep empty for `Neo4jConnection`; `config.py` has only `get_falkordb_path/graph/module` | design+spec |
| L2 | Doc's swap target is wrong. Real: `FalkorDBLiteConnection(db_path, graph="writ", module_path="vendor/falkordb.so", redis_bin="/opt/homebrew/opt/redis/bin/redis-server")`. Function is `get_falkordb_path()` NOT `get_falkordb_db_path()`. | `db.py:86` | spec |
| L3 | Raw-session scripts need query-body rewrites, not constructor swaps. `seed_phase_1a:270` uses `db._driver.session(database=db._database)`. `FalkorDBLiteConnection` has no `_driver`/`_database`; exposes `_execute_query(cypher, params)` + high-level methods. | `db.py` members; `seed_phase_1a:270`; ingest/export use `_driver.session`+`rec.data()` | research |
| L4 | `vendor/falkordb.so` absent → runtime fails today. Default `module_path="vendor/falkordb.so"`, dir doesn't exist. D5 download is required, not optional. | `ls vendor/` → absent | plan |
| L5 | `redis_bin` hardcoded ARM path `/opt/homebrew/...`; Intel = `/usr/local/...`. D9 fixes. | `db.py:86` | design (D9) |
| L6 | Two bootstrap scripts — `bootstrap.sh` + `bootstrap-plugin.sh`, both full Docker/Neo4j. | bootstrap-plugin.sh:71,93,134 | D7 |
| L7 | Runtime hook `writ-rag-inject.sh:44-47` does `docker start writ-neo4j` on prompt injection. | hook source | D7 |
| L8 | D4 delete of `docker-compose.yml` dangles live refs in bootstrap.sh / bootstrap-plugin.sh / ensure-server.sh. Scrub at delete time. | bootstrap.sh:30; ensure-server.sh | spec |
| L9 | `.gitignore .writ/` already present (line 22). Drop from scope. | grep `.gitignore` | scope |
| L10 | `falkordb-reference.md` ≠ what Phase 1 built. Reference describes `pip falkordblite` + `AsyncFalkorDB`/`redislite.falkordb_client` + positional tuples; actual `db.py` spawns raw `redis-server` + vendored `.so`, `_execute_query`→`list[dict]`; pyproject deps `falkordb>=1.0,<2`. **Trust code, not the reference doc.** | `db.py:86`; `pyproject:44` | all downstream |

---

## Scope

### In scope
- `scripts/bootstrap.sh` — full rewrite: remove Docker/Neo4j, add Redis (brew) + `vendor/falkordb.so` download (D5), idempotency (D6), always-ingest (D10)
- `scripts/bootstrap-plugin.sh` — same treatment, plugin-install path (D7/L6)
- `scripts/ensure-server.sh` — remove Neo4j/Docker checks; embedded DB needs no pre-start
- `scripts/stop-server.sh` — drop stale Neo4j comment (cosmetic)
- `.claude/hooks/writ-rag-inject.sh` — remove `docker start writ-neo4j` block (D7/L7); embedded DB up via `writ serve`
- All ~16 broken Python scripts (D8) — fix dead imports `Neo4jConnection`+`get_neo4j_*` → `FalkorDBLiteConnection(db_path=get_falkordb_path(), …)`; raw-`_driver.session()` scripts get query-body rewrites via `_execute_query`/high-level methods (L1/L2/L3)
- `docker-compose.yml` — delete; scrub live refs in bootstrap/ensure-server at delete time (L8)
- `.github/workflows/pr.yml` — delete or disable
- `writ/graph/db.py` — rename `_coerce_neo4j_value()` → `_coerce_value()` (cosmetic); fix arch-fragile `redis_bin` default (D9/L5)
- `writ/authoring.py` — update Neo4j docstring references
- `writ/compression/abstractions.py` — update Neo4j docstring references

### Out of scope
- Test suite (Phase 3)
- Retrieval pipeline
- Linux support
- Any new features
- `.gitignore` — `.writ/` already present (L9), nothing to do
- Hook *logic* — only the Docker/Neo4j auto-start in `writ-rag-inject.sh` is touched (D7); behavior unchanged otherwise

---

## Done When
- `scripts/bootstrap.sh` AND `scripts/bootstrap-plugin.sh` run clean on macOS without Docker installed
- All ~16 Python scripts import + run against FalkorDBLite without error (no ImportError, no `_driver` use)
- `grep -rIi 'neo4j\|docker' scripts/ bin/ .claude/hooks/` returns zero hits (excluding migration comments)
- `.writ/writ.db` created at project root after bootstrap; re-run re-ingests bible changes (D10)
- `vendor/falkordb.so` downloaded by bootstrap (D5); connection opens without manual binary placement

---

## Open Questions
None blocking. Cost-gated item to settle in design/research:
- **D9 arch breadth** — confirm whether both-arch handling is "cheap" (a few lines). If not, fall back to Apple-Silicon-only.
