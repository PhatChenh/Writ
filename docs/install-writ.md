# Installing Writ on a new machine

This guide sets up Writ from scratch on a **fresh Mac**. It is written to be
followed top-to-bottom — copy each command block into your terminal, wait for
it to finish, then move on. You do not need to understand the internals.

> **Already have Writ on this machine and just pulled new code?**
> You don't need this guide — see [multi-machine-sync.md](multi-machine-sync.md)
> (short version: `git pull` in the clone, then restart Claude Code).

---

## What you're installing

Writ is a Claude Code add-on with two parts:

- **The rule engine** — a small background service that feeds Claude the
  relevant coding rules for whatever you're working on.
- **The workflow hooks** — scripts that enforce a plan → test → code discipline.

Both travel with a single folder (a git clone) that Claude Code points at.
Updating later is just `git pull` + restart.

---

## Before you start — requirements

Writ runs on **Apple Silicon Macs only** (M1/M2/M3/M4). Intel Macs are not
supported. Check by running:

```sh
uname -m        # must print: arm64
```

You also need these tools. The bootstrap script checks for them and tells you
exactly what's missing, but you can install them up front:

| Tool | Install command |
|------|-----------------|
| Homebrew | See https://brew.sh |
| Python 3.11+ | `brew install python@3.11` |
| git | `brew install git` |
| gettext (`envsubst`) | `brew install gettext` |

(Redis and the FalkorDB database module are installed **for you** by the
bootstrap script — you don't fetch those yourself.)

---

## Step 1 — Get the code

Clone the repo somewhere permanent. The folder name and location are up to you;
this guide uses `~/all-projects/falkor-writ` as the example — **substitute your
own path everywhere you see it.**

```sh
git clone https://github.com/PhatChenh/Writ.git ~/all-projects/falkor-writ
```

> **Multi-machine note:** the clone path can differ per machine
> (`~/all-projects/...` on one, `~/01_all_projects/...` on another). That is
> fine — nothing hard-codes the path *except* the CodeGraph gate hooks, which
> Step 5 handles with a stable symlink.

---

## Step 2 — Tell Claude Code about the folder

Open `~/.claude/settings.json` and add these two blocks (merge them in if the
file already has other settings). **Replace the path with your Step 1 path.**

```json
"extraKnownMarketplaces": {
  "writ": { "source": { "source": "directory", "path": "/Users/YOU/all-projects/falkor-writ" } }
},
"enabledPlugins": { "writ@writ": true }
```

This registers Writ as a "directory-source" plugin — Claude Code runs it
straight from your clone, so future updates are just `git pull` + restart.

---

## Step 3 — Run the bootstrap

This one script does everything else: installs Redis, creates an isolated
Python environment, downloads the FalkorDB database module, loads the rule
corpus, and starts the background service. It is safe to re-run any time.

```sh
bash ~/all-projects/falkor-writ/scripts/bootstrap-plugin.sh
```

It prints a checklist as it goes (✓/✗ per step) and a "Ready" banner with the
rule count at the end. If a prerequisite is missing it stops and tells you what
to install, then you re-run it.

---

## Step 4 — Turn off permission prompts for Writ's own commands

Plugin installs don't touch your permissions, so Claude Code will otherwise ask
permission every time a Writ hook runs. Run this once to allow them:

```sh
bash ~/all-projects/falkor-writ/scripts/patch-global-config.sh
```

This *merges* into your `~/.claude/settings.json` — it preserves your existing
settings and ordering, and does not touch `~/.claude/CLAUDE.md`.

---

## Step 5 — Link the CodeGraph gate hooks (required if you use CodeGraph)

This repo's project settings register two extra hooks that live in a **separate**
tool folder, `codegraph-piggyback`. That folder sits under your projects
directory — whose name differs between machines — so the settings reference a
stable symlink instead of a hard-coded path. Create the symlink once per machine,
pointing at wherever `codegraph-piggyback` actually lives on *this* machine:

```sh
# Replace the target with this machine's real codegraph-piggyback path:
ln -s ~/all-projects/codegraph-piggyback ~/.cg-piggyback
```

Verify it resolves:

```sh
test -f ~/.cg-piggyback/codegraph-gate/codegraph-gate.py && echo "gate OK"
test -f ~/.cg-piggyback/ssot-diagram/decision_hook.py && echo "decision-hook OK"
```

Both should print `OK`. If you skip this step, Claude Code's Read/Grep/Glob
tools error with `can't open file ... codegraph-gate.py` until the symlink exists.

> **Why a symlink?** `~/.claude/settings.json` for this repo is committed to git
> and shared across machines. A hard-coded projects path (`~/all-projects/...`
> vs `~/01_all_projects/...`) would break on the other machine. The symlink
> `~/.cg-piggyback` is the one stable name every machine agrees on; each machine
> points it at its own real folder.

---

## Verify the whole install

```sh
# 1. Background service is up (port is auto-derived per repo — this asks the
#    running daemon for its own health, not a fixed port):
writ query "test" >/dev/null 2>&1 && echo "rule engine responding" || echo "daemon down — see troubleshooting"

# 2. Permission allowlist merged into user settings:
grep -q writ-session ~/.claude/settings.json && echo "command allowlist merged"
```

Then **restart Claude Code** so it loads the new hooks, agents, and settings.
A running session does not pick up install changes. In a fresh session, typing `/writ-work` should show Writ's slash commands — that confirms the plugin loaded.

---

## Keeping `writ` on your PATH (optional but handy)

The `writ` command lives at `<clone>/bin/writ`. To run it from any folder,
symlink it into a directory already on your PATH:

```sh
ln -sf ~/all-projects/falkor-writ/bin/writ ~/.local/bin/writ
```

Confirm from a fresh terminal: `which writ` should print the symlink path.

---

## Updating later

Directory-source installs update with plain git — **no plugin cache step**:

```sh
cd ~/all-projects/falkor-writ
git status          # must be clean first
git pull origin main
bash scripts/bootstrap-plugin.sh   # re-run: idempotent, picks up new deps/rules
```

Then restart Claude Code. Full detail and the "which install type am I?" check
are in [multi-machine-sync.md](multi-machine-sync.md).

**When only `writ/server.py` (the service code) changed**, the running daemon
keeps serving the old code until restarted:

```sh
pkill -f "writ.*serve" || true
nohup writ serve > /tmp/writ-server.log 2>&1 &
```

---

## Troubleshooting

**`writ: command not found`** — the clone's `bin/` isn't on your PATH and no
symlink exists. Do the "Keeping `writ` on your PATH" step above.

**`can't open file ... codegraph-gate.py`** on every Read/Grep — the Step 5
symlink is missing or points at the wrong folder. Recreate `~/.cg-piggyback`.

**`ConnectionRefusedError` / daemon won't answer** — a stale background service
from a crashed run. Clear it and re-bootstrap:

```sh
pkill -f "redis-server unixsocket:/tmp/writ-" || true
rm -f /tmp/writ-*/redis.sock
bash ~/all-projects/falkor-writ/scripts/bootstrap-plugin.sh
```

**Bootstrap stops on `x86_64 not supported`** — you're on an Intel Mac. Writ
requires Apple Silicon; there is no Intel build of the FalkorDB module.

**ONNX / embedding-model export hangs** — force offline mode:

```sh
HF_HUB_OFFLINE=1 TRANSFORMERS_OFFLINE=1 python scripts/export_onnx.py
```

---

## Notes

- The Python environment lives at `~/.cache/writ/.venv` (survives updates), and
  the FalkorDB module at `<clone>/vendor/falkordb.so`.
- Each repo gets its **own** background service on an auto-derived port, so
  several projects can run Writ at once without colliding.
- These setup files live in the `PhatChenh/Writ` fork (`origin`), not the
  upstream `infinri/Writ`. If you merge upstream, keep the fork's install docs.
