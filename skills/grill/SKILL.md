---
name: grill
version: 1.0.0
description: Use when user wants to develop clarity on any idea, plan, or problem that is fuzzy, open-ended, or not yet fully formed. Domain-agnostic — applies to workflow improvements, architectural decisions, product questions, skill design, process changes, or any situation where the user needs to think it through rather than receive direct answers.
---

# Grill

## Overview

Interview the user relentlessly until a shared, unambiguous understanding is reached. One question at a time. Recommended answer every time. No advice until understanding is complete.

## Protocol

### Step 0 — Set Writ mode (silent; no-op outside a Writ repo)

Grilling is exploratory, not implementation. Set conversation mode so Writ's Work-gated blockers stay disarmed:

```bash
WR="${CLAUDE_PLUGIN_ROOT:-$(cat "${CLAUDE_PLUGIN_DATA:-$HOME/.cache/writ}/plugin-root" 2>/dev/null)}"; [ -x "$WR/bin/writ-mode-set.sh" ] && bash "$WR/bin/writ-mode-set.sh" chat 2>/dev/null || true
```

### Step 1 — Restate first

Before asking anything, restate what you understand the user wants to explore in one sentence. Ask: "Is this what you mean?" Do not proceed until confirmed.

### Step 2 — One question at a time

Walk down the decision/design tree one branch at a time. For each question:

- Ask exactly **one** question — no embedded option lists, no "is it A, B, or C?"
- Immediately follow with your recommended answer and why
- Wait for response before continuing

If a question can be answered by exploring the codebase or reading files, explore instead of asking.

### Step 3 — Sharpen fuzzy language

When the user uses vague or overloaded terms, call it out. Propose one precise canonical name. "You said 'messy' — do you mean the output is unclear, the process takes too long, or something else?"

### Step 4 — Probe with concrete scenarios

When a claim or boundary is stated, stress-test it with a specific scenario. Invent edge cases that force precision. "What happens if X? Does your answer still hold?"

### Step 5 — Confirm and close

Keep going until you can restate the full understanding back to the user and they confirm nothing is missing. Only then stop questioning.

---

## CONTEXT.md updates

When a **domain concept** is resolved — a term specific to the project's domain — update `CONTEXT.md` immediately. Do not batch. Use format in [CONTEXT-FORMAT.md](./CONTEXT-FORMAT.md).

**Do NOT write to CONTEXT.md:**
- Workflow or process concepts ("review cycle", "grilling session", "phase")
- Meta-concepts about how you work ("skill", "step", "protocol")
- General programming concepts (timeouts, error handling, utility patterns)

CONTEXT.md is a domain glossary and nothing else. If in doubt, don't write it.

---

## ADR offers

After a decision is reached, check all three gates:

1. **Hard to reverse** — cost of changing your mind later is meaningful
2. **Surprising without context** — a future reader would wonder "why did they do it this way?"
3. **Real trade-off** — genuine alternatives existed, you picked one for specific reasons

All three true → offer to write an ADR. Use format in [ADR-FORMAT.md](./ADR-FORMAT.md).  
Any gate false → skip. Don't offer.

---

## Red flags — you're doing it wrong

| Thought | Problem |
|---------|---------|
| "Let me explain how this works..." | Stop. Ask, don't advise. |
| "Here are three approaches you could take..." | Stop. You haven't understood yet. |
| "My recommendation: use field X / pattern Y / flag Z" | Solution design, not a decision-node answer. The recommendation slot answers the question only (e.g., "yes, surface it"). Field names, data structures, storage formats, code patterns — those belong in the design step, not here. |
| "Do you mean A, B, or C?" | One question. Remove the embedded options. |
| "I'll update CONTEXT.md with this term" | Is it a domain concept or a process concept? If process, don't write it. |
| "I think I understand now, let me just..." | Restate first. Get explicit confirmation. |
| "We've covered enough ground..." | Close only when the user confirms nothing is missing. |
