#!/usr/bin/env bash
# Writ mode setter -- D4-03 mode auto-switch (skill-driven, deterministic).
#
# Sets the Writ session mode for the CURRENT session + repo. Modes arm/disarm
# the Work-gated blocking hooks and the plan->test->code gate machine.
#
# Callable from a skill entry step (guarded one-liner, see WRIT-LOCAL-ADAPTATION
# D4-03) OR directly by hand:
#     bin/writ-mode-set.sh work
#
# Resolution (no env vars required from the caller):
#   - per-repo port  : derived in bin/lib/common.sh (D4-02 "A-auto")
#   - session id     : /tmp/writ-current-session, published every user turn by
#                      writ-rag-inject.sh (line ~172)
#
# Exit codes: 0 set+verified | 1 no/empty session id | 2 bad usage
#             3 set but verification mismatch (daemon down?)
set -euo pipefail

# Server-side VALID_MODES (writ/server.py:38, writ-session.py:835) =
# conversation|debug|review|work. "chat" is our shorter user-facing alias for
# conversation -- map it before talking to the server. "prototype" is a
# separate legacy bypass, not settable here.
MODE="${1:-}"
[ "$MODE" = "chat" ] && MODE="conversation"
case "$MODE" in
    conversation|debug|review|work) ;;
    *)
        echo "usage: $(basename "$0") <chat|debug|review|work>" >&2
        exit 2
        ;;
esac

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# Let _writ_session resolve its subprocess fallback helper.
export WRIT_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"
export SESSION_HELPER="$WRIT_DIR/bin/lib/writ-session.py"
# common.sh derives the per-repo WRIT_PORT/WRIT_SESSION_BASE + defines _writ_session.
source "$SCRIPT_DIR/lib/common.sh"

SID_FILE="$WRIT_CURRENT_SESSION_FILE"
if [ ! -f "$SID_FILE" ]; then
    echo "writ-mode-set: no session id at $SID_FILE (has a user turn run yet?)" >&2
    exit 1
fi
SID="$(cat "$SID_FILE")"
if [ -z "$SID" ]; then
    echo "writ-mode-set: empty session id in $SID_FILE" >&2
    exit 1
fi

_writ_session "mode set" "$SID" "$MODE" >/dev/null 2>&1 || true

# Verify the daemon actually applied it (read-back).
ACTUAL="$(_writ_session "mode get" "$SID" 2>/dev/null | tr -d '[:space:]')"
if [ "$ACTUAL" = "$MODE" ]; then
    echo "[Writ: mode set -> $MODE (session ${SID}, port ${WRIT_PORT})]"
    exit 0
fi
echo "[Writ: mode set -> $MODE requested but read-back is '${ACTUAL:-<none>}' (daemon on port ${WRIT_PORT} reachable?)]" >&2
exit 3
