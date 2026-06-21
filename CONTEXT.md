# CONTEXT.md — Term Glossary (Writ FalkorDBLite fork)

Plain-English definitions of project-specific terms. Updated as terms are
resolved during design work.

---

## Phase 2 — Infrastructure Cleanup

**FalkorDBLite (as built in Phase 1)**
The embedded graph database that replaced Neo4j. Despite the name in the
old reference doc, it is NOT a `pip install falkordblite` package. In this
repo it is the class `FalkorDBLiteConnection` (`writ/graph/db.py`), which
spawns a local `redis-server` subprocess with a vendored FalkorDB module
(`vendor/falkordb.so`) loaded, talks to it over a Unix socket, and runs
Cypher queries. No Docker, no separate server process to manage.

**`vendor/falkordb.so`**
The compiled FalkorDB Redis module — the binary that teaches a plain
`redis-server` how to speak the graph query language (Cypher). The
connection loads it at startup. It is platform-specific (one build for
Apple-Silicon ARM64, a different one for Intel x86_64). It is NOT checked
into git; Phase 2's bootstrap downloads it from FalkorDB's GitHub releases.

**`redis_bin`**
The filesystem path to the `redis-server` executable that the connection
launches. The Phase-1 default hardcoded the Apple-Silicon Homebrew path
(`/opt/homebrew/opt/redis/bin/redis-server`); Intel Macs install it under
`/usr/local/...`. Phase 2 makes this resolve correctly per machine.

**`_execute_query(cypher, params)`**
The single low-level method on the connection that runs a Cypher query and
returns the answer as a plain list of dictionaries (one dict per result
row, keyed by the query's column names). It is the only place that knows
the database's raw result format. Scripts that used to reach into Neo4j
internals (`db._driver.session()`) are rewritten to call this instead.

**High-level DB methods**
The named, purpose-built methods on the connection — `create_rule`,
`create_methodology_node`, `create_edge`, `get_all_rules`, `count_rules`,
etc. They wrap `_execute_query` with the right Cypher. Scripts that only
create or count nodes can call these directly and never touch raw queries.

**Always-ingest (MERGE-idempotent)**
Bootstrap behavior decided in Phase 2: on every run it re-loads the rule
corpus from `bible/` into the graph, even when the database file already
exists. Safe because the load uses MERGE (create-or-update), so re-loading
unchanged rules does nothing, while edited rules get picked up.

**Bootstrap idempotency**
The property that re-running the setup script is safe and skips work
already done. Expensive steps (Python venv, ONNX model export, Homebrew
install, `.so` download) are skipped when their output already exists;
ingest is the one deliberate exception (see Always-ingest).

**Plugin-mode bootstrap**
A second setup path (`scripts/bootstrap-plugin.sh`) used when Writ is
installed as a Claude Code plugin rather than a checked-out repo. It puts
the Python environment in a persistent data directory so it survives
plugin upgrades. Phase 2 gives it the same Docker/Neo4j removal as the
standalone bootstrap.
