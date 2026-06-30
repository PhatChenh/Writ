# Writ (Forked) — Install & Verify Guide

Hybrid RAG rule retrieval + workflow enforcement, shipped as **one Claude Code plugin**.
Per-repo isolation is data-only (A-auto): each repo gets its own graph + daemon; the
plugin source is installed once.

---

## 1. Prerequisites

| Tool | Notes |
|------|-------|
| **macOS, Apple Silicon (arm64)** | Required. FalkorDB v4.14.6 publishes no Intel macOS module — bootstrap fails on `x86_64` by design. |
| **Homebrew** | For `redis`. |
| **redis-server** | `brew install redis` (bootstrap installs it if missing). |
| **libomp** | `brew install libomp` — OpenMP runtime required by `vendor/falkordb.so`. Bootstrap does NOT auto-install; missing causes `Can't load module` abort. |
| **openssl@3** | `brew install openssl@3` — `vendor/falkordb.so` links `libssl.3.dylib`/`libcrypto.3.dylib` from `/opt/homebrew/opt/openssl@3/lib`. Same abort if missing. |
| **jq**, **curl** | Standard CLIs. |
| **Python ≥ 3.11** | ⚠️ macOS CommandLineTools `python3` is often **3.9** — too old (helpers use `str | None` syntax). See the `WRIT_PYTHON` note below. |

> **No `envsubst` / Docker / Neo4j needed.** This fork replaced Neo4j (Docker) with embedded
> FalkorDBLite. The plugin bootstrap does not template files, so `gettext`/`envsubst` is not required.

---

## 2. Install

### 2a. Register the plugin with Claude Code (one-time, manual)

The plugin must be registered before its hooks/commands load. This alters your live Claude Code
session and needs a restart, so it is a manual step:

```bash
claude plugin marketplace add <this-repo-or-marketplace>
claude plugin install writ@writ
```

### 2b. Run the bootstrap

Builds a venv at `~/.cache/writ/.venv` (survives plugin upgrades), installs the package, ensures
redis + the FalkorDB module, exports the ONNX embedding model, ingests the rule corpus, installs
the user skills (version-gated), and starts the daemon. **Idempotent** — safe to re-run.

```bash
bash "$(claude plugin path writ)/scripts/bootstrap-plugin.sh"
# or, from a checkout:
bash scripts/bootstrap-plugin.sh 
```

**If bootstrap reports `no python >= 3.11 found`** (your `python3` is 3.9 and `python3.12`/`3.11`
aren't on PATH or are broken pyenv shims), point it at a working interpreter:

```bash
WRIT_PYTHON=/path/to/python3.12 bash scripts/bootstrap-plugin.sh
# e.g. a brew python:  WRIT_PYTHON=/opt/homebrew/bin/python3.12 ...
```

### 2c. Restart Claude Code

So the hooks take effect.

---

## 3. Verify it works

```bash
# Daemon health (bootstrap starts one on :8765)
curl -s http://localhost:8765/health
# -> {"status":"healthy","rule_count":276,"mandatory_count":30,"index_state":"warm",...}

# Retrieval over HTTP (works while the daemon is running)
curl -s -X POST http://localhost:8765/query \
  -H 'Content-Type: application/json' \
  -d '{"query":"sql injection prevention","mode":"work"}' | jq '.rules | length'
# -> 10

# Skills installed (bare names)
ls ~/.claude/skills | grep -E 'grill|build-pipeline|guardrail-check'
```

**Per-repo daemon (A-auto):** in normal use you don't start daemons by hand. The RAG hook
auto-starts a daemon for the current repo on a deterministic per-repo port (derived from the git
root) on the first prompt. The `:8765` daemon above is the bootstrap default.

**Project rules (Phase 6):** author project-specific constraints into the per-repo graph; they
export to the committed `docs/rules/`.

```bash
WR="$(claude plugin path writ)"            # or the repo root
bash "$WR/bin/writ-project-rules.sh" list  # the repo's PROJ- constraints (empty at first)
```

The dispatcher **auto-manages the daemon**: if a per-repo daemon holds the graph lock, it is
momentarily stopped for the op and restarted after (the graph persists across the bounce).

---

## 4. Running the test suite

```bash
# Use the >= 3.11 interpreter on PATH (test subprocesses call bare `python3`),
# and run with the daemon STOPPED (prod-graph tests open the graph directly).
WRIT_PORT=8765 bash scripts/stop-server.sh
PATH="$HOME/.cache/writ/.venv/bin:$PATH" \
  ~/.cache/writ/.venv/bin/python -m pytest tests/ -q -p no:cacheprovider
```

> If `python3` on PATH is 3.9, ~80 tests fail in subprocesses with empty output / JSONDecodeError —
> not real failures. Prepend the venv `bin` (as above) so `python3` is ≥ 3.11.
> A single `pytest tests/` run can be slow (redis subprocess startups); batching by file helps.

---

## 5. Troubleshooting

- **`ConnectionRefusedError` / `writ query` hangs after a crash.** Orphaned `redis-server` on the
  per-repo socket + a stale socket file short-circuit onto a dead listener. Fix:
  ```bash
  pkill -f 'redis-server.*writ-' ; rm -f /tmp/writ-*/redis.sock .writ/graph.lock
  ```
  ⚠️ Before starting a daemon, ensure no orphan redis is on the socket — a shutdown BGSAVE from an
  empty orphan can clobber `.writ/graph.db` to an empty graph. Recover with
  `writ import-markdown bible` (re-seeds from the committed corpus).

- **`RuntimeError: Writ graph DB is locked by PID …`.** A daemon owns the single-writer lock. Use
  the HTTP API (`/query`, `/propose`) while it runs, or stop it (`WRIT_PORT=<port> bash
  scripts/stop-server.sh`) for direct CLI/engine ops. The project-rules dispatcher does this
  automatically.

- **`scripts/export_onnx.py` hangs.** It does an HF Hub network probe even when fully cached. Run
  `HF_HUB_OFFLINE=1 TRANSFORMERS_OFFLINE=1 python scripts/export_onnx.py`.

- **`vendor/falkordb.so` permission error.** Needs the executable bit after a manual download:
  `chmod +x vendor/falkordb.so`.

---

## 6. Uninstall (and clean reinstall)

To fully rip out the writ **plugin** install — daemons, plugin cache/registry, venv,
ONNX model, sockets — run:

```bash
bash scripts/uninstall-plugin.sh            # full removal
bash scripts/uninstall-plugin.sh --dry-run  # preview, change nothing
bash scripts/uninstall-plugin.sh --keep-cache    # keep ~/.cache/writ (venv + ~90MB ONNX) for a fast reinstall
bash scripts/uninstall-plugin.sh --purge-locks   # also rm stale .writ/graph.lock in repos that had a daemon
```

`--purge-locks` captures each running daemon's repo before killing it, then removes
a leftover `.writ/graph.lock` there (graph.db untouched). A cleanly SIGTERM'd daemon
releases its lock on its own, so this only matters after a crash / SIGKILL.

**Removes:** running per-repo daemons + their redis, the plugin cache
(`~/.claude/plugins/cache/writ`) and data dirs, registry entries
(`~/.claude/settings.json` `enabledPlugins`/`extraKnownMarketplaces`, plus
`installed_plugins.json` / `known_marketplaces.json` — each backed up first),
the `~/.claude/skills/writ` **symlink**, `~/.cache/writ` (venv + ONNX + hnsw +
logs), and `/tmp/writ-*` scratch.

**Preserves by design (NOT removed):**
- your shared user skills in `~/.claude/skills/*` (`grill`, `handoff`,
  `build-pipeline`, … — bootstrap only copies/version-gates these; they are
  treated as yours). Remove by hand if you truly want them gone.
- each repo's `.writ/` graph data (per-project, gitignored, re-creatable).
  Purge one with `rm -rf <repo>/.writ`.
- `~/.claude/CLAUDE.md`.

**Then restart Claude Code and reinstall:**

```bash
claude plugin marketplace add /Users/phatchenh/01_all_projects/falkor-writ
claude plugin install writ@writ
bash scripts/bootstrap-plugin.sh
```

> The `claude plugin` registry changes may need a Claude Code restart to fully
> apply. The uninstall is idempotent — safe to re-run.

---

## 7. Update after `git pull` (work machine)

### Current setup on this machine

| Item | Value |
|------|-------|
| Repo | `/Users/lap14806/all-projects/falkor-writ` |
| Plugin | `writ@writ 1.5.0` — user-scope, `~/.claude/plugins/cache/writ/writ/1.5.0` |
| Venv | `~/.cache/writ/.venv` — **editable install pointing to the repo above** |
| Daemon port (this repo) | `9734` (derived: `8765 + cksum(repo_root) % 1000`) |

Because the venv is an editable install, Python changes in `writ/` are already visible to
`import` — but the **running daemon has the old modules in memory** and must be restarted to
pick them up.

---

### Step 1 — Pull and see what changed

```bash
cd ~/all-projects/falkor-writ
git pull
git diff HEAD~1 --name-only
```

---

### Step 2 — Act on what changed

| Files changed | Action |
|---|---|
| `writ/` Python code | Restart daemon (Step 3) |
| `bible/` rule files | Re-ingest + restart daemon (Step 4) |
| `writ.toml` | Restart daemon (Step 3) |
| `pyproject.toml` (new deps) | Install deps (Step 5) + restart daemon (Step 3) |
| `.claude/hooks/` scripts | Restart Claude Code — hooks are shell scripts re-executed fresh; just need a new session |
| `scripts/bootstrap-plugin.sh` | Re-run bootstrap (Step 6) — only if bootstrap itself changed |

---

### Step 3 — Restart daemon

```bash
# Stop daemon + its redis
WRIT_PORT=9734 bash ~/all-projects/falkor-writ/scripts/stop-server.sh

# Verify stopped
curl -s http://localhost:9734/health || echo "stopped"

# The RAG hook auto-restarts on next Claude prompt. Or start manually:
cd ~/all-projects/falkor-writ
~/.cache/writ/.venv/bin/writ serve --port 9734 &
curl -s http://localhost:9734/health   # wait ~5s then check
```

---

### Step 4 — Re-ingest rules (only if `bible/` changed)

```bash
# Daemon must be STOPPED before direct graph write (single-writer lock)
WRIT_PORT=9734 bash ~/all-projects/falkor-writ/scripts/stop-server.sh

cd ~/all-projects/falkor-writ
~/.cache/writ/.venv/bin/writ ingest bible/

# Then restart
~/.cache/writ/.venv/bin/writ serve --port 9734 &
curl -s http://localhost:9734/health
```

---

### Step 5 — Install new Python dependencies (only if `pyproject.toml` changed)

```bash
~/.cache/writ/.venv/bin/pip install -e ~/all-projects/falkor-writ
```

Then do Step 3 (restart daemon).

---

### Step 6 — Re-run bootstrap (only if bootstrap script itself changed)

Bootstrap is idempotent — safe to re-run. It will skip steps already done
(venv exists, FalkorDB module downloaded, ONNX model exported).

```bash
bash ~/all-projects/falkor-writ/scripts/bootstrap-plugin.sh
```

---

### Quick health check after any update

```bash
curl -s http://localhost:9734/health | python3 -m json.tool
# Expect: "status":"healthy", rule_count > 0, index_state":"warm"
```
