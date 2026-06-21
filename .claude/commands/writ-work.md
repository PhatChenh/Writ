---
name: writ-work
description: Flip the Writ session mode to work -- arms full Process Keeper: test-first gate, design-doc/plan-exit gates, plan->test->code approval machine, verify-before-claim, violation-forced-continue.
---

Set the Writ workflow mode for the current session to **work** (arms the Work-gated blocking hooks + the plan->test->code gate machine), then report the helper's output line back to the user.

```bash
WR="${CLAUDE_PLUGIN_ROOT:-$(cat "${CLAUDE_PLUGIN_DATA:-$HOME/.cache/writ}/plugin-root" 2>/dev/null)}"
bash "$WR/bin/writ-mode-set.sh" work
```
