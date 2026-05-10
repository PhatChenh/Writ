"""pyproject.toml packaging contract.

PSR-008 Finding 3 surfaced that `python3 -m writ.cli` fails outside the
writ skill's .venv (ModuleNotFoundError). The fix has two layers:

1. `bin/writ` shim (commit 08b3cff) -- works without pip install
2. `pip install -e .` from this repo -- creates `.venv/bin/writ`
   console_script via the [project.scripts] entry in pyproject.toml

This test pins the pyproject.toml shape so a future regression that
removes the entry_point or breaks package discovery is caught at lint
time, BEFORE someone tries `pip install` and discovers the shim is
the only path.
"""

from __future__ import annotations

import sys
import tomllib
from pathlib import Path

import pytest

SKILL_DIR = Path("/home/lucio.saldivar/.claude/skills/writ")
PYPROJECT = SKILL_DIR / "pyproject.toml"


@pytest.fixture(scope="module")
def pyproject() -> dict:
    with PYPROJECT.open("rb") as f:
        return tomllib.load(f)


class TestPyprojectInstallContract:
    """Pin the entries that make `pip install -e .` produce a usable
    `writ` console_script."""

    def test_project_section_present(self, pyproject: dict) -> None:
        assert "project" in pyproject, "pyproject.toml lacks [project] section"
        assert pyproject["project"].get("name") == "writ"

    def test_writ_console_script_entry_point(self, pyproject: dict) -> None:
        scripts = pyproject.get("project", {}).get("scripts", {})
        assert "writ" in scripts, (
            "pyproject.toml [project.scripts] is missing the `writ` entry. "
            "Without it, `pip install -e .` will not create a writ command."
        )
        # The entry must point at writ.cli:app (typer-style) or writ.cli:main
        # so the console script actually invokes the CLI, not a missing symbol.
        target = scripts["writ"]
        assert target.startswith("writ.cli:"), (
            f"writ entry_point points at unexpected target: {target!r}. "
            f"Should be writ.cli:app (typer) or writ.cli:main (argparse)."
        )

    def test_package_discovery_includes_writ(self, pyproject: dict) -> None:
        find_cfg = (
            pyproject.get("tool", {})
            .get("setuptools", {})
            .get("packages", {})
            .get("find", {})
        )
        includes = find_cfg.get("include", [])
        assert any("writ" in pat for pat in includes), (
            "setuptools.packages.find.include is missing writ; pip install "
            "would not discover the writ package."
        )

    def test_build_backend_present(self, pyproject: dict) -> None:
        bs = pyproject.get("build-system", {})
        assert "build-backend" in bs, "build-system.build-backend missing"
        # Must use a real PEP 517 backend, not be empty.
        assert bs["build-backend"], "build-system.build-backend is empty"

    def test_python_version_floor_supported(self, pyproject: dict) -> None:
        """Soft sanity: the floor must be a real released CPython that
        the dependencies (FastAPI, Pydantic v2, neo4j) all support."""
        rp = pyproject.get("project", {}).get("requires-python", "")
        assert ">=" in rp, f"requires-python lacks a floor: {rp!r}"
        # Floor of >=3.11 or higher is current writ baseline.
        floor = rp.split(">=")[1].strip(",<>= ")
        major, minor = floor.split(".")[:2]
        assert int(major) == 3 and int(minor) >= 11, (
            f"requires-python floor {floor} is below 3.11; "
            f"writ uses pattern matching + tomllib that need 3.11+."
        )


class TestInstalledConsoleScript:
    """Sanity check the existing installation. If pyproject.toml was
    edited and `pip install -e .` not re-run, the .venv/bin/writ might
    drift from the entry_point. This catches that."""

    def test_venv_writ_console_script_exists(self) -> None:
        venv_writ = SKILL_DIR / ".venv" / "bin" / "writ"
        if not venv_writ.exists():
            pytest.skip("writ .venv missing -- not an installed checkout")
        assert venv_writ.is_file()

    def test_venv_writ_runs_help(self) -> None:
        import subprocess
        venv_writ = SKILL_DIR / ".venv" / "bin" / "writ"
        if not venv_writ.exists():
            pytest.skip("writ .venv missing -- not an installed checkout")
        r = subprocess.run(
            [str(venv_writ), "--help"],
            capture_output=True,
            text=True,
            timeout=15,
        )
        assert r.returncode == 0, (
            f"venv/bin/writ failed: rc={r.returncode}\n"
            f"stderr={r.stderr[:500]}"
        )
        assert "audit-session" in r.stdout or "analyze-friction" in r.stdout, (
            f"writ --help output doesn't list expected commands:\n"
            f"{r.stdout[:500]}"
        )
