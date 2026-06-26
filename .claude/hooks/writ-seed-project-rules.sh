#!/usr/bin/env bash
# SessionStart: clobber-survival re-seed (D4-04, adapt-only).
#
# If the repo's committed docs/rules/ holds PROJ- constraints but the per-repo
# graph has lost them (e.g. the documented graph.db clobber incident), re-import
# them so authoring survives. The committed docs/rules/ is the system-of-record;
# the graph is volatile.
#
# Guarded so it is cheap and safe:
#   - no docs/rules/ md            -> nothing to restore, exit
#   - committed content unchanged
#     AND daemon healthy           -> already in sync, exit (no daemon bounce)
#   - committed content changed    -> re-seed (catches add/EDIT/delete) + record hash
#   - content same but daemon down -> count compare; re-seed only if clobbered/short
# Drift is detected by a content hash of docs/rules (sentinel .writ/.rules-seeded-hash),
# not a rule count -- a count misses in-place edits. Silent + non-blocking.
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

# Primary drift signal = a CONTENT HASH of the committed rule files, recorded in
# a per-repo sentinel after each successful seed. A count compare only catches
# ADDED rules; a content hash also catches an EDITED rule (same rule_id + count,
# changed body) and a DELETED one. No graph read needed, so it works whether the
# daemon is up or down. (B19: a pulled rule EDIT never re-ingested because the
# old guard compared counts, and exited early whenever the daemon was up.)
SENTINEL="$REPO/.writ/.rules-seeded-hash"

# Per-file content hashes, sorted, then re-hashed -> stable under file rename /
# directory-order changes; changes iff some rule file's bytes change. macOS ships
# shasum (perl); fall back to md5.
_rules_hash() {
    if command -v shasum >/dev/null 2>&1; then
        find "$RULES_DIR" -name '*.md' -type f -exec shasum -a 256 {} \; 2>/dev/null \
            | awk '{print $1}' | LC_ALL=C sort | shasum -a 256 | awk '{print $1}'
    else
        find "$RULES_DIR" -name '*.md' -type f -exec md5 -q {} \; 2>/dev/null \
            | LC_ALL=C sort | md5 -q 2>/dev/null
    fi
}

CUR_HASH="$(_rules_hash)"
OLD_HASH="$(cat "$SENTINEL" 2>/dev/null || true)"

# Re-seed (idempotent MERGE import; pauses + re-warms a live daemon itself), then
# record the hash we just seeded so the next session sees "in sync".
_reseed() {
    if bash "$WRIT_DIR/bin/writ-project-rules.sh" seed >/dev/null 2>&1; then
        printf '%s' "$CUR_HASH" > "$SENTINEL" 2>/dev/null || true
    fi
}

# (1) Committed rules changed since the last seed (add / edit / delete), or first
#     run (no sentinel) -> re-seed regardless of daemon state.
if [ "$CUR_HASH" != "$OLD_HASH" ]; then
    _reseed
    exit 0
fi

# (2) Content unchanged + daemon healthy -> it is already serving the correct
#     set; skip (do NOT bounce a healthy daemon at every session start).
if curl -fsS --max-time 1 "http://${WRIT_SESSION_HOST:-localhost}:${WRIT_PORT}/health" >/dev/null 2>&1; then
    exit 0
fi

# (3) Content unchanged + daemon DOWN -> guard against a clobbered graph (graph.db
#     wiped, committed docs/rules intact). Daemon down => no lock, so a direct
#     count compare is cheap. cd REPO so the CWD-relative .writ/graph.db resolves
#     to THIS repo (get_falkordb_path is CWD-relative, not WRIT_REPO_ROOT-aware).
EXPECTED="$(grep -rho 'RULE START:' "$RULES_DIR" 2>/dev/null | wc -l | tr -d ' ')"
COUNT="$( (cd "$REPO" && bash "$WRIT_DIR/bin/writ-project-rules.sh" list --json 2>/dev/null) | python3 -c "import sys,json
try: print(len(json.load(sys.stdin)))
except Exception: print(0)" 2>/dev/null || echo 0)"

# Graph carries every committed constraint -> nothing lost.
[ "${EXPECTED:-0}" -gt 0 ] && [ "${COUNT:-0}" -ge "${EXPECTED:-0}" ] && exit 0

# Clobbered / short -> restore via idempotent MERGE import.
_reseed
exit 0
