"""PSR-008 Finding 1: methodology companion must fire in orchestrator mode.

Context: PSR-008 surfaced 0 events with `query_source: "methodology"` despite
the agent running in Work mode. Root cause: writ-rag-inject.sh's orchestrator
short-circuit (`exit 0` at the IS_ORCHESTRATOR=true branch) bypasses the
methodology companion block entirely.

Fix contract (this test pins): when a session has both `mode=work` AND
`is_orchestrator=true`, the inject hook MUST still fire the methodology
companion query before short-circuiting. The status-line output and the
`exit 0` are preserved -- only the methodology block runs additionally.

This is checked structurally (the orchestrator branch of the hook source
references the methodology query) AND end-to-end (running the hook against
a seeded orchestrator cache produces a `query_source: "methodology"` line
in the friction log).
"""

from __future__ import annotations

import json
import os
import re
import subprocess

import pytest
from pathlib import Path


SKILL_DIR = str(Path.home() / ".claude/skills/writ")
HOOK = f"{SKILL_DIR}/.claude/hooks/writ-rag-inject.sh"


class TestOrchestratorMethodologyCompanionStructural:
    """Structural: the hook's orchestrator branch must reference the
    methodology companion path so a future regression that re-introduces
    the silent skip is caught at lint time."""

    def test_orchestrator_branch_invokes_methodology(self) -> None:
        with open(HOOK) as f:
            body = f.read()

        # Locate the orchestrator branch -- everything between the
        # `if [ "$IS_ORCHESTRATOR" = "true" ]; then` and its closing `fi`
        # before the next major block.
        m = re.search(
            r'if \[ "\$IS_ORCHESTRATOR" = "true" \]; then(.+?)\nfi\n',
            body,
            re.DOTALL,
        )
        assert m is not None, "could not locate orchestrator branch in hook source"
        branch_body = m.group(1)

        # Methodology references: either a node_types=Skill query or
        # a friction-event with query_source=methodology. Either is
        # evidence that methodology fires inside the branch.
        has_node_types_skill = "Skill" in branch_body and "node_types" in branch_body
        has_methodology_marker = "methodology" in branch_body.lower()
        assert has_node_types_skill or has_methodology_marker, (
            "orchestrator branch does NOT invoke the methodology companion. "
            "Branch body:\n" + branch_body[:1500]
        )


class TestOrchestratorMethodologyCompanionEndToEnd:
    """End-to-end: run the hook with a seeded orchestrator cache and a
    user prompt, verify the friction log gets a methodology rag_query."""

    def _seed_orchestrator_cache(
        self, cache_dir: str, session_id: str
    ) -> None:
        path = os.path.join(cache_dir, f"writ-session-{session_id}.json")
        with open(path, "w") as f:
            json.dump(
                {
                    "mode": "work",
                    "is_orchestrator": True,
                    "is_subagent": False,
                    "current_phase": "implementation",
                    "loaded_rule_ids": [],
                    "loaded_rule_ids_by_phase": {},
                    "remaining_budget": 8000,
                    "context_percent": 0,
                    "queries": 0,
                    "files_written": [],
                    "loaded_rules": [],
                },
                f,
            )

    @pytest.mark.skip(
        reason="End-to-end: needs an externally-running, corpus-loaded Writ "
        "server. The hook runs with cwd=<fresh tmp git dir>, so its auto-started "
        "daemon keys a per-test port onto an EMPTY graph (no methodology nodes), "
        "and the methodology companion query returns nothing. Deterministic "
        "execution would require standing up a corpus-loaded server on the "
        "computed port, which conflicts (graph lock) with the daemon-down "
        "prod-graph tests in the same run. Run manually against a live daemon."
    )
    def test_orchestrator_fires_methodology_companion(
        self, tmp_path
    ) -> None:
        """End-to-end: invoke the hook against the LIVE server with a
        seeded orchestrator cache. The hook delegates session reads to
        the running Writ server via HTTP, so the cache must live in
        the server's CACHE_DIR (default /tmp). Use a unique session
        ID and clean up after.

        Pass criterion: project-root friction-log gets at least one
        rag_query with query_source=methodology."""
        import uuid
        sid = f"orch-method-e2e-{uuid.uuid4().hex[:8]}"
        # Seed at the server's cache dir, not the test's tmp_path.
        server_cache_dir = "/tmp"
        cache_path = os.path.join(server_cache_dir, f"writ-session-{sid}.json")
        self._seed_orchestrator_cache(server_cache_dir, sid)

        try:
            # Project root with a friction-log file that the hook can
            # write to. Use a marker file so the hook detects this dir
            # as project root.
            project_root = tmp_path / "proj"
            project_root.mkdir()
            (project_root / ".git").mkdir()  # marker
            log = project_root / "workflow-friction.log"
            log.touch()

            envelope = json.dumps({
                "session_id": sid,
                "prompt": (
                    "I want to implement a small Python function that takes "
                    "a list of integers and returns their sum. Please plan "
                    "this carefully and write tests first."
                ),
            })

            result = subprocess.run(
                ["bash", HOOK],
                input=envelope,
                capture_output=True,
                text=True,
                cwd=str(project_root),
                timeout=15,
            )
        finally:
            # Always clean up the seeded cache so /tmp doesn't accumulate.
            try:
                os.unlink(cache_path)
            except FileNotFoundError:
                pass
        # Hook must not error out.
        assert result.returncode == 0, (
            f"hook returned {result.returncode}; "
            f"stderr={result.stderr[:1000]}"
        )

        # Inspect the friction log for a methodology rag_query.
        log_text = log.read_text() if log.exists() else ""
        events: list[dict] = []
        for line in log_text.splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                events.append(json.loads(line))
            except json.JSONDecodeError:
                pass

        methodology = [
            e for e in events
            if e.get("event") == "rag_query"
            and e.get("query_source") == "methodology"
        ]

        assert methodology, (
            "no rag_query with query_source=methodology in orchestrator "
            f"hook run. All events:\n{json.dumps(events, indent=2)}"
        )
