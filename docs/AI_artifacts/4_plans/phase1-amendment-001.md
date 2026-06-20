# Plan Amendment 001: Correct FalkorDB Embedded Stack

> Amends: `phase1-core-storage-swap.md` Steps 1–3
> Date: 2026-06-20
> Reason: Plan assumed `falkordblite` PyPI package existed. It does not. Also, `redislite` bundles Redis 6.2 but FalkorDB requires Redis 7.2+.

---

## What Changed

The plan's research identified a package called `falkordblite` with import path `from redislite.async_falkordb_client import AsyncFalkorDB`. This package does not exist on PyPI. Additionally, `redislite` (embedded Redis) bundles Redis 6.2.14, but ALL FalkorDB releases require Redis 7.2+, making redislite unusable.

### Final Architecture

| Plan assumed | Actual (validated) |
|-------------|-------------------|
| `falkordblite` single package | `falkordb>=1.0,<2` client + `vendor/falkordb.so` module binary + Homebrew Redis 8.x server |
| `redislite` embedded Redis | Homebrew `redis-server` managed as subprocess from Python |
| `from redislite.async_falkordb_client import AsyncFalkorDB` | `from falkordb import FalkorDB` (sync) or `from falkordb.asyncio import FalkorDB as AsyncFalkorDB` (async) |
| `AsyncFalkorDB(path)` → single embedded process | `subprocess.Popen([redis_bin, config_path])` → managed Redis process, then `FalkorDB(unix_socket_path=socket_path)` |
| Zero external dependencies | Homebrew: `redis`, `openssl@3`, `libomp` |

### System Requirements (replaces Docker + Neo4j)

```bash
brew install redis openssl@3 libomp
```

Plus: download `vendor/falkordb.so` from FalkorDB GitHub releases (platform-specific).

### Why Not redislite

- redislite bundles Redis 6.2.14 (compiled into package)
- FalkorDB v4.14.x requires Redis 7.2+
- FalkorDB v4.18.x requires Redis 8.0+
- No way to upgrade redislite's bundled Redis
- B0 research correction (redis-py 8.0 breaks redislite) is moot since we don't use redislite

## Research Corrections Status

| ID | Finding | Status |
|----|---------|--------|
| B0 | `redis<8` pin needed | **MOOT** — was for redislite only. falkordb works fine with redis-py 8.0 |
| S1 | Node `.properties` extraction | **CONFIRMED** — `falkordb.Node` has `.properties` dict |
| S2 | `QueryResult.header` is `[type_code, name]` pairs | **CONFIRMED** — e.g. `[[1, 'rule_id'], [1, 'domain']]` |
| A9 | Error check needs `"already indexed"` and `"already exist"` | **PARTIALLY CONFIRMED** — index: `"already indexed"`, constraint: `"constraint already exists"`. Both contain `"already"` but different full messages |
| A10 | Two Neo4jConnection refs in pipeline.py | Still valid (to verify at implementation time) |

## Step 1 Amendment: Dependencies

**pyproject.toml** (final):
```toml
dependencies = [
    ...
    "falkordb>=1.0,<2",    # FalkorDB graph client
    ...
]
```
No `redis` pin needed (falkordb pulls it). No `redislite`.

**System deps** (documented in README, not in pyproject.toml):
- `brew install redis` — Redis server 8.x
- `brew install openssl@3 libomp` — FalkorDB module runtime deps
- `vendor/falkordb.so` — downloaded from GitHub releases

**writ.toml** `[falkordb]` section:
```toml
[falkordb]
path = ".writ/graph.db"
graph = "writ"
module = "vendor/falkordb.so"
redis_bin = "/opt/homebrew/opt/redis/bin/redis-server"
```

## Step 2 Amendment: Config Functions

Add three config functions (not two):

```python
DEFAULT_FALKORDB_PATH = ".writ/graph.db"
DEFAULT_FALKORDB_GRAPH = "writ"
DEFAULT_FALKORDB_MODULE = "vendor/falkordb.so"
DEFAULT_REDIS_BIN = "/opt/homebrew/opt/redis/bin/redis-server"

def get_falkordb_path(path=None) -> str: ...
def get_falkordb_graph(path=None) -> str: ...
def get_falkordb_module(path=None) -> str: ...
def get_redis_bin(path=None) -> str: ...
```

## Step 3 Amendment: Constructor and Connection

The `FalkorDBLiteConnection` constructor manages the Redis subprocess:

```python
import subprocess, tempfile, os, time, signal
from falkordb import FalkorDB

class FalkorDBLiteConnection:
    def __init__(self, db_path: str, graph: str = "writ",
                 module_path: str = "vendor/falkordb.so",
                 redis_bin: str = "/opt/homebrew/opt/redis/bin/redis-server"):
        self._db_dir = os.path.dirname(os.path.abspath(db_path)) or "."
        os.makedirs(self._db_dir, exist_ok=True)

        # Write Redis config
        self._socket_path = os.path.join(self._db_dir, "redis.sock")
        self._conf_path = os.path.join(self._db_dir, "redis.conf")
        with open(self._conf_path, 'w') as f:
            f.write(f"""
port 0
unixsocket {self._socket_path}
unixsocketperm 700
dir {self._db_dir}
dbfilename {os.path.basename(db_path)}
loadmodule {os.path.abspath(module_path)}
loglevel warning
logfile {os.path.join(self._db_dir, 'redis.log')}
""")

        # Start Redis subprocess
        self._process = subprocess.Popen(
            [redis_bin, self._conf_path],
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL
        )
        # Wait for socket
        for _ in range(50):
            if os.path.exists(self._socket_path):
                break
            time.sleep(0.1)
        else:
            raise RuntimeError("Redis with FalkorDB module failed to start")

        # Connect FalkorDB client
        self._client = FalkorDB(unix_socket_path=self._socket_path)
        self._graph = self._client.select_graph(graph)
        self._path = db_path
```

**close() method**:
```python
async def close(self) -> None:
    self._client.close()
    self._process.terminate()
    self._process.wait(timeout=5)
    # lockfile cleanup
```

**_execute_query()** — structurally identical to plan. `self._graph.query()` returns `QueryResult` with `.header` and `.result_set`.

Note: The `falkordb` sync client's `graph.query()` is NOT async. For async usage, use `from falkordb.asyncio import FalkorDB`. The constructor subprocess management is sync regardless (startup only).

## Steps 4–8: No Changes

Lockfile, reach-through swaps, IntegrityChecker, server/CLI updates, and verification are mechanically identical. The `_execute_query()` contract (`list[dict]` return) is preserved.

## Validation Results (2026-06-20)

All tested with Python 3.12.3 + falkordb 1.6.1 + redis-py 8.0.0 + Redis server 8.8.0 + FalkorDB module v4.18.10:

| Test | Result |
|------|--------|
| CREATE node | ✅ |
| MATCH with field extraction | ✅ |
| MATCH returning full node | ✅ Node.properties works |
| MERGE | ✅ |
| create_node_range_index | ✅ |
| Idempotent index re-creation | ✅ "already indexed" in error msg |
| create_node_unique_constraint | ✅ |
| Idempotent constraint re-creation | ✅ "already exists" in error msg |
| QueryResult.header format | ✅ `[[type_code, name], ...]` |
| Unix socket connection | ✅ |
| Subprocess lifecycle (start/terminate) | ✅ |
