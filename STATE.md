# Writ (Forked) — Project State

_Last updated: 2026-06-21_

## Current Position

**Phase 4 — Workflow Adaptation: 🔵 IN PROGRESS (grill/design stage, NO code yet).** Operating mode locked: this repo is a **vendored fork in adapt-and-learn mode** — do NOT develop new features into Writ; adapt it + rewire our own skills/hooks. **All Phase 4 rationale + decisions live in `WRIT-LOCAL-ADAPTATION.md` (repo root) — READ FIRST.**

Three decisions locked (2026-06-21):
- **D4-01 · Graph-canonical authoring.** Graph is canonical; `bible/*.md` = derived committed export, never hand-edited. No more hand-maintained CONSTRAINTS/ADR/TECH_DEBT flat docs — input skills write into the graph. A new rule is invisible to `writ query` until daemon **re-warm** (not until bible export).
- **D4-02 · Per-repo isolation "A-auto."** Upstream Writ = one global daemon/graph (contamination by default; no "project" concept in schema). Isolate at storage: deterministic per-repo port + daemon CWD=repo root + on-demand auto-start. Safe because `db.py:106` keys the redis socket on the ABSOLUTE db dir. Work = 3 edits to `.claude/hooks/writ-rag-inject.sh` (NOT yet done), no Writ-core change.
- **D4-03 · Adopt full mode system + Work mode, skill-driven auto-switch (NEW this session).** REVERSES the earlier "stay out of Work mode" lean — we now opt INTO all modes (conversation/debug/review/work + prototype) and arm the Work-gated blockers (L3). Mode switching = deterministic, each skill sets mode on entry (`/grill`→conversation, `/build-pipeline` implement→work, `/code-review`→review, `/tdd-implement`→work); NOT a heuristic prompt classifier. **Gate-overlap direction LOCKED: Writ's plan→test→code gate machine REPLACES our HITL + /build-pipeline plan/test gates** (Writ = mechanical lock, build-pipeline = content). Full record in WRIT-LOCAL-ADAPTATION.md §D4-03.

**In-flight thread (next AI picks up here):** 4D hook walkthrough **COMPLETE** — all 33 hooks decided. **Final tally: 31 keep ✅ / 2 drop ❌** (dropped: auto-approve-gate, inject-tier-workflow). The Decision ledger in WRIT-LOCAL-ADAPTATION.md is now a **per-hook review table** (6 group tables: Decision · What it does verified-from-code · Your reasoning · My reasoning/pending) — each row carries the rationale. **Also added this session:** full Writ graph-schema appendix (13 node types / 17 edge types / Rule fields). **Next:** either (a) start the pending edits (see list below — implementation), or (b) continue Phase 4 design on 4A/4B/4C (constraints/ADR/tech-debt → graph node mapping), 4E-4G, and plugin activation scope. Confirm with user which.

**Walkthrough rules of engagement (how to run 4D — learned this session):** (a) cover **only hooks the user annotated** in the appendix Note column — skip un-noted ones (honor their table `y`/`n`). (b) **Read the actual hook .sh / server code BEFORE explaining** — user rejected hand-waving twice; the deny/allow logic for gates lives server-side (`writ/server.py` `/pre-write-check` → `bin/lib/writ-session.py` `_can_write_check`), not in the hook. (c) ONE hook at a time, not by group. (d) user gives the verdict; AI writes it into the ledger **verbatim + a one-line rationale**, never pre-decides. (e) caveman mode on; **do NOT recite the 5-Principles** (user waived for the session). (f) this is still **walkthrough/decision**, not implementation — do not start the pending edits unless told.

**Pending edits queued by the locks (NONE done yet — all deferred):** (1) D4-02 A-auto: 3 edits to `writ-rag-inject.sh`. (2) D4-03: wire `mode set` into our skill entry points. (3) Retire our HITL/`/build-pipeline` plan+test gates in favor of Writ's. (4) Merge `/build-pipeline` plan format ↔ Writ `plan.md` sections (`## Files`/`## Analysis`/`## Rules Applied`/`## Capabilities`) — both solid, cross-learn. (5) Review flow: merge methodology into reviewer agent prompts (writ-spec-reviewer / writ-code-quality-reviewer) + keep a lightweight orchestrator skill (repurpose `/review-implementation`) that dispatches spec→quality in order and records via `POST /session/{sid}/review-ordering`. (6) Walk remaining overlapping gates (validate-test-file, validate-design-doc) before locking the layer. (7) **CodeGraph-aware test/review enhancement (deferred dev build):** enhance `bin/lib/test_paths.py` so writ-run-pending-tests uses `codegraph_callers`/`codegraph_explore` to compute the blast radius of each edit (all affected sources+tests), then (a) run that holistic affected set and (b) inject a directive for the main thread to dispatch a subagent for precision review of the affected places. Heavier than config — real new behavior; cap transitive sets. (8) Adapt validate-design-doc path+sections to `docs/AI_artifacts/{1_design,2_specs,3_research,4_plans}` templates; adapt validate-handoff to our markdown /handoff; adapt validate-test-file conventions to /tdd-implement.

- **Phase 1 — Core Storage Swap:** ✅ done (merged `6b5ef23`). Neo4j → FalkorDBLite embedded graph DB.
- **Phase 2 — Infrastructure Cleanup:** ✅ done. 16 broken scripts fixed; bootstraps rewritten;
  docker-compose.yml deleted; hook Docker block removed; docstrings scrubbed.
- **Phase 3 — Test Suite Green:** ✅ done. Shared conftest fixtures + 33 files migrated + benchmarks +
  production/doc carryover scrubs + final gate.

## Phase 3 — plan summary

Artifacts: `docs/AI_artifacts/{0_draft,1_design,2_specs,3_research,4_plans}/phase3-test-suite-green.md`.
Success criteria: `behavior_inventory.yaml` → `P3-TEST-01..07`.

**Locked decisions:**
- **Scope grew 13 → 33 files** (tests/ + benchmarks/). Roadmap's "13" undercounted; research found
  4 more in `benchmarks/` (bench_targets, methodology_bench, run_benchmarks, scale_benchmark).
- **Fixture = Option A:** one **session-scoped** `FalkorDBLiteConnection` in `conftest.py` on a
  **throwaway temp dir** + function-scoped autouse `clear_all` + one shared `db()` fixture.
  Replaces ~10 duplicated per-file `db()` fixtures.
- **DB access = real, not mocks.** Exercises real Cypher. Mock-only family (`test_authority.py`,
  `test_analysis.py`) stays UNTOUCHED.
- **D9/D10 — Phase-2-carryover scrubs folded in:** `hooks/scripts/session-start-bootstrap.sh`
  (prod hook still had live Neo4j:7687 + docker compose), `writ-architecture-flowchart.html`
  (stale "Neo4j" as current pipeline stage + its test term), delete `falkordb-reference.md`.
- **Research: 22 validated / 0 invalidated / 0 unverifiable.** No hard stop.
- `_StubNeo4jSession` = dead code → delete. `IntegrityChecker(db)` single-arg.
  `test_integrity` needs `skip_redundancy=True`. `test_post_suite` was silently `pytest.skip`-ing.

## Next Up

**[Phase 3 — Test Suite Green — IMPLEMENTED 2026-06-20]**:
- [x] Phase 0 — delete `falkordb-reference.md`
- [x] Phase 1 — **DE-RISK GATE:** build conftest fixtures + smoke test, proven green
- [x] Phase 2 — config full rewrite (`test_config` + `test_config_integration`) incl. x86_64 RuntimeError
- [x] Phase 3 — top-level db() fixtures (5 files)
- [x] Phase 4 — class-nested fixtures (2 files)
- [x] Phase 5 — integrity (single-arg `IntegrityChecker(db)` + `skip_redundancy=True`)
- [x] Phase 6 — inline swaps, post-suite rename+repoint, import-markdown REAL rewrite, delete `_StubNeo4jSession`
- [x] Phase 7 — D9/D10 assertion realignment + prod `session-start-bootstrap.sh` scrub (human sign-off) + flowchart doc
- [x] Phase 8 — benchmark migration (4 files, two-arg `IntegrityChecker` fix)
- [x] Phase 9 — Full gate: core 189+ tests green, `grep -ri neo4j tests/ benchmarks/` zero wiring hits, lock-collision check

**Implementation complete 2026-06-20.** ONNX-dependent tests (~14) and SKILL_DIR tests have pre-existing failures unrelated to the Neo4j→FalkorDB migration.

## Post-Phase-3 cleanup + verification (2026-06-20)

Cleanup pass after Phase 3. All work below complete:

- **ONNX model exported** → `~/.cache/writ/models/onnx/model.onnx` (86MB). Unblocks the ~14 ONNX-dependent tests (now pass). **Gotcha:** `scripts/export_onnx.py` hangs on an HF Hub network probe even when the source model is fully cached — run with `HF_HUB_OFFLINE=1 TRANSFORMERS_OFFLINE=1` to force offline.
- **Live end-to-end verified.** `writ query` returns ranked results (Mode: full, ~6ms). Graph holds **332 nodes / 11 labels** (276 Rule + methodology) and **174 edges / 10 types**. FalkorDB storage + 5-stage retrieval fully functional.
- **Cosmetic Neo4j scrub done.** All non-load-bearing "Neo4j" docstrings/comments removed from `writ/` (incl. G1-frozen `retrieval/`, with sign-off), `tests/`, `benchmarks/`. 3 load-bearing refs intentionally kept: `test_bootstrap.py:41` (historical deletion note), `test_session_start_bootstrap.py` (names what must be ABSENT), `ground_truth_queries.json:325` (NL query test data).
- **OPEN_QUESTIONS.md reconciled** — OQ-01..04 verified resolved in code, marked ✅.

### Real test counts (corrected — prior "~28 SKILL_DIR" was a large undercount)

Full `pytest tests/`: **1315 passed, 64 skipped, 268 failed, 107 errors** → **375 non-passing total.**
- **All DB/migration/retrieval files: 100% green** (infrastructure, ingest, integrity, export, compression, config, config_integration, authoring, retrieval, graph_proximity, embeddings, session — 145 + 76 = 221 verified pass).
- **Breakdown of the 375 (none are DB/retrieval):**
  - **296** cite `FileNotFoundError: ~/.claude/skills/writ/...` directly — the Writ **plugin/skill is not installed** in this dev checkout.
  - **~79** are the same plugin axis under different assertions: installed-layout file-existence (`templates/CLAUDE.md`/`README.md`/`pyproject.toml`/`bin/writ` "must exist"), settings-wiring (`settings.json must grant Bash permission for writ-*.sh`), install-script runs (`install-harness-config.sh` non-zero, `claude plugin validate exited 1`), and bible corpus-content/vocabulary-migration checks (`Scope: entity` migration, methodology-node existence).
- To green them: install the plugin via `scripts/bootstrap-plugin.sh` (writes to `~/.claude/skills/writ`, starts the daemon). **Deferred to Phase 4** — separate axis from "FalkorDB works," and it modifies the shared `~/.claude` dir.

**Stray dev artifacts:** dozens of empty `/tmp/writ-*` temp dirs from prior test runs remain (harmless). Orphan redis-server processes from earlier runs were killed this session.

**Implementation-time sign-offs (in plan):** OQ-6 (prod hook edit), OQ-7 (HTML), OQ-8 (import-markdown), OQ-2 (credential-scan).

## Phase 3 — deviations from plan

1. **Phase 1 gate** — couldn't co-run smoke test with `test_graph_proximity.py`/`test_authoring.py` (they can't import deleted `get_neo4j_*`). Gate satisfied by smoke test proving session+function scope coexistence. Loop-safety is an A8 property of `db.py` (sync client).

2. **Subagent B modified `writ/graph/db.py`** — 3 FalkorDB fixes (traverse_neighbors BFS, list_constraints/indexes output normalization, get_abstraction Node→dict). Plan said "no production source changes" except D10 carryovers. These were load-bearing for the migrated tests to pass.

3. **`vendor/falkordb.so`** — downloaded manually + `chmod +x`. Bootstrap prerequisite (`envsubst`) not met in this env. The `.so` is gitignored and needs execute permission.

4. **~30 cosmetic "Neo4j" docstring references** remain in test files (class names, docstrings, comments). Phase 7a scrub list didn't include files migrated by Subagent B. Not wiring — purely cosmetic. Deferred to a follow-up cleanup pass.

5. **Full `pytest` suite times out** — multiple Redis subprocess startups (~5s each) make a single invocation impractical. Core suite verified in batches (189+ pass). Sufficient for confidence; CI with `pytest-xdist` would need per-worker temp dirs.

6. **~42 pre-existing failures** — ONNX model not exported (~14 errors in test_authoring/test_graph_proximity/test_retrieval/test_session) and SKILL_DIR `~/.claude/skills/writ` not installed (~28 failures/errors). Unrelated to migration.

## Key decisions / notes

- **A8 loop-safety CONSTRAINT.** Session-scoped test DB is event-loop-safe ONLY because `db.py`
  async methods wrap a SYNC `_execute_query` (no asyncio primitives, never binds a loop). A future
  async-redis refactor would silently reintroduce "attached to a different loop" failures. → TECH_DEBT.
- **D9 (scope-rule refinement).** "No changed assertions" = don't change assertions verifying
  *still-valid* behavior; DO realign assertions that test *deleted* Docker/Neo4j behavior.
- **D9 → Apple-Silicon-only.** FalkorDB v4.14.6 has no Intel macOS module; bootstrap fails on `x86_64`.
- **Deferred** (Phase 2 carryover): frozen `writ/retrieval/` Neo4j docstrings (G1) — no test asserts
  them clean, so no Phase 3 conflict; Intel support.
