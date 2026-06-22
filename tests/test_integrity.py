"""Phase 4: Integrity check tests.

Tests that IntegrityChecker detects known problems in crafted fixtures.
Requires FalkorDB running with test data.
Each test is isolated (TEST-ISO-001).
"""

from __future__ import annotations

import importlib.util
from datetime import date, timedelta

import pytest

from writ.graph.integrity import IntegrityChecker


def _make_rule(
    rule_id: str,
    mandatory: bool = False,
    trigger: str = "Default trigger",
    statement: str = "Default statement",
    last_validated: str | None = None,
    staleness_window: int = 365,
) -> dict:
    if last_validated is None:
        last_validated = date.today().isoformat()
    return {
        "rule_id": rule_id,
        "domain": "Test",
        "severity": "medium",
        "scope": "file",
        "trigger": trigger,
        "statement": statement,
        "violation": "Bad.",
        "pass_example": "Good.",
        "enforcement": "Review.",
        "rationale": "Testing.",
        "mandatory": mandatory,
        "confidence": "production-validated",
        "evidence": "doc:original-bible",
        "staleness_window": staleness_window,
        "last_validated": last_validated,
    }


@pytest.fixture()
def checker(db) -> IntegrityChecker:
    return IntegrityChecker(db)


class TestConflictDetection:
    """CONFLICTS_WITH edge detection."""

    @pytest.mark.asyncio
    async def test_conflict_detected(self, db, checker: IntegrityChecker) -> None:
        await db.create_rule(_make_rule("RULE-A-001"))
        await db.create_rule(_make_rule("RULE-B-001"))
        await db.create_edge("CONFLICTS_WITH", "RULE-A-001", "RULE-B-001")

        conflicts = await checker.detect_conflicts()
        assert len(conflicts) == 1
        pair = conflicts[0]
        assert pair["rule_a"] == "RULE-A-001"
        assert pair["rule_b"] == "RULE-B-001"

    @pytest.mark.asyncio
    async def test_no_false_positives(self, db, checker: IntegrityChecker) -> None:
        await db.create_rule(_make_rule("RULE-A-001"))
        await db.create_rule(_make_rule("RULE-B-001"))
        await db.create_edge("DEPENDS_ON", "RULE-A-001", "RULE-B-001")

        conflicts = await checker.detect_conflicts()
        assert len(conflicts) == 0


class TestOrphanDetection:
    """Rules with zero edges."""

    @pytest.mark.asyncio
    async def test_orphan_flagged(self, db, checker: IntegrityChecker) -> None:
        await db.create_rule(_make_rule("ORPHAN-RULE-001"))

        orphans = await checker.detect_orphans()
        assert "ORPHAN-RULE-001" in orphans

    @pytest.mark.asyncio
    async def test_connected_rule_not_orphan(self, db, checker: IntegrityChecker) -> None:
        await db.create_rule(_make_rule("RULE-A-001"))
        await db.create_rule(_make_rule("RULE-B-001"))
        await db.create_edge("RELATED_TO", "RULE-A-001", "RULE-B-001")

        orphans = await checker.detect_orphans()
        assert "RULE-A-001" not in orphans
        assert "RULE-B-001" not in orphans


class TestStalenessDetection:
    """Rules past staleness window."""

    @pytest.mark.asyncio
    async def test_stale_rule_flagged(self, db, checker: IntegrityChecker) -> None:
        old_date = (date.today() - timedelta(days=400)).isoformat()
        await db.create_rule(_make_rule("STALE-RULE-001", last_validated=old_date, staleness_window=365))

        stale = await checker.detect_stale()
        stale_ids = [s["rule_id"] for s in stale]
        assert "STALE-RULE-001" in stale_ids

    @pytest.mark.asyncio
    async def test_fresh_rule_not_flagged(self, db, checker: IntegrityChecker) -> None:
        today = date.today().isoformat()
        await db.create_rule(_make_rule("FRESH-RULE-001", last_validated=today))

        stale = await checker.detect_stale()
        stale_ids = [s["rule_id"] for s in stale]
        assert "FRESH-RULE-001" not in stale_ids


@pytest.mark.skipif(
    importlib.util.find_spec("sentence_transformers") is None,
    reason="redundancy detection needs sentence-transformers ([fallback] extra); "
    "production installs exclude it (ONNX is the core embedding path). "
    "The library-absent behaviour is covered by the *MissingLibrary tests.",
)
class TestRedundancyDetection:
    """Near-identical rule content detection."""

    @pytest.mark.asyncio
    async def test_near_identical_flagged(self, db, checker: IntegrityChecker) -> None:
        await db.create_rule(_make_rule(
            "DUP-A-001",
            trigger="Controller must not contain SQL queries directly",
            statement="All data access must go through repository layer",
        ))
        await db.create_rule(_make_rule(
            "DUP-B-001",
            trigger="Controller must not contain SQL queries directly",
            statement="All data access must go through repository layer",
        ))

        redundant = await checker.detect_redundant()
        assert len(redundant) >= 1
        pair = redundant[0]
        ids = {pair["rule_a"], pair["rule_b"]}
        assert ids == {"DUP-A-001", "DUP-B-001"}

    @pytest.mark.asyncio
    async def test_different_rules_clean(self, db, checker: IntegrityChecker) -> None:
        await db.create_rule(_make_rule(
            "DIFF-A-001",
            trigger="SQL query uses positional placeholders",
            statement="Use named bind parameters instead of positional",
        ))
        await db.create_rule(_make_rule(
            "DIFF-B-001",
            trigger="Class hierarchy exceeds 2 levels",
            statement="Refactor to use composition via constructor injection",
        ))

        redundant = await checker.detect_redundant()
        assert len(redundant) == 0

    @pytest.mark.asyncio
    async def test_detect_redundant_raises_when_sentence_transformers_missing(
        self,
        db,
        checker: IntegrityChecker,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """detect_redundant() must raise RuntimeError when
        sentence_transformers cannot be imported, not silently return [].

        Same bug class as the silent ONNX fallback fixed in commit
        dae679a: an empty list when the dependency is missing is
        wire-format-identical to "no redundancies found", and the
        caller (`writ validate`) cannot distinguish the two cases.
        The new contract surfaces the missing-dependency state
        explicitly via a RuntimeError that names the [fallback] install
        command and the skip_redundancy=True opt-out for callers that
        intentionally exclude this check.
        """
        import sys

        # Need at least 2 rules so detect_redundant does not early-return
        # on len(rules) < 2 before reaching the sentence_transformers
        # import.
        await db.create_rule(_make_rule("RULE-A-001"))
        await db.create_rule(_make_rule("RULE-B-001"))

        monkeypatch.setitem(sys.modules, "sentence_transformers", None)

        with pytest.raises(RuntimeError) as excinfo:
            await checker.detect_redundant()

        msg = str(excinfo.value)
        assert "sentence" in msg.lower(), (
            f"RuntimeError must name sentence-transformers; got: {msg!r}"
        )
        assert "fallback" in msg, (
            f"RuntimeError must name the [fallback] extras group; got: {msg!r}"
        )
        assert "pip install" in msg, (
            f"RuntimeError must name the pip install verb; got: {msg!r}"
        )
        assert "skip_redundancy" in msg, (
            f"RuntimeError must name the skip_redundancy=True opt-out so "
            f"callers reading the error see the supported intentional-"
            f"exclusion path; got: {msg!r}"
        )


class TestRunAllChecks:
    """Orchestrator behavior."""

    @pytest.mark.asyncio
    async def test_clean_graph_returns_zero(self, db, checker: IntegrityChecker) -> None:
        await db.create_rule(_make_rule("RULE-A-001"))
        await db.create_rule(_make_rule("RULE-B-001"))
        await db.create_edge("RELATED_TO", "RULE-A-001", "RULE-B-001")

        findings = await checker.run_all_checks(skip_redundancy=True)
        assert findings["exit_code"] == 0

    @pytest.mark.asyncio
    async def test_any_finding_returns_nonzero(self, db, checker: IntegrityChecker) -> None:
        await db.create_rule(_make_rule("RULE-A-001"))
        await db.create_rule(_make_rule("RULE-B-001"))
        await db.create_edge("CONFLICTS_WITH", "RULE-A-001", "RULE-B-001")

        findings = await checker.run_all_checks(skip_redundancy=True)
        assert findings["exit_code"] == 1
        assert len(findings["conflicts"]) == 1

    @pytest.mark.asyncio
    async def test_run_all_checks_sets_redundancy_unavailable_when_library_missing(
        self,
        db,
        checker: IntegrityChecker,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """run_all_checks(skip_redundancy=False) must catch the
        RuntimeError from detect_redundant() and surface the missing-
        dependency state via findings['redundancy_unavailable'] rather
        than killing the entire integrity scan.

        Degrade-loud-but-continue: one of five checks losing its
        dependency does not stop the other four (conflicts, orphans,
        stale, confidence-defaults) from reporting. The redundancy_
        unavailable state is informational; it does not by itself
        drive exit_code (exit_code reflects "we ran a check and found
        problems", not "we could not run a check").
        """
        import sys

        await db.create_rule(_make_rule("RULE-A-001"))
        await db.create_rule(_make_rule("RULE-B-001"))
        await db.create_edge("CONFLICTS_WITH", "RULE-A-001", "RULE-B-001")

        monkeypatch.setitem(sys.modules, "sentence_transformers", None)

        findings = await checker.run_all_checks(skip_redundancy=False)

        # Redundancy was attempted but the library was missing.
        assert "redundancy_unavailable" in findings, (
            "run_all_checks must surface the missing-dep state via "
            "the redundancy_unavailable key; got keys: "
            f"{sorted(findings.keys())}"
        )
        assert findings["redundancy_unavailable"], (
            "redundancy_unavailable must contain a non-empty message "
            "so the caller can print an actionable line; got: "
            f"{findings['redundancy_unavailable']!r}"
        )
        assert findings["redundant"] == [], (
            "redundant must remain an empty list when the check could "
            "not run; got: {findings['redundant']!r}"
        )

        # The other checks still ran. The crafted conflict surfaces.
        assert len(findings["conflicts"]) == 1, (
            f"conflicts check must still run; got: {findings['conflicts']!r}"
        )

        # Exit code is non-zero because of the real conflict, not
        # because redundancy was unavailable. The redundancy_unavailable
        # state is informational; it must not by itself drive exit_code.
        assert findings["exit_code"] == 1
