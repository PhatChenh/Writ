"""Phase 4: scripts/friction-log-delta.py snapshot/since-snapshot/reset.

The tool lets the user capture only the lines appended to
workflow-friction.log between a pre-run snapshot and a post-run call.
Stateless besides a single .friction-snapshot file holding the byte offset.

Per plan.md: 50-80 lines, no graph DB, no LLM. Pure file I/O.
"""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest

WRIT_ROOT = Path(__file__).resolve().parent.parent
DELTA_SCRIPT = WRIT_ROOT / "scripts" / "friction-log-delta.py"


def _run(args: list[str], cwd: Path) -> tuple[str, str, int]:
    proc = subprocess.run(
        [sys.executable, str(DELTA_SCRIPT), *args],
        capture_output=True, text=True, cwd=str(cwd),
    )
    return proc.stdout, proc.stderr, proc.returncode


class TestSnapshotSubcommand:
    """`snapshot` records current log size to .friction-snapshot."""

    def test_snapshot_creates_marker_file(self, tmp_path: Path) -> None:
        log = tmp_path / "workflow-friction.log"
        log.write_text("line1\nline2\n")
        stdout, stderr, code = _run(["snapshot"], cwd=tmp_path)
        assert code == 0
        marker = tmp_path / ".friction-snapshot"
        assert marker.exists()

    def test_snapshot_missing_log_exits_zero(self, tmp_path: Path) -> None:
        """No friction-log yet is valid -- snapshot records 0 bytes."""
        stdout, stderr, code = _run(["snapshot"], cwd=tmp_path)
        assert code == 0
        marker = tmp_path / ".friction-snapshot"
        assert marker.exists()

    def test_snapshot_idempotent(self, tmp_path: Path) -> None:
        """Running snapshot twice updates marker, no error."""
        log = tmp_path / "workflow-friction.log"
        log.write_text("a\nb\n")
        _run(["snapshot"], cwd=tmp_path)
        log.write_text("a\nb\nc\n")
        stdout, stderr, code = _run(["snapshot"], cwd=tmp_path)
        assert code == 0


class TestSinceSnapshotSubcommand:
    """`since-snapshot` emits lines appended after the snapshot."""

    def test_emits_only_new_lines(self, tmp_path: Path) -> None:
        log = tmp_path / "workflow-friction.log"
        log.write_text("before1\nbefore2\n")
        _run(["snapshot"], cwd=tmp_path)
        with log.open("a") as f:
            f.write("after1\nafter2\n")
        stdout, stderr, code = _run(["since-snapshot"], cwd=tmp_path)
        assert code == 0
        assert "before1" not in stdout
        assert "after1" in stdout
        assert "after2" in stdout

    def test_emits_nothing_when_no_appends(self, tmp_path: Path) -> None:
        log = tmp_path / "workflow-friction.log"
        log.write_text("a\nb\n")
        _run(["snapshot"], cwd=tmp_path)
        stdout, stderr, code = _run(["since-snapshot"], cwd=tmp_path)
        assert code == 0
        assert stdout.strip() == ""

    def test_missing_snapshot_errors_nonzero(self, tmp_path: Path) -> None:
        """Running since-snapshot without prior snapshot is an error."""
        log = tmp_path / "workflow-friction.log"
        log.write_text("a\n")
        stdout, stderr, code = _run(["since-snapshot"], cwd=tmp_path)
        assert code != 0
        assert "snapshot" in stderr.lower() or "snapshot" in stdout.lower()

    def test_handles_log_truncation_gracefully(self, tmp_path: Path) -> None:
        """If log shrank since snapshot (rotation), emit all current content."""
        log = tmp_path / "workflow-friction.log"
        log.write_text("a\nb\nc\nd\n")
        _run(["snapshot"], cwd=tmp_path)
        log.write_text("rotated-line\n")
        stdout, stderr, code = _run(["since-snapshot"], cwd=tmp_path)
        assert code == 0
        assert "rotated-line" in stdout


class TestResetSubcommand:
    """`reset` removes the .friction-snapshot marker."""

    def test_reset_removes_marker(self, tmp_path: Path) -> None:
        (tmp_path / "workflow-friction.log").write_text("x\n")
        _run(["snapshot"], cwd=tmp_path)
        stdout, stderr, code = _run(["reset"], cwd=tmp_path)
        assert code == 0
        assert not (tmp_path / ".friction-snapshot").exists()

    def test_reset_is_idempotent(self, tmp_path: Path) -> None:
        """Reset with no prior snapshot is a no-op, not an error."""
        stdout, stderr, code = _run(["reset"], cwd=tmp_path)
        assert code == 0


class TestCliShape:
    """--help exits 0 and mentions all three subcommands."""

    def test_help(self, tmp_path: Path) -> None:
        stdout, stderr, code = _run(["--help"], cwd=tmp_path)
        assert code == 0
        out = (stdout + stderr).lower()
        assert "snapshot" in out
        assert "since-snapshot" in out
        assert "reset" in out

    def test_unknown_subcommand_errors(self, tmp_path: Path) -> None:
        stdout, stderr, code = _run(["no-such-command"], cwd=tmp_path)
        assert code != 0
