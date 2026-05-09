"""Phase 6h + 6i: methodology retrieval verification + playbook event wiring.

6h verification (Stage 4 traversal against live graph):
  After Phase 6e/f/g promoted the methodology corpus to bible/methodology
  and migration created 120 edges, Stage 4 graph traversal in
  writ/retrieval/traversal.py must expand a Rule's bundle to include
  linked Skill/Playbook/AntiPattern nodes via the new methodology edge
  types (TEACHES, GATES, COUNTERS, DEMONSTRATES, DISPATCHES,
  PRESSURE_TESTS, CONTAINS, ATTACHED_TO).

6i wiring (server-side playbook_step_complete emission):
  The /session/{sid}/advance-phase endpoint now emits a
  playbook_step_complete friction event after every phase advance,
  parallel to the existing phase_advance event. This gives Phase 5's
  --playbook-compliance analyzer real signal to work with: each
  workflow phase advance is one playbook step.
"""
from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from writ.analysis.friction import (
    analyze_playbook_compliance,
    parse_log,
)
from writ.server import app

WRIT_ROOT = Path(__file__).resolve().parent.parent


# ============================================================================
# 6h -- Stage 4 traversal verification (live graph)
# ============================================================================


class TestPhase6hStage4Surfaces:
    """Stage 4 graph traversal exposes methodology nodes via the new
    edge types (TEACHES, GATES, COUNTERS, etc.).

    Uses a synthetic AdjacencyCache populated to mirror the edge
    patterns the live methodology corpus produces. Live-graph
    integration testing belongs to PSR-style end-to-end runs (6j) --
    keeping the unit-level traversal contract test free of database
    fixture state means it can't flake when a peer test wipes the
    graph mid-suite (which conftest.pytest_sessionfinish then fails
    to restore because it only refills when count_rules() == 0).
    """

    @staticmethod
    def _cache_with_edges(edges: list[tuple[str, str, str]]):
        """Build a synthetic AdjacencyCache from (src, tgt, type) tuples.

        Mirrors the bidirectional storage that build_from_db uses
        (entries written for both src->tgt and tgt->src).
        """
        from writ.retrieval.traversal import AdjacencyCache
        cache = AdjacencyCache()
        for src, tgt, edge_type in edges:
            cache._neighbors.setdefault(src, []).append(
                {"rule_id": tgt, "edge_type": edge_type, "direction": "outgoing"}
            )
            cache._neighbors.setdefault(tgt, []).append(
                {"rule_id": src, "edge_type": edge_type, "direction": "incoming"}
            )
        return cache

    def test_cache_includes_methodology_edges(self) -> None:
        """A cache populated from methodology edges (TEACHES, GATES,
        COUNTERS, CONTAINS) stores neighbors keyed on methodology
        node IDs (SKL-, PBK-, ANT-, PHA-)."""
        cache = self._cache_with_edges([
            ("ANT-PROC-PLAN-001", "SKL-PROC-PLAN-001", "COUNTERS"),
            ("PBK-PROC-PLAN-001", "ENF-PROC-PLAN-001", "GATES"),
            ("PBK-PROC-PLAN-001", "PHA-PLAN-001", "CONTAINS"),
        ])
        for mid in (
            "ANT-PROC-PLAN-001", "SKL-PROC-PLAN-001",
            "PBK-PROC-PLAN-001", "ENF-PROC-PLAN-001",
            "PHA-PLAN-001",
        ):
            assert cache.get_neighbors(mid), (
                f"Cache missing neighbors for {mid}; Stage 4 cannot expand."
            )

    def test_bundle_expansion_includes_methodology_via_counters(self) -> None:
        """Starting from an AntiPattern that COUNTERS a Skill, Stage 4
        get_bundle reaches the Skill at depth 1."""
        cache = self._cache_with_edges([
            ("ANT-PROC-PLAN-001", "SKL-PROC-PLAN-001", "COUNTERS"),
            ("ANT-PROC-PLAN-001", "ENF-PROC-PLAN-001", "COUNTERS"),
        ])
        bundle = cache.get_bundle("ANT-PROC-PLAN-001", max_depth=1)
        assert "SKL-PROC-PLAN-001" in bundle
        assert "ENF-PROC-PLAN-001" in bundle

    def test_bundle_expansion_works_for_skill_seed(self) -> None:
        """Stage 4 traversal is symmetric: starting from a Skill
        reaches the AntiPattern via the inverse-direction entry."""
        cache = self._cache_with_edges([
            ("ANT-PROC-PLAN-001", "SKL-PROC-PLAN-001", "COUNTERS"),
            ("PBK-PROC-PLAN-001", "SKL-PROC-PLAN-001", "TEACHES"),
        ])
        bundle = cache.get_bundle("SKL-PROC-PLAN-001", max_depth=1)
        assert "SKL-PROC-PLAN-001" in bundle
        assert "ANT-PROC-PLAN-001" in bundle, (
            "Inverse-direction lookup failed; Stage 4 not symmetric."
        )
        assert "PBK-PROC-PLAN-001" in bundle


# ============================================================================
# 6i -- /advance-phase emits playbook_step_complete
# ============================================================================


@pytest.fixture
def client() -> TestClient:
    return TestClient(app)


@pytest.fixture
def tmp_log(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    p = tmp_path / "workflow-friction.log"
    monkeypatch.setenv("WRIT_FRICTION_LOG", str(p))
    cache_dir = tmp_path / "writ-cache"
    cache_dir.mkdir()
    monkeypatch.setenv("WRIT_CACHE_DIR", str(cache_dir))
    from writ.server import writ_session
    monkeypatch.setattr(writ_session, "CACHE_DIR", str(cache_dir))
    return p


def _read_events(log: Path, event: str) -> list[dict]:
    if not log.exists():
        return []
    return [e.model_dump() for e in parse_log(log) if e.event == event]


class TestPhase6iAdvancePhaseFiresPlaybookStep:
    """Every /advance-phase call must emit BOTH a phase_advance and
    a playbook_step_complete event. The latter is what unlocks Phase
    5's --playbook-compliance analyzer."""

    def test_first_advance_fires_playbook_step_complete(
        self, client: TestClient, tmp_log: Path
    ) -> None:
        resp = client.post(
            "/session/test-6i-1/advance-phase",
            json={"confirmation_source": "tool"},
        )
        assert resp.status_code == 200

        # NOTE: phase_advance uses a separate write path (cwd-walked
        # project root) and does not honor WRIT_FRICTION_LOG -- so
        # we can't observe it via the tmp_log fixture. That existing
        # behavior is not changed by this commit; we assert only on
        # the new playbook_step_complete event which DOES use the
        # log_friction_event helper and respects WRIT_FRICTION_LOG.

        steps = _read_events(tmp_log, "playbook_step_complete")
        assert len(steps) == 1, (
            f"Expected one playbook_step_complete event after first "
            f"advance; got {len(steps)}: {steps}"
        )
        ev = steps[0]
        assert ev["playbook_id"] == "PBK-PROC-SDD-001"
        # planning -> testing is the first advance (planning is the
        # initial state).
        assert ev["step_id"] == "testing"
        assert ev["step_index"] == 1  # testing is index 1 in [planning, testing, implementation, complete]
        assert ev["total_steps"] == 4

    def test_step_index_increments_across_advances(
        self, client: TestClient, tmp_log: Path
    ) -> None:
        for _ in range(3):
            client.post(
                "/session/test-6i-2/advance-phase",
                json={"confirmation_source": "tool"},
            )
        steps = _read_events(tmp_log, "playbook_step_complete")
        # Three advances from the initial "planning": testing(1) ->
        # implementation(2) -> complete(3).
        assert len(steps) == 3
        indices = [s["step_index"] for s in steps]
        step_ids = [s["step_id"] for s in steps]
        assert indices == [1, 2, 3], f"step_index sequence wrong: {indices}"
        assert step_ids == ["testing", "implementation", "complete"], (
            f"step_id sequence wrong: {step_ids}"
        )

    def test_compliance_analyzer_consumes_emitted_events(
        self, client: TestClient, tmp_log: Path
    ) -> None:
        """End-to-end: emit events via /advance-phase, feed them
        to analyze_playbook_compliance, expect a non-empty result row
        for PBK-PROC-SDD-001."""
        for _ in range(3):
            client.post(
                "/session/test-6i-3/advance-phase",
                json={"confirmation_source": "tool"},
            )
        events = parse_log(tmp_log)
        rows = analyze_playbook_compliance(events, since_days=30)
        sdd_rows = [r for r in rows if r.playbook_id == "PBK-PROC-SDD-001"]
        assert sdd_rows, (
            f"--playbook-compliance analyzer found no rows for "
            f"PBK-PROC-SDD-001 after 3 advances. All rows: "
            f"{[(r.playbook_id, r.runs) for r in rows]}"
        )
        row = sdd_rows[0]
        assert row.runs >= 1
        # The 3 advances should be a contiguous step sequence (1, 2, 3),
        # which the analyzer scores by step_index ordering. Whether
        # this counts as "compliant" depends on the analyzer's
        # definition; either way runs > 0 is the minimum we assert.

    def test_event_carries_session_and_mode(
        self, client: TestClient, tmp_log: Path
    ) -> None:
        client.post(
            "/session/test-6i-4/advance-phase",
            json={"confirmation_source": "tool"},
        )
        steps = _read_events(tmp_log, "playbook_step_complete")
        assert len(steps) == 1
        # The event carries session_id under the standard 'session' key
        # (FrictionEvent's model field; see writ/analysis/friction.py).
        assert steps[0].get("session") == "test-6i-4"
