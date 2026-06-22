"""Phase 5: GET /dashboard server-rendered HTML route.

Verifies the route returns 200 + text/html, contains a section for
each documented metric, includes the meta-refresh tag, and renders
gracefully when the friction log is empty.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from writ.server import app

# Analyzers filter friction events against datetime.now(); a hardcoded date
# drifts out of the window over time. Rewrite the seeded "2026-04-30" date to
# one day back so the dashboard sees the events.
_RECENT_DAY = (datetime.now(timezone.utc) - timedelta(days=1)).strftime("%Y-%m-%d")


@pytest.fixture
def client() -> TestClient:
    return TestClient(app)


@pytest.fixture
def empty_log(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    p = tmp_path / "empty.log"
    p.write_text("")
    monkeypatch.setenv("WRIT_FRICTION_LOG", str(p))
    return p


@pytest.fixture
def synthetic_log(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    p = tmp_path / "synth.log"
    p.write_text(
        (
            '{"ts":"2026-04-30T12:00:00Z","session":"s1","mode":"work","event":"rag_query","rule_id":"ENF-X"}\n'
            '{"ts":"2026-04-30T12:00:01Z","session":"s1","mode":"work","event":"gate_denial","rule_id":"ENF-X","gate":"phase-a"}\n'
            '{"ts":"2026-04-30T12:00:05Z","session":"s1","mode":"work","event":"quality_judgment","judgment_id":"j1","rubric":"R1","decision":"fail","override":true,"latency_ms":120}\n'
        ).replace("2026-04-30", _RECENT_DAY)
    )
    monkeypatch.setenv("WRIT_FRICTION_LOG", str(p))
    return p


class TestDashboardResponse:
    def test_returns_200_html(self, client: TestClient, empty_log: Path) -> None:
        resp = client.get("/dashboard")
        assert resp.status_code == 200
        assert "text/html" in resp.headers.get("content-type", "")

    def test_meta_refresh_tag_present(self, client: TestClient, empty_log: Path) -> None:
        resp = client.get("/dashboard")
        body = resp.text.lower()
        assert "<meta" in body and "http-equiv" in body and "refresh" in body, (
            "Dashboard must auto-refresh via meta tag (no JS framework)"
        )

    def test_no_javascript_framework(self, client: TestClient, empty_log: Path) -> None:
        body = client.get("/dashboard").text.lower()
        # A bit of inline JS is tolerable; framework imports are not.
        for blacklisted in ("react", "vue.js", "angular", "<script src"):
            assert blacklisted not in body, (
                f"Dashboard must render without JS framework; found {blacklisted!r}"
            )


class TestDashboardSections:
    """Each Phase 5 metric gets a section heading on the page."""

    EXPECTED_SECTIONS = [
        "rule effectiveness",
        "skill usage",
        "playbook compliance",
        "graduation",
        "trim",
        "quality judge",
    ]

    @pytest.mark.parametrize("phrase", EXPECTED_SECTIONS)
    def test_section_present(self, phrase: str, client: TestClient, synthetic_log: Path) -> None:
        body = client.get("/dashboard").text.lower()
        assert phrase in body, f"Dashboard missing section: {phrase!r}"


class TestDashboardEmptyLog:
    def test_renders_when_log_is_empty(self, client: TestClient, empty_log: Path) -> None:
        resp = client.get("/dashboard")
        assert resp.status_code == 200
        assert resp.text.strip(), "Dashboard must render content even on empty log"

    def test_does_not_throw_on_missing_log(self, client: TestClient, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("WRIT_FRICTION_LOG", str(tmp_path / "does-not-exist.log"))
        resp = client.get("/dashboard")
        assert resp.status_code == 200, (
            "Dashboard must degrade gracefully when the configured log is absent"
        )


class TestDashboardUsesAnalyzers:
    """ARCH-SSOT-001: dashboard reads from analyzer functions, not raw events."""

    def test_recompute_signal_present_in_response(self, client: TestClient, synthetic_log: Path) -> None:
        """Indirect check: data that requires the analyzer's stuck-denial
        logic (e.g. ENF-X rule appearing on the rule-effectiveness panel
        only when the analyzer aggregates it) is rendered. If the
        dashboard recomputed inline with different math the row would
        not match the analyzer's output."""
        body = client.get("/dashboard").text
        # Synthetic log has one ENF-X gate_denial. The analyzer should
        # surface it on the rule-effectiveness panel.
        assert "ENF-X" in body
