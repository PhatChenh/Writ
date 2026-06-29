"""Tests for writ/shared/stacks.py -- B29 post-retrieval stack-facet filter.

Covers: prefix-only derivation, domain-only derivation, prefix+domain agreement,
Magento-implies-PHP, PROJ-* pass-through, universal pass-through, permissive
no-filter when request_domain is unknown/universal, and the deny cases that
motivated B29 (PHP/Magento rules dropped from a Python repo request).
"""

from __future__ import annotations

from writ.shared.stacks import is_stack_domain, rule_stacks, stack_allowed


class TestRuleStacks:
    def test_prefix_only_picks_stack(self) -> None:
        assert rule_stacks("PHP-TRY-001", None) == {"php"}
        assert rule_stacks("PY-ASYNC-001", None) == {"python"}
        assert rule_stacks("GO-001", None) == {"go"}

    def test_domain_only_picks_stack(self) -> None:
        # FW prefix is None (framework) -> stack comes from the domain field.
        assert rule_stacks("FW-M2-003", "Frameworks / Magento 2") == {"php"}
        assert rule_stacks("X-001", "Python / Async") == {"python"}

    def test_prefix_and_domain_agree(self) -> None:
        assert rule_stacks("PHP-ERR-001", "PHP / Error Handling") == {"php"}
        assert rule_stacks("PY-ASYNC-001", "Python / Async") == {"python"}

    def test_magento_implies_php(self) -> None:
        # Magento is a PHP framework -- the domain token `magento` maps to php.
        assert "php" in rule_stacks("FW-M2-001", "Frameworks / Magento 2")
        assert "python" not in rule_stacks("FW-M2-001", "Frameworks / Magento 2")

    def test_universal_rule_has_no_stack(self) -> None:
        # Architecture / security / testing rules derive no stack -> universal.
        assert rule_stacks("ARCH-ORG-001", "Architecture") == set()
        assert rule_stacks("SEC-UNI-003", "Security") == set()
        assert rule_stacks("TEST-REGRESSION-001", "Testing") == set()

    def test_empty_inputs_yield_empty(self) -> None:
        assert rule_stacks("", None) == set()
        assert rule_stacks("", "") == set()


class TestStackAllowed:
    def _rule(self, rule_id: str, domain: str | None = None) -> dict:
        r = {"rule_id": rule_id}
        if domain is not None:
            r["domain"] = domain
        return r

    def test_proj_rules_always_pass(self) -> None:
        assert stack_allowed(self._rule("PROJ-ARCH-001", "Architecture"), "python") is True
        assert stack_allowed(self._rule("PROJ-DB-001", "Database"), "php") is True

    def test_no_request_domain_no_filter(self) -> None:
        # Permissive: unknown stack -> do not filter (preserve current behavior).
        assert stack_allowed(self._rule("PHP-TRY-001", "PHP"), None) is True
        assert stack_allowed(self._rule("PHP-TRY-001", "PHP"), "") is True

    def test_universal_request_domain_no_filter(self) -> None:
        assert stack_allowed(self._rule("PHP-TRY-001", "PHP"), "universal") is True

    def test_universal_rule_passes_any_stack(self) -> None:
        assert stack_allowed(self._rule("ARCH-ORG-001", "Architecture"), "python") is True
        assert stack_allowed(self._rule("SEC-UNI-003", "Security"), "php") is True

    def test_off_stack_rule_dropped(self) -> None:
        # B29 core: PHP/Magento rules dropped from a Python repo request.
        assert stack_allowed(self._rule("PHP-TRY-001", "PHP / Error Handling"), "python") is False
        assert stack_allowed(self._rule("FW-M2-003", "Frameworks / Magento 2"), "python") is False
        assert stack_allowed(self._rule("ENF-SYS-006", "PHP state machine"), "python") is False

    def test_on_stack_rule_kept(self) -> None:
        assert stack_allowed(self._rule("PY-ASYNC-001", "Python / Async"), "python") is True
        assert stack_allowed(self._rule("PHP-TRY-001", "PHP / Error Handling"), "php") is True
        assert stack_allowed(self._rule("FW-M2-003", "Frameworks / Magento 2"), "php") is True

    def test_python_repo_keeps_proj_and_python_drops_php(self) -> None:
        # The exact B29 scenario from Iris (Python repo, PHP rules surfaced).
        rules = [
            self._rule("PROJ-GRAPH-002", "Graph"),
            self._rule("PY-ASYNC-001", "Python / Async"),
            self._rule("PHP-TRY-001", "PHP / Error Handling"),
            self._rule("FW-M2-003", "Frameworks / Magento 2"),
            self._rule("ARCH-ORG-001", "Architecture"),
        ]
        kept = [r["rule_id"] for r in rules if stack_allowed(r, "python")]
        assert kept == ["PROJ-GRAPH-002", "PY-ASYNC-001", "ARCH-ORG-001"]


class TestIsStackDomain:
    def test_detected_stacks_are_stack_domains(self) -> None:
        assert is_stack_domain("python") is True
        assert is_stack_domain("php") is True
        assert is_stack_domain("javascript") is True
        assert is_stack_domain("go") is True
        assert is_stack_domain("rust") is True

    def test_freeform_domains_are_not_stack_domains(self) -> None:
        # "Architecture" / "Security" are freeform rule domains, not detected
        # stacks -- /query keeps Stage 1 in charge for these.
        assert is_stack_domain("Architecture") is False
        assert is_stack_domain("Security") is False
        assert is_stack_domain("Testing") is False

    def test_universal_and_none_are_not_stack_domains(self) -> None:
        assert is_stack_domain("universal") is False
        assert is_stack_domain(None) is False
        assert is_stack_domain("") is False

    def test_case_insensitive(self) -> None:
        assert is_stack_domain("Python") is True
        assert is_stack_domain("PHP") is True