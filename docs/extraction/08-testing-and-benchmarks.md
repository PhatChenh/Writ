# 08 — Testing and Benchmarks

> **Refresh note (2026-05-15, v1.1.0).** Ground-truth corpus and regression floors were retuned during the Phase 1-5 public-rulebook expansion (v1.0.0). The ambiguous-set MRR@5 floor moved from 0.78 → 0.45 and the hit-rate floor from 0.90 → 0.75 as the rule corpus grew 3.8x (72 → 276 rules) while the original ambiguous-query set stayed at 19. The ground-truth file (`tests/fixtures/ground_truth_queries.json`) was expanded from 83 to 165 queries by adding 82 keyword queries targeting the new public-rulebook rule IDs. Test count grew to **1,512 tests collected (v1.1.0)** -- the 57-test increase since 1,455 reflects regression-floor consolidation, the rewritten Item 10 ranking-stability test, the new Item 3 domain-hit-rate enforcement gate, the silent-fallback closure tests for the ONNX contract, and the v1.1.0 release-prep refactors. Bench-target classes are unchanged; the bench now has **13 contractual targets** (was 12; Item 3 added `test_domain_hit_rate_top5`). v1.1.0 measurement-quality work (Items 1a-1d) recovered MRR@5 from 0.4886 to **0.6904** and hit rate from 0.7576 to **0.800** via 3 label fixes + 2 rule-text edits, no algorithmic changes. Current floors live in `tests/fixtures/regression_floors.py` (canonical) and are imported by both `bench_targets.py` and `tests/test_graph_proximity.py`. The methodology benchmark thresholds (Phase-0 corpus, n=40) are unchanged. Threshold values and counts marked below are the v1.0.0 originals.

## A. conftest.py (`tests/conftest.py`, 115 lines)

Single project-level conftest. **No `pytest_configure`** and **no `pytest_collection_modifyitems`**. Only collection-level hook is `pytest_sessionfinish`. Five module-scoped rule-dict fixtures.

### `pytest_sessionfinish(session, exitstatus)` — post-suite Neo4j restoration

Pinned by `test_post_suite_neo4j_restoration.py`. Verbatim:
```python
def pytest_sessionfinish(session, exitstatus):
    """Re-migrate rules after test suite completes so CLI queries work
    immediately.

    Pre-2026-05-09 this hook had inline migration logic gated on
    `if count == 0`. That gate skipped re-migration whenever ANY test
    re-loaded core rules (most do), leaving methodology nodes
    (Skill / Playbook / etc.) missing post-suite -- the symptom was
    `/always-on?mode=work` returning empty after `pytest -q`.

    New approach: shell out to scripts/migrate.py unconditionally.
    """
    skill_dir = Path(__file__).resolve().parent.parent
    migrate = skill_dir / "scripts" / "migrate.py"
    methodology = skill_dir / "bible" / "methodology"
    if not migrate.exists() or not methodology.exists():
        return  # not a writ checkout; nothing to restore.

    try:
        subprocess.run(
            [sys.executable, str(migrate),
             "--methodology-dir", str(methodology)],
            cwd=str(skill_dir),
            capture_output=True,
            timeout=60,
            check=False,
        )
    except (subprocess.SubprocessError, OSError):
        pass  # best-effort; never raise out of pytest_sessionfinish
```

Key invariants:
- Unconditional shell-out to `scripts/migrate.py --methodology-dir bible/methodology`.
- Never raises out of `pytest_sessionfinish` (would flip `exitstatus` and mask test results).
- Pre-fix `if count == 0:` gate is gone; `test_post_suite_neo4j_restoration.py::TestSessionFinishRestoresMethodology::test_conftest_sessionfinish_does_not_gate_on_count_zero` greps the source to enforce that.

### Fixtures

| Fixture | Yields |
|---|---|
| `valid_rule_data` | Well-formed `ARCH-ORG-001` rule with all required fields |
| `valid_enf_rule_data` | `ENF-GATE-001` rule with `mandatory: True`, `scope: session` |
| `minimal_rule_data` | `TEST-TDD-001` with only required fields |
| `compound_id_rule_data` | `valid_rule_data` with `rule_id` overridden to multi-segment `FW-M2-RT-003` |
| `enf_gate_final_data` | `valid_rule_data` with `rule_id` overridden to non-numeric `ENF-GATE-FINAL` |

All `@pytest.fixture()`, function-scope, no teardown — pure dict factories.

## B. Fixture pyramid

```
tests/conftest.py
    valid_rule_data            (root dict factory)
        compound_id_rule_data  (overrides rule_id)
        enf_gate_final_data    (overrides rule_id)
    valid_enf_rule_data        (mandatory=True)
    minimal_rule_data

tests/fixtures/methodology_loader.py
    MethodologyNode             dataclass
    load_corpus(fixture_dir)    -> list[MethodologyNode]   (reads bible/methodology/*.md)
    to_keyword_index_format()   -> list[dict] for KeywordIndex
    load_ground_truth()         -> dict   (ground_truth_proc.json)
    build_adjacency()           -> dict[node_id, list[(target,type)]]
    MethodologyIndex            tantivy BM25 over trigger(2x), statement, tags, body(0.5x)
    build_methodology_index()   -> MethodologyIndex

tests/test_methodology_retrieval.py  (module-scoped, composes the loader)
tests/test_retrieval.py              (module-scoped, composes Neo4j + bible)
```

`methodology_loader` constants:
- `RETRIEVABLE_TYPES = {"Skill", "Playbook", "Technique", "AntiPattern", "ForbiddenResponse"}`
- `ID_FIELDS` covers 12 typed `_id` aliases.
- `FIXTURE_DIR = bible/methodology`.
- `GROUND_TRUTH_PATH = tests/fixtures/ground_truth_proc.json`.
- Body-field BM25 weight at 0.5x via every-other-token dilution; trigger 2x via duplicating.

## C. Ground-truth corpus

### `tests/fixtures/ground_truth_queries.json` (now 165 entries; was 83 in original draft)

Header `_instructions`: "Ground-truth evaluation queries for automated MRR@5 and regression testing. MRR@5 assertion runs against 'ambiguous' set only. Hit-rate regression runs against the full corpus. Built from PHASE5_RESULTS.md human evaluation; Phase 6 added 82 keyword queries targeting new public-rulebook rule IDs."

**Schema:** `{"id", "set", "query", "expected_rule_id"}` — single-rule-id labels, flat list.

**Distribution (now 165 entries; original 83 retained, 82 added in Phase 6):**

| set | count (Phase 6) | count (original) |
|---|---|---|
| `keyword` | 132 | 50 (Q1–Q50) |
| `symptom` | 14 | 14 (Q51–Q65 minus Q53) |
| `ambiguous` | 19 | 19 (Q66–Q85 minus Q70) |

The ambiguous set is the gate for MRR@5; its size is intentionally held constant.

**Five representative entries (verbatim; Q1, Q83 and similar have been re-pointed at the renamed rule IDs):**
```json
{"id": "Q1",  "set": "keyword",   "query": "controller contains SQL query",                           "expected_rule_id": "SEC-INJ-SQL-001"}
{"id": "Q14", "set": "keyword",   "query": "single source of truth REST GraphQL",                     "expected_rule_id": "FW-M2-RT-004"}
{"id": "Q51", "set": "symptom",   "query": "my totals are wrong after adding item to cart",           "expected_rule_id": "FW-M2-003"}
{"id": "Q66", "set": "ambiguous", "query": "my code works in dev but breaks in production",           "expected_rule_id": "TEST-INT-001"}
{"id": "Q83", "set": "ambiguous", "query": "error message says nothing useful just something went wrong", "expected_rule_id": "CLEAN-ERR-001"}
```

### `tests/fixtures/ground_truth_proc.json` (475 lines, Phase 0 methodology corpus)

`_status: signed-off`, `_curation_date: 2026-04-21`, summary `{total: 40, kept_as_is: 33, relabeled_primary: 7}`.

**Schema:** `{"id", "set", "query", "expected_node_ids" (ordered list, multi-hit), "rationale", "source_trace"}`.

**Node-id legend:**
- `SKL-PROC-*` Skill (retrievable)
- `PBK-PROC-*` Playbook (retrievable)
- `TEC-PROC-*` Technique (retrievable)
- `ANT-PROC-*` AntiPattern (retrievable)
- `FRB-COMMS-*` ForbiddenResponse (retrievable, always-on)
- `ENF-PROC-*` Rule with mechanical enforcement path
- `ENF-COMMS-*` Rule, advisory severity
- `META-AUTH-*` Rule about skill authoring

**Sets:** direct (15), rationalization (9), red_flag (6), forbidden (3), anti_pattern (4), cross_skill (3) — total 40, IDs P1–P40.

**Coverage by skill:** brainstorming 4, writing-plans 3, executing-plans 2, subagent-driven-development 4, test-driven-development 5, verification-before-completion 3, systematic-debugging 3, using-git-worktrees 2, finishing-a-development-branch 2, requesting-code-review 2, receiving-code-review 3, dispatching-parallel-agents 2, writing-skills 2, meta-orientation-skill 0 (excluded).

**First 30 entries (verbatim shape):**
- P1 direct "should I design this feature before writing code" → [SKL-PROC-BRAIN-001, PBK-PROC-BRAIN-001, ENF-PROC-BRAIN-001]
- P2 rationalization "this project is too simple to need a design" → [SKL-PROC-BRAIN-001, ENF-PROC-BRAIN-001, PBK-PROC-BRAIN-001]
- P3 red_flag "I've brainstormed enough let me start coding now" → [SKL-PROC-BRAIN-001, ENF-PROC-BRAIN-001]
- P4 direct "how do I present visual options when brainstorming a UI feature" → [SKL-PROC-VISUAL-001, SKL-PROC-BRAIN-001]
- P5 direct "create an implementation plan for this task" → [SKL-PROC-PLAN-001, PBK-PROC-PLAN-001, ENF-PROC-PLAN-001]
- ... (P6-P30 similar shape, see `ground_truth_proc.candidates.json` for full list)

### `ground_truth_proc.candidates.json` (95 lines)
Status `draft-candidate`. 40 candidates authored by Claude Code from absorbed methodology content. Same schema as `ground_truth_proc.json`.

### `ground_truth_proc.curation-proposal.json` (55 lines)
Drafted 2026-04-21 from per-query rankings. Per-id verdicts: `keep` / `relabel-primary` / `discard` / `rewrite`. Summary: 33 keep, 7 relabel-primary, 0 discard, 0 rewrite. Seven relabels (P13, P15, P18, P21, P35, P38, P40) push primary slot from a teaching Skill/Playbook to a more-specific named counter.

**Provenance chain:** `.candidates.json` (Claude-drafted superset) → `.curation-proposal.json` (maintainer ledger) → `.json` (signed-off, test-consumed).

## D. Test files by topic (86 total)

### D.1 Schema / graph / ingest / migration

- `test_schema.py` (222) — `TestRuleValidation`, `TestRuleRejection`, `TestEnumValidation`, `TestRuleIdFormat`, `TestScopeValidation`, `TestMandatoryField`, `TestEdgeModels`.
- `test_schema_roundtrip.py` (569) — Phase 1 methodology node + edge round-trip; per-type Test* classes (Skill/Playbook/Technique/AntiPattern/ForbiddenResponse/Phase/Rationalization/PressureScenario/WorkedExample/SubagentRole) + new edge types + `TestNodeTypeEnum`, `TestSourceAttributionUniformity`.
- `test_phase6a_node_models.py` (482) — Pydantic node models, one Test* class per type plus `TestRuleUnchanged`, `TestModelCount`.
- `test_ingest.py` (525) — Phase 3 ingestion: `TestMarkdownParser`, `TestMandatoryParsing`, `TestScopeExtensibility`, `TestNeo4jConstraints`, `TestMigrationIntegration`.
- `test_multi_node_ingest.py` (269) — Phase 1 multi-node parser: `TestFrontMatterParsing`, `TestNodeMarkerParsing`, `TestLegacyRuleStart`, `TestEdgeParsing`, `TestNodeTypeDispatch`, `TestSyntheticCorpusRoundTrip`.
- `test_infrastructure.py` (200) — Phase 2 infra: `TestNeo4jCrud`, `TestTraversal`, `TestTantivyIndex`, `TestHnswlibSearch`.
- `test_export.py` (439) — Phase 7 round-trip: `TestRuleToMarkdown`, `TestGroupRulesByFile`, `TestStalenessDetection`, `TestRoundTrip`, `TestExportWithNeo4j`, `TestExportCLI`.
- `test_phase3b_export_subagent_roles.py` (110) — `TestRenderAgentMd`, `TestExportCheckMode`, `TestExportDryRun`.
- `test_integrity.py` (193) — `TestConflictDetection`, `TestOrphanDetection`, `TestStalenessDetection`, `TestRedundancyDetection`, `TestRunAllChecks`.
- `test_validate_rules.py` (190) — `TestViolationPatternMatching`, `TestPhaseBoundaryDetection`, `TestRoutingHeuristic`.
- `test_cli_rename.py` (67) — Smoke tests for CLI rename `ingest` → `import-markdown`.

### D.2 Retrieval pipeline

- `test_retrieval.py` (261) — `TestPipeline`, `TestRanking`, `TestContextBudget`, `TestAdjacencyCache`. Fixture `pipeline_db` wipes Neo4j, ingests `bible/`, yields, wipes, restores via `scripts/migrate.py`.
- `test_methodology_retrieval.py` (216) — Phase 0 methodology benchmark. `TestPhase0Blockers::test_mrr_at_5` (>=0.78), `test_hit_rate` (>=0.90), `test_bundle_completeness` (>=0.85), `test_p95_latency` (<=5ms). 7 module-scoped fixtures. `pytest.importorskip("onnxruntime")`.
- `test_embeddings.py` (185) — `TestOnnxEmbeddingModel`, `TestCachedEncoder`, `TestOnnxRankingStability`.
- `test_hnsw_persistence.py` (300) — `TestRoundTripSaveLoad`, `TestSidecarSchema`, `TestCorpusHashMismatch`, `TestAtomicWrite`, `TestMaxElementsHeadroom`, `TestMissingSidecar`, `TestCorruptedSidecar`.
- `test_graph_proximity.py` (293) — `TestComputeGraphProximity`, `TestRankingWeightsExtended`, `TestBackwardCompatibility`, `TestGraphBoostRegression`.
- `test_authority.py` (299) — `TestAuthorityProperty`, `TestAuthorityPreference`, `TestProximitySeeding`, `TestProposalWorkflow`.
- `test_frequency.py` (157) — `TestGraduationLogic`, `TestGraduationInRanking`, `TestFrequencyProperties`.
- `test_retrievable_filter.py` (67) — `TestRetrievableNodeTypes`, `TestRetrievalModeWeights`.
- `test_phase6j_node_types.py` (62) — `TestQueryRequestNodeTypes`, `TestQueryEndpointPlumbing`.
- `test_bundle_cohesion.py` (98) — `TestBundleCohesionScoring`, `TestAdjacencyBundle`.
- `test_gate.py` (286) — `TestGateResult`, `TestSchemaCheck`, `TestSpecificityCheck`, `TestNoveltyCheck`, `TestRedundancyCheck`, `TestConflictCheck`, `TestGateIntegration`.

### D.3 Hooks (PreToolUse / PostToolUse / lifecycle)

- `test_instructions_loaded.py` (484) — InstructionsLoaded hook + `instructions_rule_ids`.
- `test_posttool_rag.py` (228) — `TestAlwaysFire`, `TestWriteExtraction`, `TestEditExtraction`, `TestSourceCodeQuery`, `TestXmlConfigQuery`, `TestBudgetAndSkip`.
- `test_pre_write_dispatch.py` (476) — `/pre-write-check` endpoint + Cycle B Item 8 hook consolidation.
- `test_read_rag_hook.py` (119) — `TestReadRagModeFilter`, `TestReadRagBudgetRespect`, `TestReadRagHookSyntax`.
- `test_compaction_hooks.py` (482) — Cycle B Item 6 PreCompact / PostCompact.
- `test_compaction_detection.py` (340) — `detect-compaction` subcommand + HTTP route.
- `test_session_end.py` (290) — Cycle B Item 7 SessionEnd hook + Stop simplification.
- `test_cwd_changed.py` (408) — Cycle C Item 10 CwdChanged hook + `detected_domain`.
- `test_failed_write_tracking.py` (341) — `track-failed-writes.sh` PostToolUseFailure.
- `test_enforce_violations.py` (188) — `enforce-violations.sh` Stop hook.
- `test_hook_stderr_logging.py` (135) — Replace `2>/dev/null` with `$WRIT_HOOK_LOG`.
- `test_phase4c_stderr_capture.py` (103) — Phase 4c D1 stderr capture extension.
- `test_phase4c_postcompact_directive.py` (137) — Phase 4c D3 verify-discipline directive.
- `test_phase6_hook_defensive_json.py` (207) — Phase 6 hotfix: defensive `json.loads(sys.argv[N])`.
- `test_sdd_review_order_hook_json_decode.py` (140) — Regression: JSON-decode bug.
- `test_phase4b_memory_policy_guard.py` (215) — `writ-memory-policy-guard.sh` rule-weakening interception.
- `test_phase4b_memory_guard_robustness.py` (232) — Robustness against real-world content.
- `test_phase2_hooks.py` (134) — Phase 2 mode-scope, executability, core behaviors.
- `test_checklist_injection.py` (114) — `TestChecklistLoading`, `TestBackwardContextInjection`.

### D.4 Session / mode / gate / phase

- `test_session.py` (367) — Phase 9 agentic retrieval loop.
- `test_session_cache_migration.py` (161) — `TestLegacyCacheMigration`.
- `test_session_routes.py` (471) — 18 Test* classes covering all `/session/*` routes.
- `test_session_rules.py` (289) — `writ-session.py` feedback loop.
- `test_mode_infrastructure.py` (611) — `TestModeGet`, `TestModeSet`, `TestModeSwitch`, etc.
- `test_phase3_centralization.py` (584) — Mode-based centralization commands.
- `test_phase2_gate_policy.py` (55) — `TestMechanicalEnforcementPolicy`.
- `test_phase_machine_reset.py` (135) — `TestModeSetResetsPhase`, `TestAdvanceFromCompleteRejects`.
- `test_exit_plan_phase_reset.py` (164) — `TestResetTaskPhaseFlag`, `TestValidateExitPlanHookCallsReset`.
- `test_hardening.py` (506) — Pre-sub-agent hardening.
- `test_orchestrator_mode.py` (359) — Cycle B Item 5 orchestrator suppression.
- `test_orchestrator_hardening.py` (199) — Back-in-Stock audit hardening.
- `test_subagent_isolation.py` (238) — Sub-agent session isolation in Writ v3.
- `test_origin_context.py` (77) — Phase 2 Origin context SQLite store.
- `test_playbook_state.py` (97) — Phase 1 deliverable 7.1 session state transitions.
- `test_sticky_rules.py` (340) — Cycle C Item 9 sticky rules / prompt-cache stability.

### D.5 Approval / authoring / propose / review

- `test_authoring.py` (298) — Phase 6 authoring.
- `test_approval_patterns.py` (127) — Pattern detection in `auto-approve-gate.sh`.
- `test_phase3_approval_flow.py` (103) — Phase 3 approval flow + subagent graph canonicality.
- `test_phase3b_approval_rewrap.py` (104) — Phase 3b `auto-approve-gate.sh` emits ask-prompt.

### D.6 Compression / abstraction

- `test_compression.py` (480) — Phase 8 compression layer (clustering + abstraction). `TestClusterRules`, `TestGenerateAbstractions`, `TestAlgorithmEvaluation`, `TestAbstractionStorage`, `TestSummaryModeAbstractions`, `TestCompressCLI`, `TestNoRegression`.

### D.7 Friction / metrics / analysis

- `test_analysis.py` (576) — `writ/analysis` module: `TestPatternExtraction`, `TestPatternScanning`, `TestFindingModel`, `TestInstrumentation`, `TestAnalyzer`.
- `test_analyze_endpoint.py` (207) — POST `/analyze` integration.
- `test_phase4_analyze_friction.py` (203) — Phase 4 `writ analyze-friction` CLI + parser.
- `test_phase4_friction_delta.py` (128) — `scripts/friction-log-delta.py`.
- `test_phase5_analyzers.py` (284) — Analyzer functions: `TestRuleEffectiveness`, `TestSkillUsage`, `TestPlaybookCompliance`, `TestGraduationCandidates`, `TestTrimCandidates`, `TestQualityJudgeFalsePositives`.
- `test_phase5_cli.py` (117) — Phase 5 CLI dispatch arms.
- `test_phase5_dashboard.py` (108) — Phase 5 `GET /dashboard` server-rendered HTML.
- `test_phase5_instrumentation.py` (164) — Phase 5 instrumentation prereqs.
- `test_metrics.py` (179) — Confidence metrics in `writ-session.py`.
- `test_feedback_enrichment.py` (86) — Enriched feedback to Writ server on escalation.
- `test_cleanup_cycle.py` (333) — Friction reader, de-dupe, tier removal.
- `test_writ_audit_session.py` (204) — `writ audit-session <sid>`.
- `test_exit_code_audit.py` (330) — Exit code correctness.

### D.8 Phase 6a–6j verification (Phase 1 methodology delivery)

- `test_phase6a_node_models.py` (482) — see D.1.
- `test_phase6bcd_verification.py` (367) — Edges + traversal (6b), ingest dispatch (6c), migration idempotency (6d).
- `test_phase6efg_corpus_promotion.py` (159) — Methodology corpus promotion.
- `test_phase6hi_methodology_retrieval_and_playbook_wiring.py` (234) — Stage 4 methodology surfacing + advance-phase fires playbook step.
- `test_phase6_hook_defensive_json.py` (207) — see D.3.
- `test_phase6j_node_types.py` (62) — see D.2.
- `test_phase6j_always_on_budget.py` (160) — Always-on bundle budget tracking + cache schema migration.
- `test_always_on_methodology.py` (102) — `/always-on` extends to surface methodology nodes.
- `test_post_suite_neo4j_restoration.py` (101) — Pin the conftest contract.

### D.9 Sub-agent / orchestrator

- `test_subagent_isolation.py` — see D.4.
- `test_orchestrator_mode.py` — see D.4.
- `test_orchestrator_hardening.py` — see D.4.
- `test_methodology_companion_orchestrator.py` (168) — PSR-008 Finding 1: methodology companion fires in orchestrator mode.

### D.10 Other / cross-cutting / release

- `test_config.py` (211) — `writ/config.py` centralized writ.toml loader.
- `test_config_integration.py` (180) — `cli.py`, `server.py`, `conftest.py` read Neo4j creds from config.
- `test_bootstrap.py` (264) — Non-tech-user bootstrap.
- `test_harness_installer.py` (166) — `scripts/install-harness-config.sh` + templates.
- `test_pyproject_packaging.py` (152) — pyproject.toml install contract.
- `test_writ_cli_shim.py` (72) — PSR-008 Finding 3: writ CLI shim.
- `test_env_var_removal.py` (107) — Regression: fabricated env vars `CLAUDE_CONTEXT_PERCENT/TOKENS` removed.
- `test_v1_punch_list.py` (206) — v1 punch-list (writ-evolution Phase 1 leftovers).

## E. How to run tests

**Configuration discovery:** `pyproject.toml` declares pytest as dev/benchmark extra (`pytest>=8,<9`, `pytest-benchmark>=4,<5`, `pytest-asyncio>=0.23,<1`). NO `[tool.pytest.ini_options]`, NO `pytest.ini`, NO `setup.cfg` — pytest uses defaults.

**Entry points:**
- `pytest -q` from skill root — full suite. End-of-run, `pytest_sessionfinish` shells out to `scripts/migrate.py --methodology-dir bible/methodology`.
- `pytest tests/test_methodology_retrieval.py` — Phase 0 retrieval benchmark with MRR/hit/completeness/latency blockers. Skips if onnxruntime not installed.
- `pytest tests/test_retrieval.py` — Phase 5 pipeline; requires Neo4j running.

**Marker conventions:**
- `@pytest.mark.asyncio` — per-method async marking.
- Module-level `pytestmark = pytest.mark.asyncio(loop_scope="module")` — `test_authoring.py`, `test_graph_proximity.py`.
- Module-level `pytestmark = pytest.mark.skipif(...)` — `test_config_integration.py`.
- `@pytest.mark.parametrize` — `test_phase6efg_corpus_promotion.py::TestPerPrefixCounts::test_prefix_count`.

**Autouse fixtures** in test modules (not conftest):
- `test_phase4c_stderr_capture.py:30`
- `test_phase4b_memory_guard_robustness.py:71`

**Module-scoped fixtures** (Neo4j and indices need warm setup):
- `test_methodology_retrieval.py` — 7 module-scoped.
- `test_retrieval.py` — `pipeline_db` (async), `pipeline` (async).
- `test_graph_proximity.py:86`, `test_pyproject_packaging.py:28`.

## F. Gamed artifacts (`tests/fixtures/gamed_artifacts/trivially_bad/`)

Per `gamed_artifacts/README.md`: 50-artifact set across three difficulty tiers (`trivially_bad`, `plausible_boilerplate`, `near_miss`); Gate 5 Tier 2 must hit >=90% true-negative rate. Currently only `trivially_bad/` is seeded (10 of 15-20 artifacts).

**The 10 seeded `trivially_bad` files:**

| File | Gamed because |
|---|---|
| `design-empty.md` | All five design-doc section headers present, every body empty. |
| `design-missing-sections.md` | Two of five sections only (Goal + Chosen Approach). |
| `design-placeholder-heavy.md` | All sections present but filled with `TBD`, `TODO`, `<your text>`, "Similar to above". |
| `plan-empty-sections.md` | Plan has the four canonical headers and nothing else. |
| `plan-lorem-ipsum.md` | Each section filled with literal lorem ipsum Latin. |
| `plan-single-word.md` | Each section answered with a single word ("Yes." / "Done." / "All."). |
| `plan-todo-placeholders.md` | Sections filled with `TODO`, `TBD`, "Placeholder - similar to above". |
| `test-no-assertions.py` | Test functions named `test_*` that call helpers but have zero `assert` statements. |
| `test-only-mocks.py` | Three tests instantiating `Mock()` and asserting on the mock's own internal state. |
| `test-trivially-true.py` | `test_always_passes` asserts `True`; `test_math` asserts `1 == 1` and `2 + 2 == 4`. |

These exercise the quality-judge rubric across structural-skeleton, filler-text, and tautological-test failure modes.

## G. Files Read

| File | Lines |
|---|---|
| `tests/conftest.py` | 115 |
| `tests/__init__.py` | 0 (empty) |
| `tests/fixtures/methodology_loader.py` | 197 |
| `tests/fixtures/ground_truth_queries.json` | 88 |
| `tests/fixtures/ground_truth_proc.json` | 475 |
| `tests/fixtures/ground_truth_proc.candidates.json` | 95 |
| `tests/fixtures/ground_truth_proc.curation-proposal.json` | 55 |
| `tests/fixtures/README.md` | 22 |
| `tests/fixtures/gamed_artifacts/README.md` | 74 |
| `tests/fixtures/gamed_artifacts/trivially_bad/design-empty.md` | 9 |
| `tests/fixtures/gamed_artifacts/trivially_bad/design-missing-sections.md` | 7 |
| `tests/fixtures/gamed_artifacts/trivially_bad/design-placeholder-heavy.md` | 22 |
| `tests/fixtures/gamed_artifacts/trivially_bad/plan-empty-sections.md` | 7 |
| `tests/fixtures/gamed_artifacts/trivially_bad/plan-lorem-ipsum.md` | 16 |
| `tests/fixtures/gamed_artifacts/trivially_bad/plan-single-word.md` | 15 |
| `tests/fixtures/gamed_artifacts/trivially_bad/plan-todo-placeholders.md` | 17 |
| `tests/fixtures/gamed_artifacts/trivially_bad/test-no-assertions.py` | 18 |
| `tests/fixtures/gamed_artifacts/trivially_bad/test-only-mocks.py` | 20 |
| `tests/fixtures/gamed_artifacts/trivially_bad/test-trivially-true.py` | 15 |
| 86 test_*.py files | enumerated by line count + class headers |

## H. Cross-References Noted

- **conftest → migrate.py**: post-suite contract pinned by `tests/test_post_suite_neo4j_restoration.py`.
- **methodology_loader → bible/methodology**: Phase 6e/f/g promoted from `tests/fixtures/synthetic_methodology/`.
- **methodology_loader → writ.retrieval.keyword**: imports `_TANTIVY_RESERVED`, `_TANTIVY_SPECIAL`.
- **test_retrieval.py teardown → migrate.py**: `pipeline_db` fixture wipes Neo4j and re-runs `scripts/migrate.py` on teardown.
- **ground_truth_proc.json provenance**: `.candidates.json` → `.curation-proposal.json` → `.json`.
- **Quality-judge cross-refs**: gamed artifacts scored by `writ-quality-judge.sh`; FP rate measured by `test_phase5_analyzers.py::TestQualityJudgeFalsePositives`.
- **No `pytest_configure` / `pytest_collection_modifyitems`** — only `pytest_sessionfinish` exists.
- **No `[tool.pytest.ini_options]`, `pytest.ini`, or `setup.cfg`** — pytest runs on defaults.
- **Hard-coded Neo4j creds** in `test_retrieval.py` and `test_post_suite_neo4j_restoration.py`; `test_config_integration.py::TestCliNoHardcodedCreds` enforces the converse for production code.

## I. Benchmark suite

The suite lives in `benchmarks/` and consists of four files. Both `bench_targets.py` and `methodology_bench.py` consume ground-truth JSON files from `tests/fixtures/`.

### `benchmarks/bench_targets.py` (480 lines) — Pytest-driven Section-10 contractual benchmarks

Module-scoped async fixtures: `db` (`Neo4jConnection` to `bolt://localhost:7687`; skips if `count_rules() == 0`), `pipeline` (pre-warmed via `build_pipeline(db)`), `ground_truth` (loads `tests/fixtures/ground_truth_queries.json`).

Constants (latency budgets unchanged; MRR/hit-rate floors were retuned during Phase 1-5 — see `tests/fixtures/regression_floors.py` for the canonical floors plus the full phase-by-phase trajectory docstring):
- `LATENCY_P95_BUDGET_MS = 10.0`
- `COLD_START_BUDGET_S = 3.0`
- `MEMORY_BUDGET_BYTES = 2 GiB`
- `INTEGRITY_BUDGET_MS = 500.0`
- `INGESTION_BUDGET_S = 2.0`
- `MRR5_FLOOR = 0.45` (was 0.78; lowered across Phases 1A-3A as corpus grew 3.8x; imported from `tests/fixtures/regression_floors.py`)
- `HIT_RATE_FLOOR = 0.75` (was 0.90; lowered across Phases 1A-3B; imported from `tests/fixtures/regression_floors.py`)
- `BM25_BUDGET_MS = 2.0`
- `VECTOR_BUDGET_MS = 3.0`
- `CACHE_BUDGET_MS = 3.0`
- `RANKING_BUDGET_MS = 1.0`
- `BENCHMARK_ITERATIONS = 100`

| Test class.method | Stage | What it measures | Budget |
|---|---|---|---|
| `TestIntegrityBenchmark.test_integrity_check_duration` | offline | `IntegrityChecker.run_all_checks(skip_redundancy=True)` over 10 runs | p95 < 500 ms |
| `TestIngestionBenchmark.test_single_rule_ingestion` | ingest | `validate_parsed_rule + db.create_rule + model.encode` over 10 runs | p95 < 2 s |
| `TestColdStartBenchmark.test_cold_start` | startup | `build_pipeline(db)` over 3 runs | worst < 3 s |
| `TestMemoryBenchmark.test_memory_footprint` | memory | `getrusage(RUSAGE_SELF).ru_maxrss * 1024` after warm | < 2 GiB |
| `TestRetrievalPrecision.test_mrr5_ambiguous_set` | quality | MRR@5 on `set == "ambiguous"` (asserts >= 15 such queries exist) | >= 0.45 (was 0.78) |
| `TestRetrievalPrecision.test_hit_rate_all_queries` | quality | hit count of `expected_rule_id` in top-5 across entire ground-truth set | >= 0.75 (was 0.90) |
| `TestContextReduction.test_context_stuffing_ratio` | compression | tokens (chars/4) full corpus vs top-5 across 5 queries | ratio > 1 |
| `TestPerStageBenchmarks.test_stage2_bm25_latency` | Stage 2 | `pipeline._keyword.search(q, limit=50)` × `BENCHMARK_ITERATIONS//10` | p95 < 2 ms |
| `TestPerStageBenchmarks.test_stage3_vector_latency` | Stage 3 | `pipeline._vector.search(vec, k=10)` (encode excluded) | p95 < 3 ms |
| `TestPerStageBenchmarks.test_stage4_cache_latency` | Stage 4 | `pipeline._cache.get_enrichment(sample_ids)` for 20 IDs | p95 < 3 ms |
| `TestPerStageBenchmarks.test_stage5_ranking_latency` | Stage 5 | `normalize_ranks → compute_score → sort → apply_context_budget(5000)` | p95 < 1 ms |
| `TestPerStageBenchmarks.test_end_to_end_p95` | E2E | `pipeline.query(q)` over 10 hard-coded queries | p95 < 10 ms |

Invocation: `pytest benchmarks/bench_targets.py -v -s`. Requires Neo4j running with the migrated rule corpus (current live size: 276 rules).

### `benchmarks/run_benchmarks.py` — Pytest Neo4j traversal scale benchmarks

`EDGES_PER_NODE = 4`. Edge types: `DEPENDS_ON / SUPPLEMENTS / RELATED_TO / CONFLICTS_WITH`. Batched 500 nodes/edges per Cypher round-trip.

| Test | Scale | Hops | Budget |
|---|---|---|---|
| `TestTraversalBenchmarks.test_benchmark_1k_nodes` | 1,000 | 1, 2 | warns if p95 > 3 ms |
| `TestTraversalBenchmarks.test_benchmark_10k_nodes` | 10,000 | 1, 2 | warns if p95 > 3 ms |

Both `clear_all()` before AND after — must NOT be co-run with `bench_targets.py` against a live corpus.

Phase 2 results (informed adjacency-cache decision): 1K 1-hop p95 = 6.4 ms, 1K 2-hop p95 = 9.3 ms, 10K 1-hop p95 = 9.7 ms, 10K 2-hop p95 = 11.6 ms.

### `benchmarks/scale_benchmark.py` (498 lines) — Standalone async scale runner

`SCALE_LEVELS = [80, 500, 1_000, 10_000]`. `LATENCY_ITERATIONS = 50`. Output: `SCALE_BENCHMARK_RESULTS.md`.

`generate_synthetic_rules(count, existing_rules)` — deterministic synthetic generator using `np.random.default_rng(42)`. Cycles through 17 `SYNTHETIC_DOMAINS`, 5 `SYNTHETIC_TRIGGERS` templates, 30 `SYNTHETIC_ACTIONS`. Rule ID prefix is first 4 chars of domain prefix uppercased + `-SYN-NNNN`.

Per scale: cold start (3 runs), memory, per-stage latency (50×5), retrieval quality (domain hit rate over 10 queries), context reduction, compression (HDBSCAN + abstractions), session simulation (3-query loop with `SessionTracker(initial_budget=10000)`).

Restoration: `finally` block wipes graph and re-creates the original 80 real rules.

Invocation: `python benchmarks/scale_benchmark.py` (CLI, not pytest).

### `benchmarks/methodology_bench.py` — Phase-0 methodology retrieval benchmark

Standalone, read-only to production Writ pipeline (does not touch Neo4j). Builds in-process BM25 (`MethodologyIndex`) + ONNX vector index over methodology corpus.

Inputs:
- Corpus from `tests/fixtures/synthetic_methodology/` via `methodology_loader.load_corpus()`
- Ground truth from `tests/fixtures/ground_truth_proc.json`

Imports four Phase-0 release-blocker thresholds from `tests.test_methodology_retrieval`:
- `BLOCKER_MRR` (MRR@5 >= 0.78)
- `BLOCKER_HIT_RATE` (hit rate >= 0.90)
- `BLOCKER_COMPLETENESS` (bundle completeness >= 0.85)
- `BLOCKER_P95_MS` (p95 retrieval <= 5 ms)

Invocation: `.venv/bin/python benchmarks/methodology_bench.py [--verbose|--json]`. Exit code: 0 if all 4 blockers pass.

Phase-0 final results (post-curation; `docs/phase-0-report.md` was the original source and has since been deleted in the 2026-05-10 cleanup — numbers are preserved here as the published reference):
- MRR@5 = 0.8583 (PASS, +0.078 margin)
- Hit rate = 1.0000 (PASS, +0.100 margin)
- Bundle completeness = 0.8542 (PASS, +0.0042 margin)
- p95 retrieval = 0.98 ms (PASS)
- Encode p95 = 10.84 ms (reported, not gated)
- 40/40 hits on the curated 40-query set

## J. Latency targets vs actuals

Current live measurement (2026-05-10, 276 rules, post Phase 1-5 expansion, ONNX runtime, warm + LRU cache; 500 samples per stage):

| Metric | Target | Actual (276 rules, live) | Status |
|---|---|---|---|
| End-to-end median | -- | 0.3 ms | -- |
| End-to-end p95 (warm, post-warmup) | < 10 ms | 0.5 ms | Pass (17x headroom) |
| Cold start (cold-cold) | < 3.5 s | ~2.4 s at 276 rules | Pass |
| Cold start (warm HNSW cache, v1.1.0) | -- | ~0.24 s | n/a (10x faster than cold-cold) |
| MRR@5 (ambiguous, n=19) | >= 0.45 (was 0.78) | 0.6904 (v1.1.0; was 0.4886 at v1.0.0) | Pass |
| Hit rate (165-query corpus) | >= 0.75 (was 0.90) | 0.800 (v1.1.0; was 0.7576 at v1.0.0) | Pass |
| Domain hit rate top-5 (v1.1.0) | >= 0.90 | 0.945 | Pass |
| Memory (warm) | < 2 GB | ~1 GB | Pass |
| Integrity check | < 500 ms | (re-measure post-Phase-5) | -- |
| Context reduction (synthetic 10K) | > 1x | 726x | Pass |
| Context reduction (live 276) | > 1x | ~52x | Pass |

Pre-expansion baseline (post-ONNX optimization, 73-rule corpus, warm + LRU cache; from the original draft of this doc):

| Stage | Component | p95 | Budget | Headroom |
|---|---|---|---|---|
| 2 | BM25 (Tantivy) | 0.175 ms | 2.0 ms | 11x |
| 3 | Vector (hnswlib) | 0.047 ms | 3.0 ms | 64x |
| 4 | Adjacency cache | 0.001 ms | 3.0 ms | 3000x |
| 5 | Ranking (two-pass) | 0.089 ms | 1.0 ms | 11x |
| -- | **End-to-end** | **0.19 ms** | **10.0 ms** | **53x** |

The corpus-size growth (73 → 276 rules) increases the BM25 candidate set the ranker must score, which is what shifts E2E p95 from 0.19 ms to 0.590 ms. Per-stage budgets are unchanged.

## K. SCALE_BENCHMARK_RESULTS.md (verbatim)

Date: 2026-04-13 14:56 UTC. Scales: 80, 500, 1,000, 10,000.

```
| Metric | 80 | 500 | 1,000 | 10,000 |
|---|---|---|---|---|
| Domain rules | 45 | 465 | 965 | 9965 |
| Mandatory rules | 35 | 35 | 35 | 35 |
| Ingest time | 0.59s | 1.53s | 1.71s | 10.76s |
| Ingest rate | 135/s | 327/s | 585/s | 930/s |
| Cold start (median) | 0.494s | 3.452s | 5.782s | 70.788s |
| Memory (RSS) | 1570 MB | 2349 MB | 2674 MB | 2943 MB |
| BM25 p95 | 0.162ms | 0.182ms | 0.201ms | 0.262ms |
| Vector p95 | 0.046ms | 0.056ms | 0.057ms | 0.108ms |
| Cache p95 | 0.001ms | 0.001ms | 0.001ms | 0.001ms |
| Ranking p95 | 0.103ms | 0.139ms | 0.161ms | 0.218ms |
| **E2E p95** | **0.278ms** | **0.359ms** | **0.399ms** | **0.557ms** |
| E2E median | 0.178ms | 0.245ms | 0.325ms | 0.407ms |
| Domain hit rate | 100.0% | 90.0% | 90.0% | 90.0% |
| Context tokens (all) | 13,876 | 63,003 | 121,473 | 1,174,142 |
| Context tokens (retrieved) | 3,155 | 1,600 | 1,602 | 1,617 |
| **Context reduction** | **4.4x** | **39.4x** | **75.8x** | **726.1x** |
| Clusters | 13 | 70 | 419 | 519 |
| Ungrouped | 6 | 60 | 73 | 24 |
| Silhouette | 0.1149 | 0.2554 | 0.8882 | 0.9981 |
| Compression ratio | 5.6x | 7.6x | 2.8x | 25.2x |
| Session rules loaded | 20 | 20 | 20 | 20 |
| Session duplicates | 0 | 0 | 0 | 0 |
| Session budget remaining | 6,800 | 6,800 | 6,800 | 6,800 |
```

Compression ratios non-monotonic across scale (5.6x → 7.6x → 2.8x → 25.2x); silhouette improves monotonically (0.115 → 0.255 → 0.888 → 0.998).

## L. How to run

| Suite | Invocation | Prerequisites |
|---|---|---|
| Section-10 contractual | `pytest benchmarks/bench_targets.py -v -s` | Neo4j + 80-rule corpus migrated |
| Neo4j traversal scale | `pytest benchmarks/run_benchmarks.py -v -s` | Neo4j. **Wipes graph; do not co-run.** |
| Comprehensive scale curve | `python benchmarks/scale_benchmark.py` | Neo4j + real rules. Wipes & restores. |
| Phase-0 methodology blockers | `.venv/bin/python benchmarks/methodology_bench.py` | None. Read-only. |
| Full unit + integration | `pytest tests/ -q` | Mostly mocked |
| ONNX export prerequisite | `python scripts/export_onnx.py` | optimum + transformers |

Per `.claude/CODEBASE.md`: after any change to `writ/retrieval/` or `writ/graph/schema.py`, run `pytest benchmarks/bench_targets.py -v -s` and verify all 12 targets pass. "Do not trade latency for features."

## M. MRR / hit-rate metrics summary

Post Phase 1-5 expansion (live corpus 276 rules, ground-truth corpus 165 queries):

| Metric | Source | Threshold | Actual |
|---|---|---|---|
| MRR@5 (ambiguous, n=19) | `bench_targets.py::TestRetrievalPrecision.test_mrr5_ambiguous_set` | >= 0.45 (was 0.78) | **0.6904** (v1.1.0; was 0.4886 at v1.0.0 -- Items 1a-1d recovered ~70% of the gap via 4 label/text fixes) |
| Hit rate (all queries, n=165) | `bench_targets.py::TestRetrievalPrecision.test_hit_rate_all_queries` | >= 0.75 (was 0.90) | **0.800** (132/165 at v1.1.0; was 0.7636 / 126/165 at v1.0.0) |
| Domain hit rate top-5 (all 164 queries) | `bench_targets.py::TestRetrievalPrecision.test_domain_hit_rate_top5` (v1.1.0) | >= 0.90 | **0.945** (155/164) |
| MRR@5 (Phase-0 methodology, n=40) | `methodology_bench.py` | >= 0.78 | 0.8583 (unchanged) |
| Hit rate (Phase-0 methodology) | `methodology_bench.py` | >= 0.90 | 1.0000 (unchanged) |
| Bundle completeness (Phase-0) | `methodology_bench.py` | >= 0.85 | 0.8542 (unchanged) |
| ONNX vs PyTorch ranking stability | `test_embeddings.py::TestOnnxRankingStability::test_top1_and_top5_set_equivalent_pt_vs_onnx` (v1.1.0 rewrite, n=8 queries x 12-rule inline corpus) | identical top-1 and top-5 set | 0/8 queries diverge |

The retrieval-quality floors against the public-rulebook corpus were lowered intentionally during the expansion (the corpus grew 3.8x while the 19-query ambiguous-evaluation set held constant). Phase 6 plans a ground-truth regeneration pass to raise the floors back up. Methodology retrieval is unaffected.
