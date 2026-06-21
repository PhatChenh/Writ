"""Unit tests for writ/config.py -- centralized writ.toml loader.

Per TEST-TDD-001: skeletons approved before implementation.
Per ARCH-CONST-001: all tunables must live in writ.toml with named constant defaults.
"""

from __future__ import annotations

import os
import platform
import shutil
from unittest.mock import patch

import pytest

from writ.config import (
    load_config,
    get_falkordb_path,
    get_falkordb_graph,
    get_falkordb_module,
    get_redis_bin,
    get_hnsw_cache_dir,
    DEFAULT_FALKORDB_PATH,
    DEFAULT_FALKORDB_GRAPH,
    DEFAULT_FALKORDB_MODULE,
    DEFAULT_HNSW_CACHE_DIR,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture()
def minimal_toml(tmp_path) -> str:
    """Write a minimal writ.toml and return its path."""
    toml_file = tmp_path / "writ.toml"
    toml_file.write_text(
        '[falkordb]\npath = "/custom/graph.db"\ngraph = "custom_graph"\n'
        'module = "custom/module.so"\nredis_bin = "/custom/redis-server"\n'
        '[hnsw]\ncache_dir = "/tmp/hnsw_test"\n'
    )
    return str(toml_file)


@pytest.fixture()
def partial_toml(tmp_path) -> str:
    """writ.toml with only the falkordb section partially filled -- hnsw section missing."""
    toml_file = tmp_path / "writ.toml"
    toml_file.write_text('[falkordb]\npath = "/partial/graph.db"\n')
    return str(toml_file)


@pytest.fixture()
def empty_toml(tmp_path) -> str:
    """Completely empty writ.toml."""
    toml_file = tmp_path / "writ.toml"
    toml_file.write_text("")
    return str(toml_file)


# ---------------------------------------------------------------------------
# TestLoadConfig -- raw dict loading
# ---------------------------------------------------------------------------


class TestLoadConfig:
    """load_config() returns a dict from a writ.toml file."""

    def test_loads_full_file(self, minimal_toml: str) -> None:
        """Full writ.toml loads without error and returns a dict."""
        result = load_config(minimal_toml)
        assert isinstance(result, dict)

    def test_returns_falkordb_section(self, minimal_toml: str) -> None:
        """Loaded config contains a 'falkordb' key with the correct values."""
        result = load_config(minimal_toml)
        assert result.get("falkordb", {}).get("path") == "/custom/graph.db"

    def test_returns_hnsw_section(self, minimal_toml: str) -> None:
        """Loaded config contains an 'hnsw' key with cache_dir."""
        result = load_config(minimal_toml)
        assert result.get("hnsw", {}).get("cache_dir") == "/tmp/hnsw_test"

    def test_missing_file_returns_empty_dict(self, tmp_path) -> None:
        """When writ.toml does not exist, load_config returns {}."""
        result = load_config(str(tmp_path / "no_such_file.toml"))
        assert result == {}

    def test_empty_file_returns_empty_dict(self, empty_toml: str) -> None:
        """Empty writ.toml returns {}."""
        result = load_config(empty_toml)
        assert result == {}


# ---------------------------------------------------------------------------
# TestDefaults -- typed accessors fall back to constants
# ---------------------------------------------------------------------------


class TestDefaults:
    """Typed accessors return documented defaults when config is absent."""

    def test_falkordb_path_default(self, tmp_path) -> None:
        """get_falkordb_path returns DEFAULT_FALKORDB_PATH when file is missing."""
        result = get_falkordb_path(str(tmp_path / "missing.toml"))
        assert result == DEFAULT_FALKORDB_PATH

    def test_falkordb_graph_default(self, tmp_path) -> None:
        """get_falkordb_graph returns DEFAULT_FALKORDB_GRAPH when file is missing."""
        result = get_falkordb_graph(str(tmp_path / "missing.toml"))
        assert result == DEFAULT_FALKORDB_GRAPH

    def test_falkordb_module_default(self, tmp_path) -> None:
        """get_falkordb_module returns DEFAULT_FALKORDB_MODULE when file is missing."""
        result = get_falkordb_module(str(tmp_path / "missing.toml"))
        assert result == DEFAULT_FALKORDB_MODULE

    def test_redis_bin_default_from_path(self, tmp_path, monkeypatch) -> None:
        """get_redis_bin returns the PATH redis-server when no config override."""
        monkeypatch.setattr(shutil, "which", lambda _: "/usr/bin/redis-server")
        result = get_redis_bin(str(tmp_path / "missing.toml"))
        assert result == "/usr/bin/redis-server"

    def test_redis_bin_arm64_fallback(self, tmp_path, monkeypatch) -> None:
        """get_redis_bin falls back to Homebrew arm64 default when PATH has no redis-server."""
        monkeypatch.setattr(shutil, "which", lambda _: None)
        monkeypatch.setattr(platform, "machine", lambda: "arm64")
        result = get_redis_bin(str(tmp_path / "missing.toml"))
        assert result == "/opt/homebrew/opt/redis/bin/redis-server"

    def test_redis_bin_x86_64_raises(self, tmp_path, monkeypatch) -> None:
        """get_redis_bin raises RuntimeError on x86_64 when redis-server not on PATH."""
        monkeypatch.setattr(shutil, "which", lambda _: None)
        monkeypatch.setattr(platform, "machine", lambda: "x86_64")
        with pytest.raises(RuntimeError, match="x86_64 not supported"):
            get_redis_bin(str(tmp_path / "missing.toml"))

    def test_hnsw_cache_dir_default(self, tmp_path) -> None:
        """get_hnsw_cache_dir returns DEFAULT_HNSW_CACHE_DIR when hnsw section absent."""
        cache_dir = get_hnsw_cache_dir(str(tmp_path / "missing.toml"))
        assert cache_dir == DEFAULT_HNSW_CACHE_DIR

    def test_partial_config_uses_defaults_for_missing_keys(self, partial_toml: str) -> None:
        """Accessor for a missing key falls back to default even when file exists."""
        # falkordb.path is set, but graph/module are not
        graph = get_falkordb_graph(partial_toml)
        assert graph == DEFAULT_FALKORDB_GRAPH
        module = get_falkordb_module(partial_toml)
        assert module == DEFAULT_FALKORDB_MODULE


# ---------------------------------------------------------------------------
# TestOverride -- explicit values take precedence over defaults
# ---------------------------------------------------------------------------


class TestOverride:
    """Values in writ.toml override all defaults."""

    def test_falkordb_path_overridden(self, minimal_toml: str) -> None:
        """path from writ.toml replaces the default."""
        result = get_falkordb_path(minimal_toml)
        assert result == "/custom/graph.db"
        assert result != DEFAULT_FALKORDB_PATH

    def test_falkordb_graph_overridden(self, minimal_toml: str) -> None:
        """graph from writ.toml replaces the default."""
        result = get_falkordb_graph(minimal_toml)
        assert result == "custom_graph"

    def test_falkordb_module_overridden(self, minimal_toml: str) -> None:
        """module from writ.toml replaces the default."""
        result = get_falkordb_module(minimal_toml)
        assert result == "custom/module.so"

    def test_redis_bin_overridden(self, minimal_toml: str) -> None:
        """redis_bin from writ.toml replaces PATH/fallback resolution."""
        result = get_redis_bin(minimal_toml)
        assert result == "/custom/redis-server"

    def test_hnsw_cache_dir_overridden(self, minimal_toml: str) -> None:
        """cache_dir from writ.toml replaces the default."""
        cache_dir = get_hnsw_cache_dir(minimal_toml)
        assert cache_dir == "/tmp/hnsw_test"

    def test_hnsw_cache_dir_expands_tilde(self, tmp_path) -> None:
        """A tilde override in writ.toml must be expanded, not left literal.

        Regression: an unexpanded '~' made hnswlib create a literal '~/' dir
        wherever the process ran. The getter must expand via expanduser.
        """
        import os

        toml_file = tmp_path / "writ.toml"
        toml_file.write_text('[hnsw]\ncache_dir = "~/my_writ_cache"\n')
        cache_dir = get_hnsw_cache_dir(str(toml_file))
        assert "~" not in cache_dir, (
            f"tilde must be expanded, got: {cache_dir!r}"
        )
        assert cache_dir == os.path.expanduser("~/my_writ_cache")


# ---------------------------------------------------------------------------
# TestConsumers -- expected import surface for downstream modules
# ---------------------------------------------------------------------------


class TestConsumers:
    """load_config and typed accessors are importable by all consumer modules."""

    def test_cli_can_import_config(self) -> None:
        """writ/cli.py can import get_falkordb_path, get_falkordb_graph, get_falkordb_module, get_redis_bin."""
        from writ.config import get_falkordb_path, get_falkordb_graph, get_falkordb_module, get_redis_bin
        assert callable(get_falkordb_path)
        assert callable(get_falkordb_graph)
        assert callable(get_falkordb_module)
        assert callable(get_redis_bin)

    def test_server_can_import_config(self) -> None:
        """writ/server.py can import get_falkordb_path, get_falkordb_graph, get_falkordb_module, get_redis_bin."""
        from writ.config import get_falkordb_path, get_falkordb_graph, get_falkordb_module, get_redis_bin
        assert callable(get_falkordb_path)
        assert callable(get_falkordb_graph)
        assert callable(get_falkordb_module)
        assert callable(get_redis_bin)

    def test_pipeline_can_import_config(self) -> None:
        """writ/retrieval/pipeline.py can import get_hnsw_cache_dir."""
        from writ.config import get_hnsw_cache_dir
        assert callable(get_hnsw_cache_dir)

    def test_conftest_can_import_config(self) -> None:
        """tests/conftest.py can import config accessors instead of hardcoded strings."""
        from writ.config import get_falkordb_path, get_falkordb_graph, get_falkordb_module, get_redis_bin
        # Verify these return strings (the defaults)
        assert isinstance(get_falkordb_path(), str)
        assert isinstance(get_falkordb_graph(), str)
        assert isinstance(get_falkordb_module(), str)
        assert isinstance(get_redis_bin(), str)
