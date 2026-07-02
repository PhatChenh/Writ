# WORKFLOW_BLUEPRINT — Using AI effectively when you can't judge the engineering

Audience: you — the owner who supplies judgment (goals, budget, risk appetite) but not
software-engineering knowledge. Every item below exists to convert "trust the AI's prose"
into "trust an artifact a machine checked or a second, hostile AI attacked."

Scope: everything OUTSIDE the Writ rule engine itself. Writ injects rules; this document
is the surrounding system that makes the whole workflow safe for a non-coder to drive.
CodeGraph derivative tools referenced by section number come from
`/Users/lap14806/all-projects/codegraph-piggyback/BLUEPRINT.md`.

---

## The four principles everything below serves

1. **Trust artifacts, not claims.** An AI saying "done, tests pass" is a claim. A CI run,
   a diff, a rendered diagram, a query result is an artifact. Every workflow upgrade should
   replace one claim with one artifact.
2. **Fresh eyes grade homework.** The AI that wrote something never judges it. Different
   session, ideally different model. Disagreement between two AIs is your highest-value
   signal — it marks exactly the spots worth your attention.
3. **Determinism before inference.** Anything checkable by a script (does this file exist?
   who calls this function? did tests run?) must be checked by a script, not by an LLM
   re-reading code. LLMs get only the judgment calls. (This is codegraph-piggyback's core
   thesis — lean on it hard.)
4. **Route your attention to one-way doors.** You have limited review energy. Spend it only
   on decisions that are expensive to reverse (data formats, external APIs, tech choices).
   Everything reversible, let the AI decide and log. (Now enforced as bible rule
   DESIGN-REVERSE-001.)

---

## Tier 1 — Best ROI (do these first; each pays for itself within weeks)

### 1.1 plan-verifier (codegraph §2.2) ⭐
**What:** a script that mechanically fact-checks every plan before you approve it — does the
file the plan wants to edit exist? does the "new" function name collide? does the thing being
removed have 12 callers the plan never mentions?
**Why for you specifically:** your single biggest exposure is approving a plan built on a
hallucinated fact. You cannot catch a ghost file by reading the plan; a SQL lookup catches it
in milliseconds, for free.
**How:** build it as specced in the codegraph BLUEPRINT; wire as a mandatory `/build-pipeline`
step between spec and plan approval. Effort M. **This is the single highest-leverage item in
this document.**

### 1.2 plan-visualizer (codegraph §3.2) ⭐
**What:** renders any approved-to-be plan as a picture over the current code map — what
changes (amber), what's new (dashed), what's removed (strikethrough), and which existing
pieces depend on the changed code.
**Why:** you evaluate pictures far better than walls of engineering prose. "Why does changing
retry logic touch billing?" is a question you CAN ask — and it's exactly the right question.
**How:** depends on plan-verifier (1.1) + ssot-diagram P3/P5. Build order in the codegraph
BLUEPRINT §5 already sequences this correctly. Effort S once dependencies ship.

### 1.3 CI on every repo — the machine judge
**What:** GitHub Actions (or equivalent) that runs lint + type check + full test suite on
every push. Green check or red X, visible to you, produced by a machine no AI can sweet-talk.
**Why:** this is your judgment surrogate. When an AI claims "all 282 tests pass," you should
never take its word — the CI badge is the truth. It also catches the classic cheap-model move
of quietly weakening tests: a separate job can fail when test count DROPS.
**How:** one workflow file per repo; add a `test-count-guard` step (fail if collected test
count decreases vs main without a PR label acknowledging it). Effort S. Do this before any
more feature work anywhere.

### 1.4 Cross-model adversarial review, everywhere (extend what you have)
**What:** you already run DeepSeek-implements / Opus-reviews for code. Extend the same
pattern one level up: **designs and specs get a hostile reviewer too.** Before you approve a
design, a fresh session of a different model is prompted: "find the three biggest flaws,
hidden costs, and simpler alternatives to this design. You win by killing it."
**Why:** your bible now has THINK-STEELMAN-001/THINK-PREMORTEM-001 forcing the author to
self-attack — but a genuinely independent attacker with no authorship bias catches what
self-review structurally cannot. Where the two models disagree is where you should look.
**How:** add a `design-reviewer` agent definition mirroring the upgraded
`writ-code-quality-reviewer` posture; run it in /architecture-grill and the /build-pipeline
design step. Effort S — it's a prompt file.

### 1.5 Decision log discipline (+ decision-index, shipped)
**What:** every locked decision recorded with context/options/choice/consequences (now bible
rule DESIGN-ADR-001), anchored to code by the shipped codegraph decision-index so staleness
is detected mechanically.
**Why:** in an all-AI team, nobody remembers why. The decision log is the only institutional
memory, and it's what stops session #20 from "improving away" the fix session #12 made. You
already lived this (the "no asyncio in db.py" invariant).
**How:** habit + template, already half in place via update-project-docs skill. Ensure every
repo has a `DECISIONS.md` and the decision-index hook installed. Effort XS.

### 1.6 One-command run + smoke check per project
**What:** every project has `make run` (or equivalent) that starts the real app, and
`make smoke` that exercises one end-to-end happy path and prints PASS/FAIL.
**Why:** your strongest native judgment channel is *using the product*. If starting the app
requires engineering knowledge, you're locked out of your own best review tool. The walking-
skeleton rule (DESIGN-SKELETON-001) guarantees there's always something runnable to check.
**How:** demand it as a phase-1 deliverable of every project (it's now a bible-backed ask).
Effort XS per repo.

---

## Tier 2 — Highly recommended (structural safety, do within the next month)

### 2.1 changeset-context / branch brief (codegraph §1.2)
Auto-generated "what this change touches + who depends on it + which decisions anchor here"
brief, injected when work starts on a branch. Kills the #1 cheap-model failure — editing with
no blast-radius awareness — and saves the tokens the agent would spend rediscovering
structure. Effort S–M.

### 2.2 Multi-model judge panel for one-way doors
For irreversible decisions only (stack choice, data format, hosting): ask 2–3 different
models the same question **independently** (fresh contexts, same brief), then have a third
session diff their recommendations and present agreement/disagreement to you in plain
language. Agreement → proceed cheaply. Disagreement → the disagreement text itself tells you
what to probe. Effort XS (it's a habit + a small orchestration prompt), payoff on exactly the
decisions that can sink a project.

### 2.3 Paved-road project template
One template repo (cookiecutter) containing: CI workflow, ruff+mypy+pytest config, pre-commit
hooks, `.gitignore`, CLAUDE.md skeleton with your global contract, Writ install hook,
codegraph init, `DECISIONS.md`, `TECH_DEBT.md`, `make run/smoke/test`. Every new project
starts with all guardrails live instead of accreting them. Your /init-project skill should
emit this instead of just docs. Effort M once, XS forever after.

### 2.4 Automated hygiene you never have to judge
Machine-enforced, zero-judgment-needed safety floor on every repo:
- **Dependabot/renovate** — dependency updates with CI proof.
- **Secret scanning + pre-commit secret hook** — you can't assess crypto; you CAN prevent
  keys in git mechanically.
- **bandit / npm audit in CI** — known-vulnerability floor.
- **Formatter + linter as errors** — style disputes never reach you.
Effort S total via the template (2.3).

### 2.5 drift-digest (codegraph §3.4)
Weekly "what changed since you last looked," in component vocabulary, computed not
remembered: files changed per component, new/removed functions, decisions gone stale,
new unresolved references. This is your standing situational awareness across multiple
repos without reading a single diff. Effort S.

### 2.6 Token/cost routing discipline (efficient-mode, systematized)
Standing policy: expensive models (Opus/Fable) do design, review, and judgment; cheap models
(DeepSeek Flash, Haiku) do mechanical implementation, migrations, boilerplate; deterministic
scripts do everything checkable. You already have the efficient-mode skill — promote it from
"skill you remember to invoke" to default posture in every orchestration prompt. Effort XS,
compounding savings.

---

## Tier 3 — Should have (quality of life, next quarter)

### 3.1 repo-map at session start (codegraph §1.3)
Token-budgeted orientation map injected at SessionStart — every fresh session starts knowing
the repo's load-bearing symbols instead of spending 20 tool calls discovering them. Effort S.

### 3.2 symbol biography (codegraph §3.3)
"Tell me everything about this piece" for non-coders: what it is, who depends on it, which
decisions govern it, its git history in dates and commit subjects. Your side-panel answer to
"can I let the AI touch this?" Effort S.

### 3.3 Weekly repo health report (cron agent)
Scheduled agent that reads CI history, test-count trend, TECH_DEBT.md triggers ("has any
repayment trigger fired?"), stale decisions, and friction-log summaries (writ
analyze-friction), and writes you a 10-line plain-language report. Turns your project
portfolio into something you supervise like a manager reading dashboards. Effort S.

### 3.4 Behavior guide + reset scripts (you have the skill — apply it everywhere)
update-behavior-guide generates non-coder testing guides + setup/reset scripts. Run it at
every phase boundary on every project so you always have a click-through script for manual
acceptance. Effort XS per phase.

### 3.5 Golden-master snapshots for things you can eyeball
For anything with visual or textual output (reports, rendered pages, CLI output): snapshot
tests that fail on ANY output change, with a side-by-side "old vs new" artifact for you.
You may not judge code, but you judge "the invoice now looks wrong" instantly. Effort S.

### 3.6 Issue tracker as scope memory
GitHub Issues (or equivalent) as the single place where scope lives: every phase = milestone,
every cut/deferred item = issue. Stops "silent scope narrowing" across sessions because the
backlog is diffable. Pairs with DESIGN-CUT-001's scope ladder. Effort XS.

---

## Tier 4 — Nice to have (build when the pain appears)

- **impact pre-commit gate** (codegraph §2.3) — commit-time blast-radius warning; advisory
  first. The read-time (1.1 impact-analyzer) and CI layers already cover most of it.
- **dead-code-finder / doc-coverage** (codegraph §1.4) — hygiene reports; run quarterly.
- **Design tournaments** — for the rare BIG design, 3 independent designs from 3 angles
  (cheapest-first, safest-first, fastest-to-ship), judged by a panel, best ideas grafted.
  Expensive; reserve for one-way doors that survive 2.2's judge panel undecided.
- **Interactive explainers** (explain-codebase / drawing-html-diagram skills) — on-demand
  guided tours of any subsystem in plain Vietnamese/English; use when you inherit or revisit
  a codebase after months.
- **Friction-log analytics dashboard** — writ already logs gate denials, rule hits, token
  spend per session; a small HTML dashboard over `workflow-friction.log` shows which rules
  actually fire and which never do (candidates for pruning — rules are only useful if
  retrieved).
- **Voice/async status habit** — end-of-session agent writes a 5-line plain-language status
  to a STATUS.md you read like a text message. (update-project-docs already approximates
  this; formalize the 5-line ceiling.)

---

## What changed in Writ today (so this document is complete)

- `writ-code-quality-reviewer` agent rewritten: adversarial posture against cheap-worker
  diffs — 10 named failure modes (stub theater, test gaming, hallucinated APIs, silent scope
  narrowing…), mandatory verification protocol (run tests yourself, mutation spot-check,
  blast-radius via codegraph), and a `verification` evidence block required for any approval.
- New bible domain content, retrievable by the RAG pipeline:
  - **DESIGN-*** (architecture): SIMPLE-001 simplest-option-first · REVERSE-001 one-way/two-way
    doors · BORING-001 innovation tokens · OPTIONS-001 plain-language options with mandatory
    recommendation · FAIL-001 failure-mode enumeration · SKELETON-001 walking skeleton first ·
    BUY-001 build-vs-buy check · DATA-001 data model first · ADR-001 decision records ·
    DEBT-001 debt register with repayment triggers · CUT-001 scope-cut ladder.
  - **THINK-*** (enforcement): ASSUME-001 assumption ledger · STEELMAN-001 steelman the rejected
    option · PREMORTEM-001 pre-mortem before approval · SECOND-001 second-order costs ·
    PLAIN-001 plain-language + so-what · CONTRARY-001 earned agreement, mandatory pushback ·
    ROOT-001 causal chain before any fix · SCOPEQ-001 scope restatement before work.
  - Three over-engineering rules rewritten with explicit scope boundaries so cheap models stop
    misapplying them to small projects: ARCH-EVENT-001 (no event bus without a decoupling
    force), SOLID-OCP-002 (exhaustive match over closed sets is good code), ARCH-LAYER-002
    (no mapper layers around behavior-free CRUD models).
