# ADR Format

## Where ADRs live

Canonical path: **`docs/adr/`**, numbered `0001-slug.md`, `0002-slug.md`, … (D4-04 flat layout). Create it lazily on the first ADR. A project's `CLAUDE.md` may override the path; honor it if set.

Scan the folder for the highest existing number and increment by one.

## Template — new decision

```md
# Short title of the decision

One to three sentences: context, decision, and why.

**Status:** accepted

**Considered Options** (optional — only when rejected alternatives are worth remembering)

- Alternative A — why rejected

**Consequences** (optional — only when non-obvious downstream effects need calling out)

- What this means for future work
```

That's it. An ADR can be a single paragraph. The value is recording *that* a decision was made and *why* — not filling out sections.

## Template — superseding an existing ADR

When a decision changes, **never edit or delete the old ADR**. Instead:

1. Write a new ADR with the new decision. Add at the top:
   ```
   _Supersedes ADR-NNNN._
   ```
2. Update the old ADR's Status line:
   ```
   **Status:** superseded by ADR-NNNN
   ```
3. Add a link to the new ADR at the bottom of the old one.

## Status values

- `accepted` — decided and implemented
- `proposed` — under consideration, not yet built
- `superseded by ADR-NNNN` — replaced; link both ways
- `deprecated` — no longer relevant but not replaced

## When to offer an ADR

All three must be true:

1. **Hard to reverse** — cost of changing your mind later is meaningful
2. **Surprising without context** — a future reader will look at the code and wonder "why on earth did they do it this way?"
3. **Real trade-off** — genuine alternatives existed; you picked one for specific reasons

If a decision is easy to reverse, skip it. If it's not surprising, nobody will wonder why. If there was no real alternative, there's nothing to record.

### What qualifies

- Architectural shape — monorepo, event-sourced, pipeline-based
- Integration patterns between contexts
- Technology choices that carry lock-in (database, message bus, auth provider)
- Boundary and scope decisions — what a component owns and explicitly does not own
- Deliberate deviations from the obvious path — anything a reasonable reader would assume is different
- Constraints not visible in the code — compliance, partner SLAs, performance budgets
- Rejected alternatives when the rejection is non-obvious

## Hybrid — ADR → optional project constraint (D4-04)

An ADR is a **narrative record** (flat, append-only). It is NOT a Rule node. But some ADRs carry a **durable enforceable consequence** — a rule future code must follow (e.g. "chose event-sourcing → every state change must emit an event").

When that consequence exists, after writing the ADR **offer** to also author it as a project constraint:

- It becomes a `PROJ-` Rule node (graph) via `/guardrail-check` "add constraint" (or directly `bin/writ-project-rules.sh author … --source-attribution ADR-NNNN`), linking the rule back to the decision.
- This is what makes the decision **surface during coding** (retrieval/gates); the ADR narrative alone does not.
- When a later ADR **supersedes** this one AND both spawned rules, chain `SUPERSEDES` between the rules (the flat ADRs already cross-link via their Status lines).

Only offer when the consequence is genuinely a per-edit rule. Most ADRs ("we chose a monorepo") have no such rule — leave them as narrative only.
