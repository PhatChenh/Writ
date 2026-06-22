"""v1.5.0 -- Unified `writ import-markdown` CLI tests.

Covers the full behavior matrix introduced in v1.5.0:
- Default (no flags) imports every node type under bible/
- --only TYPE[,TYPE,...] filters to the named subset
- --dry-run parses + validates without DB writes
- Error reporting: structured IngestError (no raw Pydantic tracebacks)
- Edge creation alongside node creation
- Idempotency (MERGE semantics)
- scripts/migrate.py shim contract preservation
- Version-bump assertions

All tests FAIL until the implementation phase lands.
"""

from __future__ import annotations

import asyncio
import re
import subprocess
import sys
from pathlib import Path

import pytest

SKILL_DIR = (Path.home() / ".claude/skills/writ")
REPO_ROOT = Path(__file__).resolve().parent.parent

# Shared resolver -- one source of truth for invoking `writ` from tests.
from tests._writ_cmd import WRIT_CMD_PREFIX as _WRIT_CMD_PREFIX, WRIT_CLI


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------

_prod_db = None


def _get_prod_db():
    """Lazily create and cache a FalkorDBLiteConnection to the production graph."""
    global _prod_db
    if _prod_db is None:
        from writ.config import (
            get_falkordb_path,
            get_falkordb_graph,
            get_falkordb_module,
            get_redis_bin,
        )
        from writ.graph.db import FalkorDBLiteConnection

        _prod_db = FalkorDBLiteConnection(
            db_path=get_falkordb_path(),
            graph=get_falkordb_graph(),
            module_path=get_falkordb_module(),
            redis_bin=get_redis_bin(),
        )
    return _prod_db


def _cypher(query: str) -> int:
    """Run a read-only Cypher query via FalkorDB and return the integer result."""
    db = _get_prod_db()
    rows = db._execute_query(query)
    if rows:
        return int(list(rows[0].values())[0])
    pytest.skip(f"Cypher query returned no rows: {query!r}")


def _close_prod_db() -> None:
    """Release the cached prod-graph connection (and its lockfile) so a
    `writ import-markdown` subprocess can acquire the same single-writer lock.

    SKILL_DIR (~/.claude/skills/writ) and the repo share one .writ/graph.lock
    (SKILL_DIR is the install/symlink), so a held connection would otherwise
    deadlock the subprocess with "graph DB is locked". The next _get_prod_db()
    re-opens lazily after the subprocess has exited and released its own lock.
    """
    global _prod_db
    if _prod_db is not None:
        try:
            asyncio.run(_prod_db.close())
        except Exception:
            pass
        _prod_db = None


def _run_import(*args: str, cwd: Path = SKILL_DIR) -> subprocess.CompletedProcess:
    """Run `writ import-markdown` with the given args and return the completed process."""
    _close_prod_db()  # release the lock so the subprocess can take it
    return subprocess.run(
        [*_WRIT_CMD_PREFIX, "import-markdown", *args],
        cwd=str(cwd),
        capture_output=True,
        text=True,
        timeout=120,
    )


def _clear_graph() -> None:
    """Wipe the graph so each test starts from a clean slate."""
    db = _get_prod_db()
    db._execute_query("MATCH (n) DETACH DELETE n")


# ---------------------------------------------------------------------------
# Class TestImportMarkdownDefaultBehavior
# ---------------------------------------------------------------------------

class TestImportMarkdownDefaultBehavior:
    """writ import-markdown (no flags) must import all node types."""

    def test_default_imports_everything_from_bible(self) -> None:
        """Run 'writ import-markdown bible/' and assert Rule + Skill + Playbook exist
        plus at least one methodology edge."""
        _clear_graph()
        result = _run_import("bible/")
        assert result.returncode == 0, (
            f"import-markdown bible/ failed:\nstdout={result.stdout}\nstderr={result.stderr}"
        )

        rule_count = _cypher("MATCH (n:Rule) RETURN count(n)")
        assert rule_count > 0, "Expected at least one Rule node after full import"

        skill_count = _cypher("MATCH (n:Skill) RETURN count(n)")
        assert skill_count > 0, "Expected at least one Skill node after full import"

        playbook_count = _cypher("MATCH (n:Playbook) RETURN count(n)")
        assert playbook_count > 0, "Expected at least one Playbook node after full import"

        edge_count = _cypher(
            "MATCH ()-[e]->() WHERE type(e) IN "
            "['TEACHES','GATES','PRECEDES','DEMONSTRATES','COUNTERS',"
            "'DISPATCHES','PRESSURE_TESTS','CONTAINS','ATTACHED_TO'] "
            "RETURN count(e)"
        )
        assert edge_count > 0, (
            "Expected at least one methodology edge (TEACHES/GATES/PRECEDES/...) "
            "after full import"
        )

    def test_default_no_path_defaults_to_bible(self) -> None:
        """'writ import-markdown' with no path arg must behave identically to
        'writ import-markdown bible/'."""
        _clear_graph()
        no_arg = _run_import()
        assert no_arg.returncode == 0, (
            f"import-markdown (no args) failed:\nstdout={no_arg.stdout}\nstderr={no_arg.stderr}"
        )
        count_no_arg = _cypher("MATCH (n:Rule) RETURN count(n)")
        assert count_no_arg > 0, (
            "No Rule nodes after no-arg invocation; default path may not be 'bible/'"
        )

        skill_no_arg = _cypher("MATCH (n:Skill) RETURN count(n)")
        assert skill_no_arg > 0, (
            "No Skill nodes after no-arg invocation; default import should include methodology"
        )

    def test_default_reports_counts_per_node_type(self) -> None:
        """Stdout must include per-type count breakdown mentioning Rule, Skill, and Playbook."""
        result = _run_import("bible/")
        assert result.returncode == 0, (
            f"import-markdown failed:\nstdout={result.stdout}\nstderr={result.stderr}"
        )
        output = result.stdout + result.stderr

        # All three type names must appear.
        assert "Rule" in output, (
            f"Expected 'Rule' in import output; got:\n{output}"
        )
        assert "Skill" in output, (
            f"Expected 'Skill' in import output; got:\n{output}"
        )
        assert "Playbook" in output, (
            f"Expected 'Playbook' in import output; got:\n{output}"
        )

        # Each type name must appear near a digit on the same or adjacent line.
        for type_name in ("Rule", "Skill", "Playbook"):
            pattern = re.compile(
                rf"(?:{type_name}\D{{0,30}}\d|\d\D{{0,30}}{type_name})"
            )
            assert pattern.search(output), (
                f"Expected a numeric count near '{type_name}' in output; got:\n{output}"
            )


# ---------------------------------------------------------------------------
# Class TestImportMarkdownOnlyFilter
# ---------------------------------------------------------------------------

class TestImportMarkdownOnlyFilter:
    """--only TYPE[,TYPE,...] must restrict ingestion to the named types."""

    def test_only_rule_matches_old_behavior(self) -> None:
        """--only Rule imports Rule nodes only; no non-Rule nodes created."""
        _clear_graph()
        result = _run_import("bible/", "--only", "Rule")
        assert result.returncode == 0, (
            f"--only Rule failed:\nstdout={result.stdout}\nstderr={result.stderr}"
        )

        rule_count = _cypher("MATCH (n:Rule) RETURN count(n)")
        assert rule_count > 0, "Expected Rule nodes after --only Rule"

        non_rule_count = _cypher(
            "MATCH (n) WHERE NOT n:Rule RETURN count(n)"
        )
        assert non_rule_count == 0, (
            f"Expected zero non-Rule nodes after --only Rule; got {non_rule_count}"
        )

    def test_only_skill_imports_only_skills(self) -> None:
        """--only Skill imports Skill nodes only; no Rule / Playbook nodes."""
        _clear_graph()
        result = _run_import("bible/", "--only", "Skill")
        assert result.returncode == 0, (
            f"--only Skill failed:\nstdout={result.stdout}\nstderr={result.stderr}"
        )

        skill_count = _cypher("MATCH (n:Skill) RETURN count(n)")
        assert skill_count > 0, "Expected Skill nodes after --only Skill"

        rule_count = _cypher("MATCH (n:Rule) RETURN count(n)")
        assert rule_count == 0, (
            f"Expected zero Rule nodes after --only Skill; got {rule_count}"
        )

        playbook_count = _cypher("MATCH (n:Playbook) RETURN count(n)")
        assert playbook_count == 0, (
            f"Expected zero Playbook nodes after --only Skill; got {playbook_count}"
        )

    def test_only_multiple_types_comma_separated(self) -> None:
        """--only Skill,Playbook creates only Skill and Playbook; no Rule or AntiPattern."""
        _clear_graph()
        result = _run_import("bible/", "--only", "Skill,Playbook")
        assert result.returncode == 0, (
            f"--only Skill,Playbook failed:\nstdout={result.stdout}\nstderr={result.stderr}"
        )

        skill_count = _cypher("MATCH (n:Skill) RETURN count(n)")
        assert skill_count > 0, "Expected Skill nodes after --only Skill,Playbook"

        playbook_count = _cypher("MATCH (n:Playbook) RETURN count(n)")
        assert playbook_count > 0, "Expected Playbook nodes after --only Skill,Playbook"

        rule_count = _cypher("MATCH (n:Rule) RETURN count(n)")
        assert rule_count == 0, (
            f"Expected zero Rule nodes after --only Skill,Playbook; got {rule_count}"
        )

        antipattern_count = _cypher("MATCH (n:AntiPattern) RETURN count(n)")
        assert antipattern_count == 0, (
            f"Expected zero AntiPattern nodes after --only Skill,Playbook; got {antipattern_count}"
        )

    def test_only_with_whitespace_in_csv(self) -> None:
        """--only 'Skill, Playbook' (space after comma) must be tolerated."""
        _clear_graph()
        # Pass as a single string with embedded space; Typer receives it as one arg value.
        result = _run_import("bible/", "--only", "Skill, Playbook")
        assert result.returncode == 0, (
            f"--only with space in CSV failed (code {result.returncode}):\n"
            f"stdout={result.stdout}\nstderr={result.stderr}"
        )

        skill_count = _cypher("MATCH (n:Skill) RETURN count(n)")
        assert skill_count > 0, "Expected Skill nodes after --only 'Skill, Playbook'"

        playbook_count = _cypher("MATCH (n:Playbook) RETURN count(n)")
        assert playbook_count > 0, "Expected Playbook nodes after --only 'Skill, Playbook'"

    def test_only_unknown_type_errors_cleanly(self) -> None:
        """--only Garbage must exit non-zero, mention 'Garbage', name a valid type,
        and not print a Python traceback."""
        result = _run_import("bible/", "--only", "Garbage")
        assert result.returncode != 0, (
            "Expected non-zero exit for unknown --only type 'Garbage'"
        )
        output = result.stdout + result.stderr
        assert "Garbage" in output, (
            f"Expected the unknown type 'Garbage' to appear in error output; got:\n{output}"
        )
        # At least one valid type must be named so the user knows what to type.
        valid_types_present = any(
            t in output for t in ("Rule", "Skill", "Playbook", "AntiPattern", "Technique")
        )
        assert valid_types_present, (
            f"Expected at least one valid type name in error output; got:\n{output}"
        )
        assert "Traceback (most recent call last):" not in output, (
            "Expected no raw Python traceback in output for unknown --only type"
        )

    def test_only_known_with_one_unknown_errors(self) -> None:
        """--only Skill,BogusType must exit non-zero and mention 'BogusType'."""
        result = _run_import("bible/", "--only", "Skill,BogusType")
        assert result.returncode != 0, (
            "Expected non-zero exit when one type in --only is unknown"
        )
        output = result.stdout + result.stderr
        assert "BogusType" in output, (
            f"Expected 'BogusType' to appear in error output; got:\n{output}"
        )


# ---------------------------------------------------------------------------
# Class TestImportMarkdownDryRun
# ---------------------------------------------------------------------------

class TestImportMarkdownDryRun:
    """--dry-run must parse + validate without writing to the graph."""

    def test_dry_run_no_writes(self) -> None:
        """Rule count in the graph must be identical before and after --dry-run."""
        before = _cypher("MATCH (n:Rule) RETURN count(n)")
        result = _run_import("bible/", "--dry-run")
        assert result.returncode == 0, (
            f"--dry-run failed:\nstdout={result.stdout}\nstderr={result.stderr}"
        )
        after = _cypher("MATCH (n:Rule) RETURN count(n)")
        assert before == after, (
            f"Rule count changed during --dry-run: before={before}, after={after}"
        )

    def test_dry_run_reports_what_would_be_imported(self) -> None:
        """--dry-run stdout must announce dry-run mode and include per-type counts."""
        result = _run_import("bible/", "--dry-run")
        assert result.returncode == 0, (
            f"--dry-run failed:\nstdout={result.stdout}\nstderr={result.stderr}"
        )
        output = (result.stdout + result.stderr).lower()
        announced = (
            "dry" in output
            or "would import" in output
            or "validate only" in output
        )
        assert announced, (
            "Expected --dry-run to announce dry-run mode in output; got:\n"
            + result.stdout + result.stderr
        )
        # At least one node type name with a digit should appear.
        full_output = result.stdout + result.stderr
        has_count = re.search(r"(Rule|Skill|Playbook)\D{0,30}\d", full_output)
        assert has_count, (
            "Expected per-type count in --dry-run output; got:\n" + full_output
        )

    def test_dry_run_combined_with_only(self) -> None:
        """--only Skill --dry-run must not write AND report only Skill counts."""
        before = _cypher("MATCH (n:Skill) RETURN count(n)")
        result = _run_import("bible/", "--only", "Skill", "--dry-run")
        assert result.returncode == 0, (
            f"--only Skill --dry-run failed:\nstdout={result.stdout}\nstderr={result.stderr}"
        )
        after = _cypher("MATCH (n:Skill) RETURN count(n)")
        assert before == after, (
            f"Skill count changed during --only Skill --dry-run: before={before}, after={after}"
        )
        output = result.stdout + result.stderr
        assert "Skill" in output, (
            "Expected 'Skill' in --only Skill --dry-run output; got:\n" + output
        )
        # Rule must NOT appear as an ingested type since --only Skill was set.
        # (It may appear as "0 Rule" or not at all; either is acceptable, but
        # if it appears with a positive count that is a bug.)
        rule_count_in_report = re.search(r"Rule\D{0,20}([1-9]\d*)", output)
        assert rule_count_in_report is None, (
            f"Expected no positive Rule count in --only Skill --dry-run report; got:\n{output}"
        )


# ---------------------------------------------------------------------------
# Class TestImportMarkdownErrorReporting
# ---------------------------------------------------------------------------

class TestImportMarkdownErrorReporting:
    """Validation errors must surface with file path + field name; no raw tracebacks."""

    def test_validation_error_includes_file_path(self, tmp_path: Path) -> None:
        """A methodology YAML with staleness_window: P6M (string) must produce
        an error that names the file path and 'staleness_window', with no raw
        pydantic_core ValidationError substring."""
        bad_md = tmp_path / "BAD-SKL-001.md"
        bad_md.write_text(
            "---\n"
            "node_type: Skill\n"
            "skill_id: BAD-SKL-001\n"
            "name: Bad Skill\n"
            "staleness_window: P6M\n"
            "---\n"
            "# Bad Skill\n"
            "Content here.\n",
            encoding="utf-8",
        )
        result = _run_import(str(tmp_path))
        output = result.stdout + result.stderr

        assert str(bad_md) in output or bad_md.name in output, (
            f"Expected the file path or name in error output; got:\n{output}"
        )
        assert "staleness_window" in output, (
            f"Expected 'staleness_window' field name in error output; got:\n{output}"
        )
        assert "pydantic_core._pydantic_core.ValidationError" not in output, (
            "Expected no raw pydantic_core.ValidationError in output (API-ERROR-002)"
        )

    def test_validation_error_does_not_abort_other_files(self, tmp_path: Path) -> None:
        """With one valid and one invalid file, the valid file is ingested,
        the invalid one is reported, and the run does not silently drop both."""
        good_md = tmp_path / "SKL-TEST-PARTIAL-001.md"
        good_md.write_text(
            "---\n"
            "node_type: Skill\n"
            "skill_id: SKL-TEST-PARTIAL-001\n"
            "name: Good Test Skill\n"
            "domain: test\n"
            "severity: low\n"
            "scope: session\n"
            "trigger: \"Test trigger for partial-success ingestion.\"\n"
            "statement: \"Test statement for partial-success ingestion.\"\n"
            "rationale: \"Test rationale for partial-success ingestion.\"\n"
            "last_validated: 2026-05-21\n"
            "staleness_window: 365\n"
            "---\n"
            "# Good Skill\n"
            "Content here.\n",
            encoding="utf-8",
        )
        bad_md = tmp_path / "SKL-TEST-PARTIAL-002.md"
        bad_md.write_text(
            "---\n"
            "node_type: Skill\n"
            "skill_id: SKL-TEST-PARTIAL-002\n"
            "name: Bad Skill\n"
            "domain: test\n"
            "severity: low\n"
            "scope: session\n"
            "trigger: \"Test trigger.\"\n"
            "statement: \"Test statement.\"\n"
            "rationale: \"Test rationale.\"\n"
            "last_validated: 2026-05-21\n"
            "staleness_window: P6M\n"
            "---\n"
            "# Bad Skill\n"
            "Content here.\n",
            encoding="utf-8",
        )

        result = _run_import(str(tmp_path))
        output = result.stdout + result.stderr

        # The run should exit non-zero (partial failure) OR 0 if partial success is
        # acceptable; either way it must mention both files.
        assert good_md.name in output or "SKL-TEST-PARTIAL-001" in output, (
            f"Expected the valid file or its ID in output; got:\n{output}"
        )
        assert bad_md.name in output or "SKL-TEST-PARTIAL-002" in output, (
            f"Expected the invalid file or its ID in output; got:\n{output}"
        )

        # The valid skill must have been ingested.
        skill_count = _cypher(
            "MATCH (n:Skill {skill_id: 'SKL-TEST-PARTIAL-001'}) RETURN count(n)"
        )
        assert skill_count > 0, (
            "Expected SKL-TEST-PARTIAL-001 to be ingested despite co-existing invalid file"
        )


# ---------------------------------------------------------------------------
# Class TestImportMarkdownEdgeCases
# ---------------------------------------------------------------------------

class TestImportMarkdownEdgeCases:
    """Edge creation, idempotency, and path-scoping."""

    def test_edges_created_alongside_methodology_nodes(self) -> None:
        """After a full import, at least one TEACHES edge must exist."""
        _clear_graph()
        result = _run_import("bible/")
        assert result.returncode == 0, (
            f"Full import failed:\nstdout={result.stdout}\nstderr={result.stderr}"
        )
        teaches_count = _cypher("MATCH ()-[e:TEACHES]->() RETURN count(e)")
        assert teaches_count > 0, (
            "Expected at least one TEACHES edge after full import; "
            "edge creation pipeline may be broken"
        )

    def test_rerun_is_idempotent(self) -> None:
        """Running import twice must not duplicate nodes (MERGE semantics)."""
        _clear_graph()
        _run_import("bible/")
        rule_count_first = _cypher("MATCH (n:Rule) RETURN count(n)")
        skill_count_first = _cypher("MATCH (n:Skill) RETURN count(n)")

        _run_import("bible/")
        rule_count_second = _cypher("MATCH (n:Rule) RETURN count(n)")
        skill_count_second = _cypher("MATCH (n:Skill) RETURN count(n)")

        assert rule_count_first == rule_count_second, (
            f"Rule count changed on re-import: first={rule_count_first}, "
            f"second={rule_count_second}; MERGE semantics violated"
        )
        assert skill_count_first == skill_count_second, (
            f"Skill count changed on re-import: first={skill_count_first}, "
            f"second={skill_count_second}; MERGE semantics violated"
        )

    def test_path_argument_can_be_subdirectory(self) -> None:
        """'writ import-markdown bible/methodology' must create methodology nodes
        and the Rule nodes that legitimately live in bible/methodology/ (the
        ENF-PROC-* enforcement rules), but must NOT pull in Rule nodes from
        other bible subdirectories like bible/security/."""
        _clear_graph()
        # Count Rule files actually under bible/methodology/ via YAML front-matter.
        # Keep this dynamic so the assertion tracks the on-disk corpus.
        methodology_rule_files = sorted(
            p for p in (SKILL_DIR / "bible" / "methodology").glob("*.md")
            if p.read_text(encoding="utf-8").splitlines()[:15].__iter__()
            and any(
                line.startswith("rule_id:")
                for line in p.read_text(encoding="utf-8").splitlines()[:15]
            )
        )
        expected_methodology_rules = len(methodology_rule_files)

        result = _run_import("bible/methodology")
        assert result.returncode == 0, (
            f"import-markdown bible/methodology failed:\n"
            f"stdout={result.stdout}\nstderr={result.stderr}"
        )
        methodology_count = _cypher(
            "MATCH (n) WHERE n:Skill OR n:Playbook OR n:AntiPattern "
            "OR n:Technique OR n:Phase RETURN count(n)"
        )
        assert methodology_count > 0, (
            "Expected methodology nodes after targeting bible/methodology"
        )

        # Rule count must equal exactly the number of Rule files under
        # bible/methodology/ (subdirectory scoping must not pull in security,
        # architecture, etc.). Currently this is the 10 ENF-PROC-*
        # enforcement rules attached to methodology nodes.
        rule_count = _cypher("MATCH (n:Rule) RETURN count(n)")
        assert rule_count == expected_methodology_rules, (
            f"Expected exactly {expected_methodology_rules} Rule nodes (the "
            f"Rule files actually under bible/methodology/); got {rule_count}"
        )

        # Spot-check: a known non-methodology rule (security) must NOT be
        # present, proving subdirectory scoping was honored.
        sec_rule_count = _cypher(
            "MATCH (n:Rule {rule_id: 'SEC-AUTH-MFA-001'}) RETURN count(n)"
        )
        assert sec_rule_count == 0, (
            "Expected SEC-AUTH-MFA-001 (security rule) to NOT be ingested when "
            "targeting bible/methodology only; subdirectory scoping broken"
        )

    def test_subdir_import_does_not_trigger_full_graph_auto_export(self) -> None:
        """Subdirectory imports must skip the auto-export step.

        Regression: prior to the fix, `writ import-markdown bible/methodology/`
        would auto-export the WHOLE graph through a file-location lookup that
        only scanned the imported subdir. Rules whose original files lived
        outside scope (e.g. process domain in `bible/process/rules.md`) fell
        through to `<output_dir>/<domain>/rules.md`, creating bogus duplicates
        like `bible/methodology/process/rules.md`. Fixed by gating auto-export
        on `path.resolve() == DEFAULT_BIBLE_DIR.resolve()`.
        """
        methodology_dir = SKILL_DIR / "bible" / "methodology"
        # Snapshot existing top-level direct children so we can detect new ones.
        before = {p.name for p in methodology_dir.iterdir()}

        result = _run_import("bible/methodology")
        assert result.returncode == 0, (
            f"import-markdown bible/methodology failed:\n"
            f"stdout={result.stdout}\nstderr={result.stderr}"
        )

        after = {p.name for p in methodology_dir.iterdir()}
        new_entries = after - before
        # If any new directory appears under bible/methodology/ containing a
        # rules.md, that is the regression: the auto-export wrote the full
        # graph into the subdir scope.
        bogus_subdirs = {
            name for name in new_entries
            if (methodology_dir / name).is_dir()
            and (methodology_dir / name / "rules.md").exists()
        }
        assert not bogus_subdirs, (
            f"Auto-export wrote bogus domain subdirs under bible/methodology/: "
            f"{sorted(bogus_subdirs)}. Auto-export must not fire on subdirectory "
            f"imports."
        )
        # Also confirm the methodology-scope .export_timestamp was not written.
        meth_ts = methodology_dir / ".export_timestamp"
        assert not meth_ts.exists() or meth_ts.name in before, (
            f"Auto-export wrote {meth_ts} on a subdirectory import; "
            f"the export-timestamp should only appear at the bible/ root."
        )

    def test_default_root_import_still_triggers_auto_export(self) -> None:
        """The fix must NOT break the full-bible-root case.

        Running `writ import-markdown bible/` (the default) should still
        produce an export-timestamp at bible/.export_timestamp, because that
        is a true round-trip from the canonical source.
        """
        bible_dir = SKILL_DIR / "bible"
        ts_path = bible_dir / ".export_timestamp"
        before_mtime = ts_path.stat().st_mtime if ts_path.exists() else 0.0

        result = _run_import("bible/")
        assert result.returncode == 0, (
            f"import-markdown bible/ failed:\n"
            f"stdout={result.stdout}\nstderr={result.stderr}"
        )

        assert ts_path.exists(), (
            "bible/.export_timestamp must exist after a default-root import "
            "(auto-export should have fired)"
        )
        assert ts_path.stat().st_mtime >= before_mtime, (
            "bible/.export_timestamp mtime did not advance after default-root "
            "import; auto-export likely did not fire"
        )


# ---------------------------------------------------------------------------
# Class TestMigrateScriptShimContract
# ---------------------------------------------------------------------------

class TestMigrateScriptShimContract:
    """scripts/migrate.py must remain importable and callable as a thin shim."""

    def test_migrate_script_still_imports(self) -> None:
        """'import scripts.migrate' must succeed after the shim refactor."""
        import importlib
        import sys

        # Ensure the skill root is on sys.path for the import.
        skill_root = str(SKILL_DIR)
        inserted = False
        if skill_root not in sys.path:
            sys.path.insert(0, skill_root)
            inserted = True
        try:
            mod = importlib.import_module("scripts.migrate")
            assert mod is not None, "scripts.migrate imported as None"
        finally:
            if inserted:
                sys.path.remove(skill_root)

    def test_migrate_script_run_migration_callable(self) -> None:
        """scripts.migrate.run_migration must be a callable (shim re-export contract)."""
        import importlib
        import sys

        skill_root = str(SKILL_DIR)
        inserted = False
        if skill_root not in sys.path:
            sys.path.insert(0, skill_root)
            inserted = True
        try:
            mod = importlib.import_module("scripts.migrate")
            assert callable(getattr(mod, "run_migration", None)), (
                "scripts.migrate.run_migration is missing or not callable"
            )
        finally:
            if inserted:
                sys.path.remove(skill_root)

    def test_migrate_script_run_methodology_migration_callable(self) -> None:
        """scripts.migrate.run_methodology_migration must be callable."""
        import importlib
        import sys

        skill_root = str(SKILL_DIR)
        inserted = False
        if skill_root not in sys.path:
            sys.path.insert(0, skill_root)
            inserted = True
        try:
            mod = importlib.import_module("scripts.migrate")
            assert callable(getattr(mod, "run_methodology_migration", None)), (
                "scripts.migrate.run_methodology_migration is missing or not callable"
            )
        finally:
            if inserted:
                sys.path.remove(skill_root)

    def test_migrate_script_shim_is_small(self) -> None:
        """scripts/migrate.py must be under 80 lines (regression guard against
        re-accumulation of duplicated logic)."""
        migrate_path = SKILL_DIR / "scripts" / "migrate.py"
        assert migrate_path.exists(), f"scripts/migrate.py not found at {migrate_path}"
        lines = migrate_path.read_text(encoding="utf-8").splitlines()
        line_count = len(lines)
        assert line_count < 80, (
            f"scripts/migrate.py has {line_count} lines; expected < 80. "
            "The shim may have re-accumulated duplicated logic."
        )


# ---------------------------------------------------------------------------
# Class TestVersionBumpedTo150
# ---------------------------------------------------------------------------

class TestVersionBumpedTo150:
    """All version strings must read 1.5.0 and CHANGELOG must have the new entry."""

    def test_pyproject_version_is_1_5_0(self) -> None:
        """pyproject.toml must declare version = "1.5.0"."""
        pyproject = (SKILL_DIR / "pyproject.toml").read_text(encoding="utf-8")
        assert 'version = "1.5.0"' in pyproject, (
            "pyproject.toml does not contain version = \"1.5.0\""
        )

    def test_plugin_json_version_is_1_5_0(self) -> None:
        """`.claude-plugin/plugin.json` must have version 1.5.0."""
        import json as _json
        plugin_json = SKILL_DIR / ".claude-plugin" / "plugin.json"
        assert plugin_json.exists(), f"plugin.json not found at {plugin_json}"
        manifest = _json.loads(plugin_json.read_text(encoding="utf-8"))
        assert manifest.get("version") == "1.5.0", (
            f"plugin.json version is {manifest.get('version')!r}; expected '1.5.0'"
        )

    def test_marketplace_json_version_is_1_5_0(self) -> None:
        """`.claude-plugin/marketplace.json` must have version 1.5.0 in both locations."""
        import json as _json
        marketplace_json = SKILL_DIR / ".claude-plugin" / "marketplace.json"
        assert marketplace_json.exists(), f"marketplace.json not found at {marketplace_json}"
        data = _json.loads(marketplace_json.read_text(encoding="utf-8"))

        metadata_version = data.get("metadata", {}).get("version")
        assert metadata_version == "1.5.0", (
            f"marketplace.json metadata.version is {metadata_version!r}; expected '1.5.0'"
        )

        plugins = data.get("plugins", [])
        assert plugins, "marketplace.json has no 'plugins' array"
        plugin_version = plugins[0].get("version")
        assert plugin_version == "1.5.0", (
            f"marketplace.json plugins[0].version is {plugin_version!r}; expected '1.5.0'"
        )

    def test_changelog_has_150_entry(self) -> None:
        """CHANGELOG.md must have '## [1.5.0] - 2026-05-21' BEFORE '## [1.3.0]'.

        v1.5.0 ships the absorption and unify work as one combined release;
        there is no separate [1.4.0] entry in the changelog.
        """
        changelog = (SKILL_DIR / "CHANGELOG.md").read_text(encoding="utf-8")
        assert "## [1.5.0] - 2026-05-21" in changelog, (
            "CHANGELOG.md does not contain '## [1.5.0] - 2026-05-21'"
        )
        idx_150 = changelog.index("## [1.5.0] - 2026-05-21")
        assert "## [1.3.0]" in changelog, "CHANGELOG.md does not contain '## [1.3.0]'"
        idx_130 = changelog.index("## [1.3.0]")
        assert idx_150 < idx_130, (
            f"'## [1.5.0]' appears at position {idx_150} but '## [1.3.0]' "
            f"appears at {idx_130}; 1.5.0 entry must come before 1.3.0"
        )
