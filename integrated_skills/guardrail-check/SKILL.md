---
name: guardrail-check
description: Use when adding constraints, logging tech debt, recording open questions, checking which guardrails apply before writing code, or auditing that existing code mechanically enforces active constraints. Triggers on "add constraint", "log tech debt", "open question", "check guardrails", "guardrail check", "audit constraints in", "constraint trace", "set up guardrails", "migrate constraints".
version: 2.0.0
---

# Guardrail Check

Manage project guardrails. **Phase 6 / D4-04 split:**

| Type | Source of truth | How written |
|------|-----------------|-------------|
| **Constraints** | **the Writ graph** (`PROJ-` Rule nodes, `authority=human`) | `bin/writ-project-rules.sh author` → also exported to committed `docs/rules/` |
| **Tech Debt** | `docs/TECH_DEBT.md` (flat) | append card |
| **Open Questions** | `docs/OPEN_QUESTIONS.md` (flat) | append card |

> **Why constraints differ.** Constraints are enforceable rules — they belong in the graph so Writ's retrieval/gates can surface them during coding. The graph is volatile, so every authored constraint is also exported to the committed `docs/rules/` (the system-of-record that survives a graph clobber). TD/OQ are *not* rules (deferred work / unresolved questions) — flat docs by design. See `WRIT-LOCAL-ADAPTATION.md` D4-04. ADRs are handled by `/grill` + `codebase-design-analysis`, not here.

**Engine:** `bin/writ-project-rules.sh` resolves the plugin root via `${CLAUDE_PLUGIN_ROOT}` (or the `plugin-root` marker), then runs against the CURRENT repo's graph/port (A-auto). Resolve it once:

```bash
WR="${CLAUDE_PLUGIN_ROOT:-$(cat "${CLAUDE_PLUGIN_DATA:-$HOME/.cache/writ}/plugin-root" 2>/dev/null)}"
PR="$WR/bin/writ-project-rules.sh"
```

---

## Mode Selection

| User says | Mode |
|-----------|------|
| "add constraint", "record constraint" | Write — Constraint (→ graph) |
| "log tech debt", "add debt" | Write — Tech Debt (→ flat) |
| "open question", "log question" | Write — Open Question (→ flat) |
| "check guardrails for X", "which constraints apply" | Review |
| "audit constraints in \<file\>", "constraint trace" | Audit |

---

## Mode 1a — Write Constraint (→ graph)

**Triggered by:** "add constraint", "record constraint"

A constraint becomes a `PROJ-` Rule node. The Rule schema needs more than the old flat card — collect all fields in ONE prompt (do NOT ask field by field):

| Rule field | Ask for | Notes |
|------------|---------|-------|
| `domain` | Domain (what class of risk) | free text, e.g. `Write Safety`, `DB Integrity` |
| `severity` | critical / high / medium / low | |
| `scope` | component / task / session / entity | code granularity; default `component` |
| `trigger` | **When** does this fire? | the concrete condition — be specific, no vague words |
| `statement` | The rule — what must be true | |
| `violation` | What a violation looks like in real code | concrete |
| `pass_example` | What passing looks like | concrete |
| `enforcement` | how it's enforced | `advisory-only` / `guard-clause` / `architectural` / `tooling-hook` / `test-coverage` |
| `rationale` | Why — what breaks if violated | |

### Steps

1. Collect the fields above in one prompt.
2. **Assign the next ID.** List existing project constraints, derive the next `PROJ-<DOMAIN-CODE>-NNN`:
   ```bash
   "$PR" list --json    # inspect existing PROJ- ids for this domain
   ```
   `DOMAIN-CODE` = a short uppercase token for the domain (e.g. `WRITE`, `DBINT`, `ARCH`). `NNN` = zero-padded next number for that code. Must match `RULE_ID_PATTERN` (e.g. `PROJ-WRITE-001`).
3. **Author** (gate-screens for dup/conflict, ingests as `authority=human`, exports `docs/rules/` same turn):
   ```bash
   "$PR" author \
     --rule-id PROJ-WRITE-001 --domain "Write Safety" --severity high \
     --scope component \
     --trigger "<when>" --statement "<rule>" --violation "<danger>" \
     --pass-example "<pass>" --enforcement "advisory-only" --rationale "<why>"
   ```
4. **Read the JSON result.**
   - `"accepted": true` → confirm to user: ID, that it's in the graph + exported to `docs/rules/`. Remind them to **commit `docs/rules/`**.
   - `"accepted": false` → show `reasons` (gate rejected: schema / vague language / redundant with an existing rule / conflicts). Help the user fix the wording or, if the overlap is intentional, re-run with `--force` (records the gate reasons but ingests anyway).
5. **From an ADR?** If this constraint is the durable consequence of an ADR (4B hybrid), add `--source-attribution ADR-NNNN` so the rule links back to the decision record.

**Never hand-write `docs/rules/` or `docs/CONSTRAINTS.md`** — the engine owns that export. (Legacy `docs/CONSTRAINTS.md` is retired; migrate via the section below.)

---

## Mode 1b — Write Tech Debt (→ flat, unchanged)

**Triggered by:** "log tech debt", "add debt"

1. Read `docs/TECH_DEBT.md` → find highest `TD-NN` → next ID.
2. Append the card (format in `references/card-formats.md`) under `## Active`, above any `## Archive`.
3. Resolved items (Status: RESOLVED) move to `## Archive` — never delete.

## Mode 1c — Write Open Question (→ flat, unchanged)

**Triggered by:** "open question", "log question"

1. Read `docs/OPEN_QUESTIONS.md` → next `OQ-NN`.
2. Append the card (format in `references/card-formats.md`); 🔴 Open first, ✅ Resolved below.

---

## Mode 2 — Review (which constraints apply)

**Input:** a proposed change / diff / stated intent.

1. **Load the full project constraint set** (verbatim, no ranking):
   ```bash
   "$PR" list
   ```
   Empty output → "no project constraints authored in this repo"; stop.
2. Identify which Domains the change touches. For each constraint in a touched domain, output:
   ```
   [ ] PROJ-XXX-NNN · [statement]
       Trigger: [verbatim trigger]
       Check: does this change avoid the violation?
   ```
3. End with `Domains checked: […]` / `Domains skipped: […]`.

**Filter to touched domains** — don't dump all constraints. Each constraint's `trigger` tells you whether it fires for this change; you judge relevance (no constraint is asserted to apply).

---

## Mode 3 — Audit (is a constraint enforced in \<file\>)

**Input:** file path(s) the user specifies.

1. `"$PR" list` → constraints; read each specified file in full.
2. For each **critical/high** constraint, trace enforcement (invert the `violation`, search the file for the guard). Enforcement reliability, high→low: `architectural` > `guard-clause` > `tooling-hook` > `test-coverage` > `advisory-only` (flag advisory-only as unguarded).
3. Output per constraint: ✅ ENFORCED / ⚠️ PARTIAL / ❌ UNGUARDED with file:line evidence; for every ❌ on a critical/high, propose the specific mechanical fix.

---

## Migration (legacy flat → graph)

When `docs/CONSTRAINTS.md` exists (old flat constraints):

1. Read it in full.
2. For each constraint card, map fields → Rule fields (Severity→severity, Rule→statement, Why→rationale, Danger signal→violation). Ask the user only for the missing fields (`trigger`, `pass_example`, `enforcement`, `scope`) — batch them.
3. `"$PR" author …` each as `PROJ-<DOMAIN>-NNN`.
4. After all are authored + exported to `docs/rules/`, **delete `docs/CONSTRAINTS.md`** (confirm with user first) and remove its `## Constraint Index` block from CLAUDE.md.

---

## Common Mistakes

- Hand-writing `docs/rules/` — the engine owns it. You author via `"$PR" author`.
- Forgetting to remind the user to **commit `docs/rules/`** after authoring (the graph is gitignored; the export is the record).
- Treating Tech Debt as a constraint. TD = scheduled work (flat). Constraint = always-on law (graph).
- Forgetting `## Archive` for resolved TD.
- Auditing medium constraints — audit traces critical/high only.
