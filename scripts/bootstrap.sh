#!/usr/bin/env bash
# Writ bootstrap -- end-to-end setup for a new machine.
#
# Runs prerequisite checks, creates a Python venv, installs the package,
# renders the harness config from templates, symlinks rules and agent
# definitions, ensures Redis is available, downloads the FalkorDB module,
# ingests the rule corpus, and starts the Writ daemon.
# Idempotent -- safe to re-run.
#
# Usage:
#   cd ~/.claude/skills/writ
#   bash scripts/bootstrap.sh

set -euo pipefail

# ── Tunables (named constants per ARCH-CONST-001) ───────────────────────────
readonly DAEMON_WAIT_SECONDS=10  # Max wait for writ serve /health after launch
readonly MIN_PYTHON_MAJOR=3
readonly MIN_PYTHON_MINOR=11
readonly FALKORDB_VERSION="v4.14.6"
readonly FALKORDB_SO="falkordb-macos-arm64v8.so"
readonly FALKORDB_URL="https://github.com/FalkorDB/FalkorDB/releases/download/${FALKORDB_VERSION}/${FALKORDB_SO}"

# ── Paths ───────────────────────────────────────────────────────────────────
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
WRIT_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"
VENV_DIR="$WRIT_DIR/.venv"
VENDOR_DIR="$WRIT_DIR/vendor"

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
require_tool git     "Install git (apt install git / brew install git)." || missing=1
require_tool envsubst "Install gettext (apt install gettext-base / brew install gettext)." || missing=1
if [ $missing -ne 0 ]; then
    err "One or more prerequisites missing. See messages above."
    exit 1
fi

# Python version check
PY_VER=$(python3 -c 'import sys; print(f"{sys.version_info.major}.{sys.version_info.minor}")')
PY_MAJOR=${PY_VER%.*}
PY_MINOR=${PY_VER#*.}
if [ "$PY_MAJOR" -lt "$MIN_PYTHON_MAJOR" ] \
   || { [ "$PY_MAJOR" -eq "$MIN_PYTHON_MAJOR" ] && [ "$PY_MINOR" -lt "$MIN_PYTHON_MINOR" ]; }; then
    err "python3 version is $PY_VER; need >= $MIN_PYTHON_MAJOR.$MIN_PYTHON_MINOR"
    echo "   Install a newer Python (pyenv is a clean way to manage versions)." >&2
    exit 1
fi
ok "python3 $PY_VER"

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

# ── 3. Python venv ──────────────────────────────────────────────────────────
step "Setting up Python virtualenv"
if [ ! -d "$VENV_DIR" ]; then
    python3 -m venv "$VENV_DIR"
    ok "created $VENV_DIR"
else
    ok "venv already exists"
fi
# shellcheck disable=SC1091
source "$VENV_DIR/bin/activate"

# ── 4. Install Python deps ──────────────────────────────────────────────────
step "Installing Python dependencies"
pip install --quiet --upgrade pip
# Install with [dev] extras so optimum (ONNX export tool) is available
# for the next step. The SentenceTransformer fallback library lives in
# the separate [fallback] group and is NOT installed by default --
# production daemons running on ONNX never need it. Operators who want
# to exercise the WRIT_ALLOW_EMBEDDING_FALLBACK=1 path can install it
# explicitly with `pip install -e '.[fallback]'`.
(cd "$WRIT_DIR" && pip install --quiet -e '.[dev]')
ok "writ package installed (editable, with dev extras)"

# ── 4b. Export ONNX embedding model ─────────────────────────────────────────
ONNX_MODEL_PATH="$HOME/.cache/writ/models/onnx/model.onnx"
step "Ensuring ONNX embedding model is exported"
if [ -f "$ONNX_MODEL_PATH" ]; then
    ok "ONNX model already present at $ONNX_MODEL_PATH (skipping export)"
else
    (cd "$WRIT_DIR" && python scripts/export_onnx.py)
    ok "ONNX model exported to $ONNX_MODEL_PATH"
fi

# ── 5. Harness config ───────────────────────────────────────────────────────
step "Installing harness config (~/.claude/settings.json + CLAUDE.md)"
bash "$SCRIPT_DIR/install-harness-config.sh"

# ── 6. Symlinks for rules + agents ──────────────────────────────────────────
step "Linking rules and agent definitions into ~/.claude/"
mkdir -p "$HOME/.claude/rules" "$HOME/.claude/agents"

link_all() {
    local src_dir="$1"
    local dst_dir="$2"
    for src in "$src_dir"/*.md; do
        [ -f "$src" ] || continue
        local name
        name=$(basename "$src")
        local target="$dst_dir/$name"
        if [ -L "$target" ] || [ ! -e "$target" ]; then
            ln -sf "$src" "$target"
        fi
    done
}

link_all "$WRIT_DIR/rules" "$HOME/.claude/rules"
link_all "$WRIT_DIR/.claude/agents" "$HOME/.claude/agents"
ok "rules and agents linked"

# ── 7. Download FalkorDB module ───────────────────────────────────────────
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

# ── 8. Ingest rules ────────────────────────────────────────────────────────
step "Ingesting rule corpus from bible/"
if writ import-markdown 2>&1 | tail -5; then
    ok "rules ingested"
else
    warn "ingestion reported errors; daemon will serve whatever made it into the graph"
fi

# ── 9. Start Writ daemon ───────────────────────────────────────────────────
step "Starting Writ daemon"
DAEMON_URL="http://localhost:8765/health"
if curl -sf --connect-timeout 0.5 "$DAEMON_URL" >/dev/null 2>&1; then
    ok "writ serve already running"
else
    WRIT_LOG="/tmp/writ-server.log"
    nohup writ serve > "$WRIT_LOG" 2>&1 &
    DAEMON_PID=$!
    printf "   waiting for /health "
    waited=0
    while [ $waited -lt $DAEMON_WAIT_SECONDS ]; do
        if curl -sf --connect-timeout 0.5 "$DAEMON_URL" >/dev/null 2>&1; then
            printf "\n"
            ok "daemon ready (pid $DAEMON_PID, log $WRIT_LOG)"
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

# ── 10. Ready banner ───────────────────────────────────────────────────────
RULE_COUNT=$(curl -sf "http://localhost:8765/stats" 2>/dev/null \
    | python3 -c "import sys,json; d=json.load(sys.stdin); print(d.get('rule_count','?'))" 2>/dev/null \
    || echo "?")

printf "\n${GREEN}${BOLD}════════════════════════════════════════════${RESET}\n"
printf "${GREEN}${BOLD}  Writ is ready${RESET}\n"
printf "${GREEN}${BOLD}════════════════════════════════════════════${RESET}\n"
printf "  Writ daemon    : http://localhost:8765\n"
printf "  Rules loaded   : %s\n" "$RULE_COUNT"
printf "  Daemon log     : /tmp/writ-server.log\n"
printf "  Harness config : ~/.claude/settings.json, ~/.claude/CLAUDE.md\n"
printf "\n"
printf "${YELLOW}!${RESET} Restart Claude Code for the hooks to take effect.\n"
