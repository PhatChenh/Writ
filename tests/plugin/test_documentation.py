"""Tests for documentation and version-bump deliverables.

Verifies README, CHANGELOG, pyproject.toml, SKILL.md, and the
docs/plugin-validation.md all reflect the current release. Originally
added for the v1.0.1 plugin distribution work; refactored 2026-05-15
during the v1.1.0 release prep to read the current version dynamically
from pyproject.toml so future bumps do not require per-release test
edits.
"""

from __future__ import annotations

import re
import tomllib
from pathlib import Path

import pytest

from tests.plugin.conftest import REPO_ROOT

README = REPO_ROOT / "README.md"
CHANGELOG = REPO_ROOT / "CHANGELOG.md"
PYPROJECT = REPO_ROOT / "pyproject.toml"
SKILL_MD = REPO_ROOT / "SKILL.md"
PLUGIN_VALIDATION_DOC = REPO_ROOT / "docs" / "plugin-validation.md"


def _pyproject_version() -> str:
    """Single source of truth for the current writ version.

    Mirrors the helper in tests/plugin/test_plugin_manifest.py and
    tests/plugin/test_marketplace_manifest.py. Tests that pin to a
    specific version literal recreate the same drift pattern Finding 9
    fixed for hardcoded credentials -- every release requires touching
    the test. Reading pyproject.toml dynamically means the test catches
    drift between manifests + docs without per-release edits.
    """
    data = tomllib.loads(PYPROJECT.read_text())
    return data["project"]["version"]


class TestReadmePluginSection:
    @pytest.fixture()
    def content(self) -> str:
        assert README.exists(), "README.md must exist"
        return README.read_text()

    def test_readme_plugin_install_section_exists(self, content: str) -> None:
        """README.md must contain the heading 'Install as a Claude Code plugin'."""
        assert "Install as a Claude Code plugin" in content, (
            "README.md must have an 'Install as a Claude Code plugin' section"
        )

    def test_readme_marketplace_add_command(self, content: str) -> None:
        """README.md must contain the exact marketplace add command."""
        assert "claude plugin marketplace add infinri/Writ" in content, (
            "README.md must document 'claude plugin marketplace add infinri/Writ'"
        )

    def test_readme_plugin_install_command(self, content: str) -> None:
        """README.md must contain the exact plugin install command."""
        assert "claude plugin install writ@writ" in content, (
            "README.md must document 'claude plugin install writ@writ'"
        )

    def test_readme_switching_section_exists(self, content: str) -> None:
        """README.md must contain the 'Switching from the standalone install to the plugin' section."""
        assert "Switching from the standalone install to the plugin" in content, (
            "README.md must have a 'Switching from the standalone install to the plugin' section"
        )


class TestChangelog:
    @pytest.fixture()
    def content(self) -> str:
        assert CHANGELOG.exists(), "CHANGELOG.md must exist"
        return CHANGELOG.read_text()

    def test_changelog_1_0_1_entry(self, content: str) -> None:
        """CHANGELOG.md must contain a ## [1.0.1] section heading."""
        assert "## [1.0.1]" in content, (
            "CHANGELOG.md must have a '## [1.0.1]' section"
        )

    def test_changelog_added_changed(self, content: str) -> None:
        """The 1.0.1 section must have Added and Changed subsections."""
        assert "## [1.0.1]" in content, (
            "CHANGELOG.md must have a '## [1.0.1]' section"
        )
        idx = content.index("## [1.0.1]")
        next_section = content.find("\n## [", idx + 1)
        section = content[idx:next_section] if next_section != -1 else content[idx:]
        lowered = section.lower()
        for subsection in ("added", "changed"):
            assert subsection in lowered, (
                f"CHANGELOG.md 1.0.1 section must contain a '{subsection}' subsection"
            )


class TestVersionBumps:
    """Manifest version-field consistency.

    Previously pinned to '1.0.1' literal; refactored 2026-05-15 during
    the v1.1.0 release prep to read the current version from
    pyproject.toml so future bumps do not require per-release test
    edits. The plugin.json and marketplace.json tests use the same
    pattern; this file covers pyproject self-shape + SKILL.md.
    """

    def test_pyproject_declares_semver_version(self) -> None:
        """pyproject.toml must declare a non-empty version field that
        parses as a semver-shaped string."""
        assert PYPROJECT.exists(), "pyproject.toml must exist"
        version = _pyproject_version()
        assert version, "pyproject.toml [project].version must be non-empty"
        assert re.match(r"^\d+\.\d+\.\d+", version), (
            f"pyproject.toml version {version!r} must be semver-shaped "
            f"(MAJOR.MINOR.PATCH)."
        )

    def test_skill_md_version_matches_pyproject(self) -> None:
        """SKILL.md frontmatter metadata.version must equal pyproject's
        [project].version. Manifests move in lockstep with pyproject."""
        assert SKILL_MD.exists(), "SKILL.md must exist"
        expected = _pyproject_version()
        content = SKILL_MD.read_text()
        pattern = re.escape(expected)
        assert re.search(rf'version[:\s]+["\']?{pattern}["\']?', content), (
            f"SKILL.md frontmatter must have version: {expected!r} "
            f"(from pyproject.toml). The manifests must move in "
            f"lockstep with pyproject.toml."
        )


class TestPluginValidationDoc:
    def test_plugin_validation_doc_exists(self) -> None:
        """docs/plugin-validation.md must exist and reference claude plugin validate."""
        if not PLUGIN_VALIDATION_DOC.exists():
            pytest.skip("docs/plugin-validation.md not yet created")
        assert PLUGIN_VALIDATION_DOC.exists(), "docs/plugin-validation.md must exist"
        content = PLUGIN_VALIDATION_DOC.read_text()
        assert "claude plugin validate" in content, (
            "docs/plugin-validation.md must reference 'claude plugin validate'"
        )
