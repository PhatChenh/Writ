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

## Recurring fix checklist (when you change any hook/script)

1. Edit the file in the **repo**.
2. `bash -n <file>` (and `ruff`/`mypy` if `.py`).
3. **Sync to the cache** Claude runs:
   `cp <repo>/<path> ~/.claude/plugins/cache/writ/writ/<ver>/<path>` —
   OR reinstall the plugin to re-copy everything.
4. **Restart Claude Code** so sessions reload hooks.
5. Verify against the **cache** copy, not the repo (`grep` the cache file).

## Known-good live state (2026-06-23)
- falkor-writ daemon on **9041**, mkt_engine on **8804**, Iris on **9032** — all healthy,
  ~276–277 rules each, `PPID=1`, stdin `/dev/null`.
- All fixes above are applied in the repo AND synced to the plugin cache.
- Everything uncommitted on `main` (per owner: "main is fine").
