#!/usr/bin/env bash
# Writ plugin uninstaller — rips out the writ PLUGIN install so a fresh
# `claude plugin install` + scripts/bootstrap-plugin.sh starts from clean.
#
# REMOVES:
#   - running per-repo daemons + their redis processes
#   - plugin registry entries: ~/.claude/settings.json (enabledPlugins["writ@writ"]
#     + extraKnownMarketplaces["writ"]), installed_plugins.json, known_marketplaces.json
#   - plugin cache + data: ~/.claude/plugins/cache/writ, ~/.claude/plugins/data/writ-*
#   - the ~/.claude/skills/writ SYMLINK (the symlink only, never its target repo)
#   - ~/.cache/writ  (venv + ONNX model + hnsw cache + server.log + origin_context.db)
#   - /tmp/writ-*    (redis sockets, logs, session files, start-locks)
#
# PRESERVES BY DESIGN (NOT removed):
#   - your shared user skills in ~/.claude/skills/<name> (grill, handoff,
#     build-pipeline, guardrail-check, ...). bootstrap only COPIES these and
#     version-gates them; on this machine they predate the writ install, so they
#     are treated as yours. Remove by hand if you truly want them gone.
#   - each repo's .writ/ graph data (per-project, gitignored, re-creatable)
#   - ~/.claude/CLAUDE.md (writ's CLAUDE.md render is opt-in and was not applied)
#
# Flags:
#   --keep-cache    keep ~/.cache/writ (venv + ~90MB ONNX model) for a fast reinstall
#   --purge-locks   also rm a stale .writ/graph.lock in each repo that had a daemon
#                   (graph.db is NOT touched). A SIGTERM'd daemon releases its lock
#                   cleanly, so this only matters if one was SIGKILL'd / crashed.
#   --dry-run       print every action, change nothing
#
# Idempotent / re-run safe. After it finishes: restart Claude Code, then reinstall.
set -euo pipefail

KEEP_CACHE=0
DRY_RUN=0
PURGE_LOCKS=0
for arg in "$@"; do
    case "$arg" in
        --keep-cache)  KEEP_CACHE=1 ;;
        --purge-locks) PURGE_LOCKS=1 ;;
        --dry-run)     DRY_RUN=1 ;;
        -h|--help)     sed -n '2,31p' "$0"; exit 0 ;;
        *) echo "unknown flag: $arg (see --help)" >&2; exit 1 ;;
    esac
done

# ── Colors ──────────────────────────────────────────────────────────────────
if [ -t 1 ] && [ "${TERM:-dumb}" != "dumb" ]; then
    GREEN='\033[0;32m'; YELLOW='\033[0;33m'; RED='\033[0;31m'; BOLD='\033[1m'; RESET='\033[0m'
else
    GREEN=''; YELLOW=''; RED=''; BOLD=''; RESET=''
fi
ok()   { printf "${GREEN}✓${RESET} %s\n" "$*"; }
warn() { printf "${YELLOW}!${RESET} %s\n" "$*"; }
step() { printf "\n${BOLD}→ %s${RESET}\n" "$*"; }
note() { printf "  %s\n" "$*"; }

# run / show a mutating command, honoring --dry-run
run() {
    if [ "$DRY_RUN" -eq 1 ]; then
        printf "  ${YELLOW}[dry-run]${RESET} %s\n" "$*"
    else
        eval "$@"
    fi
}

CLAUDE_DIR="$HOME/.claude"
CACHE_DIR="$HOME/.cache/writ"

[ "$DRY_RUN" -eq 1 ] && warn "DRY RUN — nothing will be changed."

# ── 1. Stop daemons + redis ──────────────────────────────────────────────────
step "Stopping writ daemons and redis"
# Match BOTH daemon launch forms so neither orphans through uninstall:
#   - hook auto-start:  python -m uvicorn writ.server:app --port ...
#   - bootstrap / CLI:   .../bin/writ serve   (cmdline has NO "uvicorn writ.server:app")
# The pattern is an extended regex (pkill/pgrep -f). Specific enough not to hit
# `writ import-markdown`, `writ-project-rules.sh`, or this uninstaller itself.
DAEMON_PAT='uvicorn writ\.server:app|/writ serve'
# --purge-locks: capture each daemon's repo (cwd) BEFORE killing it — the pid is
# gone post-kill, so we record where to look for a stale graph.lock now.
DAEMON_CWDS=""
if [ "$PURGE_LOCKS" -eq 1 ]; then
    for _pid in $(pgrep -f "$DAEMON_PAT" 2>/dev/null); do
        _cwd=$(lsof -a -p "$_pid" -d cwd -Fn 2>/dev/null | sed -n 's/^n//p' | head -1)
        [ -n "$_cwd" ] && DAEMON_CWDS="${DAEMON_CWDS}${_cwd}
"
    done
fi
if pgrep -f "$DAEMON_PAT" >/dev/null 2>&1; then
    run "pkill -f '$DAEMON_PAT' || true"
    ok "writ daemons signalled (uvicorn + writ serve forms)"
else
    ok "no writ daemons running"
fi
if pgrep -f "redis-server unixsocket:/tmp/writ-" >/dev/null 2>&1; then
    run "pkill -f 'redis-server unixsocket:/tmp/writ-' || true"
    ok "writ redis processes signalled"
else
    ok "no writ redis processes running"
fi

# --purge-locks: with the daemons down, remove any stale .writ/graph.lock left in
# the repos they ran in (plus the current dir). A clean SIGTERM release leaves
# nothing; this only catches crash/SIGKILL leftovers. graph.db is never touched.
if [ "$PURGE_LOCKS" -eq 1 ]; then
    step "Purging stale graph.lock (--purge-locks)"
    [ "$DRY_RUN" -eq 0 ] && sleep 1   # let a SIGTERM-driven lock release settle
    _purged=0
    while IFS= read -r _r; do
        [ -n "$_r" ] || continue
        _lock="$_r/.writ/graph.lock"
        if [ -f "$_lock" ]; then run "rm -f '$_lock'"; ok "removed $_lock"; _purged=1; fi
    done <<EOF
$(printf '%s\n%s\n' "$DAEMON_CWDS" "$PWD" | sort -u)
EOF
    [ "$_purged" -eq 0 ] && ok "no stale graph.lock in daemon repos"
    note "elsewhere (a daemon SIGKILL'd in another repo): rm <repo>/.writ/graph.lock"
fi

# ── 2. Plugin registry (prefer the official CLI, fall back to jq) ─────────────
step "Removing plugin registration"
if command -v claude >/dev/null 2>&1; then
    run "claude plugin uninstall writ@writ >/dev/null 2>&1 || true"
    run "claude plugin marketplace remove writ >/dev/null 2>&1 || true"
    ok "claude plugin uninstall + marketplace remove attempted"
    note "(plugin CLI changes may need a Claude Code restart to fully apply)"
else
    warn "claude CLI not on PATH — will clean registry files directly"
fi

# Belt-and-suspenders: scrub writ entries from the registry JSON files even if
# the CLI ran (older CLI versions leave some). Each file is backed up first.
edit_json() {  # edit_json <file> <jq-filter>
    local file="$1" filter="$2"
    [ -f "$file" ] || return 0
    command -v jq >/dev/null 2>&1 || { warn "jq missing; skipped $file (edit by hand)"; return 0; }
    grep -q '"writ"\|writ@writ' "$file" 2>/dev/null || return 0
    if [ "$DRY_RUN" -eq 1 ]; then
        printf "  ${YELLOW}[dry-run]${RESET} jq '%s' %s\n" "$filter" "$file"; return 0
    fi
    local bak="${file}.bak.$(date -u +%Y%m%dT%H%M%SZ)"
    cp "$file" "$bak"
    if jq "$filter" "$file" >"${file}.tmp" 2>/dev/null; then
        mv "${file}.tmp" "$file"; ok "scrubbed writ from $(basename "$file") (backup: $bak)"
    else
        rm -f "${file}.tmp"; mv "$bak" "$file"; warn "jq edit failed on $file; left untouched"
    fi
}
edit_json "$CLAUDE_DIR/settings.json"          'del(.enabledPlugins["writ@writ"]) | del(.extraKnownMarketplaces["writ"])'
edit_json "$CLAUDE_DIR/plugins/installed_plugins.json"   'del(.plugins["writ@writ"])'
edit_json "$CLAUDE_DIR/plugins/known_marketplaces.json"  'del(.writ)'

# ── 3. Plugin cache + data ───────────────────────────────────────────────────
step "Removing plugin cache and data"
for d in "$CLAUDE_DIR"/plugins/cache/writ "$CLAUDE_DIR"/plugins/data/writ-*; do
    [ -e "$d" ] || continue
    run "rm -rf '$d'"; ok "removed $d"
done

# ── 4. Skills symlink (symlink only — never the target repo) ─────────────────
step "Removing the skills symlink"
SK="$CLAUDE_DIR/skills/writ"
if [ -L "$SK" ]; then
    run "rm '$SK'"; ok "removed symlink $SK -> $(readlink "$SK" 2>/dev/null)"
elif [ -e "$SK" ]; then
    warn "$SK is NOT a symlink (real dir) — left in place; inspect manually"
else
    ok "no skills/writ symlink"
fi

# ── 5. Data + model cache ────────────────────────────────────────────────────
step "Removing data/model cache (~/.cache/writ)"
if [ "$KEEP_CACHE" -eq 1 ]; then
    warn "--keep-cache: leaving $CACHE_DIR (venv + ONNX model) intact"
elif [ -d "$CACHE_DIR" ]; then
    run "rm -rf '$CACHE_DIR'"; ok "removed $CACHE_DIR"
else
    ok "no $CACHE_DIR"
fi

# ── 6. /tmp scratch ──────────────────────────────────────────────────────────
step "Removing /tmp/writ-* scratch"
if ls /tmp/writ-* >/dev/null 2>&1; then
    run "rm -rf /tmp/writ-*"; ok "removed /tmp/writ-* (sockets, logs, locks, sessions)"
else
    ok "no /tmp/writ-* files"
fi

# ── 7. Preserved items (informational) ───────────────────────────────────────
step "Preserved (NOT removed)"
note "Shared user skills in ~/.claude/skills/ — writ ships copies of these but"
note "they predate/overlap your own; remove by hand only if you are sure:"
note "  build-pipeline codebase-design-analysis grill guardrail-check handoff"
note "  plan-from-specs review-implementation subagent-driven-development"
note "  tdd-implement think-with-me writing-detailed-specs"
note ""
note "Per-repo graph data (.writ/) is left in each repo. To purge a repo's graph:"
note "  rm -rf <repo>/.writ"
note ""
note "~/.claude/CLAUDE.md is left untouched."

printf "\n${GREEN}${BOLD}════════════════════════════════════════════${RESET}\n"
printf "${GREEN}${BOLD}  Writ plugin uninstalled${RESET}\n"
printf "${GREEN}${BOLD}════════════════════════════════════════════${RESET}\n"
note "Next: restart Claude Code, then reinstall:"
note "  claude plugin marketplace add /Users/phatchenh/01_all_projects/falkor-writ"
note "  claude plugin install writ@writ"
note "  bash scripts/bootstrap-plugin.sh"
[ "$DRY_RUN" -eq 1 ] && warn "DRY RUN — nothing was changed."
