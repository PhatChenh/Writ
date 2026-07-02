#!/usr/bin/env bash
# Workflow-stage artifact quality gate (workflow adaptation, 2026-07-02).
#
# PreToolUse on Write to a pre-build stage artifact, classified by
# bin/lib/artifact_paths.py:
#   architecture   -> /architecture-exploration output (architecture.md)
#   project_design -> /init-project design spec (docs/roadmap/project-design.md)
#   roadmap        -> /init-project roadmap (docs/roadmap/roadmap.md)
#   contracts      -> /architecture-grill freeze doc (docs/roadmap/skeleton-contracts.md)
#
# Denies when the doc is missing its stage's required sections or contains
# placeholder text. Sibling of validate-design-doc.sh (which owns the
# build-pipeline 1_design docs); like it, this fires in ANY mode -- these
# artifacts are written in conversation mode, before Work is ever armed.
# Fires on Write only: later phase-status touch-ups arrive as Edit and pass.
set -euo pipefail
HOOK_DIR="$(cd "$(dirname "$0")" && pwd)"
WRIT_DIR="$(cd "$HOOK_DIR/../.." && pwd)"
source "$WRIT_DIR/bin/lib/common.sh"

PARSED=$(parse_hook_stdin)
SESSION_ID=$(detect_session_id "$PARSED")
[ -z "$SESSION_ID" ] && exit 0

FILE=$(parsed_field "$PARSED" "file_path")
[ -z "$FILE" ] && exit 0
ART=$(python3 "$WRIT_DIR/bin/lib/artifact_paths.py" classify "$FILE" 2>/dev/null)
case "$ART" in
    architecture|project_design|roadmap|contracts) ;;
    *) exit 0 ;;
esac

CONTENT=$(echo "$PARSED" | python3 -c "import sys,json; print((json.load(sys.stdin).get('tool_input') or {}).get('content',''))")
[ -z "$CONTENT" ] && exit 0

DENY=$(SD_CONTENT="$CONTENT" SD_TYPE="$ART" python3 <<'PY'
import re, os
content = os.environ["SD_CONTENT"]
art = os.environ["SD_TYPE"]

def has_heading(kw):
    return re.search(r"^#{1,4} .*" + re.escape(kw), content, re.MULTILINE | re.IGNORECASE) is not None

errors = []

# Placeholder blocklist. Deliberately excludes TODO/TBD: roadmap + contracts
# legitimately track deferred work; only true template stubs are blocked.
for bl in ["fill in", "<describe>", "<your text>", "placeholder"]:
    if bl.lower() in content.lower():
        errors.append(f"contains placeholder text '{bl}'")
        break

if art == "architecture":
    # architecture-exploration Phase 4 output: Overview + block sections with
    # per-module concerns tables (each names Dependencies + a build Phase).
    if not has_heading("Overview"):
        errors.append("missing 'Overview' section")
    if len(re.findall(r"^## ", content, re.MULTILINE)) < 3:
        errors.append("needs at least 3 '## ' sections (overview + architectural blocks)")
    if "dependencies" not in content.lower():
        errors.append("no module concerns found (each module needs a Dependencies row)")
elif art == "project_design":
    # init-project Artifact 1 template.
    for kw in ["Overview", "Stack", "Features", "Out of Scope"]:
        if not has_heading(kw):
            errors.append(f"missing '{kw}' section")
elif art == "roadmap":
    # init-project Artifact 2 template.
    for kw in ["Project Context", "Feature Inventory", "Build Order"]:
        if not has_heading(kw):
            errors.append(f"missing '{kw}' section")
    if not re.search(r"^### Phase ", content, re.MULTILINE):
        errors.append("no '### Phase N' entries under Build Order")
elif art == "contracts":
    # architecture-grill output: one '## Block N' per frozen contract, each
    # with pinned Decisions and an explicit frozen-vs-deferred split.
    if not re.search(r"^## Block ", content, re.MULTILINE):
        errors.append("no '## Block N' frozen-contract sections")
    if not has_heading("Decisions"):
        errors.append("blocks need a 'Decisions' subsection (the pinned contract)")
    if not re.search(r"deferred|PENDING", content, re.IGNORECASE):
        errors.append("no frozen-now-vs-deferred/PENDING split (later phases must know what they may still fill)")

if errors:
    print(f"validate-stage-doc ({art}): " + "; ".join(errors))
PY
)

if [ -n "$DENY" ]; then
    DENY_MSG="$DENY" python3 -c "
import json, os
print(json.dumps({
    'hookSpecificOutput': {
        'hookEventName': 'PreToolUse',
        'permissionDecision': 'deny',
        'permissionDecisionReason': os.environ['DENY_MSG']
    }
}))"
fi
exit 0
