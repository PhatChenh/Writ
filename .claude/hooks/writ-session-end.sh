#!/usr/bin/env bash
# Writ SessionEnd hook -- fires once at session close (1.5s timeout)
#
# Consolidates session-level operations that previously ran on every Stop:
# 1. auto-feedback: correlate rules with analysis outcomes, POST to Writ
# 2. coverage: compute rule coverage report
# 3. gate metrics: write context metrics for recently approved gates (replaces log-session-metrics.sh)
# 4. session_end rollup: log final session totals to friction log
#
# Hook type: SessionEnd
# Exit: always 0

set -euo pipefail

HOOK_DIR="$(cd "$(dirname "$0")" && pwd)"
WRIT_DIR="$(cd "$HOOK_DIR/../.." && pwd)"
SESSION_HELPER="$WRIT_DIR/bin/lib/writ-session.py"
source "$WRIT_DIR/bin/lib/common.sh"

HOOK_START_NS=$(hook_timer_start)

# Session ID: grandparent PID = the claude process
SESSION_ID=$(ps -o ppid= -p $PPID 2>/dev/null | tr -d ' ')
if [ -z "$SESSION_ID" ]; then
    SESSION_ID=$(echo "${PWD}:${USER}" | md5sum | cut -c1-12)-$(date +%Y%m%d)
fi

# 1. Auto-feedback: correlate rules-in-context with analysis outcomes
_writ_session auto-feedback "$SESSION_ID" \
    >> "/tmp/writ-feedback-${SESSION_ID}.log" 2>/dev/null || true

# 2. Coverage report
_writ_session coverage "$SESSION_ID" \
    >> "/tmp/writ-coverage-${SESSION_ID}.log" 2>/dev/null || true

# 3. Gate metrics (replaces log-session-metrics.sh)
PROJECT_ROOT=$(detect_project_root "$(pwd)")
if [ -n "$PROJECT_ROOT" ]; then
    GATE_DIR="$PROJECT_ROOT/.claude/gates"
    METRICS_FILE="$PROJECT_ROOT/.claude/session-metrics.md"
    if [ -d "$GATE_DIR" ]; then
        for gate_file in "$GATE_DIR"/*.approved; do
            [ ! -f "$gate_file" ] && continue
            GATE_NAME=$(basename "$gate_file" .approved)
            TIMESTAMP=$(date -u '+%Y-%m-%dT%H:%M:%SZ')
            mkdir -p "$(dirname "$METRICS_FILE")"
            printf '\n## Gate: %s -- %s\n' \
                "$GATE_NAME" "$TIMESTAMP" \
                >> "$METRICS_FILE" 2>/dev/null || true
        done
    fi
fi

# 4. Session end rollup: log final totals to friction log
CACHE=$(_writ_session read "$SESSION_ID" 2>/dev/null || echo '{}')
python3 -c "
import json, sys, os
from datetime import datetime, timezone

try:
    cache = json.loads(sys.argv[1])
except Exception:
    cache = {}

rules_loaded = len(cache.get('loaded_rule_ids', []))
violations = len(cache.get('pending_violations', []))
files_written = len(cache.get('files_written', []))
queries = cache.get('queries', 0)
mode = cache.get('mode')
phase = cache.get('current_phase')

entry = json.dumps({
    'ts': datetime.now(timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ'),
    'session': sys.argv[2],
    'mode': mode,
    'event': 'session_end',
    'rules_loaded': rules_loaded,
    'total_violations': violations,
    'files_written': files_written,
    'queries': queries,
    'final_phase': phase,
})

markers = ['composer.json','package.json','Cargo.toml','go.mod','pyproject.toml','.git']
path = os.getcwd()
while path != '/':
    if any(os.path.exists(os.path.join(path, m)) for m in markers):
        try:
            with open(os.path.join(path, 'workflow-friction.log'), 'a') as f:
                f.write(entry + '\n')
        except OSError:
            pass
        break
    path = os.path.dirname(path)
" "$CACHE" "$SESSION_ID" 2>/dev/null || true

# 5. Project-rule export safety-net (D4-04): flush graph PROJ- constraints to
# the committed docs/rules/. Primary export is author-time (the guardrail skill
# exports the turn it authors); this catches rules authored via the raw CLI.
# Run ONLY when the daemon is already DOWN -> the export's direct connection is a
# cheap no-bounce op that fits the 1.5s budget. If the daemon is UP, skip: the
# dispatcher would stop+restart it (too slow here, and pointless at session end).
if ! curl -fsS --max-time 1 "http://${WRIT_SESSION_HOST:-localhost}:${WRIT_PORT}/health" >/dev/null 2>&1; then
    bash "$WRIT_DIR/bin/writ-project-rules.sh" export >/dev/null 2>&1 || true
fi

hook_timer_end "$HOOK_START_NS" "writ-session-end" "$SESSION_ID" ""
exit 0
