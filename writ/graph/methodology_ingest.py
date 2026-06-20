"""Unified bible ingestion library (v1.5.0).

Single source of truth for the parse + validate + write pipeline that backs
both the `writ import-markdown` CLI command and the thin `scripts/migrate.py`
compatibility shim. Collapses the duplicate ingest loops that previously
lived in `writ/cli.py::import_markdown` (Rule-only) and
`scripts/migrate.py::run_methodology_migration` (methodology) into one
registry-dispatched walk per DRY-DUP-002.

Public surface:
- `ingest_path(path, db, only=None, dry_run=False) -> IngestReport`
- `ingest_edges(parsed_nodes, parsed_edges, db) -> tuple[int, int]`
- `INGESTER_REGISTRY: dict[str, Callable]`
- `KNOWN_NODE_TYPES: frozenset[str]`
- `IngestReport`, `IngestError`

Per SOLID-OCP-002 the per-node dispatch is a registry lookup, not an if/elif
chain. Per API-ERROR-002 validation failures surface as typed
`IngestError(file, node_type, node_id, reason)` records, not raw Pydantic
tracebacks.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Awaitable, Callable

from writ.graph.db import FalkorDBLiteConnection
from writ.graph.ingest import (
    NODE_ID_FIELDS,
    discover_rule_files,
    parse_edges_from_file,
    parse_nodes_from_file,
    validate_parsed_node,
)


# --- Registry ----------------------------------------------------------------

# Per SOLID-OCP-002: per-node-type dispatch is a registry lookup. Adding a
# new node type is a one-line registry edit, not a CLI-rewrite.
Ingester = Callable[[FalkorDBLiteConnection, dict], Awaitable[str]]


async def _ingest_rule(db: FalkorDBLiteConnection, clean: dict) -> str:
    return await db.create_rule(clean)


def _make_methodology_ingester(node_type: str) -> Ingester:
    async def _ingest(db: FalkorDBLiteConnection, clean: dict) -> str:
        return await db.create_methodology_node(node_type, clean)

    return _ingest


INGESTER_REGISTRY: dict[str, Ingester] = {
    "Rule": _ingest_rule,
    **{nt: _make_methodology_ingester(nt) for nt in NODE_ID_FIELDS if nt != "Rule"},
}

KNOWN_NODE_TYPES: frozenset[str] = frozenset(INGESTER_REGISTRY.keys())


# --- Typed records -----------------------------------------------------------

@dataclass(frozen=True)
class IngestError:
    """Structured validation / write error (API-ERROR-002).

    `__str__` returns a single-line summary suitable for stderr; no Python
    traceback is included.
    """

    file: Path
    node_type: str | None
    node_id: str | None
    field: str | None
    reason: str

    def __str__(self) -> str:
        nt = self.node_type or "?"
        nid = self.node_id or "?"
        field_part = f" [field={self.field}]" if self.field else ""
        return f"{self.file}:{nt} '{nid}'{field_part} -- {self.reason}"


@dataclass
class IngestReport:
    """Per-type counts + edge counts + structured errors for one ingest run."""

    counts_by_type: dict[str, int] = field(default_factory=dict)
    edges_created: int = 0
    edges_dangling: int = 0
    errors: list[IngestError] = field(default_factory=list)
    ingested: list[tuple[Path, str, str]] = field(default_factory=list)
    dry_run: bool = False

    def render(self) -> str:
        """Human-readable multi-line summary for stdout."""
        lines: list[str] = []
        header = "[DRY RUN] " if self.dry_run else ""
        if self.counts_by_type:
            lines.append(f"{header}Imported nodes by type:")
            for nt in sorted(self.counts_by_type):
                lines.append(f"  {nt}: {self.counts_by_type[nt]}")
            total = sum(self.counts_by_type.values())
            lines.append(f"  Total: {total}")
        else:
            lines.append(f"{header}Imported nodes by type: (none)")
        # When errors exist alongside successful ingests, list the successfully
        # ingested files so the user can see which files DID land (partial-
        # success diagnostics). Skipped in clean runs to keep output compact.
        if self.errors and self.ingested:
            lines.append("Ingested files:")
            for filepath, node_type, node_id in self.ingested:
                lines.append(f"  {filepath}:{node_type} '{node_id}'")
        if not self.dry_run:
            lines.append(
                f"Edges created: {self.edges_created} "
                f"({self.edges_dangling} skipped: dangling)"
            )
        if self.errors:
            lines.append(f"Errors: {len(self.errors)}")
        return "\n".join(lines)


# --- Core pipeline -----------------------------------------------------------

def _extract_pydantic_field(exc: Exception) -> tuple[str | None, str]:
    """Best-effort extract field names + messages from a Pydantic / ValueError.

    When the exception carries multiple field errors (Pydantic's `.errors()`),
    the returned `field` is the first offending field name and the returned
    reason enumerates ALL field-name -- message pairs joined by `; `. This
    keeps the CLI line single-row while still surfacing every offending field
    name (the test contract requires the offending field to appear in output).
    """
    errors_attr = getattr(exc, "errors", None)
    if callable(errors_attr):
        try:
            errs = errors_attr()
        except Exception:
            errs = None
        if errs:
            parts = []
            first_field: str | None = None
            for e in errs:
                loc = e.get("loc") or ()
                fname = str(loc[0]) if loc else "?"
                if first_field is None and loc:
                    first_field = fname
                msg = e.get("msg") or "validation error"
                parts.append(f"{fname}: {msg}")
            return first_field, "; ".join(parts)
    return None, str(exc)


async def ingest_path(
    path: Path,
    db: FalkorDBLiteConnection,
    *,
    only: set[str] | None = None,
    dry_run: bool = False,
) -> IngestReport:
    """Walk `path` recursively for *.md, parse each, validate, write via registry.

    `only` -- when non-empty, files whose parsed `node_type` is not in the set
    are skipped (parsed-and-discarded). `dry_run` -- parse + validate without
    DB writes. Returns an `IngestReport` with per-type counts and structured
    errors.
    """
    report = IngestReport(dry_run=dry_run)
    if not path.exists():
        report.errors.append(
            IngestError(
                file=path,
                node_type=None,
                node_id=None,
                field=None,
                reason=f"path does not exist: {path}",
            )
        )
        return report

    files = discover_rule_files(path)
    parsed_nodes: list[dict] = []
    parsed_edges: list[dict] = []
    # Track which file each parsed node came from for error reporting on write.
    node_source: dict[int, Path] = {}

    for filepath in files:
        try:
            file_nodes = parse_nodes_from_file(filepath)
        except Exception as exc:
            field_name, reason = _extract_pydantic_field(exc)
            report.errors.append(
                IngestError(
                    file=filepath,
                    node_type=None,
                    node_id=None,
                    field=field_name,
                    reason=f"parse error: {reason}",
                )
            )
            continue

        for node in file_nodes:
            node_type = node.get("node_type", "Rule")
            if only and node_type not in only:
                continue
            if node_type not in INGESTER_REGISTRY:
                id_field = NODE_ID_FIELDS.get(node_type, "id")
                report.errors.append(
                    IngestError(
                        file=filepath,
                        node_type=node_type,
                        node_id=node.get(id_field),
                        field=None,
                        reason=(
                            f"unknown node_type '{node_type}' (expected one of "
                            f"{sorted(KNOWN_NODE_TYPES)})"
                        ),
                    )
                )
                continue

            try:
                validate_parsed_node(node)
            except Exception as exc:
                id_field = NODE_ID_FIELDS.get(node_type, "id")
                # validate_parsed_node wraps Pydantic in a ValueError; unwrap
                # to extract the offending field name.
                cause = exc.__cause__ if exc.__cause__ is not None else exc
                field_name, reason = _extract_pydantic_field(cause)
                report.errors.append(
                    IngestError(
                        file=filepath,
                        node_type=node_type,
                        node_id=node.get(id_field),
                        field=field_name,
                        reason=reason,
                    )
                )
                continue

            node_source[id(node)] = filepath
            parsed_nodes.append(node)

        # Collect edges from the file's front-matter (only-filter is applied
        # at edge-creation time so cross-type edges still resolve).
        try:
            parsed_edges.extend(parse_edges_from_file(filepath))
        except Exception as exc:
            report.errors.append(
                IngestError(
                    file=filepath,
                    node_type=None,
                    node_id=None,
                    field=None,
                    reason=f"edge parse error: {exc}",
                )
            )

    # Write nodes via registry.
    if not dry_run and parsed_nodes:
        try:
            await db.apply_constraints()
        except Exception:
            # Constraints already exist or DB unavailable; surface DB errors
            # on the actual create_* calls below.
            pass

    for node in parsed_nodes:
        node_type = node["node_type"]
        clean = {
            k: v for k, v in node.items()
            if k != "node_type" and not k.startswith("_") and k != "edges"
        }
        if dry_run:
            report.counts_by_type[node_type] = (
                report.counts_by_type.get(node_type, 0) + 1
            )
            id_field = NODE_ID_FIELDS.get(node_type, "id")
            report.ingested.append((
                node_source.get(id(node), Path("<unknown>")),
                node_type,
                node.get(id_field, "?"),
            ))
            continue
        ingester = INGESTER_REGISTRY[node_type]
        try:
            await ingester(db, clean)
            report.counts_by_type[node_type] = (
                report.counts_by_type.get(node_type, 0) + 1
            )
            id_field = NODE_ID_FIELDS.get(node_type, "id")
            report.ingested.append((
                node_source.get(id(node), Path("<unknown>")),
                node_type,
                node.get(id_field, "?"),
            ))
        except Exception as exc:
            id_field = NODE_ID_FIELDS.get(node_type, "id")
            report.errors.append(
                IngestError(
                    file=node_source.get(id(node), Path("<unknown>")),
                    node_type=node_type,
                    node_id=node.get(id_field),
                    field=None,
                    reason=f"db write failed: {exc}",
                )
            )

    # Edges -- skip in dry-run.
    if not dry_run and parsed_nodes:
        created, dangling = await ingest_edges(parsed_nodes, parsed_edges, db)
        report.edges_created = created
        report.edges_dangling = dangling

    return report


async def ingest_edges(
    parsed_nodes: list[dict],
    parsed_edges: list[dict],
    db: FalkorDBLiteConnection,
) -> tuple[int, int]:
    """Create methodology + cross-reference edges; return (created, dangling)."""
    # Build the set of node IDs that are known to the graph: parsed-this-run
    # union pre-existing Rule corpus.
    parsed_ids: set[str] = set()
    for node in parsed_nodes:
        nt = node.get("node_type", "Rule")
        id_field = NODE_ID_FIELDS.get(nt)
        if id_field and id_field in node:
            parsed_ids.add(node[id_field])

    try:
        existing_rule_ids = {r["rule_id"] for r in await db.get_all_rules()}
    except Exception:
        existing_rule_ids = set()
    known_ids = parsed_ids | existing_rule_ids

    created = 0
    dangling = 0

    # Front-matter declared edges.
    for edge in parsed_edges:
        src = edge.get("source")
        tgt = edge.get("target")
        etype = edge.get("type")
        if not src or not tgt or not etype:
            dangling += 1
            continue
        if src not in known_ids or tgt not in known_ids:
            dangling += 1
            continue
        try:
            await db.create_edge(etype, src, tgt)
            created += 1
        except ValueError:
            dangling += 1

    # Legacy RELATED_TO skeleton edges from cross-references on Rule nodes.
    rule_ids = {
        n["rule_id"] for n in parsed_nodes
        if n.get("node_type", "Rule") == "Rule" and "rule_id" in n
    }
    for node in parsed_nodes:
        if node.get("node_type", "Rule") != "Rule":
            continue
        own_id = node.get("rule_id")
        if not own_id:
            continue
        for ref_id in node.get("_cross_references", []):
            if ref_id in rule_ids:
                try:
                    await db.create_edge("RELATED_TO", own_id, ref_id)
                    created += 1
                except ValueError:
                    dangling += 1

    return created, dangling
