---
name: write-review
description: Flip the Writ session mode to review (advisory -- file-context review rules surface on Read; no blocking write gates).
---

Set the Writ workflow mode for the current session to **review** (advisory; no Work-gated write blockers), then report the helper's output line back to the user.

```bash
bash "$(git rev-parse --show-toplevel 2>/dev/null)/bin/writ-mode-set.sh" review
```
