#!/usr/bin/env bash
# Phase 2: enforce worktree gitignore safety (ENF-PROC-WORKTREE-001).
#
# PreToolUse on Bash matching `git worktree add`. Denies if the target
# path is project-local and not in .gitignore. Feature-flag gated.
set -euo pipefail
HOOK_DIR="$(cd "$(dirname "$0")" && pwd)"
WRIT_DIR="$(cd "$HOOK_DIR/../.." && pwd)"
source "$WRIT_DIR/bin/lib/common.sh"

PARSED=$(parse_hook_stdin)
SESSION_ID=$(detect_session_id "$PARSED")
[ -z "$SESSION_ID" ] && exit 0
is_work_mode "$SESSION_ID" || exit 0

CMD=$(echo "$PARSED" | python3 -c "import sys,json; d=json.load(sys.stdin); print((d.get('tool_input') or {}).get('command',''))" 2>/dev/null)
# Only act on `git worktree add` commands.
case "$CMD" in
    *"git worktree add"*) ;;
    *) exit 0 ;;
esac

DENY=$(WT_CMD="$CMD" python3 <<'PY'
import os, re, subprocess, sys
cmd = os.environ["WT_CMD"]
# Extract the path argument. `git worktree add [opts] <path> [branch]`
m = re.search(r'git\s+worktree\s+add\s+((?:--?\S+\s+)*)(\S+)', cmd)
if not m:
    sys.exit(0)
target = m.group(2)

# B28: the hook reads the RAW command string the agent typed, BEFORE the shell
# expands it. So a target like `"$WT"` arrives literal -- the hook has no access
# to the agent's interactive-shell variables (they are not exported into the
# hook's environment). Expand what IS available (exported vars) from os.environ;
# if a `$var` token survives unresolved we cannot verify the path, so we do NOT
# deny (the guard is an ergonomics safety-net, not a hard security boundary, and
# Work mode is trusted). This stops the false-positive denial of the standard
# variable-driven `WT=...; git worktree add "$WT"` orchestration pattern.
def _expand(tok):
    tok = tok.strip().strip('"').strip("'")
    def repl(mo):
        name = mo.group(2) or mo.group(1)
        return os.environ.get(name, mo.group(0))
    return re.sub(r'\$\{(\w+)\}|\$(\w+)', repl, tok)

target = _expand(target)
if not target or "$" in target:
    # Unresolved variable reference -- cannot evaluate; do not block.
    sys.stderr.write(
        f"[writ-worktree-safety] target '{target or m.group(2)}' contains an "
        f"unresolved shell variable; skipping gitignore check (cannot expand).\n"
    )
    sys.exit(0)

# Absolute paths or paths outside the repo tree are not project-local.
repo_root = os.getcwd()
abs_target = os.path.abspath(target)
if not abs_target.startswith(repo_root + os.sep) and abs_target != repo_root:
    sys.exit(0)
rel = os.path.relpath(abs_target, repo_root)

# Authoritative: ask git whether the resolved path is ignored. This handles
# nested .gitignore files, negation patterns, and trailing-slash variants the
# textual prefix match below misses. Exit 0 = ignored (allow); 1 = not ignored;
# 128 = git error (fall through to the textual check + message).
try:
    r = subprocess.run(["git", "check-ignore", "--quiet", rel],
                       cwd=repo_root, capture_output=True)
    if r.returncode == 0:
        sys.exit(0)  # ignored -> allow
    if r.returncode == 1:
        top = rel.split(os.sep)[0]
        print(f"ENF-PROC-WORKTREE-001: project-local worktree target '{rel}' is not matched by any .gitignore entry. Add '{top}/' to .gitignore before creating the worktree.")
        sys.exit(0)
except Exception:
    pass  # fall through to textual fallback

# Textual fallback (only when git check-ignore is unavailable).
ignore_path = os.path.join(repo_root, ".gitignore")
if not os.path.exists(ignore_path):
    print(f"ENF-PROC-WORKTREE-001: project-local worktree target '{rel}' but no .gitignore exists. Add an entry for '{rel}' (or a parent like '.worktrees/') before creating the worktree.")
    sys.exit(0)
with open(ignore_path) as f:
    ignored = [line.strip() for line in f if line.strip() and not line.startswith("#")]
top = rel.split(os.sep)[0]
matched = any(
    top == p.strip("/") or p.rstrip("/") == top or p.startswith(top + "/")
    for p in ignored
)
if not matched:
    print(f"ENF-PROC-WORKTREE-001: project-local worktree target '{rel}' is not matched by any .gitignore entry. Add '{top}/' to .gitignore before creating the worktree.")
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
