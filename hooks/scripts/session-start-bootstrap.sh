#!/usr/bin/env bash
# SessionStart hook: probes the plugin's runtime prerequisites and starts the
# Writ FastAPI daemon FOR THE CURRENT REPO. Graceful-degrades in every failure
# branch (exits 0 so the session is never blocked).
#
# Per-repo isolation (D4-02 "A-auto"): each repo runs its own daemon on a
# hash-derived port, reading a CWD-relative .writ/graph.db. This hook therefore
# must (a) resolve the repo root, (b) ensure that repo's graph is seeded with
# the bible, and (c) start the daemon on the repo's derived port -- not a single
# global 8765 daemon. common.sh derives the per-repo port + WRIT_PYTHON.
#
# Lives at hooks/scripts/, not .claude/hooks/, so dirname walks resolve wrong;
# uses ${CLAUDE_PLUGIN_ROOT} directly instead.

set -u

# 1. Resolve install root and persistent-data dir. The plugin loader sets
#    CLAUDE_PLUGIN_ROOT; if unset, we're not running under the loader so
#    there's nothing to bootstrap.
if [ -z "${CLAUDE_PLUGIN_ROOT:-}" ]; then
  exit 0
fi
WRIT_DIR="${CLAUDE_PLUGIN_ROOT}"
# The venv may live under $CLAUDE_PLUGIN_DATA OR ~/.cache/writ -- Claude Code
# can move CLAUDE_PLUGIN_DATA between versions while bootstrap-plugin.sh
# installed the venv at ~/.cache/writ/.venv. Trust whichever actually exists;
# otherwise the venv probe below wrongly reports "missing" and the hook exits.
VENV_DIR=""
for _d in "${CLAUDE_PLUGIN_DATA:-}" "$HOME/.cache/writ"; do
  [ -n "$_d" ] && [ -x "$_d/.venv/bin/python3" ] && { VENV_DIR="$_d/.venv"; break; }
done
# Fall back to the documented default path so the "venv missing" message points
# somewhere sensible even when nothing was found.
[ -z "$VENV_DIR" ] && VENV_DIR="${CLAUDE_PLUGIN_DATA:-$HOME/.cache/writ}/.venv"
# Logs + server.log live alongside the resolved venv (a known-writable dir).
WRIT_DATA="$(dirname "$VENV_DIR")"

# 2. Probe venv. If missing, instruct user and exit 0.
if [ ! -x "${VENV_DIR}/bin/python3" ]; then
  cat >&2 <<MSG
[Writ] Plugin venv not bootstrapped at ${VENV_DIR}.
[Writ] Run once:
[Writ]   bash ${WRIT_DIR}/scripts/bootstrap-plugin.sh
[Writ] Writ hooks will degrade gracefully until bootstrap completes.
MSG
  exit 0
fi

# 3. Resolve the user's repo root from the SessionStart envelope cwd (the same
#    pattern the sibling SessionStart hooks use), then derive the per-repo port
#    via common.sh. Presetting WRIT_REPO_ROOT keys the port on THIS repo
#    regardless of the hook's own PWD.
PARSED="$(cat 2>/dev/null)"
CWD="$(printf '%s' "$PARSED" | "${VENV_DIR}/bin/python3" -c "import sys,json
try: print((json.load(sys.stdin) or {}).get('cwd',''))
except Exception: print('')" 2>/dev/null)"
[ -z "$CWD" ] && CWD="$PWD"
REPO="$(cd "$CWD" 2>/dev/null && git rev-parse --show-toplevel 2>/dev/null)"
# Non-git CWD: fall back to the install dir so a single "global" daemon serves
# (mirrors common.sh's own fallback). This keeps non-repo sessions working.
[ -z "$REPO" ] && REPO="$WRIT_DIR"

export WRIT_REPO_ROOT="$REPO"
# shellcheck disable=SC1091
source "${WRIT_DIR}/bin/lib/common.sh" 2>/dev/null || true
# common.sh exports WRIT_PORT (per-repo). Belt-and-suspenders default.
WRIT_PORT="${WRIT_PORT:-8765}"
HEALTH_URL="http://localhost:${WRIT_PORT}/health"

# 4. If this repo's daemon is already healthy, we're done.
if curl -fsS --max-time 1 "${HEALTH_URL}" >/dev/null 2>&1; then
  exit 0
fi

# 5. Ensure the repo's graph is seeded with the bible. The daemon is DOWN here
#    (step 4 failed), so a direct import is safe -- no socket/lock contention
#    with a live daemon. Sentinel-guarded so it runs once per repo; the import
#    itself is idempotent (MERGE) so a stray re-run is harmless.
#
#    Pass an ABSOLUTE bible path: import-markdown only auto-exports the whole
#    graph back to bible/ when the import path == DEFAULT_BIBLE_DIR resolved
#    against CWD. An absolute path makes that equality false, so the canonical
#    bible is never written. The graph itself is written CWD-relative to
#    "$REPO/.writ/graph.db", which is why we cd into the repo first.
SENTINEL="${REPO}/.writ/.bible-seeded"
if [ ! -f "$SENTINEL" ] && [ -d "${WRIT_DIR}/bible" ]; then
  mkdir -p "${REPO}/.writ" 2>/dev/null || true
  if ( cd "${REPO}" && "${VENV_DIR}/bin/writ" import-markdown "${WRIT_DIR}/bible" >/dev/null 2>&1 ); then
    touch "$SENTINEL" 2>/dev/null || true
  fi
fi

# 6. Start the repo's daemon on its derived port. cd into the repo so the
#    CWD-relative graph path resolves to "$REPO/.writ/graph.db".
#
#    RACE GUARD: this hook and writ-rag-inject.sh both fire on session open and
#    each try to start the daemon. Two simultaneous starts collide on db.py's
#    single-writer graph.lock -- the loser dies with "graph DB is locked by PID
#    N", and the winner sometimes dies too, leaving NO daemon. Both paths now
#    coordinate through one per-port start-lock: whoever grabs it starts; the
#    other just waits for /health below.
START_LOCK="/tmp/writ-server-starting-${WRIT_PORT}.lock"
# Steal a stale lock whose owner is gone (crash/SIGKILL left it behind), else a
# dead starter would wedge auto-start for every later session.
if [ -f "$START_LOCK" ]; then
  _owner="$(cat "$START_LOCK" 2>/dev/null)"
  { [ -n "$_owner" ] && kill -0 "$_owner" 2>/dev/null; } || rm -f "$START_LOCK"
fi
if ( set -o noclobber; echo $$ > "$START_LOCK" ) 2>/dev/null; then
  trap 'rm -f "$START_LOCK"' EXIT
  writ_clean_stale_embedded_state "$REPO"

  # Detached in a new session (os.setsid) so Claude's process-tree SIGTERM
  # (#43123) cannot reap it; macOS lacks `setsid`, and bare nohup+disown left
  # the daemon in the hook's session. repo-root CWD keeps .writ/graph.db per-repo.
  writ_spawn_daemon_detached "${VENV_DIR}/bin/python3" "${WRIT_PORT}" "${WRIT_DATA}/server.log" "${REPO}"
fi
# If we did NOT get the lock, another starter (rag-inject) is bringing the daemon
# up -- fall through to the health-wait below without spawning a second daemon.

# Wait up to 5 seconds for the daemon to come up.
for _ in 1 2 3 4 5; do
  if curl -fsS --max-time 1 "${HEALTH_URL}" >/dev/null 2>&1; then
    break
  fi
  sleep 1
done

exit 0
