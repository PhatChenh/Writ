"""Shared test fixtures for Writ test suite."""

from __future__ import annotations

import os
import pytest
import pytest_asyncio


def pytest_sessionfinish(session, exitstatus):
    """Re-migrate rules after test suite completes so CLI queries work
    immediately.

    Pre-2026-05-09 this hook had inline migration logic gated on
    `if count == 0`. That gate skipped re-migration whenever ANY test
    re-loaded core rules (most do), leaving methodology nodes
    (Skill / Playbook / etc.) missing post-suite -- the symptom was
    `/always-on?mode=work` returning empty after `pytest -q`.

    New approach: shell out to `writ import-markdown bible/` unconditionally.
    The command is MERGE-only (idempotent), runs in <2s, and is the
    canonical import path used in production. Single source of
    truth -- the inline duplicate is gone.
    """
    import os
    import subprocess
    import sys
    from pathlib import Path

    from tests._writ_cmd import WRIT_CMD_PREFIX

    skill_dir = Path(__file__).resolve().parent.parent
    bible = skill_dir / "bible"
    if not bible.exists():
        return  # not a writ checkout; nothing to restore.

    try:
        subprocess.run(
            [*WRIT_CMD_PREFIX, "import-markdown", "bible/"],
            cwd=str(skill_dir),
            capture_output=True,
            timeout=60,
            check=False,
        )
    except (subprocess.SubprocessError, OSError):
        # The graph server may not be running, migrate.py may have changed
        # signature, etc. End-of-suite is best-effort -- we don't
        # raise out of pytest_sessionfinish because doing so flips
        # exitstatus and masks the actual test results.
        pass


# ---------------------------------------------------------------------------
# Phase 3 shared DB fixtures — one real FalkorDBLiteConnection, session-scoped,
# auto-reset before every test so no test can leak state into the next.
# ---------------------------------------------------------------------------


@pytest_asyncio.fixture(scope="session", loop_scope="session")
async def _session_db():
    """One real FalkorDBLiteConnection for the whole test run, on a throwaway
    temp dir so it never touches or locks the production .writ/graph.db.
    """
    import shutil
    import tempfile

    from writ.config import (
        get_falkordb_graph,
        get_falkordb_module,
        get_redis_bin,
    )
    from writ.graph.db import FalkorDBLiteConnection

    tmpdir = tempfile.mkdtemp(prefix="writ-test-")
    db_path = os.path.join(tmpdir, "graph.db")
    conn = FalkorDBLiteConnection(
        db_path=db_path,
        graph=get_falkordb_graph(),
        module_path=get_falkordb_module(),
        redis_bin=get_redis_bin(),
    )
    yield conn
    await conn.close()
    shutil.rmtree(tmpdir, ignore_errors=True)


@pytest_asyncio.fixture(autouse=True)
async def _clear_db(_session_db):
    """Wipe the test graph clean before every single test."""
    await _session_db.clear_all()


@pytest.fixture()
def db(_session_db):
    """Shared FalkorDBLiteConnection — the one handle every DB-touching test
    asks for instead of building its own connection."""
    return _session_db


@pytest.fixture()
def valid_rule_data() -> dict:
    """A well-formed rule with all required fields."""
    return {
        "rule_id": "ARCH-ORG-001",
        "domain": "Architecture",
        "severity": "critical",
        "scope": "component",
        "trigger": "When creating a class that contains logic from a different layer.",
        "statement": "Each class must belong to exactly one architectural layer.",
        "violation": "Controller contains SQL query.",
        "pass_example": "Controller delegates to service, service delegates to repository.",
        "enforcement": "Per-slice findings table must verify layer separation.",
        "rationale": "Mixed layers create untestable, unreusable, fragile classes.",
        "last_validated": "2026-03-15",
    }


@pytest.fixture()
def valid_enf_rule_data() -> dict:
    """An ENF-* rule with mandatory=true."""
    return {
        "rule_id": "ENF-GATE-001",
        "domain": "AI Enforcement",
        "severity": "critical",
        "scope": "session",
        "trigger": "When the AI completes Phase A analysis.",
        "statement": "Phase A output must be approved before Phase B begins.",
        "violation": "AI proceeds to Phase B without human approval of Phase A.",
        "pass_example": "AI halts after Phase A and waits for approval.",
        "enforcement": "Gate file must exist before Phase B output is generated.",
        "rationale": "Human review catches incorrect call-path declarations.",
        "mandatory": True,
        "last_validated": "2026-03-15",
    }


@pytest.fixture()
def minimal_rule_data() -> dict:
    """Rule with only required fields -- graph-only fields use defaults."""
    return {
        "rule_id": "TEST-TDD-001",
        "domain": "Testing",
        "severity": "high",
        "scope": "slice",
        "trigger": "When generating implementation code for a new class.",
        "statement": "Test skeletons must exist before the implementation they test.",
        "violation": "Implementation written first, tests added after.",
        "pass_example": "Test skeleton written and approved before implementation.",
        "enforcement": "ENF-GATE-007 test-first gate.",
        "rationale": "Tests written after implementation confirm what was built, not what should be built.",
        "last_validated": "2026-03-15",
    }


@pytest.fixture()
def compound_id_rule_data(valid_rule_data: dict) -> dict:
    """Rule with a multi-segment ID like FW-M2-RT-003."""
    return {**valid_rule_data, "rule_id": "FW-M2-RT-003"}


@pytest.fixture()
def enf_gate_final_data(valid_rule_data: dict) -> dict:
    """Rule with non-numeric suffix: ENF-GATE-FINAL."""
    return {**valid_rule_data, "rule_id": "ENF-GATE-FINAL"}
