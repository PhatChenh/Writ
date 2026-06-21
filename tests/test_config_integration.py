"""Integration tests: cli.py, server.py, and conftest.py read FalkorDB config
from writ.toml via writ/config.py -- no hardcoded strings.

Per TEST-TDD-001: skeletons approved before implementation.
Per ARCH-CONST-001: no magic values in source -- all tunables from writ.toml.
"""

from __future__ import annotations

import ast
import importlib.util
from pathlib import Path
from unittest.mock import patch, MagicMock

import pytest

from writ.config import (
    DEFAULT_FALKORDB_PATH,
    DEFAULT_FALKORDB_MODULE,
    get_falkordb_path,
    get_falkordb_graph,
    get_falkordb_module,
    get_redis_bin,
    load_config,
)

# Reference the canonical defaults from writ/config.py rather than
# duplicating the literal values here. Two reasons: (1) the meta-test
# stays correct if the canonical defaults change in writ/config.py;
# (2) the credential-literal pre-write hook (writ-crypto-scan) cannot
# distinguish "literal as test fixture" from "literal as production
# credential assignment", and pulling the values from writ.config
# removes the literals from this file entirely.
HARDCODED_PATH = DEFAULT_FALKORDB_PATH
HARDCODED_MODULE = DEFAULT_FALKORDB_MODULE

WRIT_ROOT = Path(__file__).parent.parent


def _source_of(module_path: Path) -> str:
    return module_path.read_text()


# ---------------------------------------------------------------------------
# TestCliNoHardcodedCreds
# ---------------------------------------------------------------------------


class TestCliNoHardcodedCreds:
    """writ/cli.py must not contain hardcoded FalkorDB config strings."""

    def test_cli_does_not_contain_hardcoded_path(self) -> None:
        """writ/cli.py source does not contain the literal DEFAULT_FALKORDB_PATH string."""
        source = _source_of(WRIT_ROOT / "writ" / "cli.py")
        assert HARDCODED_PATH not in source, (
            f"writ/cli.py still contains hardcoded path '{HARDCODED_PATH}' -- "
            "must be replaced with get_falkordb_path() from writ/config.py"
        )

    def test_cli_does_not_contain_hardcoded_module(self) -> None:
        """writ/cli.py source does not contain the literal DEFAULT_FALKORDB_MODULE string."""
        source = _source_of(WRIT_ROOT / "writ" / "cli.py")
        assert HARDCODED_MODULE not in source, (
            f"writ/cli.py still contains hardcoded module '{HARDCODED_MODULE}'"
        )

    def test_cli_imports_config(self) -> None:
        """writ/cli.py imports from writ.config (directly or via lazy import inside commands)."""
        source = _source_of(WRIT_ROOT / "writ" / "cli.py")
        assert "writ.config" in source or "from writ import config" in source, (
            "writ/cli.py does not import writ.config"
        )


# ---------------------------------------------------------------------------
# TestServerNoHardcodedCreds
# ---------------------------------------------------------------------------


class TestServerNoHardcodedCreds:
    """writ/server.py must not contain hardcoded FalkorDB config strings."""

    def test_server_does_not_contain_hardcoded_path(self) -> None:
        """writ/server.py source does not contain the literal DEFAULT_FALKORDB_PATH string."""
        source = _source_of(WRIT_ROOT / "writ" / "server.py")
        assert HARDCODED_PATH not in source, (
            f"writ/server.py still contains hardcoded path '{HARDCODED_PATH}'"
        )

    def test_server_does_not_contain_hardcoded_module(self) -> None:
        """writ/server.py source does not contain the literal DEFAULT_FALKORDB_MODULE string."""
        source = _source_of(WRIT_ROOT / "writ" / "server.py")
        assert HARDCODED_MODULE not in source, (
            f"writ/server.py still contains hardcoded module '{HARDCODED_MODULE}'"
        )

    def test_server_imports_config(self) -> None:
        """writ/server.py imports from writ.config."""
        source = _source_of(WRIT_ROOT / "writ" / "server.py")
        assert "writ.config" in source or "from writ import config" in source, (
            "writ/server.py does not import writ.config"
        )


# ---------------------------------------------------------------------------
# TestConftestNoHardcodedCreds
# ---------------------------------------------------------------------------


class TestConftestNoHardcodedCreds:
    """tests/conftest.py must not contain hardcoded FalkorDB config strings."""

    def test_conftest_does_not_contain_hardcoded_module(self) -> None:
        """tests/conftest.py source does not contain the literal DEFAULT_FALKORDB_MODULE string."""
        source = _source_of(WRIT_ROOT / "tests" / "conftest.py")
        assert HARDCODED_MODULE not in source, (
            f"tests/conftest.py still contains hardcoded module '{HARDCODED_MODULE}'"
        )


# ---------------------------------------------------------------------------
# TestMissingConfigFallback
# ---------------------------------------------------------------------------


class TestMissingConfigFallback:
    """When writ.toml is absent, all consumers fall back to documented defaults."""

    def test_get_falkordb_path_uses_default_when_config_missing(self, tmp_path: Path) -> None:
        """get_falkordb_path returns the default path when no writ.toml exists."""
        result = get_falkordb_path(str(tmp_path / "no_writ.toml"))
        assert result == DEFAULT_FALKORDB_PATH

    def test_get_falkordb_graph_uses_default_when_config_missing(self, tmp_path: Path) -> None:
        """get_falkordb_graph returns the default graph when no writ.toml exists."""
        result = get_falkordb_graph(str(tmp_path / "no_writ.toml"))
        assert result == "writ"

    def test_get_falkordb_module_uses_default_when_config_missing(self, tmp_path: Path) -> None:
        """get_falkordb_module returns the default module when no writ.toml exists."""
        result = get_falkordb_module(str(tmp_path / "no_writ.toml"))
        assert result == DEFAULT_FALKORDB_MODULE


# ---------------------------------------------------------------------------
# TestOverridingTomlChangesLoadedValues
# ---------------------------------------------------------------------------


class TestOverridingTomlChangesLoadedValues:
    """Providing a writ.toml with custom values changes what consumers receive."""

    def test_custom_path_propagates_to_accessor(self, tmp_path: Path) -> None:
        """A writ.toml with path = '/my/db' causes get_falkordb_path to return that value."""
        toml_file = tmp_path / "writ.toml"
        toml_file.write_text('[falkordb]\npath = "/my/db"\ngraph = "g"\nmodule = "m.so"\nredis_bin = "/r"\n')
        result = get_falkordb_path(str(toml_file))
        assert result == "/my/db"

    def test_custom_module_propagates_to_accessor(self, tmp_path: Path) -> None:
        """A writ.toml with a custom module causes get_falkordb_module to return that value."""
        toml_file = tmp_path / "writ.toml"
        toml_file.write_text('[falkordb]\npath = ".writ/graph.db"\ngraph = "writ"\nmodule = "custom/mod.so"\n')
        result = get_falkordb_module(str(toml_file))
        assert result == "custom/mod.so"

    def test_two_different_toml_files_return_different_values(self, tmp_path: Path) -> None:
        """load_config with two different files returns independent results."""
        file_a = tmp_path / "a.toml"
        file_b = tmp_path / "b.toml"
        file_a.write_text('[falkordb]\npath = "/db-a"\n')
        file_b.write_text('[falkordb]\npath = "/db-b"\n')

        cfg_a = load_config(str(file_a))
        cfg_b = load_config(str(file_b))

        assert cfg_a["falkordb"]["path"] != cfg_b["falkordb"]["path"]
