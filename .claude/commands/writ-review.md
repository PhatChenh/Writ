---
name: writ-review
description: Flip the Writ session mode to review (advisory -- file-context review rules surface on Read; no blocking write gates).
---

Set the Writ workflow mode for the current session to **review** (advisory; no Work-gated write blockers), then report the helper's output line back to the user.

```bash
WR="${CLAUDE_PLUGIN_ROOT:-$(cat "${CLAUDE_PLUGIN_DATA:-$HOME/.cache/writ}/plugin-root" 2>/dev/null)}"
bash "$WR/bin/writ-mode-set.sh" review
```
