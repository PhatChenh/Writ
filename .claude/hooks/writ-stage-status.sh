#!/usr/bin/env bash
# SessionStart: project lifecycle stage status (workflow adaptation, 2026-07-02).
#
# Stateless: derives where the project sits in the workflow chain
#   /architecture-exploration -> /init-project -> /architecture-grill
#   -> per-phase /build-pipeline -> /deepseek-orchestrate
# purely from which stage artifacts exist on disk, and injects ONE context
# line naming the next expected stage. No session cache, no markers.
#
# Quiet exits: not a git repo, or repo shows no sign of the doc workflow
# (no docs/roadmap/ and no docs/AI_artifacts/).
set -u
HOOK_DIR="$(cd "$(dirname "$0")" && pwd)"

# Resolve the user's repo root from the SessionStart envelope cwd (fall back PWD).
PARSED="$(cat 2>/dev/null)"
CWD="$(printf '%s' "$PARSED" | python3 -c "import sys,json
try: print((json.load(sys.stdin) or {}).get('cwd',''))
except Exception: print('')" 2>/dev/null)"
[ -z "$CWD" ] && CWD="$PWD"
REPO="$(cd "$CWD" 2>/dev/null && git rev-parse --show-toplevel 2>/dev/null)"
[ -z "$REPO" ] && exit 0

# Participation guard: only speak in repos that use the doc workflow.
[ -d "$REPO/docs/roadmap" ] || [ -d "$REPO/docs/AI_artifacts" ] || exit 0

_exists_any() {
    local f
    for f in "$@"; do
        [ -f "$REPO/$f" ] && return 0
    done
    return 1
}

EXPLORE="✗"; INIT="✗"; GRILL="✗"
_exists_any "architecture.md" "docs/roadmap/architecture.md" "docs/architecture/architecture.md" && EXPLORE="✓"
[ -f "$REPO/docs/roadmap/project-design.md" ] && [ -f "$REPO/docs/roadmap/roadmap.md" ] && INIT="✓"
[ -f "$REPO/docs/roadmap/skeleton-contracts.md" ] && GRILL="✓"
PLANS=$(find "$REPO/docs/AI_artifacts/4_plans" -maxdepth 1 -name '*.md' 2>/dev/null | wc -l | tr -d ' ')

if [ "$EXPLORE" = "✗" ] && [ "$INIT" = "✗" ]; then
    NEXT="/architecture-exploration"
elif [ "$INIT" = "✗" ]; then
    NEXT="/init-project"
elif [ "$GRILL" = "✗" ]; then
    NEXT="/architecture-grill"
else
    NEXT="per-phase /build-pipeline, then /deepseek-orchestrate to implement"
fi

echo "[Writ stage: exploration $EXPLORE | init-project $INIT | grill $GRILL | pipeline plans: $PLANS — next: $NEXT]"
exit 0
