<!-- RULE START: DESIGN-ADR-001 -->
## Rule DESIGN-ADR-001

**Domain**: architecture
**Severity**: Medium
**Scope**: Repo
**Mandatory**: false

### Trigger
When a design decision is locked (user approves an option, a tradeoff is settled, a constraint is accepted).

### Statement
Every locked decision is recorded at the moment of locking: context (what forced the choice), options considered, the choice, and the consequences accepted (what we gave up). The record lives in a durable project doc (decision log, STATE.md, design doc) — not only in the chat transcript. Re-litigating a recorded decision without new information is a violation in both directions (AI must not silently deviate; AI must also defend the record against its own future forgetfulness).

### Violation
```
Decision made in chat session 12; session 20's AI, lacking the context, "improves"
the architecture by undoing it — reintroducing the exact problem the decision solved.
```

### Pass
```
## D7 — Sync client, no asyncio in db.py (LOCKED 2026-06-20)
Context: session-scoped test fixture must be event-loop-safe.
Options: async-redis client / sync client behind async defs / full sync API.
Chose: sync client behind async defs. Gave up: true async concurrency in graph layer.
Consequence: adding any asyncio primitive to db.py reintroduces cross-loop failures.
```

### Enforcement
update-project-docs step at session end; reviewers check diffs against the decision log.

### Rationale
In an AI-driven workflow the "team member who remembers why" does not exist — every session starts amnesiac. The decision record is the only institutional memory. Undocumented decisions get unmade by the next model, and the human cannot catch it because they never knew the reason either.

<!-- RULE END: DESIGN-ADR-001 -->
---

<!-- RULE START: DESIGN-BORING-001 -->
## Rule DESIGN-BORING-001

**Domain**: architecture
**Severity**: High
**Scope**: Repo
**Mandatory**: false

### Trigger
When choosing a technology: language, framework, database, queue, hosting, protocol, major library.

### Statement
Default to boring, proven, mainstream technology (the thing with 10 years of Stack Overflow answers and stable docs). Each non-boring choice spends one "innovation token" and requires: (a) a named capability the boring option lacks, (b) evidence the project actually needs that capability, and (c) an exit path if the choice fails. A project gets at most ONE innovation token unless the user explicitly grants more.

### Violation
```
Stack proposal: new experimental web framework + niche vector DB + beta ORM,
because each is "more modern." Three innovation tokens spent, zero justified.
```

### Pass
```
Stack: Python + FastAPI + SQLite (all boring). One innovation token spent on
FalkorDBLite because the project's core feature is Cypher graph traversal and the
boring alternative (Postgres + recursive CTEs) was tested and is 40x slower on our
query shape. Exit path: graph layer is behind writ/graph/db.py; swap = 1 module.
```

### Enforcement
Design review: count non-mainstream choices, demand the three-part justification per token.

### Rationale
Novel tech fails in novel ways, and a non-expert cannot distinguish "this library is broken" from "my design is wrong." Boring tech makes failures searchable and answers findable — which is the cheapest form of support a solo builder can get.

<!-- RULE END: DESIGN-BORING-001 -->
---

<!-- RULE START: DESIGN-BUY-001 -->
## Rule DESIGN-BUY-001

**Domain**: architecture
**Severity**: Medium
**Scope**: Repo
**Mandatory**: false

### Trigger
When a design introduces a custom-built component in a solved problem space (auth, search, parsing, scheduling, diffing, retry, caching, markdown rendering, embeddings).

### Statement
Before designing a custom component, the doc names at least one existing library/service that covers the need and states why it is insufficient — with the reason grounded in a real constraint (license, size, missing capability, unacceptable dependency), not aesthetics ("cleaner to own it"). If nothing was searched, the design is not ready.

### Violation
```
Spec includes "custom BM25 implementation (~800 lines)" with no mention that
tantivy/lucene/whoosh exist and no reason they were rejected.
```

### Pass
```
Ranking: tantivy (BM25, maintained, Python bindings). Rejected whoosh: unmaintained
since 2022. Rejected custom: 800 lines we would own forever for zero differentiation.
Custom code is reserved for the one thing no library does: our two-pass RRF merge.
```

### Enforcement
Design review: every custom component in a solved space carries a "considered and rejected" line.

### Rationale
Custom code in solved spaces is the highest-interest debt a small project can take: it gets the maintenance burden of a library with none of the community hardening. The differentiated 10% of a project deserves the custom effort; the commodity 90% does not.

<!-- RULE END: DESIGN-BUY-001 -->
---

<!-- RULE START: DESIGN-CUT-001 -->
## Rule DESIGN-CUT-001

**Domain**: architecture
**Severity**: Medium
**Scope**: Repo
**Mandatory**: false

### Trigger
When writing a spec, phase plan, or roadmap with more than trivial scope.

### Statement
Every spec/phase declares its scope-cut ladder before building starts: which parts are CORE (phase fails without them), which are STANDARD (expected but cuttable), and which are STRETCH (first to drop). When time/complexity overruns, cutting follows the ladder — the AI must not silently thin quality (skipped tests, missing error handling) across the whole scope instead of visibly cutting features off the ladder.

### Violation
```
Phase overruns. Implementer keeps all 6 features but quietly drops tests on 4 of
them and swallows errors to "make it work." Scope looks intact; quality is hollow.
```

### Pass
```
Scope ladder: CORE = ingest + query path (with tests). STANDARD = export command.
STRETCH = friction dashboard. Overrun in week 2 → dashboard dropped, stated in the
phase report. Core kept its tests.
```

### Enforcement
Spec template includes the ladder; phase-completion review compares delivered scope to the ladder and rejects silent quality-thinning.

### Rationale
Under pressure, cutting quality is invisible and cutting scope is visible — so AIs (and humans) default to the invisible cut, which is the one that destroys the codebase. A pre-agreed ladder makes the visible cut cheap to invoke and the invisible one detectable.

<!-- RULE END: DESIGN-CUT-001 -->
---

<!-- RULE START: DESIGN-DATA-001 -->
## Rule DESIGN-DATA-001

**Domain**: architecture
**Severity**: High
**Scope**: Repo
**Mandatory**: false

### Trigger
When writing a design or spec for a feature that stores, transforms, or exchanges data.

### Statement
The data design comes first and is stated explicitly: what entities exist, which fields they carry, which component OWNS each piece of data (may write it), and what the source of truth is when two copies disagree. Behavior/endpoints/UI are designed after the data shapes are pinned. A spec whose data model is implied by its code examples rather than declared is a violation.

### Violation
```
Spec describes 6 API endpoints in detail; the reader must reverse-engineer the
data model from response examples. Two endpoints disagree about whether `status`
lives on the order or the shipment.
```

### Pass
```
## Data model (design this first)
Rule { id, domain, severity, body }        — owned by: bible/ markdown (source of truth)
GraphNode mirrors Rule                     — owned by: ingest (derived; rebuildable)
On disagreement: markdown wins; re-ingest repairs the graph.
Endpoints follow from this model (below).
```

### Enforcement
Spec template requires a data-model section above the behavior section; review checks ownership + source-of-truth lines exist.

### Rationale
Bad code with a good data model can be fixed incrementally; good code on a bad data model must be rewritten. Data shape is also the highest-cost thing to change after real data exists — it deserves the design attention first.

<!-- RULE END: DESIGN-DATA-001 -->
---

<!-- RULE START: DESIGN-DEBT-001 -->
## Rule DESIGN-DEBT-001

**Domain**: architecture
**Severity**: Medium
**Scope**: Repo
**Mandatory**: false

### Trigger
When a shortcut is deliberately taken during design or implementation (hardcoded value, skipped edge case, missing migration path, "temporary" workaround).

### Statement
Shortcuts are legal only when logged in a tech-debt register at the moment they are taken, each entry naming: what was skipped, why now, the risk while it stands, and the REPAYMENT TRIGGER — the concrete event that forces the fix ("before adding a second provider", "when rule count exceeds 1000"). A shortcut without a trigger is not debt, it is decay. Silent shortcuts are violations regardless of size.

### Violation
```
Implementer hardcodes the port and single-tenant assumption, mentions it nowhere.
Six sessions later a second repo silently collides with the first.
```

### Pass
```
DEBT-014: retrieval assumes single graph per daemon. Why: multi-graph adds 2 days,
one repo today. Risk: cross-repo rule bleed if shared. Repayment trigger: the moment
a second repo installs writ. (Logged in TECH_DEBT.md; trigger fired → fixed in D4-02.)
```

### Enforcement
guardrail-check skill: `log tech debt` entries; review flags TODO/hardcode diffs without a register entry.

### Rationale
Shortcuts are how projects ship — the danger is only in losing track of them. A trigger converts vague "we should fix this someday" into a mechanical if-then a future session can enforce, which is the only form of "someday" that survives AI session amnesia.

<!-- RULE END: DESIGN-DEBT-001 -->
---

<!-- RULE START: DESIGN-FAIL-001 -->
## Rule DESIGN-FAIL-001

**Domain**: architecture
**Severity**: High
**Scope**: Repo
**Mandatory**: false

### Trigger
When a design or spec is about to be presented for approval.

### Statement
Before approval, the design doc enumerates its top failure modes: for each — what breaks it (input, load, dependency outage, bad data), the blast radius (what the user loses), how it would be detected, and how it recovers. A design with no failure-mode section is incomplete. "It won't fail" is not an entry.

### Violation
```
Spec ships with features and data model only. First failure analysis happens in
production when the sync job silently drops records.
```

### Pass
```
## Failure modes
1. Embedded DB file corrupted (power loss mid-write) → all rule retrieval down →
   detected by health endpoint → recover: rebuild from bible/ markdown (source of truth).
2. ONNX model missing → queries fail loudly at startup, not silently degraded →
   recover: scripts/export_onnx.py.
3. Port collision with another repo's daemon → detected at bind → per-repo port hash avoids.
```

### Enforcement
Design review gate: approval blocked until the failure-mode section exists and each entry has detect + recover.

### Rationale
Enumerating failure modes is the cheapest moment to change a design — one paragraph now versus an incident later. It also forces the "what is the source of truth / what can be rebuilt" question, which drives the most robust architectures.

<!-- RULE END: DESIGN-FAIL-001 -->
---

<!-- RULE START: DESIGN-OPTIONS-001 -->
## Rule DESIGN-OPTIONS-001

**Domain**: architecture
**Severity**: Critical
**Scope**: Repo
**Mandatory**: false

### Trigger
When presenting design or architecture options to a non-technical decision-maker for a choice — in brainstorming, architecture exploration, grill sessions, or plan reviews.

### Statement
Every option presented must carry, in plain language: (1) what it means in one everyday sentence (analogy allowed), (2) cost now (build time/complexity), (3) cost later (what becomes harder to change), (4) main risk and what failure would look like, (5) a clear recommendation with the reason stated in terms of the project's goals — never in terms of engineering ideology. Jargon without translation is a violation. Presenting options without a recommendation is a violation: the AI has the knowledge; abstaining transfers the decision to the person least equipped to make it.

### Violation
```
"Option A: event-driven CQRS with saga orchestration. Option B: monolithic layered
architecture with repository pattern. Which do you prefer?"
(No translation, no costs, no recommendation — the user cannot answer this.)
```

### Pass
```
"Option A — one program that does everything (like one shop with all counters inside).
Fastest to build (~2 days), easiest to debug. Gets messy only if we later need parts
to scale separately. Option B — separate small programs talking over messages (like
separate shops with couriers between them). ~2 weeks, harder to debug, pays off only
at team scale. Recommendation: A — nothing in your goals needs B, and we can split
later at a known seam."
```

### Enforcement
Design review checklist: each option has the 5 elements; response contains an explicit "Recommendation:" line; response volunteers at least one cross-cutting risk outside the framed options, or states "no cross-cutting risks identified" with the reasoning shown.

### Rationale
The human's contribution is judgment about goals, budget, and appetite for risk — not engineering knowledge. Options phrased in engineering terms force the human to judge what they cannot judge; options phrased as cost/risk/goal-fit let them exercise the judgment they actually have.

<!-- RULE END: DESIGN-OPTIONS-001 -->
---

<!-- RULE START: DESIGN-REVERSE-001 -->
## Rule DESIGN-REVERSE-001

**Domain**: architecture
**Severity**: High
**Scope**: Repo
**Mandatory**: false

### Trigger
When presenting an architecture or design decision for approval — technology choice, data model, module boundary, protocol, storage format.

### Statement
Every decision presented for approval is classified as a ONE-WAY DOOR (expensive to reverse: database choice, data format on disk, public API shape, framework) or a TWO-WAY DOOR (cheap to reverse: internal function structure, library behind an adapter, naming). One-way doors get the full options-and-tradeoffs treatment and explicit user sign-off. Two-way doors are decided by the AI immediately with a one-line note — burning the user's attention on reversible choices is a violation.

### Violation
```
AI asks the user to choose between two internal helper-module layouts (reversible in
an hour) with a 4-option question — while silently picking the database (one-way door)
without presenting alternatives.
```

### Pass
```
"Two decisions today. One-way door: storage engine — options A/B/C with tradeoffs below,
your call. Two-way door: I split the parser into 3 files; reversible anytime, no action needed."
```

### Enforcement
Design review. Decision docs carry a `door: one-way|two-way` tag per decision.

### Rationale
A non-technical decision-maker has limited judgment budget. Spending it on reversible choices exhausts it before the choices that actually matter. Classifying doors routes human attention to exactly the decisions where being wrong is expensive.

<!-- RULE END: DESIGN-REVERSE-001 -->
---

<!-- RULE START: DESIGN-SIMPLE-001 -->
## Rule DESIGN-SIMPLE-001

**Domain**: architecture
**Severity**: High
**Scope**: Repo
**Mandatory**: false

### Trigger
When proposing a design, architecture, module map, or spec — during brainstorming, architecture exploration, roadmap writing, or build-pipeline design steps.

### Statement
Every design proposal must include the simplest viable option as one of the candidates, and every unit of complexity beyond it (extra service, extra layer, extra abstraction, queue, cache, plugin system) must be justified by a NAMED, CURRENT requirement — not a hypothetical future one. "We might need it later" is not a justification; it is the definition of speculative complexity. If the simplest option is rejected, the design doc states exactly which requirement it fails.

### Violation
```
Design proposes: API gateway + 3 microservices + message queue + Redis cache
for an app with 1 user and no measured load. Justification: "scalable, future-proof."
The simple option (one process + SQLite) was never presented.
```

### Pass
```
Option A (recommended): single FastAPI process + SQLite. Meets all stated requirements.
Option B: adds a job queue — only needed IF background exports exceed 30s (not yet observed).
Decision: A. Revisit B when export timing is measured, not before.
```

### Enforcement
Design review. Reviewer asks for each component: "which stated requirement dies without this?" Components with no answer are cut.

### Rationale
AI models trained on big-company codebases default to big-company architecture. For a solo/small project, every speculative component is pure carrying cost: more code to review, more failure modes, more for the human to judge without the knowledge to judge it. Simplicity is the only defense a non-expert reviewer has — a simple design can be understood and therefore checked.

<!-- RULE END: DESIGN-SIMPLE-001 -->
---

<!-- RULE START: DESIGN-SKELETON-001 -->
## Rule DESIGN-SKELETON-001

**Domain**: architecture
**Severity**: High
**Scope**: Repo
**Mandatory**: false

### Trigger
When sequencing a roadmap or phase plan for a new system or major feature.

### Statement
The roadmap's first buildable milestone is a walking skeleton: the thinnest end-to-end slice that exercises every major component with real (not mocked) connections — even if each component does almost nothing. Feature depth comes after the skeleton stands. A roadmap that builds one component to completion before any end-to-end path exists is a violation.

### Violation
```
Phase 1: complete the entire storage layer (5 weeks).
Phase 2: complete the entire API layer.
Phase 3: connect them. ← integration risk discovered at week 10.
```

### Pass
```
Phase 1: one query flows end-to-end — CLI → API → retrieval → DB → answer (ugly, minimal).
Phase 2+: deepen each stage. Integration risk retired in week 1.
```

### Enforcement
Roadmap review: check phase 1 output crosses every planned seam.

### Rationale
Integration points are where designs actually fail; component internals rarely sink a project. The skeleton surfaces seam problems when the code is small enough to change freely — and gives a non-technical owner something running to react to immediately, which is their strongest feedback channel.

<!-- RULE END: DESIGN-SKELETON-001 -->
