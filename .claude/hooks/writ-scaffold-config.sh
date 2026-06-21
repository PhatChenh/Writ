#!/usr/bin/env bash
# SessionStart: auto-create a per-repo .claude/writ.json when the repo's layout
# isn't a built-in default (e.g. a flat Python package like writ/ rather than
# src/). So the test-discipline hooks (mark/run-pending) recognize the layout
# without manual setup. Conservative + silent + graceful -- never blocks.
#
# The committed writ.json travels with the repo (machine-independent, relative
# paths only), so this only ever fires the first time a repo has none.
set -u
HOOK_DIR="$(cd "$(dirname "$0")" && pwd)"
WRIT_DIR="$(cd "$HOOK_DIR/../.." && pwd)"

# Resolve the user's repo root: prefer the session cwd from the hook envelope,
# fall back to PWD. SessionStart provides cwd in its stdin JSON.
PARSED="$(cat 2>/dev/null)"
CWD="$(printf '%s' "$PARSED" | python3 -c "import sys,json
try: print((json.load(sys.stdin) or {}).get('cwd',''))
except Exception: print('')" 2>/dev/null)"
[ -z "$CWD" ] && CWD="$PWD"

REPO="$(cd "$CWD" 2>/dev/null && git rev-parse --show-toplevel 2>/dev/null)"
[ -z "$REPO" ] && exit 0

python3 "$WRIT_DIR/bin/lib/scaffold_writ_json.py" "$REPO" 2>/dev/null || true
exit 0
