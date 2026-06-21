"""Tests for the non-tech-user bootstrap: scripts/bootstrap.sh + ensure-server.sh.

These are source-inspection tests (no real brew/pip invocation). They verify
that the bootstrap script contains every required section and that the supporting
infrastructure files exist with the expected shape. Shell execution is exercised
only where a mock PATH + tmp dirs keep it safe.
"""

from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path

import pytest


SKILL_DIR = Path(__file__).resolve().parent.parent
SCRIPTS_DIR = SKILL_DIR / "scripts"
BOOTSTRAP = SCRIPTS_DIR / "bootstrap.sh"
COMPOSE_FILE = SKILL_DIR / "docker-compose.yml"
ENSURE_SERVER = SCRIPTS_DIR / "ensure-server.sh"
INSTALL_SKILL = SCRIPTS_DIR / "install-skill.sh"


# ---------------------------------------------------------------------------
# File presence + executability
# ---------------------------------------------------------------------------


class TestFilePresence:
    def test_bootstrap_exists(self) -> None:
        assert BOOTSTRAP.exists(), "scripts/bootstrap.sh must exist"

    def test_bootstrap_is_executable(self) -> None:
        assert os.access(BOOTSTRAP, os.X_OK), "scripts/bootstrap.sh must be executable"

    def test_docker_compose_does_not_exist(self) -> None:
        assert not COMPOSE_FILE.exists(), (
            "docker-compose.yml must NOT exist — it was deleted in Phase 2 (Neo4j → FalkorDBLite)"
        )

    def test_install_skill_is_deleted(self) -> None:
        assert not INSTALL_SKILL.exists(), (
            "scripts/install-skill.sh must be deleted — stale and superseded "
            "by install-harness-config.sh + bootstrap.sh"
        )


# ---------------------------------------------------------------------------
# bootstrap.sh contains all required sections (source inspection)
# ---------------------------------------------------------------------------


class TestBootstrapSections:
    """Each required step must leave an identifiable marker in the script source."""

    @pytest.fixture
    def content(self) -> str:
        return BOOTSTRAP.read_text()

    def test_bootstrap_uses_strict_mode(self, content: str) -> None:
        """set -euo pipefail must be present for fail-fast behavior."""
        assert "set -euo pipefail" in content

    def test_bootstrap_checks_python_prerequisite(self, content: str) -> None:
        assert "python3" in content and ("3.11" in content or "3\\.11" in content), (
            "bootstrap.sh must check for python3 >= 3.11"
        )

    def test_bootstrap_checks_brew_prerequisite(self, content: str) -> None:
        assert "brew" in content.lower()
        # Must verify Homebrew is available, not just the binary
        assert "require_tool brew" in content or "command -v brew" in content, (
            "bootstrap.sh must verify Homebrew is available"
        )

    def test_bootstrap_checks_envsubst_prerequisite(self, content: str) -> None:
        assert "envsubst" in content, (
            "bootstrap.sh must check for envsubst (used by install-harness-config.sh)"
        )

    def test_bootstrap_creates_venv(self, content: str) -> None:
        assert "venv" in content and ".venv" in content, (
            "bootstrap.sh must create and use .venv"
        )

    def test_bootstrap_installs_deps(self, content: str) -> None:
        # After Finding D (Approach C, 2026-05-14), bootstrap installs
        # with the [dev] extras group so optimum is available for the
        # ONNX export step. The [fallback] group (sentence-transformers)
        # is intentionally NOT installed by default; production daemons
        # running on ONNX never need it. Operators who want to exercise
        # WRIT_ALLOW_EMBEDDING_FALLBACK=1 install it explicitly via
        # `pip install -e '.[fallback]'`.
        assert "pip install" in content, "bootstrap.sh must run pip install"
        assert "-e '.[dev]'" in content or "-e .[dev]" in content, (
            "bootstrap.sh must install -e '.[dev]' (Approach C: dev extras "
            "provide optimum for the ONNX export step). If you intentionally "
            "moved to bare -e . install, update this test AND the install "
            "contract in pyproject.toml's three-group partitioning."
        )

    def test_bootstrap_exports_onnx_model(self, content: str) -> None:
        # After Finding D (Approach C, 2026-05-14), bootstrap must
        # produce the ONNX model on disk so the daemon can take the
        # production ONNX path on first start. The export is gated on
        # the model file not already existing -- the test verifies
        # that bootstrap.sh has the export step, not the gating logic
        # (idempotency is verified separately by re-running bootstrap).
        assert "scripts/export_onnx.py" in content, (
            "bootstrap.sh must run scripts/export_onnx.py so the ONNX model "
            "is present for the daemon's production-path startup. Without "
            "this, a fresh install runs `writ serve` and the daemon refuses "
            "to start (see writ/retrieval/pipeline.py three-state ONNX "
            "contract, commit dae679a)."
        )

    def test_bootstrap_invokes_harness_installer(self, content: str) -> None:
        assert "install-harness-config.sh" in content, (
            "bootstrap.sh must invoke install-harness-config.sh"
        )

    def test_bootstrap_creates_rule_and_agent_symlinks(self, content: str) -> None:
        assert "ln -sf" in content or "ln -s" in content, (
            "bootstrap.sh must create symlinks for rules/agents"
        )
        assert "rules" in content and "agents" in content, (
            "bootstrap.sh must handle both rules/ and agents/ directories"
        )

    def test_bootstrap_ensures_redis(self, content: str) -> None:
        assert "redis" in content.lower(), (
            "bootstrap.sh must ensure Redis is available (install via Homebrew if needed)"
        )

    def test_bootstrap_downloads_falkordb_module(self, content: str) -> None:
        # Downloads falkordb-macos-arm64v8.so from GitHub releases
        assert "falkordb" in content.lower(), (
            "bootstrap.sh must download the FalkorDB module (falkordb.so)"
        )

    def test_bootstrap_ingests_rules(self, content: str) -> None:
        assert "import-markdown" in content, (
            "bootstrap.sh must run `writ import-markdown`"
        )

    def test_bootstrap_starts_daemon(self, content: str) -> None:
        assert "writ serve" in content, "bootstrap.sh must start the Writ daemon"

    def test_bootstrap_waits_for_daemon_health(self, content: str) -> None:
        assert "/health" in content, "bootstrap.sh must check daemon /health endpoint"

    def test_bootstrap_prints_ready_banner(self, content: str) -> None:
        lowered = content.lower()
        assert "ready" in lowered or "writ is ready" in lowered, (
            "bootstrap.sh must print a 'ready' banner at the end"
        )




# ---------------------------------------------------------------------------
# ensure-server.sh must use writ serve, not docker compose
# ---------------------------------------------------------------------------


class TestEnsureServerMigration:
    def test_ensure_server_uses_writ_serve(self) -> None:
        content = ENSURE_SERVER.read_text()
        assert "writ serve" in content, (
            "ensure-server.sh must use `nohup writ serve` for the Writ daemon"
        )

    def test_ensure_server_not_docker(self) -> None:
        content = ENSURE_SERVER.read_text()
        # Docker / docker-compose references should be gone — uses writ serve directly
        assert "docker" not in content.lower(), (
            "ensure-server.sh must not reference Docker; it uses writ serve directly"
        )


# ---------------------------------------------------------------------------
# Bootstrap prerequisite-check behavior (runtime, but sandboxed via PATH)
# ---------------------------------------------------------------------------


class TestBootstrapPrerequisiteChecks:
    """Run bootstrap.sh with a stripped PATH and verify it fails cleanly."""

    def _run_with_limited_path(
        self, tmp_path: Path, include_tools: list[str]
    ) -> subprocess.CompletedProcess:
        """Run bootstrap with a PATH containing only the tools we specify."""
        fake_bin = tmp_path / "bin"
        fake_bin.mkdir()
        for tool in include_tools:
            found = shutil.which(tool)
            if found:
                (fake_bin / tool).symlink_to(found)
        env = {"HOME": str(tmp_path), "PATH": str(fake_bin)}
        return subprocess.run(
            [str(BOOTSTRAP)],
            env=env,
            capture_output=True,
            text=True,
            timeout=10,
        )

    def test_fails_cleanly_when_python3_missing(self, tmp_path: Path) -> None:
        # bash is needed to run the script itself, but python3 is omitted
        result = self._run_with_limited_path(tmp_path, ["bash", "brew", "git", "envsubst"])
        assert result.returncode != 0, "bootstrap must fail when python3 is missing"
        combined = (result.stdout + result.stderr).lower()
        assert "python" in combined, "error message must mention python"

    def test_fails_cleanly_when_brew_missing(self, tmp_path: Path) -> None:
        result = self._run_with_limited_path(tmp_path, ["bash", "python3", "git", "envsubst"])
        assert result.returncode != 0, "bootstrap must fail when brew is missing"
        combined = (result.stdout + result.stderr).lower()
        assert "brew" in combined, "error message must mention brew"

    def test_fails_cleanly_when_git_missing(self, tmp_path: Path) -> None:
        result = self._run_with_limited_path(tmp_path, ["bash", "python3", "brew", "envsubst"])
        assert result.returncode != 0, "bootstrap must fail when git is missing"
        combined = (result.stdout + result.stderr).lower()
        assert "git" in combined, "error message must mention git"

    def test_fails_cleanly_when_envsubst_missing(self, tmp_path: Path) -> None:
        result = self._run_with_limited_path(
            tmp_path, ["bash", "python3", "brew", "git"]
        )
        assert result.returncode != 0, "bootstrap must fail when envsubst is missing"
        combined = (result.stdout + result.stderr).lower()
        assert "envsubst" in combined, "error message must mention envsubst"


# ---------------------------------------------------------------------------
# README has Quick Start + Troubleshooting
# ---------------------------------------------------------------------------


class TestReadme:
    @pytest.fixture
    def content(self) -> str:
        return (SKILL_DIR / "README.md").read_text()

    def test_readme_has_quick_start(self, content: str) -> None:
        lowered = content.lower()
        assert "quick start" in lowered or "quickstart" in lowered, (
            "README.md must have a Quick Start section"
        )

    def test_readme_references_bootstrap_script(self, content: str) -> None:
        assert "bootstrap.sh" in content, (
            "README.md Quick Start must reference scripts/bootstrap.sh"
        )

    def test_readme_has_troubleshooting(self, content: str) -> None:
        lowered = content.lower()
        assert "troubleshooting" in lowered or "common errors" in lowered, (
            "README.md must have a troubleshooting section"
        )
