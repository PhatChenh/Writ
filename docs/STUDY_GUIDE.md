# Writ Study Guide

A structured learning path for understanding how Writ works, why it was built this way, and how to modify it. Designed to be used with an AI coaching agent — the agent reads this guide and walks you through each level at your pace.

---

## How to use this guide

Each level builds on the previous. Don't skip ahead — concepts compound. For each level:
1. **Read** the listed docs
2. **Explore** the suggested code/files
3. **Check understanding** by answering the questions (coach should quiz you)
4. **Optional hands-on** exercises to solidify understanding

Estimated total: ~6-8 hours across all levels. Do one level per session.

---

## Level 1 — What Writ is and why it exists

**Goal:** Understand the two problems Writ solves and the user experience.

### Read these (in order):
1. `HANDBOOK.md` §"What Writ is" through §"What you experience when you use it" (lines 1-53) — the clearest 2-minute overview
2. `README.md` — the public-facing explanation, covers install + usage
3. Open `writ-complete-overview.html` in a browser — visual overview of the entire system

### Key concepts to understand:
- **Context stuffing problem** — why pasting all rules every turn fails at scale (1.17M tokens at 10K rules)
- **Process enforcement problem** — why static skill files can't enforce workflow
- **Librarian** — the retrieval half (which rules matter right now?)
- **Process Keeper** — the enforcement half (is the AI allowed to do this right now?)
- **Modes** — Discussion / Debug / Review / Work. Only Work mode has gates

### Check understanding:
- Why can't you just put all rules in CLAUDE.md?
- What's the difference between a mode and a phase?
- What happens when Claude tries to write code before a plan exists?

---

## Level 2 — Architecture: the three layers

**Goal:** Understand how the three layers (knowledge, enforcement, data store) interact.

### Read these:
1. `docs/extraction/01-architecture-and-data-flow.md` — system overview + end-to-end query trace
2. `.claude/CODEBASE.md` — module map with lines/role/load-bearing flags
3. Open `writ-architecture-flowchart.html` in a browser — visual architecture diagram

### Key concepts:
- **Knowledge layer** = `writ/` Python package, FastAPI on localhost:8765
- **Enforcement layer** = `bin/lib/writ-session.py` (~2,090 lines) + 33 hooks + agents + commands
- **Canonical store** = Neo4j (→ FalkorDBLite in our fork)
- **bible/ is NOT a runtime data source** — it's an exported view, like `dist/`
- In-memory indexes (Tantivy, hnswlib, adjacency cache) are built FROM the graph DB at startup

### Explore these files:
- `writ/server.py` — FastAPI endpoints, the HTTP boundary
- `bin/lib/writ-session.py` — the state machine (big file, skim the class structure)
- `.claude/hooks/writ-rag-inject.sh` — the hook that triggers retrieval on every user prompt

### Check understanding:
- Trace a user prompt from submission to rule injection (the full path through hooks → HTTP → pipeline → response)
- Which layer owns mode/phase state?
- Why are mandatory rules excluded from the pipeline?

---

## Level 3 — The retrieval pipeline (the brain)

**Goal:** Understand the 5-stage hybrid RAG pipeline in detail.

### Read these:
1. `docs/extraction/03-retrieval-pipeline.md` (639 lines) — deep dive on all 5 stages
2. `HANDBOOK.md` §"The five-stage pipeline" — the measured numbers
3. `SCALE_BENCHMARK_RESULTS.md` — what happens at 1K, 5K, 10K rules
4. `writ.toml` `[ranking]` section — the actual weight values

### Explore these files (read the code):
- `writ/retrieval/pipeline.py` (346 lines) — orchestrator, all 5 stages
- `writ/retrieval/ranking.py` (292 lines) — RRF scoring, authority preference, context budget
- `writ/retrieval/embeddings.py` (226 lines) — ONNX model, hnswlib vector store
- `writ/retrieval/keyword.py` (96 lines) — Tantivy BM25 wrapper
- `writ/retrieval/traversal.py` (109 lines) — adjacency cache, graph proximity

### Key concepts:
- **Stage 1: Domain filter** — post-filter, scopes to relevant domain
- **Stage 2: BM25 keyword** — Tantivy, top-50 candidates by text match
- **Stage 3: ANN vector** — hnswlib + ONNX embeddings, top-10 by semantic similarity
- **Stage 4: Graph traversal** — pre-computed adjacency cache (1-hop, 2-hop neighbors)
- **Stage 5: Two-pass RRF ranking** — weighted score (0.198 BM25 + 0.594 vector + 0.099 severity + 0.099 confidence + 0.01 graph), then graph proximity + authority preference + context budget
- **No I/O in hot path** — all indexes pre-warmed in memory at startup
- **Authority hard preference** — human rules outrank AI rules at equal relevance (threshold 0.0749)
- **Context budget** — limits total tokens returned (8,000 standard, 2,000 summary)

### Check understanding:
- Why is vector weighted 3x more than BM25?
- What does "authority hard preference" mean concretely? What's the threshold?
- Why must ranking weights sum to 1.0?
- What happens if you change the embedding model?

---

## Level 4 — The graph: rules, edges, and evolution

**Goal:** Understand rule schema, graph structure, and how rules evolve.

### Read these:
1. `docs/extraction/02-graph-and-storage.md` (684 lines) — graph schema deep dive
2. `docs/extraction/07-rule-schema-and-validation.md` — rule format and field constraints
3. `docs/extraction/11-evolution-and-authority.md` — confidence tiers, graduation, deprecation
4. Browse `bible/security/` and `bible/testing/` — read 3-4 actual rules to see the format

### Explore these files:
- `writ/graph/schema.py` (216 lines) — Pydantic models for all 12 node types, 10 edge types
- `writ/graph/ingest.py` (152 lines) — markdown parser, field validation
- `writ/graph/integrity.py` (273 lines) — conflict detection, orphan detection, staleness
- `writ/gate.py` (249 lines) — structural pre-filter for AI rule proposals

### Key concepts:
- **12 node types**: Rule, AntiPattern, Phase, Playbook, Skill, Technique, PressureScenario, Rationalization, SubagentRole, WorkedExample, ForbiddenResponse, Abstraction
- **10 edge types**: RELATED_TO, COUNTERS, TEACHES, DEMONSTRATES, GATES, PRECEDES, DISPATCHES, CONTAINS, PRESSURE_TESTS, ATTACHED_TO
- **Confidence tiers**: speculative → peer-reviewed → production-validated → battle-tested
- **AI rules enter at ai-provisional** — require human promotion via `writ review --promote`
- **SUPERSEDES edges** for deprecation (preserves history, no deletion)
- **Gate checks**: schema validity, vague language (10 banned phrases), redundancy (cosine ≥ 0.95), conflict justification

### Check understanding:
- What's the difference between a Rule and an AntiPattern node?
- Why can't AI-provisional rules seed graph proximity?
- What are the 10 banned vague phrases in the gate?
- How does graduation work (threshold + ratio)?

---

## Level 5 — Hooks and enforcement

**Goal:** Understand the hook system, session state machine, modes, and gates.

### Read these:
1. `docs/extraction/06-hooks-and-claude-code-integration.md` (425 lines) — hook architecture
2. `docs/extraction/12-session-and-agentic-retrieval.md` (333 lines) — session tracking, subagent handling
3. `templates/settings.json` — the full hook wiring + permissions
4. Open `writ-workflow-flowchart.html` in a browser — visual workflow diagram

### Explore these files:
- `.claude/hooks/writ-rag-inject.sh` — RAG injection hook (the most important hook)
- `.claude/hooks/writ-pre-write-dispatch.sh` — gate enforcement on file writes
- `.claude/hooks/writ-quality-judge.sh` — quality judge hook
- `.claude/hooks/writ-pressure-audit.sh` — pressure scenario detection
- `bin/lib/writ-session.py` — the state machine (modes, phases, gates)
- `bin/lib/checklists.json` — phase exit criteria
- `bin/lib/gate-categories.json` — file classification globs

### Key concepts:
- **Hook lifecycle**: UserPromptSubmit → PreToolUse → PostToolUse → session end
- **Mode state machine**: Discussion (default) → Work (explicit entry) → gates activate
- **Plan gate**: `plan.md` must exist with 4 sections (Files, Analysis, Rules Applied, Capabilities)
- **Test gate**: at least one test file with real assertions before production code
- **Anti-cheat**: gate approval requires filesystem token at `/tmp/writ-gate-token-${SESSION_ID}`, written only on human approval phrase. AI cannot self-approve
- **Subagent handling**: `is_subagent: true` bypasses gates, gets fresh 8K token budget
- **Friction logging**: every gate denial/approval/transition logged to JSONL

### Check understanding:
- Walk through what happens when you type "let's implement feature X" in a fresh session
- How does the anti-cheat token prevent AI self-approval?
- What's the difference between how subagents and orchestrators interact with Writ?
- Why are some hooks on UserPromptSubmit vs PreToolUse vs PostToolUse?

---

## Level 6 — Testing, benchmarks, and pressure runs

**Goal:** Understand how Writ validates itself.

### Read these:
1. `docs/extraction/08-testing-and-benchmarks.md` (541 lines) — test architecture
2. `SCALE_BENCHMARK_RESULTS.md` — performance at scale
3. `docs/pressure-runs/README.md` — the manual adversarial testing process
4. Read ONE pressure run end-to-end: `docs/pressure-runs/PSR-001/` (scenario → transcript → analysis)
5. Read the scenario definitions: `docs/pressure-runs/scenarios/` — what adversarial prompts look like

### Key concepts:
- **282 tests** across 15 files — the correctness contract
- **12 benchmark targets** — latency, memory, MRR@5, hit rate, cold start
- **Pressure runs** — manual adversarial scenarios to test process enforcement
- **5 adversarial scenarios**: quick-fix pressure, scope creep, trust-and-ship, post-compact reflex, skip-plan
- **Friction log analysis** — `writ analyze-friction` for monthly rule health reviews

### Check understanding:
- What's MRR@5 and why does it matter for retrieval quality?
- What's a pressure run testing that unit tests can't?
- How does the monthly review process work (friction log → rule health)?

---

## Level 7 — Configuration, compression, and advanced topics

**Goal:** Understand the tuning knobs and advanced features.

### Read these:
1. `docs/extraction/09-configuration-and-deployment.md` (501 lines) — all config options
2. `docs/extraction/10-compression-and-abstractions.md` (220 lines) — HDBSCAN clustering, abstraction nodes
3. `docs/extraction/04-cli-commands.md` — all CLI commands
4. `docs/extraction/05-http-api.md` — all HTTP endpoints
5. `CONTRIBUTING.md` — how the author expected contributions

### Explore:
- `writ.toml` — read every section, understand what each knob does
- `writ/compression/clusters.py` — HDBSCAN/k-means clustering
- `writ/compression/abstractions.py` — abstraction node generation

### Check understanding:
- When would you change the ranking weights?
- What problem does compression/abstraction solve?
- How does `writ.toml` env var override work?

---

## Level 8 — The FalkorDBLite swap (your fork)

**Goal:** Understand what changed in the fork and why.

### Read these:
1. `docs/roadmap/project-design.md` — your fork's design spec
2. `docs/roadmap/roadmap.md` — the 3-phase swap plan
3. `CLAUDE.md` — the fork's AI orientation doc

### Then compare:
- Read `writ/graph/db.py` — the Neo4j implementation (what you're replacing)
- Read FalkorDBLite docs — Cypher dialect differences

### Check understanding:
- What are the 5 Python files that reference Neo4j?
- Why did we choose FalkorDBLite over alternatives?
- What are the key invariants that must hold after the swap?

---

## Visual resources (open in browser)

| File | What it shows |
|------|---------------|
| `writ-complete-overview.html` | Full system overview — start here |
| `writ-architecture-flowchart.html` | Architecture layers and data flow |
| `writ-workflow-flowchart.html` | Mode/phase/gate state machine |
| `writ-commands.html` | All CLI commands visualized |

---

## Doc inventory by depth

| Doc | Lines | Best for |
|-----|-------|----------|
| HANDBOOK.md | 497 | Best single doc — covers everything at user level |
| extraction/03-retrieval-pipeline.md | 639 | Deepest on the retrieval pipeline |
| extraction/02-graph-and-storage.md | 684 | Deepest on graph schema and storage |
| extraction/08-testing-and-benchmarks.md | 541 | Test architecture and benchmark contracts |
| extraction/09-configuration-and-deployment.md | 501 | All config options |
| extraction/06-hooks-and-claude-code-integration.md | 425 | Hook architecture and wiring |
| extraction/11-evolution-and-authority.md | 340 | Rule lifecycle and authority model |
| extraction/12-session-and-agentic-retrieval.md | 333 | Session tracking and subagent handling |
| SCALE_BENCHMARK_RESULTS.md | 267 | Performance at 1K/5K/10K rules |
| extraction/01-architecture-and-data-flow.md | 286 | System overview and query trace |
| .claude/CODEBASE.md | 175 | Module map for developers |
| extraction/07-rule-schema-and-validation.md | 259 | Rule format spec |
| extraction/04-cli-commands.md | 258 | CLI reference |
| extraction/05-http-api.md | 270 | HTTP API reference |
| extraction/10-compression-and-abstractions.md | 220 | Compression/clustering |
