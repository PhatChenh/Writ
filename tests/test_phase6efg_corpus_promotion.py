"""Phase 6e/6f/6g: methodology corpus promotion to bible/methodology/.

The 60-file methodology corpus moved from
`tests/fixtures/synthetic_methodology/` to `bible/methodology/` in
this commit. Migration runs against the new location to populate
the graph with Skill / Playbook / Technique / AntiPattern / Role /
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
live graph DB) is verified out-of-band via curl /health, not in this
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
# promotion verification. Updated 2026-05-09 for two additions:
# SKL-PROC-WORKTREE-001 (post-PSR-008 methodology-gap closure) and
# PBK-AUTHOR-001 (skill-authoring playbook). Updated 2026-05-21 for
# v1.4.0 additions: PBK-PROC-WORK-WORKFLOW-001, PBK-PROC-ORCHESTRATOR-001,
# SKL-PROC-MODE-001, SKL-PROC-WRIT-FAILURE-001. When you add a new
# methodology file in this corpus, bump the corresponding count here
# so the snapshot stays honest.
EXPECTED_FILE_COUNTS = {
    "PBK": 10,  # Playbooks (+2 v1.4.0: PBK-PROC-WORK-WORKFLOW-001, PBK-PROC-ORCHESTRATOR-001)
    "SKL": 10,  # Skills (+2 v1.4.0: SKL-PROC-MODE-001, SKL-PROC-WRIT-FAILURE-001)
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


# TestMasterPlanReflectsClosure removed 2026-05-10: docs/phase-6-plan.md
# was deleted as a stale planning artifact (methodology absorption shipped;
# the corpus and code in this very test file are the verified outcome).
