#!/bin/bash
# Handoff markdown validation -- PostToolUse (advisory: exit 1 = warn, never blocks).
#
# Fires after a write to the configured handoff dir (default
# .claude/handoffs/*.md; resolved by bin/lib/artifact_paths.py + optional
# .claude/writ.json). Checks our markdown /handoff doc carries its required
# sections and has no unresolved "I cannot verify" claims. Advisory only --
# surfaces gaps for the agent without blocking the write.
set -euo pipefail
HOOK_DIR="$(cd "$(dirname "$0")" && pwd)"
WRIT_DIR="$(cd "$HOOK_DIR/../.." && pwd)"
source "$WRIT_DIR/bin/lib/common.sh"

PARSED=$(parse_hook_stdin)
FILE=$(parsed_field "$PARSED" "file_path")
[ -z "$FILE" ] && exit 0

# Skip if the write itself failed.
parsed_bool "$PARSED" "is_error" && exit 0

# Only validate handoff docs (config-driven path; default .claude/handoffs/*.md).
ART=$(python3 "$WRIT_DIR/bin/lib/artifact_paths.py" classify "$FILE" 2>/dev/null)
[ "$ART" = "handoff" ] || exit 0
[ -f "$FILE" ] || exit 0

WARN=$(python3 - "$FILE" <<'PY'
import re, sys
try:
    content = open(sys.argv[1], encoding="utf-8").read()
except OSError:
    sys.exit(0)
REQUIRED = ["## Goal", "## Read First", "## State", "## Next Steps", "## Open Items", "## Files Touched", "## Suggested Skills"]
pattern = re.compile(r"^## (.+)$", re.MULTILINE)
matches = list(pattern.finditer(content))
sections = {}
for i, m in enumerate(matches):
    name = "## " + m.group(1).strip()
    start = m.end()
    end = matches[i + 1].start() if i + 1 < len(matches) else len(content)
    sections[name] = content[start:end]
errors = []
for s in REQUIRED:
    if s not in sections:
        errors.append(f"missing section '{s}'")
    elif len(sections[s].split()) < 3:
        errors.append(f"{s}: effectively empty")
if "I cannot verify" in content:
    errors.append("contains unresolved 'I cannot verify' -- verify it, get human sign-off, or remove the claim")
if errors:
    print("validate-handoff: " + "; ".join(errors))
PY
)

if [ -n "$WARN" ]; then
    echo "$WARN" >&2
    exit 1
fi
exit 0
