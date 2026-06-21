#!/usr/bin/env bash
# Phase 2: Gate 5 Tier 1 design-doc quality gate (plan Section 15.3).
#
# PreToolUse on Write to a design-doc artifact (path classified by
# bin/lib/artifact_paths.py; default docs/AI_artifacts/1_design/).
# Denies if the design doc is missing any required subsection, any subsection
# is under the word-count floor, or blocklist placeholders are present.
#
# D4-03 #4 (decoupled from Work mode, 2026-06-21): this is a pure
# path+content format validator with no teeth on code, so it fires in ANY
# mode (conversation/debug/review/work) whenever a Writ session is active.
# Rationale: build-pipeline writes design docs via a SUBAGENT in the design
# step, which runs BEFORE Work mode is armed (Work is armed only at the plan
# transition). Gating this on Work mode meant pipeline design docs were never
# validated. Decoupling (vs arming Work at the design step) keeps the rest of
# the Work-mode blocker suite off during design/spec. The session guard below
# keeps it quiet in Writ-less contexts. See WRIT-LOCAL-ADAPTATION.md #4.
set -euo pipefail
HOOK_DIR="$(cd "$(dirname "$0")" && pwd)"
WRIT_DIR="$(cd "$HOOK_DIR/../.." && pwd)"
source "$WRIT_DIR/bin/lib/common.sh"

PARSED=$(parse_hook_stdin)
SESSION_ID=$(detect_session_id "$PARSED")
[ -z "$SESSION_ID" ] && exit 0

FILE=$(parsed_field "$PARSED" "file_path")
[ -z "$FILE" ] && exit 0
# Path knowledge is config-driven (bin/lib/artifact_paths.py + optional
# .claude/writ.json). Default design dir = docs/AI_artifacts/1_design/.
ART=$(python3 "$WRIT_DIR/bin/lib/artifact_paths.py" classify "$FILE" 2>/dev/null)
[ "$ART" = "design" ] || exit 0

CONTENT=$(echo "$PARSED" | python3 -c "import sys,json; print((json.load(sys.stdin).get('tool_input') or {}).get('content',''))")
[ -z "$CONTENT" ] && exit 0

DENY=$(DD_CONTENT="$CONTENT" python3 <<'PY'
import re, os
content = os.environ["DD_CONTENT"]
REQUIRED = ["## Summary", "## Constraints", "## Alternatives Considered", "## Chosen Approach", "## Risks", "## Open Questions"]
# Open Questions may legitimately be short (e.g. "None") -> presence-only, no floor.
FLOOR = ["## Summary", "## Constraints", "## Alternatives Considered", "## Chosen Approach", "## Risks"]
BLOCKLIST = ["TODO", "TBD", "fill in", "appropriate", "similar to above", "as needed", "placeholder", "<describe>", "<your text>"]
errors = []
for section in REQUIRED:
    if section not in content:
        errors.append(f"missing subsection '{section}'")
# Split into sections to measure word counts per subsection.
pattern = re.compile(r"^## (.+)$", re.MULTILINE)
sections = {}
matches = list(pattern.finditer(content))
for i, m in enumerate(matches):
    name = "## " + m.group(1).strip()
    start = m.end()
    end = matches[i + 1].start() if i + 1 < len(matches) else len(content)
    sections[name] = content[start:end]
for section in FLOOR:
    text = sections.get(section, "")
    # Strip code fences for fair word-count.
    cleaned = re.sub(r"```[\s\S]*?```", "", text)
    word_count = len(cleaned.split())
    if word_count < 50:
        errors.append(f"{section}: {word_count} words below 50-word floor")
    for bl in BLOCKLIST:
        if bl.lower() in cleaned.lower():
            errors.append(f"{section}: contains blocklist placeholder '{bl}'")
            break
# Alternatives Considered must name at least 2 alternatives.
alts = sections.get("## Alternatives Considered", "")
alt_list = re.findall(r"^\s*[-*]\s+\S", alts, re.MULTILINE)
if len(alt_list) < 2:
    errors.append("## Alternatives Considered: must name at least 2 alternatives")
# Risks section must name at least 1 risk with mitigation.
risks = sections.get("## Risks", "")
if "mitigation" not in risks.lower():
    errors.append("## Risks: must name at least 1 risk with a mitigation")
if errors:
    print("Gate 5 Tier 1 (validate-design-doc): " + "; ".join(errors))
PY
)

if [ -n "$DENY" ]; then
    python3 -c "
import json
print(json.dumps({
    'hookSpecificOutput': {
        'hookEventName': 'PreToolUse',
        'permissionDecision': 'deny',
        'permissionDecisionReason': '''$DENY'''
    }
}))"
fi
exit 0
