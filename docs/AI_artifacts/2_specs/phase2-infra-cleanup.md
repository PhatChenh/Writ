# Phase 2 — Infrastructure Cleanup

> Spec produced 2026-06-20. Upstream design (trusted): `docs/AI_artifacts/1_design/phase2-infra-cleanup.md`.
> Background (locked decisions D1–D10 + landmine register): `docs/AI_artifacts/0_draft/phase2-decisions.md`.
> Behavior-inventory prefix: **P2-INFRA** (criteria 01–08 in `behavior_inventory.yaml`).
> Where the draft and the design disagree, the **design doc wins** (constructor takes 4 args; `friction-log-delta.py` is not broken; landmine L11 — connection methods are `async def` but the underlying query is NOT awaited).

---

## Purpose

Phase 1 swapped the database engine inside the `writ/` package (Neo4j → embedded FalkorDBLite) but left the *plumbing around it* still wired for Docker-based Neo4j. After this phase, a fresh Mac goes from `git clone` to a running Writ with one command and zero Docker: the setup scripts install Redis via Homebrew and download the database plugin binary instead of starting a container, every helper script that loads rules works again (they have been crashing on import since Phase 1 merged), the runtime hook stops trying to start a Docker container on every prompt, and the dead Docker/CI files are deleted. Nothing about *which rules get retrieved or how they rank* changes — only how the project is set up and operated.

---

## Already built (reuse, do not rebuild)

In plain terms: almost all the database machinery already exists from Phase 1. This phase wires the scripts and setup into it; it does not build new database code. The one method that translates raw query results into the old result shape (`_execute_query`) is the existing bridge every rewritten script will route through — do not create a new wrapper around it.

| Function / Module | Location | What it does | How this spec uses it | Depth |
|-------------------|----------|--------------|-----------------------|-------|
| `FalkorDBLiteConnection.__init__` | `writ/graph/db.py:86-145` | Opens the embedded DB — launches a private redis-server subprocess with the graph plugin loaded, talks over a Unix socket. Takes **4 args**: `db_path, graph="writ", module_path="vendor/falkordb.so", redis_bin=<path>`. | The replacement constructor every broken script calls. | deep |
| `_execute_query(cypher, params)` | `writ/graph/db.py:162-184` | The ONLY method that understands FalkorDB's result format. Returns `list[dict]` with string keys — same shape the old Neo4j `record.data()` produced. **It is a plain `def` (synchronous)** and calls `self._graph.query(...)` directly (no `await`). | The single bridge that the 13 raw-session scripts route their hand-written Cypher through. | deep (20+ adapters) |
| `create_rule(rule_data)` | `writ/graph/db.py:194-203` | Create-or-update a Rule node (MERGE on `rule_id`, idempotent). `async def`; calls `_execute_query` internally. | Already used by high-level scripts; left untouched where present. | deep |
| `create_methodology_node(label, data)` | `writ/graph/db.py` (high-level method) | Create-or-update a methodology node without raw Cypher. | `ingest_subagent_roles.py` already uses it — keep as-is. | deep |
| `_coerce_neo4j_value(v)` | `writ/graph/db.py:50-63` | Converts Python values to FalkorDB-compatible property values (dates→ISO, dicts→JSON). 2 call sites, both inside `db.py` (lines 201, 234). | Renamed to `_coerce_value` (cosmetic Neo4j-scrub); all 3 references are inside the one file. | shallow |
| `get_falkordb_path()` / `get_falkordb_graph()` / `get_falkordb_module()` / `get_redis_bin()` | `writ/config.py:47-68` | The **four** config getters that supply the four constructor arguments. Each falls back to a `DEFAULT_*` constant (`writ/config.py:20-23`). | The constructor-argument source for every fixed script. The `DEFAULT_REDIS_BIN` default (line 23) is the arch-fragile value fixed under D9. | shallow |
| Canonical 4-arg constructor call pattern | `writ/cli.py:761, 912, 941, 979`; `writ/server.py:143` | The verified, in-production way to open a connection: `FalkorDBLiteConnection(get_falkordb_path(), get_falkordb_graph(), get_falkordb_module(), get_redis_bin())`. | The template every script's constructor swap copies — verbatim. | n/a |
| `writ import-markdown` (`writ/cli.py` ingest command) | `writ/cli.py` (the `ingest` flow at ~908-925) | CLI entry that ingests `bible/` into the graph via MERGE (idempotent). | Bootstrap's always-ingest step (D10) calls this. | deep |
| `writ serve` / `writ.server:app` | `writ/server.py` | FastAPI/uvicorn server; opens the embedded DB inside its own process at startup. | Bootstrap and the hook start *only* this — there is no separate DB server. | deep |
| `scripts/export_onnx.py` | `scripts/export_onnx.py` | Exports the ONNX embedding model to `~/.cache/writ/models/onnx/`. | Bootstrap's ONNX step (unchanged, still skip-on-exists). | n/a |
| `scripts/install-harness-config.sh` | `scripts/install-harness-config.sh` | Renders `~/.claude/settings.json` + `CLAUDE.md` from templates. | Bootstrap step 5 (unchanged). | n/a |

---

## Feature overview

Plain-English description of the general logic, happy path first.

**Setup (bootstrap), happy path.** A developer clones onto a fresh Mac and runs `scripts/bootstrap.sh`. The script checks prerequisites — but the list no longer includes Docker; instead it ensures Homebrew's `redis-server` is installed (skipping the install if already present). It downloads the arm64 `vendor/falkordb.so` (`falkordb-macos-arm64v8.so`) from FalkorDB's GitHub releases (skipping if the file already exists); on Intel (`x86_64`) it fails loudly, because no Intel macOS binary is published at v4.14.6 (D9 — Apple-Silicon-only). It creates the Python virtualenv and exports the ONNX model (both skipped if already done), then **always** runs the rule ingest — safe to repeat because it create-or-updates rather than duplicates. It never starts a database container, because there is none: when the ingest step opens a `FalkorDBLiteConnection`, that call launches a private redis-server subprocess with the graph plugin loaded and talks to it over a local socket. The plugin-mode script (`bootstrap-plugin.sh`) does the same, rooted at the plugin's persistent data directory.

**Runtime (the hook).** When a user submits a prompt, the RAG-inject hook checks whether the Writ HTTP server is up. If not, it starts *only* the Writ server (a uvicorn process) — the old block that ran `docker start writ-neo4j` and waited on port 7474 is gone, because the embedded database lives inside that server process and comes up with it. If the server cannot start, the hook still degrades to "server unavailable" and never blocks the prompt.

**The helper scripts.** The ~16 scripts that load rules each currently crash on import — they reference `Neo4jConnection` and `get_neo4j_uri/user/password`, which Phase 1 deleted. Each one swaps to opening a `FalkorDBLiteConnection(get_falkordb_path(), get_falkordb_graph(), get_falkordb_module(), get_redis_bin())`. Scripts that only create-or-count nodes need nothing more. Scripts that previously opened a raw Neo4j session (`db._driver.session(...)`) and ran Cypher by hand have those blocks rewritten to call `_execute_query`, which returns the same `list[dict]` shape the old `record.data()` produced — so the surrounding print/verification logic keeps working.

**How it connects.** `config.py` supplies four values → those become the four constructor args of `FalkorDBLiteConnection` → which (in `db.py`) writes a redis config pointing at the downloaded `vendor/falkordb.so`, spawns redis-server (at the path `get_redis_bin()` returns), and exposes `_execute_query`. Bootstrap's job is to make two of those four inputs real before anything opens a connection: install redis-server so its path resolves, and download the `.so` so the plugin path resolves.

**Edge cases.** (1) Intel Macs are **unsupported** (D9 — Apple-Silicon-only): FalkorDB v4.14.6 publishes no Intel macOS `.so`, so both the `.so` download and the redis-bin resolution fail loudly with an explicit "x86_64 not supported" message rather than the old opaque "Redis failed to start". (2) On a brand-new checkout, `vendor/` does not exist and no connection can open at all until bootstrap downloads the binary. (3) Re-running bootstrap on an existing `.writ/graph.db` must still re-ingest (catches edited rules), but must skip the expensive steps (venv, ONNX, brew, `.so`). (4) If the pinned FalkorDB release URL disappears, bootstrap breaks until the pin is bumped.

---

## Out of scope

- **Test suite adaptation** — the 282 tests are NOT updated here; deferred to **Phase 3** (D7). Phase 2 must not break test *imports*, but no test is edited.
- **Retrieval pipeline (`writ/retrieval/`)** — untouched. Not part of the DB/infra cleanup (CLAUDE.md critical rule, design guardrail G1). *Deferred — never; pipeline is intentionally frozen.*
- **Linux support / cross-platform** — macOS only (D2). No Linux branch is added anywhere. *Deferred — no phase; explicitly dropped.*
- **Hook logic beyond the one Docker block** — only the `docker start writ-neo4j` auto-start block in `writ-rag-inject.sh:44-54` is removed. The RAG/session/escalation/prompt-cleaning logic is unchanged (D7). *Deferred — never; out of mandate.*
- **`.gitignore` changes** — `.writ/` is already ignored (L9). Nothing to do.
- **`pyproject.toml` / Python-version work** — already done (`requires-python = ">=3.12"`, `falkordb>=1.0,<2` pinned, `neo4j` removed). No change here.
- **A shared `scripts/open_db()` factory** — rejected by the design's deletion test (Option E): it would be a pass-through over one 4-arg constructor call. Do NOT introduce one.
- **`falkordb-reference.md`** — stale; describes an API Phase 1 never built (L10). Not edited here; trust the code.
- **`scripts/friction-log-delta.py`** — NOT broken; it imports no `writ.config`/`writ.graph` symbol. Out of scope (design correction; see Assumptions A11). The draft's D8 list and "~16" count include it erroneously.

---

## Constraints

Non-negotiable rules the build must respect, with source.

- **Do NOT modify retrieval pipeline logic** (`writ/retrieval/`) — source: CLAUDE.md "Critical Rules"; design guardrail **G1**. Phase 2 touches only scripts, shell, CI, docstrings, and `db.py`'s `redis_bin` default + the `_coerce` rename.
- **Preserve the 8 key invariants** (`.claude/CODEBASE.md`) — source: CLAUDE.md; guardrail **G2**. No node/edge schema, ranking-weight, or public-method-signature change.
- **No ranking-weight change** (weights must sum to 1.0) — source: CLAUDE.md; guardrail **G5**. Not applicable here, but do not touch `writ.toml [ranking]`.
- **Zero docker/neo4j in `scripts/`, `bin/`, `.claude/hooks/`** (the binding success criterion, P2-INFRA-06) — source: design guardrail **G4**; D7. The grep `grep -rIi 'neo4j\|docker' scripts/ bin/ .claude/hooks/` must return zero hits (migration-comment carve-outs aside).
- **Config tunables live in `writ.toml` with named-constant defaults** (ARCH-CONST-001) — source: `writ/config.py:5,19`. The fixed `redis_bin` default must remain a named `DEFAULT_*` constant, overridable via `writ.toml [falkordb]`.
- **Test imports must not break** — source: guardrail **G3** (D7). Phase 2 may not leave any in-scope module un-importable; test *behavior* adaptation is Phase 3.
- **`_execute_query` is synchronous; public DB methods are `async def`** (landmine **L11**) — source: `db.py:162` (`def`, no `async`) and `db.py:194` (`async def create_rule`). Rewritten scripts must `await` the public method they call but must NOT add `await` in front of `_execute_query` if they call it from inside an already-async context expecting it to be sync. Verify the exact shape against `db.py:162-184` per rewrite.
- **macOS-only** (D2) — no Linux code paths added.

---

## Assumptions

Each is a falsifiable claim tied to a file:line or symbol so research can verify it.

| ID | Assumption | Source implication | What would prove it wrong |
|----|-----------|--------------------|---------------------------|
| A1 | The connection constructor takes exactly **4 positional args** in this order: `db_path, graph, module_path, redis_bin`. | design "constructor takes four args"; verified `db.py:86-92` | `__init__` signature at `db.py:86` shows a different arity/order. |
| A2 | `writ/config.py:47-68` exposes exactly **four** getters: `get_falkordb_path`, `get_falkordb_graph`, `get_falkordb_module`, `get_redis_bin`. | design "four getters"; `config.py:47-68` | A getter is missing or renamed; a fifth exists that the constructor needs. |
| A3 | **16 Python scripts** under `scripts/` import the dead symbols `Neo4jConnection` and/or `get_neo4j_*`. (Design prose says 15; its own per-script audit and the grep both enumerate 16. See OQ-P2-03.) | L1; design Implications | `grep -rln "Neo4jConnection\|get_neo4j" scripts/` returns a different file set. |
| A4 | **3 scripts are constructor-only** (no `_driver`/`_database` use): `migrate.py`, `instrument-cold-start.py`, `profile_hotpath.py`. | design Implications (constructor-only bucket) | Any of the three contains a `db._driver` / `db._database` reference. |
| A5 | **13 scripts open a raw `db._driver.session(...)`** and run hand-written Cypher: the 10 seeders (`seed_phase_1a_injection.py` … `seed_phase_5_process.py`), `export_subagent_roles.py`, `instrument-corpus-stats.py`, and `ingest_subagent_roles.py` (verification block only). | design Implications (query-rewrite + hybrid) | `grep -rln "_driver" scripts/` returns a different set. |
| A6 | `_execute_query` returns `list[dict]` with string keys, matching the old `record.data()` shape, so result-reading lines convert by dict indexing. | design "_execute_query returns same shape"; `db.py:162-184` | `_execute_query` returns tuples/objects, not dicts. |
| A7 | `_execute_query` is **synchronous** (`def`, not `async def`) and the underlying `self._graph.query()` is NOT awaited (the `falkordb` 1.x client is sync). | L11; `db.py:162,169` | `db.py:162` reads `async def` or line 169 has `await`. |
| A8 | `migrate.py`'s broken sites are: 3 module-level `get_neo4j_*()` calls (`:22-24`), 1 `Neo4jConnection(...)` call (`:34`), 2 type hints (`:31,51`). | design "migrate.py (3 constructor sites)" | The grep shows a different layout. |
| A9 | `vendor/falkordb.so` is absent from the repo today; the default `module_path` points at nothing. | L4; `ls vendor/` → absent | `vendor/falkordb.so` exists on disk. |
| A10 | The redis_bin default (`config.py:23` and `db.py:91`) is the Apple-Silicon path `/opt/homebrew/opt/redis/bin/redis-server`. **Resolution is ARM-only (D9):** `shutil.which("redis-server")` → arm64 Homebrew fallback → loud failure. There is no `/usr/local/...` (Intel) fallback — x86_64 is unsupported. | L5; `config.py:23`, `db.py:91` | The default branches to a `/usr/local/...` Intel path, or fails to fail loudly on `x86_64`. |
| A11 | `friction-log-delta.py` imports no `writ.config`/`writ.graph` symbol → not broken, out of scope. | design "friction-log-delta is NOT broken" | `friction-log-delta.py` imports `Neo4jConnection` or `get_neo4j_*`. |
| A12 | `_coerce_neo4j_value` has exactly 3 references, all inside `writ/graph/db.py` (def `:50`, calls `:201,:234`) — the rename is file-local. | design "rename" | A reference to `_coerce_neo4j_value` exists outside `db.py`. |
| A13 | Both bootstrap scripts carry the full Docker/Neo4j flow (prereq check, daemon check, `docker compose up -d neo4j`, bolt-wait loop, banner line, `$COMPOSE_FILE`). | L6; `bootstrap.sh:16,25,59,79-86,147-169,216`, `bootstrap-plugin.sh:18,37,71,92-99,133-155,203` | A bootstrap script has no Docker block. |
| A14 | `ensure-server.sh` has a Neo4j docker block (`:24-47`) and a dangling `$WRIT_DIR/docker-compose.yml` log hint (`:42`). | L8; `ensure-server.sh:24-47` | No Neo4j/docker reference in `ensure-server.sh`. |
| A15 | `writ-rag-inject.sh:44-54` is the only Docker block in the hook; the surrounding logic is independent. | L7; hook `:36-83` | Docker references appear elsewhere in the hook. |
| A16 | `docker-compose.yml` exists at repo root and defines a single `neo4j` service; deleting it dangles `$COMPOSE_FILE` refs in both bootstraps + `ensure-server.sh`. | L8; `docker-compose.yml` present | Compose file absent, or referenced beyond those three shell files. |
| A17 | `.github/workflows/` contains `pr.yml` (delete) and `publish.yml` (keep — no DB dependency). | D3/D4; `ls .github/workflows/` | A different workflow set, or `publish.yml` has a DB dependency. |
| A18 | Neo4j references survive in **five** non-frozen `writ/` files (outside `db.py`'s rename), all docstrings/comments: `authoring.py:27,42`, `compression/abstractions.py:3,63`, `export.py:3,135`, `graph/ingest.py:3`, `graph/schema.py:260,488`. (The design's "only authoring + abstractions" claim was incomplete; research found three more files.) The two refs in `writ/retrieval/` (`traversal.py:1,4,7,26,34`, `pipeline.py:467,507`) are **G1-FROZEN** and explicitly NOT in scope. | verified grep `grep -rni neo4j writ/` | A non-docstring/non-comment code reference to Neo4j exists in any of the five in-scope files, or a sixth non-frozen file is found. |

---

## Component dependency order

Documents what must exist before each component can work — not the order a developer types code. Execution order is owned by `/plan-from-specs`.

### 1. db.py — `redis_bin` default fix + `_coerce` rename
**Goal.** Make the connection resolve redis-server robustly on Apple Silicon (D9 — Apple-Silicon-only), and scrub the last Neo4j name from the DB module — without changing any public method signature.

**Build.** In `writ/graph/db.py` and `writ/config.py`:
- Fix the arch-fragile `redis_bin` default (D9/L5). The default currently hardcodes `/opt/homebrew/opt/redis/bin/redis-server` at `config.py:23` (`DEFAULT_REDIS_BIN`) and `db.py:91`. Replace the static default with runtime resolution in this order (D9, ARM-only): (1) `writ.toml [falkordb] redis_bin` override → (2) `shutil.which("redis-server")` → (3) arm64 Homebrew fallback `/opt/homebrew/opt/redis/bin/redis-server` → (4) loud failure. There is **no** Intel/`x86_64` (`/usr/local/...`) fallback path: on `x86_64`, fail loudly with an explicit "x86_64 not supported (Apple-Silicon-only, D9)" message. Keep it a named `DEFAULT_*`/helper constant (ARCH-CONST-001) and overridable via `writ.toml [falkordb] redis_bin`.
- Rename `_coerce_neo4j_value` → `_coerce_value` at its definition (`db.py:50`) and both call sites (`db.py:201,234`). All 3 references are inside `db.py` (A12) — no other file imports it.

**Depends on.** None.

**Assumes.** A1, A2, A10, A12.

**Decisions.**
- Q: Resolve redis-server via `shutil.which` (dynamic) or a hardcoded path? **RESOLVED (D9, OQ-P2-01):** ARM-only resolution order — `writ.toml` override → `shutil.which("redis-server")` → arm64 Homebrew fallback `/opt/homebrew/opt/redis/bin/redis-server` → loud failure. No x86 fallback; `x86_64` fails loudly (Apple-Silicon-only).

**Done when.** Opening a connection on an Apple-Silicon machine without overriding `redis_bin` in `writ.toml` resolves the correct redis-server (via `which` or the arm64 fallback); on `x86_64` the failure message is explicit ("x86_64 not supported (Apple-Silicon-only)", not an opaque "Redis failed to start"). `grep -rn "_coerce_neo4j_value" writ/` returns zero hits; `grep -rn "_coerce_value" writ/` returns the def + 2 call sites. (P2-INFRA-08)

---

### 2. Constructor-only script fixes (3 scripts)
**Goal.** Resurrect the 3 scripts that only use high-level methods — a one-line import + constructor swap, no query rewrites.

**Build.** For `migrate.py`, `instrument-cold-start.py`, `profile_hotpath.py`:
- Replace `from writ.graph.db import Neo4jConnection` → `from writ.graph.db import FalkorDBLiteConnection`.
- Replace `from writ.config import get_neo4j_password, get_neo4j_uri, get_neo4j_user` → `from writ.config import get_falkordb_path, get_falkordb_graph, get_falkordb_module, get_redis_bin`.
- Replace every `Neo4jConnection(...)` construction with the canonical 4-arg call: `FalkorDBLiteConnection(get_falkordb_path(), get_falkordb_graph(), get_falkordb_module(), get_redis_bin())`.
- Rename `db: Neo4jConnection` type hints → `db: FalkorDBLiteConnection`.
- In `migrate.py` specifically (A8): remove/replace the 3 module-level `get_neo4j_*()` assignments (`:22-24`, which crash at import), the `Neo4jConnection(...)` at `:34`, the 2 type hints (`:31,51`), and scrub the "Migrate Markdown nodes into Neo4j graph" wording in the argparse description (`:57`) so the grep gate passes.

**Depends on.** Component 1 (the constructor it calls must resolve redis correctly on this arch).

**Assumes.** A1, A2, A4, A8.

**Done when.** `python -c "import scripts.migrate"` (and the other two, via their module paths) raises no `ImportError` on `Neo4jConnection`/`get_neo4j_*`; running one of them does not raise `AttributeError` on `db._driver`/`db._database`. No `neo4j` string remains in the three files. (P2-INFRA-05 in part)

---

### 3. Query-body rewrite script fixes (12 scripts)
**Goal.** Resurrect the 12 scripts that reach into the deleted raw Neo4j session API by routing their hand-written Cypher through the existing `_execute_query` bridge — so the surrounding print/verification logic keeps working unchanged.

**Build.** For the 10 seeders (`seed_phase_1a_injection.py` … `seed_phase_5_process.py`), `export_subagent_roles.py`, and `instrument-corpus-stats.py`:
- Apply the same import + constructor swap as Component 2.
- Replace each `async with db._driver.session(database=db._database) as session:` block. The old pattern runs `await session.run(cypher, params)` then reads results via `await result.single()` or `[rec.data() async for rec in result]`. The new pattern calls `db._execute_query(cypher, params)` which returns `list[dict]` directly (A6, A7). Adjust result-reading lines:
  - `[rec.data() async for rec in result]` → the `list[dict]` `_execute_query` already returns.
  - `(await result.single())["col"]` (single-row counts, e.g. `instrument-corpus-stats._count_edges` at `:97-98`, seeder count checks at `seed_phase_1a:308-310`) → index `rows[0]["col"]` from the returned list.
  - existence probes (`await result.single() is not None`, `seed_phase_1a:284-287`) → `bool(rows)`.
- Respect L11 (A7): `_execute_query` is synchronous. Call it without `await`. If the enclosing function must stay `async def` (because it also `await`s `db.close()` or high-level methods), that is fine — only the `_execute_query` call itself is sync. Verify the exact `await` shape against `db.py:162-184` per script.
- Per-script raw-session locations to rewrite (verified): `seed_phase_1a_injection.py:270,276,284,290,308,310` (and the analogous blocks in the other 9 seeders), `export_subagent_roles.py:52-67` (`fetch_roles`), `instrument-corpus-stats.py:86-88` (`_load_rules`) and `:96-98` (`_count_edges`).
- Scrub any remaining "Neo4j" wording in comments/docstrings in these files so the grep gate passes.

**Depends on.** Component 1.

**Assumes.** A1, A2, A5, A6, A7.

**Decisions.**
- Q: Do all 10 seeders share an identical session-block shape, allowing one rewrite template? Options: identical-template / per-seeder-verify. Leaning **per-seeder-verify** (research/plan should diff each seeder's block — `seed_phase_1a` is the reference, but delete-by-id / probe-then-upsert variants may differ). **(Research task.)**

**Done when.** Each of the 12 scripts imports without `ImportError`; running one seeder reports created/updated counts; `export_subagent_roles.py` produces its role list; `instrument-corpus-stats.py` prints node/edge counts — none raise `AttributeError` on `db._driver`/`db._database`. No `neo4j` string remains in the 12 files. (P2-INFRA-05)

---

### 4. Hybrid script fix — `ingest_subagent_roles.py`
**Goal.** Resurrect the one script that already uses a high-level method but has a single raw-session verification block.

**Build.** In `scripts/ingest_subagent_roles.py`:
- Apply the import + constructor swap (Component 2).
- Keep the existing `await db.create_methodology_node("SubagentRole", n)` calls (`:118`) as-is — they already use the high-level API.
- Rewrite the single raw-session verification block (`:124-131`: `db._driver.session(...)` → `session.run(q)` → `[rec.data() async for rec in result]`) to `db._execute_query(q)` returning `list[dict]` (same adjustment as Component 3).

**Depends on.** Component 1.

**Assumes.** A1, A2, A5, A6, A7.

**Done when.** `ingest_subagent_roles.py` imports and runs end-to-end: methodology nodes are created and the verification block prints its row count without touching `db._driver`. No `neo4j` string remains in the file. (P2-INFRA-05)

---

### 5. `writ-rag-inject.sh` — remove the Docker DB-ensure block
**Goal.** Stop the runtime hook from trying to start a Neo4j Docker container on every prompt; the embedded DB now comes up inside `writ serve`.

**Build.** In `.claude/hooks/writ-rag-inject.sh`, delete the Neo4j auto-start block at lines 44-54 (`command -v docker` check, `docker start writ-neo4j`, the port-7474 wait loop) and update the comment at `:36-37` to drop "Neo4j and". Leave everything else — the lockfile dance (`:41-42,72-82`), the `writ serve`/uvicorn start (`:56-70`), the stdin-parse and RAG logic (`:85+`) — exactly as is (D7, A15). The hook must still degrade gracefully ("server unavailable", exit 0) when startup fails.

**Depends on.** None.

**Assumes.** A15.

**Done when.** With Docker absent and the Writ server stopped, submitting a prompt starts only the uvicorn server; `/tmp/writ-rag-debug.log` and the hook output show no `docker start writ-neo4j`; the hook exits 0 and degrades to "server unavailable" if startup fails. (P2-INFRA-07)

---

### 6. `ensure-server.sh` — remove Neo4j/Docker checks
**Goal.** Drop the plugin-init Neo4j-start logic; the embedded DB needs no pre-start.

**Build.** In `scripts/ensure-server.sh`, remove the `NEO4J_PORT` var (`:21`), the `neo4j_running()` function (`:24-27`), the entire "Check Neo4j" block (`:29-47`, including the `docker compose up -d neo4j` and the dangling `docker compose -f $WRIT_DIR/docker-compose.yml logs` hint at `:42` — L8). Keep the Writ-server check/start (`:49-80`) unchanged.

**Depends on.** None (but coordinate the `docker-compose.yml` ref removal with Component 9).

**Assumes.** A14, A16.

**Done when.** `ensure-server.sh` contains no `neo4j`/`docker` reference and still starts the Writ server (or degrades non-fatally). Counts toward P2-INFRA-06.

---

### 7. `stop-server.sh` — scrub the stale Neo4j comment
**Goal.** Cosmetic: remove the only Neo4j mention so the grep gate passes.

**Build.** In `scripts/stop-server.sh`, edit the comment at `:4` ("Does NOT stop Neo4j (it may be shared with other tools).") to drop the Neo4j reference (e.g. remove the line or rephrase to "Does NOT touch the embedded DB."). No logic change.

**Depends on.** None.

**Assumes.** A18 (this is the only stray ref found in `scripts/`).

**Done when.** `grep -i neo4j scripts/stop-server.sh` returns nothing. Counts toward P2-INFRA-06.

---

### 8. `bootstrap.sh` — full rewrite (Redis + .so download + idempotency + always-ingest)
**Goal.** Make the standalone bootstrap run clean on a Docker-free Mac: install Redis via Homebrew, download the DB plugin binary, set up the venv/ONNX, always ingest, start only the Writ daemon.

**Build.** Rewrite `scripts/bootstrap.sh`:
- **Header/comment** (`:1-11`): drop the "brings up Neo4j via docker compose" wording.
- **Tunables** (`:16`): remove `NEO4J_WAIT_SECONDS`; remove `COMPOSE_FILE` (`:25`).
- **Prereqs** (`:59`): remove the `require_tool docker` line; add a step that ensures Homebrew's `redis-server` is installed — `brew list redis` check, `brew install redis` if missing (skip if present, D6). (Keep `python3`, `git`, `envsubst`.)
- **Docker-daemon check** (`:79-86`): delete entirely.
- **`.so` download** (new step, D5/D9): add a loud `x86_64` guard first — if `uname -m` is not `arm64`, fail with an explicit "Apple-Silicon-only (D9); no Intel macOS binary at v4.14.6" message and exit non-zero. If `vendor/falkordb.so` already exists, skip (D6); else download the arm64 asset **unconditionally** from `https://github.com/FalkorDB/FalkorDB/releases/download/v4.14.6/falkordb-macos-arm64v8.so` into `vendor/falkordb.so`. No `uname -m` both-arch branch.
- **venv / deps / ONNX** (`:88-119`): keep, all skip-on-exists (D6).
- **Neo4j compose block** (`:147-169`): delete entirely (the `docker compose up -d neo4j`, bolt-wait loop, and `$COMPOSE_FILE` log hint).
- **Ingest** (`:171-177`): keep but make it **always run** (D10) — do not gate on `.writ/graph.db` existing; it is MERGE-idempotent. Reword the "made it into Neo4j" warning (`:176`).
- **Daemon start** (`:179-206`): keep (starts `writ serve`).
- **Banner** (`:208-222`): remove the `Neo4j : bolt://localhost:7687` line (`:216`); keep the "Writ is ready" banner and daemon URL.

**Depends on.** Components 1–4 (the ingest step opens a connection and runs the fixed ingest path; the connection must resolve redis + find the downloaded `.so`).

**Assumes.** A9, A10, A13, A16.

**Decisions.**
- Q: Resolve redis-server lookup order — does the `brew install redis` step guarantee redis is on PATH before the first connection opens? Options: rely-on-PATH / export-brew-prefix-bin first. Leaning **ensure the brew bin is on PATH before ingest** so `shutil.which` from Component 1 resolves. **(OQ-P2-01.)**
- Q: Exact `.so` asset names for arm64 vs x86_64 at v4.14.6? **RESOLVED (OQ-P2-02, D9):** only arm64 is published — `falkordb-macos-arm64v8.so`. No x86_64 asset exists; download arm64 unconditionally and fail loud on Intel.

**Done when.** On an Apple-Silicon Mac with Docker NOT installed, `scripts/bootstrap.sh` exits 0, prints a "Writ is ready" banner, never calls `docker` or references Neo4j, downloads `vendor/falkordb.so` (the arm64 asset), and leaves `.writ/graph.db` on disk. On `x86_64` it exits non-zero with the explicit Apple-Silicon-only message. A second run with an edited bible rule re-ingests (the edit is queryable afterward) while skipping venv/ONNX/brew/`.so`. (P2-INFRA-01, 03, 04)

---

### 9. `bootstrap-plugin.sh` — same treatment, plugin-rooted
**Goal.** Make the plugin-install bootstrap match Component 8, rooted at the plugin's persistent data dir.

**Build.** Apply the same edits as Component 8 to `scripts/bootstrap-plugin.sh`, preserving its plugin-specific paths (`CLAUDE_PLUGIN_ROOT`/`CLAUDE_PLUGIN_DATA`, venv at `${WRIT_DATA}/.venv`, editable install from `${WRIT_DIR}`):
- Header (`:1-13`): drop "Brings up Neo4j via docker compose".
- Tunables (`:18`), `COMPOSE_FILE` (`:37`): remove.
- Prereqs (`:71`): remove `require_tool docker`; add the brew `redis` ensure step. (Keep `jq`, `curl`, `envsubst`.)
- Docker-daemon check (`:92-99`): delete.
- `.so` download step (new, D5/D9): same as Component 8 — loud `x86_64` guard, then unconditional arm64 download of `falkordb-macos-arm64v8.so` from the v4.14.6 release URL, writing into `${WRIT_DIR}/vendor/falkordb.so`. No `uname -m` both-arch branch.
- Neo4j compose block (`:133-155`, including `$COMPOSE_FILE` log hint at `:153`): delete.
- Ingest (`:157-163`): always-run (D10); reword the "into Neo4j" warning (`:162`).
- Banner (`:198-210`): remove the `Neo4j : bolt://localhost:7687` line (`:203`).

**Depends on.** Components 1–4.

**Assumes.** A9, A10, A13, A16.

**Decisions.** Same OQ-P2-01 / OQ-P2-02 as Component 8 — both RESOLVED (ARM-only resolution order; arm64-only `.so` asset).

**Done when.** With `CLAUDE_PLUGIN_ROOT` set and Docker NOT installed, on Apple Silicon `bootstrap-plugin.sh` exits 0, prints "Writ plugin is ready", makes no docker/Neo4j call, lands the venv at the persistent data dir, downloads the arm64 `.so`, and leaves `.writ/graph.db` on disk. On `x86_64` it exits non-zero with the Apple-Silicon-only message. (P2-INFRA-02)

---

### 10. Delete `docker-compose.yml` + scrub dangling refs
**Goal.** Remove the dead Docker compose file and every reference to it in the same commit, so nothing dangles (L8).

**Build.** Delete `docker-compose.yml` (D4). The only live references to it are the `$COMPOSE_FILE`/compose-file uses in `bootstrap.sh`, `bootstrap-plugin.sh`, and `ensure-server.sh` — all already removed in Components 6, 8, 9. This component is the deletion + a final grep confirming no `docker-compose` reference survives anywhere in `scripts/`/`bin/`/`.claude/hooks/`.

**Depends on.** Components 6, 8, 9 (their ref removals must land first or in the same commit).

**Assumes.** A16.

**Done when.** `docker-compose.yml` no longer exists; `grep -rn "docker-compose\|COMPOSE_FILE" scripts/ bin/ .claude/hooks/` returns nothing. Counts toward P2-INFRA-06.

---

### 11. Delete `.github/workflows/pr.yml`
**Goal.** Remove the Linux/Neo4j CI workflow that is structurally incompatible with the embedded, macOS-only design (D3).

**Build.** Delete `.github/workflows/pr.yml` (runs on Linux with a Neo4j service container). Keep `.github/workflows/publish.yml` — it has no DB dependency (A17).

**Depends on.** None.

**Assumes.** A17.

**Done when.** `.github/workflows/pr.yml` is gone; `.github/workflows/publish.yml` remains untouched.

---

### 12. Docstring scrub — 5 non-frozen `writ/` files
**Goal.** Remove the remaining Neo4j mentions from the **five** non-frozen `writ/` Python files (cosmetic docstrings/comments; not in the grep-gated paths but completes the scrub). Research confirmed three more files beyond the design's named two.

**Build.** Update docstrings/comments only — no logic change in any file (all verified via `grep -rni neo4j writ/`):
- `writ/authoring.py`: `:27` ("Neo4j's MERGE would silently update…") and `:42` ("Fail fast if `rule_id` already exists in Neo4j.") → FalkorDB / the embedded graph.
- `writ/compression/abstractions.py`: `:3` ("Abstraction nodes stored in Neo4j…") and `:63` ("Write Abstraction nodes and ABSTRACTS edges to Neo4j.").
- `writ/export.py`: `:3` ("derived exported view of the canonical Neo4j graph…") and `:135` ("`db`: Neo4j connection.").
- `writ/graph/ingest.py`: `:3` ("the exported view of the canonical Neo4j graph…").
- `writ/graph/schema.py`: `:260` ("Neo4j migration creates a label per node_type…") and `:488` ("Neo4j relationship type matches class name uppercased-with-underscores…").

**G1-frozen carve-out (do NOT touch).** `writ/retrieval/traversal.py` (Neo4j refs at `:1,4,7,26,34`) and `writ/retrieval/pipeline.py` (`:467,507`) are frozen under guardrail G1 (CLAUDE.md critical rule). Their Neo4j mentions are left in place intentionally; they are out of scope for this scrub and any other Phase 2 work.

**Depends on.** None.

**Assumes.** A18.

**Done when.** `grep -rni neo4j writ/authoring.py writ/compression/abstractions.py writ/export.py writ/graph/ingest.py writ/graph/schema.py` returns nothing; the `writ/retrieval/` refs are deliberately untouched; behavior unchanged across all five files.

---

## Handoff notes

- **Contract with Phase 3 (tests):** Phase 2 guarantees every in-scope module imports cleanly and the public DB method signatures are unchanged (only `_coerce_neo4j_value`→`_coerce_value`, a private rename with no external callers — A12). Phase 3 owns adapting the 282 tests; Phase 2 must not have broken their *imports*.
- **Two research blockers — both now RESOLVED (2026-06-20):**
  - **OQ-P2-01** — redis-server resolution order. RESOLVED: ARM-only order `writ.toml` override → `shutil.which("redis-server")` → arm64 Homebrew fallback `/opt/homebrew/opt/redis/bin/redis-server` → loud failure; bootstrap's `brew install redis` precedes the first connection (ingest), so `which` resolves. The fix lives in Component 1, the guarantee in bootstrap (Components 8/9). No x86 fallback.
  - **OQ-P2-02** — `vendor/falkordb.so` GitHub release asset at FalkorDB **v4.14.6**. RESOLVED: only the arm64 asset `falkordb-macos-arm64v8.so` is published; no Intel macOS `.so` exists. D9 = Apple-Silicon-only — download arm64 unconditionally, fail loud on `x86_64`.
- **Open uncertainty — the 15-vs-16 script count.** The design prose says "15 broken scripts" but its own per-script audit and the verified grep both enumerate **16** (3 constructor-only + 12 query-rewrite + 1 hybrid; `friction-log-delta.py` excluded because it imports nothing). This spec treats **16** as the build target (A3). See OQ-P2-03 below.
- **Suggested research:** diff all 10 seeder session-blocks against the `seed_phase_1a` reference — they likely share a shape but may carry delete-by-id / probe-then-upsert variants that need individual handling (Component 3 Decision).
- **Sequencing note for `/plan`:** Component 1 (constructor redis fix) gates Components 2–4 and 8–9; Components 6/8/9 must land with or before Component 10 (compose delete) to avoid a dangling-ref window. Components 5, 7, 11, 12 are independent.

## Open questions (carried forward + new)

- **OQ-P2-01** (from design) — **RESOLVED.** Redis-server is resolved at runtime in this order (ARM-only): `writ.toml [falkordb] redis_bin` override → `shutil.which("redis-server")` → arm64 Homebrew fallback `/opt/homebrew/opt/redis/bin/redis-server` → loud failure. Bootstrap's `brew install redis` step precedes the first connection (the ingest step), so `shutil.which` resolves before any connection opens. No x86 fallback.
- **OQ-P2-02** (from design) — **RESOLVED.** FalkorDB v4.14.6 publishes only the arm64 macOS module asset `falkordb-macos-arm64v8.so` (`https://github.com/FalkorDB/FalkorDB/releases/download/v4.14.6/falkordb-macos-arm64v8.so`). No Intel/x86_64 macOS `.so` exists at this pin → D9 resolves to **Apple-Silicon-only**: download arm64 unconditionally, fail loud on `x86_64`.
- **OQ-P2-03** (new, raised by this spec) — Authoritative broken-script count: design prose says 15, but the verified grep + the design's own per-script audit enumerate **16**. This spec builds for 16. Confirm with the design author whether one script (which?) was intentionally excluded, or whether "15" is a prose slip. Does not block the build — fixing all 16 importers is strictly required for P2-INFRA-05 ("no ImportError") to pass.
