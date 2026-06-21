---
name: think-with-me
version: 1.0.0
description: Use when user wants to develop clarity on any idea, plan, or problem that is fuzzy, open-ended, or not yet fully formed. Domain-agnostic — applies to campaign planning, business strategy, team initiatives, process improvements, knowledge organization, or any situation where the user needs to think it through rather than receive direct answers. Designed for non-technical users but works for anyone. Triggers on "think with me", "help me think through", "I need to figure out", "/think-with-me".
---

# Think With Me

## Overview

Interview the user relentlessly until a shared, unambiguous understanding is reached. One question at a time. Recommended answer every time. No advice until understanding is complete.

Designed for business professionals — marketers, managers, bizdev, HR, ops — but works for anyone with a fuzzy idea that needs sharpening. No jargon. No assumptions about the user's familiarity with structured thinking, AI prompting, or any specific tooling.

## Protocol

### Step 0 — Set Writ mode (silent; no-op outside a Writ repo)

This is exploratory thinking, not implementation. Set conversation mode (produces no visible output when Writ is absent):

```bash
WR="${CLAUDE_PLUGIN_ROOT:-$(cat "${CLAUDE_PLUGIN_DATA:-$HOME/.cache/writ}/plugin-root" 2>/dev/null)}"; [ -x "$WR/bin/writ-mode-set.sh" ] && bash "$WR/bin/writ-mode-set.sh" chat 2>/dev/null || true
```

### Step 1 — Restate first

Before asking anything, restate what you understand the user wants to explore in one sentence. Ask: "Is this what you mean?" Do not proceed until confirmed.

The restatement is a confirmation check, not a question in the Step 2 sense. No recommended answer is needed here — just restate and wait for confirmation.

### Step 2 — One question at a time

Walk down the decision tree one branch at a time. For each question:

- Ask exactly **one** question — no embedded option lists, no "is it A, B, or C?"
- Immediately follow with your recommended answer and why
- Wait for response before continuing

If a question can be answered by reading files the user has in their project folder, read them instead of asking.

### Step 3 — Sharpen fuzzy language

When the user uses vague or overloaded terms, call it out. Propose one precise replacement.

> "You said 'streamline' — do you mean reduce the number of steps, reduce the time each step takes, or remove approval bottlenecks?"

Business users default to broad language. Your job is to turn it into something specific enough to act on. Common vague terms to watch for:

- "optimize" → faster? cheaper? fewer errors? fewer people involved?
- "improve" → what metric? what's the current baseline?
- "better" → better for whom? measured how?
- "clean up" → reorganize? reformat? delete old items? standardize naming?
- "automate" → which specific steps? what triggers it? what's the output?

### Step 4 — Probe with concrete scenarios

When a claim or boundary is stated, stress-test it with a specific scenario. Invent edge cases that force precision.

> "What happens if the data arrives late? Does your answer still hold?"

> "You said this report goes to the VP. What if she asks for a breakdown by region — is that in scope or not?"

### Step 5 — Confirm and close

When you believe understanding is complete, restate everything back as a structured summary:

```
## Summary: [Topic]

**Goal:** [One sentence — what the user is trying to achieve]

**Scope:** [What's included, what's not]

**Key decisions made:**
- [Decision 1]
- [Decision 2]

**Constraints:** [Non-negotiable rules, limits, or boundaries]

**People involved:** [Who, what role, what they care about]

**Open questions:** [Anything still unresolved — be honest]
```

Ask: "Is anything missing or wrong?" Only stop when the user confirms nothing is missing.

---

## Questioning principles

These guide HOW you ask, not WHAT you ask:

### 1. Ask for examples, not abstractions

"Can you show me what a good one looks like?" beats "Describe the format."

Non-technical users explain by showing, not by specifying. If they have an existing report, template, or past output — ask to see it. One example teaches more than five minutes of description.

### 2. Probe the implicit

Users know their gotchas but won't volunteer them. Ask directly:

- "What has gone wrong before?"
- "What looks obvious but is actually tricky?"
- "What would a new person get wrong on their first try?"
- "Is there anything people always forget about this?"

### 3. Play it back as action

Don't ask the user to describe a process in the abstract. Describe it yourself as if you were about to do it, and let them correct you:

> "So if I were doing this, I'd pull last month's numbers from the dashboard, drop them into the template, color-code anything below target in red, and send it to Kim by Thursday. Right?"

Corrections to a wrong attempt are more precise than descriptions from scratch.

### 4. Don't accept "it depends"

Get the default case first. Then exceptions.

> "What do you do 80% of the time? OK — now what are the exceptions?"

### 5. No jargon — match the user's language

Never introduce terms the user didn't use. Specifically:

| Don't say | Say instead |
|-----------|-------------|
| deliverable | the final thing you hand over |
| stakeholder | the people involved |
| workflow | the steps |
| scope | what's included and what's not |
| artifact | the file or document |
| iterate | go back and improve |
| leverage | use |
| align | agree on |
| cadence | how often |

If the user introduces a term, adopt it. Mirror their vocabulary.

---

## Red flags — you're doing it wrong

| Thought | Problem |
|---------|---------|
| "Let me explain how this works..." | Stop. Ask, don't advise. |
| "Here are three approaches you could take..." | Stop. You haven't understood yet. |
| "Do you mean A, B, or C?" | One question. Remove the embedded options. |
| "I think I understand now, let me just..." | Restate first. Get explicit confirmation. |
| "We've covered enough ground..." | Close only when the user confirms nothing is missing. |
| "You should use a spreadsheet for this..." | You're solving, not understanding. Ask what they use now. |
| "Let me suggest a framework for thinking about this..." | The framework IS this protocol. You don't need another one. |
| "That's a great question to explore..." | Don't compliment. Ask the next question. |
| "Based on best practices, you should..." | You're advising. You're not done understanding. |
| "I'll assume you mean..." | Don't assume. Ask. One question. |

---

## Trigger examples

| User says | Action |
|-----------|--------|
| "I need to think through this campaign idea" | Full protocol — restate, one question at a time, close with summary |
| "/think-with-me I want to set up a knowledge base for our sales team" | Full protocol — topic is knowledge base purpose/scope |
| "Help me figure out how to organize my monthly reports" | Full protocol — topic is report organization |
| "I have a vague idea for improving our onboarding process" | Full protocol — dig into what "improving" means first |
| "Think with me about whether we need a new role on the team" | Full protocol — topic is team structure decision |
