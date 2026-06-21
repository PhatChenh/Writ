# 01 — Architecture and Data Flow

> **Refresh note (2026-05-10).** This document was first written when the live corpus held 73 rules / 11 mandatory and 33 hook scripts. Phase 1-5 of the public-rulebook expansion (commits 516b963 → db0a367) brought the corpus to **276 rules / 30 mandatory**, and a separate cleanup pass deleted 3 legacy hooks (`check-gate-approval.sh`, `enforce-final-gate.sh`, `writ-pretool-rag.sh`) leaving **30 hook scripts**. `HANDBOOK.md` and `README.md` are the canonical sources for current counts and latency numbers. Where this doc differs in counts, defer to those. Architecture and data-flow descriptions below remain accurate.

## 1. System overview

**Writ is the full Claude Code harness in this repository.** It is not a single service. The repo composes two co-equal layers plus a canonical data store:

- **Knowledge layer** — the `writ/` Python package, served via FastAPI on `localhost:8765`. This is the part that is a hybrid-RAG service: it answers "what rules apply to this context?" via the five-stage pipeline. Stateless w.r.t. workflow.
- **Enforcement layer** — `bin/lib/writ-session.py` (the session/mode/gate state machine, ~2,090 lines) plus 30 hook scripts under `.claude/hooks/`, plus slash commands under `.claude/commands/`, plus sub-agent role definitions under `.claude/agents/`, wired through Claude Code via `templates/settings.json`. Owns mode state, phase state, gate criteria, file classification, audit trail. Hooks are thin clients that delegate decisions to `writ-session.py`.
- **Canonical store** — Neo4j (running in Docker via `docker-compose.yml`, image `neo4j:5`, bolt on `localhost:7687`). Single source of truth for rules, methodology nodes, and edges. The hybrid-RAG indexes (Tantivy BM25, hnswlib HNSW, adjacency cache) are all built **from Neo4j** at server startup and served from memory. Runtime queries hit those in-memory indexes; they do not hit Neo4j directly except in Stage 4 fallbacks (which are not on the hot path).

`bible/` is **not** a runtime data source. Per `writ.toml [source]` (`canonical = "neo4j"`, `exported_view = "bible/"`) and `writ/graph/ingest.py`'s module docstring: `bible/*.md` is the human-readable exported view of the canonical Neo4j graph, used for first-time bootstrap ingestion (`writ import-markdown bible/`) and as a re-export target after edits (`writ export bible/` or auto-export after `writ add` / `writ edit`). It is closer to a `dist/` artifact than to a database — derived, not authoritative.

Together these layers replace the two failure modes that motivated Writ:
- **Context-stuffing all rules every turn** — token cost scales linearly (1.17 M tokens per turn at 10K rules). Writ swaps in sub-millisecond ranked retrieval (0.557 ms p95 at 10K rules) plus a separate always-on bundle for safety-critical rules that cannot be ranked away.
- **Static skill files describing a process without enforcing it** — the model can read "always write tests first" and produce the implementation first because nothing stopped it. Writ ties enforcement to the tool-call boundary via mode + gate state, so writes are denied until the discipline is satisfied.

The five-stage pipeline (handbook §4.1):

```
Query text
  Stage 1: Domain Filter            < 1 ms     domain-scoped corpus
  Stage 2: BM25 keyword (Tantivy)   < 2 ms     top 50 candidates
  Stage 3: ANN vector (hnswlib)     < 3 ms     top 10 candidates
  Stage 4: Graph traversal          < 3 ms     enriched with neighbors
            (pre-computed adjacency cache)
  Stage 5: Ranking & return         < 1 ms     two-pass RRF, context budget applied
                                      total p95 budget < 10 ms
```

Mandatory rules (originally just `ENF-*`; now also `SEC-INJ-*`, `SEC-AUTH-*`, `SEC-AUTHZ-*`, `SEC-VAL-*`, `SEC-CRYPTO-*`, `SEC-DATA-PII-001`, `PERF-QUERY-001`, `SCALE-STATELESS-001` per Phase 1-5) are excluded from the pipeline before Stage 1 and loaded out-of-band by hooks (handbook §7.5: "It is a hard filter at Stage 1 of the pipeline. Mandatory rules are excluded before BM25 scoring begins").

## 2. End-to-end query trace

Concrete trace from "user types prompt" to "RAG block injected":

1. User submits a prompt in Claude Code.
2. **Claude Code fires `UserPromptSubmit`**.
3. **`writ-rag-inject.sh`** (registered in `~/.claude/settings.json`) runs:
   - Parses stdin envelope via `bin/lib/parse-hook-stdin.py`.
   - Reads session cache (mode, loaded rule IDs by phase, remaining budget, context-pressure flag) from `bin/lib/writ-session.py`.
   - If mode is unset, emits a mode-classification directive (deny-to-ask path; gate hooks block all writes except `plan.md` until a mode is set).
   - If mode is set and `budget_tokens > 0` and prompt length >= 10 chars and context pressure < 75%, POSTs to the local service.
4. **`auto-approve-gate.sh`** detects approval patterns ("approved" by itself), creates the gate token at `/tmp/writ-gate-token-{sid}`, emits a directive steering Claude to `/writ-approve` slash command. The slash command then POSTs to `/session/{sid}/advance-phase` with the matching token.
5. **HTTP**: `POST http://localhost:8765/query` with body `{query, domain?, scope?, budget_tokens, exclude_rule_ids, loaded_rule_ids}`. httpx async client, 50 ms fallback timeout.
6. **`writ/server.py`** (FastAPI/uvicorn, async): receives the request, calls `pipeline.query(query_text, ...)`.
7. **`writ/retrieval/pipeline.py`** runs the five stages:
   - **Stage 1 — Domain filter**: post-filter by `domain` if provided. Mandatory rules pre-excluded at index build time.
   - **Stage 2 — BM25**: `pipeline._keyword.search(q, limit=50)` against in-process Tantivy index built from `trigger + statement + tags` (with `TRIGGER_BOOST=2.0`). Returns up to 50 `(rule_id, bm25_score)`.
   - **Stage 3 — ANN vector**: `pipeline._model.encode(q)` (ONNX `all-MiniLM-L6-v2` with LRU cache `maxsize=1024`) then `pipeline._vector.search(qv, k=10)` against in-process hnswlib index (`ef_search=50`).
   - **Stage 4 — Graph traversal**: union the BM25 + vector candidate IDs; for each, `pipeline._cache.get_enrichment([id])` returns 1-hop and 2-hop neighbors from the pre-computed adjacency dictionary (built once at startup from Neo4j; ~50 ms at 80 rules, ~500 ms at 10K).
   - **Stage 5 — Ranking** (`writ/retrieval/ranking.py`):
     - Pass 1: `score = 0.198*bm25_norm + 0.594*vector_norm + 0.099*severity + 0.099*confidence`. Weights tuned over two rounds against the 83-query ground-truth set.
     - Pass 2: graph proximity (weight 0.01) seeded from top-3 of pass 1, but only seeded by `human` or `ai-promoted` rules (`ai-provisional` excluded).
     - Authority preference: human rules outrank AI rules at equal relevance (hard rerank, not weight; threshold 0.0749 by default 0.0).
     - Confidence graduation: rules whose frequency counters meet the bar (n>=50, ratio>=0.75) are scored using empirical ratio.
     - `apply_context_budget`: clips to summary mode (<2K tokens), standard (2K-8K, top 5), or full (>8K, top 10).
8. Server returns JSON `{rules, mode, total_candidates, latency_ms}`.
9. Hook receives response, formats via `bin/lib/writ-session.py format`, emits a single `--- WRIT RULES ---` block to stdout (Claude Code injects into the next inference call).
10. Hook updates session cache: appends returned `rule_id`s to `loaded_rule_ids[<current_phase>]`, decrements `budget_tokens` by token cost.
11. **Friction logging**: `Stop` hooks record gate denials, phase transitions, hook timing, rule-effectiveness signals.
12. **PostToolUse RAG**: when the agent writes a file in Work mode, `writ-pre-write-dispatch.sh` (consolidated successor to the legacy `writ-pretool-rag.sh`) and `writ-posttool-rag.sh` re-query the pipeline with file context for additional file-specific rules. These also fire inside sub-agents.

Sub-agent variant: `writ-subagent-start.sh` fires on `SubagentStart`, creates an isolated session cache keyed on `agent_id`, with `is_subagent: true` set. Phase-A and test-skeletons gates do not apply. Each sub-agent gets a fresh 8000-token RAG budget.

## 3. Component diagram

```
                       ~/.claude/CLAUDE.md (global instructions, memory tier list)
                                          |
                                          v
+-----------------------------------------+----------------------------------------+
|  Claude Code  (LLM agent runtime)                                                 |
|     | UserPromptSubmit, PreToolUse(Write|Edit|ExitPlanMode|Read),                  |
|     |   PostToolUse(Write|Edit|Bash), Stop, SubagentStart, SubagentStop            |
|     v                                                                             |
|  Hooks layer  (.claude/hooks/*.sh, registered in ~/.claude/settings.json)          |
|    writ-rag-inject.sh, auto-approve-gate.sh, writ-pre-write-dispatch.sh,           |
|    pre-validate-file.sh, validate-exit-plan.sh, validate-rules.sh,                 |
|    inject-tier-workflow.sh, validate-file.sh, validate-handoff.sh,                 |
|    friction-logger.sh, writ-context-tracker.sh, writ-posttool-rag.sh,              |
|    writ-read-rag.sh, writ-subagent-start.sh, writ-subagent-stop.sh,                |
|    writ-quality-judge.sh, ... (30 hooks total)                                     |
|     |                                                                              |
|     | shell helpers:                                                               |
|     |   bin/lib/parse-hook-stdin.py     (normalize stdin envelope)                  |
|     |   bin/lib/writ-session.py         (mode/gate/phase state machine)             |
|     |   bin/lib/gate-categories.json    (file classification)                       |
|     |   bin/lib/checklists.json         (phase exit criteria)                       |
|     |   bin/run-analysis.sh             (PHPStan/ESLint/ruff/xmllint/cargo/govet)   |
|     v                                                                              |
|  HTTP boundary (httpx, ~50 ms fallback timeout)                                    |
+------------------------------+----------------------------------------------------+
                               |
                               v
+------------------------------+-----------------------------------+
|  Writ server  (writ/server.py, FastAPI, uvicorn, async)           |
|    /query    /propose    /feedback    /rule/{id}    /conflicts    |
|    /always-on    /subagent-role/{name}    /pre-write-check        |
|    /health    /dashboard    /analyze    /session/* (~25 routes)   |
+------------+----------------------+-------------------+-----------+
             |                      |                   |
             v                      v                   v
   Pipeline (Stages 2-5)     Authoring + Gate      Frequency / Authority
   writ/retrieval/*          writ/authoring.py     writ/frequency.py
                             writ/gate.py          writ/origin_context
                             writ/export.py
             |                                          |
             v                                          v
  +----------+-------------+    +---------+----+   +-----+--------+
  | Tantivy index (BM25)   |    | hnswlib HNSW |   | Adjacency    |
  | in-process, pre-warmed |    | in-process,  |   | cache        |
  | from Rule.{trigger,    |    | 384-d ONNX   |   | dict[id] ->  |
  |   statement,tags}      |    | embeddings   |   |   neighbors  |
  +------------------------+    +--------------+   +------+-------+
                                                          |
                                                          v
                                          +---------------+----+
                                          | Neo4j (bolt 7687)  |
                                          | source of truth    |
                                          | Rule, Abstraction, |
                                          | + 10 methodology   |
                                          | node types,        |
                                          | + 17 edge types    |
                                          +--------------------+
```

## 4. The graph model

Rules and methodology nodes live in Neo4j. Doc 02 carries the full schema; high-level shape:

**Original node types:** Rule, Abstraction, Domain, Evidence, Tag.

**Methodology node types added in Phase 6:** Skill (`SKL-`), Playbook (`PBK-`), Technique (`TEC-`), AntiPattern (`ANT-`), ForbiddenResponse (`FRB-`), Phase (`PHA-`), Rationalization (`RAT-`), PressureScenario (`PSC-`), WorkedExample (`EXM-`), SubagentRole (`ROL-`). Of these, Skill / Playbook / Technique / AntiPattern / ForbiddenResponse are retrievable; Phase / Rationalization / PressureScenario / WorkedExample / SubagentRole are non-retrievable (surface only via Stage-4 graph traversal as bundle members).

**Edge types** — driver-level allowlist `ALLOWED_EDGE_TYPES` in `writ/graph/db.py:40-47` lists 17:
- Existing 9: `DEPENDS_ON`, `PRECEDES`, `CONFLICTS_WITH`, `SUPPLEMENTS`, `SUPERSEDES`, `RELATED_TO`, `APPLIES_TO`, `ABSTRACTS`, `JUSTIFIED_BY`.
- Phase 1 additions (8): `TEACHES`, `COUNTERS`, `DEMONSTRATES`, `DISPATCHES`, `GATES`, `PRESSURE_TESTS`, `CONTAINS`, `ATTACHED_TO`.

(Note: `docs/phase-0-schema-proposal.md` reconciles to 14 expected — 6 existing + 8 new — but the driver allowlist contains 17. Defer to doc 02 for the authoritative schema-vs-driver count.)

Rule node required fields: `rule_id`, `domain`, `severity`, `scope`, `trigger`, `statement`, `violation`, `pass_example`, `enforcement`, `rationale`, plus graph-only `mandatory`, `confidence`, `evidence`, `staleness_window`, `last_validated`. Phase 6 added `always_on`, `mechanical_enforcement_path`, `rationalization_counters`, `red_flag_thoughts`, `source_attribution`, `source_commit`, `body`.

## 5. The hybrid retrieval philosophy

Direct quote from handbook §12 ("Hybrid retrieval"):

> Combining multiple retrieval methods (keyword search + vector search + graph traversal) and fusing their results. No single method is sufficient: BM25 misses semantic matches ("SQL" vs "database query"), vectors miss exact keyword matches, and neither understands rule relationships.

Each retriever covers a blind spot the others have:
- **BM25** catches exact keyword matches (`controller`, `SQL`) but misses paraphrases.
- **Vector** catches paraphrases via cosine similarity but misses exact-keyword exact-match cases.
- **Graph traversal** catches rules that share neither keyword nor semantic similarity but are causally related.
- **Two-pass RRF ranking** fuses signals via reciprocal rank, working even when scores are on different scales.

(Note: ranking.py's `normalize_ranks` is plain reciprocal rank `1/(rank+1)`, not classical RRF `1/(k+rank)`. There is no `k` constant. Module docstrings call it RRF but it's reciprocal-rank + weighted linear fusion. See doc 03.)

## 6. Pre-computation philosophy

Direct quote from handbook §1.2:

> KEY INSIGHT: The secret sauce is not raw speed. It is pre-computation. Nothing is calculated at query time that could have been calculated at ingestion time. The graph, the embeddings, the BM25 index, and the abstraction node summaries are all pre-built. Retrieval serves from memory.

Concretely:
- **Tantivy BM25 index** built from Neo4j Rule nodes at `writ serve` startup (in-memory by default — `KeywordIndex()` is constructed with no `index_dir`). The on-disk corpus is Neo4j; ingestion of rules into Neo4j happens via `writ import-markdown` (initial bootstrap from `bible/`) or `writ add` / `writ edit` / `POST /propose` (incremental).
- **hnswlib HNSW vector index** built at startup; persisted to `~/.cache/writ/hnsw/{writ_hnsw.bin, writ_hnsw.json}` with SHA-256 corpus hash invalidation.
- **ONNX embedding model** loaded once; query encoding uses an LRU cache (`maxsize=1024`).
- **Adjacency cache (Stage 4)** built at startup by reading every edge from Neo4j into a Python dict. Lookup is O(1) — "0.002ms" vs Neo4j live Cypher's "6ms+".
- **Abstraction summaries** generated by `writ compress` (HDBSCAN/k-means + centroid-nearest summary, no LLM) and stored as graph nodes.

## 7. Mandatory vs retrieved rule split

From handbook §7.5 ("Status: Closed"):

> The retrieval pipeline is not authoritative for which rules the AI sees. It is authoritative for domain-specific technical rules only. A separate mandatory rule set always loads into agent context regardless of retrieval ranking, query content, or context budget.

> If `ENF-GATE-001` is subject to retrieval ranking and the ranking algorithm does not surface it for a given query, the AI proceeds as if no gate exists, writes a file, and gets blocked by the hook.

Mechanism:
- Rules with `mandatory: true` carry a graph property that excludes them from the candidate set before Stage 1.
- Never BM25-indexed, never embedded, never ranked.
- Loaded out-of-band by hooks via `/always-on` endpoint, with own independent budget cap (`always_on_budget` default 5000 tokens).
- `/always-on` returns `always_on=true` rules + all `FRB-*` ForbiddenResponse nodes.

A 2026-04-21 audit classified the original 35 ENF rules: 15 had viable mechanical-enforcement paths, 2 were Phase 2.5 candidates, 18 were recommended for demotion. The 2026-05-10 cleanup acted on that audit (pruning the corpus to 11 mandatory ENF-* rules). Phase 1-5 then added 19 new mandatory public-rulebook rules, each backed by a mechanical analyzer in `bin/run-analysis.sh`:

| Phase | Mandatory rules added | Analyzer function |
|---|---|---|
| 1A Injection | SEC-INJ-SQL-001, XSS-001, CMD-001, SSRF-001, DESER-001, CSRF-001 | `analyze_security_injection` |
| 1B Auth+AuthZ+Val | SEC-AUTH-HASH-001, TOKEN-001; SEC-AUTHZ-ENFORCE-001, IDOR-001, DEFAULT-001, MASS-001; SEC-VAL-SERVER-001, FILE-001 | `analyze_security_auth_authz` |
| 1C Crypto | SEC-CRYPTO-KEY-001, RAND-001 | `analyze_security_crypto_headers` |
| 1D Data | SEC-DATA-PII-001 | `analyze_security_data_protection` |
| 3B Performance | PERF-QUERY-001 (N+1) | `analyze_performance_n_plus_one` |
| 4 Scaling | SCALE-STATELESS-001 | `analyze_scaling_stateless` |

Total mandatory: **30** (11 original ENF-* + 19 new public-rulebook rules).

## 8. Sub-agent architecture

From `~/.claude/skills/writ/rules/writ-orchestrator.md`:

- `is_subagent: true` set in cache by `writ-subagent-start.sh` on `SubagentStart`. Phase-A / test-skeletons gates do not apply.
- Each sub-agent gets its own session cache keyed on `agent_id`, fresh 8000-token RAG budget (or unlimited if `subagent_budget: null` in `budget.json`).
- PostToolUse RAG fires inside sub-agents; rule injection on every file write.
- The orchestrator master session sets Work mode with `--orchestrator`, which sets `is_orchestrator: true`. `writ-rag-inject.sh` then suppresses the broad ~1400-token RAG injection on every UserPromptSubmit and emits a compact status line instead.
- Workers run in foreground (sequential) by design: each worker's output gates the next phase.

## 9. The "Dwarf in the Glass" evolution model

Operational legs:
1. **AI proposes via gate** — AI agents discover rule-shaped patterns mid-task and submit via `POST /propose`. The structural pre-filter (`writ/gate.py`) runs five checks: schema, mechanical-enforcement (if mandatory), specificity, redundancy/novelty, conflict. Surviving rules enter the graph as `authority: ai-provisional`, `confidence: speculative`.
2. **Frequency drives graduation** — automatic feedback from the Stop hook correlates which rules were in context with static-analysis pass/fail and posts to `/feedback`, incrementing `times_seen_positive` / `times_seen_negative`. `writ/frequency.py:evaluate_graduation` graduates a rule when `n = positive + negative >= 50` and `positive/n >= 0.75`.
3. **Human approves authority promotion** — `writ review` lists, inspects, promotes (to `ai-promoted`, `peer-reviewed`), rejects, or downweights. Human rules outrank AI rules at equal relevance.

**Note (now reconciled)**: earlier handbook revisions and CODEBASE.md described the graduation logic as "Wilson CI" / "Wilson confidence interval analysis". The actual code in `writ/frequency.py:41-53` computes a plain ratio `times_positive / (times_positive + times_negative) >= 0.75` — there is no Wilson CI computation. HANDBOOK.md has since been corrected to drop the Wilson framing.

## 10. Sub-agent role definitions

From `.claude/agents/writ-*.md`:

| Sub-agent | Model | Tools | Role | When dispatched |
|---|---|---|---|---|
| `writ-explorer` | sonnet | Read, Glob, Grep, Bash | Read-only codebase-exploration. Reports framework, directory layout, namespace conventions, similar existing modules. | Phase 1 (before planning). |
| `writ-planner` | opus | Read, Glob, Grep, Write | Designs implementation plans. Writes `plan.md` and `capabilities.md` to project root. | Phase 2; consumes explorer output. |
| `writ-test-writer` | sonnet | Read, Glob, Grep, Write, Bash | Writes test skeleton files with method signatures, mock setup, specific assertions. | Phase 3, after plan approval. |
| `writ-implementer` | opus | Read, Glob, Grep, Write, Edit, Bash | Writes all production code per plan, ordered: registration/config → API/DTO → model → business logic → frontend/admin. Updates `capabilities.md`. | Phase 4, after test-skeleton approval. |
| `writ-plan-reviewer` | haiku | Read, Glob, Grep, Bash | Reviews diff for plan compliance only. Strict JSON output. Runs *before* code-quality review (the SDD review-order rule enforces this via `writ-sdd-review-order.sh`). | First reviewer. |
| `writ-code-quality-reviewer` | sonnet | Read, Glob, Grep, Bash | Reviews diff for correctness, safety, readability, project conventions, rule violations. Severity: Critical (block merge), Important (should fix), Minor (nit). | Second reviewer, after plan-compliance passes. |

The orchestrator dispatches workers in foreground sequentially. Workers bypass mode/gate checks entirely; they do not set a mode.

## 11. Document references / handbook navigation map

Many of the original navigation targets (`docs/phase-0-*.md`, `docs/phase-2-self-review-decision.md`, `docs/phase-6-plan.md`, `docs/mandatory-rule-audit.md`, `docs/evolution-reference.md`, `docs/integration.md`, `docs/plan-format.md`, `bin/verify-matrix.sh`) were deleted in the 2026-05-10 cleanup. The remaining canonical pointers:

| Topic | Primary doc & section | Supporting docs |
|---|---|---|
| Vision, problem statement | `HANDBOOK.md` §1 | `README.md` "The problem" |
| Rule schema, enforceability | `HANDBOOK.md` §2 | doc 02, doc 07 |
| Graph node + edge taxonomy | `HANDBOOK.md` §3 | doc 02 |
| Five-stage pipeline, ranking, ground-truth, context budget | `HANDBOOK.md` §4 | doc 03, `tests/fixtures/ground_truth_queries.json` |
| Runtime requirements, deps, embedding model | `HANDBOOK.md` §5 | doc 09, `docs/install-writ.md` |
| Project structure, CLI commands | `HANDBOOK.md` §6 | doc 04 |
| HTTP API, fallback, session state, mandatory vs retrieved | `HANDBOOK.md` §7 | doc 05, doc 06, doc 12 |
| Performance targets, measurement | `HANDBOOK.md` "By the numbers" | doc 08, `SCALE_BENCHMARK_RESULTS.md` |
| Technology decision rationale | `HANDBOOK.md` (architecture section) | -- |
| Glossary | `HANDBOOK.md` (glossary section) | -- |
| Hooks inventory + roles | `HANDBOOK.md` | doc 06 |
| Mode system, gate criteria, phase model | `HANDBOOK.md`, Methodology node `SKL-PROC-MODE-001`, `SKL-PROC-WRIT-FAILURE-001` | doc 06, doc 12 |
| Sub-agent orchestration | Methodology node `PBK-PROC-ORCHESTRATOR-001` | `.claude/agents/writ-*.md`, doc 12 |
| Authority + frequency model | `HANDBOOK.md` (mandatory-rule section) | doc 11, `writ/frequency.py`, `writ/authoring.py` |
| Public out-of-the-box rulebook (220 rules across 12 domains) | `out-of-the-box-rules.md` | doc 07 |
| Monthly review cadence | `CONTRIBUTING.md`, `docs/monthly-reviews/TEMPLATE.md` | `docs/monthly-reviews/2026-05.md` |
| Install / settings sync | `docs/install-writ.md`, `README.md` | doc 09, `scripts/bootstrap.sh` |

## 12. Discrepancies catalog (code wins)

Several entries from the original draft have been resolved by code changes; surviving discrepancies are flagged below.

- **Wilson CI** — resolved. HANDBOOK.md no longer claims Wilson CI; code uses a plain ratio threshold (`writ/frequency.py:28-53`).
- **Edge type count** — driver allowlist in `writ/graph/db.py:40-47` contains 17 types (9 original + 8 Phase-1 additions). The `APPLIES_TO`, `ABSTRACTS`, `JUSTIFIED_BY` types are present in the allowlist but lack dedicated Pydantic write paths (see doc 02 §11.1).
- **Latency numbers** — live measurement as of 2026-05-10 against the 276-rule post-expansion corpus: E2E p95 = 0.590 ms, median = 0.338 ms (10 representative queries × 50 iterations). See `SCALE_BENCHMARK_RESULTS.md` for synthetic curve.
- **Hooks count** — 30 wired hooks; `templates/settings.json` is authoritative.
- **Test counts** — 1,455 tests collected as of 2026-05-10 (was ~320 pre-hardening; growth from v2/v3 hardening and Phase 6 methodology absorption).
- **Gate phases** — `gate-categories.json` still defines phase-b/c/d categories. `_can_write_check` in writ-session.py uses only `phase-a` + `test-skeletons`. The category-level rules are a holdover, not enforced by v2.
- **`abstractions=` parameter** — resolved. The pipeline now passes abstractions through to `apply_context_budget` (see `writ/retrieval/pipeline.py::query` and `build_pipeline`).
- **`compute_confidence_weight`** — resolved. Now invoked from `compute_score` in `writ/retrieval/ranking.py`.
- **`Abstraction.abstraction_id` uniqueness constraint** — resolved. Constraint added in `writ/graph/db.py::apply_constraints`.
- **`mechanical_enforcement_path`** — required by gate Check 1b for any `mandatory: true` rule. All 30 current mandatory rules satisfy this (the original 11 ENF-* rules point at hook files; the 19 new public-rulebook mandatory rules point at the 6 analyzers in `bin/run-analysis.sh`).

## Files Read (original 2026-05 extraction pass)

- `benchmarks/bench_targets.py`, `run_benchmarks.py`, `scale_benchmark.py`, `methodology_bench.py`
- `SCALE_BENCHMARK_RESULTS.md`, the architecture handbook (now `HANDBOOK.md`, originally ~934 lines as `RAG_arch_handbook.md`), `README.md`, `SKILL.md`, `CONTRIBUTING.md`
- `docs/install-writ.md` and the now-deleted planning artifacts (`evolution-reference.md`, `integration.md`, `mandatory-rule-audit.md`, `phase-0-report.md`, `phase-0-schema-proposal.md`, `phase-2-self-review-decision.md`, `phase-6-plan.md`, `plan-format.md`)
- `docs/monthly-reviews/2026-05.md`, `TEMPLATE.md`
- `.claude/agents/writ-{explorer,planner,test-writer,implementer,plan-reviewer,code-quality-reviewer}.md`

Spot-check: `writ/frequency.py` (plain ratio, no Wilson CI).

## Cross-References Noted

- All 12 extraction documents in `extraction/` cover specific facets in detail; this doc is the navigation map.
- Test counts and phase status drift between docs — see Discrepancy Catalog above.
- Phase-6 sub-phase status: 6e/6f/6g were file-system-only promotions; live Neo4j ingestion was added 2026-05-09 via `writ import-markdown bible/` (50 new-type + 10 methodology-Rule nodes, 120 edges).
