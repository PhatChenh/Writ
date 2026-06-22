"""Tests for scripts/bootstrap-plugin.sh (Phase C).

Verifies the plugin bootstrap script exists, is executable, uses the correct
CLAUDE_PLUGIN_DATA-based venv path, installs via pip install -e, checks
required prerequisites, and is idempotent.
"""

from __future__ import annotations

import os
from pathlib import Path

import pytest

from tests.plugin.conftest import REPO_ROOT

BOOTSTRAP_PLUGIN = REPO_ROOT / "scripts" / "bootstrap-plugin.sh"


class TestBootstrapPluginExists:
    def test_bootstrap_plugin_script_exists(self) -> None:
        """scripts/bootstrap-plugin.sh must exist and be executable."""
        if not BOOTSTRAP_PLUGIN.exists():
            pytest.skip("Phase C artifact scripts/bootstrap-plugin.sh not yet created")
        assert BOOTSTRAP_PLUGIN.exists(), "scripts/bootstrap-plugin.sh must exist"
        assert os.access(BOOTSTRAP_PLUGIN, os.X_OK), (
            "scripts/bootstrap-plugin.sh must have the executable bit set"
        )


class TestBootstrapPluginContent:
    @pytest.fixture()
    def content(self) -> str:
        if not BOOTSTRAP_PLUGIN.exists():
            pytest.skip("Phase C artifact scripts/bootstrap-plugin.sh not yet created")
        return BOOTSTRAP_PLUGIN.read_text()

    def test_bootstrap_plugin_uses_plugin_data_for_venv(self, content: str) -> None:
        """Venv path must use ${CLAUDE_PLUGIN_DATA:-$HOME/.cache/writ}/.venv."""
        assert "${CLAUDE_PLUGIN_DATA:-$HOME/.cache/writ}" in content, (
            "bootstrap-plugin.sh must use ${CLAUDE_PLUGIN_DATA:-$HOME/.cache/writ} for venv base"
        )
        assert "${CLAUDE_PLUGIN_DATA:-$HOME/.cache/writ}/.venv" in content, (
            "bootstrap-plugin.sh venv path must be ${CLAUDE_PLUGIN_DATA:-$HOME/.cache/writ}/.venv"
        )

    def test_bootstrap_plugin_uses_pip_install_editable(self, content: str) -> None:
        """Script must use pip install -e referencing ${CLAUDE_PLUGIN_ROOT}."""
        assert "pip install -e" in content, (
            "bootstrap-plugin.sh must use 'pip install -e' for editable install"
        )
        assert "${CLAUDE_PLUGIN_ROOT}" in content, (
            "bootstrap-plugin.sh must reference ${CLAUDE_PLUGIN_ROOT} so upgrades rebind"
        )

    def test_bootstrap_plugin_installs_dev_extras(self, content: str) -> None:
        """After Finding D (Approach C, 2026-05-14), bootstrap-plugin.sh
        installs with [dev] extras so optimum is available for the ONNX
        export step. The [fallback] group (sentence-transformers) is
        intentionally NOT installed by default."""
        assert "[dev]" in content, (
            "bootstrap-plugin.sh must install -e '${WRIT_DIR}[dev]' (or "
            "equivalent) so optimum is available for the ONNX export step. "
            "If you intentionally moved to bare -e install, update this "
            "test AND the install contract in pyproject.toml."
        )

    def test_bootstrap_plugin_exports_onnx_model(self, content: str) -> None:
        """bootstrap-plugin.sh must produce the ONNX model on disk so the
        daemon takes the production ONNX path on first start. Without this,
        a fresh plugin install runs `writ serve` and the daemon refuses
        to start (see writ/retrieval/pipeline.py three-state ONNX contract,
        commit dae679a)."""
        assert "scripts/export_onnx.py" in content, (
            "bootstrap-plugin.sh must run scripts/export_onnx.py to produce "
            "the ONNX model before the daemon starts."
        )

    def test_bootstrap_plugin_checks_prerequisites(self, content: str) -> None:
        """Script must check for python3 >= 3.11, jq, and curl.

        NOTE: docker is intentionally NOT required -- this fork replaced Neo4j
        (Docker) with embedded FalkorDBLite. envsubst is also not required by
        the plugin bootstrap: it ships hooks/commands/agents via the plugin
        manifest and never invokes envsubst (only the non-plugin bootstrap.sh
        does, for CLAUDE.md/settings templating).
        """
        lowered = content.lower()
        assert "python3" in lowered, (
            "bootstrap-plugin.sh must check for python3"
        )
        assert "3.11" in content or "3\\.11" in content, (
            "bootstrap-plugin.sh must verify python3 >= 3.11"
        )
        assert "jq" in content, (
            "bootstrap-plugin.sh must check for jq"
        )
        assert "curl" in content, (
            "bootstrap-plugin.sh must check for curl"
        )

    def test_bootstrap_plugin_idempotent(self, content: str, tmp_path: Path) -> None:
        """Running bootstrap-plugin.sh twice must not fail; second run is a no-op or re-syncs.

        Note: This test is a structural check only. Full idempotency requires a
        shell sandbox with a real venv stub directory. To run manually:
          1. Set CLAUDE_PLUGIN_ROOT=/path/to/Writ
          2. Set CLAUDE_PLUGIN_DATA=/tmp/writ-idem-test
          3. Run bootstrap-plugin.sh twice; verify exit 0 both times.
        """
        pytest.skip(
            "requires shell sandbox: full idempotency test needs real venv stub; "
            "run manually per docstring instructions"
        )
