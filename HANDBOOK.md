# The Writ Handbook

A complete guide to what Writ is, why it exists, and how it works. Written for two audiences at once: people who just want to know what changes when they install it, and people who want to understand the architecture well enough to extend it.

Every number in this document was measured live against the running system on 2026-05-10 with the production rule corpus (276 rules, 30 of them mandatory). The corpus reflects the Phase 1-5 public-rulebook expansion: 198 new rules seeded across 12 domains (Security, Clean Code, DRY, SOLID, Architecture, Testing, Error Handling, Performance, Scaling, API Design, Documentation, Process). The 2026-05-10 cleanup baseline that preceded the expansion pruned 17 dead-workflow rules and demoted 12 advisories; that floor underlies the expansion. Every code reference points to a file path and line number you can open. Where older documentation drifted from the code, the code wins.

## What Writ is

Writ is a Claude Code add-on. You install it once, and from then on every Claude Code session you start has two helpers running in the background.

The first helper is a librarian. When you ask Claude to do something, the librarian quietly looks up the coding rules that fit what you are working on right now and slides them into the conversation. Not all of them. Just the ones that matter for this file, this domain, this turn. The librarian works in well under a millisecond, so you never feel it.

The second helper is a process keeper. When Claude is about to do something risky, like write a file before you have agreed on a plan, the process keeper steps in. It tells Claude to pause, asks you to approve, and only then unlocks the next step. You stay in charge of the workflow without having to chase Claude through every decision.

That is the whole product, in two sentences. A fast, smart rule lookup, plus a workflow that keeps the model honest.

## Why we built it

Two problems made every other approach break down.

### Problem one: context stuffing does not scale

The natural way to give Claude a coding rulebook is to paste the whole thing into the prompt every turn. That works fine when you have ten rules. It falls apart at one thousand. By the time you are at ten thousand rules, you are paying for over a million tokens of rule text per turn (live measurement at our 80 rule baseline: 13,876 tokens; at 10,000 rules: 1,174,142 tokens). The model treats none of them as load bearing because it cannot tell which ones are. Cache hit rates collapse. Latency climbs. The bill scales with your rulebook, not with your work.

### Problem two: process discipline cannot live in a prompt

Static skill files can describe a workflow, like "always write the failing test first," but they cannot enforce it. The model can read the skill and then write the implementation first anyway, because nothing stopped it. Discipline that lives only in a prompt is a suggestion. We needed it to live at the boundary where Claude actually calls tools.

Writ solves both at once. The librarian replaces context stuffing with relevance. The process keeper replaces suggestion with enforcement.

## What you experience when you use it

You install Writ. You open Claude Code. You type a prompt.

Behind the scenes, Writ reads your prompt, figures out the relevant slice of the rulebook, and injects a compact `--- WRIT RULES ---` block ahead of Claude's reply. The block is small (typically a few hundred to a couple thousand tokens, depending on remaining budget and which mode the budget triggers). At the top of each turn you see a brief status line:

```
[Writ: mode=work, phase=implementation, gates=[], violations=0]
```

That tells you four things at a glance. What mode the session is in. Where in the workflow you are. Which gates are still pending (an empty list means the gates that apply to the current phase have been cleared). Whether anything is blocking progress.

If you ask Claude to write code before you have a plan, Claude tries, the write is denied, and Claude tells you why. Something like:

```
[ENF-GATE-PLAN] Write blocked. Approve plan.md first.
```

That is the process keeper in action. You write the plan, you say "approved," the gate opens, Claude writes the code. The next gate (test skeletons) blocks code that has no tests pointing at it. Same pattern: write the tests, approve, the gate opens.

When Claude is doing read-only work (asking questions, debugging, reviewing), there are no gates. Discipline kicks in only when you have declared that you are working.

That is the whole user experience. Smarter rules, fewer surprises, and a workflow that holds the line.

## The three pieces under the hood

Writ is not one piece of software. It is three things working together.

### The knowledge layer (the librarian)

This is the Python package at `writ/`, served on `localhost:8765` by a small FastAPI service. It owns the retrieval pipeline, the structural gate that vets new rules, the analyzer that checks code for violations, and 36 HTTP endpoints (11 top-level, 25 under `/session/{id}/`). It is stateless with respect to your workflow.

### The enforcement layer (the process keeper)

This is the librarian's enforcer. It is made up of 30 hook scripts under `.claude/hooks/`, all wired into Claude Code through `templates/settings.json`, a session state machine in `bin/lib/writ-session.py` (just over 2,000 lines), the slash commands under `.claude/commands/`, and 6 sub-agent role files under `.claude/agents/`. (Three legacy hooks tied to the deprecated Phase A-D / completion-matrix gate workflow were removed on 2026-05-10: `check-gate-approval.sh`, `enforce-final-gate.sh`, and `writ-pretool-rag.sh`.) Hooks are thin clients; the state machine owns the truth.

### The canonical store

This is Neo4j 5, running in a Docker container that Writ brings up on `bolt://localhost:7687`. It holds the rulebook itself. The librarian builds its fast in-memory indexes from Neo4j when the service starts and serves queries from those indexes. Neo4j is the source of truth. Everything else is a view.

There is a fourth thing in the repo, the `bible/` directory, that is easy to mistake for a data source. It is not. `bible/` is the human-readable Markdown export of the graph. You ingest it once during install (`writ import-markdown bible/`), and after that the graph is canonical. Subsequent edits flow through `writ add`, `writ edit`, or `POST /propose`, and `bible/` is re-exported on the way out so it stays in sync. Think of `bible/` the way you would think of a `dist/` directory: a derived artifact that exists for humans, not for the runtime.

## A single turn, end to end

You type a prompt. Claude Code fires a `UserPromptSubmit` event. Writ's hook layer wakes up.

It reads the session cache to see what mode you are in, what phase of the workflow you are in, which rules are already loaded, and how much of your token budget for this turn is left (default budget: 8,000 tokens). If no mode is set, the hook tells Claude to declare one before doing anything risky. If the budget is exhausted or the context is over 75 percent full, the hook stays quiet.

Otherwise the hook posts your prompt (or a keyword extract of it, for long prompts) to the local service. The service runs the retrieval pipeline. Five stages, all in memory:

1. Filter to the relevant domain.
2. Run a keyword search (BM25 over the rule text).
3. Run a vector search (cosine similarity in 384 dimensional embedding space).
4. Look up neighbors in the pre-built graph adjacency cache.
5. Score everything with a weighted formula, apply your token budget, return the winners.

The whole pipeline takes 0.590 milliseconds at the 95th percentile against the live 276 rule corpus (post-expansion). The response comes back as a JSON list of rules.

The hook formats the response as a `--- WRIT RULES (N rules, MODE mode) ---` block, calculates the token cost, deducts that from your remaining budget, and prints the block to stdout. Claude Code injects it into the next turn.

A separate hook handles the always-on rules, the ones that have to be present every turn regardless of relevance. Those load from a different endpoint with a separate budget cap of 5,000 tokens, so the librarian can never starve them.

When Claude tries to write a file, a different hook fires. It checks whether you are in Work mode, whether the right gates have been cleared, and whether the file is the kind that the gate applies to. If everything is in order, the write goes through. If not, the write is denied with a structured reason, which Claude then tells you about.

When Claude finishes, a final set of hooks runs. They record what happened (which rules fired, which gates denied, how long the hooks took, whether the static analysis passed) into a friction log at `workflow-friction.log`. That log is what we use to learn which rules are actually useful, which ones are noise, and which workflows are holding up.

That is one turn, beginning to end. You get smart rule injection, a hard gate on writes that need approval, and a learning loop that gets better with use.

## The five stages, in detail

The pipeline is the heart of the librarian. Each stage covers a blind spot the others have.

### Stage 1: filter to the domain

If you tell Writ you are working on Python, the pipeline drops every PHP rule before it does anything else. This is a cheap filter applied to candidate sets, not a separate query.

### Stage 2: keyword search (BM25 via Tantivy)

The fastest way to find a rule is by its words. If you ask about "controller contains SQL query," BM25 picks `DB-SQL-001` because the rule body literally contains those words. (We just verified this against the running system. Top three hits for that query: `DB-SQL-001`, `DB-SQL-002`, `DB-SQL-003`.)

Tantivy is a Rust BM25 library, in process, in memory, no network. The BM25 index covers the trigger, statement, tags, and body of every rule. Trigger gets weighted twice (`TRIGGER_BOOST = 2.0`), body gets weighted half (every-other-token dilution), because triggers are short and signal-rich.

Stage budget: less than 2 ms at the 95th percentile. Live measurement: **0.275 ms p95**.

### Stage 3: vector search (HNSW via hnswlib)

Keyword search misses paraphrase. If you ask about "direct database call from web layer," BM25 will not find `DB-SQL-001` because none of those words match. The vector store catches that. Every rule is encoded into a 384 dimensional embedding using `all-MiniLM-L6-v2` (exported to ONNX runtime for speed; see `scripts/export_onnx.py`). Cosine similarity in that space puts paraphrases close to each other. hnswlib is a C++ library that does approximate nearest neighbor search well under a millisecond.

Stage budget: less than 3 ms at the 95th percentile. Live measurement: **0.064 ms p95**.

### Stage 4: graph traversal

Some rules apply not because they match your query but because they are related to a rule that does. The pipeline picks the top three first-pass matches and pulls in their one-hop and two-hop neighbors. For the live query "dependency injection constructor," the top matches are `ARCH-DI-001`, `FW-M2-004`, `ARCH-COMP-001`; traversal would surface neighbors of those.

The trick is making it fast. A live database query for a one-hop neighbor lookup costs about six milliseconds round trip, which is too slow for our budget. So Writ pre-computes the entire edge map at startup into a Python dictionary. Lookups become O(1) at one microsecond each.

Stage budget: less than 3 ms at the 95th percentile. Live measurement: **0.001 ms p95**.

### Stage 5: rank, fuse, trim

Each candidate now has a BM25 score, a vector score, plus metadata (severity, confidence, graph proximity, bundle cohesion). The ranking formula combines them into a single number. The default weights live in `writ/retrieval/ranking.py:18-42`:

```
keyword (BM25)        0.198
vector (cosine)       0.594
severity              0.099
confidence            0.099
graph proximity       0.010
bundle cohesion       0.000  (computed but unweighted by default)
```

Those weights were tuned over two rounds of evaluation against a curated set of 83 queries (`tests/fixtures/ground_truth_queries.json`). The top candidates are then trimmed to fit your token budget.

Stage budget: less than 1 ms at the 95th percentile. End-to-end live measurement: **0.414 ms p95** (budget 10 ms).

Two refinements matter for cache friendliness. Within a tight band of similar scores (0.02), Writ stabilizes the order from turn to turn so the prompt cache stays warm. And when human and AI proposed rules tie, human rules win by default (the threshold is 0 by default, which makes it a no-op until you opt in).

## The mode and gate system

Writ knows the difference between you asking a question and you writing code.

### The four modes

| Mode         | Purpose                                                | Gates apply? |
|--------------|--------------------------------------------------------|--------------|
| Conversation | Discussion, brainstorming, questions                   | No           |
| Debug        | Investigating a specific problem, read only            | No           |
| Review       | Evaluating code against rules, read only               | No           |
| Work         | Building or modifying code                             | Yes          |

You declare a mode at the start of each session. If you forget, the first prompt prompts you (the rule injection block tells Claude to set a mode before proceeding). Writ also blocks Claude from writing anything until a mode is set, which is what keeps the discipline from being optional.

### The two Work mode gates

In Work mode, two gates stand between Claude and your filesystem.

**Gate 1: phase-a (the plan gate).** Before any code is written, a `plan.md` has to exist with four sections: `## Files`, `## Analysis`, `## Rules Applied`, `## Capabilities`. The plan also has to cite real rule IDs from the rules already loaded in the session, not made up ones. When you say "approved," Claude runs the `/writ-approve` slash command, which validates the plan and clears the gate.

**Gate 2: test-skeletons (the test gate).** Before production code is written, at least one test file has to exist with real assertions in it (not just empty function bodies). Same approval pattern: write the skeletons, say approved, gate clears.

After both gates clear, Claude writes the implementation freely.

### How approval is anti-cheat

The gates have a property worth calling out. The `/writ-approve` slash command requires a one time token that lives at `/tmp/writ-gate-token-${SESSION_ID}`. The token is 32 hex characters generated by `secrets.token_hex(16)` and is written to disk only when the user actually types an approval phrase (`auto-approve-gate.sh:173-175`). If Claude tries to advance the gate by calling the API directly, the token is missing and the call is denied with `agent_self_approval_blocked` logged to the friction log. Self approval is structurally impossible.

## The graph: what makes Writ different

A vector database can find rules that look like your query. A keyword index can find rules that mention your query. Neither one knows that one rule depends on another, that two rules conflict, or that a methodology node teaches a rule. Writ's graph does.

### The 12 node types, with live counts from the production graph

| Node type           | Live count | Retrievable? |
|---------------------|-----------:|--------------|
| Rule                | 90         | yes          |
| AntiPattern         | 10         | yes          |
| Phase               | 9          | bundle only  |
| Playbook            | 8          | yes          |
| Skill               | 8          | yes          |
| Technique           | 4          | yes          |
| PressureScenario    | 3          | bundle only  |
| Rationalization     | 3          | bundle only  |
| SubagentRole        | 3          | bundle only  |
| WorkedExample       | 2          | bundle only  |
| ForbiddenResponse   | 2          | yes          |
| Abstraction         | 0          | yes          |

Total: 142 nodes. (Abstraction count is 0 because `writ compress` has not been run on this corpus; abstractions are generated on demand.)

"Retrievable" means the node can be returned directly by the pipeline. "Bundle only" means it surfaces only as a neighbor of a retrievable node through Stage 4 graph traversal.

### The edge types, with live counts

The driver allows 17 edge types (`ALLOWED_EDGE_TYPES` in `writ/graph/db.py:40-47`). The live graph currently uses 10 of them:

| Edge type        | Live count |
|------------------|-----------:|
| RELATED_TO       | 147        |
| COUNTERS         | 28         |
| TEACHES          | 20         |
| DEMONSTRATES     | 20         |
| GATES            | 16         |
| PRECEDES         | 15         |
| DISPATCHES       | 13         |
| CONTAINS         | 9          |
| PRESSURE_TESTS   | 3          |
| ATTACHED_TO      | 3          |

Total: 274 edges. The seven unused edge types (`DEPENDS_ON`, `CONFLICTS_WITH`, `SUPPLEMENTS`, `SUPERSEDES`, `APPLIES_TO`, `ABSTRACTS`, `JUSTIFIED_BY`) are valid in the schema but have no rules using them yet. This is one of the documented seams: schema is wider than current usage.

### Why the graph matters

A flat retrieval system has to choose: be tight (and miss related rules) or be loose (and surface too many). The graph lets us be tight on relevance and loose on bundle membership. Stage 4 traversal expands a single matched rule into a coherent bundle without polluting the top-of-list ranking.

## Mandatory rules: the architectural invariant

A retrieval system that ranks safety rules is dangerous. If the ranker has a bad day, a critical security rule slips off the bottom of the list, the model writes a bug, and the only thing that catches it is whatever review process you trust. We do not trust that.

So Writ separates the rulebook into two pools.

**Retrieved rules** are the domain specific guidance. They live in the graph, get indexed by BM25 and the vector store, get ranked by the pipeline. They show up when they are relevant. There are 49 of these in the live graph.

**Mandatory rules** (the ones with `mandatory: true`, all 41 of which carry the `ENF-` prefix in the live corpus) live in the same graph but are explicitly excluded from the retrieval pipeline at index build time. They never enter BM25, never enter the vector store, never get ranked. They cannot be ranked away.

Every turn, a separate hook calls a separate endpoint (`/always-on`) that returns the full mandatory set, plus all `ForbiddenResponse` nodes, plus any Skill or Playbook explicitly marked always on. That set is rendered into the prompt with its own token budget cap of 5,000 tokens (`writ/shared/budget.json:always_on_cap`), so even if the retrieval pipeline runs hot, the mandatory rules are not competing for the same space.

The invariant in one sentence: no change to ranking weights, embedding model, BM25 tuning, or graph traversal can cause an enforcement rule to disappear from agent context.

A note on the audit and the expansion. A 2026-04-21 audit reviewed the original 35 mandatory rules and recommended 18 of them for demotion. The pre-cleanup graph had 41 mandatory rules. The 2026-05-10 cleanup pruned that down to 11 (deleted 17 rules tied to the dead Phase A-D / Tier-0-3 workflow and demoted 12 to advisory). The Phase 1-5 public-rulebook expansion then added 19 new mandatory rules from the public out-of-the-box rulebook, each backed by a real mechanical-enforcement analyzer:

| Mandatory addition phase | Rules | Analyzer |
|---|---|---|
| Phase 1A Injection | SEC-INJ-SQL-001, XSS-001, CMD-001, SSRF-001, DESER-001, CSRF-001 | `bin/run-analysis.sh::analyze_security_injection` |
| Phase 1B Auth/AuthZ/Val | SEC-AUTH-HASH-001, TOKEN-001; SEC-AUTHZ-ENFORCE-001, IDOR-001, DEFAULT-001, MASS-001; SEC-VAL-SERVER-001, FILE-001 | `bin/run-analysis.sh::analyze_security_auth_authz` |
| Phase 1C Crypto | SEC-CRYPTO-KEY-001, RAND-001 | `bin/run-analysis.sh::analyze_security_crypto_headers` |
| Phase 1D Data | SEC-DATA-PII-001 | `bin/run-analysis.sh::analyze_security_data_protection` |
| Phase 3B Performance | PERF-QUERY-001 (N+1) | `bin/run-analysis.sh::analyze_performance_n_plus_one` |
| Phase 4 Scaling | SCALE-STATELESS-001 | `bin/run-analysis.sh::analyze_scaling_stateless` |

The remaining 11 mandatory rules are the Writ-original ENF-* enforcement set, each tied to a wired hook in `.claude/hooks/`. Total mandatory: 30.

## Sub-agents and orchestration

Many real workflows use multiple Claude sessions. You have an orchestrator that delegates to workers: an explorer that maps the codebase, a planner that drafts the design, a test writer, an implementer, two reviewers (one for spec compliance, one for code quality). Writ supports this pattern as a first class feature. The 6 sub-agent role definitions live in `.claude/agents/`.

When the orchestrator dispatches a worker, a hook fires (`writ-subagent-start.sh`) and creates an isolated session for the worker. The worker has its own session cache, its own token budget (8,000 tokens, fresh), its own mode (inherited from the orchestrator), and one important flag: `is_subagent: true`. That flag means the worker bypasses the gates entirely. The orchestrator already cleared them; re-policing the worker would just create false denials.

Conversely, when you set the orchestrator session to Work mode with the `--orchestrator` flag, a different flag (`is_orchestrator: true`) tells the librarian to suppress the broad rule injection on the orchestrator itself and emit a compact status line instead. The orchestrator does not need rule guidance turn by turn; the workers do.

The result is that you can run multi-hour autonomous workflows where the orchestrator stays focused on coordination, workers get the rules they need, and the gates fire only where they actually matter.

## How rules grow: AI proposal and graduation

Rulebooks are alive. New patterns appear in code; old rules go stale. Writ has an opinion about how rules should evolve.

### Step 1: an AI agent proposes a rule

If Claude spots a recurring antipattern that does not yet have a rule, it can call `POST /propose` with a candidate rule. The structural gate (`writ/gate.py:54-106`) runs five checks in order:

1. **Schema validity.** Pydantic validation against the `Rule` model. Required fields present, types correct.
2. **Mechanical enforcement path.** If the rule is mandatory, it must declare a `mechanical_enforcement_path`. Otherwise it cannot be enforced and would just be advisory in disguise.
3. **Specificity.** No vague language. Ten phrases are blocked: "consider," "be aware," "where appropriate," "when possible," "if necessary," "as needed," "try to," "should generally," "may want to," "keep in mind."
4. **Redundancy and novelty.** Cosine similarity check against existing rules. Anything at or above 0.95 is rejected as redundant. Anything between 0.85 and 0.95 is flagged as too novel (likely a duplicate the proposer did not find).
5. **Conflict.** If the new rule has a `CONFLICTS_WITH` edge to an existing rule and that conflict is not justified, reject.

If the rule passes all five, it lands in the graph as `authority: ai-provisional` with `confidence: speculative`. If it fails, it never enters the graph and the rejection reasons come back to the caller.

The gate also writes an origin context record (`writ/origin_context.py`) to a SQLite database, capturing what task the AI was working on and what query triggered the proposal. That record is what `writ review` shows you when you triage proposed rules.

### Step 2: frequency drives graduation

Once a rule is in the graph, hooks accumulate signals. Every time the rule was loaded into context and the resulting code passed static analysis, the rule's `times_seen_positive` counter goes up. Every time it was loaded and the code failed, `times_seen_negative` goes up. The graduation logic (`writ/frequency.py:28-53`) is:

```
if n = positive + negative >= 50 and positive / n >= 0.75:
    graduated = true
elif n >= 50 and positive / n < 0.75:
    flagged = true   # surfaces in integrity report for human review
else:
    not enough data yet
```

When a rule graduates, the ranking pipeline starts treating its empirical positive ratio as its weight, replacing the default weight for its confidence tier. Rules earn their relevance.

### Step 3: a human approves authority promotion

The `writ review` command shows you all the AI provisional rules. You can promote them (which moves them to `ai-promoted` and bumps confidence to `peer-reviewed`), reject them (which deletes them from the graph), or downweight them (which pins confidence to `speculative`). Promotion is a deliberate human act, not something the system does on its own.

The result is a rulebook that grows from observed patterns, gets vetted by humans, and is weighted by data rather than guesses.

## By the numbers

Live measurement on 2026-05-15 (v1.1.0) against the production corpus (276 rules, 30 mandatory, post Phase 1-5 expansion). 100 samples for the E2E test (10 prompts x 10 iterations) with warmup, 100 samples per per-stage test.

### Per-stage latency (live, v1.1.0)

| Stage                   | Median   | p95          | Budget    | Headroom |
|-------------------------|---------:|-------------:|----------:|---------:|
| BM25 (Tantivy)          | 0.135 ms | 0.278 ms     | 2.0 ms    | 7x       |
| Vector (hnswlib)        | 0.038 ms | 0.124 ms     | 3.0 ms    | 24x      |
| Cache (adjacency)       | 0.002 ms | 0.002 ms     | 3.0 ms    | >1000x   |
| Ranking (RRF + budget)  | 0.076 ms | 0.107 ms     | 1.0 ms    | 9x       |
| End to end              | 0.3 ms   | **0.5 ms**   | **10.0 ms** | **17x** |

End-to-end p95 of 0.5 ms is the steady-state warm-cache number. The v1.0.0 measurement of 0.590 ms is the same property; an intermediate measurement that produced 10-11 ms was a missing-warmup artifact in the bench, not a regression -- see `SCALE_BENCHMARK_RESULTS.md` "Real-vs-synthetic at matched scale" section for the diagnosis and the warmup fix.

### Cold start (v1.1.0, Item 4 fix)

| Mode                        | Cold start | Budget | Notes                        |
|-----------------------------|-----------:|-------:|------------------------------|
| Cold-cold (fresh install)   | ~2.4 s     | 3.5 s  | One-time per machine         |
| Warm cache (HNSW persisted) | ~0.24 s    | 3.5 s  | Every subsequent daemon start |

v1.1.0 reworked HNSW cache lookup: the corpus hash is now computed from rule text (not from embeddings), so the cache check happens before the encode_batch pass that dominates cold-start. On warm cache, `encode_batch` is skipped entirely. At 10,000 rules the warm-cache cold-start would still be ~0.24 s rather than the ~80 s the synthetic curve previously predicted.

### Scale (from `SCALE_BENCHMARK_RESULTS.md`)

The numbers above are for the live 276 rule corpus. Synthetic scale runs at 80, 500, 1,000, and 10,000 rules show how the system behaves under load; the live corpus now sits between the 80 and 500 synthetic points. Per the v1.1.0 Item 2 investigation, the synthetic curve underpredicts real-corpus per-query cost (real rules are 2.2x longer and embedding-diverse within a domain, where synthetic rules are templated near-clones); but the absolute numbers below remain the published synthetic upper bound for retrieval latency growth.

| Metric                  | 80 rules    | 500         | 1,000       | 10,000       |
|-------------------------|------------:|------------:|------------:|-------------:|
| End to end p95          | 0.278 ms    | 0.359 ms    | 0.399 ms    | **0.557 ms** |
| Cold start (median, pre-Item-4) | 0.494 s     | 3.452 s     | 5.782 s     | 70.788 s     |
| Memory (RSS, peak)      | 1,570 MB    | 2,349 MB    | 2,674 MB    | 2,943 MB     |
| Tokens, full corpus     | 13,876      | 63,003      | 121,473     | 1,174,142    |
| Tokens, retrieved       | 3,155       | 1,600       | 1,602       | 1,617        |
| **Context reduction**   | **4.4 x**   | **39.4 x**  | **75.8 x**  | **726.1 x**  |

The headline number is the context reduction at scale. At 1,000 rules you save 76 times the tokens on every turn. At 10,000 rules, 726 times. That is what changes the economics of a large rulebook. After the v1.1.0 Item 4 HNSW cache fix, cold-start at 10K rules also drops dramatically on warm cache (the cold-cold first-install number is unchanged; subsequent starts skip the encode_batch).

### Quality (v1.1.0)

| Metric                                          | Floor     | Actual            |
|-------------------------------------------------|-----------|-------------------|
| MRR at 5 (ambiguous queries, n=19)              | >= 0.45   | 0.6904 (17-18/19) |
| Hit rate (all 165 queries)                      | >= 0.75   | 0.800 (132/165)   |
| Domain hit rate top-5 (all 164 queries)         | >= 0.90   | 0.945 (155/164)   |
| Methodology MRR at 5 (n=40, signed off corpus)  | >= 0.78   | 0.8583            |
| Methodology hit rate                            | >= 0.90   | 1.0000 (40/40)    |
| Methodology bundle completeness                 | >= 0.85   | 0.8542            |
| ONNX vs PyTorch ranking stability (inline corpus, n=8) | identical top-1 and top-5 set | 0/8 differ |

The v1.0.0 baseline MRR@5 of 0.78 was on a 72-rule corpus and 83-query ground truth; v1.1.0 floor of 0.45 reflects the 276-rule corpus with an unchanged 19-query ambiguous subset. The Item 1a-1d work this release recovered ~70% of the v0->v1.0.0 gap (0.4886 -> 0.6904) by fixing label quality and rule-text coverage; the remaining ~12% gap to 0.78 is corpus-growth dilution at 3.8x the original rule count. The Item 10 ranking-stability test was rewritten in v1.1.0 to use a fixed inline 12-rule corpus and assert top-1 strict + top-5 set equality, which is corpus-state-independent and unflakes the prior 4 ADJACENT-SWAP false positives.

### Test and bench suite

| Suite          | Count | Time     | Gate                          |
|----------------|------:|---------:|-------------------------------|
| `make test`    | 1,512 | ~75 s    | All required for merge        |
| `make bench`   |    13 | ~12 s    | All required for merge        |

Both run on every PR via `.github/workflows/pr.yml` against a Neo4j 5 service container. v1.0.0 reported 1,441 tests; the v1.1.0 increase reflects the regression-floor consolidation, the rewritten ranking-stability test, the new domain-hit-rate enforcement gate, and the silent-fallback closure tests.

## What the repository contains

```
writ/                          The Python package (the librarian)
  server.py                    FastAPI app, 36 endpoints
  cli.py                       Typer CLI (entry point: writ.cli:app)
  graph/                       Neo4j models, ingest, integrity
  retrieval/                   Pipeline, BM25, vector, traversal, ranking, session tracker
  compression/                 HDBSCAN and k-means clustering, abstraction generation
  analysis/                    Pattern matching, LLM escalation, friction analytics
  config.py, dashboard.py, export.py, gate.py, authoring.py, frequency.py, origin_context.py

bin/lib/writ-session.py        The state machine (the process keeper, ~2,000 lines)
bin/                           Verification helpers (check-gates, run-analysis,
                               scan-deps, verify-files)

.claude/hooks/                 30 scripts, all wired into Claude Code events
                               (3 legacy hooks removed 2026-05-10:
                               check-gate-approval.sh, enforce-final-gate.sh,
                               writ-pretool-rag.sh)
.claude/agents/                6 sub-agent role definitions
.claude/commands/              Slash commands (writ-approve)

.claude-plugin/plugin.json     The plugin manifest

bible/                         Human readable Markdown export of the graph (not a runtime
                               data source)
docs/                          Specs, plans, monthly reviews, pressure runs, audits
benchmarks/                    Four benchmark suites (contractual, traversal, scale,
                               methodology)
tests/                         90 test files, 1,192 test functions
scripts/                       12 setup, migration, and tooling scripts
templates/                     settings.json and CLAUDE.md, rendered into ~/.claude/
                               on install

writ.toml                      Service configuration (Neo4j credentials, ranking weights,
                               budget thresholds)
pyproject.toml                 Package metadata and dependencies
docker-compose.yml             Neo4j 5 container
Makefile                       test, bench, check
```

## What is solid and what is still moving

### Production ready
- All five retrieval stages, with live latency well under budget at every level.
- Mode and gate enforcement.
- AI rule proposal with the five-check structural gate.
- Frequency-driven graduation logic in `writ/frequency.py`.
- Sub-agent isolation (`is_subagent`) and orchestrator suppression (`is_orchestrator`).
- ONNX-optimized embedding inference with verified ranking parity against PyTorch.
- HNSW persistence with corpus-hash invalidation.
- 1,442 tests, 12 contractual benchmark targets.
- Friction log analytics with a dashboard (`GET /dashboard`).
- Public out-of-the-box rulebook seeded: 198 new rules across 12 domains (Security, Clean Code, DRY, SOLID, Architecture, Testing, Error Handling, Performance, Scaling, API Design, Process, Documentation) per Phases 1-5; see `out-of-the-box-rules.md` for the canonical rule list.

### Under review
- Self review judge calibration (the hook-directive design is in place; see `.claude/hooks/writ-quality-judge.sh`).

## Getting started

```bash
git clone <writ-repo> ~/.claude/skills/writ
cd ~/.claude/skills/writ
bash scripts/bootstrap.sh
```

That single script does everything: checks Python 3.11+ and Docker, sets up a virtualenv, installs the package, ingests the rule corpus into Neo4j, starts the service, and wires the hooks into your Claude Code config. Idempotent, so you can re-run it any time.

For plugin-mode installs, see README "Install as a Claude Code plugin." The plugin path runs `scripts/bootstrap-plugin.sh` instead of `scripts/bootstrap.sh`, then `scripts/patch-global-config.sh` to bring `~/.claude/settings.json` and `~/.claude/CLAUDE.md` up to the state a standalone install would produce.

Verify with:

```bash
writ status
writ query "controller contains SQL query"
```

Expected output for `writ status`:
```
{"status": "healthy", "rule_count": 276, "mandatory_count": 30, "index_state": "warm", ...}
```

Open Claude Code in any project. Type a prompt. You should see a `[Writ: ...]` status line at the top of Claude's reply, and a `--- WRIT RULES ---` block with three to five rules. That is Writ working.

## Glossary

**Always on bundle.** The mandatory rule set plus all `ForbiddenResponse` nodes, plus any `Skill` or `Playbook` flagged `always_on: true`. Loaded every turn through `/always-on` with its own 5,000 token budget cap. Never subject to retrieval ranking.

**Authority.** A property on each rule, one of `human`, `ai-provisional`, `ai-promoted`. Determines how the rule was created and how it ranks at equal relevance. Live corpus: all 276 rules are `human`.

**Bundle cohesion.** A score that boosts rules whose neighbors are also being surfaced this turn. Helps return coherent bundles instead of disjoint matches. Default weight: 0 (computed but not contributing).

**Confidence.** A property on each rule, one of `battle-tested`, `production-validated`, `peer-reviewed`, `speculative`. Used as a weight in ranking. Empirical graduation substitutes the observed positive ratio for the static tier weight when a rule has at least 50 observations and a positive ratio of at least 0.75, via `compute_confidence_weight` invoked from the pipeline ranking path.

**Friction log.** A JSONL file (`workflow-friction.log`) that records every interesting event in a session: gate denials, phase transitions, hook timing, rule loads, sub-agent completions, quality judge overrides. The dashboard at `GET /dashboard` reads from this file.

**Gate.** A workflow checkpoint. Two in Work mode: `phase-a` (plan approved) and `test-skeletons` (tests written). Cleared by user approval through the `/writ-approve` slash command, which validates a one-time token to prevent self-approval.

**Hook.** A shell script wired into a Claude Code event. Writ ships 33 of them across UserPromptSubmit, PreToolUse, PostToolUse, Stop, SessionEnd, SubagentStart, SubagentStop, PreCompact, PostCompact, CwdChanged, and InstructionsLoaded events. Hooks are thin clients; the session state machine in `bin/lib/writ-session.py` is the authority.

**Mode.** One of `conversation`, `debug`, `review`, `work`. Determines whether gates apply. Read-only modes (the first three) bypass gates entirely.

**Orchestrator.** A master Claude Code session that dispatches workers. Sets `is_orchestrator: true`, which suppresses the broad rule injection on the orchestrator itself and emits a compact status line instead. Workers handle their own retrieval.

**Phase.** Within Work mode, a workflow stage: `planning`, `testing`, `implementation`, `complete`. Transitions happen when gates clear.

**Pre-computation.** The architectural philosophy that nothing is computed at query time that could have been computed at ingestion time. The graph, the embeddings, the BM25 index, the adjacency cache, and the abstraction summaries are all pre-built. Retrieval serves from memory.

**Sub-agent.** A worker session spawned from an orchestrator. Sets `is_subagent: true`, which bypasses gates and budget skip checks. Workers get a fresh 8,000 token budget per session.
