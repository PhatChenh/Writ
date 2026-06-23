# 06 — Hooks and Claude Code Integration

> **Refresh note (2026-05-10).** The 2026-05-10 cleanup deleted three legacy hooks that this doc originally described as "registered but superseded": `check-gate-approval.sh`, `enforce-final-gate.sh`, and `writ-pretool-rag.sh`. They are gone from disk. The current wired set is **30 hooks** (was 33). Separately, `bin/run-analysis.sh` grew from ~387 lines to ~1,053 lines via 6 new cross-language security/performance/scaling analyzers added in Phase 1-5 of the public-rulebook expansion. The new analyzers are documented in §10 below. Use `templates/settings.json` as the canonical wiring source; the table in §1 below has been updated to drop the deleted hooks.

Skill root: `~/.claude/skills/writ`. Hook scripts under `.claude/hooks/`. Libraries under `bin/lib/`. Hooks are wired via `templates/settings.json` (the canonical wiring file users copy into `~/.claude/settings.json`).

## 1. Hook Trigger Map

Source: `templates/settings.json:55-358`. `.claude/settings.local.json` only carries permissions — no hook block — so wiring lives entirely in `templates/settings.json`.

| Claude Code event | Matcher | Hook script |
|---|---|---|
| **UserPromptSubmit** | (any) | `auto-approve-gate.sh` (line 56-65) |
| **UserPromptSubmit** | (any) | `writ-rag-inject.sh` (line 66-75) |
| **SubagentStart** | (any) | `writ-subagent-start.sh` (line 76-86) |
| **SubagentStop** | (any) | `writ-subagent-stop.sh` (line 87-97) |
| **Stop** | (any) | `writ-context-tracker.sh` (line 98-107) |
| **Stop** | (any) | `friction-logger.sh` (line 108-116) |
| **Stop** | (any) | `enforce-violations.sh` (line 117-125) |
| **Stop** | (any) | `writ-verify-before-claim.sh` (line 126-134) |
| **PostToolUseFailure** | `Write\|Edit` | `track-failed-writes.sh` (line 136-146) |
| **PreCompact** | (any) | `writ-precompact.sh` (line 147-157) |
| **PostCompact** | (any) | `writ-postcompact.sh` (line 158-168) |
| **SessionEnd** | (any) | `writ-session-end.sh` (line 169-178) |
| **SessionEnd** | (any) | `writ-pressure-audit.sh` (line 179-188) |
| **CwdChanged** | (any) | `writ-cwd-changed.sh` (line 189-199) |
| **InstructionsLoaded** | (any) | `writ-instructions-loaded.sh` (line 200-210) |
| **PreToolUse** | `ExitPlanMode` | `validate-exit-plan.sh` (line 212-220) |
| **PreToolUse** | `Read` | `writ-read-rag.sh` (line 221-229) |
| **PreToolUse** | `Write\|Edit` | `writ-pre-write-dispatch.sh` (line 230-238) |
| **PreToolUse** | `Write\|Edit` | `pre-validate-file.sh` (line 239-247) |
| **PreToolUse** | `TodoWrite` | `writ-verify-before-claim.sh` (line 248-256) |
| **PreToolUse** | `Task` | `writ-sdd-review-order.sh` (line 257-265) |
| **PreToolUse** | `Bash` | `writ-worktree-safety.sh` (line 266-274) |
| **PreToolUse** | `Write` | `validate-test-file.sh` (line 275-283) |
| **PreToolUse** | `Write` | `validate-design-doc.sh` (line 284-292) |
| **PreToolUse** | `Write` | `writ-memory-policy-guard.sh` (line 293-301) |
| **PostToolUse** | `Bash` | `inject-tier-workflow.sh` (line 305-312) |
| **PostToolUse** | `Write\|Edit` | `validate-file.sh` (line 313-321) |
| **PostToolUse** | `Write\|Edit` | `validate-handoff.sh` (line 322-330) |
| **PostToolUse** | `Write\|Edit` | `validate-rules.sh` (line 331-339) |
| **PostToolUse** | `Write\|Edit` | `writ-posttool-rag.sh` (line 340-348) |
| **PostToolUse** | `Write` | `writ-quality-judge.sh` (line 349-357) |

Hooks deleted 2026-05-10 (formerly listed as legacy-but-present):
- `check-gate-approval.sh` — was superseded by `writ-pre-write-dispatch.sh`; now deleted from disk.
- `enforce-final-gate.sh` — was superseded; logic moved into `_can_write_check` in `writ-session.py`; now deleted from disk.
- `writ-pretool-rag.sh` — was superseded by `writ-pre-write-dispatch.sh`; now deleted from disk.

`writ-verify-before-claim.sh` is registered on BOTH PreToolUse(TodoWrite) and Stop.

## 2. Per-Hook Behavior

### `auto-approve-gate.sh` — UserPromptSubmit (213 lines)
- **Input**: stdin JSON envelope (`prompt`, `session_id`/`agent_id`).
- **Steps**: (1) extracts session_id/prompt/agent_id, (2) publishes session_id to `/tmp/writ-current-session` unless inside sub-agent, (3) checks if prompt matches approval pattern using exact match, prefix-strip + match, Levenshtein <=2 fuzzy match, and 5 regex patterns, (4) if match → ensures gate-token file `/tmp/writ-gate-token-${SESSION_ID}` exists with `secrets.token_hex(16)`, (5) emits a `[Writ: approval pattern detected]` directive on stdout steering Claude to `/writ-approve` slash command, (6) logs `approval_pattern_match` or `approval_pattern_miss` events.
- **Exit**: always 0. Pattern match does NOT itself advance phase (Plan Section 8.1).
- **Side effects**: writes `/tmp/writ-current-session`, `/tmp/writ-gate-token-{sid}`, `/tmp/writ-prompt-debug.log`, project's `workflow-friction.log`.

### `enforce-violations.sh` — Stop (64 lines)
Only acts when mode=work. Reads `pending_violations` from cache. If non-empty: prints `You have N unresolved violations: [RULE_IDS]. Fix these before completing.` to stderr and **exits 2** (forces Claude to continue).

### `friction-logger.sh` — Stop (235 lines)
Emits: `gate_denied_then_approved`, `phase_transition_time` (compares mtimes of phase-a.approved and test-skeletons.approved), `phase_transition` (new entries in cache's phase_transitions[]).

### `inject-tier-workflow.sh` — PostToolUse Bash (87 lines)
Detects `mode set <conversation|debug|review|work>` or legacy `tier set [0-3]` (tier 0→conversation, tier 1/2/3→work). Emits a mode-specific reminder block.

### `pre-validate-file.sh` — PreToolUse Write/Edit (~100 lines)
Writes proposed content to a tempfile, runs `bin/run-analysis.sh`, on non-zero emits `permissionDecision: deny` with `[ENF-POST-007]` listing first 5 errors. Skips paths matching `scripts/seed_*.py` since the public-rulebook seed scripts intentionally embed bad-code samples in `violation`/`pass_example` fields of the rules they ingest, and the new security analyzers would otherwise flag those literals.

### `track-failed-writes.sh` — PostToolUseFailure Write/Edit (78 lines)
Builds `{file, reason, timestamp}` record, calls `_writ_session update --add-failed-write`, logs `write_failure` event.

### `validate-design-doc.sh` — PreToolUse Write (82 lines)
Bails unless mode=work AND file matches `*/docs/*/specs/*-design.md` or `*/docs/specs/*-design.md`. Requires sections `## Goal`, `## Constraints`, `## Alternatives Considered`, `## Chosen Approach`, `## Risks`. Each section ≥ 50 words. Blocklist: `TODO`, `TBD`, `fill in`, `appropriate`, `similar to above`, `as needed`, `placeholder`. Alternatives must list ≥ 2 bullets. Risks must contain "mitigation".

### `validate-exit-plan.sh` — PreToolUse ExitPlanMode (165 lines)
Skips if mode != work. Runs `_validate_phase_a` from writ-session.py. On failure logs `exitplanmode_denial` and emits deny JSON. On pass, calls `_writ_session update --reset-task-phase` (sets `current_phase=planning`, clears `gates_approved`).

### `validate-file.sh` — PostToolUse Write/Edit (70 lines)
Skips when `is_error=true`. Detects language; runs `bin/run-analysis.sh`; tracks file outcome via `_writ_session update --add-file --add-file-result FILE pass|fail`.

### `validate-handoff.sh` — PostToolUse Write/Edit (131 lines)
Only acts on `*/.claude/handoffs/slice-*.json`. Required keys: `slice, files, interfaces, invariants_satisfied, plan_deviations, open_items`.

### `validate-rules.sh` — PostToolUse Write/Edit (412 lines)
The largest validator. Skips if not work mode or analysis_results[file] != "pass". Builds context, determines phase from gate file presence. POSTs `{code, file_path, phase, context}` to `/analyze`. On violations, logs each as pending violation. Detects boundary mode: for each violated rule, if rule_id in `loaded_rules` → invalidate phase-a gate; else log as new finding only.
**Exit**: 0 (pass) / 1 (per-write warnings) / **2 (phase-boundary violations routed to gate-invalidation)**.

### `validate-test-file.sh` — PreToolUse Write (80 lines)
Only fires for `.{py,js,ts,php,go,rs,java}` under `/(src|lib|app|writ)/`. Computes language-specific test-path candidates. Each candidate must exist AND contain `\b(assert|expect|should|test_)\w*`. If none match → deny with `ENF-PROC-TDD-001`.

### `writ-context-tracker.sh` — Stop (10 lines)
**No-op stub** retained for hook registration compatibility.

### `writ-cwd-changed.sh` — CwdChanged (93 lines)
Domain detection priority: `composer.json→php`, `pyproject.toml→python`, `package.json→javascript`, `Cargo.toml→rust`, `go.mod→go`, default `universal`. Writes `cache.detected_domain`.

### `writ-instructions-loaded.sh` — InstructionsLoaded (105 lines)
Regex-extracts rule IDs matching `[A-Z][A-Z0-9]*(?:-[A-Z][A-Z0-9]*)*-[A-Z][A-Z0-9]*-\d{3}`. Detects keywords `WHEN:|RULE:|VIOLATION:|TRIGGER:`. Stores deduped IDs in `cache.instructions_rule_ids`. The RAG inject hook merges this list into the exclusion list.

### `writ-memory-policy-guard.sh` — PreToolUse Write (196 lines)
Only acts on `*/.claude/projects/*/memory/*` paths. Override marker: YAML `explicit_rule_override: true` OR body line `override authorized by:` skips check. Patterns block phrases like "skip the verification", "no fresh verification", "trust the implementer", "take at face value", "bypass the discipline" (PSR-003).

### `writ-postcompact.sh` — PostCompact (55 lines)
Calls `_writ_session reset-after-compaction`. Emits a verify-discipline directive (PSR-004) instructing model to re-verify before answering "is it working/done/passing".

### `writ-posttool-rag.sh` — PostToolUse Write/Edit (330 lines)
Skips if `is_orchestrator=true`. Extracts code-derived signals (XML class refs, plugin methods, event names, route URLs OR source code class/function/import names). Caps budget at `min(remaining, 1500)`. POSTs to `/query`. Requires at least one rule with `score >= 0.4`. Logs `rag_query` with `query_source: "file-write-post"`.

### `writ-precompact.sh` — PreCompact (31 lines)
Calls `_writ_session clear-rules-for-compaction` which empties `loaded_rules` (full objects) but keeps `loaded_rule_ids`. Logs `pre_compaction`.

### `writ-pressure-audit.sh` — SessionEnd (55 lines)
Emits `pressure_audit` friction event with `mode, active_playbook, phases_traversed, verification_evidence_count, quality_judgment_count, quality_override_count`. If `quality_override_count > 3` adds `escalation: "quality_override_threshold_exceeded"`.

### `writ-pre-write-dispatch.sh` — PreToolUse Write/Edit (164 lines, v2)
Calls `_writ_session pre-write-check` which posts to `POST /pre-write-check` (1s max) with subprocess fallback. Parses `decision` field (`allow|deny|ask`). On `deny`/`ask` emits hookSpecificOutput JSON with warning. On `allow` if `rag_rules` present, prints `[Writ: file-context rules for FILE]` block and updates cache.

### `writ-quality-judge.sh` — PostToolUse Write (100 lines)
Bails if not work mode. Classifies file path → `plan` / `design` / `test`. Emits a self-review directive on stdout instructing Claude to score the artifact 0-5 against rubric and POST to `/session/$SESSION_ID/quality-judgment`.

### `writ-rag-inject.sh` — UserPromptSubmit (994 lines, the giant one)
Structure:
1. **Auto-start**: pings `/health`. If down: acquires `/tmp/writ-server-starting.lock` via `set -o noclobber`, ensures `docker start writ-neo4j`, polls `localhost:7474` for 8s, launches `nohup .venv/bin/python3 -m uvicorn writ.server:app …`, polls health for 5s.
2. **Prompt extraction**: extracts `prompt`, `session_id`/`agent_id`. Long prompts (>300 chars) keyword-extracted (max 25 keywords).
3. **Session ID fallback**: PPID then `md5(${PWD}:${USER})-DATE`.
4. **Publish session ID**: writes `/tmp/writ-current-session` UNLESS in sub-agent.
5. **Skip checks**: `should-skip` (budget exhausted or context_percent ≥ 75); sub-agents bypass.
6. **Orchestrator branch**: if `is_orchestrator=true`, suppresses broad `/query`. Emits compact status line `[Writ: mode=X, phase=Y, gates=…, violations=N]`. If mode=work AND budget>600 AND prompt≥10, fires methodology-only `/query` with `node_types: ['Skill','Playbook']`, budget 600.
7. **Cache reads**: phase-scoped exclusion list (`loaded_rule_ids_by_phase[current_phase]`), `last_injected_rule_ids` → `prefer_rule_ids`, `detected_domain` → domain, `instructions_rule_ids` merged into exclusion list.
8. **POST /query**: curl 0.5s connect, 2s max.
9. **Low-relevance detection**: NO_RULES (empty array) or LOW_SCORES (< 0.3 threshold).
10. **Format response**: `_writ_session format` splits into rules text + `WRIT_META:` line.
11. **Always-on bundle**: GET `/always-on?mode=${CURRENT_MODE:-universal}`. Emits `=== ALWAYS-ACTIVE RULES ===` block. Tracks against `always_on_budget` via `--add-always-on-tokens`.
12. **Rules injection**.
13. **Mode classification directive** if no mode set.
14. **Mode-specific reminders**: conversation/debug/review get one-line reminders; work mode checks gate file presence.
15. **Proposal nudge** on NO_RULES or LOW_SCORES.
16. **Cache update**: rule_ids, cost, queries, sticky `last_injected_rule_ids`, full `loaded_rules`. Logs `rag_query` with `query_source: "broad"`.
17. **Methodology companion** in work mode with budget>600: second `/query` with `node_types: ['Skill','Playbook']`, budget 600. `query_source: "methodology"`.
18. **Escalation injection**: `/check-escalation`. If `needed=true`, emits failure history and sends enriched negative `/feedback` for each invalidation rule_id.
19. **Backward context**: in work mode if any gate has invalidation records but `.approved` file missing → emits `[Writ: GATE INVALIDATED -- cycle X of Y]`.

### `writ-read-rag.sh` — PreToolUse Read (303 lines)
**Mode-gated**: only fires in `review` or `debug` modes. Same shape as pretool-rag (path-based query, /query call, format, cache update). `query_source: "file-read"`.

### `writ-sdd-review-order.sh` — PreToolUse Task (71 lines)
Bails unless work mode. Acts only when `tool_input.subagent_type` contains "code-quality" or "code-review". Reads `cache.review_ordering_state[task_id]`. If `plan_reviewer_completed != true` → deny with `ENF-PROC-SDD-001` (record completion via `writ-session.py update <sid> --set-plan-reviewed <task>`).

### `writ-session-end.sh` — SessionEnd (98 lines)
PPID-derived session_id. Sequence: (1) `auto-feedback`, (2) `coverage`, (3) gate metrics: appends `## Gate: NAME -- TIMESTAMP` to `${PROJECT_ROOT}/.claude/session-metrics.md`, (4) emits `session_end` rollup with `rules_loaded, total_violations, files_written, queries, mode, final_phase`.

### `writ-subagent-start.sh` — SubagentStart (175 lines)
Requires agent_id. Reads parent's session cache. **Builds isolated cache for agent_id**: inherits `mode`/`current_phase`/`gates_approved` from parent; resets `remaining_budget=DEFAULT_SESSION_BUDGET` (telemetry only); sets `is_subagent=true` (disables budget skips). Pings `/health`; if up, extracts agent prompt (≤500 chars) and POSTs to `/query` with `budget_tokens: 2000`. Emits hookSpecificOutput with `additionalContext` containing `[Writ sub-agent: mode=X, phase=Y, gates=Z]` plus rules text. Logs `subagent_start`.

### `writ-subagent-stop.sh` — SubagentStop (82 lines)
Reads agent's cache. Emits `subagent_complete` with `agent_id, agent_type, parent_session, files_written, rules_loaded, queries, remaining_budget, denial_count`.

### `writ-verify-before-claim.sh` — PreToolUse TodoWrite + Stop (72 lines)
Bails if not work mode. For each todo with `status=completed`: requires (1) `cache.verification_evidence[tid]` to exist (`ENF-PROC-VERIFY-001`), (2) no `quality_judgment_state` artifact with `score<3 AND not overridden`.

### `writ-worktree-safety.sh` — PreToolUse Bash (67 lines)
Bails unless work mode AND command contains `git worktree add`. Extracts target path; if abs path inside repo root and `.gitignore` doesn't list the top-level dir → deny with `ENF-PROC-WORKTREE-001`.

## 3. Session Library (`bin/lib/writ-session.py`, 2090 lines)

### Cache file path
`${WRIT_CACHE_DIR:-tempfile.gettempdir()}/writ-session-{session_id}.json` (lines 58-62).

### Constants (lines 44-58)
Loaded from `writ/shared/budget.json`:
- `DEFAULT_SESSION_BUDGET` (default 8000)
- `APPROX_TOKENS_PER_RULE_FULL` (200) / `STANDARD` (120) / `SUMMARY` (40)
- `DEFAULT_ALWAYS_ON_CAP` (default 5000)

### Cache schema
See doc 12 — comprehensive table of every key.

### `cmd_*` subcommands (full surface from `main()` at line 1925)

| CLI subcommand | Function | Responsibility |
|---|---|---|
| `read <sid>` | `cmd_read` | Dump cache as JSON. |
| `update <sid> [flags]` | `cmd_update` | `--add-rules JSON`, `--cost N`, `--context-percent N`, `--inc-queries`, `--add-file PATH`, `--add-file-result PATH STATUS`, `--add-feedback-sent ID`, `--add-pretool-file PATH`, `--add-rule-objects JSON`, `--token-snapshot JSON`, `--add-failed-write JSON`, `--add-always-on-tokens N`, `--reset-task-phase`. |
| `format` | `cmd_format` | Reads /query JSON from stdin. Emits `--- WRIT RULES (N rules, MODE mode) ---` block then `WRIT_META:{rule_ids,cost}` line. |
| `should-skip <sid> [--threshold N]` | `cmd_should_skip` | Returns true (exit 0) when (NOT is_subagent) AND (remaining_budget≤0 OR context_percent≥75). |
| `mode get <sid>` | `cmd_mode("get")` | Prints mode string. |
| `mode set <mode> <sid> [--orchestrator]` | `cmd_mode("set")` | `_mode_set`: writes mode, fresh state, `current_phase = planning if work else None`. |
| `mode switch <mode> <sid>` | `cmd_mode("switch")` | `_mode_switch`: saves/restores `paused_work_state`. |
| `coverage <sid>` | `cmd_coverage` | Maps file extensions → domains and rule prefixes → domains. Universal domains: architecture, performance, testing, security, enforcement. |
| `auto-feedback <sid>` | `cmd_auto_feedback` | Correlates loaded rules' domains with file pass/fail outcomes. POSTs positive/negative signals to `/feedback`. |
| `add-pending-violation <sid> --rule R --file F [--line N] [--evidence E]` | `cmd_add_pending_violation` | Dedupes by `(rule_id, file, line)`. |
| `clear-pending-violations <sid>` | `cmd_clear_pending_violations` | Empty list. |
| `invalidate-gate <sid> <gate> --rule R --file F [--evidence E] [--trace T] [--plan-hash H]` | `cmd_invalidate_gate` | Appends `{cycle, rule_id, file, line, evidence, trace, prior_plan_hash, timestamp}` to `invalidation_history[gate]`. If cycle ≥ MAX_CYCLES_BEFORE_ESCALATION (3), sets `escalation.needed=true`. Best-effort `os.remove(.claude/gates/{gate}.approved)`. |
| `check-escalation <sid>` | `cmd_check_escalation` | Returns `{needed, gate, diagnosis, cycles}`. |
| `pending-violations <sid>` | `cmd_pending_violations` | List as JSON. |
| `can-write <sid> [--skill-dir PATH]` | `cmd_can_write` | Reads stdin envelope; calls `_can_write_check`. |
| `advance-phase <sid> [--project-root P] [--token T]` | `cmd_advance_phase` | **Requires --token matching `/tmp/writ-gate-token-{sid}`**. Logs `agent_self_approval_blocked` on mismatch. |
| `current-phase <sid>` | `cmd_current_phase` | Returns `{phase, mode, gates_approved}`. |
| `detect-compaction <sid> --context-percent N` | `cmd_detect_compaction` | If previous_pct - N > 20: clears current-phase exclusion, resets budget, clears sticky rules. |
| `clear-rules-for-compaction <sid>` | `cmd_clear_rules_for_compaction` | Empties `loaded_rules`. |
| `reset-after-compaction <sid>` | `cmd_reset_after_compaction` | PostCompact entry. |
| `metrics [--log PATH]` | `cmd_metrics` | Parses workflow-friction.log; outputs aggregate JSON. |

### Constants
- `MAX_CYCLES_BEFORE_ESCALATION = 3`
- `VALID_MODES = {"conversation","debug","review","work"}`
- `GATE_SEQUENCE_WORK = ["phase-a", "test-skeletons"]`
- `_PHASE_AFTER_GATE_WORK = {"phase-a":"testing", "test-skeletons":"implementation"}`

## 4. Parser Library (`bin/lib/parse-hook-stdin.py`, 85 lines)

Single function `parse()`:
- Reads full stdin → `envelope = json.loads(...)`.
- `tool_input` extracted: dict OR JSON string OR fallback to `CLAUDE_TOOL_INPUT` env var.
- Outputs flattened JSON: `session_id, agent_id, agent_type, event, tool_name, tool_input, tool_output, is_error, file_path, content, old_string, new_string, command`.

## 5. Common Library (`bin/lib/common.sh`, 465 lines)

| Function | Purpose |
|---|---|
| `parse_hook_stdin` | Pipes stdin through `parse-hook-stdin.py`. CALL ONCE PER HOOK. |
| `parsed_field <json> <field>` | Extract string field via Python. |
| `parsed_bool <json> <field>` | Extract bool field via shell exit code. |
| `is_work_mode <sid>` | True if mode == "work". |
| `detect_project_root <path>` | Walks up looking for `composer.json`, `package.json`, `Cargo.toml`, `go.mod`, `pyproject.toml`, `.git`. |
| `detect_session_id <parsed>` | `agent_id || session_id || PPID || md5(${PWD}:${USER})-DATE`. |
| `json_finding <is_error> <rule> <message> <file> <fix>` | Build single JSON object. |
| `json_array` | Reads JSON-per-line stdin → JSON array. |
| `find_tool <project_root> <vendor_path> <global_name>` | Vendor-first tool resolution. |
| `detect_language <file>` | Maps ext → `php\|xml\|javascript\|typescript\|python\|rust\|go\|graphql\|unknown`. |
| `log_friction_event <sid> <mode> <event> [extra_json]` | Appends JSON line to `${PROJECT_ROOT}/workflow-friction.log`. |
| `hook_timer_start` / `hook_timer_end` | Tracks `hook_execution` event with `duration_ms`. |
| `_writ_session <subcmd> [args...]` | HTTP-first dispatcher with subprocess fallback. |
| `read_project_config <root> <config_file> <default>` | One-line config readers. |

`_writ_session` URL/method map: most subcommands HTTP-call the server (`http://${WRIT_HOST:-localhost}:${WRIT_PORT:-8765}/...`). Complex args (update, invalidate-gate, add-pending-violation) go subprocess. Default timeouts: 0.1s connect, 0.5s max (pre-write-check uses 0.2/1.0).

## 6. JSON Config Files

### `bin/lib/checklists.json` (65 lines)
Three top-level phases — each `mode: "work"` and `exit_criteria[]`:
- **planning**: plan-files-listed (## Files w/ ≥1 path), plan-analysis (## Analysis), plan-rules-applied (## Rules Applied with rule ID matching `[A-Z]+-[A-Z]+-[0-9]+` or "No matching rules"), plan-capabilities (## Capabilities w/ ≥1 checkbox).
- **code_generation**: all-planned-files-written (files_written ⊇ plan list), no-pending-violations, static-analysis-pass.
- **testing**: test-files-exist, public-methods-covered, violation-patterns-tested.

`testing.public_method_patterns` provides regex per language for method-detection.

### `bin/lib/gate-categories.json` (488 lines)
Schema: `version=2`, `framework_detection`, `exclusions`, `categories`.

`framework_detection`: magento2, laravel, django, rails, spring, nestjs, express.

`exclusions`: glob patterns NOT gated — `*__init__.py`, `*conftest.py`, `*/test/*`, `*/tests/*`, `*Test.php`, `*_spec.py`, `*/migrations/*`, `*/.claude/*`.

`categories[]` — six categories (any_source_file → phase-a, event_wiring → phase-a, validation → phase-b, integration_point → phase-c, concurrency → phase-d, implementation → test-skeletons).

> **NOTE**: `_can_write_check` only USES `exclusions`. The category-specific phase-b/c/d rules are not enforced by the v2 mode/gate system, which uses only phase-a + test-skeletons. This file is a holdover from earlier design.

## 7. Mode System — Allow vs Deny vs Ask

Source of truth: `_can_write_check` in writ-session.py (lines 1077-1178).

### Decision matrix

| Condition | Decision | Reason ID |
|---|---|---|
| `is_subagent=True` | allow (logs `subagent_bypass`) | — |
| file_path empty | allow | — |
| file inside `skill_dir/` or `~/.claude/settings*` | allow | infrastructure |
| basename == `plan.md` AND mode is None | allow | pre-mode escape hatch |
| basename == `capabilities.md` | allow always | — |
| basename == `plan.md` AND mode=work AND `current_phase=implementation` | deny | `[ENF-GATE-PLAN]` |
| basename == `plan.md` AND mode=work otherwise | allow | — |
| mode is None (any other file) | deny | `[ENF-GATE-MODE]` |
| mode in {conversation, debug, review} | allow (logs `gate_status=no_gates`) | — |
| mode=work AND file matches `exclusions[]` | allow (logs `gate_status=excluded`) | — |
| mode=work AND `phase-a` not in `gates_approved` | deny | `[ENF-GATE-PLAN]` |
| mode=work AND `test-skeletons` not in `gates_approved` | deny | `[ENF-GATE-TEST]` |
| mode=work AND both gates approved | allow (logs `gate_status=all_approved`) | — |

The "ask" decision is added by `writ-pre-write-dispatch.sh` and `check-gate-approval.sh`: when `denial_counts[gate] >= 2`, the deny is escalated to `permissionDecision: "ask"`.

## 8. RAG Injection Flow End-to-End

Orchestrating hook: **`writ-rag-inject.sh`** on UserPromptSubmit. See §2 entry above for full structure.

Other RAG entry points:
- `writ-pre-write-dispatch.sh` (PreToolUse Write/Edit): consolidated `POST /pre-write-check` returns `{decision, reason, rag_rules, rag_meta}` and embeds the file-path-derived RAG query the legacy `writ-pretool-rag.sh` used to fire. Source: `file-write-pre`.
- `writ-posttool-rag.sh` (PostToolUse Write/Edit): code-derived query. Source: `file-write-post`.
- `writ-read-rag.sh` (PreToolUse Read): only review/debug modes. Source: `file-read`.

### Token budget enforcement
- Session budget: `cache.remaining_budget` decremented on each `--cost`; `should-skip` returns true when ≤ 0.
- Always-on budget: `always_on_tokens_used` increments via `--add-always-on-tokens`; `always_on_budget` decrements (independent cap of 5000).
- Per-call budget caps: PreTool/PostTool 1500; UserPromptSubmit uses `remaining_budget`; methodology companion 600.
- Sub-agents: `is_subagent=True` makes `cmd_should_skip` always return False.

## 9. Sub-Agent Handling

`writ-subagent-start.sh` sets `is_subagent: True`. The flag drives:

1. **`cmd_should_skip`**: `if is_subagent: return False` — unlimited RAG injection.
2. **`_can_write_check`**: `if is_subagent: return {"can_write": True}` — bypasses ALL gate enforcement. Logs `gate_status=subagent_bypass`.
3. **`writ-rag-inject.sh`**: does NOT overwrite `/tmp/writ-current-session` when `AGENT_ID` is set.
4. **`auto-approve-gate.sh`**: same protection.
5. **Two-flag distinction**: `is_subagent` (set by writ-subagent-start.sh) vs `is_orchestrator` (set via `mode set work --orchestrator`). Sub-agent flag bypasses gates AND budget skips; orchestrator flag suppresses broad RAG and emits compact status line for the master.

### Sub-agent session cache shape
```
mode: <inherits from parent>
current_phase: <inherits from parent>
gates_approved: <inherits from parent>
remaining_budget: DEFAULT_SESSION_BUDGET    # fresh, telemetry only
is_subagent: True
loaded_rule_ids: []
loaded_rule_ids_by_phase: {}
loaded_rules: []
denial_counts: {}
queries: 0
context_percent: 0
files_written: []
analysis_results: {}
pending_violations: []
feedback_sent: []
pretool_queried_files: []
token_snapshots: []
```

## 10. `bin/run-analysis.sh` — cross-language static analysis (added 2026-05-10)

The analyzer router grew from ~387 lines to ~1,053 lines during the Phase 1-5 public-rulebook expansion. It now contains 7 per-language entry points and 6 cross-cutting public-rulebook analyzers. The per-language analyzers are called first; the cross-cutting analyzers run after each on the same file. All findings flow through the same `[ENF-POST-007]` channel that `pre-validate-file.sh` consumes.

### Per-language analyzers (`bin/run-analysis.sh:41-310`)

| Function | Lang | Mechanism |
|---|---|---|
| `analyze_php` | PHP | PHPStan level 8 + PHPCS sniffs (vendor-resolved via `find_tool`) |
| `analyze_xml` | XML | `xmllint` schema + DTD validation |
| `analyze_js_ts` | JavaScript/TypeScript | ESLint + tsc-strict via `find_tool` |
| `analyze_python` | Python | `ruff check` (vendor-resolved) |
| `analyze_rust` | Rust | `cargo check --quiet` (vendor-resolved) |
| `analyze_go` | Go | `go vet` + `staticcheck` |
| `analyze_graphql` | GraphQL | schema validation |

### Public-rulebook analyzers (`bin/run-analysis.sh:352-998`)

Each is a regex pass implemented inline as `python3 - <<'PYEOF' "$file" "$lang"`. Each skips `scripts/seed_*.py` (the seed scripts embed example bad-code as documentation in rule `violation` fields).

| Function | Phase | Mandatory rules backed |
|---|---|---|
| `analyze_security_injection` | 1A | SEC-INJ-SQL-001, XSS-001, CMD-001, SSRF-001, DESER-001, CSRF-001 (+ advisory SEC-INJ-PATH-001, LDAP-001, SSTI-001, HEADER-001, LOG-001, XSS-002, XSS-003, CMD-002, REDIR-001) |
| `analyze_security_auth_authz` | 1B | SEC-AUTH-HASH-001, TOKEN-001; SEC-AUTHZ-ENFORCE-001, IDOR-001, DEFAULT-001, MASS-001; SEC-VAL-SERVER-001, FILE-001 |
| `analyze_security_crypto_headers` | 1C | SEC-CRYPTO-KEY-001, RAND-001 (+ advisory ALGO-001, CERT-001) |
| `analyze_security_data_protection` | 1D | SEC-DATA-PII-001 |
| `analyze_performance_n_plus_one` | 3B | PERF-QUERY-001 (warning, not error — heuristic) |
| `analyze_scaling_stateless` | 4 | SCALE-STATELESS-001 (warning, not error — heuristic) |

Each analyzer emits JSON-per-line via `emit(line_no, rule, tool, message, severity)`, where `severity ∈ {error, warning}`. `pre-validate-file.sh` denies the write only on `severity = error`; warnings surface as advisories.

## Files Read (original 2026-05 extraction pass)

| Path | Lines |
|---|---|
| `templates/settings.json` | 360 |
| `templates/CLAUDE.md` | 83 |
| `templates/commands/writ-approve.md` | 31 |
| `.claude/commands/writ-approve.md` | 31 |
| `.claude/settings.local.json` | 100 |
| `.claude/hooks/auto-approve-gate.sh` | 213 |
| `.claude/hooks/enforce-violations.sh` | 64 |
| `.claude/hooks/friction-logger.sh` | 235 |
| `.claude/hooks/inject-tier-workflow.sh` | 87 |
| `.claude/hooks/pre-validate-file.sh` | 92 |
| `.claude/hooks/track-failed-writes.sh` | 78 |
| `.claude/hooks/validate-design-doc.sh` | 82 |
| `.claude/hooks/validate-exit-plan.sh` | 165 |
| `.claude/hooks/validate-file.sh` | 70 |
| `.claude/hooks/validate-handoff.sh` | 131 |
| `.claude/hooks/validate-rules.sh` | 412 |
| `.claude/hooks/validate-test-file.sh` | 80 |
| `.claude/hooks/writ-context-tracker.sh` | 10 |
| `.claude/hooks/writ-cwd-changed.sh` | 93 |
| `.claude/hooks/writ-instructions-loaded.sh` | 105 |
| `.claude/hooks/writ-memory-policy-guard.sh` | 196 |
| `.claude/hooks/writ-postcompact.sh` | 55 |
| `.claude/hooks/writ-posttool-rag.sh` | 330 |
| `.claude/hooks/writ-precompact.sh` | 31 |
| `.claude/hooks/writ-pressure-audit.sh` | 55 |
| `.claude/hooks/writ-pre-write-dispatch.sh` | 164 |
| `.claude/hooks/writ-quality-judge.sh` | 100 |
| `.claude/hooks/writ-rag-inject.sh` | 994 |
| `.claude/hooks/writ-read-rag.sh` | 303 |
| `.claude/hooks/writ-sdd-review-order.sh` | 71 |
| `.claude/hooks/writ-session-end.sh` | 98 |
| `.claude/hooks/writ-subagent-start.sh` | 175 |
| `.claude/hooks/writ-subagent-stop.sh` | 82 |
| `.claude/hooks/writ-verify-before-claim.sh` | 72 |
| `.claude/hooks/writ-worktree-safety.sh` | 67 |
| `bin/check-gates.sh` | 60 |
| `bin/run-analysis.sh` | 1,053 (was 387 at original extraction; 6 new analyzers added) |
| `bin/scan-deps.sh` | 362 (not detail-read) |
| `bin/validate-handoff.sh` | 87 |
| `bin/verify-files.sh` | 76 |
| `bin/lib/parse-hook-stdin.py` | 85 |
| `bin/lib/writ-session.py` | 2,090 |
| `bin/lib/common.sh` | 465 |
| `bin/lib/checklists.json` | 65 |
| `bin/lib/gate-categories.json` | 488 |

`bin/verify-matrix.sh` (originally 268 lines) was deleted 2026-05-10 along with the Phase A-D / `ENF-GATE-FINAL` workflow it served. Total per the original extraction: 49 files read; ~9,400 lines covered. The current set is 46 files / ~9,700 lines (analyzer growth offsets the 3 deleted files).

## Cross-References Noted

- **Gate token flow**: `auto-approve-gate.sh` creates `/tmp/writ-gate-token-{sid}`. `cmd_advance_phase` requires `--token` matching this file. Agent self-approval via raw bash POST is blocked.
- **Two-flag distinction**: `is_subagent` (writ-subagent-start.sh) vs `is_orchestrator` (`mode set work --orchestrator`).
- **Phase-scoped exclusion**: All RAG hooks read `loaded_rule_ids_by_phase[current_phase]`.
- **v2 wiring vs v1 legacy**: `templates/settings.json` does NOT register `check-gate-approval.sh` or `enforce-final-gate.sh`. `writ-pre-write-dispatch.sh` consolidates them via `/pre-write-check`.
- **Compaction recovery**: real signal is PostCompact hook → `reset-after-compaction`.
- **Common library env vars**: `WRIT_HOST` (default localhost), `WRIT_PORT_OVERRIDE` (pins the port; else per-repo derived in `common.sh` as `8765 + cksum(repo_root) % 1000`, D4-02 — bare `WRIT_PORT` is ignored by common.sh, honored only by standalone stop/ensure-server scripts), `WRIT_CACHE_DIR`, `WRIT_HOOK_LOG`, `WRIT_DEBUG_LOG`, `WRIT_SESSION_ID`.
- **Session ID derivation chain**: `agent_id || session_id (envelope) || PPID || md5(${PWD}:${USER})-DATE`.
- **Mode set vs switch**: `mode set` resets phase/gates/state. `mode switch` saves and restores `paused_work_state`.
- **Gate sequence**: only two gates in v2 — `phase-a` (post-plan-approval) and `test-skeletons` (post-test-approval).
