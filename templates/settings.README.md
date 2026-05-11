# templates/settings.json — legacy install template

This file is consumed by `scripts/install-harness-config.sh` when Writ is
installed as a standalone skill at `~/.claude/skills/writ/`. The script
substitutes `$HOME` and renders the JSON into `~/.claude/settings.json`,
registering all 31 hooks against the user's global Claude Code config.

**Plugin installs do not use this file.** When Writ is installed via
`/plugin install writ@writ`, Claude Code reads the hook configuration from
`hooks/hooks.json` (at the plugin root), which uses `${CLAUDE_PLUGIN_ROOT}`
paths so registrations remain valid across plugin upgrades.

Keep the hook registrations in `hooks/hooks.json` and `templates/settings.json`
in sync until the standalone install path is sunset. After every change to one,
update the other.
