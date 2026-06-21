"""Thin compatibility shim over `writ.graph.methodology_ingest` (v1.5.0).

Canonical entry point is `writ import-markdown`. Retained so existing call
sites (`scripts.migrate import run_migration`, third-party CI) keep working.
All parse / validate / DB-write logic lives in
`writ/graph/methodology_ingest.py`.
"""

from __future__ import annotations

import argparse
import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from writ.config import get_falkordb_path, get_falkordb_graph, get_falkordb_module, get_redis_bin
from writ.graph.db import FalkorDBLiteConnection
from writ.graph.methodology_ingest import ingest_path

_METH_TYPES = {"Skill", "Playbook", "Technique", "AntiPattern", "ForbiddenResponse",
               "Phase", "Rationalization", "PressureScenario", "WorkedExample", "SubagentRole"}


async def _ingest(dir_: Path, only: set[str] | None, dry_run: bool,
                  db: FalkorDBLiteConnection | None = None) -> None:
    owned = db is None
    if owned:
        db = FalkorDBLiteConnection(
            get_falkordb_path(), get_falkordb_graph(),
            get_falkordb_module(), get_redis_bin(),
        )
    try:
        report = await ingest_path(dir_, db, only=only, dry_run=dry_run)
        print(report.render())
        for err in report.errors:
            print(str(err), file=sys.stderr)
    finally:
        if owned:
            await db.close()


async def run_migration(bible_dir: Path, dry_run: bool = False) -> None:
    """Rule-only migration. Delegates to ingest_path(only={'Rule'})."""
    await _ingest(bible_dir, {"Rule"}, dry_run)


async def run_methodology_migration(fixtures_dir: Path, dry_run: bool = False,
                                    db: FalkorDBLiteConnection | None = None) -> None:
    """Methodology-only migration. Delegates to ingest_path with methodology types."""
    await _ingest(fixtures_dir, _METH_TYPES, dry_run, db=db)


def main() -> None:
    parser = argparse.ArgumentParser(description="Migrate Markdown nodes into the graph.")
    parser.add_argument("--bible-dir", type=Path, default=Path("bible/"))
    parser.add_argument("--methodology-dir", type=Path, default=None)
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()
    print("scripts/migrate.py is deprecated; prefer `writ import-markdown`.", file=sys.stderr)
    target = args.methodology_dir if args.methodology_dir is not None else args.bible_dir
    if not target.exists():
        print(f"Error: directory not found: {target}", file=sys.stderr)
        sys.exit(1)
    asyncio.run(_ingest(target, None, args.dry_run))


if __name__ == "__main__":
    main()
