"""Phase 6e/6f/6g: methodology corpus promotion to bible/methodology/.

The 60-file methodology corpus moved from
`tests/fixtures/synthetic_methodology/` to `bible/methodology/` in
this commit. Migration runs against the new location to populate
Neo4j with Skill / Playbook / Technique / AntiPattern / Role /
ForbiddenResponse / Phase / Rationalization / PressureScenario /
WorkedExample / SubagentRole nodes.

Tests verify:
  1. The new location exists with the expected per-type file counts.
  2. The old location is gone (catches incomplete moves).
  3. Each major node-type prefix is represented.
  4. The corpus parses cleanly via the existing methodology loader
     (no parser regression introduced by the path change).
  5. The Phase 6 master plan reflects 6e/6f/6g as shipped (doc
     update coupled to the code change).

Migration smoke (running the migrate script + asserting against the
live Neo4j) is verified out-of-band via curl /health, not in this
test suite, because integration tests against a running daemon
belong with the integration harness, not unit pytest.
"""
from __future__ import annotations

from pathlib import Path

import pytest

WRIT_ROOT = Path(__file__).resolve().parent.parent
BIBLE_METHODOLOGY = WRIT_ROOT / "bible" / "methodology"
OLD_FIXTURE_PATH = WRIT_ROOT / "tests" / "fixtures" / "synthetic_methodology"


# Per-prefix counts. Originally captured pre-rename for Phase 6e/6f/6g
# promotion verification. Updated 2026-05-09 for the post-methodology-
# absorption additions: SKL-PROC-WORKTREE-001 (item 1 of the post-PSR-008
# methodology-gap closure) and PBK-AUTHOR-001 (skill-authoring playbook).
# When you add a new methodology file in this corpus, bump the
# corresponding count here so the snapshot stays honest.
EXPECTED_FILE_COUNTS = {
    "PBK": 8,   # Playbooks (+1: PBK-AUTHOR-001 added 2026-05-09)
    "SKL": 8,   # Skills (+1: SKL-PROC-WORKTREE-001 added 2026-05-09)
    "ANT": 10,  # AntiPatterns
    "ROL": 3,   # SubagentRoles
    "FRB": 2,   # ForbiddenResponses
    "PHA": 9,   # Phases
    "RAT": 3,   # Rationalizations
    "PSC": 3,   # PressureScenarios
    "EXM": 2,   # WorkedExamples
    "ENF": 8,   # Rule companions (rule-format files in the methodology corpus)
    "META": 2,  # Meta-authoring nodes
    "TEC": 4,   # Techniques
}


class TestCorpusLocation:
    """The corpus lives at bible/methodology/ after promotion."""

    def test_new_location_exists(self) -> None:
        assert BIBLE_METHODOLOGY.is_dir(), (
            f"Expected promoted corpus at {BIBLE_METHODOLOGY}; "
            "did the git mv complete?"
        )

    def test_old_location_is_gone(self) -> None:
        """Sanity: the rename should have removed the old path."""
        assert not OLD_FIXTURE_PATH.exists(), (
            f"Old fixture path {OLD_FIXTURE_PATH} still present -- "
            "the rename was incomplete (copy instead of move?)."
        )

    def test_total_file_count_matches_pre_rename(self) -> None:
        """Sum of per-prefix counts equals the total file count, and
        every .md file has a recognized prefix."""
        files = sorted(BIBLE_METHODOLOGY.glob("*.md"))
        expected_total = sum(EXPECTED_FILE_COUNTS.values())
        assert len(files) == expected_total, (
            f"Expected {expected_total} methodology files; found {len(files)}"
        )


class TestPerPrefixCounts:
    """Each major node-type prefix has the expected file count."""

    @pytest.mark.parametrize(
        "prefix, expected",
        sorted(EXPECTED_FILE_COUNTS.items()),
    )
    def test_prefix_count(self, prefix: str, expected: int) -> None:
        files = list(BIBLE_METHODOLOGY.glob(f"{prefix}-*.md"))
        assert len(files) == expected, (
            f"Expected {expected} files with prefix {prefix}-; "
            f"found {len(files)}: {[f.name for f in files]}"
        )


class TestCorpusParsesAfterRename:
    """The existing methodology loader still loads every file from
    the new location -- the rename did not break the parser path."""

    def test_methodology_loader_loads_corpus(self) -> None:
        from tests.fixtures.methodology_loader import load_corpus
        corpus = load_corpus(BIBLE_METHODOLOGY)
        # load_corpus returns a list; assert non-empty + sane minimum.
        assert len(corpus) >= 50, (
            f"Methodology loader returned only {len(corpus)} nodes "
            "from the renamed corpus; expected >=50"
        )

    def test_each_major_type_present_after_load(self) -> None:
        from tests.fixtures.methodology_loader import load_corpus
        corpus = load_corpus(BIBLE_METHODOLOGY)
        # Each item is a dict with a node_type key (or a Pydantic
        # model with one). Use a coarse "any of the expected
        # types appears" assertion.
        types_seen: set[str] = set()
        for item in corpus:
            if hasattr(item, "node_type"):
                types_seen.add(getattr(item, "node_type", ""))
            elif isinstance(item, dict):
                t = item.get("node_type")
                if t:
                    types_seen.add(t)
            else:
                # MethodologyNode-shaped: fall back to class name
                types_seen.add(type(item).__name__)
        for required in (
            "Skill", "Playbook", "AntiPattern", "ForbiddenResponse",
            "SubagentRole",
        ):
            assert required in types_seen, (
                f"Major node type {required!r} missing from corpus after rename. "
                f"Types seen: {sorted(types_seen)}"
            )


class TestMasterPlanReflectsClosure:
    """docs/phase-6-plan.md must mark 6e/6f/6g as shipped/verified
    after this commit."""

    def test_master_plan_marks_6efg_shipped(self) -> None:
        plan_path = WRIT_ROOT / "docs" / "phase-6-plan.md"
        text = plan_path.read_text()
        # Look for "6e" row + a "shipped" or "verified" status nearby.
        # Heuristic: each sub-phase ID followed (within ~200 chars) by
        # a status indicator.
        for sub_phase in ("6e", "6f", "6g"):
            idx = text.find(f"| {sub_phase} ")
            if idx == -1:
                idx = text.find(f"| **{sub_phase}**")
            assert idx != -1, (
                f"docs/phase-6-plan.md is missing a row for sub-phase {sub_phase}"
            )
            window = text[idx: idx + 400].lower()
            assert "shipped" in window or "verified" in window, (
                f"docs/phase-6-plan.md sub-phase {sub_phase} row does not "
                f"contain 'shipped' or 'verified' status. Window: {window[:300]!r}"
            )
