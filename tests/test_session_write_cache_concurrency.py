"""Regression test for B23: `_write_cache` shared-tmp race.

Context: every UserPromptSubmit fires `writ-rag-inject` and a context-watcher
hook that both POST `/session/<sid>/context-percent`, and several PostToolUse
hooks call `writ-session.py update <sid>` on the same session id within one
turn. Each of those is a separate process that calls `_write_cache(sid, ...)`,
which wrote `<cache>/<sid>.json.tmp` then `os.rename`'d it over the final path.

A FIXED `.tmp` name means two concurrent writers share one temp file: writer A
finishes and renames (deleting the temp), writer B's `os.rename` then raises
`FileNotFoundError: ...json.tmp -> ...json` -> the hook gets a 500 / non-zero
exit and silently drops the cache update. Seen live in `/tmp/writ-server.log`
(`FileNotFoundError` on `writ-session-<sid>.json.tmp`).

Fix: per-PID temp name (`<path>.<pid>.tmp`) + `os.replace` (atomic, overwrites).
This test pins that contract: N concurrent writers on the same session id all
succeed (no `FileNotFoundError`, exit 0) and the final cache file is valid JSON.

Per TEST-REGRESSION-001.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import threading
from pathlib import Path

SKILL_DIR = str(Path.home() / ".claude/skills/writ")
WRIT_SESSION_PY = f"{SKILL_DIR}/bin/lib/writ-session.py"

# Fall back to the repo copy when the skill symlink is not installed (CI / a
# bare dev checkout without `scripts/bootstrap-plugin.sh` having run).
if not Path(WRIT_SESSION_PY).exists():
    WRIT_SESSION_PY = str(
        Path(__file__).resolve().parent.parent / "bin" / "lib" / "writ-session.py"
    )


def _run_update(cache_dir: str, sid: str, rid: str) -> subprocess.CompletedProcess[str]:
    env = os.environ.copy()
    env["WRIT_CACHE_DIR"] = cache_dir
    return subprocess.run(
        [sys.executable, WRIT_SESSION_PY, "update", sid, "--add-rules",
         json.dumps([rid]), "--inc-queries"],
        capture_output=True,
        text=True,
        env=env,
    )


class TestWriteCacheConcurrency:
    """Concurrent writers on the same session id must not collide on a shared
    `<sid>.json.tmp` (B23)."""

    def test_concurrent_updates_all_succeed_and_final_cache_valid(self, tmp_path) -> None:
        """N processes call `update` on the same sid in parallel. Before the
        per-PID-tmp fix, some would crash with FileNotFoundError on rename."""
        sid = "concurrent-sid"
        n = 12
        results: list[subprocess.CompletedProcess[str]] = [None] * n  # type: ignore[assignment]
        errors: list[str] = []

        def writer(i: int) -> None:
            try:
                results[i] = _run_update(str(tmp_path), sid, f"R-{i:02d}")
            except Exception as exc:  # pragma: no cover
                errors.append(f"writer {i}: {exc!r}")

        threads = [threading.Thread(target=writer, args=(i,)) for i in range(n)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert not errors, errors
        for i, r in enumerate(results):
            assert r is not None, f"writer {i} produced no result"
            assert r.returncode == 0, (
                f"writer {i} exited {r.returncode} (B23 race): stderr={r.stderr}"
            )
            assert "FileNotFoundError" not in r.stderr, (
                f"writer {i} hit the shared-tmp race: stderr={r.stderr}"
            )

        # The final cache file must be valid JSON regardless of which writer
        # won the last-writer race on the array contents.
        cache_file = tmp_path / f"writ-session-{sid}.json"
        assert cache_file.exists(), "final cache file missing"
        cache = json.loads(cache_file.read_text())
        assert isinstance(cache, dict)
        # No leftover .tmp files from a crashed rename.
        leftovers = [p for p in tmp_path.iterdir() if p.name.endswith(".tmp")]
        assert leftovers == [], f"orphan tmp files: {leftovers}"

    def test_concurrent_write_cache_unit_no_exception(self, tmp_path) -> None:
        """Direct in-process stress of `_write_cache` from many threads on the
        same sid -- the function-level contract the subprocess test exercises
        end-to-end. Loads `writ-session.py` by path (its hyphenated name is not
        importable as a normal module)."""
        import importlib.util

        os.environ["WRIT_CACHE_DIR"] = str(tmp_path)
        try:
            spec = importlib.util.spec_from_file_location(
                "writ_session_under_test", WRIT_SESSION_PY
            )
            assert spec is not None and spec.loader is not None
            mod = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(mod)
            # CACHE_DIR is read at import time from the env we just set; set it
            # again in case a prior test already imported this module cached.
            mod.CACHE_DIR = str(tmp_path)
            sid = "unit-concurrent-sid"
            errors: list[str] = []

            def writer(i: int) -> None:
                for n in range(40):
                    try:
                        mod._write_cache(sid, {"i": i, "n": n, "loaded_rule_ids": []})
                    except Exception as exc:  # pragma: no cover
                        errors.append(f"writer {i} iter {n}: {exc!r}")

            threads = [threading.Thread(target=writer, args=(i,)) for i in range(8)]
            for t in threads:
                t.start()
            for t in threads:
                t.join()

            assert not errors, errors
            cache_file = tmp_path / f"writ-session-{sid}.json"
            assert cache_file.exists()
            json.loads(cache_file.read_text())  # valid JSON
            leftovers = [p for p in tmp_path.iterdir() if p.name.endswith(".tmp")]
            assert leftovers == [], f"orphan tmp files: {leftovers}"
        finally:
            os.environ.pop("WRIT_CACHE_DIR", None)