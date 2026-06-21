---
name: write-debug
description: Flip the Writ session mode to debug (advisory -- RAG rules inject incl. file-context rules on Read, no blocking gates).
---

Set the Writ workflow mode for the current session to **debug** (advisory; no Work-gated blockers), then report the helper's output line back to the user.

```bash
bash "$(git rev-parse --show-toplevel 2>/dev/null)/bin/writ-mode-set.sh" debug
```
