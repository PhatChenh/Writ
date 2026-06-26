# Card Formats

> Constraints are NO LONGER flat cards — they are `PROJ-` Rule nodes authored via
> `bin/writ-project-rules.sh author` (see SKILL.md Mode 1a). Only Tech Debt and
> Open Questions remain flat cards.

## Tech Debt Entry — `docs/TECH_DEBT.md`

```markdown
### TD-[ID] · [Short name]
**Status:** OPEN | RESOLVED
**Phase:** [When it will be addressed]
**Risk if triggered early:** [What breaks if addressed before the right phase]
**What:** [Description]
**Why deferred:** [Reason]
**Source:** [Reference]
```

### File structure

```markdown
# Tech Debt

## Active
[Active TD entries — Status: OPEN]

## Archive
[Resolved TD entries — Status: RESOLVED — kept for reference, not audited]
```

---

## Open Question — `docs/OPEN_QUESTIONS.md`

```markdown
### OQ-[ID] · [Short question title]
**Blocks:** [What this question must be answered before proceeding]
**Status:** 🔴 Open | ✅ Resolved
**Question:** [Full question]
**Context:** [What has been considered so far]
```

### File structure

```markdown
# Open Questions

[OQ entries — 🔴 Open items first, ✅ Resolved below]
```

---

## Constraint → Rule field mapping (for Mode 1a + migration)

| Old flat card | Rule field | Note |
|---------------|------------|------|
| Severity (CRITICAL/HIGH/MEDIUM) | `severity` | lowercase; add `low` |
| Domain | `domain` | |
| Rule | `statement` | |
| Why | `rationale` | |
| Danger signal | `violation` | |
| Source | `source_attribution` | optional; use `ADR-NNNN` for ADR-derived rules |
| — (new, ask) | `trigger` | when the rule fires — concrete, no vague words |
| — (new, ask) | `pass_example` | concrete passing example |
| — (new, ask) | `enforcement` | advisory-only / guard-clause / architectural / tooling-hook / test-coverage |
| — (new, ask) | `scope` | component / task / session / entity (default component) |

ID: `PROJ-<DOMAIN-CODE>-NNN` (e.g. `PROJ-WRITE-001`), must match `RULE_ID_PATTERN`.
