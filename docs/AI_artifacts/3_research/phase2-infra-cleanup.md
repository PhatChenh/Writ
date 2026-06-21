# Research: Phase 2 — Infrastructure Cleanup
_Last updated: 2026-06-20_

## Overview

Plain English: This phase finishes a database swap that Phase 1 started. Phase 1 replaced the database engine inside the main `writ/` package (Neo4j → embedded FalkorDBLite) but left all the surrounding plumbing — setup scripts, helper scripts, the runtime hook, and CI — still wired for the old Docker-based Neo4j. About a dozen-plus helper scripts have been crashing on their first line since Phase 1 merged. This research independently verifies, against the real code, every claim the spec makes about what is broken and how to fix it.

What this research verified: all 18 spec assumptions (A1–A18), the load-bearing code facts about the DB connection layer, the exact Docker/Neo4j touch points in every shell file, and the two deferred questions (OQ-P2-01 redis-server resolution, OQ-P2-02 the FalkorDB v4.14.6 download assets).

Headline findings:
- **17 of 18 assumptions validated. 1 invalidated (A18).** A18 is a non-blocking cosmetic claim — it under-counts the leftover Neo4j docstring mentions in `writ/`, but none of the extras break anything or fail any gate.
- **OQ-P2-02 is now decided, and it forces D9 to Apple-Silicon-only.** The FalkorDB v4.14.6 release has a macOS arm64 `.so` but **no macOS Intel (x86_64) `.so`**. The both-arch path the design hoped for is impossible at this pin. Bootstrap must download the arm64 asset and fail loudly on Intel.
- **OQ-P2-01 is resolvable**: `shutil.which("redis-server")` does resolve after `brew install redis` on a normal macOS PATH (verified on this Apple-Silicon machine), with the arch-derived Homebrew path as a fallback.
- The core L11 fact (the async/sync mismatch the rewrites depend on) is confirmed exactly as the spec states.

---

## Key Components

Plain English: A handful of files carry all the weight in this phase. The connection object and the config getters are the API every broken script must be re-pointed at; one private method (`_execute_query`) is the bridge that 13 scripts route their hand-written queries through; and a set of shell files carry the Docker/Neo4j start-up logic that must be deleted.

- `writ/graph/db.py` — `FalkorDBLiteConnection.__init__` (`db.py:86-92`), the sync bridge `_execute_query` (`db.py:162-184`), the `_coerce_neo4j_value` helper (`db.py:50`, calls at `:201,:234`).
- `writ/config.py` — the four getters `get_falkordb_path`/`get_falkordb_graph`/`get_falkordb_module`/`get_redis_bin` (`config.py:47-68`) and their `DEFAULT_*` constants (`config.py:20-23`).
- The 16 broken scripts under `scripts/` (enumerated in Spec Verification A3–A5).
- Shell files: `scripts/bootstrap.sh`, `scripts/bootstrap-plugin.sh`, `scripts/ensure-server.sh`, `scripts/stop-server.sh`, `.claude/hooks/writ-rag-inject.sh`, and `docker-compose.yml`.

---

## How It Works

Plain English: When any script (or bootstrap's ingest step, or the server) opens the database, it constructs `FalkorDBLiteConnection` with four values pulled from config. The constructor writes a small redis config file pointing at the downloaded `vendor/falkordb.so` plugin, spawns a private `redis-server` subprocess (using the path `get_redis_bin()` returns), waits for its Unix socket, and connects. Every query then funnels through one method, `_execute_query`, which is the only place that understands FalkorDB's raw result format and hands callers back a plain list of dictionaries.

The async/sync shape (the L11 landmine) verified at `db.py:162-184`:
- `_execute_query` is declared `def` (synchronous) — `db.py:162`. NOT `async def`.
- It calls `result = self._graph.query(cypher, params=...)` at `db.py:169` with **no `await`** — the `falkordb` 1.x client is synchronous.
- The public methods (`create_rule`, `create_methodology_node`, `traverse_neighbors`, `get_rule`, `create_edge`) are `async def` but call `self._execute_query(...)` **without `await`** internally (`db.py:189,202,224,240,258`).
- Consequence for the rewrites: a rewritten script calls `db._execute_query(cypher, params)` **without `await`** (it is sync and returns `list[dict]` directly). If the enclosing function stays `async def` because it also `await`s `db.close()` or a high-level method, that is fine — only the `_execute_query` call itself must not be awaited. The spec's constraint wording ("must `await` the public method… but must NOT add `await` in front of `_execute_query`") is correct against the code.

---

## Spec Verification

Plain English: Every spec assumption was checked against the actual file and line. All but one held. A18 is wrong as written (it claims authoring.py + abstractions.py are the *only* Neo4j references left in `writ/`, but six more exist) — though the error is cosmetic and blocks nothing.

| ID | Spec Claim | Verdict | Evidence |
|----|-----------|---------|----------|
| A1 | Constructor takes exactly 4 positional args in order `db_path, graph, module_path, redis_bin`. | ✅ Validated | `writ/graph/db.py:86-92` — `__init__(self, db_path, graph="writ", module_path="vendor/falkordb.so", redis_bin="/opt/homebrew/opt/redis/bin/redis-server")`. |
| A2 | `config.py` exposes exactly 4 getters: `get_falkordb_path/graph/module` + `get_redis_bin`. | ✅ Validated | `writ/config.py:47,53,59,65`. 4th getter name is `get_redis_bin` (`:65`). No fifth getter the constructor needs. |
| A3 | 16 Python scripts under `scripts/` import `Neo4jConnection` and/or `get_neo4j_*`. | ✅ Validated | `grep -rln "Neo4jConnection\|get_neo4j" scripts/` → exactly 16 files (10 seeders + export + ingest + instrument-cold-start + instrument-corpus-stats + migrate + profile_hotpath). |
| A4 | 3 scripts are constructor-only (no `_driver`/`_database`): `migrate.py`, `instrument-cold-start.py`, `profile_hotpath.py`. | ✅ Validated | These 3 import Neo4j symbols but are absent from `grep -rln "_driver" scripts/`. Set difference confirms exactly these 3. |
| A5 | 13 scripts open raw `db._driver.session(...)`: the 10 seeders, `export_subagent_roles.py`, `instrument-corpus-stats.py`, `ingest_subagent_roles.py`. | ✅ Validated | `grep -rln "_driver" scripts/` returns exactly those 13. Blocks read at `seed_phase_1a:269-270`, `export_subagent_roles:52-67`, `instrument-corpus-stats:86-99`, `ingest_subagent_roles:124-131`. |
| A6 | `_execute_query` returns `list[dict]` with string keys, matching old `record.data()` shape. | ✅ Validated | `db.py:162` return annotation `-> list[dict]`; body `db.py:172-184` builds `dict(zip(names, converted))` per row, extracting `.properties` from Node/Edge objects. |
| A7 | `_execute_query` is synchronous (`def`, not `async`) and `self._graph.query()` is NOT awaited. | ✅ Validated | `db.py:162` is `def _execute_query` (no `async`); `db.py:169` is `result = self._graph.query(...)` with no `await`. |
| A8 | `migrate.py` broken sites: 3 module-level `get_neo4j_*()` (`:22-24`), 1 `Neo4jConnection(...)` (`:34`), 2 type hints (`:31,:51`). | ✅ Validated | `migrate.py:22-24` module-level getters; `:34` `Neo4jConnection(NEO4J_URI, NEO4J_USER, NEO4J_PASSWORD)`; type hints `db: Neo4jConnection` at `:31` and `:51`. Also argparse description "into Neo4j graph" at `:57` (spec component 2 names it). |
| A9 | `vendor/falkordb.so` absent today; default `module_path` points at nothing. | ✅ Validated | `ls vendor/` → "No such file or directory". Default `module_path="vendor/falkordb.so"` (`db.py:90`). |
| A10 | `redis_bin` default (`config.py:23`, `db.py:91`) is the Apple-Silicon path; Intel uses `/usr/local/...`. | ✅ Validated | `config.py:23` `DEFAULT_REDIS_BIN = "/opt/homebrew/opt/redis/bin/redis-server"`; `db.py:91` same literal. No arch branch. (`/usr/local/opt/redis/bin/redis-server` absent on this arm64 box, confirming the path is arch-specific.) |
| A11 | `friction-log-delta.py` imports no `writ.config`/`writ.graph` symbol → not broken, out of scope. | ✅ Validated | Imports are only `argparse, hashlib, sys, pathlib` (`friction-log-delta.py:14-19`). No Neo4j, no writ import. Correctly excluded from the 16. |
| A12 | `_coerce_neo4j_value` has exactly 3 refs, all inside `db.py` (def `:50`, calls `:201,:234`). | ✅ Validated | `grep -rn "_coerce_neo4j_value" writ/` → exactly `db.py:50` (def), `:201`, `:234`. Rename is file-local. |
| A13 | Both bootstraps carry full Docker/Neo4j flow at the cited lines. | ✅ Validated | `bootstrap.sh`: `:16,25,59,79-86,147-169,216` all confirmed (NEO4J_WAIT_SECONDS, COMPOSE_FILE, require_tool docker, docker-info check, compose block, banner). `bootstrap-plugin.sh`: `:18,37,71,92-99,133-155,203` all confirmed. |
| A14 | `ensure-server.sh` has a Neo4j docker block (`:24-47`) + dangling compose-file log hint (`:42`). | ✅ Validated | `NEO4J_PORT` `:21`; `neo4j_running()` `:24-27`; "Check Neo4j" block `:29-47` with `docker compose up -d neo4j` `:32`; log hint `docker compose -f $WRIT_DIR/docker-compose.yml logs neo4j` at `:42`. |
| A15 | `writ-rag-inject.sh:44-54` is the only Docker block; surrounding logic independent. | ✅ Validated | Block `:44-54`: comment `:44`, `command -v docker` `:45`, `docker start writ-neo4j` `:46`, port-7474 wait `:47-53`, closing `fi` `:54`. No other `docker`/`neo4j` in the hook. Comment "Neo4j and Writ server" at `:36`. |
| A16 | `docker-compose.yml` exists at root, single `neo4j` service; deleting it dangles `$COMPOSE_FILE` refs in 3 shell files. | ✅ Validated | File present (558 bytes); 8 `neo4j` mentions (one service). Live refs: `bootstrap.sh:25,167`, `bootstrap-plugin.sh:37,135,153`, `ensure-server.sh:42`. No other referencing file. |
| A17 | `.github/workflows/` has `pr.yml` (delete) and `publish.yml` (keep). | ✅ Validated | `ls .github/workflows/` → exactly `pr.yml`, `publish.yml`. (publish.yml DB-independence not deep-read; name/scope match D3/D4 — see Open Questions.) |
| A18 | The ONLY Neo4j refs in `writ/` (outside db.py rename) are docstrings in `authoring.py:27,42` + `compression/abstractions.py:3,63`. | ✅ Resolved | Was ❌ Invalidated (six more docstring refs found). **Resolved 2026-06-20:** spec Component 12 widened to scrub the 3 non-frozen extras (`export.py`, `graph/ingest.py`, `graph/schema.py`); the 2 G1-frozen `retrieval/*` refs are deferred to the roadmap (Phase 2 Carryover). All refs are docstrings/comments only, no code. |

---

## Edge Cases & Silent Failure Modes

Plain English: A few things can fail quietly or surprisingly.

- **Intel Mac, no binary to download.** There is no macOS x86_64 `.so` at v4.14.6 (OQ-P2-02). On an Intel Mac, bootstrap cannot download a working plugin at all. The fix is to detect `x86_64` and fail loudly with a clear message — not to attempt a download that produces a non-loadable or 404 file. (`db.py:140-142` already raises a generic "Redis with FalkorDB module failed to start" if the socket never appears; without an explicit arch check the Intel failure stays opaque.)
- **`shutil.which("redis-server")` returns `None` if Homebrew's bin is off PATH.** On a normal macOS shell `/opt/homebrew/bin` (arm64) is already on PATH, so it resolves after `brew install redis`. But if a future change runs the connection in a stripped environment, `shutil.which` returns `None` and `subprocess.Popen([None, ...])` would crash. The arch-derived fallback (`/opt/homebrew/opt/redis/bin/redis-server`) must cover that case, and an unresolved binary must fail loudly (OQ-P2-01).
- **Sync-in-async trap (L11).** If a rewrite author "helpfully" adds `await db._execute_query(...)`, it raises `TypeError: object list can't be used in 'await' expression` because the method is sync. Each rewrite must be checked against `db.py:162`.
- **Dangling `$COMPOSE_FILE` window.** If `docker-compose.yml` is deleted before the shell refs are scrubbed, any run of the old bootstrap/ensure-server path references a missing file. Spec sequencing (components 6/8/9 before/with 10) avoids this.

---

## Dependencies & Coupling

Plain English: The fixes have a strict order. The connection constructor fix must land first because every resurrected script and the bootstrap ingest step opens a connection through it.

- **Component 1 (db.py redis_bin fix) gates Components 2–4 and 8–9.** The scripts and bootstrap ingest open `FalkorDBLiteConnection`; if redis resolution is still arch-fragile they fail on the wrong machine.
- **`_execute_query` is a shared seam** used by all 5 public DB methods and (after this phase) the 13 rewritten scripts. It is `db.py`-internal; no script imports it as a symbol — they call it as a method on a constructed connection. Verified via codegraph: `db.py` is used by 39 files including all the broken scripts.
- **`_coerce_neo4j_value` rename is fully file-local** (A12) — zero external importers, so the rename cannot break any caller.
- **`docker-compose.yml` is referenced only by the 3 shell files** (A16); deleting it after scrubbing them leaves nothing dangling.

---

## Extension Points

Plain English: Where future change is safe, and where it is locked.

- **`redis_bin` resolution** is the one place that should become smarter (dynamic + fallback). Keep it a named `DEFAULT_*` constant overridable via `writ.toml [falkordb] redis_bin` (ARCH-CONST-001 at `config.py:5,19`). This is the clean extension point for any future Intel/non-Homebrew support.
- **The `.so` version pin** lives in bootstrap only. Bumping FalkorDB versions is a one-line URL/asset-name change — but the asset naming scheme (`falkordb-macos-arm64v8.so`) is release-specific and must be re-verified per bump (see OQ-P2-02).
- **Locked:** `writ/retrieval/` (G1), node/edge schema + public method signatures (G2), ranking weights (G5). None are touched by this phase.

---

## Open Questions

### OQ-P2-01 — RESOLVED: redis-server resolution order

Plain English: The current default redis path only works on Apple-Silicon Macs. The question was whether to look the binary up dynamically (`shutil.which`) or hardcode two arch paths, and whether dynamic lookup actually resolves after bootstrap installs redis.

**Answer (verified on this machine, arm64):**
- `which redis-server` → `/opt/homebrew/bin/redis-server` (resolves). `brew --prefix redis` → `/opt/homebrew/opt/redis`. The current hardcoded default `/opt/homebrew/opt/redis/bin/redis-server` also exists.
- `brew install redis` symlinks `redis-server` into `/opt/homebrew/bin/`, which is already on a standard macOS PATH (it is where `brew` itself lives). Bootstrap's `source $VENV_DIR/bin/activate` (`bootstrap.sh:97`) prepends the venv bin but preserves the rest of PATH, so `/opt/homebrew/bin` stays reachable. Therefore `shutil.which("redis-server")` resolves at the ingest step on Apple Silicon.

**Recommended resolution order for Component 1's default:**
1. `writ.toml [falkordb] redis_bin` override (explicit user value) — highest priority, already supported by `get_redis_bin()`.
2. `shutil.which("redis-server")` — works on any Mac with redis on PATH.
3. Arch-derived Homebrew fallback: `/opt/homebrew/opt/redis/bin/redis-server` on `arm64`. (No `/usr/local/...` Intel fallback is useful here because there is no Intel `.so` to load anyway — see OQ-P2-02.)
4. If none resolve: raise an explicit error naming the missing binary (not the opaque "Redis failed to start").

Sequencing guarantee: the `brew install redis` step in bootstrap must run **before** the ingest step (first connection open) so `shutil.which` resolves. This is already the implied order; the plan should make it explicit.

### OQ-P2-02 — RESOLVED (decisive): FalkorDB v4.14.6 has NO macOS x86_64 asset

Plain English: The plugin binary is fetched from FalkorDB's GitHub release. The question was whether v4.14.6 publishes separate, predictably-named macOS ARM64 and x86_64 `.so` files. The answer decides whether bootstrap supports both Mac chips or only Apple Silicon.

**Answer:** v4.14.6 has **10 assets**. The complete list (via GitHub API `releases/tags/v4.14.6`):
- `falkordb-arm64v8.so` (Linux arm64)
- `falkordb-debug-arm64v8.so`
- `falkordb-debug-macos-arm64v8.so`
- `falkordb-debug-rhel-x64.so`
- `falkordb-debug-x64.so`
- **`falkordb-macos-arm64v8.so`** ← the macOS arm64 release plugin
- `falkordb-rhel-x64.so` (Linux x86_64, RHEL/glibc)
- `falkordb-x64.so` (Linux x86_64, Debian/glibc)

**There is exactly ONE macOS release asset: `falkordb-macos-arm64v8.so` (arm64). There is NO `falkordb-macos-x64.so` — no macOS Intel/x86_64 prebuilt binary exists.** The `*-x64.so` assets are Linux builds (Mach-O is not their format; they will not load into a macOS `redis-server`).

- Exact macOS arm64 asset name: `falkordb-macos-arm64v8.so`
- Download URL: `https://github.com/FalkorDB/FalkorDB/releases/download/v4.14.6/falkordb-macos-arm64v8.so`
- Verified downloadable: `curl -sIL` → HTTP **200**.

**Decision impact on D9:** The both-arch path is impossible at this pin. **D9 must ship Apple-Silicon-only, downloading `falkordb-macos-arm64v8.so` and failing loudly on `x86_64`** (the design's Option C fallback). The earlier hope that "a single `uname -m` branch ships both arches" does not hold — there is no Intel asset to branch to. Bootstrap should: `arch=$(uname -m)`; if `arm64` → download the macOS arm64 `.so`; if `x86_64` → print an explicit "macOS Intel is not supported (no prebuilt FalkorDB binary at v4.14.6)" error and exit non-zero. This also means OQ-P2-01's Intel fallback path is moot — an Intel Mac cannot run this anyway.

### OQ-P2-03 — Script count: confirmed 16

Plain English: The design prose says "15 broken scripts" in one place but its own audit and the grep enumerate 16. This research confirms **16** (10 seeders + `export_subagent_roles` + `instrument-corpus-stats` + `instrument-cold-start` + `migrate` + `profile_hotpath` + `ingest_subagent_roles`). `friction-log-delta.py` is correctly excluded (A11). The "15" is a prose slip; build for 16. Not a blocker.

### Carried-forward (minor, non-blocking)
- `publish.yml` DB-independence (A17) was confirmed only by name/scope match to D3/D4, not a deep read of the workflow file. If the plan wants certainty before deleting `pr.yml`, read `publish.yml` once to confirm it has no DB step. Low risk.

---

## Technical Debt Spotted

- **Leftover Neo4j docstrings across `writ/`** (the A18 miss): `export.py`, `graph/ingest.py`, `graph/schema.py`, `retrieval/traversal.py`, `retrieval/pipeline.py` still say "Neo4j" in comments/docstrings. The grep gate (P2-INFRA-06) only covers `scripts/ bin/ .claude/hooks/`, so these do not fail any check — but the "scrub the last Neo4j name" intent is left partially done. `retrieval/*` is frozen by G1, so those two cannot be touched in Phase 2 regardless. A future cosmetic-scrub pass could clean `export.py`, `ingest.py`, `schema.py`.
- **The `redis_bin` default duplicated in two files** (`config.py:23` and `db.py:91`). The constructor default at `db.py:91` is only used when someone constructs `FalkorDBLiteConnection` without passing `redis_bin`; all in-production call sites pass `get_redis_bin()`. Fixing both keeps them in sync; the live value is the config getter.

---

## Invalidated Assumptions

### A18 — "Only" Neo4j refs in `writ/` are authoring.py + abstractions.py
**Spec claimed:** "The only Neo4j references in `writ/` Python (outside `db.py`'s rename) are docstrings in `authoring.py:27,42` and `compression/abstractions.py:3,63`."
**Code shows:** Those four exist (verified), but they are NOT the only ones. `grep -rni neo4j writ/ --include="*.py"` (excluding db.py) also returns: `export.py:3` ("canonical Neo4j graph"), `export.py:135` ("Neo4j connection"), `graph/ingest.py:3` ("canonical Neo4j graph"), `graph/schema.py:260` ("Neo4j migration creates a label…"), `graph/schema.py:488` ("Neo4j relationship type…"), `retrieval/traversal.py:1` ("Neo4j Cypher 1-2 hop traversal"), `retrieval/pipeline.py:467` ("JSON strings from Neo4j"), `retrieval/pipeline.py:507` ("Load all non-mandatory rules from Neo4j"). Each was read line-by-line — all are docstrings or comments, none are code.
**Why this matters:** Low. No code path depends on the string "Neo4j", no gate covers `writ/`, and nothing breaks. The only consequence is that Component 12 ("remove the last Neo4j mentions from `writ/` Python docstrings") does not actually remove the *last* mentions — six survive. If the team wants a truthful "zero Neo4j in `writ/`" claim, the scope of Component 12 is wrong as written.
**Suggested resolution directions:** (1) Reword A18 and Component 12's "Goal"/"Done when" to scope the docstring scrub to authoring.py + abstractions.py explicitly (acknowledging retrieval/ is frozen and the rest is deferred). OR (2) widen Component 12 to also scrub `export.py`, `graph/ingest.py`, `graph/schema.py` (leave `retrieval/*` untouched per G1) and adjust the "Done when" grep accordingly. Either is a documentation/scope decision for the spec author, not a code blocker — Phase 2 can ship without it.

**RESOLVED 2026-06-20 (orchestrator, user-confirmed):** Took direction (2) — spec Component 12 widened to scrub `export.py`, `graph/ingest.py`, `graph/schema.py` in addition to authoring.py + abstractions.py. The 2 `retrieval/*` refs stay (G1-frozen) and are recorded in the roadmap's "Phase 2 — Carryover" section for a later phase. No code change; cosmetic only. **This invalidation is closed — not a plan blocker.**
