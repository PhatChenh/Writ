# Writ Debug Records

Running log of Writ runtime/integration bugs hit while operating the plugin, with
the **exact failure signature, root cause, and fix** for each. Read this before
debugging "writ isn't working" — most symptoms here look different but share a few
root causes (port derivation, the plugin-cache copy, daemon lifecycle under Claude
hooks, macOS python 3.9).

Last updated: 2026-06-23.

---

## Mental model — read first (the things that bite repeatedly)

1. **There are TWO copies of every hook/script.**
   - The **repo** (`/Users/phatchenh/01_all_projects/falkor-writ`) — canonical source.
   - The **plugin cache** Claude actually runs:
     `~/.claude/plugins/cache/writ/writ/<version>/` (`CLAUDE_PLUGIN_ROOT`).
     This is a **copy** made at `claude plugin install` time, NOT a symlink.
   - **Editing the repo does NOT change what Claude runs.** A fix only takes effect
     after you either (a) `cp` the file into the cache, or (b) reinstall the plugin
     (re-copies from the repo working tree), AND restart Claude Code (hooks load at
     session start).
   - `~/.claude/skills/writ` is a **symlink → repo** (separate from the plugin cache).

2. **Per-repo daemon port is DERIVED, never stored.**
   `WRIT_PORT = 8765 + cksum(repo_root) % 1000`, computed in `bin/lib/common.sh`.
   `repo_root = git rev-parse --show-toplevel`. There is no port-record file.
   - Examples: falkor-writ → **9041**, mkt_engine → **8804**, Iris → **9032**.
   - The derivation is **fragile to inputs**: a trailing slash or a different
     `WRIT_REPO_ROOT` yields a *different* port → daemon and hook disagree → "offline".

3. **macOS system `python3` is 3.9** and cannot parse `str | None` (3.10+). Writ's
   Python (`writ-session.py` etc.) REQUIRES ≥3.11. Always use the venv interpreter
   `~/.cache/writ/.venv/bin/python` or `$WRIT_PYTHON` (resolver in common.sh).

4. **Claude Code reaps hook-spawned background processes** unless they fully detach
   (close stdin + new session). A daemon that inherits the hook's stdin (Claude's
   stream-json pipe) blocks the hook's return → Claude SIGTERMs the whole spawned
   tree. `nohup` alone is NOT enough.

5. **"writ online" can be a mirage.** A leftover daemon answering `/health` does NOT
   mean hooks fire. If the plugin is uninstalled (cache gone), NO hooks run anywhere,
   but an orphan daemon still serves `/health`. Always check the plugin cache exists
   AND rag-debug is logging, not just `/health`.

---

## Diagnostic quick-reference

```bash
# Per-repo port for a repo:
r=/path/to/repo; echo $(( 8765 + $(printf '%s' "$r" | cksum | cut -d' ' -f1) % 1000 ))

# Is the daemon up / what port is a daemon on:
curl -s http://127.0.0.1:<port>/health
lsof -nP -p <pid> | grep LISTEN

# List all writ daemons (BOTH launch forms):
pgrep -fa 'uvicorn writ\.server:app|/writ serve'

# A daemon's repo (cwd) and whether it's detached:
lsof -a -p <pid> -d cwd -Fn | sed -n 's/^n//p'   # repo
ps -o ppid= -p <pid>                              # PPID 1 = detached/persistent
lsof -a -p <pid> -d 0                             # stdin; want /dev/null

# Did hooks fire? (recreated on every rag-inject invocation):
tail /tmp/writ-rag-debug.log

# Does Claude actually run the fixed hook? (the cache copy, not the repo):
ls ~/.claude/plugins/cache/writ/writ/*/ && grep -c '</dev/null' \
  ~/.claude/plugins/cache/writ/writ/*/.claude/hooks/writ-rag-inject.sh

# Per-repo redis socket dir:
echo /tmp/writ-$(printf '%s' "/path/to/repo/.writ" | md5 | cut -c1-12)

# Clean stale embedded-server state for a repo:
pkill -f 'redis-server unixsocket:/tmp/writ-<md5>' ; rm -f /tmp/writ-<md5>/redis.sock <repo>/.writ/graph.lock
```

---

## Bug log

### B1 — Orphan daemon on the wrong port; 3-way port disagreement
- **Symptoms:** bootstrap "daemon did not become healthy within 10s"; rag hook
  `[Writ: server unavailable]`; ingest `RuntimeError: Writ graph DB is locked by PID 57907`.
- **Logs:** `~/.cache/writ/server.log` startup `RuntimeError: ... locked by PID 57907`;
  `/tmp/writ-rag-debug.log`: `repo_root=.../falkor-writ port=9041 ... failed: empty response from server`.
- **Cause:** three components computed three different ports —
  running daemon on **9436** (its `WRIT_REPO_ROOT` had resolved to the skill dir
  `~/.claude/skills/writ`), the rag hook on **9041** (cksum of the git root),
  bootstrap-plugin.sh hard-coded **8765**. The 9436 daemon held the project's
  `graph.lock`, so nothing else could bind.
- **Fix:**
  - `writ/cli.py`: `DEFAULT_PORT = int(os.environ.get("WRIT_PORT", "8765"))` so
    `writ serve` honors the per-repo port instead of hardcoding 8765.
  - `scripts/bootstrap-plugin.sh`: compute the per-repo port (mirror of common.sh)
    and use it for the daemon URL/health/banner instead of 8765.
  - `bin/lib/common.sh`: when `git rev-parse` fails, walk up from `$PWD` to find
    `.writ/`/`.git/` before falling back to the skill dir.

### B2 — `WRIT_PORT` override-inheritance drift
- **Symptom:** daemon on a port that doesn't match the repo even though cwd is correct.
- **Cause:** common.sh honored a bare inherited `WRIT_PORT`. A stale value exported
  into the env decoupled the port from the repo root (B1's 9436 was this).
- **Fix:** `WRIT_PORT` is now ALWAYS derived from the repo root; the only explicit
  override is `WRIT_PORT_OVERRIDE` (opt-in, can't leak by accident). 7 tests that set
  `WRIT_PORT=19999` were migrated to `WRIT_PORT_OVERRIDE`.

### B3 — Trailing-slash port mismatch
- **Symptom:** SessionStart daemon came up on **8909**, rag hook queried **9041** (same repo).
- **Cause:** a repo root arriving with a trailing slash hashes differently:
  `cksum(".../falkor-writ/") != cksum(".../falkor-writ")` → 8909 vs 9041.
- **Fix:** `bin/lib/common.sh` normalizes `WRIT_REPO_ROOT="${WRIT_REPO_ROOT%/}"`
  before hashing, so slash/no-slash map to the same port.

### B4 — Hook-spawned daemon reaped by Claude (the big one)
- **Symptoms:** daemon "works when I run the hook manually" but never persists when
  Claude runs it; `<repo>/.writ/redis.log` shows redis getting `SIGTERM` ~0.2s after
  every start; rag-debug `failed: empty response from server`.
- **Cause:** the auto-start used `nohup python -m uvicorn ... >>log 2>&1 &` — it
  redirected stdout/stderr but **left stdin inherited** from the hook (Claude's
  stream-json pipe). Holding that pipe open blocks the hook's return, so Claude's
  cleanup SIGTERMs the spawned process tree. (Claude Code GitHub issue **#43123**;
  `nohup` only ignores SIGHUP, not this SIGTERM.)
- **Fix:** add `</dev/null` (+ `disown`) to all daemon launches:
  `.claude/hooks/writ-rag-inject.sh`, `bin/writ-project-rules.sh`,
  `hooks/scripts/session-start-bootstrap.sh`.
- **Verify:** the live daemon should show `PPID=1` and stdin `/dev/null`
  (`lsof -a -p <pid> -d 0`).

### B5 — Plugin uninstalled → hooks dead globally, but "writ online"
- **Symptoms:** a repo (Iris) had no `.writ/` and no daemon despite "writ online";
  `/tmp/writ-rag-debug.log` had ZERO entries for it; this happened in *every* repo.
- **Cause:** the writ plugin had been removed via `claude plugin uninstall writ@writ`
  — `~/.claude/plugins/cache/writ` gone, registry scrubbed (settings.json
  `enabledPlugins`/`extraKnownMarketplaces`, `installed_plugins.json`,
  `known_marketplaces.json`). With no plugin, **no hooks load in any session**. A
  leftover `writ serve` daemon kept answering `/health` on 9041 → false "online".
- **Fix / restore:**
  ```bash
  claude plugin marketplace add /Users/phatchenh/01_all_projects/falkor-writ
  claude plugin install writ@writ
  bash scripts/bootstrap-plugin.sh
  # then RESTART Claude Code (hooks load at session start)
  ```
- **Tell-tale:** no `*.bak.*` files next to settings.json ⇒ it was the official
  `claude plugin uninstall`, not `scripts/uninstall-plugin.sh` (that one backs up first).

### B6 — `uninstall-plugin.sh` left a `writ serve` daemon orphaned
- **Cause:** the kill pattern `pkill -f 'uvicorn writ.server:app'` matches the hook
  auto-start form (`python -m uvicorn writ.server:app`) but NOT the bootstrap/CLI form
  (`.../bin/writ serve`, whose cmdline has no "uvicorn writ.server:app").
- **Fix:** pattern is now `'uvicorn writ\.server:app|/writ serve'` (matches both).

### B7 — mode-set crash: `TypeError: unsupported operand type(s) for |: 'type' and 'NoneType'`
- **Symptom:** setting a Writ mode via the directive Claude is told to run crashes.
- **Log:** `TypeError: unsupported operand type(s) for |: 'type' and 'NoneType'`
  from `bin/lib/writ-session.py` (it uses `str | None` type hints).
- **Cause:** the rag-inject directive printed `Declare: python3 .../writ-session.py
  mode set ...`. Claude runs that in a fresh shell where `python3` = macOS system
  3.9.6, which can't parse `str | None`. (Inside hooks it works because common.sh
  defines a `python3()` function wrapping `$WRIT_PYTHON`; a fresh Claude shell has no
  such function.)
- **Fix:** the directive now prints `$WRIT_PYTHON` (resolved ≥3.11) instead of bare
  `python3`. `.claude/hooks/writ-rag-inject.sh` (two `Declare:` heredocs).

### B8 — Session-open daemon-start race (intermittent "not online" on new sessions)
- **Symptoms:** a freshly opened session's repo daemon dies; intermittent (some repos
  win, some lose on the same restart); `~/.cache/writ/server.log`:
  `RuntimeError: Writ graph DB is locked by PID N` (different N each attempt).
- **Cause:** on session open, **two hooks both try to start the daemon** —
  `hooks/scripts/session-start-bootstrap.sh` and `.claude/hooks/writ-rag-inject.sh`.
  Two simultaneous starts collide on db.py's single-writer `graph.lock`; the loser
  dies, and sometimes the winner too → no surviving daemon. rag-inject had a per-port
  start-lock (`/tmp/writ-server-starting-<port>.lock`) but session-start didn't honor it.
- **Fix:** both paths now coordinate through the SAME start-lock — whoever acquires it
  starts; the other just waits for `/health`. Both also do **stale-lock recovery**
  (steal the lock if its owner PID is dead) so a crashed starter can't wedge auto-start.

---

### B9 — Reaped daemon leaves a stale socket -> every auto-restart fails to bind (~27min outage)
- **Symptoms:** rag hook `[Writ: server unavailable, proceeding without rules]`; `<repo>/.writ/redis.log` ends `Received SIGTERM ... bye bye`; nothing listening on the per-repo port; rag-debug shows the hook FIRED (auto-start ran) seconds after the crash, yet no daemon ever came up; a later *clean* manual start works first try.
- **Cause:** when Claude reaps the daemon (B4/B8 class), redis can leave a stale `/tmp/writ-<md5(.writ)>/redis.sock` with no live listener. db.py startup does `if os.path.exists(socket)` (`db.py:55`) and short-circuits onto the dead socket -> `ConnectionRefusedError` -> uvicorn never binds. The auto-start recovery only stole the *start-lock*, never the stale socket, so every restart re-hit the dead socket until the OS cleared it. (db.py already steals a dead-owner `graph.lock` at `db.py:71-84`, so the LOCK was not the blocker -- the SOCKET was.)
- **Fix:** new `writ_clean_stale_embedded_state()` in `bin/lib/common.sh`, called inside BOTH auto-start paths (`hooks/scripts/session-start-bootstrap.sh`, `.claude/hooks/writ-rag-inject.sh`) right after `/health` fails and INSIDE the per-port start-lock, before spawning uvicorn. Removes a stale socket (only after `redis-cli ping` proves it is NOT a healthy redis) + a dead-owner `graph.lock`.
- **Clobber-safety (critical):** a *healthy* redis (PONG) is left UNTOUCHED. Killing a healthy redis triggers a shutdown BGSAVE that can clobber `graph.db` to empty (the documented orphan-BGSAVE incident). Verified: stale socket+dead lock -> removed; live daemon (PONG, rule_count intact) -> untouched.

### B10 — Hardcoded `/Users/<other-user>/...` hook path in COMMITTED settings.json blocks Read on a different machine
- **Symptoms:** every Grep/Glob/Read errors `PreToolUse:Read hook error ... can't open file '/Users/phatchenh/.codegraph-piggyback/codegraph_adoption/codegraph-gate.py' ... No such file`. Read tool unusable for the whole session (Edit too -- it needs a prior Read).
- **Cause:** `<repo>/.claude/settings.json` registers the codegraph-gate PreToolUse hook with an ABSOLUTE path baked in by `codegraph-piggyback/piggyback.py` `hook_command()` (`python3 {(ROOT/script).resolve()}`, `piggyback.py:91-97`; `ROOT = Path(__file__).resolve().parent`). Committed on one machine (`phatchenh`), the absolute path travels via git to another machine (`lap14806`) where it does not exist. "Many machines" = guaranteed breakage.
- **Fix (immediate):** replaced `/Users/<user>/` -> `$HOME` in the committed settings (`Writ` + `mkt_engine` `.claude/settings.json` codegraph-gate; global `~/.claude/settings.json` caveman hooks + impact-analyzer line 51). The shell expands `$HOME` at hook-run time -> portable across machines/users. Left global `path: /Users/.../all-projects/Writ` (plugin-source root, genuinely absolute). JSON validated; gate runs exit 0.
- **Caveat:** hook configs load at SESSION START -- the session that hit the broken hook keeps it until Claude restarts.
- **Root-cause / install-script fix (SEPARATE REPO -- ✅ DONE 2026-06-23):** `codegraph-piggyback/piggyback.py` `hook_command()` wrote the resolved ABSOLUTE path; now emits a `$HOME`-relative token via new `_portable_path()` when the script lives under `Path.home()` (else absolute fallback). `is_owned()` updated to recognize BOTH the portable (`$HOME/<rel>`) and legacy-absolute forms, so old entries migrate on the next `piggyback update` without churn; cross-machine legacy abs (e.g. `/Users/phatchenh/...`) stays conservatively unowned (already hand-fixed). +2 portability tests (`test_piggyback.py` 17/17 green). Synced to BOTH clones (dev `~/all-projects/codegraph-piggyback` + canonical install `~/.codegraph-piggyback`); the installed tool now emits `python3 $HOME/.codegraph-piggyback/codegraph_adoption/codegraph-gate.py`, matching the manual settings fix. Durable propagation = commit+push from dev, `piggyback update` re-pulls.

### B11 — Plugin agents never register (manifest missing the `agents` key)
- **Symptoms:** in any repo OTHER than Writ, `writ-plan-reviewer` / `writ-code-quality-reviewer` (+ the other 4 writ agents) are absent from the agent-type list; `ls "$CLAUDE_PLUGIN_ROOT/agents/"` is empty. They appear ONLY inside the Writ repo.
- **Cause:** `.claude-plugin/plugin.json` declared `commands` + `hooks` (non-default paths) but OMITTED `agents`. The 6 agent files live in `.claude/agents/` (non-default; the loader default is `agents/` at plugin root, which Writ does not have), so they never registered as PLUGIN agents. Inside the Writ repo they showed up only as PROJECT agents (Claude auto-loads `<cwd>/.claude/agents/`). caveman works because ITS agents sit in the default `agents/` dir.
- **Fix:** added `"agents": [ "./.claude/agents/writ-*.md" x6 ]` to the manifest (schema confirms `agents` = string|array of `.md` paths relative to plugin root). Future `claude plugin install` reads the corrected manifest -> agents register in every repo. **Restart Claude to reload the manifest.** No bootstrap-script change (bootstrap copies the manifest, does not generate it).

### B12 — Global `/tmp/writ-current-session` clobbered across concurrent repos (gate deny / phantom phase reset)
- **Symptoms:** in a repo with a second Claude session open elsewhere: `writ-sdd-review-order` denies the code-quality reviewer even after `--set-plan-reviewed` "succeeded"; a phase advance (planning->testing) later reads back as `planning`; `/writ-approve` / mode-set act on the wrong session. Two session ids appear "live at once."
- **Cause:** the "current session" pointer was a SINGLE global file `/tmp/writ-current-session`. Every repo's UserPromptSubmit (`writ-rag-inject`) writes it; with N concurrent repos it is last-writer-wins. Consumers (the SDD gate's writer skills, `writ-mode-set`, `enforce-violations`, `validate-exit-plan`, `friction-logger`, `track-failed-writes`, `writ-subagent-start`, `/writ-approve`) then read **another repo's** session id. The daemon/port/graph were already per-repo (D4-02); this pointer was the one remaining global. **Live proof:** the file held mkt_engine's `1a5e5f50` while the Writ session was `b6433218`.
- **Fix (2026-06-23):** `common.sh` now exports `WRIT_CURRENT_SESSION_FILE=/tmp/writ-current-session-${WRIT_PORT}` (keyed on the per-repo port). All producers/consumers use it. Per-repo, so concurrent repos cannot clobber each other.
- **Related, same session (codegraph-found):**
  - **`_mode_set` reset every `mode set work`** (`writ-session.py:892-896`) — phase + gates were wiped on EVERY call, not just real mode changes; the per-turn mode nag re-emits `mode set work`, discarding mid-task advances. Now idempotent on an unchanged mode.
  - **SDD-gate writer line in the two review skills used bare `python3` + `2>/dev/null || true`** — on macOS 3.9 the `writ-session.py` import crashes (no `from __future__ import annotations`; `str | None`) and the redirect swallowed it -> setter silently no-op'd -> gate denied forever. Now `source common.sh` (=> `$WRIT_PYTHON` wrapper + per-repo pointer) and surfaces the error.
  - Gate `task_id` collapses to `"default"` (no `task_id` in the Task envelope; `active_phase` is set only by the test-only `/active-playbook` endpoint). Writer skills now pass the literal `default` to match; `--reset-plan-reviewed <task>` added to re-arm per task.
- **Full diagnosis:** `docs/writ-bugs-2026-06-23.md`.

---

## Session block — 2026-06-23 (mkt_engine P0 build via `/subagent-driven-development`)

Observed from the **running plugin cache** while driving an 11-phase P0 implementation
(Phases 1–6 built) with the Writ two-stage reviewer agents. `Fix:` intentionally left
EMPTY below for the next AI to handle. Two genuinely-new bugs (B13, B14) + two new minor
diagnostics (B15, B16), then a re-observation table for bugs already logged above whose
fixes did **not** take effect in the cache this session.

### B13 — Writ TDD gate (`ENF-PROC-TDD-001`) is basename-strict, forcing test-file names
- **Severity:** medium (ergonomics + collisions).
- **Symptom:** writing `lib/<dir>/<X>.ts` is DENIED until `tests/<X>.test.ts` exists — the gate maps impl→test purely by file **basename**. Intent-named tests are rejected. Worse, when two seams' impl entrypoints are both `index.ts` (e.g. storage factory + analytics index + llm index), they all want `tests/index.test.ts` → collision; implementers fell back to generic names (`types.test.ts`, `s3.test.ts`, `noop.test.ts`) dictated by the gate, not by intent. Also forced an extra `tests/noop.test.ts` for `lib/analytics/sinks/noop.ts` beyond the plan's named test list.
- **Evidence:** Phase 4/5/6 implementers each reported the gate rejecting their first-choice test filename; `lib/analytics/sinks/noop.ts` write blocked until `tests/noop.test.ts` was created.
- **Affected:** the TDD gate that maps production→test (`ENF-PROC-TDD-001`; the `tests/**` matcher).
- **Root cause:** basename-only mapping with no support for (a) intent-named tests, (b) directory-qualified mapping (`lib/a/index.ts` vs `lib/b/index.ts`), or (c) a single test file covering multiple small sibling modules.
- **Fix (2026-06-23, `validate-test-file.sh`):** the gate now accepts a write on EITHER of two conditions (option "Both: mirror OR content-match"):
  - **PASS A — directory-qualified mirror.** Candidate test paths are now mirrored under the impl's repo-relative subdir, not just basename: `lib/storage/index.ts` → `tests/storage/index.test.ts`, `lib/analytics/index.ts` → `tests/analytics/index.test.ts`. The two `index.ts` seams get DISTINCT candidates → the `tests/index.test.ts` collision is gone. (Bare-basename candidates kept too, for backward compat.)
  - **PASS B — intent-named test references the impl.** Walks `tests/`,`test/`,`__tests__`,`spec/` for ANY file that (a) has assertion markers (`assert|expect|should|test_|it(|describe(`) AND (b) has an `import`/`from`/`require`/`use`/`include` line that names this impl. Lets a test be named for the behavior it covers (`tracks-events.spec.ts`) instead of the impl filename.
  - **False-accept guard:** PASS B requires an actual import/require LINE naming the impl path (`lib[/.]storage[/.]index`), parent-qualified stem (`storage[/.]index`), or — only for a distinctive stem (len≥3, not in `{index,main,mod,init,app,lib,types,__init__}`) — the bare stem as a `\b`-bounded import token. A mere comment mention does NOT pass. Verified 7 cases (mirror-pass / collision-deny / intent-pass TS+Py / distinctive-stem-pass / comment-only-deny / no-test-deny). Synced to plugin cache.

### B14 — `writ-run-pending-tests.sh:42` uses `declare -A` under macOS bash 3.2 → Stop hook crashes
- **Severity:** medium (Stop-hook silently no-ops on macOS).
- **Symptom:** on session Stop:
  ```
  /Users/lap14806/all-projects/Writ//.claude/hooks/writ-run-pending-tests.sh: line 42: declare: -A: invalid option
  declare: usage: declare [-afFirtx] [-p] [name[=value] ...]
  ```
- **Evidence:** Stop-hook feedback, this session.
- **Affected:** `/Users/lap14806/all-projects/Writ/.claude/hooks/writ-run-pending-tests.sh:42` (`declare -A`).
- **Root cause:** `declare -A` (associative array) requires bash ≥4. macOS ships bash **3.2.57** (last GPLv2 bash); the hook's shebang resolves to `/bin/bash` (3.2). The "run pending tests on stop" hook therefore aborts at line 42 and never runs. (Note: the double slash `Writ//.claude` in the path is cosmetic, not the cause.)
- **Fix (2026-06-23, `writ-run-pending-tests.sh`):** removed the 4 associative arrays. Test files are now grouped by runner via a temp `KEY<TAB>testfile` pairs file (`$LOG_DIR/.runner-pairs.tmp`), where `KEY="CMD|CFG"`. Unique KEYs come from `cut -f1 | awk '!seen'`; for each KEY, `CMD`/`CFG` are split back out with `${KEY%%|*}` / `${KEY#*|}` (CMD has no `|`), `FMT` re-derived from CMD via `case`, and `FILES` collected with `awk -F'\t' '$1==k'`. The `while … done <<< "$KEYS"` here-string runs in the current shell, so `OVERALL_RC`/`SUMMARY_FMT` mutations persist (same as the old `for` loop). Verified: `bash -n` clean under bash 3.2 + functional group test (two pytest files grouped together, phpunit separate). Synced to plugin cache.

### B15 — `/tmp/writ-hook-debug.log` stays empty despite the hook's `tee` capture
- **Severity:** low (diagnostics gap — made B1/B12 hard to diagnose).
- **Symptom:** `writ-sdd-review-order.sh` does `exec 2> >(tee -a /tmp/writ-hook-debug.log >&2)` (comment claims "Phase 4c diagnostics"), but `/tmp/writ-hook-debug.log` was empty when the gate denied — so the SID the gate actually resolved could not be observed; had to import `_read_cache` manually to diagnose.
- **Affected:** `/Users/lap14806/all-projects/Writ/.claude/hooks/writ-sdd-review-order.sh` (the `tee`/`exec 2>` capture).
- **Root cause (suspected):** the Python deny-path writes nothing to stderr on a normal deny (it only `print()`s the deny JSON to stdout), so there is nothing for `tee` to capture; the diagnostic never records WHICH session id / task_id the gate read. No verbose/debug line on the allow/deny decision.
- **Fix (already resolved by the B6/B12 work, verified 2026-06-23):** `writ-sdd-review-order.sh` now emits two UNCONDITIONAL stderr diagnostics — `[writ-sdd-review-order] resolved session_id=$SESSION_ID` (line 28, every work-mode invocation) and `[writ-sdd-review-order] task_id=… plan_reviewed=…` (Python, line 69, on every code-quality dispatch). The root cause ("nothing written to stderr") no longer holds, so the `tee -a /tmp/writ-hook-debug.log` capture now populates. Confirmed the `exec 2> >(tee -a … >&2)` pattern flushes the log on hook exit (isolated repro wrote both diag lines). No new code needed for B15.

### B16 — `writ-session.py get <sid>` emits non-JSON (or `get` is not a subcommand)
- **Severity:** low (inspection ergonomics).
- **Symptom:** `python3 writ-session.py get "$SID"` piped to `json.load` failed `JSONDecodeError: Expecting value: line 1 column 1 (char 0)`. State inspection only worked by importing `_read_cache()` directly from the module.
- **Affected:** `/Users/lap14806/all-projects/Writ/bin/lib/writ-session.py` (CLI subcommand surface).
- **Root cause (suspected):** there is no `get` subcommand that prints the raw cache JSON (or it prints a human-formatted, non-JSON view). No documented way to dump `review_ordering_state`/phase for a session as machine-readable JSON.
- **Fix (already resolved, verified 2026-06-23):** `writ-session.py` `main()` aliases `get` → `read` (`if cmd in ("read", "get")`, line ~1996), and `cmd_read` does `json.dump(cache, sys.stdout)` — raw machine-readable JSON. Verified: `writ-session.py get <sid>` round-trips through `json.load` ("VALID JSON"). Present in the plugin cache too. (Note `get`/`read` print the FULL cache; pipe to `python -c 'import json,sys; print(json.load(sys.stdin)["review_ordering_state"])'` to slice.) No new code needed for B16.

### B17 — Hook daemon launch never session-detached on macOS → every auto-start reaped (mkt_engine ~12min+ outage)
- **Severity:** high (a fresh repo's daemon never persists from hooks on macOS).
- **Symptom:** mkt_engine reported "writ NOT online." `<repo>/.writ/redis.log` shows redis `Received SIGTERM` ~0.2–1s after EVERY start, 6× over 12 min (20:50→21:02), each followed by a fresh start that is also reaped. graph.db healthy (seeded 245KB), no graph.lock, socket dir empty — state recoverable; only the daemon won't stay up. falkor-writ's own daemon (9041) was alive only because nothing was respawning it.
- **Root cause:** the three hook launch sites (`writ-rag-inject.sh`, `session-start-bootstrap.sh`, `bin/writ-project-rules.sh:start_daemon`) used `nohup … </dev/null & disown`. That detaches job control but does **NOT** start a new session — the daemon stays in the hook's process session, so Claude's process-tree SIGTERM (#43123) still reaches it. The B4 fix (`</dev/null`+disown) was necessary but **insufficient on macOS**, which has no `setsid` to fix it from shell. So bare nohup never produced a persistent daemon.
- **Fix (2026-06-23):** new `writ_spawn_daemon_detached <py> <port> <log> <repo>` in `bin/lib/common.sh` — a portable python double-fork + `os.setsid()` (works macOS+Linux) that yields a **PPID=1, TTY-less** daemon Claude cannot reap; chdirs to the repo (per-repo graph) and redirects fds to the log. All three launch sites now call it. **Also hardened bind 0.0.0.0 → 127.0.0.1** (was LAN-exposed, no auth; all clients use localhost). Verified: relaunch via the helper → `PPID=1`, stdin `/dev/null`, `127.0.0.1:8804`, healthy 278 rules. Synced to the plugin cache; **restart Claude to reload hooks**.
- **Note:** the running daemon was first brought online by a manual `os.setsid` double-fork (same technique) before the hook fix landed, so mkt_engine was online during the fix.

### Re-observed this session — already logged above, but the fix was NOT effective in the running plugin cache

These reproduced during the build even though their fixes are recorded above as applied
**in the repo** (2026-06-23). Per the "Recurring fix checklist," repo edits do not take
effect until copied into `~/.claude/plugins/cache/writ/writ/<ver>/` AND Claude restarts —
so the actionable item is **verify the cache is synced**, not re-fix.

| Re-observed symptom (this session) | Already logged as | Note |
|---|---|---|
| `--set-plan-reviewed default` "succeeded" yet `writ-sdd-review-order` kept denying the code-quality reviewer; only recording on BOTH live SIDs unblocked it | **B12** (global `/tmp/writ-current-session` clobber; bare-`python3` setter no-op) | fix in repo; cache appears stale — gate still read a different SID than the writer |
| Phase advanced `planning→testing`, later read back `planning`; SID rotated `1a5e5f50`↔`5d7dd4b5` | **B12** (`_mode_set` reset + per-repo pointer) | re-occurred; verify cache sync + restart |
| Gate `task_id` always `default`; no per-task ordering; had to hand-reset `review_ordering_state.default.plan_reviewer_completed=false` between phases | **B12** bullet (`task_id` collapses to `default`; `--reset-plan-reviewed` added) | `--reset-plan-reviewed` was NOT available in the cache this session (had to patch state via raw `_read_cache`/`_write_cache`) |
| redis/daemon SIGTERM + restart mid-session, correlated with the phase/SID reset | **B4 / B9** (hook-reaped daemon, stale socket) | daemon lifecycle churn under Claude hooks |
| Session-start hook injected `[Writ: server unavailable, proceeding without rules]` while the daemon was reachable seconds later | **B5 / B9** (false online/offline) | status line lagged real daemon state |

**Bottom line for the next AI:** the highest-leverage action is to **sync the B12 fixes into the
running plugin cache and restart Claude** (per the Recurring fix checklist) — that should clear
the re-observed gate-deny / phase-reset / SID-mismatch class. B13–B16 are new and still need fixes.

### B18 — `writ-project-rules.sh seed` broken (hardcoded skill-dir venv) → silent project-constraint dropout (graph drift) — ✅ FIXED 2026-06-24
- **Severity:** high. The constraint preload (`writ-project-rules.sh list`) silently returned an INCOMPLETE rule set, and the documented recovery path (`seed`, re-seed-survival D4-04) could not run. Build-pipeline subagents would be dispatched with missing guardrails and nobody would notice — `list` succeeds, it just under-reports.
- **Symptom A (graph drift):** `writ-project-rules.sh list` returned only **1** rule (`PROJ-ARCH-001`) while `docs/rules/` held all **3** committed (`PROJ-ARCH-001`, `PROJ-RESEARCH-001`, `PROJ-DOCSYNC-001`). The graph DB lost 2 of 3 committed PROJ- rules (mkt_engine `.writ/graph.db`, 255KB, 2026-06-24). No error — `list` just returned the short set.
- **Symptom B (recovery broken):** `writ-project-rules.sh seed` (the intended fix for A) fails:
  ```
  writ: venv python not found at /Users/lap14806/all-projects/Writ/.venv/bin/python3
  writ: run scripts/bootstrap.sh from the writ skill directory first
  ```
- **Root cause:** `do_seed()` (`bin/writ-project-rules.sh:72-78`) shells out to the `writ` console entry (`writ import-markdown "$RULES_DIR" --only Rule`). The `writ` shim (`bin/writ:26`) hardcodes `VENV_PY="$SKILL_DIR/.venv/bin/python3"` and `exec`s it (`bin/writ:34`) — it does **NOT** use common.sh's `_writ_resolve_python` (`bin/lib/common.sh:12-35`), which probes BOTH `$CLAUDE_PLUGIN_DATA/.venv` and `$HOME/.cache/writ/.venv`. On this machine only `~/.cache/writ/.venv` is bootstrapped; `Writ/.venv` does not exist. So `list`/`author`/`export` work (they route through `$WRIT_PYTHON` → `bin/lib/project_rules.py`) but `seed` dies (it bypasses that resolver via the `writ` shim). The asymmetry is the bug: two python-resolution paths, only one survives a cache-venv-only install. *Why the graph drifted in the first place is secondary and likely a graph.db rebuild/reset without a working re-seed — exactly the D4-04 case `seed` exists to cover, itself broken.*
- **Workaround applied this session (NOT the fix):** invoked the import directly through the WORKING cache-venv console, bypassing the broken shim — `do_seed`'s intent via the correct interpreter:
  ```
  /Users/lap14806/.cache/writ/.venv/bin/writ import-markdown docs/rules --only Rule
  ```
  → `Imported nodes by type: Rule: 3`. Idempotent MERGE; no `graph.lock` present so no daemon pause needed. `writ-project-rules.sh list` now returns all 3. Graph restored for mkt_engine, but the `seed` command is still broken for everyone.
- **Fix (2026-06-24):** three edits + cache sync. **(1) P1 — `do_seed` (`bin/writ-project-rules.sh:72`)** now runs the import through the resolved `"$WRIT_PYTHON" -m writ.cli import-markdown` (common.sh is already sourced) instead of the bare `writ` shim, so `seed` no longer depends on a skill-dir `.venv`. **(2) `bin/writ` shim (`bin/writ:24`)** hardened: replaced the single hardcoded `$SKILL_DIR/.venv/bin/python3` with a dual-location probe (`$CLAUDE_PLUGIN_DATA/.venv` → `~/.cache/writ/.venv` → `$SKILL_DIR/.venv`), mirroring `_writ_resolve_python`. Works on a cache-venv-only install and survives a Writ folder move/rename. **(3) P2 — drift detection (`.claude/hooks/writ-seed-project-rules.sh`)**: the SessionStart re-seed previously fired ONLY when the graph was EMPTY (`COUNT > 0 → exit`), so newly-pulled rules added to a NON-empty graph never seeded (the originally-reported symptom: close machine → author rules elsewhere → pull → graph not updated). Now compares graph PROJ-count against the committed rule count (`grep -rho 'RULE START:' docs/rules | wc -l`) and re-seeds on `COUNT < EXPECTED` (covers both clobber AND incremental pull). **Verified live (2026-06-24):** `bin/writ` shim resolves the cache venv (was fatal); `seed` against mkt_engine → `Imported nodes by type: Rule: 3`, exit 0; real hook in 3==3 state exits 0 with no churn; drift branch table `3≥3 SKIP / 2<3 SEED / 0<3 SEED` correct. **Bonus path-portability:** `scripts/uninstall-plugin.sh:205` hardcoded `/Users/phatchenh/01_all_projects/falkor-writ` → `$(cd "$(dirname "$0")/.." && pwd)`. All four synced to `~/.claude/plugins/cache/writ/writ/1.5.0/` and re-verified in the cache. **Restart Claude Code so sessions reload the hooks.** Still-open follow-up: 5 stale `*.bak.<ts>` files are git-tracked (`.claude-plugin/plugin.json.bak.*`, `.claude/hooks/writ-rag-inject.sh.bak.*`, `.claude/settings.json.bak.*`, `bin/lib/common.sh.bak.*`, `hooks/scripts/session-start-bootstrap.sh.bak.*`) and still carry old `/Users/phatchenh/...` paths — inert (nothing loads them) but worth deleting in a cleanup pass.

## Recurring fix checklist (when you change any hook/script)

1. Edit the file in the **repo**.
2. `bash -n <file>` (and `ruff`/`mypy` if `.py`).
3. **Sync to the cache** Claude runs:
   `cp <repo>/<path> ~/.claude/plugins/cache/writ/writ/<ver>/<path>` —
   OR reinstall the plugin to re-copy everything. **Also sync `.claude-plugin/plugin.json`** when you add/move agents/commands/hooks paths.
4. **Restart Claude Code** so sessions reload hooks.
5. Verify against the **cache** copy, not the repo (`grep` the cache file).

## Known-good live state (2026-06-23)
- falkor-writ daemon on **9041**, mkt_engine on **8804**, Iris on **9032** — all healthy,
  ~276–277 rules each, `PPID=1`, stdin `/dev/null`.
- All fixes above are applied in the repo AND synced to the plugin cache.
- Everything uncommitted on `main` (per owner: "main is fine").
