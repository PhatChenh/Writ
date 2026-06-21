"""Tests for hooks/scripts/session-start-bootstrap.sh (Phase C).

Verifies the SessionStart hook script exists, uses explicit CLAUDE_PLUGIN_ROOT
resolution (not dirname walk), probes the expected services, and exits 0 in
all branches (graceful degradation).
"""

from __future__ import annotations

import os
from pathlib import Path

import pytest

from tests.plugin.conftest import REPO_ROOT

SESSION_START_BOOTSTRAP = REPO_ROOT / "hooks" / "scripts" / "session-start-bootstrap.sh"


class TestSessionStartBootstrapExists:
    def test_session_start_bootstrap_script_exists(self) -> None:
        """hooks/scripts/session-start-bootstrap.sh must exist and be executable."""
        if not SESSION_START_BOOTSTRAP.exists():
            pytest.skip(
                "Phase C artifact hooks/scripts/session-start-bootstrap.sh not yet created"
            )
        assert SESSION_START_BOOTSTRAP.exists()
        assert os.access(SESSION_START_BOOTSTRAP, os.X_OK), (
            "hooks/scripts/session-start-bootstrap.sh must have the executable bit set"
        )


class TestSessionStartBootstrapContent:
    @pytest.fixture()
    def content(self) -> str:
        if not SESSION_START_BOOTSTRAP.exists():
            pytest.skip(
                "Phase C artifact hooks/scripts/session-start-bootstrap.sh not yet created"
            )
        return SESSION_START_BOOTSTRAP.read_text()

    def test_session_start_uses_explicit_plugin_root(self, content: str) -> None:
        """Script must set WRIT_DIR from ${CLAUDE_PLUGIN_ROOT}, not from dirname walk.

        The script lives at hooks/scripts/ (two levels deep), so a dirname walk
        would resolve to hooks/scripts rather than the repo root.
        """
        assert 'WRIT_DIR="${CLAUDE_PLUGIN_ROOT}"' in content or \
               "WRIT_DIR=${CLAUDE_PLUGIN_ROOT}" in content, (
            "session-start-bootstrap.sh must set WRIT_DIR from ${CLAUDE_PLUGIN_ROOT} explicitly"
        )
        # Should NOT use dirname-based resolution for WRIT_DIR
        assert 'dirname "$0"' not in content or "WRIT_DIR" not in content.split('dirname "$0"')[0].split('\n')[-1], (
            "session-start-bootstrap.sh must not use dirname walk to resolve WRIT_DIR"
        )

    def test_session_start_probes_venv(self, content: str) -> None:
        """Script must check for ${CLAUDE_PLUGIN_DATA:-$HOME/.cache/writ}/.venv/bin/python3."""
        assert "${CLAUDE_PLUGIN_DATA:-$HOME/.cache/writ}/.venv" in content, (
            "session-start-bootstrap.sh must probe ${CLAUDE_PLUGIN_DATA:-$HOME/.cache/writ}/.venv"
        )
        assert "python3" in content, (
            "session-start-bootstrap.sh venv probe must check for python3 binary"
        )

    def test_session_start_no_neo4j_probe(self, content: str) -> None:
        """Script must NOT contain a TCP probe for Neo4j bolt port 7687 —
        FalkorDBLite is embedded, no separate bolt port to probe."""
        assert "7687" not in content, (
            "session-start-bootstrap.sh must NOT probe Neo4j bolt port 7687 "
            "(FalkorDBLite is embedded)"
        )
        assert "/dev/tcp/" not in content, (
            "session-start-bootstrap.sh must NOT contain /dev/tcp/ probe "
            "(no external DB to probe)"
        )

    def test_session_start_probes_server_health(self, content: str) -> None:
        """Script must probe http://localhost:8765/health."""
        assert "localhost:8765/health" in content or "8765/health" in content, (
            "session-start-bootstrap.sh must probe http://localhost:8765/health"
        )

    def test_session_start_graceful_degradation(self, content: str) -> None:
        """Script must exit 0 in all branches; must not exit 1 for missing venv."""
        lines = content.splitlines()
        hard_exits = [
            line.strip() for line in lines
            if line.strip().startswith("exit 1")
        ]
        assert not hard_exits, (
            "session-start-bootstrap.sh must not call 'exit 1' — all degradation paths "
            f"must exit 0. Found: {hard_exits}"
        )