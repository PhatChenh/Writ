"""Phase 4: writ analyze-friction CLI + writ/analysis/friction.py parser.

Reads workflow-friction.log (JSONL), parses into FrictionEvent Pydantic
models, aggregates by rule / event / mode. Used after manual pressure
runs to turn log deltas into per-rule compliance metrics.

Pure file I/O; no graph DB, no LLM.
"""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

WRIT_ROOT = Path(__file__).resolve().parent.parent


class TestFrictionEventModel:
    """FrictionEvent Pydantic model validates log rows."""

    def test_model_accepts_canonical_row(self) -> None:
        from writ.analysis.friction import FrictionEvent
        row = {
            "ts": "2026-04-22T12:00:00Z",
            "session": "abc-123",
            "mode": "work",
            "event": "approval_pattern_match",
        }
        fe = FrictionEvent.model_validate(row)
        assert fe.event == "approval_pattern_match"
        assert fe.mode == "work"

    def test_model_accepts_minimal_row(self) -> None:
        """Older rows may lack mode; the parser permits None."""
        from writ.analysis.friction import FrictionEvent
        row = {"ts": "2026-04-22T12:00:00Z", "session": "x", "event": "rag_query"}
        fe = FrictionEvent.model_validate(row)
        assert fe.mode is None

    def test_model_captures_extra_fields(self) -> None:
        """Rule ID, gate name, rationalization text -- optional extras."""
        from writ.analysis.friction import FrictionEvent
        row = {
            "ts": "2026-04-22T12:00:00Z",
            "session": "x",
            "event": "gate_deny",
            "rule_id": "ENF-PROC-VERIFY-001",
            "gate": "phase-a",
        }
        fe = FrictionEvent.model_validate(row)
        assert fe.rule_id == "ENF-PROC-VERIFY-001"
        assert fe.gate == "phase-a"


class TestParseLogFile:
    """parse_log reads a JSONL file into a list[FrictionEvent]."""

    def test_parses_valid_jsonl(self, tmp_path: Path) -> None:
        from writ.analysis.friction import parse_log
        log = tmp_path / "friction.log"
        log.write_text(
            json.dumps({"ts": "t1", "session": "s", "event": "e1"}) + "\n"
            + json.dumps({"ts": "t2", "session": "s", "event": "e2"}) + "\n"
        )
        events = parse_log(log)
        assert len(events) == 2
        assert events[0].event == "e1"
        assert events[1].event == "e2"

    def test_skips_malformed_lines(self, tmp_path: Path) -> None:
        """Malformed lines are skipped; does not abort the whole parse."""
        from writ.analysis.friction import parse_log
        log = tmp_path / "friction.log"
        log.write_text(
            json.dumps({"ts": "t1", "session": "s", "event": "ok"}) + "\n"
            + "not-json\n"
            + json.dumps({"ts": "t2", "session": "s", "event": "ok2"}) + "\n"
        )
        events = parse_log(log)
        assert len(events) == 2

    def test_missing_file_returns_empty(self, tmp_path: Path) -> None:
        from writ.analysis.friction import parse_log
        events = parse_log(tmp_path / "does-not-exist.log")
        assert events == []


class TestAggregateByRule:
    """aggregate_by_rule counts events per rule_id."""

    def test_counts_each_rule(self) -> None:
        from writ.analysis.friction import FrictionEvent, aggregate_by_rule
        events = [
            FrictionEvent(ts="t", session="s", event="gate_deny", rule_id="R1"),
            FrictionEvent(ts="t", session="s", event="gate_deny", rule_id="R1"),
            FrictionEvent(ts="t", session="s", event="gate_deny", rule_id="R2"),
        ]
        agg = aggregate_by_rule(events)
        assert agg["R1"] == 2
        assert agg["R2"] == 1

    def test_ignores_events_without_rule_id(self) -> None:
        from writ.analysis.friction import FrictionEvent, aggregate_by_rule
        events = [
            FrictionEvent(ts="t", session="s", event="rag_query"),  # no rule_id
            FrictionEvent(ts="t", session="s", event="gate_deny", rule_id="R1"),
        ]
        agg = aggregate_by_rule(events)
        assert agg == {"R1": 1}


class TestAggregateByEvent:
    """aggregate_by_event counts events per event name."""

    def test_counts_each_event(self) -> None:
        from writ.analysis.friction import FrictionEvent, aggregate_by_event
        events = [
            FrictionEvent(ts="t", session="s", event="approval_pattern_match"),
            FrictionEvent(ts="t", session="s", event="approval_pattern_match"),
            FrictionEvent(ts="t", session="s", event="gate_deny"),
        ]
        agg = aggregate_by_event(events)
        assert agg["approval_pattern_match"] == 2
        assert agg["gate_deny"] == 1


class TestAnalyzeFrictionCLI:
    """`writ analyze-friction` wraps the parser/aggregator."""

    def test_cli_help(self) -> None:
        proc = subprocess.run(
            [".venv/bin/writ", "analyze-friction", "--help"],
            capture_output=True, text=True, cwd=str(WRIT_ROOT),
        )
        if proc.returncode != 0 and "No module" in proc.stderr:
            pytest.skip("writ CLI not installed in venv")
        assert proc.returncode == 0
        assert "analyze-friction" in (proc.stdout + proc.stderr).lower()

    def test_cli_json_output_shape(self, tmp_path: Path) -> None:
        """--json emits {'by_rule': {...}, 'by_event': {...}, 'total': N}."""
        log = tmp_path / "workflow-friction.log"
        log.write_text(
            json.dumps({"ts": "t", "session": "s", "event": "gate_deny",
                        "rule_id": "R1"}) + "\n"
        )
        proc = subprocess.run(
            [".venv/bin/writ", "analyze-friction", "--json",
             "--log", str(log)],
            capture_output=True, text=True, cwd=str(WRIT_ROOT),
        )
        if proc.returncode != 0 and "No module" in proc.stderr:
            pytest.skip("writ CLI not installed")
        assert proc.returncode == 0
        data = json.loads(proc.stdout)
        assert "by_rule" in data
        assert "by_event" in data
        assert "total" in data
        assert data["total"] == 1
        assert data["by_rule"]["R1"] == 1

    def test_cli_text_output_mentions_counts(self, tmp_path: Path) -> None:
        """Default text output includes per-rule table headers."""
        log = tmp_path / "workflow-friction.log"
        log.write_text(
            json.dumps({"ts": "t", "session": "s", "event": "gate_deny",
                        "rule_id": "ENF-PROC-VERIFY-001"}) + "\n"
        )
        proc = subprocess.run(
            [".venv/bin/writ", "analyze-friction", "--log", str(log)],
            capture_output=True, text=True, cwd=str(WRIT_ROOT),
        )
        if proc.returncode != 0 and "No module" in proc.stderr:
            pytest.skip("writ CLI not installed")
        assert proc.returncode == 0
        assert "ENF-PROC-VERIFY-001" in proc.stdout


class TestRuleFilter:
    """`--rule ID` narrows output to one rule."""

    def test_filter_by_rule(self, tmp_path: Path) -> None:
        log = tmp_path / "workflow-friction.log"
        log.write_text(
            json.dumps({"ts": "t", "session": "s", "event": "gate_deny",
                        "rule_id": "R1"}) + "\n"
            + json.dumps({"ts": "t", "session": "s", "event": "gate_deny",
                          "rule_id": "R2"}) + "\n"
        )
        proc = subprocess.run(
            [".venv/bin/writ", "analyze-friction", "--json",
             "--log", str(log), "--rule", "R1"],
            capture_output=True, text=True, cwd=str(WRIT_ROOT),
        )
        if proc.returncode != 0 and "No module" in proc.stderr:
            pytest.skip("writ CLI not installed")
        assert proc.returncode == 0
        data = json.loads(proc.stdout)
        assert data["total"] == 1
        assert data["by_rule"] == {"R1": 1}
