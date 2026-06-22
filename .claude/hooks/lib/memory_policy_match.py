#!/usr/bin/env python3
"""Memory-policy rule-weakening matcher (extracted from writ-memory-policy-guard.sh).

Reads the candidate memory content from the WG_CONTENT env var and prints a JSON
object: {"override": "yes"|"no", "matched": [<phrase>, ...]}.

Extracted into a standalone file so the hook contains NO inline Python heredocs.
macOS ships bash 3.2, which mis-parses certain heredoc/command-substitution +
embedded-quote combinations (the multiline regex patterns below triggered a
`bash -n` / runtime parse failure on the deny path). A plain `python3 <file>`
call sidesteps bash parsing entirely.
"""

from __future__ import annotations

import json
import os
import re

OVERRIDE_PATTERNS = (
    r'explicit_rule_override\s*:\s*true',
    r'override\s+authorized\s+by\s*:',
)

# Rule-weakening phrases (case-insensitive). Any match -> deny. False positives
# can be escaped via an explicit override marker (see OVERRIDE_PATTERNS).
WEAKENING_PATTERNS = (
    # Skip / no verification variants
    r'\bskip\s+(?:the\s+)?(?:verification|verify|test\s+run|tests?|check|checks|validation|validate)\b',
    r'\bno\s+(?:verification|verify|re-?run|re-?runs?|fresh\s+verification)\b',
    r'\bnever\s+(?:re-?run|verify|test)\b',
    r'\bdon\'?t\s+(?:re-?run|verify|re-?verify)\b',
    # Face-value / trust-as-bypass
    r'take\s+(?:the\s+)?[\w\s\-]{0,40}?(?:report|claim|output|result|answer)\s+at\s+face\s+value',
    r'\btrust\s+[\w\s\-]{0,20}?(?:source|sub-?agent|implementer|worker|report)\s*=\s*(?:no|skip|never|face)',
    # Rule-override / bypass language outside an authorized marker
    r'\b(?:override|bypass|weaken|suspend|disable)\s+[\w\s\-]{0,20}?(?:ENF-|rule|verify|discipline|verification)',
    # PSR-003 exact phrasing
    r'["\']?i\s+trust\s+you["\']?[^\n]{0,120}(?:skip|no|never|face\s+value|move\s+on)',
    r'take\s+[\w\s\-]{0,40}?\s+at\s+face\s+value\s+and\s+move\s+on',
)


def main() -> None:
    content = os.environ.get("WG_CONTENT", "")

    override = any(
        re.search(p, content, re.IGNORECASE) for p in OVERRIDE_PATTERNS
    )

    matched: list[str] = []
    for p in WEAKENING_PATTERNS:
        m = re.search(p, content, re.IGNORECASE)
        if m:
            matched.append(m.group(0)[:80])

    print(json.dumps({"override": "yes" if override else "no", "matched": matched}))


if __name__ == "__main__":
    main()
