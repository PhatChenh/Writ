# Design: Phase 2 — Infrastructure Cleanup

> Produced 2026-06-20. Inputs: locked decisions D1–D10 (`docs/AI_artifacts/0_draft/phase2-decisions.md`), full code read via CodeGraph, direct reads of all shell/CI/script files.
> Behavior-inventory ID prefix for this phase: **`P2-INFRA`** (Phase 1 defined no prefix; none inherited).

---

## Cast of characters (project symbols referenced 3+ times)

| Symbol | Plain-English role |
|--------|--------------------|
| `FalkorDBLiteConnection` | The embedded-DB connection object; launches a local redis-server with the graph module and runs Cypher. |
| `_execute_query(cypher, params)` | The one low-level method that runs a query and returns rows as a list of dictionaries. |
| `_driver.session()` | The OLD Neo4j way of opening a query session. No longer exists — any script using it is broken. |
| `get_falkordb_path()` / `get_falkordb_graph()` / `get_falkordb_module()` / `get_redis_bin()` | The four config getters that supply the connection's four constructor arguments. |
| `create_rule` / `create_methodology_node` | High-level DB methods that create-or-update a node without writing raw Cypher. |
| `redis_bin` | Path to the redis-server executable the connection launches. |
| `vendor/falkordb.so` | The graph-database plugin binary the connection loads at startup. |

---

## In plain terms

Phase 1 already swapped the database engine inside the main `writ/` package, but it left the *plumbing around it* still wired for the old Docker-based Neo4j: the setup scripts, the continuous-integration config, and roughly a dozen helper scripts that load rules into the database. Today those helper scripts are simply broken — they import names that Phase 1 deleted, so they crash on the first line. Phase 2 finishes the job: it rewrites the setup so a fresh Mac can go from clone to running with one command and no Docker, fixes every broken helper script, removes the leftover Docker/Neo4j references, and deletes the dead Docker and CI files. Nothing about *what rules get retrieved or how they rank* changes — only how the project is set up and operated.

---

## Decision

**Chosen approach:** Per-script DB-talk gets rewritten to match what each script actually does — cheap constructor-only swaps where the script only uses high-level methods, and query-body rewrites (via `_execute_query`) only where a script reaches into the dead Neo4j session API. Architecture handling (D9) uses runtime binary resolution (`shutil.which`) with an arm64 Homebrew fallback, and downloads the arm64 `vendor/falkordb.so` (`falkordb-macos-arm64v8.so`) unconditionally; on Intel (`x86_64`) it fails loudly, because FalkorDB v4.14.6 publishes no Intel macOS binary — D9 resolves to Apple-Silicon-only. The setup scripts and the runtime hook drop their "start the database server" blocks entirely, because the embedded database has no separate server to start — opening a `FalkorDBLiteConnection` *is* starting it.

- One sentence why: it is the lowest-risk path that honors every locked decision (D1–D10) while staying within the cheap-cost gate D9 set, and it matches the established Phase-1 pattern (`_execute_query` as the single bridge for raw-session sites).

---

## What happens inside (chosen option, no diagram)

When a developer clones the repo onto a fresh Mac and runs `scripts/bootstrap.sh`, the script first checks prerequisites — but the list no longer includes Docker; instead it ensures Homebrew's `redis-server` is installed (skipping the install if already present). It downloads the arm64 `vendor/falkordb.so` (`falkordb-macos-arm64v8.so`) from FalkorDB's GitHub releases (skipping if the file already exists), failing loudly on Intel (`x86_64`) since no Intel macOS binary is published at v4.14.6, creates the Python virtual environment and exports the ONNX model (both skipped if already done), and then *always* runs the rule ingest — which is safe to repeat because it create-or-updates rather than duplicates. It never starts a database container, because there is no container: when the ingest step opens a `FalkorDBLiteConnection`, that call launches a private redis-server subprocess with the graph module loaded and talks to it over a local socket. The plugin-mode script (`bootstrap-plugin.sh`) does the same, just rooted at the plugin's persistent data directory.

At runtime, when a user submits a prompt, the RAG-inject hook checks whether the Writ HTTP server is up. If not, it starts only the Writ server (a Python/uvicorn process) — the old block that ran `docker start writ-neo4j` is gone, because the embedded database lives *inside* that server process and comes up with it. If the server cannot start, the hook still degrades gracefully to "server unavailable" and never blocks the user's prompt.

The dozen-plus helper scripts that load rules each open a `FalkorDBLiteConnection(get_falkordb_path(), get_falkordb_graph(), get_falkordb_module(), get_redis_bin())` instead of the deleted `Neo4jConnection(...)`. Scripts that only create or count nodes are otherwise untouched; scripts that previously opened a raw Neo4j session and ran Cypher by hand have those query blocks rewritten to call `_execute_query`, which returns the same list-of-dictionaries shape the old `record.data()` produced — so the surrounding print/verification logic keeps working.

---

## Guardrail Checklist

**No `docs/CONSTRAINTS.md` exists** in this repo, and there is no `DEBTS_CONSTRAINTS.md` to migrate, so a formal constraint-card review could not run. Per the guardrail-check Review-mode stop rule, no cards were invented. The spec writer should treat the following project-native rules as the danger checklist instead (sourced from `CLAUDE.md` "Critical Rules" and the decisions doc "Done When"):

- [ ] **G1 · Do not modify retrieval pipeline logic** (`writ/retrieval/`) — satisfied: Phase 2 touches only scripts, shell, CI, docstrings, and `db.py`'s `redis_bin` default + a rename. No pipeline file is in scope.
- [ ] **G2 · Preserve the 8 key invariants** (`.claude/CODEBASE.md`) — satisfied: no node/edge schema, ranking-weight, or public-method-signature change.
- [ ] **G3 · 282 tests remain the correctness contract** — deferred to Phase 3 by D7; Phase 2 must not break the test *imports*, but test adaptation is explicitly out of scope.
- [ ] **G4 · "Zero docker/neo4j in scripts/ bin/ hooks/"** — the binding success criterion; every option is checked against it below.
- [ ] **G5 · Ranking weights must sum to 1.0** — not applicable (no ranking change).

If the spec writer wants these mechanically enforced, the natural place is the `grep -rIi 'neo4j\|docker'` gate (criterion P2-INFRA-06) wired into a pre-commit or `make` target.

---

## Implications

- **The helper scripts are not "being swapped" — they are being resurrected.** They have been dead since Phase 1 merged; anyone who ran one got an immediate crash. Phase 2 is the first time they will work against the new database.
  - All 16 import the two deleted symbols: `Neo4jConnection` (from `writ.graph.db`) and `get_neo4j_uri/user/password` (from `writ.config`). Confirms **L1**.

- **The real connection constructor takes four positional arguments, not the two the decisions doc implies.** Any fix that passes only path + graph will be missing the module path and redis binary path.
  - Pattern (verified at `writ/cli.py:912`, `writ/server.py:143`): `FalkorDBLiteConnection(get_falkordb_path(), get_falkordb_graph(), get_falkordb_module(), get_redis_bin())`. The getter is `get_falkordb_path()`, confirming **L2**, and `writ/config.py:47–68` exposes **four** getters — the decisions doc named only three. **[Correction to scope text, see Risks.]**

- **Only some scripts need real query rewrites; most need a one-line constructor change.** Telling them apart up front prevents over-engineering the cheap ones and under-budgeting the expensive ones. Confirms **L3**.
  - **Constructor-only (cheap)** — no `_driver`/`_database` use: `migrate.py` (3 constructor sites), `instrument-cold-start.py`, `profile_hotpath.py`. Swap the import + constructor; rename the `db: Neo4jConnection` type hints.
  - **Query-body rewrite (via `_execute_query`)** — these open `db._driver.session(...)` and call `session.run(...)` + `await result.single()` / `[rec.data() async for rec in result]`: the 10 seeders (`seed_phase_1a_injection.py` … `seed_phase_5_process.py`), `export_subagent_roles.py` (its `fetch_roles`), and `instrument-corpus-stats.py` (two helpers: `_load_rules`, `_count_edges`).
  - **Hybrid** — `ingest_subagent_roles.py` already uses the high-level `db.create_methodology_node(...)` (keep as-is) but has ONE raw `_driver.session()` verification block that needs the `_execute_query` rewrite.

- **`friction-log-delta.py` is NOT broken and is out of scope.** It is a pure log-diffing tool with no `writ.config`/`writ.graph` import at all — it never appears in the broken-import set. D8's bullet list erroneously slotted it among the instrumentation scripts to fix; excluding it, the verified count of broken scripts is **16** (3 constructor-only + 12 query-rewrite + 1 hybrid). **[Correction — see Risks.]**

- **The database binary the connection needs does not exist on disk today.** A fresh checkout cannot open a connection at all until bootstrap downloads it. Confirms **L4**.
  - `vendor/` is absent (verified: `ls vendor/` → "No such file or directory"); the default `module_path="vendor/falkordb.so"` points at nothing. D5's download is mandatory, not a nicety.

- **The redis-server path default assumes an Apple-Silicon Mac.** On an Intel Mac it silently points at the wrong location, and the failure mode is an opaque "Redis failed to start." Confirms **L5**.
  - `writ/config.py:23` and `writ/graph/db.py:91` both default to `/opt/homebrew/opt/redis/bin/redis-server`; Intel Homebrew uses `/usr/local/...`.

- **There are two bootstrap scripts and both carry the full Docker/Neo4j flow.** Fixing only the standalone one leaves "zero Docker" false on plugin install. Confirms **L6**.
  - `scripts/bootstrap.sh` (lines 16, 25, 59, 79–86, 147–169, 216) and `scripts/bootstrap-plugin.sh` (lines 18, 37, 71, 92–99, 133–155, 203) each have prerequisite checks, a daemon-reachable check, a `docker compose up -d neo4j` block, a bolt-port wait loop, and a banner line.

- **The runtime hook starts a Docker container on every prompt.** This is the most user-visible Docker dependency and the one that breaks the "embedded" promise during normal use. Confirms **L7**.
  - `.claude/hooks/writ-rag-inject.sh:36–54` runs `docker start writ-neo4j` and waits on `http://localhost:7474` inside the server-auto-start block. Only this block is touched; the surrounding RAG/session/escalation logic stays unchanged (D7 "hook logic out of scope").

- **Deleting `docker-compose.yml` will dangle live references unless scrubbed at the same time.** Confirms **L8**.
  - `bootstrap.sh:25` and `:167` reference `$COMPOSE_FILE`; `bootstrap-plugin.sh:37` and `:135,153`; `ensure-server.sh:42` prints a `docker compose -f .../docker-compose.yml logs` hint. All vanish when the Docker blocks are removed.

- **`.writ/` is already gitignored — nothing to do there.** Confirms **L9** (the decisions doc already drops it from scope).

- **The old reference doc describes an API Phase 1 never built — trust the code.** Confirms **L10**.
  - `falkordb-reference.md` describes `AsyncFalkorDB` / positional tuples / `pip install falkordblite`; the real code (`db.py`) uses a synchronous `FalkorDB(unix_socket_path=...)` client wrapped in async methods, `_execute_query` returns `list[dict]`, and `pyproject.toml:44` pins `falkordb>=1.0,<2`. **The methods are `async def` but call the sync client directly — they do not `await` the query** (see new landmine L11).

- **The dependency and Python-version work is already done.** No `pyproject.toml` change is needed in Phase 2.
  - `pyproject.toml:6` is `requires-python = ">=3.12"`; deps already list `falkordb` / `falkordb>=1.0,<2`. The `neo4j` dependency is already gone.

- **The CI `pr.yml` is structurally incompatible with the embedded, macOS-only design.** It runs on Linux with a Neo4j service container; D2 (macOS-only) and D3 (delete pr.yml) settle this. `publish.yml` has no DB dependency and stays.

### Module depth note
This phase deepens no module and creates no new module boundary. `_execute_query` is an existing, already-deep seam (small interface — one method; large implementation — the only place that understands the DB result format) with 20+ adapters across the codebase. Routing the resurrected scripts through it is the correct use of an existing seam, not a new abstraction. The deletion test for any *new* helper (e.g. a shared `open_db()` factory for the scripts) fails: it would be a pass-through over a one-line constructor call, so the design does NOT introduce one.

---

## Success criteria

Written to `behavior_inventory.yaml` (repo root) as entries **P2-INFRA-01 … P2-INFRA-08**, `origin: design`, `granularity: outcome`, `status: planned`. They cover: both bootstraps run clean without Docker (01, 02), the `.so` downloads and the connection opens (03), re-run re-ingests edits (04), all 16 scripts import and run (05), the zero-docker/neo4j grep gate (06), the hook no longer starts a container (07), and arch-correct redis resolution (08).

---

## Known tradeoffs

- **macOS-only, by decision.** Dropping Linux/CI (D2/D3) means there is no automated check that the project still builds on a clean machine other than the single developer's Mac. We trade cross-platform safety for radical local simplicity. Reversible later by restoring `pr.yml` from git history.
- **Auto-download pins one binary version.** Bootstrap fetches FalkorDB `v4.14.6` (D5). If that release URL ever disappears, bootstrap breaks until the pin is bumped. We trade a small future-maintenance touch for zero manual setup steps today.
- **Always-ingest costs a sub-second re-load on every bootstrap run.** We trade a tiny, predictable cost for never silently missing an edited rule (D10).
- **Query rewrites are mechanical but not free.** The 12 raw-session scripts each need their Cypher moved into `_execute_query` calls and their result-reading lines adjusted from async-record iteration to dict indexing. Lower-risk than touching pipeline code, but more than a find-replace.

---

## Risks

- **The decisions-doc scope text under-specifies the constructor (3 args vs the real 4) and its D8 bullet miscounts the scripts (it lists `friction-log-delta.py`, which is not broken).** The spec and plan must use the verified four-arg constructor and the verified 16-script list (excluding `friction-log-delta.py`, which was never in the broken set). Watch for a copy-pasted three-arg fix.
- **NEW landmine L11 — the async methods call a synchronous client.** `FalkorDBLiteConnection` methods are `async def` but `_execute_query` calls `self._graph.query(...)` *without* `await` (the `falkordb` 1.x client used here is synchronous). The rewritten scripts must call `await db._execute_query(...)` (the method is async) but must NOT expect the underlying query to yield control — there is no event-loop concurrency benefit. This differs from the Phase-1 *design doc's* sketch, which showed `await self._graph.query(...)`. The shipped code does not await it. Verify the exact `await`/non-`await` shape against `db.py:162–184` when writing each rewrite.
- **`shutil.which('redis-server')` returns nothing unless Homebrew's bin is on PATH.** D9's runtime resolution must run *after* the brew-install step in bootstrap, or fall back to the arch-derived path. Research should confirm the resolution order.
- **The `.so` download URL scheme for both arches must be verified against the actual FalkorDB v4.14.6 release assets** before the plan commits to a URL template (research task).
- **D9 RESOLVED to Apple-Silicon-only (research, 2026-06-20):** FalkorDB v4.14.6 publishes only the arm64 macOS module `falkordb-macos-arm64v8.so` — there is no Intel macOS `.so` at this pin. Bootstrap downloads the arm64 asset unconditionally and fails loudly on `x86_64`; the `uname -m` both-arch branch is dropped, and redis-bin resolution has no `/usr/local/...` Intel fallback.
- **Deleting `docker-compose.yml` and `pr.yml` is irreversible in the working tree** (recoverable from git history). Both are explicitly approved by D3/D4, so no separate sign-off is needed, but the implementer should delete and scrub the dangling references in the same commit (L8).

---

## Open questions

**OQ-P2-01 — How should the redis-server binary path be resolved at runtime?**

Right now the connection assumes one fixed location that only exists on Apple-Silicon Macs; on an Intel Mac it points at the wrong place and fails with an unclear error.

The question: should the default resolve the binary dynamically (look it up on the system PATH) or branch on the chip type with two hardcoded paths?

**If dynamic lookup (`shutil.which`):** one line, works on any Mac that has redis-server installed and on PATH, but returns nothing if PATH is not set up — so bootstrap must guarantee PATH before the first connection.
**If chip-type branch:** explicit and predictable, but bakes in two Homebrew-specific paths and breaks for anyone using a non-Homebrew redis.

Recommendation: dynamic lookup with the arch-derived Homebrew path as a fallback. It is the cheapest path that works for both chips without assuming where redis lives, which is what D9's cost-gate asks for.

**OQ-P2-02 — Exact download URL and asset names for `vendor/falkordb.so` per architecture.**

Right now the binary is not in the repo and must be fetched, but the precise GitHub release asset names for ARM64 vs x86_64 at v4.14.6 are not yet confirmed.

The question: do FalkorDB's v4.14.6 release assets include separate, predictably-named macOS ARM64 and x86_64 `.so` files?

**If yes:** the single `uname -m` branch in D9 is genuinely cheap and both arches are supported.
**If no (e.g. only ARM64 published, or a tarball):** fall back to Apple-Silicon-only with a loud Intel error, per D9's cost-gate.

Recommendation: defer to research to read the actual release page. This is the one fact that decides whether D9 ships both-arch or Apple-Silicon-only.

---

## ADR references

No ADR written. The two hard-to-reverse choices (delete `docker-compose.yml`, delete `pr.yml`) are pre-locked by D3/D4 and are not surprising given the "remove Docker" mandate — they fail the "surprising without context" gate. If the spec writer disagrees, the candidate ADR would be "Drop Linux CI and Docker entirely (macOS-only embedded DB)."

---

## Options explored

- **Option A — Per-script tailored rewrite + `shutil.which` + drop server-start blocks (CHOSEN).** Matches each script to its real DB usage, resolves the binary at runtime, and removes the now-meaningless "start the DB" blocks. Lowest risk, honors D1–D10, stays inside D9's cost gate.
- **Option B — Route every script through high-level methods only.** Rejected: the seeders do bespoke things (delete-by-id, existence-probe-then-upsert, count sanity checks) that have no single high-level method; forcing them through `create_rule` would lose the delete/probe behavior or require new methods — a bigger change than `_execute_query` rewrites.
- **Option C — Apple-Silicon-only, hardcode the ARM path (skip D9 both-arch).** Rejected unless OQ-P2-02 forces it: D9 prefers both arches *if cheap*, and a single `uname -m` branch is cheap; defaulting to ARM-only without checking the release assets would discard a near-free win and re-bake the L5 fragility.
- **Option D — Keep `pr.yml`, retarget it to macOS runners with embedded DB.** Rejected: contradicts D3 (delete pr.yml) and D2 (macOS-only, no CI); macOS GitHub runners are scarce/slow and the single-dev rationale makes CI net-negative.
- **Option E — Add a shared `scripts/_db.py open_db()` factory.** Rejected on the deletion test: it would be a pass-through wrapper over a single four-arg constructor call, a shallow module that adds an indirection without removing complexity.

---

## Next step

Design doc written. Run `/architecture-docs` to update the main architecture designs, then `/writing-detailed-specs` to structure the chosen option into build steps. Research must resolve OQ-P2-01 and OQ-P2-02 (binary URL + redis resolution order) before the plan commits to exact commands.
