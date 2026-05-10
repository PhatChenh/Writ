"""writ audit-session <sid>: per-session timeline.

Closes the auditability gap with methodology' Skill-tool-call transcript
visibility. Methodology exposes "what skills the agent invoked" via
explicit Skill(X) tool calls in the transcript. Writ already has richer
event capture in workflow-friction.log, but no CLI surface to ask
"what happened in session X?" -- this command provides that view.

The contract:
- `writ audit-session <sid>` reads the friction log, filters to one
  session, and emits a structured summary: phase progression, mode,
  rule loads, gate denials, subagent dispatches, token consumption.
- `--json` for machine-readable output.
- Empty session id or no matching events: prints a clear "no events"
  message; exits 0 (idempotent CLI).
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

SKILL_DIR = "/home/lucio.saldivar/.claude/skills/writ"
SHIM = f"{SKILL_DIR}/bin/writ"


def _write_synthetic_log(path: Path, events: list[dict]) -> None:
    with path.open("w") as f:
        for e in events:
            f.write(json.dumps(e) + "\n")


def _events_for_session(sid: str) -> list[dict]:
    """A representative session with: mode change, rag queries, phase
    advances, gate denial, subagent dispatch, always-on inject."""
    return [
        {"ts": "2026-05-09T19:00:00Z", "session": sid, "mode": None,
         "event": "mode_change", "change_type": "set", "from_mode": None, "to_mode": "work"},
        {"ts": "2026-05-09T19:00:01Z", "session": sid, "mode": "work",
         "event": "always_on_inject", "tokens": 387, "rule_count": 5},
        {"ts": "2026-05-09T19:00:02Z", "session": sid, "mode": "work",
         "event": "rag_query", "query_source": "broad", "tokens_injected": 400,
         "rules_returned_count": 10, "rule_ids": ["ARCH-TYPE-001", "PY-PYDANTIC-001"]},
        {"ts": "2026-05-09T19:00:03Z", "session": sid, "mode": "work",
         "event": "rag_query", "query_source": "methodology", "tokens_injected": 600,
         "rules_returned_count": 4, "rule_ids": ["SKL-PROC-PLAN-001", "PBK-PROC-PLAN-001"]},
        {"ts": "2026-05-09T19:05:00Z", "session": sid, "mode": "work",
         "event": "phase_advance", "from_phase": "planning", "to_phase": "testing",
         "confirmation_source": "tool"},
        {"ts": "2026-05-09T19:08:00Z", "session": sid, "mode": "work",
         "event": "gate_denial", "rule_id": "ENF-PROC-TDD-001"},
        {"ts": "2026-05-09T19:10:00Z", "session": sid, "mode": "work",
         "event": "phase_advance", "from_phase": "testing", "to_phase": "implementation",
         "confirmation_source": "tool"},
        {"ts": "2026-05-09T19:12:00Z", "session": sid, "mode": "work",
         "event": "subagent_start", "subagent_type": "writ-implementer"},
        {"ts": "2026-05-09T19:14:00Z", "session": sid, "mode": "work",
         "event": "subagent_complete", "subagent_type": "writ-implementer"},
        {"ts": "2026-05-09T19:14:01Z", "session": sid, "mode": "work",
         "event": "playbook_step_complete",
         "playbook_id": "PBK-PROC-SDD-001", "step_id": "implementation",
         "step_index": 2, "total_steps": 3},
        # Noise from a different session -- must be filtered out.
        {"ts": "2026-05-09T19:01:00Z", "session": "OTHER-SESSION", "mode": "work",
         "event": "rag_query", "query_source": "broad", "tokens_injected": 100,
         "rules_returned_count": 1, "rule_ids": ["NOISE"]},
    ]


class TestAuditSessionCommand:
    """End-to-end: invoke `writ audit-session <sid> --log <path>` and
    assert the output contains the expected session-scoped fields."""

    def test_audit_session_emits_phase_progression(
        self, tmp_path: Path
    ) -> None:
        sid = "AUDIT-SID-1"
        log = tmp_path / "workflow-friction.log"
        _write_synthetic_log(log, _events_for_session(sid))

        result = subprocess.run(
            [SHIM, "audit-session", sid, "--log", str(log)],
            capture_output=True,
            text=True,
            timeout=15,
        )
        assert result.returncode == 0, result.stderr
        out = result.stdout
        # Phase progression must appear -- core of the audit view.
        assert "planning" in out and "testing" in out and "implementation" in out, (
            f"phase progression missing from output:\n{out[:1000]}"
        )

    def test_audit_session_filters_to_target_session(
        self, tmp_path: Path
    ) -> None:
        sid = "AUDIT-SID-2"
        log = tmp_path / "workflow-friction.log"
        _write_synthetic_log(log, _events_for_session(sid))

        result = subprocess.run(
            [SHIM, "audit-session", sid, "--log", str(log)],
            capture_output=True,
            text=True,
            timeout=15,
        )
        assert result.returncode == 0
        # Noise from OTHER-SESSION must NOT appear.
        assert "NOISE" not in result.stdout, (
            f"audit leaked events from other sessions:\n{result.stdout[:1000]}"
        )
        assert "OTHER-SESSION" not in result.stdout

    def test_audit_session_surfaces_skill_loads(
        self, tmp_path: Path
    ) -> None:
        sid = "AUDIT-SID-3"
        log = tmp_path / "workflow-friction.log"
        _write_synthetic_log(log, _events_for_session(sid))

        result = subprocess.run(
            [SHIM, "audit-session", sid, "--log", str(log)],
            capture_output=True,
            text=True,
            timeout=15,
        )
        assert result.returncode == 0
        assert "SKL-PROC-PLAN-001" in result.stdout, (
            f"SKL load not surfaced:\n{result.stdout[:1000]}"
        )

    def test_audit_session_surfaces_gate_denial(
        self, tmp_path: Path
    ) -> None:
        sid = "AUDIT-SID-4"
        log = tmp_path / "workflow-friction.log"
        _write_synthetic_log(log, _events_for_session(sid))

        result = subprocess.run(
            [SHIM, "audit-session", sid, "--log", str(log)],
            capture_output=True,
            text=True,
            timeout=15,
        )
        assert result.returncode == 0
        # Gate denial surfaces with the offending rule.
        assert "ENF-PROC-TDD-001" in result.stdout
        # Either "denial" or "denied" appears as a label.
        assert ("denial" in result.stdout.lower()
                or "denied" in result.stdout.lower()), (
            f"gate denial not labeled:\n{result.stdout[:1000]}"
        )

    def test_audit_session_no_events_exits_cleanly(
        self, tmp_path: Path
    ) -> None:
        log = tmp_path / "workflow-friction.log"
        _write_synthetic_log(log, _events_for_session("OTHER"))

        result = subprocess.run(
            [SHIM, "audit-session", "NONEXISTENT", "--log", str(log)],
            capture_output=True,
            text=True,
            timeout=15,
        )
        # Empty session = clean exit, not crash.
        assert result.returncode == 0, (
            f"empty audit crashed: stderr={result.stderr[:500]}"
        )
        # Output must indicate no events found, not silent.
        assert ("no events" in result.stdout.lower()
                or "empty" in result.stdout.lower()
                or "0 events" in result.stdout.lower()), (
            f"empty audit gave no signal:\n{result.stdout!r}"
        )

    def test_audit_session_json_output_is_parseable(
        self, tmp_path: Path
    ) -> None:
        sid = "AUDIT-SID-JSON"
        log = tmp_path / "workflow-friction.log"
        _write_synthetic_log(log, _events_for_session(sid))

        result = subprocess.run(
            [SHIM, "audit-session", sid, "--log", str(log), "--json"],
            capture_output=True,
            text=True,
            timeout=15,
        )
        assert result.returncode == 0, result.stderr
        # Must be parseable JSON.
        try:
            parsed = json.loads(result.stdout)
        except json.JSONDecodeError as e:
            pytest.fail(f"--json output not parseable: {e}\n{result.stdout[:500]}")
        # Top-level keys we expect: session, event_count, phase_transitions,
        # rule_loads, gate_denials.
        assert parsed.get("session") == sid
        assert "event_count" in parsed
        assert "phase_transitions" in parsed
