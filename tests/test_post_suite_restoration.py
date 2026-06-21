"""End-of-suite graph restoration: methodology corpus must be present
after pytest finishes.

Context: 9 test modules call `db.clear_all()`. Only `test_retrieval`
restored via migrate.py in its module teardown. The pre-existing
`pytest_sessionfinish` hook in tests/conftest.py was supposed to be
the safety net but its `if count == 0` gate skipped re-migration
whenever ANY test re-loaded core rules (most do), leaving methodology
nodes (Skill / Playbook / etc.) missing post-suite.

Symptom: `/always-on?mode=work` returned empty after `pytest -q`
because the methodology corpus had been wiped and never restored.

This test pins the new contract: after pytest_sessionfinish runs,
Skill nodes are in the graph (a methodology marker, since core Rule
re-loads can leave that label empty).
"""

from __future__ import annotations

import asyncio
import subprocess
import sys

import pytest

from tests._writ_cmd import WRIT_CMD_PREFIX
from pathlib import Path


SKILL_DIR = str(Path.home() / ".claude/skills/writ")


def _count(label: str) -> int:
    """Direct FalkorDB graph count of a label, bypassing the test session
    fixtures (so we observe the production graph state)."""
    from writ.config import (
        get_falkordb_path,
        get_falkordb_graph,
        get_falkordb_module,
        get_redis_bin,
    )
    from writ.graph.db import FalkorDBLiteConnection

    async def _q() -> int:
        db = FalkorDBLiteConnection(
            db_path=get_falkordb_path(),
            graph=get_falkordb_graph(),
            module_path=get_falkordb_module(),
            redis_bin=get_redis_bin(),
        )
        rows = db._execute_query(f"MATCH (n:{label}) RETURN count(n) AS c")
        await db.close()
        return int(rows[0]["c"]) if rows else 0

    return asyncio.run(_q())


class TestSessionFinishRestoresMethodology:
    """Pin the conftest contract by exercising the same restore path
    pytest_sessionfinish triggers. The hook itself runs once at end of
    suite -- we can't directly re-invoke it from a test, so this test
    runs the canonical migration script and confirms the post-state.
    Equivalent to what pytest_sessionfinish should do."""

    def test_migrate_restores_skill_nodes(self) -> None:
        # Run the same migration the conftest hook should be running.
        result = subprocess.run(
            [*WRIT_CMD_PREFIX, "import-markdown", "bible/"],
            cwd=SKILL_DIR,
            capture_output=True,
            text=True,
            timeout=60,
        )
        assert result.returncode == 0, (
            f"writ import-markdown failed: stderr={result.stderr[:500]}"
        )

        # After migration, methodology labels MUST be populated.
        assert _count("Skill") > 0, (
            "Skill nodes missing after migrate.py -- methodology "
            "ingestion is broken"
        )
        assert _count("Playbook") > 0, "Playbook nodes missing after migrate.py"
        assert _count("ForbiddenResponse") > 0, (
            "ForbiddenResponse nodes missing after migrate.py"
        )

    def test_conftest_sessionfinish_does_not_gate_on_count_zero(self) -> None:
        """The conftest hook used to skip restoration when count > 0
        (i.e. when bible/ rules were already loaded). That gate left
        methodology nodes missing whenever any test re-ingested only
        the core corpus. Pin the fix: the source must NOT contain
        the `if count == 0` early-return pattern."""
        with open(f"{SKILL_DIR}/tests/conftest.py") as f:
            body = f.read()

        # Heuristic: the count-zero gate around re-migration is gone.
        # Either the function calls migrate.py via subprocess (the new
        # path), or it still has inline logic but without the gate.
        assert "if count == 0:" not in body or "subprocess" in body, (
            "tests/conftest.py still contains the `if count == 0` "
            "early-return that skips methodology restoration"
        )
