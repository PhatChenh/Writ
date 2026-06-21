# Plan: Phase 2 — Infrastructure Cleanup
_Last updated: 2026-06-20_
_Status: [ ] pending_

> Source spec: `docs/AI_artifacts/2_specs/phase2-infra-cleanup.md` (components 1–12).
> Source research: `docs/AI_artifacts/3_research/phase2-infra-cleanup.md` (assumptions A1–A18 verified; A18 RESOLVED).
> Behavior-inventory prefix: **P2-INFRA** (success criteria 01–08).
> This plan owns HOW and the ordering; the spec owns WHAT. Each phase names the spec component(s) it implements — open the spec for the full Build / Files / Done-when detail.

---

## Architecture

Plain English: Phase 1 already swapped the *database engine* deep inside the `writ/` package — out went Docker-hosted Neo4j, in came an embedded FalkorDBLite that runs a private `redis-server` subprocess with a graph plugin loaded over a local socket. The engine works. What is still broken is everything *around* it: the setup scripts still try to start a Docker container, ~16 helper scripts crash on their first line because they import names Phase 1 deleted, the runtime hook still tries to `docker start writ-neo4j` on every prompt, and dead Docker/CI files linger. This phase is plumbing-and-cleanup only — it changes how Writ is set up and operated, never how rules are retrieved or ranked.

How the pieces connect (the load-bearing seam, verified against current code):
- `writ/config.py` exposes exactly four getters — `get_falkordb_path`, `get_falkordb_graph`, `get_falkordb_module`, `get_redis_bin` (`config.py:47,53,59,65`) — each backed by a `DEFAULT_*` constant (`config.py:20-23`).
- Those four values become the four positional arguments of the one connection class: `FalkorDBLiteConnection(db_path, graph, module_path, redis_bin)` (`db.py:86-92`). The in-production call pattern, copied verbatim by every fixed script, is `FalkorDBLiteConnection(get_falkordb_path(), get_falkordb_graph(), get_falkordb_module(), get_redis_bin())` (verified at `cli.py:761,912,941,979` and `server.py:143-146`).
- Constructing that object writes a redis config pointing at `vendor/falkordb.so`, spawns `redis-server` at the `redis_bin` path, waits for its Unix socket, then connects (`db.py:104-145`).
- Every query funnels through one private method, `_execute_query(cypher, params)` (`db.py:162-184`) — the *only* place that understands FalkorDB's raw result format. It returns `list[dict]` with string keys, the same shape the old Neo4j `record.data()` produced. **Critical seam detail (landmine L11, verified):** `_execute_query` is a synchronous `def` (`db.py:162`) and calls `self._graph.query(...)` with **no `await`** (`db.py:169`) — the `falkordb` 1.x client is sync. The public DB methods (`create_rule`, `create_methodology_node`, etc.) are `async def` but call `_execute_query` *without* `await` internally. So rewritten scripts must `await` any public method they call, but must **never** put `await` in front of `_execute_query`.

What this phase conforms to and must not touch:
- `writ/retrieval/` is frozen (guardrail G1, CLAUDE.md critical rule). The two Neo4j docstring refs there are deferred to the roadmap — not scrubbed here.
- No node/edge schema, ranking-weight, or public-method-signature change (G2/G5). The only `writ/` code-shaped change is the `redis_bin` default resolution logic and a file-local private rename `_coerce_neo4j_value` → `_coerce_value` (3 refs, all inside `db.py` — `db.py:50,201,234`; verified zero external importers).
- The binding success gate P2-INFRA-06: `grep -rIi 'neo4j\|docker' scripts/ bin/ .claude/hooks/` returns zero hits.

Platform reality (D9, forced by research OQ-P2-02): FalkorDB v4.14.6 publishes **only** a macOS arm64 plugin asset (`falkordb-macos-arm64v8.so`). There is no macOS Intel `.so`. So this phase is **Apple-Silicon-only**: bootstrap downloads the arm64 asset and fails loudly on `x86_64`; redis resolution likewise has no Intel fallback.

Components introduced by this plan and their extensibility:
- `redis_bin` runtime resolution (Component 1) — `[extensible: config]`: overridable via `writ.toml [falkordb] redis_bin`; the clean future hook for non-Homebrew/Intel support.
- The `.so` version pin lives only in the two bootstrap scripts (Components 8/9) — `[extensible: config]`: a version bump is a one-line URL change (asset name is release-specific; re-verify per bump).
- Everything else is a deletion or a verbatim swap to the existing constructor — `[closed]`, by design. The spec explicitly rejected a shared `scripts/open_db()` factory (it would be a pass-through over one constructor call); do **not** introduce one.

---

## Approach

Fix the shared seam first, then radiate outward. Component 1 (`db.py` redis resolution) lands before anything that opens a connection, because every resurrected script and both bootstraps construct `FalkorDBLiteConnection`. Then the 16 broken scripts are fixed in dependency buckets (constructor-only → query-rewrite → hybrid), each verified by *running/importing the script* — not by new pytest, since test adaptation is Phase 3 (out of scope). Shell/CI cleanup follows, with the `docker-compose.yml` deletion sequenced to land in the same commit as the last reference-scrub so no dangling `$COMPOSE_FILE` window ever exists. The independent cosmetic scrubs (hook, stop-server, CI, docstrings) slot in wherever convenient.

TDD note: this phase has no new behavior to test-drive in pytest (tests are frozen for Phase 3). The RED→GREEN discipline here is mechanical: RED = the script/import currently crashes or the grep gate currently fails; GREEN = run the import/script/grep and observe it pass. Each phase's Test criteria are exactly those runnable checks.

---

## Phases

### Phase 1 — DB connection seam: redis resolution + Neo4j-name scrub
**Goal**: Make the connection resolve `redis-server` robustly on Apple Silicon and remove the last Neo4j name from the DB module — with zero public-signature change. This gates every later phase that opens a connection.

**Implements**: spec **Component 1**. Satisfies **P2-INFRA-08**.

**Design**:
Before — the `redis_bin` default is a hardcoded Apple-Silicon literal in two places (`config.py:23` `DEFAULT_REDIS_BIN`, and the constructor default at `db.py:91`). If `redis-server` isn't at exactly that path the connection dies with the opaque "Redis with FalkorDB module failed to start" (`db.py:140-142`). And the value-coercion helper still carries the name `_coerce_neo4j_value`.
After — redis is resolved at runtime in a fixed order (Apple-Silicon-only, D9): (1) `writ.toml [falkordb] redis_bin` override → (2) `shutil.which("redis-server")` → (3) arm64 Homebrew fallback `/opt/homebrew/opt/redis/bin/redis-server` → (4) if none resolve, raise an explicit error naming the missing binary. On `x86_64`, fail loudly with "x86_64 not supported (Apple-Silicon-only, D9)" rather than the opaque socket-timeout error. The helper is renamed `_coerce_value`. No public method signature changes.

**Steps**:
1. In `writ/config.py`, replace the static `DEFAULT_REDIS_BIN` literal (`config.py:23`) consumption with runtime resolution inside `get_redis_bin()` (`config.py:65`): honor a `writ.toml [falkordb] redis_bin` override first; else `shutil.which("redis-server")`; else, if `platform.machine()` is `arm64`, the Homebrew fallback constant; else raise the explicit "x86_64 not supported (Apple-Silicon-only, D9)" error. Keep the fallback as a named `DEFAULT_*`/helper constant (ARCH-CONST-001).
2. In `writ/graph/db.py`, align the constructor default at `db.py:91` so a no-arg-`redis_bin` construction also resolves correctly (the live path is the config getter; keep the two in sync — research Tech-Debt note).
3. Rename `_coerce_neo4j_value` → `_coerce_value` at the definition (`db.py:50`) and both call sites (`db.py:201,234`). All 3 refs are inside `db.py` (A12 verified — zero external importers).

**Files to modify**:
- `writ/config.py` — `get_redis_bin()` resolution + the `DEFAULT_*` constant (~`:20-23,:65`).
- `writ/graph/db.py` — constructor `redis_bin` default (`:91`); rename helper (`:50,201,234`).

**Test criteria** (RED before / GREEN after):
- [ ] On this Apple-Silicon machine with no `writ.toml` override, opening a `FalkorDBLiteConnection(...)` resolves a real `redis-server` (via `which` or the arm64 fallback) and the socket appears.
- [ ] Simulating `x86_64` (or reading the branch) yields the explicit "x86_64 not supported" message, not the opaque "Redis failed to start".
- [ ] `grep -rn "_coerce_neo4j_value" writ/` returns zero hits.
- [ ] `grep -rn "_coerce_value" writ/` returns the def + exactly 2 call sites.
- [ ] `python -c "import writ.graph.db, writ.config"` imports cleanly.

**Commit boundary**: one commit — "Phase 2.1: runtime redis-server resolution + _coerce rename".

**Status**: [ ] pending

---

### Phase 2 — Constructor-only script fixes (3 scripts)
**Goal**: Resurrect the 3 scripts that only call high-level methods — a pure import + constructor swap, no query rewrites.

**Implements**: spec **Component 2**. Contributes to **P2-INFRA-05**.

**Design**:
Before — `migrate.py`, `instrument-cold-start.py`, `profile_hotpath.py` import `Neo4jConnection` and `get_neo4j_*` (deleted in Phase 1), so they `ImportError` on load; `migrate.py` additionally crashes at *module level* because it calls `get_neo4j_*()` at import time (`migrate.py:22-24`).
After — each imports `FalkorDBLiteConnection` + the four `get_falkordb_*`/`get_redis_bin` getters and constructs via the canonical 4-arg call. They use only high-level methods, so no `_driver`/`_database` rewrite is needed (A4 verified: these 3 are absent from the `_driver` grep set).

**Steps**:
1. In all three: swap `from writ.graph.db import Neo4jConnection` → `FalkorDBLiteConnection`; swap the `from writ.config import get_neo4j_*` line → `from writ.config import get_falkordb_path, get_falkordb_graph, get_falkordb_module, get_redis_bin`.
2. Replace every `Neo4jConnection(...)` with `FalkorDBLiteConnection(get_falkordb_path(), get_falkordb_graph(), get_falkordb_module(), get_redis_bin())`. Rename `db: Neo4jConnection` type hints → `db: FalkorDBLiteConnection`.
3. In `migrate.py` specifically (A8 verified): remove/replace the 3 module-level `get_neo4j_*()` assignments (`:22-24`), the `Neo4jConnection(...)` at `:34`, the 2 type hints (`:31,:51`), and scrub the "into Neo4j graph" argparse description (`:57`) so the grep gate passes.

**Files to modify**:
- `scripts/migrate.py`, `scripts/instrument-cold-start.py`, `scripts/profile_hotpath.py`.

**Test criteria**:
- [ ] `python -c "import scripts.migrate"` (and the analogous import for the other two) raises no `ImportError` on `Neo4jConnection`/`get_neo4j_*`.
- [ ] Running one of them does not raise `AttributeError` on `db._driver`/`db._database`.
- [ ] `grep -rIi neo4j scripts/migrate.py scripts/instrument-cold-start.py scripts/profile_hotpath.py` returns nothing.

**Depends on**: Phase 1 (constructor must resolve redis on this arch).

**Commit boundary**: one commit — "Phase 2.2: fix 3 constructor-only scripts".

**Status**: [ ] pending

---

### Phase 3 — Query-rewrite script fixes (12 scripts)
**Goal**: Resurrect the 12 scripts that reach into the deleted raw Neo4j session API by routing their hand-written Cypher through the existing `_execute_query` bridge, keeping all surrounding print/verification logic unchanged.

**Implements**: spec **Component 3**. Satisfies **P2-INFRA-05** (with Phases 2 and 4).

**Design**:
Before — the 10 seeders (`seed_phase_1a_injection.py` … `seed_phase_5_process.py`), `export_subagent_roles.py`, and `instrument-corpus-stats.py` open `async with db._driver.session(database=db._database) as session:` and run `await session.run(...)`, reading results via `await result.single()` or `[rec.data() async for rec in result]`. Both `_driver` and `_database` were deleted in Phase 1, so these `AttributeError` at runtime (and the imports `ImportError` first).
After — the import + constructor swap from Phase 2 is applied, and each raw-session block is rewritten to a single `db._execute_query(cypher, params)` call. That returns `list[dict]` directly (A6/A7 verified), so result-reading lines convert by dict indexing.

**Steps**:
1. Apply the Phase 2 import + constructor swap to all 12.
2. Replace each `async with db._driver.session(...)` block with a `db._execute_query(cypher, params)` call. **No `await` on `_execute_query`** — it is sync (`db.py:162`, verified). If the enclosing function stays `async def` because it also `await`s `db.close()` or a high-level method, that is fine — only the `_execute_query` call must not be awaited (L11).
3. Adjust result-reading lines:
   - `[rec.data() async for rec in result]` → use the `list[dict]` `_execute_query` already returns.
   - `(await result.single())["col"]` (single-row counts) → `rows[0]["col"]`.
   - existence probes `await result.single() is not None` → `bool(rows)`.
4. Verified raw-session locations to rewrite: `seed_phase_1a_injection.py:270,276,284,290,308,310` (reference shape) plus the analogous blocks in the other 9 seeders; `export_subagent_roles.py:52-67` (`fetch_roles`); `instrument-corpus-stats.py:86-88` (`_load_rules`) and `:96-98` (`_count_edges`). **Diff each seeder against the `seed_phase_1a` reference before rewriting** — they likely share a shape but may carry delete-by-id / probe-then-upsert variants (spec Component 3 Decision; research suggested-research note). Do not blind-apply one template.
5. Scrub any remaining "Neo4j" wording in comments/docstrings across the 12 files so the grep gate passes.

**Files to modify**:
- `scripts/seed_phase_1a_injection.py` … `scripts/seed_phase_5_process.py` (10 files), `scripts/export_subagent_roles.py`, `scripts/instrument-corpus-stats.py`.

**Test criteria**:
- [ ] Each of the 12 imports without `ImportError`.
- [ ] Running one seeder reports created/updated counts; `export_subagent_roles.py` produces its role list; `instrument-corpus-stats.py` prints node/edge counts.
- [ ] None raise `AttributeError` on `db._driver`/`db._database`, and none raise `TypeError: object list can't be used in 'await' expression` (the L11 sync-in-async trap).
- [ ] `grep -rIi neo4j` over the 12 files returns nothing.

**Depends on**: Phase 1.

**Commit boundary**: may split into two commits if the seeder diffs reveal divergent shapes — "Phase 2.3a: fix 10 seeders" and "Phase 2.3b: fix export/instrument scripts". Otherwise one commit.

**Status**: [ ] pending

---

### Phase 4 — Hybrid script fix: `ingest_subagent_roles.py`
**Goal**: Resurrect the one script that already uses a high-level method but carries a single raw-session verification block.

**Implements**: spec **Component 4**. Contributes to **P2-INFRA-05**.

**Design**:
Before — `ingest_subagent_roles.py` correctly uses `await db.create_methodology_node("SubagentRole", n)` (`:118`) but its verification block (`:124-131`) still opens `db._driver.session(...)` → `session.run(q)` → `[rec.data() async for rec in result]`, which crashes after Phase 1.
After — the high-level `create_methodology_node` calls stay untouched; only the verification block is rewritten to `db._execute_query(q)` returning `list[dict]` (same adjustment as Phase 3).

**Steps**:
1. Apply the import + constructor swap (Phase 2 pattern).
2. Keep `await db.create_methodology_node(...)` calls as-is.
3. Rewrite the single raw-session verification block (`:124-131`) to a non-awaited `db._execute_query(q)` and read the returned `list[dict]`.
4. Scrub any remaining "Neo4j" wording in the file.

**Files to modify**:
- `scripts/ingest_subagent_roles.py`.

**Test criteria**:
- [ ] Imports without `ImportError`.
- [ ] Runs end-to-end: methodology nodes created, verification block prints its row count without touching `db._driver`.
- [ ] `grep -rIi neo4j scripts/ingest_subagent_roles.py` returns nothing.

**Depends on**: Phase 1.

**Commit boundary**: one commit — "Phase 2.4: fix ingest_subagent_roles hybrid script". (May be folded into the Phase 3 commit if landed together.)

**Status**: [ ] pending

---

### Phase 5 — Independent cosmetic scrubs (hook, stop-server, CI, docstrings)
**Goal**: Land the four no-dependency cleanups that have no bearing on connection-open: remove the hook's Docker auto-start block, scrub the stop-server comment, delete the dead CI workflow, and scrub the remaining `writ/` docstrings. Grouped because each is small, independent, and individually verified by grep.

**Implements**: spec **Components 5, 7, 11, 12**. Satisfies **P2-INFRA-07** (Component 5) and contributes to **P2-INFRA-06** (Component 7).

**Design**:
- Component 5 (`writ-rag-inject.sh`) — Before: on every prompt the hook runs `command -v docker` → `docker start writ-neo4j` → waits on port 7474 (`:44-54`). After: that block is deleted and the comment at `:36-37` drops "Neo4j and"; the embedded DB now comes up inside `writ serve`. Everything else — lockfile dance (`:41-42,72-82`), uvicorn start (`:56-70`), stdin-parse/RAG logic (`:85+`) — is left exactly as is (D7, A15 verified: this is the only Docker block in the hook). The hook must still degrade to "server unavailable" / exit 0 when startup fails.
- Component 7 (`stop-server.sh`) — edit the single comment at `:4` ("Does NOT stop Neo4j…") to drop the Neo4j reference. No logic change.
- Component 11 (`.github/workflows/pr.yml`) — delete it (Linux + Neo4j service container, incompatible with embedded macOS-only design, D3). Keep `publish.yml` (no DB dependency, A17). **Before deleting, read `publish.yml` once** to confirm it has no DB step (research carried-forward note — name/scope match was confirmed, deep read was not).
- Component 12 (docstring scrub, 5 non-frozen `writ/` files) — replace "Neo4j" with "FalkorDB"/"the embedded graph" in docstrings/comments only, no logic change: `authoring.py:27,42`; `compression/abstractions.py:3,63`; `export.py:3,135`; `graph/ingest.py:3`; `graph/schema.py:260,488`. **Do NOT touch** `writ/retrieval/traversal.py` (`:1,4,7,26,34`) or `writ/retrieval/pipeline.py` (`:467,507`) — G1-frozen, deferred to roadmap.

**Steps**:
1. Delete `.claude/hooks/writ-rag-inject.sh:44-54` and edit the comment at `:36-37`.
2. Edit `scripts/stop-server.sh:4` comment.
3. Read `.github/workflows/publish.yml` to confirm DB-independence, then delete `.github/workflows/pr.yml`.
4. Scrub the 9 docstring/comment lines across the 5 in-scope `writ/` files.

**Files to modify**:
- `.claude/hooks/writ-rag-inject.sh`, `scripts/stop-server.sh`, `writ/authoring.py`, `writ/compression/abstractions.py`, `writ/export.py`, `writ/graph/ingest.py`, `writ/graph/schema.py`.
- Delete: `.github/workflows/pr.yml`.

**Test criteria**:
- [ ] With Docker absent and the Writ server stopped, submitting a prompt starts *only* uvicorn; `/tmp/writ-rag-debug.log` and hook output show no `docker start writ-neo4j`; hook exits 0 and degrades to "server unavailable" on startup failure. (P2-INFRA-07)
- [ ] `grep -i neo4j scripts/stop-server.sh` returns nothing.
- [ ] `.github/workflows/pr.yml` is gone; `publish.yml` untouched and confirmed DB-free.
- [ ] `grep -rni neo4j writ/authoring.py writ/compression/abstractions.py writ/export.py writ/graph/ingest.py writ/graph/schema.py` returns nothing; the `writ/retrieval/` refs remain intentionally.
- [ ] All five `writ/` files still import cleanly (behavior unchanged).

**Depends on**: none (all independent).

**Commit boundary**: one commit — "Phase 2.5: cosmetic scrubs (hook, stop-server, CI, docstrings)". May be split per-file if preferred; each is self-verifying.

**Status**: [ ] pending

---

### Phase 6 — Bootstrap rewrites + compose deletion (atomic group)
**Goal**: Make both bootstraps run clean on a Docker-free Apple-Silicon Mac (install Redis via brew, download the arm64 `.so`, idempotent skips, always-ingest, start only the Writ daemon), strip the dangling compose refs from `ensure-server.sh`, and delete `docker-compose.yml` — all so no dangling-`$COMPOSE_FILE` window ever exists.

**Implements**: spec **Components 6, 8, 9, 10** (grouped per the spec's sequencing note). Satisfies **P2-INFRA-01, 02, 03, 04** and contributes to **P2-INFRA-06**.

**Design**:
Before — both bootstraps require Docker (`require_tool docker`), check the Docker daemon, run `docker compose up -d neo4j`, wait on a bolt port, print a `Neo4j : bolt://…` banner line, and reference `$COMPOSE_FILE`; `ensure-server.sh` has its own Neo4j-start block (`:24-47`) with a dangling `docker compose -f $WRIT_DIR/docker-compose.yml logs` hint (`:42`); `docker-compose.yml` defines the single `neo4j` service. None of this works without Docker, and the embedded DB needs none of it.
After — both bootstraps ensure Homebrew `redis-server` (skip if present), download `falkordb-macos-arm64v8.so` into `vendor/falkordb.so` (skip if present; fail loud on `x86_64`), keep the venv/ONNX skip-on-exists steps, **always** run the MERGE-idempotent ingest, and start only `writ serve` — whose embedded DB comes up inside the process. `ensure-server.sh` loses its Neo4j block entirely. `docker-compose.yml` is deleted. Because all four land in one commit, the `$COMPOSE_FILE` references and the file vanish together.

**Steps** (ordering inside the phase):
1. **Component 6** — `scripts/ensure-server.sh`: remove `NEO4J_PORT` (`:21`), `neo4j_running()` (`:24-27`), the entire "Check Neo4j" block (`:29-47`, including `docker compose up -d neo4j` and the `$WRIT_DIR/docker-compose.yml` log hint at `:42`). Keep the Writ-server check/start (`:49-80`).
2. **Component 8** — rewrite `scripts/bootstrap.sh`: drop Neo4j header wording (`:1-11`); remove `NEO4J_WAIT_SECONDS` (`:16`) and `COMPOSE_FILE` (`:25`); remove `require_tool docker` (`:59`) and add a brew `redis` ensure step (`brew list redis` → `brew install redis` if missing) and make sure `/opt/homebrew/bin` is on PATH before ingest so `shutil.which` resolves (OQ-P2-01); delete the Docker-daemon check (`:79-86`); add the `.so` step (loud `x86_64` guard via `uname -m`, then skip-if-exists, else unconditional download of `falkordb-macos-arm64v8.so` from `https://github.com/FalkorDB/FalkorDB/releases/download/v4.14.6/falkordb-macos-arm64v8.so` into `vendor/falkordb.so` — no both-arch branch); keep venv/deps/ONNX skip-on-exists (`:88-119`); delete the Neo4j compose block (`:147-169`); make ingest **always run** (D10, MERGE-idempotent) and reword the "into Neo4j" warning (`:176`); keep the daemon start (`:179-206`); remove the `Neo4j : bolt://…` banner line (`:216`).
3. **Component 9** — apply the same edits to `scripts/bootstrap-plugin.sh`, preserving its plugin-specific paths (`CLAUDE_PLUGIN_ROOT`/`CLAUDE_PLUGIN_DATA`, venv at `${WRIT_DATA}/.venv`, editable install from `${WRIT_DIR}`, `.so` into `${WRIT_DIR}/vendor/falkordb.so`): header (`:1-13`), `COMPOSE_FILE` (`:37`), `require_tool docker` (`:71`), Docker-daemon check (`:92-99`), Neo4j compose block (`:133-155`, incl. `$COMPOSE_FILE` hint at `:153`), ingest always-run (`:157-163`, reword `:162`), banner line (`:203`).
4. **Component 10** — delete `docker-compose.yml`. Run the final grep gate confirming no `docker-compose`/`COMPOSE_FILE` reference survives in `scripts/`/`bin/`/`.claude/hooks/`.

**Files to modify**:
- `scripts/ensure-server.sh`, `scripts/bootstrap.sh`, `scripts/bootstrap-plugin.sh`.
- Delete: `docker-compose.yml`.

**Test criteria**:
- [ ] On an Apple-Silicon Mac with Docker NOT installed, `scripts/bootstrap.sh` exits 0, prints "Writ is ready", makes no `docker` call, references no Neo4j, downloads `vendor/falkordb.so`, leaves `.writ/graph.db` on disk. (P2-INFRA-01, 03)
- [ ] A second `bootstrap.sh` run with an edited bible rule re-ingests (the edit is queryable afterward) while skipping venv/ONNX/brew/`.so`. (P2-INFRA-04)
- [ ] On `x86_64`, `bootstrap.sh` exits non-zero with the explicit "Apple-Silicon-only (D9)" message.
- [ ] With `CLAUDE_PLUGIN_ROOT` set and Docker absent, `bootstrap-plugin.sh` on Apple Silicon exits 0, prints "Writ plugin is ready", makes no docker/Neo4j call, lands the venv at the persistent data dir, downloads the arm64 `.so`, leaves `.writ/graph.db`. (P2-INFRA-02)
- [ ] `ensure-server.sh` contains no `neo4j`/`docker` reference and still starts (or non-fatally degrades) the Writ server.
- [ ] `docker-compose.yml` no longer exists; `grep -rn "docker-compose\|COMPOSE_FILE" scripts/ bin/ .claude/hooks/` returns nothing.
- [ ] **Final P2-INFRA-06 gate**: `grep -rIi 'neo4j\|docker' scripts/ bin/ .claude/hooks/` returns zero hits (migration-comment carve-outs aside).

**Depends on**: Phases 1–4 (the ingest step opens a connection through the fixed constructor and runs the fixed ingest path). All four components in this phase must land in one commit (avoids the dangling-ref window — research Edge Cases).

**Commit boundary**: one atomic commit — "Phase 2.6: bootstrap rewrites (redis + arm64 .so + always-ingest), ensure-server scrub, delete docker-compose".

**Status**: [ ] pending

---

## Open Questions

- **OQ-P2-01** — RESOLVED (research). Redis resolution order is ARM-only: `writ.toml` override → `shutil.which("redis-server")` → arm64 Homebrew fallback → loud failure; bootstrap's `brew install redis` precedes the first connection so `which` resolves. No x86 fallback. Carried into Phase 1 + Phase 6; not re-opened.
- **OQ-P2-02** — RESOLVED (research, decisive). v4.14.6 publishes only `falkordb-macos-arm64v8.so`; no Intel macOS asset. D9 = Apple-Silicon-only; download arm64 unconditionally, fail loud on `x86_64`. Carried into Phase 6; not re-opened.
- **OQ-P2-03** — Non-blocking. Design prose says "15 broken scripts" but the verified grep and the design's own audit enumerate **16** (3 + 12 + 1). This plan builds for **16**. Worth a one-line confirmation from the design author whether one script was intentionally excluded or "15" is a prose slip — but it does not block: fixing all 16 importers is strictly required for P2-INFRA-05.
- **`publish.yml` DB-independence** — confirmed by name/scope only in research, not a deep read. Phase 5 Step 3 reads it once before deleting `pr.yml` to close this. Low risk.

## Out of Scope

(Carried verbatim-in-intent from spec "Out of scope" — do not expand into these.)
- **Test suite adaptation** — the 282 tests are NOT updated here; deferred to Phase 3 (D7). Phase 2 must not break test *imports*, but edits no test. (This is why every phase verifies by import/run/grep, not by new pytest.)
- **Retrieval pipeline (`writ/retrieval/`)** — frozen (G1). Including its two Neo4j docstring refs (`traversal.py`, `pipeline.py`) — deferred to the roadmap's Phase 2 Carryover, never touched here.
- **Linux / cross-platform** — macOS-only (D2). No Linux branch anywhere; no Intel fallback.
- **Hook logic beyond the one Docker block** — only the `docker start writ-neo4j` block is removed from `writ-rag-inject.sh`; RAG/session/escalation/prompt-cleaning logic is unchanged.
- **`.gitignore`, `pyproject.toml`, Python-version work** — already done; no change.
- **A shared `scripts/open_db()` factory** — rejected by the design's deletion test; do NOT introduce one.
- **`falkordb-reference.md`** — stale; trust the code, do not edit.
- **`scripts/friction-log-delta.py`** — NOT broken (imports no `writ.config`/`writ.graph` symbol, A11 verified); excluded from the 16.
