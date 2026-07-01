# Syncing Writ across machines (directory-source install)

If Writ is installed as a **directory-source** marketplace (a local git clone
that Claude Code points at), there is **no plugin "update" command and no cache
step**. Claude Code runs hooks and agents straight from the clone via
`${CLAUDE_PLUGIN_ROOT}`. Updating = `git pull` in the clone + restart Claude Code.

This is how the `block-spawning-agents` PreToolUse hook and the `worker` agent
travel between machines.

## Confirm your install type first

```sh
grep -A3 '"writ"' ~/.claude/settings.json
```

- `source: "directory"` → follow this doc (`git pull` + restart).
- `source: "github"` → you installed via `/plugin`; Claude Code runs from its
  own cache, not a pullable clone. Update through the `/plugin` menu
  (`/plugin marketplace update writ`) instead of `git pull`.

## Update an existing clone (the common case)

```sh
cd <path-to>/falkor-writ
git status            # must be clean; resolve local edits / divergence first
git pull origin main
```

Then **restart Claude Code**. Hooks (`hooks/hooks.json`) and agents
(`.claude-plugin/plugin.json` → `.claude/agents/*.md`) are read at SessionStart;
a running session will not pick up the pull.

## Fresh machine (no clone yet)

```sh
git clone https://github.com/PhatChenh/Writ.git <path-to>/falkor-writ
```

Then in `~/.claude/settings.json` add (adjust the absolute path per machine):

```json
"extraKnownMarketplaces": {
  "writ": { "source": { "source": "directory", "path": "<abs-path>/falkor-writ" } }
},
"enabledPlugins": { "writ@writ": true }
```

Restart Claude Code.

## Verify the spawn-block hook + worker agent

Direct hook test (no restart needed):

```sh
echo '{"tool_name":"Agent","tool_input":{"subagent_type":"general-purpose"}}' | \
  python3 <path-to>/falkor-writ/hooks/scripts/block-spawning-agents.py; echo "exit=$?"
# expect exit=2 and a BLOCKED message

echo '{"tool_name":"Agent","tool_input":{"subagent_type":"worker"}}' | \
  python3 <path-to>/falkor-writ/hooks/scripts/block-spawning-agents.py; echo "exit=$?"
# expect exit=0, no output
```

After restart, `worker` should appear in the agent picker.

## What each piece is

- `hooks/scripts/block-spawning-agents.py` — denies spawn-capable subagent types
  (`general-purpose`, `claude`, default). They carry `Tools: *`, so they can
  recursively spawn grandchildren (the fan-out that burned a usage limit).
- `worker` agent — a leaf agent with `Read/Edit/Write/Grep/Glob/Bash` and **no**
  Agent/Task tool: writes files at any scope but cannot spawn. Use it instead of
  read-only `Explore` when a delegated task needs to write.

## Fork note

These live in the `PhatChenh/Writ` fork (`origin`), not `infinri/Writ`
(`upstream`). If you merge upstream, keep these commits.
