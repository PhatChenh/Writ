#!/usr/bin/env bash
# Stop: durable-doc sync gate (workflow adaptation, 2026-07-02).
#
# If a pipeline artifact (docs/AI_artifacts/{1_*,2_*,3_*,4_*}) is newer than
# the repo's STATE.md, the stage finished without syncing the durable docs --
# the next session starts stale. Block the stop ONCE per artifact batch with
# a directive to run the update-project-docs targeted sync.
#
# Loop safety: the newest artifact mtime is recorded in a per-session marker
# after the first block; an identical mtime never blocks twice. Touching
# STATE.md clears the condition naturally (mtime comparison).
#
# Quiet exits: no Writ session, no STATE.md at repo root (repo doesn't use
# the convention), no artifacts newer than STATE.md.
set -euo pipefail
HOOK_DIR="$(cd "$(dirname "$0")" && pwd)"
WRIT_DIR="$(cd "$HOOK_DIR/../.." && pwd)"
source "$WRIT_DIR/bin/lib/common.sh"

PARSED=$(parse_hook_stdin)
SESSION_ID=$(detect_session_id "$PARSED")
[ -z "$SESSION_ID" ] && exit 0

REPO="$(git rev-parse --show-toplevel 2>/dev/null)" || exit 0
[ -z "$REPO" ] && exit 0
STATE="$REPO/STATE.md"
[ -f "$STATE" ] || exit 0
ART_DIR="$REPO/docs/AI_artifacts"
[ -d "$ART_DIR" ] || exit 0

# Newest artifact mtime across the output stages (0_draft/0_scout are inputs).
NEWEST=$(find "$ART_DIR" -mindepth 2 -maxdepth 2 -name '*.md' \
    -path "$ART_DIR/[1-9]*" -newer "$STATE" 2>/dev/null \
    -exec stat -f '%m %N' {} \; | sort -rn | head -1)
[ -z "$NEWEST" ] && exit 0

NEWEST_MTIME="${NEWEST%% *}"
NEWEST_FILE="${NEWEST#* }"

# Once-per-batch marker: same newest-mtime never blocks a second stop.
MARKER_DIR="$WRIT_DIR/cache/$SESSION_ID"
mkdir -p "$MARKER_DIR"
MARKER="$MARKER_DIR/doc-sync-nagged"
if [ -f "$MARKER" ] && [ "$(cat "$MARKER" 2>/dev/null)" = "$NEWEST_MTIME" ]; then
    exit 0
fi
printf '%s' "$NEWEST_MTIME" > "$MARKER"

REL="${NEWEST_FILE#"$REPO"/}"
echo "Pipeline artifact '$REL' is newer than STATE.md. Before finishing: run the update-project-docs targeted sync (STATE.md position + any affected durable docs) so the next session picks up full context." >&2
exit 2
