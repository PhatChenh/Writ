"""Phase 5: analyzer functions in writ/analysis/friction.py.

Six analyzers, one TestClass each. Each class fixtures synthetic
FrictionEvent instances covering empty input, single-entity,
multi-session aggregation, and threshold edge cases. No mocks --
analyzers are pure functions on parsed events.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from writ.analysis.friction import (
    FrictionEvent,
    analyze_graduation_candidates,
    analyze_playbook_compliance,
    analyze_quality_judge_false_positives,
    analyze_rule_effectiveness,
    analyze_skill_usage,
    analyze_trim_candidates,
)


def _ev(event: str, ts: datetime, **fields) -> FrictionEvent:
    """Helper: build a FrictionEvent with defaults filled in."""
    return FrictionEvent(
        ts=ts.isoformat().replace("+00:00", "Z"),
        session=fields.pop("session", "test-session"),
        event=event,
        mode=fields.pop("mode", "work"),
        **fields,
    )


@pytest.fixture
def now() -> datetime:
    # Relative to the current time, not a hardcoded date: analyze_* filters
    # events by `since_days` against datetime.now(), so a fixed past date
    # silently drifts out of the window and every analyzer returns []. Anchor
    # one day back so the +minutes/+hours offsets in tests stay inside any
    # reasonable since_days window.
    return datetime.now(timezone.utc).replace(microsecond=0) - timedelta(days=1)


class TestRuleEffectiveness:
    """analyze_rule_effectiveness: stuck-denial rate per rule_id."""

    def test_empty_input_returns_empty_list(self) -> None:
        rows = analyze_rule_effectiveness([], since_days=30)
        assert rows == []

    def test_single_rule_with_stuck_denials_reports_full_rate(self, now: datetime) -> None:
        events = [
            _ev("rag_query", now, rule_id="ENF-X-001"),
            _ev("gate_denial", now + timedelta(seconds=5), rule_id="ENF-X-001"),
            _ev("rag_query", now + timedelta(minutes=10), rule_id="ENF-X-001"),
            _ev("gate_denial", now + timedelta(minutes=10, seconds=5), rule_id="ENF-X-001"),
        ]
        rows = analyze_rule_effectiveness(events, since_days=30)
        assert len(rows) == 1
        assert rows[0].rule_id == "ENF-X-001"
        assert rows[0].activations == 2
        assert rows[0].stuck_denials == 2
        assert rows[0].denial_stick_rate == pytest.approx(1.0)

    def test_approval_within_session_unsticks_denial(self, now: datetime) -> None:
        events = [
            _ev("rag_query", now, rule_id="ENF-X-001", session="s1"),
            _ev("gate_denial", now + timedelta(seconds=5), rule_id="ENF-X-001", session="s1"),
            _ev("approval_pattern_match", now + timedelta(minutes=2), rule_id="ENF-X-001", session="s1"),
        ]
        rows = analyze_rule_effectiveness(events, since_days=30)
        assert rows[0].stuck_denials == 0

    def test_filters_to_window(self, now: datetime) -> None:
        old = now - timedelta(days=60)
        events = [
            _ev("rag_query", old, rule_id="ENF-OLD-001"),
            _ev("gate_denial", old, rule_id="ENF-OLD-001"),
            _ev("rag_query", now, rule_id="ENF-NEW-001"),
        ]
        rows = analyze_rule_effectiveness(events, since_days=30)
        ids = {r.rule_id for r in rows}
        assert "ENF-OLD-001" not in ids
        assert "ENF-NEW-001" in ids

    def test_top_caps_returned_rows(self, now: datetime) -> None:
        events = []
        for i in range(20):
            events.append(_ev("rag_query", now, rule_id=f"R{i}"))
        rows = analyze_rule_effectiveness(events, since_days=30, top=5)
        assert len(rows) == 5

    def test_repeated_denial_counts_as_rationalization(self, now: datetime) -> None:
        events = [
            _ev("rag_query", now, rule_id="R1"),
            _ev("repeated_denial", now + timedelta(seconds=10), rule_id="R1"),
            _ev("repeated_denial", now + timedelta(seconds=20), rule_id="R1"),
        ]
        rows = analyze_rule_effectiveness(events, since_days=30)
        assert rows[0].rationalizations == 2


class TestSkillUsage:
    """analyze_skill_usage: skill loads vs playbook completion."""

    def test_empty_input_returns_empty_list(self) -> None:
        rows = analyze_skill_usage([], since_days=60)
        assert rows == []

    def test_skill_loaded_and_playbook_completed_counts_completion(self, now: datetime) -> None:
        events = [
            _ev("rag_query", now, skill_id="SKL-A", session="s1"),
            _ev("playbook_step_complete", now + timedelta(minutes=5), playbook_id="PBK-A", step_index=2, total_steps=2, session="s1"),
        ]
        rows = analyze_skill_usage(events, since_days=60)
        assert len(rows) == 1
        assert rows[0].skill_id == "SKL-A"
        assert rows[0].loads == 1
        assert rows[0].completions == 1

    def test_skill_loaded_without_completion_recorded(self, now: datetime) -> None:
        events = [_ev("rag_query", now, skill_id="SKL-A", session="s1")]
        rows = analyze_skill_usage(events, since_days=60)
        assert rows[0].completions == 0
        assert rows[0].completion_rate == pytest.approx(0.0)

    def test_skill_never_loaded_excluded(self, now: datetime) -> None:
        events = [_ev("rag_query", now, rule_id="ENF-X-001")]
        rows = analyze_skill_usage(events, since_days=60)
        assert rows == []


class TestPlaybookCompliance:
    """analyze_playbook_compliance: declared step sequence vs observed."""

    def test_empty_input_returns_empty_list(self) -> None:
        rows = analyze_playbook_compliance([], since_days=30)
        assert rows == []

    def test_complete_sequence_marked_compliant(self, now: datetime) -> None:
        events = [
            _ev("playbook_step_complete", now, playbook_id="PBK-X", step_id="s1", step_index=0, total_steps=3, session="ss"),
            _ev("playbook_step_complete", now + timedelta(seconds=10), playbook_id="PBK-X", step_id="s2", step_index=1, total_steps=3, session="ss"),
            _ev("playbook_step_complete", now + timedelta(seconds=20), playbook_id="PBK-X", step_id="s3", step_index=2, total_steps=3, session="ss"),
        ]
        rows = analyze_playbook_compliance(events, since_days=30)
        assert len(rows) == 1
        assert rows[0].playbook_id == "PBK-X"
        assert rows[0].runs == 1
        assert rows[0].compliant_runs == 1

    def test_missing_step_marks_non_compliant(self, now: datetime) -> None:
        events = [
            _ev("playbook_step_complete", now, playbook_id="PBK-X", step_id="s1", step_index=0, total_steps=3, session="ss"),
            _ev("playbook_step_complete", now + timedelta(seconds=10), playbook_id="PBK-X", step_id="s3", step_index=2, total_steps=3, session="ss"),
        ]
        rows = analyze_playbook_compliance(events, since_days=30)
        assert rows[0].compliant_runs == 0
        assert "s2" in rows[0].common_skip_points or rows[0].common_skip_points

    def test_out_of_order_step_marks_non_compliant(self, now: datetime) -> None:
        events = [
            _ev("playbook_step_complete", now, playbook_id="PBK-X", step_id="s2", step_index=1, total_steps=3, session="ss"),
            _ev("playbook_step_complete", now + timedelta(seconds=10), playbook_id="PBK-X", step_id="s1", step_index=0, total_steps=3, session="ss"),
        ]
        rows = analyze_playbook_compliance(events, since_days=30)
        assert rows[0].compliant_runs == 0

    def test_compliant_when_sequence_starts_at_one_and_reaches_last_index(self, now: datetime) -> None:
        events = [
            _ev("playbook_step_complete", now, playbook_id="PBK-X", step_id="testing", step_index=1, total_steps=4, session="ss"),
            _ev("playbook_step_complete", now + timedelta(seconds=10), playbook_id="PBK-X", step_id="implementation", step_index=2, total_steps=4, session="ss"),
            _ev("playbook_step_complete", now + timedelta(seconds=20), playbook_id="PBK-X", step_id="complete", step_index=3, total_steps=4, session="ss"),
        ]
        rows = analyze_playbook_compliance(events, since_days=30)
        assert len(rows) == 1
        assert rows[0].playbook_id == "PBK-X"
        assert rows[0].runs == 1
        assert rows[0].compliant_runs == 1

    def test_non_compliant_when_sequence_has_gap_starting_at_one(self, now: datetime) -> None:
        events = [
            _ev("playbook_step_complete", now, playbook_id="PBK-X", step_id="testing", step_index=1, total_steps=4, session="ss"),
            _ev("playbook_step_complete", now + timedelta(seconds=10), playbook_id="PBK-X", step_id="complete", step_index=3, total_steps=4, session="ss"),
        ]
        rows = analyze_playbook_compliance(events, since_days=30)
        assert len(rows) == 1
        assert rows[0].compliant_runs == 0


class TestGraduationCandidates:
    """analyze_graduation_candidates: stable-rule promotion candidates."""

    def test_empty_input_returns_empty_list(self) -> None:
        rows = analyze_graduation_candidates([])
        assert rows == []

    def test_stable_rule_with_high_stick_rate_is_candidate(self, now: datetime) -> None:
        events = []
        for i in range(20):
            events.append(_ev("rag_query", now - timedelta(days=40 - i), rule_id="ENF-STABLE", session=f"s{i}"))
        for i in range(18):
            events.append(_ev("gate_denial", now - timedelta(days=40 - i), rule_id="ENF-STABLE", session=f"s{i}"))
        rows = analyze_graduation_candidates(events)
        ids = {r.rule_id for r in rows}
        assert "ENF-STABLE" in ids

    def test_low_stick_rate_excludes_rule(self, now: datetime) -> None:
        events = []
        for i in range(20):
            events.append(_ev("rag_query", now - timedelta(days=40 - i), rule_id="ENF-WEAK", session=f"s{i}"))
            events.append(_ev("gate_denial", now - timedelta(days=40 - i), rule_id="ENF-WEAK", session=f"s{i}"))
            events.append(_ev("approval_pattern_match", now - timedelta(days=40 - i), rule_id="ENF-WEAK", session=f"s{i}"))
        rows = analyze_graduation_candidates(events)
        ids = {r.rule_id for r in rows}
        assert "ENF-WEAK" not in ids


class TestTrimCandidates:
    """analyze_trim_candidates: low-activation rules / skills."""

    def test_empty_input_returns_empty_list(self) -> None:
        rows = analyze_trim_candidates([], since_days=90)
        assert rows == []

    def test_rule_with_few_activations_in_window_is_candidate(self, now: datetime) -> None:
        events = [
            _ev("rag_query", now - timedelta(days=80), rule_id="ENF-DUSTY"),
            _ev("rag_query", now - timedelta(days=75), rule_id="ENF-DUSTY"),
        ]
        rows = analyze_trim_candidates(events, since_days=90)
        ids = {r.entity_id for r in rows}
        assert "ENF-DUSTY" in ids

    def test_active_rule_excluded(self, now: datetime) -> None:
        events = []
        for i in range(20):
            events.append(_ev("rag_query", now - timedelta(days=i), rule_id="ENF-ACTIVE"))
            events.append(_ev("gate_denial", now - timedelta(days=i), rule_id="ENF-ACTIVE"))
        rows = analyze_trim_candidates(events, since_days=90)
        ids = {r.entity_id for r in rows}
        assert "ENF-ACTIVE" not in ids

    def test_unused_skill_is_candidate(self, now: datetime) -> None:
        events = [
            _ev("rag_query", now - timedelta(days=80), skill_id="SKL-DUSTY"),
        ]
        rows = analyze_trim_candidates(events, since_days=60)
        ids = {r.entity_id for r in rows}
        assert "SKL-DUSTY" in ids


class TestQualityJudgeFalsePositives:
    """analyze_quality_judge_false_positives: rubric override rate."""

    def test_empty_input_returns_empty_list(self) -> None:
        rows = analyze_quality_judge_false_positives([], since_days=30)
        assert rows == []

    def test_no_fail_judgments_returns_empty_list(self, now: datetime) -> None:
        events = [
            _ev("quality_judgment", now, rubric="RUB-A", decision="pass", override=False),
        ]
        rows = analyze_quality_judge_false_positives(events, since_days=30)
        assert rows == []

    def test_fail_with_override_counts(self, now: datetime) -> None:
        events = [
            _ev("quality_judgment", now, rubric="RUB-A", decision="fail", override=True),
            _ev("quality_judgment", now + timedelta(minutes=1), rubric="RUB-A", decision="fail", override=False),
        ]
        rows = analyze_quality_judge_false_positives(events, since_days=30)
        row = next(r for r in rows if r.rubric == "RUB-A")
        assert row.total_fails == 2
        assert row.overrides == 1
        assert row.override_rate == pytest.approx(0.5)

    def test_high_override_rate_appears_first(self, now: datetime) -> None:
        events = [
            _ev("quality_judgment", now, rubric="LOW", decision="fail", override=False),
            _ev("quality_judgment", now, rubric="LOW", decision="fail", override=False),
            _ev("quality_judgment", now, rubric="LOW", decision="fail", override=True),
            _ev("quality_judgment", now, rubric="HIGH", decision="fail", override=True),
            _ev("quality_judgment", now, rubric="HIGH", decision="fail", override=True),
        ]
        rows = analyze_quality_judge_false_positives(events, since_days=30)
        assert rows[0].rubric == "HIGH"
