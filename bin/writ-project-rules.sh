#!/usr/bin/env bash
# Project-rule dispatcher (Phase 6 / D4-04, adapt-only).
#
# Thin shell front-end for bin/lib/project_rules.py (author|export|list) plus
# `seed` (import direction, re-seed survival). Sources common.sh so every
# call inherits the per-repo port (D4-02 "A-auto") + the >=3.11 $WRIT_PYTHON
# wrapper, and runs against the CURRENT repo's graph.
#
#   writ-project-rules.sh author --rule-id PROJ-WRITE-001 --domain ... ...
#   writ-project-rules.sh export                 # graph PROJ- -> docs/rules/
#   writ-project-rules.sh list [--json]          # explicit load-all, no ranking
#   writ-project-rules.sh seed                   # docs/rules/ (+bible) -> graph
#
# Exit: passes through the python engine / writ CLI exit code.
set -euo pipefail

HOOK_DIR="$(cd "$(dirname "$0")" && pwd)"
WRIT_DIR="$(cd "$HOOK_DIR/.." && pwd)"
source "$WRIT_DIR/bin/lib/common.sh"

ENGINE="$WRIT_DIR/bin/lib/project_rules.py"
RULES_DIR="${WRIT_REPO_ROOT}/docs/rules"

# --- Daemon management (D4-04) ---------------------------------------------- #
# Every op below opens a DIRECT graph connection, which acquires db.py's
# single-writer lock (graph.lock). A running per-repo daemon (A-auto) holds that
# lock, so a direct op fails ("graph DB is locked -- use the HTTP API"). Since
# the daemon exposes no HTTP endpoint for human-authority authoring / list-all /
# export, we momentarily PAUSE the daemon for the op and restart it after. The
# graph RDB persists across the bounce, so no data is lost; the restarted daemon
# re-warms from disk. Rare for author; the build-pipeline `list` preload pays one
# bounce per phase. Mirrors writ-rag-inject.sh's start command.
WRIT_DATA="${CLAUDE_PLUGIN_DATA:-$HOME/.cache/writ}"
VENV_DIR="$WRIT_DATA/.venv"
HEALTH_URL="http://${WRIT_SESSION_HOST:-localhost}:${WRIT_PORT}/health"

daemon_up() { curl -sf --connect-timeout 0.3 "$HEALTH_URL" >/dev/null 2>&1; }

stop_daemon() {
    WRIT_PORT="$WRIT_PORT" bash "$WRIT_DIR/scripts/stop-server.sh" >/dev/null 2>&1 || true
    # Wait for the lock to actually release (graceful shutdown closes the db).
    for _i in $(seq 1 20); do
        [ -f "${WRIT_REPO_ROOT}/.writ/graph.lock" ] || break
        sleep 0.2
    done
}

start_daemon() {
    [ -x "$VENV_DIR/bin/python3" ] || return 0
    # Detached in a new session (os.setsid): a hook-context caller would otherwise
    # have the daemon reaped by Claude's process-tree SIGTERM (#43123); macOS lacks
    # `setsid`. repo-root CWD keeps .writ/graph.db per-repo.
    writ_spawn_daemon_detached "$VENV_DIR/bin/python3" "$WRIT_PORT" /tmp/writ-server.log "$WRIT_REPO_ROOT"
    for _i in $(seq 1 20); do daemon_up && break; sleep 0.5; done
}

# Run "$@" with the per-repo daemon paused if it was up; restart it after.
with_daemon_paused() {
    local was_up=0 rc=0
    if daemon_up; then was_up=1; stop_daemon; fi
    "$@"; rc=$?
    [ "$was_up" -eq 1 ] && start_daemon
    return $rc
}

# writ.* import path: prefer the installed console entry; fall back to running
# the engine with WRIT_DIR on PYTHONPATH (dev checkout, package not installed).
run_engine() {
    PYTHONPATH="${WRIT_DIR}${PYTHONPATH:+:$PYTHONPATH}" python3 "$ENGINE" --rules-dir "$RULES_DIR" "$@"
}

do_seed() {
    # Re-seed survival (D4-04): import the committed per-repo project rules back
    # into this repo's graph. Idempotent (MERGE). Universal bible is a separate
    # concern seeded at bootstrap; we only restore PROJ- here.
    if [ -d "$RULES_DIR" ] && [ -n "$(find "$RULES_DIR" -name '*.md' -print -quit 2>/dev/null)" ]; then
        (cd "$WRIT_REPO_ROOT" && writ import-markdown "$RULES_DIR" --only Rule)
    else
        echo "writ-project-rules: no $RULES_DIR/**/*.md to seed" >&2
    fi
}

CMD="${1:-}"
case "$CMD" in
    author|export|list)
        with_daemon_paused run_engine "$@"
        ;;
    seed)
        with_daemon_paused do_seed
        ;;
    ""|-h|--help)
        echo "usage: $(basename "$0") <author|export|list|seed> [args]" >&2
        exit 2
        ;;
    *)
        echo "writ-project-rules: unknown subcommand '$CMD'" >&2
        exit 2
        ;;
esac
