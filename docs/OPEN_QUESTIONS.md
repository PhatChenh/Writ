# Open Questions

_All Phase 3 questions below resolved + verified in code 2026-06-20._

### OQ-01 · Scrub production hook `session-start-bootstrap.sh`
**Blocks:** Phase 3, Phase 7 — fully-clean `grep -ri neo4j tests/` and honest bootstrap behavior.
**Status:** ✅ Resolved (Phase 3, sign-off OQ-6)
**Question:** Approve editing the production hook `hooks/scripts/session-start-bootstrap.sh` to remove its live Neo4j:7687 + `docker compose ... neo4j` references (plan specifies: delete lines 24-25 + the probe block 38-49), then realign `test_session_start_probes_neo4j`?
**Resolution:** Approved + done. `hooks/scripts/session-start-bootstrap.sh` is clean of `neo4j`/`7687`/`docker`. The test was realigned to assert *absence* — `tests/plugin/test_session_start_bootstrap.py::test_session_start_no_neo4j_probe` now asserts `"7687" not in content`. (The retained "Neo4j" strings there name what must NOT exist — load-bearing, intentionally kept.)
**Context:** Phase 2 was believed to have scrubbed all Docker/Neo4j, but research confirmed this production hook still probed Neo4j and contradicted the shipped Docker-free/FalkorDB product. Plan working label: OQ-6.

### OQ-02 · Scrub `writ-architecture-flowchart.html` Neo4j → FalkorDB
**Blocks:** Phase 3, Phase 7 — clean grep + accurate architecture doc.
**Status:** ✅ Resolved (Phase 3, sign-off OQ-7)
**Question:** Confirm scrubbing `writ-architecture-flowchart.html` (replace "Neo4j" → "FalkorDB" at line 410 "Neo4j, cached" and line 588 "rules live in a Neo4j graph") and changing the pinned required term in `test_architecture_flowchart.py:125` from `"Neo4j"` to `"FalkorDB"`?
**Resolution:** Approved + done. `writ-architecture-flowchart.html` is clean of `neo4j`; `tests/test_architecture_flowchart.py:125` now pins `"FalkorDB"` in its required-terms tuple.
**Context:** The doc named Neo4j as a CURRENT pipeline stage (present-tense, no historical framing), so it was stale, not a historical-design reference. Plan working label: OQ-7.

### OQ-03 · `test_import_markdown_unified.py` rewrite path
**Blocks:** Phase 3, Phase 6.
**Status:** ✅ Resolved (Phase 3, sign-off OQ-8)
**Question:** Confirm the rewrite approach for `test_import_markdown_unified.py` — replace `docker exec writ-neo4j cypher-shell` + `_writ_config["neo4j"]["password"]` (KeyErrors today) with the FalkorDB `_execute_query` path?
**Resolution:** Approved + done. `tests/test_import_markdown_unified.py` is clean of `docker exec`/`neo4j`/`cypher-shell`; rewritten to the FalkorDB `_execute_query` path.
**Context:** Mis-batched as a "comment scrub" in the spec; it was a substantive live test. Plan re-batched it as a real rewrite. Plan working label: OQ-8.

### OQ-04 · Credential-scan meta-test: retire or re-aim?
**Blocks:** Phase 3, Phase 7.
**Status:** ✅ Resolved (Phase 3, sign-off OQ-2) — retired
**Question:** The repo-wide credential-scan meta-test scans for a Neo4j password that no longer exists. Retire the test, or re-aim it at whatever (if any) secret the FalkorDB setup introduces (none today)?
**Resolution:** Retired. No Neo4j-password scan remains in `tests/`. Embedded FalkorDB uses a unix socket — no credential to scan.
**Context:** No Neo4j password exists post-fork; embedded FalkorDB uses a unix socket, no credential. Plan working label: OQ-2.
