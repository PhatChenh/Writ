#!/usr/bin/env bash
# SessionStart hook: probes the plugin's runtime prerequisites and starts
# the Writ FastAPI daemon if everything is in place. Graceful-degrades
# in every failure branch (exits 0 so the session is never blocked).
#
# Lives at hooks/scripts/, not .claude/hooks/, so dirname walks resolve
# wrong; uses ${CLAUDE_PLUGIN_ROOT} directly instead.

set -u

# 1. Resolve install root and persistent-data dir. The plugin loader sets
#    CLAUDE_PLUGIN_ROOT; if unset, we're not running under the loader so
#    there's nothing to bootstrap.
if [ -z "${CLAUDE_PLUGIN_ROOT:-}" ]; then
  exit 0
fi
WRIT_DIR="${CLAUDE_PLUGIN_ROOT}"
WRIT_DATA="${CLAUDE_PLUGIN_DATA:-$HOME/.cache/writ}"
# Venv lives at ${CLAUDE_PLUGIN_DATA:-$HOME/.cache/writ}/.venv so it
# survives plugin upgrades that rewrite ${CLAUDE_PLUGIN_ROOT}.
VENV_DIR="${CLAUDE_PLUGIN_DATA:-$HOME/.cache/writ}/.venv"
SERVER_URL="${WRIT_SERVER_URL:-http://localhost:8765}"
SERVER_HEALTH_URL="http://localhost:8765/health"

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


# 3. Probe server health at http://localhost:8765/health. If already
#    running, we're done.
if curl -fsS --max-time 1 "${SERVER_HEALTH_URL}" >/dev/null 2>&1; then
  exit 0
fi

# 4. Start the server in the background. cd into WRIT_DIR so writ.toml is
#    read from the plugin install dir, not the user's cwd.
(
  cd "${WRIT_DIR}" || exit 0
  # shellcheck disable=SC1091
  . "${VENV_DIR}/bin/activate" 2>/dev/null || exit 0
  nohup writ serve >"${WRIT_DATA}/server.log" 2>&1 &
  disown 2>/dev/null || true
) >/dev/null 2>&1 &

# Wait up to 5 seconds for the server to come up.
for _ in 1 2 3 4 5; do
  if curl -fsS --max-time 1 "${SERVER_HEALTH_URL}" >/dev/null 2>&1; then
    break
  fi
  sleep 1
done

exit 0
