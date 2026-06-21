"""Fresh-install smoke test for the full plugin distribution pipeline (Phase D, integration).

This test is intentionally heavyweight and is skipped unless the env var
WRIT_INTEGRATION_TESTS=1 is explicitly set. It exercises the complete install
path: marketplace add, plugin install, bootstrap, and health check.

To run manually:
  1. Ensure claude CLI is installed and authenticated.
  2. Ensure Redis is running (for graph DB).
  3. Set: export WRIT_INTEGRATION_TESTS=1
  4. Run: pytest tests/plugin/test_fresh_install_smoke.py -v

What the test does:
  1. Clones the current git checkout to /tmp/writ-fresh-<uuid>/
  2. Runs: claude plugin marketplace add /tmp/writ-fresh-<uuid>
  3. Runs: claude plugin install writ@writ
  4. Runs: bash <plugin-install-dir>/scripts/bootstrap-plugin.sh
  5. Asserts: curl http://localhost:8765/health returns {"status":"healthy"}
  6. Asserts: ${CLAUDE_PLUGIN_DATA}/.venv/bin/python3 exists
  7. Cleanup: removes marketplace, uninstalls plugin, deletes temp clone
"""

from __future__ import annotations

import os
import shutil
import subprocess
import uuid
from pathlib import Path

import pytest

from tests.plugin.conftest import REPO_ROOT


_INTEGRATION = os.environ.get("WRIT_INTEGRATION_TESTS", "") == "1"


@pytest.mark.integration
@pytest.mark.skipif(
    not _INTEGRATION,
    reason="Set WRIT_INTEGRATION_TESTS=1 to run heavyweight integration tests",
)
class TestFreshInstallSmoke:
    def test_fresh_install_marketplace_plugin_smoke(self, tmp_path: Path) -> None:
        """Full fresh-install pipeline: clone, marketplace add, plugin install, bootstrap, health check.

        See module docstring for manual execution instructions.
        This test exercises the entire Phase A-C delivery end-to-end.
        """
        # Step 1: Clone current checkout to a temp path
        clone_dir = Path(f"/tmp/writ-fresh-{uuid.uuid4().hex[:8]}")
        try:
            subprocess.run(
                ["git", "clone", str(REPO_ROOT), str(clone_dir)],
                check=True,
                capture_output=True,
                timeout=60,
            )

            # Step 2: Add marketplace
            subprocess.run(
                ["claude", "plugin", "marketplace", "add", str(clone_dir)],
                check=True,
                capture_output=True,
                timeout=30,
            )

            # Step 3: Install plugin
            subprocess.run(
                ["claude", "plugin", "install", "writ@writ"],
                check=True,
                capture_output=True,
                timeout=60,
            )

            # Step 4: Determine plugin install dir and run bootstrap
            result = subprocess.run(
                ["claude", "plugin", "path", "writ"],
                capture_output=True,
                text=True,
                timeout=10,
            )
            plugin_install_dir = Path(result.stdout.strip())
            bootstrap = plugin_install_dir / "scripts" / "bootstrap-plugin.sh"
            assert bootstrap.exists(), f"bootstrap-plugin.sh not found at {bootstrap}"
            subprocess.run(
                ["bash", str(bootstrap)],
                check=True,
                capture_output=True,
                timeout=300,
            )

            # Step 5: Assert health endpoint
            health_result = subprocess.run(
                ["curl", "-sf", "http://localhost:8765/health"],
                capture_output=True,
                text=True,
                timeout=15,
            )
            assert health_result.returncode == 0, (
                f"Writ health endpoint not reachable: {health_result.stderr}"
            )
            assert '"status"' in health_result.stdout and "healthy" in health_result.stdout, (
                f"Writ health endpoint did not return healthy status: {health_result.stdout}"
            )

            # Step 6: Assert venv exists
            plugin_data = Path(
                os.environ.get("CLAUDE_PLUGIN_DATA", str(Path.home() / ".cache" / "writ"))
            )
            venv_python = plugin_data / ".venv" / "bin" / "python3"
            assert venv_python.exists(), (
                f"Expected venv python3 at {venv_python} after bootstrap"
            )

        finally:
            # Cleanup: best-effort; do not raise on cleanup failure
            if clone_dir.exists():
                shutil.rmtree(clone_dir, ignore_errors=True)
            subprocess.run(
                ["claude", "plugin", "uninstall", "writ"],
                capture_output=True,
                timeout=30,
            )
            subprocess.run(
                ["claude", "plugin", "marketplace", "remove", "writ"],
                capture_output=True,
                timeout=30,
            )
