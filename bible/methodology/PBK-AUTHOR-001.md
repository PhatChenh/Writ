---
playbook_id: PBK-AUTHOR-001
node_type: Playbook
domain: meta-authoring
severity: high
scope: task
trigger: "When authoring a new methodology node (Skill, Playbook, Technique, AntiPattern, Rule, ForbiddenResponse) for Writ, OR when revising an existing node whose effectiveness is unclear or unmeasured."
statement: "Apply RED-GREEN-REFACTOR to documentation: (1) write a baseline pressure scenario, (2) run it and observe the agent violate (RED), (3) draft the node, (4) re-run and observe the agent comply (GREEN), (5) close loopholes (REFACTOR), (6) link the scenario via PressureScenario edge, (7) write the migration."
rationale: "Untested methodology is unvalidated hypothesis. Skills written without a failing baseline are guessing at what agents will do; the failure mode is a skill that reads convincingly but doesn't change behavior. The RED-GREEN-REFACTOR discipline that catches this in code also catches it in docs -- the medium changes, the discipline doesn't."
tags: [authoring, meta, playbook, pressure-test, red-green-refactor, tdd-for-docs]
confidence: peer-reviewed
authority: human
last_validated: 2026-05-09
staleness_window: 365
evidence: doc:methodology
always_on: false
source_attribution: "writ-native"
source_commit: null
phase_ids: []
preconditions: [META-AUTH-001, META-AUTH-002]
dispatched_roles: []
edges:
  - { target: META-AUTH-001, type: GATES }
  - { target: META-AUTH-002, type: GATES }
  - { target: PBK-PROC-TDD-001, type: TEACHES }
  - { target: PSC-TDD-001, type: DEMONSTRATES }
---

# Playbook: Author a methodology node

## Step 1 -- Write the failing pressure scenario FIRST

Before drafting any node text, write the scenario that the future node should make the agent pass. The scenario is your test case; the node is the implementation.

A scenario specifies:
- A user prompt that triggers the target behavior
- The expected agent action (compliance) AND the failure mode (violation)
- Grading criteria: what's a pass, what's a fail
- (Optional) follow-up prompts that probe rationalization paths

File: `bible/methodology/PSC-<DOMAIN>-<NAME>-001.md` with `node_type: PressureScenario`.

If you cannot describe the scenario, you cannot describe the node. Stop here until you can.

## Step 2 -- Run the scenario WITHOUT the new node (RED)

In a fresh Claude Code session (no prior context), paste the scenario's prompt verbatim. Do not soften it. Observe the agent's response.

Acceptable RED outcomes:
- The agent violates the target behavior cleanly. Document the violation text.
- The agent partially complies but rationalizes. Document the rationalization.

Unacceptable RED outcomes (means scenario is mis-calibrated):
- The agent already complies fully without the new node. The scenario is too easy; revise to be more adversarial.
- The agent fails for unrelated reasons (server unreachable, etc.). Fix the environment.

Save the transcript to `docs/pressure-runs/PSR-NNN/transcript-baseline.md`.

## Step 3 -- Draft the node

Use the existing schema for the node type:
- Skill: `SKL-<DOMAIN>-<NAME>-001` -- agent-facing trigger; describes WHEN, statement is the bumper-sticker rule
- Playbook: `PBK-<DOMAIN>-<NAME>-001` -- multi-step procedural workflow
- Technique: `TEC-<DOMAIN>-<NAME>-001` -- named pattern with the how-to
- Rule: `ENF-<DOMAIN>-<NAME>-001` (mandatory) or domain-prefix (advisory) -- with `mechanical_enforcement_path` if a hook can deny
- AntiPattern: `ANT-<DOMAIN>-<NAME>-001` -- failure mode; what NOT to do, with rationalization counters

Apply `META-AUTH-001`: the trigger field describes WHEN, not WHAT. No action verbs ("does", "performs", "executes"). Authoring lint warns on these.

## Step 4 -- Re-run the scenario WITH the new node (GREEN)

Migrate the new node into Neo4j: `python3 scripts/migrate.py --methodology-dir bible/methodology`. Restart Writ if needed.

Re-run the scenario in a fresh session. Observe the agent's response.

Acceptable GREEN outcomes:
- The agent complies and cites the new node ID in its reasoning.
- The agent complies via the always-on bundle (if the node is tagged `always_on: true`) without explicit citation -- still GREEN.

If the agent still violates: REFACTOR (Step 5).

## Step 5 -- Close loopholes (REFACTOR)

Common reasons GREEN fails on first try:
- The rationalization the scenario triggers isn't covered in the node's `rationalization_counters`. Add it.
- The trigger field is too narrow; the agent doesn't recognize the scenario as in-scope. Broaden the trigger predicate.
- The statement is too abstract; the agent can claim compliance while violating. Make the rule mechanical.
- The node isn't being retrieved at all -- confirm Stage 4 graph traversal and BM25/vector indexes have it. Check `analyze-friction --skill-usage` post-run.

Re-draft, re-migrate, re-run.

## Step 6 -- Link the scenario via the graph

In the new node's `edges:` list, add `{ target: PSC-<DOMAIN>-<NAME>-001, type: DEMONSTRATES }`. This creates the bidirectional link the analyzer uses to confirm the node has been pressure-tested.

`META-AUTH-002` warns on add/edit if a SKL/PBK/TEC/ENF node lacks a linked PressureScenario.

## Step 7 -- Commit

Single commit including:
- The new node markdown file(s)
- The new PSC scenario markdown
- The baseline + GREEN run transcripts under `docs/pressure-runs/PSR-NNN/`
- Migration: don't commit Neo4j state; commit only the source markdown
- Tests: if the node has a mechanical enforcement path, commit the hook + tests for it in the same change

## Why this is BETTER than methodology' writing-skills

Methodology' `writing-skills` describes RED-GREEN-REFACTOR-for-docs as a discipline. This playbook makes it auditable:

- Step 1 has a concrete file path (`PSC-<DOMAIN>-<NAME>-001.md`) and a node_type. The scenario lives in the graph, not in prose.
- Step 6 enforces the link via a graph edge that `META-AUTH-002` lints against. Untested skills surface in `analyze-friction --trim-candidates` (zero linked scenarios = candidate for review).
- Step 4's GREEN signal is measurable: `analyze-friction --skill-usage --since N` shows whether the node is being retrieved at all post-deployment. Methodology has no equivalent measurement.
- The output of Step 7 is a single auditable artifact: scenario + node + transcript + tests + edges. The PSR directory layout proves the discipline ran.

## Anti-patterns

- "I know what the skill should say, I'll write the scenario after." -- Skips RED. The scenario has to fail first or you're guessing.
- "The scenario is implicit in the node's trigger." -- Trigger predicates are conditions, not adversarial probes. They're not the same artifact.
- "I'll add the DEMONSTRATES edge later." -- Without the edge, the analyzer can't surface the scenario when retrieving the node, and `META-AUTH-002`'s lint can't confirm coverage.
- "This skill is too obvious to test." -- Then you don't need a skill; rules already cover it. If you're authoring a Skill, by definition the agent's default behavior is wrong without it. Prove the default is wrong before claiming the skill fixes it.
