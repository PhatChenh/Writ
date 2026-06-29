#!/usr/bin/env bash
# Phase 2: enforce verification-before-completion (ENF-PROC-VERIFY-001).
#
# PreToolUse on TodoWrite + Stop.
# Deny completion claims without fresh verification evidence recorded via
# POST /session/{sid}/verification-evidence. Feature-flag gated.
set -euo pipefail
HOOK_DIR="$(cd "$(dirname "$0")" && pwd)"
WRIT_DIR="$(cd "$HOOK_DIR/../.." && pwd)"
SESSION_HELPER="$WRIT_DIR/bin/lib/writ-session.py"
source "$WRIT_DIR/bin/lib/common.sh"

PARSED=$(parse_hook_stdin)
SESSION_ID=$(detect_session_id "$PARSED")
[ -z "$SESSION_ID" ] && exit 0

is_work_mode "$SESSION_ID" || exit 0

TOOL=$(parsed_field "$PARSED" "tool_name")

# Only evaluate on TodoWrite marking a todo completed, or on Stop events.
# For TodoWrite: parse the tool_input.todos and check if any NEW transition to
# "completed" lacks verification_evidence. B26: a completed item that was
# already completed in the prior snapshot (re-sent after a reword) is NOT
# re-gated -- evidence is carried forward by list position. The snapshot is
# persisted only on allow, so a denied TodoWrite re-evaluates against the same
# prior state next time.
DENY_REASON=""
if [ "$TOOL" = "TodoWrite" ]; then
    DENY_REASON=$(python3 <<PY
import json, sys
sys.path.insert(0, "$WRIT_DIR/bin/lib")
from importlib import util
spec = util.spec_from_file_location('writ_session', "$SESSION_HELPER")
mod = util.module_from_spec(spec); spec.loader.exec_module(mod)
session = mod._read_cache("$SESSION_ID")
evidence = dict(session.get("verification_evidence") or {})
judgments = session.get("quality_judgment_state") or {}
prior_todos = session.get("last_todos") or []
parsed = json.loads('''$PARSED''')
tool_input = parsed.get("tool_input") or {}
todos = tool_input.get("todos") or []

deny = ""
carried = False
for i, t in enumerate(todos):
    tid = t.get("id") or t.get("content", "")[:40]
    status = t.get("status") or ""
    if status != "completed":
        continue
    # Check 1: verification_evidence required (ENF-PROC-VERIFY-001).
    if tid not in evidence:
        # B26: was this same list position already completed+verified in the
        # prior snapshot? A reword changes content[:40] -> new key -> not in
        # evidence, but the item is the SAME work, just reworded. Carry the
        # prior position's evidence forward so a re-sent completed item is not
        # re-gated. Tradeoff (documented): a shift+similar at the same index
        # can false-allow; the gate is ergonomics, leans toward allow.
        prior = prior_todos[i] if i < len(prior_todos) else None
        if (prior and prior.get("status") == "completed"
                and prior.get("key") in evidence):
            evidence[tid] = dict(evidence[prior["key"]])
            carried = True
        else:
            deny = f"ENF-PROC-VERIFY-001: completion claim for '{tid}' has no verification_evidence. Run the check, then POST /session/{{sid}}/verification-evidence before marking completed."
            break
    # Check 2: any artifact with a Gate 5 quality judgment below 3 blocks
    # completion unless explicitly overridden (hook-directive self-review;
    # the judge POSTs its score to /session/{sid}/quality-judgment).
    failing_artifacts = [
        path for path, j in judgments.items()
        if isinstance(j, dict) and j.get("score", 5) < 3 and not j.get("overridden")
    ]
    if failing_artifacts:
        deny = f"Gate 5 Tier 2: cannot mark '{tid}' completed while the following artifacts have quality scores below 3 (fix or override): {failing_artifacts}"
        break

# Persist the snapshot only on allow (no deny). Carry-forward evidence writes
# back so future re-sends of the reworded item match by key directly.
if not deny:
    session["verification_evidence"] = evidence
    session["last_todos"] = [
        {"key": (t.get("id") or t.get("content", "")[:40]),
         "status": t.get("status") or ""}
        for t in todos
    ]
    mod._write_cache("$SESSION_ID", session)
    if carried:
        sys.stderr.write("[writ-verify-before-claim] carried evidence forward for reworded completed todo(s)\n")

print(deny)
PY
    )
fi

if [ -n "$DENY_REASON" ]; then
    python3 -c "
import json
print(json.dumps({
    'hookSpecificOutput': {
        'hookEventName': 'PreToolUse',
        'permissionDecision': 'deny',
        'permissionDecisionReason': '''$DENY_REASON'''
    }
}))"
fi
exit 0
