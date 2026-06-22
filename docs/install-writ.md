# Installing Writ

> Writ is distributable as a Claude Code plugin.
> See the README "Install as a Claude Code plugin" section for the
> plugin install path. The instructions below cover the standalone-skill
> install at `~/.claude/skills/writ/`, which remains supported.

Writ is a Claude Code skill at `~/.claude/skills/writ/`. After cloning
the skill repo there, two install touch-points wire it into the Claude
Code runtime so the hooks and slash commands work from any project
directory.

## 1. Sync hook permissions and registrations

The active settings file Claude Code reads at session start is
`~/.claude/settings.json`. The skill's canonical hook registrations
live in `~/.claude/skills/writ/templates/settings.json`. There are two
ways to install, depending on how much of your existing config you
want to keep.

**Full wholesale install (matches what `bootstrap.sh` does):**

```bash
bash ~/.claude/skills/writ/scripts/install-harness-config.sh
```

This renders both `templates/settings.json` and `templates/CLAUDE.md`
into `~/.claude/`, backing up any pre-existing files. Use this on
first install or after a Writ update that adds new hooks.

**Lighter alternative when only permissions changed:**

```bash
bash ~/.claude/skills/writ/scripts/patch-global-config.sh
```

This merges the cross-mode allow/deny entries into your existing
`~/.claude/settings.json` (preserving your ordering and any non-Writ
entries). By default it does **not** touch `~/.claude/CLAUDE.md` --
opt in with `WRIT_PATCH_CLAUDE_MD=1` to also render the Writ
`templates/CLAUDE.md` (it backs up any existing file first).
Hook registrations are not touched, so this is not a substitute for
the full install when hooks change. The script is the same one
plugin-mode users run; standalone users can call it for non-destructive
permission updates between full installs.

If you'd rather merge `templates/settings.json` by hand, the
Writ-specific blocks are:
- All `Bash(bash $HOME/.claude/skills/writ/.claude/hooks/*.sh)` lines
  in `permissions.allow`
- The cross-mode Bash allowlist entries (`Bash(python3 *writ-session.py *)`,
  `Bash(bash *writ/bin/*.sh*)`, `Bash(*writ/bin/writ ...*)`,
  `Bash(bash *writ/scripts/*.sh*)`)
- `AskUserQuestion` in `permissions.deny`
- All entries under `hooks` whose `command` paths point at
  `$HOME/.claude/skills/writ/.claude/hooks/`

## 2. Slash commands and user skills (handled by the plugin + bootstrap)

Slash commands (`/writ-approve`, `/writ-chat|debug|review|work`) ship
**with the plugin** from `.claude/commands/` (declared in
`.claude-plugin/plugin.json`), so installing the plugin makes them
available in every project — no separate copy step.

User skills (grill, build-pipeline, tdd-implement, …) are installed by
`scripts/bootstrap-plugin.sh` (step 6b) into `~/.claude/skills/<name>`
as plain skills, **version-gated**: a skill is installed if missing,
upgraded only when the in-repo `version:` is newer, and left untouched
otherwise (your local edits survive). Re-run bootstrap after pulling
skill updates.

## Verify install

```bash
test -f ~/.claude/commands/writ-approve.md && echo "/writ-approve installed"
grep -q writ-memory-policy-guard ~/.claude/settings.json && \
    echo "memory-policy-guard hook registered"
```

Both should print confirmation lines. If neither does, re-run the
relevant step above.

## Update path

When the skill is updated (`git pull` or equivalent in
`~/.claude/skills/writ/`), re-run the install steps:

```bash
bash $(claude plugin path writ)/scripts/install-harness-config.sh
bash $(claude plugin path writ)/scripts/bootstrap-plugin.sh
```

`install-harness-config.sh` is destructive (renders the templates wholesale,
backing up any pre-existing files). `bootstrap-plugin.sh` is idempotent and
re-installs user skills version-gated (step 6b). Slash commands ride the
plugin (no separate copy step). If the update only touched permissions
(no new hooks), `scripts/patch-global-config.sh` is a non-destructive
alternative that preserves your existing `~/.claude/settings.json`
ordering and non-Writ entries (and leaves `~/.claude/CLAUDE.md` alone
unless you set `WRIT_PATCH_CLAUDE_MD=1`).

## 3. Restart the writ daemon (when server.py changes)

When `writ/server.py` changes (new endpoints, modified routes), the
running uvicorn process keeps serving the old module until restarted.
PSR-005 caught a `/dashboard` 404 traced to exactly this: the route
was wired in code but the daemon predated the change.

```bash
pkill -f "writ.*serve" || true
nohup writ serve > /tmp/writ-server.log 2>&1 &
```

Verify with `curl -sf http://localhost:8765/health`. Restart is only
required when `server.py` (or any FastAPI route module it imports)
changes; routine ingest, query, or hook updates do not need it.

## Known limitations

- `install-harness-config.sh` (and the older `cp` approach) replaces
  your active `~/.claude/settings.json` wholesale. Custom permissions
  or hooks outside the Writ template are lost. Use
  `patch-global-config.sh` for non-destructive permission updates, or
  merge by hand if you have non-Writ hook registrations.
- The user-commands installer overwrites identically-named files in
  `~/.claude/commands/`. If you have a non-Writ `writ-approve.md`
  there for some reason, it gets replaced.
- Restarting Claude Code is required after install changes for the
  settings/commands to take effect in a running session.