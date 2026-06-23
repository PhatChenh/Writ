# WRIT-REWORK-FOR-REASONIX

Findings from session 2026-06-23: **can Writ run under Reasonix** (esengine/DeepSeek-Reasonix,
a DeepSeek-native terminal coding agent — Claude Code analogue) instead of Claude Code?

All Reasonix facts below were **verified against source** (branch `main-v2`, commit
`0cfc302...` for hooks; fresh `main-v2` clone for task/skill), not docs or inference.
Source clone used this session: `/tmp/rx-src` (ephemeral).

---

## TL;DR

Writ's **methodology** ports (skills = checklists the model follows). Writ's **mechanical
guardrails do not** — RAG per-prompt injection, the enforcement hooks, and named-agent
subagent dispatch all assume Claude Code internals Reasonix doesn't share.

| Writ pillar | Reasonix | Status |
|---|---|---|
| Librarian RAG server (FastAPI) | model-agnostic HTTP daemon | ✅ runs |
| **Per-prompt RAG rule injection** | no hook injects stdout into model context | ❌ **dead** (this is Writ's core) |
| Process Keeper enforcement hooks | only PreToolUse + UserPromptSubmit gate; stdout never reaches model | ⚠️ blocks port; advisory/inject dies |
| Completion gate (force-continue) | Stop is non-gating | ❌ dead |
| Named subagent dispatch (`subagent_type: writ-*`) | no such param; `.claude/agents/` not loaded | ❌ dead as-is → ✅ **ported + live-verified** (see "Implemented" below) |
| Skill workflow text (TDD/SDD/review steps) | skills load + run | ✅ works |

> **Update 2026-06-23 — subagent layer ported and live-verified on Reasonix.** The named-agent dispatch gap is closed: 6 `.claude/agents/writ-*.md` reborn as `runAs: subagent` skills (`skills/reasonix-*`), 3 orchestrators copied with `run_skill` dispatch. **Verified by running reasonix v1.6.0-rc.1 against DeepSeek** — see "Implemented + verified" section at the bottom. The RAG-injection and enforcement-hook gaps remain (unchanged, architectural).

---

## Reasonix verified facts

### Hooks — `internal/hook/hook.go` @ `0cfc302`

Events defined (11): `PreToolUse`, `PostToolUse`, `PermissionRequest`, `UserPromptSubmit`,
`Stop`, `PostLLMCall`, `SessionStart`, `SessionEnd`, `SubagentStop`, `Notification`, `PreCompact`.

- **Gating (exit 2 → block) only on `PreToolUse` and `UserPromptSubmit`.** All other events
  non-gating (exit code → warn at most). So `Stop` and `PostToolUse` **cannot block**.
- **No event injects hook stdout into the model context pre-generation.** Package comment:
  output "captured (capped) and surfaced to the **user**." Only two events touch model
  processing, both useless for rule injection:
  - `PostLLMCall` → stdout replaces reasoning *display* (post-generation)
  - `PreCompact` → stdout = compaction guidance
- `UserPromptSubmit` stdout specifically: captured into `Outcome`, **never appended to prompt.**
  No `additionalContext` equivalent. This is the single fact that kills Writ's RAG core.
- Events Reasonix **lacks entirely** (Writ binds hooks to these): `SubagentStart`,
  `PostToolUseFailure`, `PostCompact`, `CwdChanged`, `InstructionsLoaded`.
- Hook config format (per user's `reasonix_setup.md`): `match` (regex on tool name, not
  `matcher`), direct `command` (no `type:"command"` wrapper), tool names
  `edit_file|write_file|multi_edit|bash|read_file` (not `Edit|Write|Bash`), exit 0 pass /
  exit 2 block, requires `/hooks trust` per project. Payload JSON schema differs from Claude
  Code's `tool_input.file_path` shape → every Writ hook script needs payload-parse rewrite.

### Subagents / task tool — `internal/agent/task.go`, `internal/skill/skill.go`

- `task` tool params (`task.go:194-204`): `prompt, description, tools, max_steps,
  run_in_background, model, effort, continue_from, fork_from`. **No `subagent_type`.**
- Subagent persona = a **skill** with frontmatter `runAs: subagent` (`skill.go:38-45,484`),
  invoked via `run_skill` / generic `task`. Persona is NOT selected by an agent-type name.
- Skill discovery (`skill.go:183-213`) scans convention dirs `.reasonix / .agents / .agent /
  .claude` (project + home) — but only the **`skills/` subdir** of each (`:195`).
  `grep -rn '.claude/agents' internal/` = **zero hits**. Reasonix **never loads
  `.claude/agents/*.md`.**
- Skill subagent frontmatter honored: `runAs` (inline|subagent), `allowed-tools`, `model`,
  `effort`.

### Skills / memory / config (from user's `reasonix_setup.md`, consistent w/ source)

- Loads `~/.claude/skills` via `config.toml [skills] paths` → Writ skills appear in `/skills`.
- Project memory = `AGENTS.md` / `REASONIX.md` (symlink from `CLAUDE.md`), loaded every
  session like CLAUDE.md. **Static** — no retrieval.
- MCP supported (stdio/http). CodeGraph built-in (its own `.codegraph/`).
- Global config `~/Library/Application Support/reasonix/`; hooks in `~/.reasonix/settings.json`.

---

## Writ component-by-component

### 1. Librarian (RAG server) — ✅ runs, but orphaned
Python/FastAPI daemon, model-agnostic. DeepSeek consumes rules as plain text fine.
But: **nothing pipes its output into the model per turn** (no UserPromptSubmit injection).
Only reachable if wrapped as an MCP tool the model *chooses* to call — voluntary, not enforced.

### 2. Per-prompt RAG injection (`writ-rag-inject.sh`, UserPromptSubmit) — ❌ dead
The `--- WRIT RULES ---` block mechanism = UserPromptSubmit stdout → additionalContext.
That path does not exist in Reasonix. **This is the irreplaceable loss.**

### 3. Process Keeper hooks (37 bindings in `hooks/hooks.json`)
- **Pure pre-write blocks** → ✅ portable (rewrite matcher→reasonix tool name + script
  payload parse + `/hooks trust`): `validate-test-file` (test-first gate),
  `pre-validate-file`, `validate-design-doc`, `writ-memory-policy-guard`,
  `writ-worktree-safety` (Bash).
- **Block+inject hybrids** → ⚠️ only the block survives; advisory text to model dies:
  `writ-pre-write-dispatch`, `writ-read-rag` (Read RAG = pure inject → fully dead).
- **PostToolUse validators** (`validate-file/handoff/rules`, `writ-quality-judge`,
  `writ-posttool-rag`, `writ-mark-pending-test`, `inject-tier-workflow`) → run as
  side-effects, **cannot block, model never sees output** (PostToolUse non-gating + stdout→user).
- **Stop completion gate** (`enforce-violations`, `writ-run-pending-tests`,
  `writ-verify-before-claim`) → ❌ Stop non-gating → can't force-continue; logging only.
- **Dead events** (`track-failed-writes`@PostToolUseFailure, SubagentStart, PostCompact,
  CwdChanged, InstructionsLoaded hooks) → never fire.
- `validate-exit-plan`@ExitPlanMode, `writ-sdd-review-order`@Task → ⚠️ Reasonix plan mode =
  Shift+Tab (maybe not a tool) and subagent tool name differs → matchers likely won't match.

### 4. Refitted skills `/subagent-driven-development`, `/tdd-implement`, `/review-implementation`
Coupling found by reading `skills/*/SKILL.md`:
- `writ-mode-set.sh work/review` at skill top → ✅ runs, but **arms gates that don't enforce**
  on Reasonix → cosmetic.
- `writ-session.py update --set-plan-reviewed` + `common.sh` → ✅ runs (python/bash), writes
  session state.
- Reviewer/implementer dispatch `Task(subagent_type: writ-plan-reviewer |
  writ-code-quality-reviewer | writ-implementer)` → ❌ **un-dispatchable** (no `subagent_type`;
  agents dir not scanned). Skill text forbids the hand-written-prompt fallback. Steps no-op.
- `writ-sdd-review-order` backstop hook → ❌ won't fire → review ordering rests on skill text only.
- `/writ-approve` + write-block gate → ❌ ceremonial (records state nothing enforces).
**Net: degrade to smart checklists. Discipline survives; mechanical guardrails + multi-agent
review don't.**

---

## Porting worklist (if pursued)

1. **Subagents:** convert each `.claude/agents/writ-*.md` → a skill with `runAs: subagent`
   frontmatter (+ `allowed-tools`, `model`, `effort`) under a scanned `skills/` dir. Rewrite
   the three skills' dispatch from `subagent_type:` → Reasonix `run_skill`/`task` invocation.
2. **Block hooks:** rewrite the pure-pre-write-block hooks to Reasonix format — `match` regex,
   tool names `write_file|edit_file|multi_edit|bash|read_file`, parse Reasonix payload JSON,
   `/hooks trust`.
3. **Always-on ENF rules:** dump into `AGENTS.md`/`REASONIX.md` (static, loaded every session).
   Loses per-query retrieval — back to "all rules in prompt," the thing Writ exists to avoid.
4. **Librarian (optional):** wrap as MCP server so DeepSeek can *opt* to query rules. Voluntary,
   not injected, not enforced.
5. **Accept losses:** per-prompt RAG injection, completion gate, advisory rule surfacing on
   read/write — no Reasonix mechanism. Cannot port.

## Implemented + verified (2026-06-23)

**Built (repo `skills/`, all new, nothing existing modified):**
- 6 subagent skills: `reasonix-{plan-reviewer, code-quality-reviewer, implementer, explorer,
  planner, test-writer}` — `runAs: subagent`, `model: deepseek-pro`, `effort: high`,
  `allowed-tools` mapped to Reasonix builtins (`read_file/glob/grep/bash/write_file/edit_file`,
  `codegraph_*`). Each carries a `repo:` working-dir instruction.
- 3 orchestrators: `reasonix-{subagent-driven-development, tdd-implement, review-implementation}`
  — copies with dispatch rewritten `subagent_type` → `run_skill({name, arguments, continue_from})`,
  `arguments` now include `repo: <abs path>`. Dead Writ machinery kept as harmless no-op + a
  "Reasonix port" header note (enforcement is advisory/by-construction, not gated).

**Verified live** (reasonix v1.6.0-rc.1, deepseek-pro, real API):
- Discovery: reasonix lists the `reasonix-*` skills. ✓
- `run_skill` dispatch of a `runAs:subagent` skill; subagent runs in isolated context with its
  own tools, returns final answer to parent. ✓ (`reasonix-explorer`)
- Reviewer **JSON-only contract** parsed correctly; caught a deliberate non-compliance
  (`bar()` missing). ✓ (`reasonix-plan-reviewer`)
- **`continue_from` re-review loop** accepted (no lineage error); 13.7k-token cache hit on
  resume = genuine context continuation. ✓
- **Write-tool subagent under sandbox** `write_roots`: `reasonix-implementer` created `greet.py`,
  self-tested via `python3 import`, Status DONE, file confirmed on disk. ✓
- **Full `/reasonix-review-implementation` orchestration**: Stage 1 (plan-compliance) dispatched
  BEFORE Stage 3 (code-quality), both valid JSON, ordering honored. ✓
- The `repo:` fix eliminated the earlier subagent path-wander (subagents `cd` straight to the
  passed path). ✓

**Still NOT ported (architectural — unchanged):**
- Per-prompt RAG rule injection (`UserPromptSubmit` stdout → model): no Reasonix injection path.
- Enforcement hooks (test-first block, write-gate, completion force-continue): Reasonix hooks
  gate via exit code only, never inject; `Stop`/`PostToolUse` non-gating. Advisory at best.

## Open / unverified
- Reasonix plan-mode tool name (is `ExitPlanMode` a tool? Shift+Tab suggests UI state) — only
  relevant if porting the `validate-exit-plan` gate.
- `reasonix-tdd-implement` end-to-end (multi-phase TDD loop) not run live; only the shared
  subagent primitives it relies on are verified.
- `reasonix-planner` / `reasonix-test-writer` not individually run (same `run_skill`+write
  primitives as the verified `reasonix-implementer`, so low risk).
