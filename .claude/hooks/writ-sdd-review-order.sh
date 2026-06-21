#!/usr/bin/env bash
# Phase 2: enforce plan-review-before-code-quality-review (ENF-PROC-SDD-001).
#
# PreToolUse on Task when the dispatched subagent is a code-quality reviewer.
# Denies dispatch if writ-plan-reviewer for the current task hasn't completed
# (recorded via `writ-session.py update <sid> --set-plan-reviewed <task>`).
# Work-mode gated. ("spec"->"plan" rename: our implementer's contract doc is
# the plan at docs/AI_artifacts/4_plans/, not a separate spec. #5 review flow.)
set -euo pipefail

# Phase 4c: capture stderr (Python tracebacks etc.) to debug log so
# next-occurrence diagnostics are readable. tee preserves stderr
# propagation so behavior is unchanged.
exec 2> >(tee -a /tmp/writ-hook-debug.log >&2)
HOOK_DIR="$(cd "$(dirname "$0")" && pwd)"
WRIT_DIR="$(cd "$HOOK_DIR/../.." && pwd)"
SESSION_HELPER="$WRIT_DIR/bin/lib/writ-session.py"
source "$WRIT_DIR/bin/lib/common.sh"

PARSED=$(parse_hook_stdin)
SESSION_ID=$(detect_session_id "$PARSED")
[ -z "$SESSION_ID" ] && exit 0

is_work_mode "$SESSION_ID" || exit 0

# Pass $PARSED to Python via env var rather than heredoc substitution.
# Heredoc substitution preserves raw control characters (newlines/tabs
# embedded in tool_input fields), which Python's triple-quoted string
# accepts but json.loads rejects -- causing the SDD review-order gate
# to fall open silently with a non-blocking traceback. PSR-008 surfaced
# this on every subagent dispatch. Same bug class as commit db58ec1.
DENY=$(WRIT_PARSED_ENVELOPE="$PARSED" python3 <<PY
import json, os, sys
sys.path.insert(0, "$WRIT_DIR/bin/lib")
from importlib import util
spec = util.spec_from_file_location('writ_session', "$SESSION_HELPER")
mod = util.module_from_spec(spec); spec.loader.exec_module(mod)
raw = os.environ.get("WRIT_PARSED_ENVELOPE", "")
try:
    parsed = json.loads(raw)
except (json.JSONDecodeError, ValueError) as _e:
    sys.stderr.write(
        f'[writ-hook json.loads recovery] WRIT_PARSED_ENVELOPE in writ-sdd-review-order.sh: {_e}\\n'
        f'  len={len(raw)} sample={raw[:200]!r}\\n'
    )
    sys.exit(0)
ti = parsed.get("tool_input") or {}
agent_type = (ti.get("subagent_type") or "").lower()
# Match our code-quality reviewer (writ-code-quality-reviewer) plus any generic
# code-review subagent. Note "code-review" does NOT substring-match
# "code-quality-reviewer", so both tokens are checked.
if "code-quality" not in agent_type and "code-review" not in agent_type:
    sys.exit(0)
session = mod._read_cache("$SESSION_ID")
state = session.get("review_ordering_state") or {}
# Default task key if not specified: use the current active task id or 'default'
task_id = ti.get("task_id") or session.get("active_phase") or "default"
if not state.get(task_id, {}).get("plan_reviewer_completed", False):
    print(f"ENF-PROC-SDD-001: code-quality review dispatched before plan-compliance review completed for task '{task_id}'. Dispatch writ-plan-reviewer first, then record it: bin/lib/writ-session.py update <sid> --set-plan-reviewed '{task_id}'. Then dispatch writ-code-quality-reviewer.")
PY
)

if [ -n "$DENY" ]; then
    # Same env-var pattern as above: avoid heredoc substitution that
    # breaks on quotes/specials in $DENY.
    WRIT_DENY_REASON="$DENY" python3 -c "
import json, os
print(json.dumps({
    'hookSpecificOutput': {
        'hookEventName': 'PreToolUse',
        'permissionDecision': 'deny',
        'permissionDecisionReason': os.environ.get('WRIT_DENY_REASON', ''),
    }
}))"
fi
exit 0
