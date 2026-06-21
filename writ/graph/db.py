"""FalkorDB connection layer -- embedded Redis subprocess, Unix socket, Cypher queries.

Per PERF-IO-001: no sync I/O in the hot path (anything reachable from FastAPI endpoints).
Graph queries only happen at startup (index warming) and in CLI/server background ops.
"""

from __future__ import annotations

import os
import signal
import subprocess
import tempfile
import time
from datetime import datetime
from pathlib import Path
from typing import Protocol


# --- Phase 1 additions: methodology node labels + expanded edge allowlist ---
# Per plan Section 3.1 (15 edge types total: 6 existing + 8 new per schema proposal).

METHODOLOGY_NODE_LABELS: frozenset[str] = frozenset({
    "Skill", "Playbook", "Technique", "AntiPattern", "ForbiddenResponse",
    "Phase", "Rationalization", "PressureScenario", "WorkedExample", "SubagentRole",
})

METHODOLOGY_NODE_ID_FIELDS: dict[str, str] = {
    "Skill": "skill_id",
    "Playbook": "playbook_id",
    "Technique": "technique_id",
    "AntiPattern": "antipattern_id",
    "ForbiddenResponse": "forbidden_id",
    "Phase": "phase_id",
    "Rationalization": "rationalization_id",
    "PressureScenario": "scenario_id",
    "WorkedExample": "example_id",
    "SubagentRole": "role_id",
}

ALLOWED_EDGE_TYPES: frozenset[str] = frozenset({
    # Pre-existing
    "DEPENDS_ON", "PRECEDES", "CONFLICTS_WITH", "SUPPLEMENTS",
    "SUPERSEDES", "RELATED_TO", "APPLIES_TO", "ABSTRACTS", "JUSTIFIED_BY",
    # Phase 1 additions per plan Section 3.1
    "TEACHES", "COUNTERS", "DEMONSTRATES", "DISPATCHES",
    "GATES", "PRESSURE_TESTS", "CONTAINS", "ATTACHED_TO",
})


def _coerce_value(v):
    """Convert Python objects to FalkorDB-compatible property values.

    Dates → ISO strings. Nested dicts → JSON strings (FalkorDB doesn't store maps
    as node properties). Lists of primitives pass through.
    """
    import json
    if hasattr(v, "isoformat"):
        return v.isoformat()
    if isinstance(v, dict):
        return json.dumps(v)
    if isinstance(v, list) and v and isinstance(v[0], dict):
        return json.dumps(v)
    return v


class GraphConnection(Protocol):
    """Connection interface for graph database operations.

    Per PY-PROTO-001: Protocol over ABC for pure interfaces.
    """

    async def get_rule(self, rule_id: str) -> dict | None: ...
    async def create_rule(self, rule_data: dict) -> str: ...
    async def create_edge(self, edge_type: str, source_id: str, target_id: str) -> None: ...
    async def traverse_neighbors(self, rule_id: str, hops: int) -> list[dict]: ...
    async def close(self) -> None: ...


class FalkorDBLiteConnection:
    """FalkorDB implementation of GraphConnection.

    Manages a Redis subprocess with the FalkorDB module loaded, connecting
    via Unix socket. Uses MERGE for idempotent writes.
    """

    def __init__(
        self,
        db_path: str,
        graph: str = "writ",
        module_path: str = "vendor/falkordb.so",
        redis_bin: str = "/opt/homebrew/opt/redis/bin/redis-server",
    ) -> None:
        from falkordb import FalkorDB

        self._path = db_path
        abs_db_path = os.path.abspath(db_path)
        self._db_dir = os.path.dirname(abs_db_path) or "."
        os.makedirs(self._db_dir, exist_ok=True)

        # Lockfile
        self._lock_path = Path(self._db_dir) / "graph.lock"
        self._acquire_lock()

        # Redis config — socket in /tmp to stay under macOS 104-char limit
        import hashlib
        sock_hash = hashlib.md5(self._db_dir.encode()).hexdigest()[:12]
        sock_dir = os.path.join("/tmp", f"writ-{sock_hash}")
        os.makedirs(sock_dir, exist_ok=True)
        self._socket_path = os.path.join(sock_dir, "redis.sock")
        conf_path = os.path.join(self._db_dir, "redis.conf")
        abs_module = os.path.abspath(module_path)
        with open(conf_path, "w") as f:
            f.write(
                f"port 0\n"
                f"unixsocket {self._socket_path}\n"
                f"unixsocketperm 700\n"
                f"dir {self._db_dir}\n"
                f"dbfilename {os.path.basename(abs_db_path)}\n"
                f"loadmodule {abs_module}\n"
                f"loglevel warning\n"
                f"logfile {os.path.join(self._db_dir, 'redis.log')}\n"
            )

        # Start Redis subprocess
        self._process = subprocess.Popen(
            [redis_bin, conf_path],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        for _ in range(50):
            if os.path.exists(self._socket_path):
                break
            time.sleep(0.1)
        else:
            log_path = os.path.join(self._db_dir, "redis.log")
            log_content = ""
            if os.path.exists(log_path):
                with open(log_path) as lf:
                    log_content = lf.read()[-500:]
            raise RuntimeError(
                f"Redis with FalkorDB module failed to start.\n{log_content}"
            )

        self._client = FalkorDB(unix_socket_path=self._socket_path)
        self._graph = self._client.select_graph(graph)

    def _acquire_lock(self) -> None:
        if self._lock_path.exists():
            try:
                pid = int(self._lock_path.read_text().strip())
                os.kill(pid, 0)
                raise RuntimeError(
                    f"Writ graph DB is locked by PID {pid}. "
                    "Stop the server or use the HTTP API."
                )
            except ProcessLookupError:
                pass
            except ValueError:
                pass
        self._lock_path.write_text(str(os.getpid()))

    def _execute_query(self, cypher: str, params: dict | None = None) -> list[dict]:
        """Execute a Cypher query and return results as list[dict].

        This is the ONLY place that knows about FalkorDB's result format.
        All callers get back list[dict] with string keys — same contract
        as the canonical record-dict pattern.
        """
        result = self._graph.query(cypher, params=params or {})
        if not result.result_set:
            return []
        # S2: header items are [type_code, name] pairs
        names = [h[1] for h in result.header]
        rows = []
        for row in result.result_set:
            converted = []
            for val in row:
                # S1: detect Node/Edge objects and extract .properties
                if hasattr(val, "properties"):
                    converted.append(val.properties)
                else:
                    converted.append(val)
            rows.append(dict(zip(names, converted)))
        return rows

    async def get_rule(self, rule_id: str) -> dict | None:
        """Fetch a single rule node by rule_id. Returns None if not found."""
        query = "MATCH (r:Rule {rule_id: $rule_id}) RETURN r"
        rows = self._execute_query(query, {"rule_id": rule_id})
        if not rows:
            return None
        return rows[0]["r"]

    async def create_rule(self, rule_data: dict) -> str:
        """Create or update a Rule node. Idempotent via MERGE on rule_id."""
        query = """
            MERGE (r:Rule {rule_id: $rule_id})
            SET r += $props
            RETURN r.rule_id AS rule_id
        """
        props = {k: _coerce_value(v) for k, v in rule_data.items() if k != "rule_id"}
        rows = self._execute_query(query, {"rule_id": rule_data["rule_id"], "props": props})
        return rows[0]["rule_id"]

    async def create_edge(self, edge_type: str, source_id: str, target_id: str) -> None:
        """Create a typed edge between two nodes. Idempotent via MERGE."""
        if edge_type not in ALLOWED_EDGE_TYPES:
            raise ValueError(f"Unknown edge type: {edge_type}")
        query = f"""
            MATCH (a) WHERE a.rule_id = $source_id
                OR a.skill_id = $source_id OR a.playbook_id = $source_id
                OR a.technique_id = $source_id OR a.antipattern_id = $source_id
                OR a.forbidden_id = $source_id OR a.phase_id = $source_id
                OR a.rationalization_id = $source_id OR a.scenario_id = $source_id
                OR a.example_id = $source_id OR a.role_id = $source_id
            MATCH (b) WHERE b.rule_id = $target_id
                OR b.skill_id = $target_id OR b.playbook_id = $target_id
                OR b.technique_id = $target_id OR b.antipattern_id = $target_id
                OR b.forbidden_id = $target_id OR b.phase_id = $target_id
                OR b.rationalization_id = $target_id OR b.scenario_id = $target_id
                OR b.example_id = $target_id OR b.role_id = $target_id
            MERGE (a)-[:{edge_type}]->(b)
        """
        self._execute_query(query, {"source_id": source_id, "target_id": target_id})

    async def create_methodology_node(self, node_type: str, data: dict) -> str:
        """Create or update a methodology node (non-Rule type). Idempotent via MERGE."""
        if node_type not in METHODOLOGY_NODE_LABELS:
            raise ValueError(f"Unknown methodology node_type: {node_type}")
        id_field = METHODOLOGY_NODE_ID_FIELDS[node_type]
        if id_field not in data:
            raise ValueError(f"{node_type} data missing required {id_field}")
        node_id = data[id_field]
        props = {k: _coerce_value(v) for k, v in data.items() if k != id_field}
        query = f"""
            MERGE (n:{node_type} {{{id_field}: $node_id}})
            SET n += $props
            RETURN n.{id_field} AS id
        """
        rows = self._execute_query(query, {"node_id": node_id, "props": props})
        return rows[0]["id"]

    async def traverse_neighbors(self, rule_id: str, hops: int = 1) -> list[dict]:
        """Return neighbors within N hops, including edge types."""
        max_hops = 3
        if not (1 <= hops <= max_hops):
            raise ValueError(f"hops must be between 1 and {max_hops}")

        # Single-hop fast path: simple edge match.
        one_hop_query = """
            MATCH (start:Rule {rule_id: $rule_id})-[rel]-(neighbor:Rule)
            RETURN DISTINCT
                neighbor.rule_id AS rule_id,
                type(rel) AS edge_type,
                startNode(rel).rule_id AS from_id,
                endNode(rel).rule_id AS to_id
        """
        rows = self._execute_query(one_hop_query, {"rule_id": rule_id})
        if hops == 1:
            return rows

        # Multi-hop: iterative BFS in Python.  FalkorDB variable-length
        # path syntax [rel*1..N] returns a Path object that cannot be
        # UNWIND-ed, so we expand hop-by-hop.
        seen: set[str] = {rule_id}
        for row in rows:
            seen.add(row["rule_id"])
        results: list[dict] = list(rows)
        frontier: set[str] = {row["rule_id"] for row in rows}

        for _ in range(2, hops + 1):
            next_frontier: set[str] = set()
            for current_id in frontier:
                neighbor_rows = self._execute_query(
                    one_hop_query, {"rule_id": current_id}
                )
                for row in neighbor_rows:
                    nid = row["rule_id"]
                    if nid not in seen:
                        seen.add(nid)
                        next_frontier.add(nid)
                        results.append(row)
            frontier = next_frontier
            if not frontier:
                break

        return results

    async def count_rules(self) -> int:
        """Return total Rule node count."""
        query = "MATCH (r:Rule) RETURN count(r) AS count"
        rows = self._execute_query(query)
        return rows[0]["count"] if rows else 0

    async def get_all_rules(self) -> list[dict]:
        """Fetch all Rule nodes. Returns list of property dicts."""
        query = "MATCH (r:Rule) RETURN r ORDER BY r.rule_id"
        rows = self._execute_query(query)
        return [row["r"] for row in rows]

    async def get_all_edges(self) -> list[dict]:
        """Fetch all edges between Rule nodes."""
        query = """
            MATCH (a:Rule)-[rel]->(b:Rule)
            RETURN a.rule_id AS from_id, b.rule_id AS to_id, type(rel) AS edge_type
            ORDER BY a.rule_id, b.rule_id
        """
        return self._execute_query(query)

    async def create_abstraction(self, data: dict) -> str:
        """Create or update an Abstraction node. Idempotent via MERGE."""
        query = """
            MERGE (a:Abstraction {abstraction_id: $abstraction_id})
            SET a += $props
            RETURN a.abstraction_id AS abstraction_id
        """
        props = {k: v for k, v in data.items() if k != "abstraction_id"}
        rows = self._execute_query(
            query, {"abstraction_id": data["abstraction_id"], "props": props}
        )
        return rows[0]["abstraction_id"]

    async def create_abstracts_edge(self, abstraction_id: str, rule_id: str) -> None:
        """Create ABSTRACTS edge from Abstraction to Rule. Idempotent via MERGE."""
        query = """
            MATCH (a:Abstraction {abstraction_id: $abstraction_id})
            MATCH (r:Rule {rule_id: $rule_id})
            MERGE (a)-[:ABSTRACTS]->(r)
        """
        self._execute_query(query, {"abstraction_id": abstraction_id, "rule_id": rule_id})

    async def get_all_abstractions(self) -> list[dict]:
        """Fetch all Abstraction nodes with member rule_ids."""
        query = """
            MATCH (a:Abstraction)
            OPTIONAL MATCH (a)-[:ABSTRACTS]->(r:Rule)
            RETURN a, collect(r.rule_id) AS member_ids
            ORDER BY a.abstraction_id
        """
        rows = self._execute_query(query)
        abstractions = []
        for row in rows:
            data = row["a"]
            data["member_ids"] = row["member_ids"]
            abstractions.append(data)
        return abstractions

    async def get_abstraction(self, abstraction_id: str) -> dict | None:
        """Fetch a single Abstraction with member rule details."""
        query = """
            MATCH (a:Abstraction {abstraction_id: $abstraction_id})
            OPTIONAL MATCH (a)-[:ABSTRACTS]->(r:Rule)
            RETURN a, collect(r) AS members
        """
        rows = self._execute_query(query, {"abstraction_id": abstraction_id})
        if not rows:
            return None
        data = rows[0]["a"]
        # Normalize members: FalkorDB returns Node objects; convert to
        # property dicts so callers can subscript with field names.
        raw_members = rows[0]["members"]
        data["members"] = [
            m.properties if hasattr(m, "properties") else m
            for m in raw_members
        ]
        return data

    async def delete_abstractions(self) -> int:
        """Delete all Abstraction nodes and their ABSTRACTS edges. Rules unaffected."""
        query = "MATCH (a:Abstraction) DETACH DELETE a RETURN count(a) AS deleted"
        rows = self._execute_query(query)
        return rows[0]["deleted"] if rows else 0

    async def get_rule_abstraction(self, rule_id: str) -> dict | None:
        """Return abstraction membership for a rule."""
        query = """
            MATCH (a:Abstraction)-[:ABSTRACTS]->(r:Rule {rule_id: $rule_id})
            OPTIONAL MATCH (a)-[:ABSTRACTS]->(sibling:Rule)
            WHERE sibling.rule_id <> $rule_id
            RETURN a.abstraction_id AS abstraction_id,
                   collect(sibling.rule_id) AS sibling_rule_ids
        """
        rows = self._execute_query(query, {"rule_id": rule_id})
        if not rows or rows[0]["abstraction_id"] is None:
            return None
        return {
            "abstraction_id": rows[0]["abstraction_id"],
            "sibling_rule_ids": sorted(rows[0]["sibling_rule_ids"]),
        }

    async def apply_constraints(self) -> None:
        """Apply indexes and uniqueness constraints. Idempotent via error swallowing."""
        index_specs = [
            ("Rule", "rule_id"),
            ("Rule", "domain"),
            ("Rule", "mandatory"),
            ("Abstraction", "abstraction_id"),
            ("Abstraction", "domain"),
        ]
        for label, id_field in METHODOLOGY_NODE_ID_FIELDS.items():
            index_specs.append((label, id_field))
            index_specs.append((label, "domain"))

        for label, field in index_specs:
            try:
                self._graph.create_node_range_index(label, field)
            except Exception as e:
                msg = str(e).lower()
                if "already indexed" in msg or "already exist" in msg:
                    pass
                else:
                    raise

        unique_specs = [
            ("Rule", "rule_id"),
            ("Abstraction", "abstraction_id"),
        ]
        for label, id_field in METHODOLOGY_NODE_ID_FIELDS.items():
            unique_specs.append((label, id_field))

        for label, field in unique_specs:
            try:
                self._graph.create_node_unique_constraint(label, field)
            except Exception as e:
                msg = str(e).lower()
                if "already exist" in msg:
                    pass
                else:
                    raise

    async def list_constraints(self) -> list[dict]:
        """Return all constraints normalized to a stable, canonical format.

        FalkorDB's CALL db.constraints() returns {type, label, properties,
        entitytype, status}; the canonical shape is {name, type, entityType, ...}.
        We synthesize a ``name`` key so existing tests pass unchanged.
        """
        raw = self._execute_query("CALL db.constraints()")
        out: list[dict] = []
        for c in raw:
            label = c.get("label", "")
            props = c.get("properties", [])
            prop_str = "_".join(props) if props else ""
            name = f"{prop_str}_unique" if prop_str else ""
            out.append({
                "name": name,
                "type": c.get("type", ""),
                "label": label,
                "properties": props,
            })
        return out

    async def list_indexes(self) -> list[dict]:
        """Return all indexes normalized to a stable, canonical format.

        FalkorDB's CALL db.indexes() returns {label, properties, types,
        entitytype, status, ...}; the canonical shape is {name, type, entityType, ...}.
        We synthesize a ``name`` key so existing tests pass unchanged.
        """
        raw = self._execute_query("CALL db.indexes()")
        out: list[dict] = []
        seen: set[str] = set()
        for ix in raw:
            label = ix.get("label", "")
            for prop in ix.get("properties", []):
                name = f"{label}_{prop}".lower()
                if name not in seen:
                    seen.add(name)
                    out.append({
                        "name": name,
                        "label": label,
                        "properties": ix.get("properties", []),
                    })
        return out

    async def get_rules_by_authority(self, authority: str) -> list[dict]:
        """Fetch all Rule nodes with a given authority value."""
        query = """
            MATCH (r:Rule)
            WHERE r.authority = $authority
            RETURN r
            ORDER BY r.last_validated DESC
        """
        rows = self._execute_query(query, {"authority": authority})
        return [row["r"] for row in rows]

    async def update_rule_authority(self, rule_id: str, authority: str) -> bool:
        """Update the authority property on a Rule node. Returns True if found."""
        query = """
            MATCH (r:Rule {rule_id: $rule_id})
            SET r.authority = $authority
            RETURN r.rule_id AS rule_id
        """
        rows = self._execute_query(query, {"rule_id": rule_id, "authority": authority})
        return len(rows) > 0

    async def update_rule_confidence(self, rule_id: str, confidence: str) -> bool:
        """Update the confidence property on a Rule node. Returns True if found."""
        query = """
            MATCH (r:Rule {rule_id: $rule_id})
            SET r.confidence = $confidence
            RETURN r.rule_id AS rule_id
        """
        rows = self._execute_query(query, {"rule_id": rule_id, "confidence": confidence})
        return len(rows) > 0

    async def increment_positive(self, rule_id: str) -> bool:
        """Increment times_seen_positive and update last_seen. Returns True if found."""
        ts = datetime.now().isoformat()
        query = """
            MATCH (r:Rule {rule_id: $rule_id})
            SET r.times_seen_positive = coalesce(r.times_seen_positive, 0) + 1,
                r.last_seen = $ts
            RETURN r.rule_id AS rule_id
        """
        rows = self._execute_query(query, {"rule_id": rule_id, "ts": ts})
        return len(rows) > 0

    async def increment_negative(self, rule_id: str) -> bool:
        """Increment times_seen_negative and update last_seen. Returns True if found."""
        ts = datetime.now().isoformat()
        query = """
            MATCH (r:Rule {rule_id: $rule_id})
            SET r.times_seen_negative = coalesce(r.times_seen_negative, 0) + 1,
                r.last_seen = $ts
            RETURN r.rule_id AS rule_id
        """
        rows = self._execute_query(query, {"rule_id": rule_id, "ts": ts})
        return len(rows) > 0

    async def delete_rule(self, rule_id: str) -> bool:
        """Delete a Rule node and all its edges. Returns True if found."""
        query = """
            MATCH (r:Rule {rule_id: $rule_id})
            DETACH DELETE r
            RETURN count(r) AS deleted
        """
        rows = self._execute_query(query, {"rule_id": rule_id})
        return rows[0]["deleted"] > 0 if rows else False

    async def count_by_authority(self) -> dict[str, int]:
        """Count rules grouped by authority value."""
        query = """
            MATCH (r:Rule)
            RETURN coalesce(r.authority, 'human') AS authority, count(r) AS count
            ORDER BY authority
        """
        rows = self._execute_query(query)
        return {row["authority"]: row["count"] for row in rows}

    async def clear_all(self) -> None:
        """Delete all nodes and edges. For test cleanup only."""
        self._execute_query("MATCH (n) DETACH DELETE n")

    async def close(self) -> None:
        """Shut down the Redis subprocess and release the lockfile."""
        try:
            self._client.close()
        except Exception:
            pass
        if self._process.poll() is None:
            self._process.terminate()
            try:
                self._process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                self._process.kill()
                self._process.wait()
        try:
            self._lock_path.unlink(missing_ok=True)
        except OSError:
            pass
