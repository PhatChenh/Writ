"""Centralized writ.toml loader using tomllib (Python 3.11+).

Returns typed config dict. All modules read config through this, not hardcoded values.

Per ARCH-CONST-001: all tunables must live in writ.toml with named constant defaults.
"""

from __future__ import annotations

import os
import platform
import shutil
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
_REDIS_SEARCH_PATHS = [
    "/opt/homebrew/opt/redis/bin/redis-server",   # Homebrew arm64
    "/usr/local/bin/redis-server",                 # Homebrew x86 / manual
    "/opt/local/bin/redis-server",                 # MacPorts
]
# Scan Python framework bin dirs (Python.org installers drop redis-server here)
import glob as _glob
_REDIS_SEARCH_PATHS += _glob.glob(
    "/Library/Frameworks/Python.framework/Versions/*/bin/redis-server"
)
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
    """Return falkordb.module from config, falling back to DEFAULT_FALKORDB_MODULE.

    A relative module path is resolved against the writ package root (where the
    bundled vendor/falkordb.so ships), NOT the current working directory. The cwd
    is the consuming project writ runs against (e.g. mkt_engine), which has no
    vendor/falkordb.so — resolving there made Redis abort with "module failed to
    load: server aborting".
    """
    cfg = load_config(path)
    module = cfg.get("falkordb", {}).get("module", DEFAULT_FALKORDB_MODULE)
    if not os.path.isabs(module):
        module = str(_PACKAGE_ROOT / module)
    return module


def get_redis_bin(path: str | None = None) -> str:
    """Resolve the redis-server binary path at runtime.

    Resolution order (Apple-Silicon-only per D9):
    1. writ.toml [falkordb] redis_bin override
    2. shutil.which("redis-server") — PATH lookup
    3. Homebrew arm64 default (/opt/homebrew/opt/redis/bin/redis-server)
    4. On x86_64: explicit error (not supported)
    """
    cfg = load_config(path)
    override = cfg.get("falkordb", {}).get("redis_bin")
    if override:
        return override
    found = shutil.which("redis-server")
    if found:
        return found
    for candidate in _REDIS_SEARCH_PATHS:
        if os.path.isfile(candidate) and os.access(candidate, os.X_OK):
            return candidate
    raise RuntimeError(
        "redis-server not found on PATH or common install locations. "
        "Install redis (brew install redis) or set [falkordb] redis_bin in writ.toml. "
        "Install redis: brew install redis"
    )


def get_hnsw_cache_dir(path: str | None = None) -> str:
    """Return hnsw.cache_dir from config, falling back to DEFAULT_HNSW_CACHE_DIR.

    TOML strings like "~/.cache/writ/hnsw" are expanded to an absolute path.
    Without this, Path() treats "~" as a literal dir name and creates a
    stray "~" folder wherever the process runs.
    """
    cfg = load_config(path)
    raw = cfg.get("hnsw", {}).get("cache_dir", DEFAULT_HNSW_CACHE_DIR)
    return os.path.expanduser(raw)
