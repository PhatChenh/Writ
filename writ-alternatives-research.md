# Writ Alternatives & Agent-Memory Research

*Reference notes for when you decide to build your own version of Writ. Saved June 2026.*

---

## TL;DR

Writ is **not** a rules file — it's a heavyweight RAG retrieval engine (local HTTP daemon + Neo4j + Tantivy/BM25 + hnswlib vectors + ONNX embeddings, wired into Claude Code via 16 hooks). Its real contribution is **selective retrieval of a holistic knowledge corpus under a context-window budget** — surfacing only the ~5 relevant rules/ADRs/constraints per task instead of stuffing all 120k tokens every turn.

The correct mental category for "do it like Writ" is **agent memory**, *not* guardrails. Guardrail/hook tools enforce; they don't remember.

---

## Two different jobs (don't conflate them)

**Enforcement** — stop the agent doing a bad thing (rm -rf, push to prod, bypass lint). Reactive allow/deny gates on tool calls. Carries no knowledge. → LaneKeep, agent-guardrails, Cerbos Synapse, plain Claude Code hooks.

**Knowledge retrieval under a context budget** — remember a large holistic body (ADRs, tech debt, constraints, architecture, coding patterns) and surface only the task-relevant slice. → This is Writ's actual job. The memory-layer category.

---

## Guardrail / enforcement tools (from first round — NOT what you want for knowledge)

Principle running through the space: *"Rules in markdown are suggestions. Code hooks are laws."* These enforce, they don't carry knowledge.

- **LaneKeep** — pure Bash + jq, zero network calls, runs locally, Claude Code hooks. 150+ rules, 10+ policy categories, append-only audit trail the agent can't modify, budget/token/action/time limits, self-protection so agent can't disable its own governance. Lightweight enforcement.
- **jzOcb/agent-guardrails** — mechanical enforcement via hooks, model-agnostic (Claude Code / Cursor / any agent). "Hooks are laws" philosophy.
- **hookify** — most minimal. Plain-English → generated hook. `/hookify Warn me when any command contains "prod"`. Zero infra. Start with one rule, tune weekly, add incrementally.
- **Cerbos Synapse** — team/org-wide policy. Sits at Claude Code's HTTP hook endpoint, converts each tool call into an authz check, returns allow/deny. Agent never sees / can't modify / can't skip. Via MDM (Jamf/Intune) server-managed settings, the hook is baked in org-wide — neither dev nor agent can remove it.
- **Plain Claude Code hooks** — native. The documented layered model: CLAUDE.md (instruction-level, weakest) → tool-enforced config (deny lists, MCP allowlists) → OS sandboxing (only truly unbypassable layer).

---

## Agent-memory alternatives (the REAL competitors to Writ's retrieval engine)

Three shapes. Which fits depends on what you value about Writ.

### 1. General-purpose agent memory frameworks
**Mem0, Zep, MemGPT/Letta, Cognee.** Mature, benchmark-backed.
- Mem0: April 2026 token-efficient algo (single-pass hierarchical extraction + multi-signal retrieval). ECAI 2025 paper = first broad 10-approach comparison on LoCoMo benchmark. Far more battle-tested than Writ; no need to stand up Neo4j yourself.
- **Catch:** built for conversational/user memory (preferences, past interactions), not opinionated about *coding governance*. You'd get the retrieval substrate but model ADRs/constraints/patterns + the "mandatory rule can't be dropped" guarantee yourself.

### 2. GraphRAG-style structured retrieval
**Microsoft GraphRAG, HippoRAG2, Cognee.** Closest match to Writ's *specific architecture* — Writ's distinguishing feature is the Neo4j graph modeling `DEPENDS_ON` / `CONFLICTS_WITH` / `SUPPLEMENTS` between rules.
- GraphRAG = entity-document graphs capturing structural dependencies. HippoRAG2 = nonparametric retrieval. Both react to similarity/entity-centric retrieval neglecting causality in stored info.
- Use if you care that an ADR's constraints pull in dependent patterns. **As heavy as Writ.**

### 3. Lightweight build-it-yourself: ADRs-as-files + tool-based retrieval
The pragmatic answer most teams land on. Addresses context-window concern without Writ-scale infra.
- Don't keep all ADRs in active context. Give the agent an API/tool (MCP) to query `/docs/adrs/` or commit history on demand.
- Configure retrieval so task subject pulls only relevant ADRs (frontend task → TypeScript-migration ADR).
- "Mandatory rule" handled by **promotion, not ranking**: promote permanent project laws into AGENTS.md / CLAUDE.md so they're always core operational rules. (This is Writ's `ENF-*` "load directly, never ranked" mechanism.)
- Essentially a stripped-down Writ. Loses sub-ms graph ranking; keeps the core value at a fraction of operational cost. **Best effort-to-payoff for a single team.**

---

## KEY DESIGN SUBTLETY (preserve this in any build)

Retrieval has **two modes that look alike but aren't** — conflating them is the most common mistake in this space:

- **Known-scope lookup (enumeration):** "Give me all active policies that apply this turn." Every match returned, no top-k, no ranking, runs every turn. → Feeds the static prefix.
- **Semantic discovery (ranked):** "Find things conceptually relevant to this message." Ranking + top-k + score thresholds matter. → Feeds the volatile tail, on demand.

**Apply to your build:**
- Mandatory constraints (security gates, "all UI is TypeScript") = **enumeration**. NEVER through a ranker that could drop them.
- ADRs / patterns / tech-debt = **semantic discovery**. Rank + budget those.

Writ gets this right by separating `ENF-*` from the ranked pipeline. Reproduce that split or a security rule will eventually be silently ranked out of context.

---

## Decision guide

| You want… | Pick |
|---|---|
| Writ's capability + real maturity/benchmarks, willing to model governance yourself | **Mem0** (or Zep / Letta) |
| Writ's exact graph-relationship modeling | **GraphRAG / HippoRAG2 / Cognee** (≈ Writ weight) |
| Writ's *value* without Neo4j + Docker + daemon | **ADRs-as-files + MCP/tool retrieval + promote-criticals-to-AGENTS.md** (lightest) |
| Just enforcement (stop bad actions) | Plain hooks → LaneKeep / agent-guardrails / Cerbos |

**On Writ itself:** reasonable if you genuinely have a large interdependent governance corpus and want it pre-assembled — but note it's a 2-star solo research project with no releases. The underlying pattern is now well-documented enough to assemble from sturdier parts.

---

## Sources
- Writ repo: github.com/infinri/Writ
- Mem0 — State of AI Agent Memory 2026: mem0.ai/blog/state-of-ai-agent-memory-2026
- "RAG is Not Dead — It's Just Becoming Agent Memory": dev.to/dhruvjoshi9
- Oracle — From RAG to AI Memory Systems (two-mode retrieval insight): blogs.oracle.com/developers/from-rag-to-memory-systems-building-stateful-ai-architecture
- OpenML — Codebase RAG for Coding Agent (ADRs-as-files pattern): blogs.openml.io/posts/agent-coding-rag/
- AMA-Bench (GraphRAG/HippoRAG2 context): arxiv.org/pdf/2602.22769
- LaneKeep: medium.com/@mightymo (guardrails write-up)
- jzOcb/agent-guardrails: github.com/jzOcb/agent-guardrails
- Cerbos Synapse: cerbos.dev/blog
