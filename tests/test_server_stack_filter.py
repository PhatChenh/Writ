"""B29 server-level integration: the /query endpoint drops cross-project bible
rules whose stack cannot match the active repo's detected language.

The filter lives at `writ.server.query_rules` (post-retrieval, so the
writ/retrieval/ pipeline is untouched). These tests mock the pipeline's
`query()` return value and assert the endpoint's response has the off-stack
rules removed. Permissive contract: no filter when domain is None/universal;
PROJ-* and universal rules always pass.
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

from fastapi.testclient import TestClient

from writ.server import app


def _rule(rule_id: str, domain: str | None, statement: str = "") -> dict:
    r = {"rule_id": rule_id, "statement": statement or rule_id}
    if domain is not None:
        r["domain"] = domain
    return r


# A representative mixed corpus: project-local, on-stack, off-stack (PHP/Magento),
# and universal (architecture). Mirrors the B29 Iris scenario.
MIXED = [
    _rule("PROJ-GRAPH-002", "Graph"),
    _rule("PY-ASYNC-001", "Python / Async"),
    _rule("PHP-TRY-001", "PHP / Error Handling"),
    _rule("FW-M2-003", "Frameworks / Magento 2"),
    _rule("ARCH-ORG-001", "Architecture"),
]


def _post(fake: MagicMock, body: dict) -> dict:
    with patch("writ.server._pipeline", fake):
        client = TestClient(app)
        r = client.post("/query", json=body)
    assert r.status_code == 200, r.text
    return r.json()


class TestQueryEndpointStackFilter:
    def test_python_domain_drops_off_stack_bible_rules(self) -> None:
        fake = MagicMock()
        fake.query.return_value = {"rules": list(MIXED), "mode": "semantic",
                                   "total_candidates": len(MIXED)}
        out = _post(fake, {"query": "build a python service", "domain": "python"})
        ids = [r["rule_id"] for r in out["rules"]]
        assert ids == ["PROJ-GRAPH-002", "PY-ASYNC-001", "ARCH-ORG-001"]
        # The off-stack PHP/Magento rules are dropped.
        assert "PHP-TRY-001" not in ids
        assert "FW-M2-003" not in ids

    def test_php_domain_keeps_php_and_magento_drops_python(self) -> None:
        fake = MagicMock()
        fake.query.return_value = {"rules": list(MIXED), "mode": "semantic",
                                   "total_candidates": len(MIXED)}
        out = _post(fake, {"query": "magento collect totals", "domain": "php"})
        ids = [r["rule_id"] for r in out["rules"]]
        # Magento implies php -> FW-M2-003 kept; PY-ASYNC-001 dropped.
        assert ids == ["PROJ-GRAPH-002", "PHP-TRY-001", "FW-M2-003", "ARCH-ORG-001"]
        assert "PY-ASYNC-001" not in ids

    def test_no_domain_keeps_everything(self) -> None:
        """Permissive: unknown stack -> no filter (preserve current behavior)."""
        fake = MagicMock()
        fake.query.return_value = {"rules": list(MIXED), "mode": "semantic",
                                   "total_candidates": len(MIXED)}
        out = _post(fake, {"query": "anything"})
        ids = [r["rule_id"] for r in out["rules"]]
        assert ids == [r["rule_id"] for r in MIXED]

    def test_universal_domain_keeps_everything(self) -> None:
        fake = MagicMock()
        fake.query.return_value = {"rules": list(MIXED), "mode": "semantic",
                                   "total_candidates": len(MIXED)}
        out = _post(fake, {"query": "anything", "domain": "universal"})
        ids = [r["rule_id"] for r in out["rules"]]
        assert ids == [r["rule_id"] for r in MIXED]

    def test_empty_rules_still_returns_cleanly(self) -> None:
        fake = MagicMock()
        fake.query.return_value = {"rules": [], "mode": "semantic", "total_candidates": 0}
        out = _post(fake, {"query": "x", "domain": "python"})
        assert out["rules"] == []

    def test_stack_domain_bypasses_stage1_and_post_filters(self) -> None:
        """For a stack domain, pipeline.query() receives domain=None (Stage 1
        would otherwise nuke the mixed set) and the post-filter trims off-stack
        rules."""
        fake = MagicMock()
        fake.query.return_value = {"rules": list(MIXED), "mode": "semantic",
                                   "total_candidates": len(MIXED)}
        out = _post(fake, {"query": "x", "domain": "python"})
        fake.query.assert_called_once()
        assert fake.query.call_args.kwargs.get("domain") is None
        ids = [r["rule_id"] for r in out["rules"]]
        assert "PHP-TRY-001" not in ids
        assert "FW-M2-003" not in ids
        assert "PY-ASYNC-001" in ids

    def test_universal_domain_passes_none_to_pipeline(self) -> None:
        """universal -> no Stage 1 filter (domain=None), no post-filter -> all kept."""
        fake = MagicMock()
        fake.query.return_value = {"rules": list(MIXED), "mode": "semantic",
                                   "total_candidates": len(MIXED)}
        out = _post(fake, {"query": "anything", "domain": "universal"})
        assert fake.query.call_args.kwargs.get("domain") is None
        assert [r["rule_id"] for r in out["rules"]] == [r["rule_id"] for r in MIXED]

    def test_freeform_domain_keeps_stage1_contract(self) -> None:
        """A non-stack freeform domain (e.g. "Architecture") is forwarded to the
        pipeline (Stage 1 equality filter) and NOT post-filtered -- unchanged
        contract for non-stack domain queries."""
        fake = MagicMock()
        fake.query.return_value = {"rules": list(MIXED), "mode": "semantic",
                                   "total_candidates": len(MIXED)}
        out = _post(fake, {"query": "x", "domain": "Architecture"})
        assert fake.query.call_args.kwargs.get("domain") == "Architecture"
        # No post-filter for non-stack domains -> mixed set returned as-is.
        assert [r["rule_id"] for r in out["rules"]] == [r["rule_id"] for r in MIXED]

    def test_rules_without_domain_enriched_from_pipeline_metadata(self) -> None:
        """The real pipeline serializes rules WITHOUT a `domain` field (only
        rule_id/statement/trigger/...). The endpoint enriches `domain` from
        `_pipeline._metadata[rid]["domain"]` before filtering, so FW-* rules
        whose stack comes only from the domain field (magento->php) are still
        dropped for a python request."""
        # Rules as the pipeline actually returns them: no `domain` key.
        bare = [
            {"rule_id": "FW-M2-003"},                      # magento -> php
            {"rule_id": "PHP-TRY-001"},                    # prefix php
            {"rule_id": "PY-ASYNC-001"},                   # prefix python
            {"rule_id": "ARCH-ORG-001"},                   # universal
        ]
        fake = MagicMock()
        fake.query.return_value = {"rules": [dict(r) for r in bare],
                                   "mode": "semantic", "total_candidates": 4}
        # _metadata carries the full rule dict (built from the graph fetch).
        fake._metadata = {
            "FW-M2-003": {"rule_id": "FW-M2-003", "domain": "Frameworks / Magento 2"},
            "PHP-TRY-001": {"rule_id": "PHP-TRY-001", "domain": "PHP / Error Handling"},
            "PY-ASYNC-001": {"rule_id": "PY-ASYNC-001", "domain": "Python / Async"},
            "ARCH-ORG-001": {"rule_id": "ARCH-ORG-001", "domain": "Architecture"},
        }
        out = _post(fake, {"query": "x", "domain": "python"})
        ids = [r["rule_id"] for r in out["rules"]]
        # FW-M2-003 (magento->php) is dropped even though its rule_id prefix is
        # FW (None) -- the enrichment supplies the domain so the filter fires.
        assert ids == ["PY-ASYNC-001", "ARCH-ORG-001"]
        assert "FW-M2-003" not in ids
        assert "PHP-TRY-001" not in ids