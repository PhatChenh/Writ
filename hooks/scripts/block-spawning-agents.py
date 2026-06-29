#!/usr/bin/env python3
"""PreToolUse gate for the subagent-spawn tool (named "Agent" or "Task").

Root cause this blocks: dispatching a subagent whose toolset includes the spawn
tool lets that child spawn its own grandchildren, fanning out uncontrollably
(this exhausted a 5-hour usage limit on 2026-06-29). Leaf agent types that lack
the spawn tool cannot recurse, so only the spawn-capable types are denied here.

Deny: general-purpose, claude, and the default (subagent_type omitted -> resolves
to general-purpose). These carry `Tools: *` (the spawn tool included).
Allow: every other (leaf) agent type -- Explore, Plan, cavecrew-*, writ-*,
reasonix-*, etc. -- which cannot spawn.

Portable: ships inside the Writ plugin (hooks/scripts/), referenced from
hooks/hooks.json via ${CLAUDE_PLUGIN_ROOT}. Travels to every machine that
installs Writ; applies to every project where Writ is enabled.
"""
import json
import sys

# Agent types known to carry the spawn tool (Tools: *) and therefore able to
# recursively spawn. Default (no subagent_type) resolves to general-purpose.
SPAWN_CAPABLE = {"general-purpose", "claude", ""}

# Tool names used for subagent spawning across Claude Code versions.
SPAWN_TOOLS = {"Agent", "Task"}

try:
    payload = json.load(sys.stdin)
except Exception:
    # If we cannot parse the event, fail safe: do not block.
    sys.exit(0)

if payload.get("tool_name") not in SPAWN_TOOLS:
    sys.exit(0)

subagent_type = (payload.get("tool_input", {}) or {}).get("subagent_type", "") or ""

if subagent_type.strip().lower() in SPAWN_CAPABLE:
    msg = (
        f"BLOCKED: subagent_type '{subagent_type or '(default=general-purpose)'}' "
        "carries the spawn tool and can recursively spawn grandchildren "
        "(the fan-out that burned a usage limit). Use a leaf agent type that "
        "cannot spawn: Explore, Plan, cavecrew-investigator, or another type "
        "without the Agent/Task tool. To override, the user must remove this hook "
        "from the Writ plugin's hooks/hooks.json."
    )
    print(msg, file=sys.stderr)
    sys.exit(2)  # exit 2 = deny the tool call, surface stderr to the model

sys.exit(0)
