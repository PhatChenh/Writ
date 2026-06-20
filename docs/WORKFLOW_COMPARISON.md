# Workflow comparison: my setup (ai_kms) vs Writ author

Side-by-side comparison to understand what changes when adopting Writ, and what to keep from my existing approach.

---

## Constraint storage

| Aspect | My approach (ai_kms) | Writ author |
|--------|---------------------|-------------|
| **Where** | `CONSTRAINTS.md` flat file at repo root | Neo4j graph DB, 18-domain `bible/` corpus |
| **Format** | `### C-NN · Title` with Severity, Domain, Rule, Why, Danger signal, Source | Markdown with frontmatter (Domain, Severity, Scope, Mandatory) + body (Trigger, Statement, Violation, Pass, Enforcement, Rationale) |
| **Retrieval** | Full file loaded every session (~15 constraints) | 5-stage RAG: only relevant rules per query. Mandatory rules (ENF-*) always loaded separately |
| **Enforcement** | PostToolUse grep hooks catch violations at write-time | RAG injection at think-time + static analyzers in `run-analysis.sh` |
| **Scale** | Works at ~15-20 constraints. Would bloat prompt at 100+ | Tested at 10K rules (1.17M tokens → ~1,600 tokens via RAG) |
| **Evolution** | Manual edit of CONSTRAINTS.md. Source field tracks origin | Confidence tiers (speculative → battle-tested), graduation logic, SUPERSEDES edges |

**What changes with Writ:** Constraints move into the graph as rules. My `C-NN` constraint IDs map to Writ rule IDs. My "Danger signal" maps to Writ's "Violation" + "Trigger" fields. My PostToolUse hooks stay — they enforce at a different layer (code write-time vs think-time).

---

## ADR (Architecture Decision Records)

| Aspect | My approach (ai_kms) | Writ author |
|--------|---------------------|-------------|
| **Where** | `docs/architecture/system_adr/NNNN-slug.md` (system-wide) + `docs/architecture/phaseN/adr/` (domain-specific) | No separate ADR folder. Decisions embedded as rules with SUPERSEDES edges |
| **Format** | Title, Status (accepted), Considered Options, Consequences | Rule format with confidence tier. Deprecated decisions get SUPERSEDES edge to replacement |
| **Numbering** | Sequential `0001-0020` | Rule IDs by domain (SEC-INJ-001, ARCH-DRY-001, etc.) |
| **Linking** | Cross-referenced in CONSTRAINTS.md Source fields, CLAUDE.md, OPEN_QUESTIONS.md | Graph edges (RELATED_TO, SUPERSEDES, CONFLICTS_WITH) |
| **Lifecycle** | Static once accepted. No formal deprecation | Confidence tiers + SUPERSEDES. Old decisions stay as deprecated nodes, not deleted |

**What changes with Writ:** Two options — (a) keep ADRs as separate files for human readability AND create corresponding Writ rules for AI retrieval, or (b) migrate ADRs fully into Writ rules. Option (a) is safer: ADRs are for humans to read, Writ rules are for AI to retrieve. The SUPERSEDES edge is strictly better than my current approach of manually noting "replaces ADR-NNNN" in text.

---

## Tech debt tracking

| Aspect | My approach (ai_kms) | Writ author |
|--------|---------------------|-------------|
| **Where** | `TECH_DEBT.md` flat file at repo root | Friction JSONL log + monthly reviews (`writ analyze-friction`) |
| **Format** | `### TD-NNN · Title` with Status, Phase, Risk, What, Why deferred, Touches, Source | JSONL events: gate denials, approvals, phase transitions, rule loads, quality judge overrides |
| **Analysis** | Manual review. Check when touching related code | Automated: rules with <50% stick rate, trim candidates (<5 activations in 90d), graduation candidates |
| **Resolution** | Manual status update (OPEN → RESOLVED) | Rules graduate (speculative → battle-tested) or get trimmed |
| **Richness** | Very rich entries: risk assessment, deferred reasoning, exact files to touch | Event-based: less narrative, more quantitative |

**What changes with Writ:** Friction logging replaces manual TD tracking for recurring patterns. But some tech debts are one-off deferred tasks (e.g., "reconstruct lost behavior-inventory entries") that don't map to rules. Keep a lightweight TECH_DEBT.md for one-off deferred tasks; let Writ friction logs handle rule-based patterns.

---

## Open questions

| Aspect | My approach (ai_kms) | Writ author |
|--------|---------------------|-------------|
| **Where** | `OPEN_QUESTIONS.md` flat file at repo root | No equivalent. Questions are either resolved in rules or tracked as graph gaps |
| **Format** | `### OQ-NNN · Title` with Blocks, Status, Question, Context | N/A |
| **Lifecycle** | Open → Closed (with resolution). Blocks field tracks what's waiting | N/A |

**What changes with Writ:** Keep OPEN_QUESTIONS.md. Writ doesn't have a direct equivalent. When an OQ is resolved, the resolution becomes a rule or ADR in the graph.

---

## Hooks

| Aspect | My approach (ai_kms) | Writ author |
|--------|---------------------|-------------|
| **Count** | ~10 hooks | 33 hooks |
| **Location** | Inline in `.claude/settings.json` | External shell scripts in `.claude/hooks/` |
| **Purpose** | Code constraint enforcement (grep violations at write-time) | Workflow enforcement (mode/gate state machine) + RAG injection + friction logging |
| **Examples** | Vault write guard, threshold guard, logic-in-tools guard, prompt guard | RAG inject, gate check, mode transition, quality judge, pressure audit, context tracker |
| **Coexistence** | They don't overlap — different layers | |

**What changes with Writ:** Both sets of hooks run. My hooks catch code violations (PostToolUse grep). Writ hooks control workflow (UserPromptSubmit RAG injection, PreToolUse gate checks). No conflict.

---

## Session state

| Aspect | My approach (ai_kms) | Writ author |
|--------|---------------------|-------------|
| **State tracking** | `STATE.md` manually updated by `/update-state` command | Session state machine in `writ-session.py` (modes, phases, gates) |
| **Modes** | None — CLAUDE.md behavioral rules guide what AI should do | 4 modes: Discussion, Debug, Review, Work. Only Work has gates |
| **Gates** | None — process discipline via skill instructions + CLAUDE.md rules | Plan gate (plan.md must exist), Test gate (tests before code), Anti-cheat tokens |
| **Persistence** | STATE.md survives across sessions | Session state resets per session. Friction log persists |

**What changes with Writ:** STATE.md still useful for cross-session project state (Writ sessions reset). Writ modes add intra-session discipline. The mode system is the biggest workflow change — you'll need to explicitly enter Work mode before coding.

---

## Process workflow

| Aspect | My approach (ai_kms) | Writ author |
|--------|---------------------|-------------|
| **Pipeline** | `/build-pipeline` skill: design → spec → research → plan as isolated subagents | Mode system: Discussion → Work (plan gate → test gate → code) |
| **Artifacts** | Numbered folders: `docs/0_draft/` → `docs/1_design/` → `docs/2_specs/` → `docs/3_research/` → `docs/4_plans/` | `plan.md` + `capabilities.md` at project root (via writ-planner agent) |
| **Orchestration** | Skills orchestrate subagents | Agents are standalone roles (planner, implementer, test-writer) |
| **Approval** | CLAUDE.md behavioral rules: "wait for go-ahead" | Gate tokens: human must type approval phrase, filesystem token written |

**What changes with Writ:** My /build-pipeline is more sophisticated than Writ's plan gate. Keep /build-pipeline for complex multi-phase work. Writ's gate system adds enforcement (you MUST have a plan, not just SHOULD). They complement: /build-pipeline produces the plan, Writ gates verify it exists before coding proceeds.

---

## Agents vs skills

| Aspect | My approach (ai_kms) | Writ author |
|--------|---------------------|-------------|
| **Approach** | Skills for orchestration, skills call subagents | Standalone agents with restricted tools |
| **Defined** | `.claude/skills/` (11 agentbase-* skills) + global skills | `.claude/agents/` (6 role agents: explorer, planner, implementer, test-writer, spec-reviewer, code-quality-reviewer) |
| **Control** | Skills share conversation context, full tool access | Agents have isolated context, restricted tools (planner: Read/Glob/Grep/Write only) |

**What changes with Writ:** Writ's agents can be called by my skills. Best pattern: skills for orchestration (they have context), agents for isolated specialized roles (they have boundaries).

---

## Summary: what to keep, what to adopt, what to merge

### Keep as-is
- `OPEN_QUESTIONS.md` — Writ has no equivalent
- `STATE.md` + `/update-state` — cross-session state, Writ sessions reset
- PostToolUse grep hooks — different layer than Writ hooks
- `/build-pipeline` skill — more sophisticated than Writ's plan gate
- Numbered docs folders (`0_draft/` → `4_plans/`) for complex projects
- ADR folder structure — human-readable, complement Writ rules

### Adopt from Writ
- RAG-based constraint retrieval (replace full CONSTRAINTS.md load)
- Mode system (Discussion/Debug/Review/Work) for intra-session discipline
- Gate enforcement (plan + test gates) — CLAUDE.md rules can't enforce this
- Anti-cheat tokens for gate approval
- Friction logging for automated rule health analysis
- Confidence tiers for rule/constraint evolution
- SUPERSEDES edges for ADR deprecation

### Merge (both approaches combined)
- Constraints: keep human-readable format + store in Writ graph for RAG retrieval
- Tech debt: keep TECH_DEBT.md for one-off deferred tasks + Writ friction logs for pattern tracking
- ADRs: keep ADR files + create corresponding Writ rules with graph edges
- Hooks: both sets run simultaneously, no overlap
- Process: /build-pipeline produces plans, Writ gates verify plans exist
