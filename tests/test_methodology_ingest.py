"""Unit tests for writ/graph/methodology_ingest.py (v1.5.0).

Covers the library surface that the unified `writ import-markdown` CLI and
the `scripts/migrate.py` shim both consume. End-to-end / graph-integration
behavior is exercised by tests/test_import_markdown_unified.py; this module
pins the in-process invariants:

- INGESTER_REGISTRY contains an entry for every known node type.
- KNOWN_NODE_TYPES is the registry key-set.
- IngestError stringifies to a single line with file:type 'id' -- reason
  shape (no Python traceback substring).
- IngestReport.render() includes per-type counts and a totals line.
"""

from __future__ import annotations

import asyncio
from pathlib import Path

import pytest

from writ.graph.methodology_ingest import (
    INGESTER_REGISTRY,
    KNOWN_NODE_TYPES,
    IngestError,
    IngestReport,
    ingest_path,
)


class TestRegistry:
    def test_registry_has_rule(self) -> None:
        assert "Rule" in INGESTER_REGISTRY
        assert callable(INGESTER_REGISTRY["Rule"])

    def test_registry_has_core_methodology_types(self) -> None:
        for nt in ("Skill", "Playbook", "AntiPattern", "Technique",
                   "ForbiddenResponse", "Phase", "SubagentRole",
                   "Rationalization", "WorkedExample"):
            assert nt in INGESTER_REGISTRY, f"missing registry entry: {nt}"

    def test_known_node_types_matches_registry(self) -> None:
        assert KNOWN_NODE_TYPES == frozenset(INGESTER_REGISTRY.keys())

    def test_known_node_types_is_frozenset(self) -> None:
        assert isinstance(KNOWN_NODE_TYPES, frozenset)


class TestIngestError:
    def test_str_contains_file_type_id_reason(self) -> None:
        err = IngestError(
            file=Path("/tmp/bad.md"),
            node_type="Skill",
            node_id="SKL-X-001",
            field="staleness_window",
            reason="value is not a valid integer",
        )
        s = str(err)
        assert "bad.md" in s
        assert "Skill" in s
        assert "SKL-X-001" in s
        assert "staleness_window" in s
        assert "value is not a valid integer" in s

    def test_str_has_no_traceback(self) -> None:
        err = IngestError(
            file=Path("/tmp/bad.md"),
            node_type="Skill",
            node_id="SKL-X-001",
            field=None,
            reason="boom",
        )
        assert "Traceback (most recent call last):" not in str(err)
        assert "pydantic_core._pydantic_core.ValidationError" not in str(err)

    def test_str_handles_missing_fields(self) -> None:
        err = IngestError(
            file=Path("/tmp/nope.md"),
            node_type=None,
            node_id=None,
            field=None,
            reason="parse error",
        )
        s = str(err)
        assert "nope.md" in s
        assert "parse error" in s


class TestIngestReport:
    def test_render_empty(self) -> None:
        r = IngestReport()
        out = r.render()
        assert "Imported nodes by type" in out

    def test_render_includes_per_type_counts(self) -> None:
        r = IngestReport(counts_by_type={"Rule": 80, "Skill": 12, "Playbook": 4})
        out = r.render()
        assert "Rule" in out and "80" in out
        assert "Skill" in out and "12" in out
        assert "Playbook" in out and "4" in out

    def test_render_includes_totals(self) -> None:
        r = IngestReport(counts_by_type={"Rule": 10, "Skill": 5})
        out = r.render()
        assert "Total" in out
        assert "15" in out

    def test_render_dry_run_marker(self) -> None:
        r = IngestReport(counts_by_type={"Skill": 1}, dry_run=True)
        out = r.render()
        assert "DRY RUN" in out or "dry" in out.lower()

    def test_render_edges_line_for_live_run(self) -> None:
        r = IngestReport(
            counts_by_type={"Rule": 1},
            edges_created=3,
            edges_dangling=1,
            dry_run=False,
        )
        out = r.render()
        assert "Edges created" in out
        assert "3" in out

    def test_render_errors_line(self) -> None:
        r = IngestReport(
            counts_by_type={"Rule": 1},
            errors=[
                IngestError(
                    file=Path("/x.md"),
                    node_type="Rule",
                    node_id="X-001",
                    field=None,
                    reason="bad",
                )
            ],
        )
        out = r.render()
        assert "Errors" in out
        assert "1" in out


class TestIngestPathMissingDir:
    def test_returns_error_for_nonexistent(self) -> None:
        async def _run() -> IngestReport:
            return await ingest_path(Path("/nonexistent/path/xyz"), db=None, dry_run=True)

        report = asyncio.run(_run())
        assert report.errors
        assert any("does not exist" in e.reason for e in report.errors)
