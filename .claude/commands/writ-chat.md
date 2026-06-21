---
name: writ-chat
description: Flip the Writ session mode to chat (advisory only -- RAG rules inject, no blocking gates). "chat" maps to the server's conversation mode.
---

Set the Writ workflow mode for the current session to **chat** (advisory; no Work-gated blockers), then report the helper's output line back to the user.

```bash
WR="${CLAUDE_PLUGIN_ROOT:-$(cat "${CLAUDE_PLUGIN_DATA:-$HOME/.cache/writ}/plugin-root" 2>/dev/null)}"
bash "$WR/bin/writ-mode-set.sh" chat
```
