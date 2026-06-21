---
name: write-work
description: Flip the Writ session mode to work -- arms full Process Keeper: test-first gate, design-doc/plan-exit gates, plan->test->code approval machine, verify-before-claim, violation-forced-continue.
---

Set the Writ workflow mode for the current session to **work** (arms the Work-gated blocking hooks + the plan->test->code gate machine), then report the helper's output line back to the user.

```bash
bash "$(git rev-parse --show-toplevel 2>/dev/null)/bin/writ-mode-set.sh" work
```
