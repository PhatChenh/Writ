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

SKILL_DIR = (Path.home() / ".claude/skills/writ")
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
        # The PyPI distribution name is "claude-writ" (the unqualified "writ"
        # name was taken by an unrelated package; see commit 0e533b9 + CHANGELOG
        # 1.0.1). The Python module name (`import writ`) and the console script
        # name (`writ`) are unchanged; only the pip distribution identifier
        # differs.
        assert pyproject["project"].get("name") == "claude-writ"

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

    def test_license_declared(self, pyproject: dict) -> None:
        """PEP 639 / SPDX-style license field. Required for a clean
        `pip install` and for downstream consumers to know the
        license without parsing the LICENSE file by hand."""
        license_field = pyproject.get("project", {}).get("license")
        assert license_field, "pyproject.toml [project].license is missing"
        # Either an SPDX string ("MIT") or a {file = "LICENSE"} table.
        if isinstance(license_field, str):
            assert license_field, "license string is empty"
        elif isinstance(license_field, dict):
            assert license_field.get("file") or license_field.get("text"), (
                "license table must have file or text key"
            )
        else:
            pytest.fail(f"license field has unexpected type: {type(license_field)}")

    def test_license_files_includes_LICENSE(self, pyproject: dict) -> None:
        """LICENSE file must be in license-files so sdist/wheel builds
        bundle it. Required for MIT redistribution compliance."""
        files = pyproject.get("project", {}).get("license-files", [])
        assert any("LICENSE" in pat for pat in files), (
            "pyproject.toml [project].license-files must include LICENSE"
        )

    def test_python_version_floor_supported(self, pyproject: dict) -> None:
        """Soft sanity: the floor must be a real released CPython that
        the dependencies (FastAPI, Pydantic v2, falkordb) all support."""
        rp = pyproject.get("project", {}).get("requires-python", "")
        assert ">=" in rp, f"requires-python lacks a floor: {rp!r}"
        # Floor of >=3.11 or higher is current writ baseline.
        floor = rp.split(">=")[1].strip(",<>= ")
        major, minor = floor.split(".")[:2]
        assert int(major) == 3 and int(minor) >= 11, (
            f"requires-python floor {floor} is below 3.11; "
            f"writ uses pattern matching + tomllib that need 3.11+."
        )


class TestLicensePresent:
    """LICENSE file exists at repo root and is the MIT text."""

    def test_license_file_present(self) -> None:
        license_path = SKILL_DIR / "LICENSE"
        assert license_path.is_file(), "LICENSE file is missing at repo root"
        body = license_path.read_text()
        assert "MIT License" in body, "LICENSE does not appear to be the MIT text"


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
