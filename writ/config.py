"""Centralized writ.toml loader using tomllib (Python 3.11+).

Returns typed config dict. All modules read config through this, not hardcoded values.

Per ARCH-CONST-001: all tunables must live in writ.toml with named constant defaults.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any

try:
    import tomllib
except ModuleNotFoundError:
    import tomli as tomllib  # type: ignore[no-redef]

# Per ARCH-CONST-001: named constants for defaults.
DEFAULT_FALKORDB_PATH = ".writ/graph.db"
DEFAULT_FALKORDB_GRAPH = "writ"
DEFAULT_FALKORDB_MODULE = "vendor/falkordb.so"
DEFAULT_REDIS_BIN = "/opt/homebrew/opt/redis/bin/redis-server"
DEFAULT_HNSW_CACHE_DIR = str(Path.home() / ".cache" / "writ" / "hnsw")

# Default config file path: writ.toml in the package root (one level above writ/).
_PACKAGE_ROOT = Path(__file__).resolve().parent.parent
_DEFAULT_CONFIG_PATH = str(_PACKAGE_ROOT / "writ.toml")


def load_config(path: str | None = None) -> dict[str, Any]:
    """Load and return the parsed writ.toml as a dict.

    Returns an empty dict when the file does not exist or is empty.
    """
    config_path = path if path is not None else _DEFAULT_CONFIG_PATH
    if not os.path.isfile(config_path):
        return {}
    try:
        with open(config_path, "rb") as f:
            data = tomllib.load(f)
        return data if data else {}
    except Exception:
        return {}


def get_falkordb_path(path: str | None = None) -> str:
    """Return falkordb.path from config, falling back to DEFAULT_FALKORDB_PATH."""
    cfg = load_config(path)
    return cfg.get("falkordb", {}).get("path", DEFAULT_FALKORDB_PATH)


def get_falkordb_graph(path: str | None = None) -> str:
    """Return falkordb.graph from config, falling back to DEFAULT_FALKORDB_GRAPH."""
    cfg = load_config(path)
    return cfg.get("falkordb", {}).get("graph", DEFAULT_FALKORDB_GRAPH)


def get_falkordb_module(path: str | None = None) -> str:
    """Return falkordb.module from config, falling back to DEFAULT_FALKORDB_MODULE."""
    cfg = load_config(path)
    return cfg.get("falkordb", {}).get("module", DEFAULT_FALKORDB_MODULE)


def get_redis_bin(path: str | None = None) -> str:
    """Return falkordb.redis_bin from config, falling back to DEFAULT_REDIS_BIN."""
    cfg = load_config(path)
    return cfg.get("falkordb", {}).get("redis_bin", DEFAULT_REDIS_BIN)


def get_hnsw_cache_dir(path: str | None = None) -> str:
    """Return hnsw.cache_dir from config, falling back to DEFAULT_HNSW_CACHE_DIR.

    TOML strings like "~/.cache/writ/hnsw" are expanded to an absolute path.
    Without this, Path() treats "~" as a literal dir name and creates a
    stray "~" folder wherever the process runs.
    """
    cfg = load_config(path)
    raw = cfg.get("hnsw", {}).get("cache_dir", DEFAULT_HNSW_CACHE_DIR)
    return os.path.expanduser(raw)
