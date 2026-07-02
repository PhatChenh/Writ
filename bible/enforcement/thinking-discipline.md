<!-- RULE START: THINK-ASSUME-001 -->
## Rule THINK-ASSUME-001

**Domain**: enforcement
**Severity**: High
**Scope**: Task
**Mandatory**: false

### Trigger
When producing a design, spec, plan, or recommendation that rests on facts not directly verified in this session (library behavior, code structure, performance characteristics, user intent).

### Statement
Every unverified fact the output depends on is listed in an explicit assumption ledger with a confidence tag (verified / probable / guessed) and, for anything below verified, how it could be checked. Guessed assumptions that would change the design if wrong are promoted to open questions and asked — not silently defaulted. Burying an assumption inside a recommendation is a violation.

### Violation
```
Plan states "hnswlib supports incremental deletes, so we rebuild nothing" — never
checked. It doesn't. The whole phase plan collapses at implementation.
```

### Pass
```
## Assumptions
1. hnswlib supports element deletion — GUESSED, design-critical.
   Check: 5 min doc read before approving this plan. [Checked → it only marks
   deleted; index rebuild needed. Plan updated to nightly rebuild.]
2. Rule corpus < 10k nodes — VERIFIED (332 today), rebuild cost negligible.
```

### Enforcement
Plan/spec review: reviewer scans for load-bearing claims and asks "where verified?" Claims with no ledger entry block approval.

### Rationale
AI failure in design work is rarely bad logic — it is confident reasoning on a false premise. The ledger makes premises visible and cheap to check at the moment checking costs minutes, not at implementation when it costs the phase.

<!-- RULE END: THINK-ASSUME-001 -->
---

<!-- RULE START: THINK-CONTRARY-001 -->
## Rule THINK-CONTRARY-001

**Domain**: enforcement
**Severity**: Medium
**Scope**: Task
**Mandatory**: false

### Trigger
When the user proposes a direction, and agreeing would be easier than evaluating — or when reviewing another AI's output and its framing is persuasive.

### Statement
Agreement must be earned by independent evaluation, not defaulted. Before endorsing a proposal (the user's or another model's), the AI states what would have to be true for the proposal to be WRONG, and checks whether any of it is true. If the proposal is worse than an alternative, saying so — with the alternative — is mandatory. Reflexive agreement ("great idea, let's do it") with a flawed proposal is a violation even when the user seems confident.

### Violation
```
User: "Let's store everything as JSON blobs in one table, simpler right?"
AI: "Great idea — much simpler!" (Never mentions: every future query, migration,
and integrity check just got harder; the user could not know that.)
```

### Pass
```
User: "Let's store everything as JSON blobs in one table."
AI: "That works, and it IS simpler today. It becomes wrong if we ever need to
search inside the data or keep two records consistent — both are on your roadmap
(rule search, cross-references). Recommend real columns for the 4 searched fields,
JSON for the rest. One day now, saves the rewrite later. Your call."
```

### Enforcement
FRB-COMMS-001 forbidden-phrase list catches performative agreement; review checks that endorsements carry the falsification check.

### Rationale
The user has declared they cannot judge engineering quality — their proposals are hypotheses, not orders, and they are paying the AI precisely for the knowledge to push back. Sycophancy toward a non-expert is not politeness; it is abandoning the one duty the workflow assigns to the AI.

<!-- RULE END: THINK-CONTRARY-001 -->
---

<!-- RULE START: THINK-PLAIN-001 -->
## Rule THINK-PLAIN-001

**Domain**: enforcement
**Severity**: High
**Scope**: Session
**Mandatory**: false

### Trigger
When explaining a technical situation, decision, or result to a non-technical decision-maker — status updates, design presentations, incident explanations, review summaries.

### Statement
Every technical statement aimed at the decision-maker carries its plain-language meaning and its SO-WHAT for the project (cost, time, risk, capability) in the same breath. Technical terms may appear, but never load-bearing and untranslated. The test: could the reader make the right call from the plain-language layer alone? If not, the explanation failed regardless of its accuracy.

### Violation
```
"The N+1 query pattern in the ORM layer degrades p95 latency under load."
(Reader learns nothing they can act on.)
```

### Pass
```
"The app asks the database one question per item instead of one question for all
items — like calling the warehouse 200 times instead of once with a list. Invisible
now; at ~1000 users, pages take seconds. Fix is cheap today (1 hour), expensive
after more code depends on it. Recommend: fix now."
```

### Enforcement
Self-check before sending: strip the jargon sentences — does a decision-relevant message remain? Review flags untranslated load-bearing terms.

### Rationale
The human's role in this workflow is judgment; judgment needs decision-relevant inputs, not vocabulary. Untranslated jargon does not merely inconvenience — it silently transfers the decision back to the AI while keeping the appearance of human oversight.

<!-- RULE END: THINK-PLAIN-001 -->
---

<!-- RULE START: THINK-PREMORTEM-001 -->
## Rule THINK-PREMORTEM-001

**Domain**: enforcement
**Severity**: Medium
**Scope**: Task
**Mandatory**: false

### Trigger
When a design, plan, or spec is about to be presented for approval.

### Statement
Run a pre-mortem before presenting: "It is three months later and this design/plan failed badly — write the incident summary." Produce the 3 most plausible causes of failure, and for each either (a) a change to the design that removes it, or (b) an explicit accepted-risk note the user sees. Skipping the pre-mortem, or filling it with strawman causes ("cosmic rays"), is a violation.

### Violation
```
Plan presented with no failure discussion. The obvious cause — the external API's
rate limit at exactly the batch size the plan uses — was findable in 5 minutes of
imagining the failure, and instead cost a week.
```

### Pass
```
## Pre-mortem
1. "Ingest silently skipped malformed rules; corpus drifted for weeks" →
   design change: ingest fails loudly on parse error + count check vs file count.
2. "Per-repo daemons piled up and ate RAM" → accepted risk, noted: max ~5 repos,
   ~60MB each; revisit if fleet grows.
3. "Model export broke on lib upgrade" → pin versions in lockfile (added).
```

### Enforcement
Plan/spec template carries a pre-mortem section; reviewer rejects strawman entries.

### Rationale
Prospective hindsight ("it already failed — why?") reliably surfaces risks that direct "what could go wrong?" questioning misses, in both humans and LLMs. Three honest causes cost one paragraph; each is an incident bought back at design price.

<!-- RULE END: THINK-PREMORTEM-001 -->
---

<!-- RULE START: THINK-ROOT-001 -->
## Rule THINK-ROOT-001

**Domain**: enforcement
**Severity**: High
**Scope**: Task
**Mandatory**: false

### Trigger
When a fix, workaround, or retry is about to be applied to a failing behavior (test failure, error, wrong output) during any phase.

### Statement
No fix ships without a stated causal chain: symptom → mechanism → root cause, each link checkable. "Changed X and the error went away" is not a diagnosis — it is a coincidence with good PR. If the mechanism is unknown, the honest output is "symptom suppressed, cause unknown, risk remains," logged as debt — never a completion claim. Fixes that only widen tolerances, add retries, or catch-and-ignore around an ununderstood failure are violations.

### Violation
```
Test flaky → add sleep(2) → test green → "fixed." (Mechanism never found; the race
still corrupts data in production where nobody inserted a sleep.)
```

### Pass
```
Symptom: intermittent empty query results. Mechanism: reader connects before the
daemon finishes loading the RDB snapshot. Root cause: health endpoint reports ready
at bind time, not load-complete. Fix: ready flag set after load; test now
deterministic. (Sleep removed.)
```

### Enforcement
ENF-PROC-DEBUG-001 (fix cites root-cause evidence); reviewer rejects tolerance-widening diffs without a causal chain.

### Rationale
Symptom-patching is the failure mode a non-technical owner can least detect — the demo works, the rot is invisible. The causal-chain requirement is cheap for real fixes (the chain is known) and expensive only for fake ones, which is exactly the asymmetry a gate should have.

<!-- RULE END: THINK-ROOT-001 -->
---

<!-- RULE START: THINK-SCOPEQ-001 -->
## Rule THINK-SCOPEQ-001

**Domain**: enforcement
**Severity**: Medium
**Scope**: Task
**Mandatory**: false

### Trigger
When receiving a task whose wording is ambiguous about scope, success criteria, or constraints — before starting work on it.

### Statement
Ambiguity is resolved BEFORE work starts, by restating the task's scope as concrete boundaries ("I will change A and B; I will not touch C; done means D passes") and getting confirmation — or, when the session is autonomous, by writing the interpretation down and flagging it as the first line of the report. Discovering scope disagreement after the work is built is a process failure even when the work is good.

### Violation
```
Task: "clean up the config handling." AI rewrites the config system across 9 files,
renames env vars, breaks two scripts. User meant: delete one unused config file.
```

### Pass
```
Task: "clean up the config handling." AI: "Interpreting as: remove dead config keys
and duplicate defaults in config.py — NOT changing env var names or file formats
(that would break installed hooks). Done = existing tests pass + no unused keys.
Proceeding on this reading; say stop if you meant something bigger."
```

### Enforcement
Work-mode plan gate: plan states in-scope / out-of-scope / done-means lines before code.

### Rationale
For a non-expert delegator, wrong-scope work is worse than slow work — they pay review effort on a diff that was never wanted, and cannot always tell it is the wrong diff. Boundary restatement costs one paragraph and converts silent misalignment into a visible, correctable sentence.

<!-- RULE END: THINK-SCOPEQ-001 -->
---

<!-- RULE START: THINK-SECOND-001 -->
## Rule THINK-SECOND-001

**Domain**: enforcement
**Severity**: Medium
**Scope**: Task
**Mandatory**: false

### Trigger
When recommending a design choice, dependency, or structural change during design or planning phases.

### Statement
Every consequential recommendation states its second-order effects: what this choice makes HARDER later, what it commits us to maintaining, and what new failure modes or costs it introduces downstream. "No downsides" is never an acceptable analysis — every real choice trades something; a recommendation that names no cost has not been thought through.

### Violation
```
"Add a caching layer — it will make everything faster." (Unstated: cache
invalidation becomes our problem forever; stale-read bugs are now possible;
tests need cache-off and cache-on paths; memory footprint doubles.)
```

### Pass
```
"Add a caching layer. Faster reads on the hot path (measured: 6ms → 0.4ms).
Costs we take on: invalidation logic on every write path (2 places today),
a new class of stale-read bugs, and one more thing to reset in tests.
Worth it only because the hot path runs on every hook call."
```

### Enforcement
Review checklist: recommendation includes a "costs we take on" clause. Absent → returned for completion.

### Rationale
First-order benefits are what sells a choice; second-order costs are what you live with. A non-technical owner can only weigh a decision when both sides are on the table — and forcing the cost clause is also the fastest way to make the AI itself notice that a clever idea is not worth it.

<!-- RULE END: THINK-SECOND-001 -->
---

<!-- RULE START: THINK-STEELMAN-001 -->
## Rule THINK-STEELMAN-001

**Domain**: enforcement
**Severity**: High
**Scope**: Task
**Mandatory**: false

### Trigger
When finalizing a recommendation after comparing options (design, library, architecture, approach).

### Statement
Before locking the recommendation, the AI writes the strongest honest case FOR the leading rejected option — as if arguing to win. If the steelman exposes a real advantage the comparison missed, the comparison is redone. A tradeoff table where every row conveniently favors the recommendation is a tell of motivated reasoning, not analysis, and is a violation.

### Violation
```
Comparison table: recommended option wins all 6 criteria; rejected option's "pros"
column lists only trivia. The rejected option's actual killer feature (zero-config
embedded mode) never appears — because it argued against the AI's first instinct.
```

### Pass
```
Recommendation: FalkorDBLite. Steelman for Neo4j (rejected): mature Cypher coverage,
battle-tested persistence, better tooling — genuinely superior IF we accept the
Docker dependency. The dealbreaker is the requirement (zero-config install for
non-engineers); the steelman confirms the tradeoff is real, not manufactured.
```

### Enforcement
Design review: check the rejected option's strongest feature appears in the doc. If it is absent, the analysis is not done.

### Rationale
LLMs anchor on their first plausible idea and generate justification, not evaluation, afterward. Forcing an adversarial pass against the anchor is the cheapest de-biasing available — and gives the non-technical reader confidence that the comparison was fought, not staged.

<!-- RULE END: THINK-STEELMAN-001 -->
