"""Stack-facet maps + predicate for the B29 post-retrieval filter.

Cross-project "bible" rules (e.g. Magento/PHP rules) were being injected into
unrelated repos (e.g. a Python project) because the retrieval scorer ranks the
shared corpus by semantic similarity with no hard language/framework gate.
The fix (B29) is a post-retrieval filter at `writ/server.py:query_rules` that
drops rules whose stack cannot match the active repo's detected language.
This module is the single source of truth for the stack derivation so the
filter and future callers share one map.

The facet is derived from TWO existing signals on every Rule node -- no schema
change, no reingest:
- `rule_id` prefix (first segment before `-`): `PHP`, `PY`, `FW`, `ARCH`, ...
- `domain` frontmatter field (freeform, e.g. `"PHP / Error Handling"`).

A rule with no derivable stack (architecture, security, testing, ...) is
universal and always passes. Project-local `PROJ-*` rules are always passed
(they are already scoped to the repo).

Stdlib only -- no external dependencies. Mirrors the prefix map already living
in `bin/lib/writ-session.py:478` so both paths agree.
"""

from __future__ import annotations

from typing import Any

# rule_id prefix -> stack string, OR None for cross-stack / universal prefixes.
# Stack-bearing prefixes pin a single language. None-valued prefixes are
# resolved via the `domain` field (e.g. FW -> framework, look at domain).
PREFIX_TO_STACK: dict[str, str | None] = {
    "PY": "python",
    "PHP": "php",
    "JS": "javascript",
    "TS": "typescript",
    "GO": "go",
    "RS": "rust",
    "JAVA": "java",
    "RB": "ruby",
    "FW": None,       # framework -- stack resolved via the domain field
    "DB": None,       # cross-stack
    "SQL": None,      # cross-stack
    "ARCH": None,     # universal
    "PERF": None,     # universal
    "TEST": None,     # universal
    "SEC": None,      # universal
    "ENF": None,      # universal
    "OPS": None,      # universal
    "API": None,      # universal
    "DOC": None,      # universal
    "SCAL": None,     # universal
    "CODE": None,     # universal
    "FRB": None,      # universal (forbidden-response)
    "PHA": None,      # universal (phase)
    "META": None,     # universal
    "PBK": None,      # universal (playbook)
    "CLEAN": None,    # universal
}

# Tokens in the freeform `domain` field that pin a stack. `magento` maps to
# `php` (Magento runs on PHP); add more framework->language implications here.
DOMAIN_KEYWORD_TO_STACK: dict[str, str] = {
    "php": "php",
    "python": "python",
    "javascript": "javascript",
    "typescript": "typescript",
    "js": "javascript",
    "ts": "typescript",
    "go": "go",
    "golang": "go",
    "rust": "rust",
    "java": "java",
    "ruby": "ruby",
    "magento": "php",
    "laravel": "php",
    "symfony": "php",
    "django": "python",
    "flask": "python",
    "fastapi": "python",
    "react": "javascript",
    "vue": "javascript",
    "angular": "typescript",
    "spring": "java",
    "rails": "ruby",
}


def _tokens(text: str) -> list[str]:
    import re

    return re.findall(r"[A-Za-z]+", text)


def rule_stacks(rule_id: str, domain: str | None) -> set[str]:
    """Derive the set of stacks a rule applies to from its rule_id prefix +
    domain field tokens. Empty set => universal (applies to any stack)."""
    stacks: set[str] = set()
    if rule_id:
        prefix = rule_id.split("-", 1)[0].upper()
        pstack = PREFIX_TO_STACK.get(prefix)
        if pstack:
            stacks.add(pstack)
    if domain:
        for tok in _tokens(domain):
            base = DOMAIN_KEYWORD_TO_STACK.get(tok.lower())
            if base:
                stacks.add(base)
    return stacks


def stack_allowed(rule: dict[str, Any], request_domain: str | None) -> bool:
    """Permissive post-retrieval predicate (B29).

    - PROJ-* (project-local): always pass (already scoped to the repo).
    - No request_domain / "universal": no filter (preserve current behavior).
    - Rule derives no stack (universal rule -- architecture/security/testing):
      always pass.
    - Otherwise: pass iff the request's stack is in the rule's stack set.
    """
    rid = rule.get("rule_id", "") or ""
    if rid.startswith("PROJ-"):
        return True
    if not request_domain:
        return True
    rd = request_domain.lower()
    if rd in ("", "universal"):
        return True
    stacks = rule_stacks(rid, rule.get("domain"))
    if not stacks:
        return True
    return rd in stacks


# The set of stack values the detector (writ-cwd-changed.sh) can produce. Used
# by `is_stack_domain` to decide whether /query should bypass the pipeline's
# Stage 1 strict-equality domain filter (which nukes the whole result set for
# a stack value like "python" because rule domains are freeform, e.g.
# "Python / Async"). For stack domains the post-retrieval `stack_allowed`
# filter is the gate instead; for non-stack domains (e.g. "Architecture") the
# pipeline's Stage 1 filter is left in charge so that contract is unchanged.
STACKS: frozenset[str] = frozenset(DOMAIN_KEYWORD_TO_STACK.values())


def is_stack_domain(domain: str | None) -> bool:
    """True if `domain` is a detected stack (python/php/...), not a freeform
    rule-domain like "Architecture" or "Security"."""
    return bool(domain) and domain.lower() in STACKS