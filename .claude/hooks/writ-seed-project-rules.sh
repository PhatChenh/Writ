#!/usr/bin/env bash
# SessionStart: clobber-survival re-seed (D4-04, adapt-only).
#
# If the repo's committed docs/rules/ holds PROJ- constraints but the per-repo
# graph has lost them (e.g. the documented graph.db clobber incident), re-import
# them so authoring survives. The committed docs/rules/ is the system-of-record;
# the graph is volatile.
#
# Guarded so it is cheap and safe:
#   - no docs/rules/ md      -> nothing to restore, exit
#   - daemon not healthy     -> skip (never cold-spawn redis in SessionStart)
#   - graph already has PROJ- -> nothing lost, exit
#   - else                   -> seed (idempotent MERGE import)
# Silent + non-blocking; never fails the session.
set -u
HOOK_DIR="$(cd "$(dirname "$0")" && pwd)"
WRIT_DIR="$(cd "$HOOK_DIR/../.." && pwd)"

# Resolve the user's repo root from the SessionStart envelope cwd (fall back PWD).
PARSED="$(cat 2>/dev/null)"
CWD="$(printf '%s' "$PARSED" | python3 -c "import sys,json
try: print((json.load(sys.stdin) or {}).get('cwd',''))
except Exception: print('')" 2>/dev/null)"
[ -z "$CWD" ] && CWD="$PWD"
REPO="$(cd "$CWD" 2>/dev/null && git rev-parse --show-toplevel 2>/dev/null)"
[ -z "$REPO" ] && exit 0

RULES_DIR="$REPO/docs/rules"
[ -d "$RULES_DIR" ] || exit 0
[ -n "$(find "$RULES_DIR" -name '*.md' -print -quit 2>/dev/null)" ] || exit 0

# Per-repo port + $WRIT_PYTHON wrapper. Preset WRIT_REPO_ROOT so common.sh keys
# the port on THIS repo regardless of the hook's PWD.
export WRIT_REPO_ROOT="$REPO"
source "$WRIT_DIR/bin/lib/common.sh"

# Act ONLY when the daemon is DOWN. The clobber case we guard against (graph.db
# wiped, committed docs/rules intact) happens with the daemon down; a direct
# list/seed is then cheap (no daemon bounce). If the daemon is already UP, the
# graph is live/not-clobbered -> nothing to restore -> skip (avoid a pointless
# stop+restart of a healthy daemon at session start).
if curl -fsS --max-time 1 "http://${WRIT_SESSION_HOST:-localhost}:${WRIT_PORT}/health" >/dev/null 2>&1; then
    exit 0
fi

# Daemon down: a direct list is cheap. Compare what the graph carries against
# what is committed and re-seed on DRIFT (graph has fewer than committed), not
# only when the graph is empty. This covers two cases with one idempotent MERGE:
#   - clobber  -> graph wiped (count 0) vs committed constraints intact
#   - new pull -> committed rules added on another machine, pulled here, but the
#                 graph still holds the old (smaller) set (B18 symptom A: graph 1,
#                 docs/rules 3). The empty-only guard missed this entirely.
# Expected = number of committed rules; each is wrapped in a "RULE START" marker.
EXPECTED="$(grep -rho 'RULE START:' "$RULES_DIR" 2>/dev/null | wc -l | tr -d ' ')"
COUNT="$(bash "$WRIT_DIR/bin/writ-project-rules.sh" list --json 2>/dev/null | python3 -c "import sys,json
try: print(len(json.load(sys.stdin)))
except Exception: print(0)" 2>/dev/null || echo 0)"

# Graph carries every committed constraint -> nothing lost, nothing to restore.
[ "${EXPECTED:-0}" -gt 0 ] && [ "${COUNT:-0}" -ge "${EXPECTED:-0}" ] && exit 0

# Drift (clobber or newly-pulled rules) -> restore via idempotent MERGE import.
bash "$WRIT_DIR/bin/writ-project-rules.sh" seed >/dev/null 2>&1 || true
exit 0
