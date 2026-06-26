#!/usr/bin/env bash
# Writ plugin bootstrap -- end-to-end setup for a Claude Code plugin install.
#
# Plugin-aware variant of scripts/bootstrap.sh. Creates a Python venv at
# ${CLAUDE_PLUGIN_DATA:-$HOME/.cache/writ}/.venv so the venv survives plugin
# upgrades that rewrite ${CLAUDE_PLUGIN_ROOT}. Installs the package via
# `pip install -e ${CLAUDE_PLUGIN_ROOT}` (editable) so subsequent upgrades
# rebind imports to the new install path. Ensures Redis is available,
# downloads the FalkorDB module, ingests the rule corpus, and starts the
# Writ daemon. Idempotent -- safe to re-run on every plugin upgrade.
#
# Usage:
#   bash $(claude plugin path writ)/scripts/bootstrap-plugin.sh

set -euo pipefail

# ── Tunables (named constants per ARCH-CONST-001) ───────────────────────────
readonly DAEMON_WAIT_SECONDS=10  # Max wait for writ serve /health after launch
readonly MIN_PYTHON_MAJOR=3
readonly MIN_PYTHON_MINOR=11
readonly FALKORDB_VERSION="v4.14.6"
readonly FALKORDB_SO="falkordb-macos-arm64v8.so"
readonly FALKORDB_URL="https://github.com/FalkorDB/FalkorDB/releases/download/${FALKORDB_VERSION}/${FALKORDB_SO}"

# ── Paths ───────────────────────────────────────────────────────────────────
# Plugin install root: prefer ${CLAUDE_PLUGIN_ROOT} (set by Claude Code when
# the plugin is loaded). Fall back to a dirname walk so the script also works
# when invoked from a checked-out repo without the plugin env set.
if [ -n "${CLAUDE_PLUGIN_ROOT:-}" ]; then
    WRIT_DIR="${CLAUDE_PLUGIN_ROOT}"
else
    SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
    WRIT_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"
fi

# Persistent data dir survives plugin upgrades.
WRIT_DATA="${CLAUDE_PLUGIN_DATA:-$HOME/.cache/writ}"
VENV_DIR="${WRIT_DATA}/.venv"
VENDOR_DIR="${WRIT_DIR}/vendor"

# ── Per-repo port (D4-02 "A-auto") ──────────────────────────────────────────
# WRIT_PORT is derived in bin/lib/common.sh (single source of truth) from
# WRIT_REPO_ROOT = 8765 + cksum(repo_root) % 1000. Pin the repo root to the
# PLUGIN dir's git toplevel (not whatever CWD bootstrap was invoked from) so
# the daemon serves THIS repo's graph on the SAME port the hooks query.
# common.sh is sourced at step 7 -- after the venv it prefers exists -- where
# it exports WRIT_PORT and provides the detached-spawn + stale-state-clean
# helpers the daemon launch needs. Trailing-slash normalized so the hash is
# stable (B3).
WRIT_REPO_ROOT="$(git -C "$WRIT_DIR" rev-parse --show-toplevel 2>/dev/null || echo "$WRIT_DIR")"
[ "$WRIT_REPO_ROOT" != "/" ] && WRIT_REPO_ROOT="${WRIT_REPO_ROOT%/}"
export WRIT_REPO_ROOT

# ── Colors (ANSI, degrade gracefully on dumb terminals) ─────────────────────
if [ -t 1 ] && [ "${TERM:-dumb}" != "dumb" ]; then
    GREEN='\033[0;32m'
    YELLOW='\033[0;33m'
    RED='\033[0;31m'
    BOLD='\033[1m'
    RESET='\033[0m'
else
    GREEN=''; YELLOW=''; RED=''; BOLD=''; RESET=''
fi

ok()   { printf "${GREEN}✓${RESET} %s\n" "$*"; }
warn() { printf "${YELLOW}!${RESET} %s\n" "$*"; }
err()  { printf "${RED}✗${RESET} %s\n" "$*" >&2; }
step() { printf "\n${BOLD}→ %s${RESET}\n" "$*"; }

# ── 1. Prerequisite checks ──────────────────────────────────────────────────
step "Checking prerequisites"

require_tool() {
    local tool="$1"
    local hint="$2"
    if ! command -v "$tool" >/dev/null 2>&1; then
        err "Missing required tool: $tool"
        echo "   $hint" >&2
        return 1
    fi
    ok "$tool"
}

missing=0
require_tool python3 "Install Python 3.11+ (e.g., apt install python3 python3-venv / brew install python@3.11)." || missing=1
require_tool brew    "Install Homebrew (https://brew.sh/)." || missing=1
require_tool jq      "Install jq (apt install jq / brew install jq)." || missing=1
require_tool curl    "Install curl (apt install curl / brew install curl)." || missing=1
# NOTE: no envsubst requirement here. The non-plugin bootstrap.sh needs it for
# CLAUDE.md/settings templating; the plugin variant ships hooks/commands/agents
# via the plugin manifest and never invokes envsubst, so requiring it only
# blocks installs on machines without gettext for no reason (Phase 6 fix).
if [ $missing -ne 0 ]; then
    err "One or more prerequisites missing. See messages above."
    exit 1
fi

# Resolve a >= 3.11 interpreter for the venv base. Bare `python3` is often the
# macOS CommandLineTools 3.9; probe versioned names first (each candidate is
# run so a broken pyenv shim is skipped). Mirrors the $WRIT_PYTHON resolver in
# bin/lib/common.sh (which can't be reused here -- it prefers the venv we are
# about to create). Override: WRIT_PYTHON=/path/to/python.
PYTHON_BIN=""
for cand in "${WRIT_PYTHON:-}" python3.12 python3.11 python3; do
    [ -z "$cand" ] && continue
    if command -v "$cand" >/dev/null 2>&1 \
       && "$cand" -c 'import sys; sys.exit(0 if sys.version_info >= (3,11) else 1)' 2>/dev/null; then
        PYTHON_BIN="$cand"; break
    fi
done
if [ -z "$PYTHON_BIN" ]; then
    err "no python >= $MIN_PYTHON_MAJOR.$MIN_PYTHON_MINOR found (tried python3.12, python3.11, python3)"
    echo "   Install a newer Python (pyenv is a clean way to manage versions)," >&2
    echo "   or set WRIT_PYTHON=/path/to/python3.12." >&2
    exit 1
fi
PY_VER=$("$PYTHON_BIN" -c 'import sys; print(f"{sys.version_info.major}.{sys.version_info.minor}")')
ok "python $PY_VER ($PYTHON_BIN)"

# ── 2. Platform check and Redis ensure ────────────────────────────────────
step "Checking platform and Redis"

# Apple Silicon only (D9)
ARCH=$(uname -m)
if [ "$ARCH" != "arm64" ]; then
    err "Unsupported architecture: $ARCH"
    echo "   Writ requires Apple Silicon (arm64). x86_64 is not supported (D9)." >&2
    exit 1
fi
ok "Apple Silicon ($ARCH)"

# Ensure /opt/homebrew/bin is on PATH so shutil.which() resolves
if ! echo "$PATH" | grep -q "/opt/homebrew/bin"; then
    export PATH="/opt/homebrew/bin:$PATH"
fi

# Ensure Redis is installed (via Homebrew, skip if present)
if command -v redis-server >/dev/null 2>&1; then
    ok "redis-server found on PATH"
elif brew list redis >/dev/null 2>&1; then
    ok "redis already installed (Homebrew)"
else
    printf "   installing redis via Homebrew... "
    brew install redis >/dev/null 2>&1
    ok "redis installed"
fi

# ── 3. Python venv at ${CLAUDE_PLUGIN_DATA}/.venv ───────────────────────────
step "Setting up Python virtualenv at $VENV_DIR"
mkdir -p "$WRIT_DATA"

# Plugin-root marker. Standalone user skills (installed in step 6b, NOT
# plugin-namespaced) and the slash commands resolve the live plugin bin/
# without CLAUDE_PLUGIN_ROOT (which is unset outside plugin hook context):
#   WR="${CLAUDE_PLUGIN_ROOT:-$(cat "$WRIT_DATA/plugin-root")}"
printf '%s\n' "$WRIT_DIR" > "$WRIT_DATA/plugin-root"
ok "plugin-root marker written ($WRIT_DATA/plugin-root)"
if [ ! -d "$VENV_DIR" ]; then
    "$PYTHON_BIN" -m venv "$VENV_DIR"
    ok "created $VENV_DIR"
else
    ok "venv already exists"
fi
# shellcheck disable=SC1091
source "$VENV_DIR/bin/activate"

# ── 4. Install Python deps (editable; rebinds on plugin upgrade) ────────────
step "Installing Python dependencies"
pip install --quiet --upgrade pip
# Install with [dev] extras so optimum (ONNX export tool) is available
# for the export step. The SentenceTransformer fallback library lives
# in the separate [fallback] group and is NOT installed by default --
# production daemons running on ONNX never need it.
pip install --quiet -e "${WRIT_DIR}[dev]"
ok "writ package installed (editable from ${WRIT_DIR}, with dev extras)"

# ── 4b. Export ONNX embedding model ─────────────────────────────────────────
ONNX_MODEL_PATH="${HOME}/.cache/writ/models/onnx/model.onnx"
step "Ensuring ONNX embedding model is exported"
if [ -f "$ONNX_MODEL_PATH" ]; then
    ok "ONNX model already present at $ONNX_MODEL_PATH (skipping export)"
else
    (cd "${WRIT_DIR}" && python scripts/export_onnx.py)
    ok "ONNX model exported to $ONNX_MODEL_PATH"
fi

# ── 5. Download FalkorDB module ───────────────────────────────────────────
step "Ensuring FalkorDB module"
mkdir -p "$VENDOR_DIR"
FALKORDB_SO_PATH="$VENDOR_DIR/falkordb.so"
if [ -f "$FALKORDB_SO_PATH" ]; then
    ok "falkordb.so already present (skipping download)"
else
    printf "   downloading falkordb-macos-arm64v8.so (${FALKORDB_VERSION})... "
    curl -sSL "$FALKORDB_URL" -o "$FALKORDB_SO_PATH"
    ok "falkordb.so downloaded"
fi

# ── 6. Ingest rules (cd into WRIT_DIR so bible/ resolves) ──────────────────
step "Ingesting rule corpus from bible/"
if (cd "${WRIT_DIR}" && writ import-markdown 2>&1 | tail -5); then
    ok "rules ingested"
else
    warn "ingestion reported errors; daemon will serve whatever made it into the graph"
fi

# ── 6b. User skills — delegated to deploy.py (NOT copied here) ───────────────
# Skill install is owned by the unified symlinker: skill_library/tools/deploy.py.
# It symlinks BOTH personal and Writ skills into ~/.claude/skills from their git
# sources, so edits land in git and `git pull` is the only cross-machine transport.
# Bootstrap must NOT copy skills here — a copy would clobber those symlinks and
# reintroduce the drift this design removes. Run deploy.py after cloning/pulling.
step "User skills (delegated to deploy.py — not copied)"
ok "skill install delegated to deploy.py (skill_library/tools/deploy.py); bootstrap skips copy"

# ── 6c. Seed Writ command allowlist into user settings ──────────────────────
# Pre-approve the Bash commands the agent is DIRECTED to run (mode set,
# project-rules, writ console, gate checks) so they bypass Claude Code's auto
# safety-classifier. Without this, those commands rely on the classifier to
# approve them at runtime; when the classifier is unavailable the mode-set
# directive (and every other writ command) is hard-blocked, wedging the
# workflow. Patterns use a leading `*` to match any python/bash prefix and
# `*/bin/...` (NOT the legacy `*writ/bin/...`) so they match the plugin-cache
# path `.../writ/<ver>/bin/writ` too. Additive + idempotent + order-preserving.
step "Seeding Writ command allowlist into ~/.claude/settings.json"
USER_SETTINGS="$HOME/.claude/settings.json"
WRIT_ALLOW='[
  "Bash(*writ-session.py *)",
  "Bash(*writ-project-rules.sh *)",
  "Bash(*/bin/writ query *)",
  "Bash(*/bin/writ status*)",
  "Bash(*/bin/writ role-prompt *)",
  "Bash(*/bin/writ validate*)",
  "Bash(*/bin/writ analyze-friction*)",
  "Bash(*/bin/writ audit-session*)",
  "Bash(bash */bin/check-gates.sh*)",
  "Bash(bash */bin/verify-files.sh*)",
  "Bash(bash */bin/scan-deps.sh*)",
  "Bash(bash */bin/run-analysis.sh*)",
  "Bash(bash */bin/validate-handoff.sh*)"
]'
if [ ! -f "$USER_SETTINGS" ]; then
    mkdir -p "$(dirname "$USER_SETTINGS")"
    printf '{}\n' > "$USER_SETTINGS"
fi
_writ_tmp_settings="$(mktemp)"
if jq --argjson add "$WRIT_ALLOW" '
      .permissions.allow = (
        (.permissions.allow // []) as $cur
        | $cur + [ $add[] | select( . as $x | ($cur | index($x)) | not ) ]
      )' "$USER_SETTINGS" > "$_writ_tmp_settings" 2>/dev/null; then
    mv "$_writ_tmp_settings" "$USER_SETTINGS"
    ok "writ command allowlist present in $USER_SETTINGS"
else
    rm -f "$_writ_tmp_settings"
    warn "could not patch $USER_SETTINGS (invalid JSON?); add the writ allow rules manually"
fi

# ── 7. Start Writ daemon ───────────────────────────────────────────────────
step "Starting Writ daemon"
# Source common.sh here (the venv from step 3 is active, so its python resolver
# finds it) for the per-repo WRIT_PORT and the detached daemon spawn / stale
# state clean helpers. The daemon MUST be launched session-detached via
# writ_spawn_daemon_detached (os.setsid): a bare `nohup writ serve &` stays in
# this script's process session and is reaped by Claude's process-tree SIGTERM
# (Claude Code issue #43123) within ~0.2s, so the /health wait loop below never
# succeeds -- the "daemon did not become healthy within 10s" reinstall failure
# (B17). writ_clean_stale_embedded_state first clears any socket/lock a prior
# reaped daemon left behind (B9, the uninstall-keep-cache-then-reinstall case).
# shellcheck disable=SC1091
source "${WRIT_DIR}/bin/lib/common.sh"

DAEMON_URL="http://localhost:${WRIT_PORT}/health"
if curl -sf --connect-timeout 0.5 "$DAEMON_URL" >/dev/null 2>&1; then
    ok "writ serve already running"
else
    WRIT_LOG="${WRIT_DATA}/server.log"
    writ_clean_stale_embedded_state "$WRIT_REPO_ROOT"
    writ_spawn_daemon_detached "$VENV_DIR/bin/python3" "$WRIT_PORT" "$WRIT_LOG" "$WRIT_REPO_ROOT"
    printf "   waiting for /health "
    waited=0
    while [ $waited -lt $DAEMON_WAIT_SECONDS ]; do
        if curl -sf --connect-timeout 0.5 "$DAEMON_URL" >/dev/null 2>&1; then
            printf "\n"
            ok "daemon ready (log $WRIT_LOG)"
            break
        fi
        printf "."
        sleep 1
        waited=$((waited + 1))
    done
    if [ $waited -ge $DAEMON_WAIT_SECONDS ]; then
        printf "\n"
        err "daemon did not become healthy within ${DAEMON_WAIT_SECONDS}s"
        echo "   Check log: $WRIT_LOG" >&2
        exit 1
    fi
fi

# ── 8. Ready banner ────────────────────────────────────────────────────────
RULE_COUNT=$(curl -sf "http://localhost:${WRIT_PORT}/stats" 2>/dev/null \
    | python3 -c "import sys,json; d=json.load(sys.stdin); print(d.get('rule_count','?'))" 2>/dev/null \
    || echo "?")

printf "\n${GREEN}${BOLD}════════════════════════════════════════════${RESET}\n"
printf "${GREEN}${BOLD}  Writ plugin is ready${RESET}\n"
printf "${GREEN}${BOLD}════════════════════════════════════════════${RESET}\n"
printf "  Plugin root    : %s\n" "$WRIT_DIR"
printf "  Venv           : %s\n" "$VENV_DIR"
printf "  Writ daemon    : http://localhost:%s\n" "$WRIT_PORT"
printf "  Rules loaded   : %s\n" "$RULE_COUNT"
printf "  Daemon log     : %s/server.log\n" "$WRIT_DATA"
printf "\n"
printf "  Verify         : curl http://localhost:%s/health\n" "$WRIT_PORT"
printf "\n"
printf "${YELLOW}!${RESET} Restart Claude Code for the hooks to take effect.\n"
