---
name: writ-debug
description: Flip the Writ session mode to debug (advisory -- RAG rules inject incl. file-context rules on Read, no blocking gates).
---

Set the Writ workflow mode for the current session to **debug** (advisory; no Work-gated blockers), then report the helper's output line back to the user.

```bash
WR="${CLAUDE_PLUGIN_ROOT:-$(cat "${CLAUDE_PLUGIN_DATA:-$HOME/.cache/writ}/plugin-root" 2>/dev/null)}"
bash "$WR/bin/writ-mode-set.sh" debug
```
