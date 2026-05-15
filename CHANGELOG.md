# Changelog

All notable changes to Writ are documented in this file. The format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and the project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Added

- `AskUserQuestion` added to `permissions.deny` in `templates/settings.json`. Prevents the agent from opening an upfront clarifying-question wizard before producing a plan. The intended workflow is research first, then a plan with the agent's recommendation called out; the user redirects from the plan rather than answering a tabbed quiz.
- Cross-mode Writ command allowlist in `templates/settings.json`. Covers the read-only `bin/` diagnostic scripts (`check-gates`, `verify-files`, `scan-deps`, `run-analysis`, `validate-handoff`), the read-only `writ` CLI subcommands (`query`, `status`, `role-prompt`, `validate`, `analyze-friction`, `audit-session`), the idempotent install scripts under `scripts/` (`bootstrap`, `bootstrap-plugin`, `ensure-server`, `install-harness-config`, `install-user-commands`, `stop-server`), and the `writ-session.py` state machine. Patterns use wildcards (`*writ/...`) so a single entry matches both standalone (`$HOME/.claude/skills/writ/...`) and plugin (`${CLAUDE_PLUGIN_ROOT}/...`) command paths.
- `scripts/patch-global-config.sh` for plugin-mode users. Plugin installs render neither `templates/settings.json` into `~/.claude/settings.json` (the plugin manifest schema has no permissions field; `hooks/hooks.json` only registers hook events) nor `templates/CLAUDE.md` into `~/.claude/CLAUDE.md` (the plugin lifecycle does not touch the global instructions file). This script closes both gaps in a single run. The settings step merges the cross-mode allow/deny entries idempotently while preserving the user's existing ordering. The CLAUDE.md step renders the template via `envsubst '$HOME'`, skipping the write when the target already matches the template byte-for-byte. Both steps back up any pre-existing file before overwriting, and `--dry-run` previews the diff for each phase without touching disk. Requires `jq` and `envsubst`.
- `onnxruntime>=1.20,<2` added as a core production dependency in `pyproject.toml`. The writ runtime imports `onnxruntime` in `writ/retrieval/embeddings.py` to serve predictions from the ONNX-exported embedding model. Prior to this declaration, fresh `pip install -e .` runs (including the standalone and plugin bootstrap scripts) silently omitted the package, and `build_pipeline()` silently fell back to SentenceTransformer when `OnnxEmbeddingModel.__init__` raised `ImportError`. With the explicit ONNX contract from commit `dae679a` now in place, the daemon refuses to start when the package is missing, so this declaration is required for a fresh install to produce a working daemon without the `WRIT_ALLOW_EMBEDDING_FALLBACK=1` override. `onnxruntime` is wheel-distributed on Linux x86_64 and macOS arm64 for cpython 3.11+; `pip install` pulls a prebuilt manylinux wheel and does not require local compilation.
- `optimum[onnxruntime]>=2.0,<3` added to the `[dev]` optional-dependencies group. Build-time only: `scripts/export_onnx.py` uses optimum to convert the `sentence-transformers/all-MiniLM-L6-v2` checkpoint to the optimized ONNX graph that the runtime consumes via `onnxruntime`. The writ runtime itself never imports `optimum`; production installs do not pull it.
- New `[fallback]` optional-dependencies group declaring `sentence-transformers>=3.3,<4`. The production runtime no longer imports `sentence-transformers`; it is needed only for the `WRIT_ALLOW_EMBEDDING_FALLBACK=1` opt-in fallback path in `writ/retrieval/pipeline.py` and for two maintainer-only paths (`writ compress` and the integrity-check redundancy detection). Pulls the `torch` + nvidia CUDA transitive cascade (~5 GB) only when explicitly installed. The three-group partitioning rule established by this change: `[dependencies]` for production runtime, `[dev]` for build/test tooling (optimum, pytest, mypy, ruff), `[fallback]` for the opt-in SentenceTransformer path.

### Changed

- `scripts/bootstrap.sh` and `scripts/bootstrap-plugin.sh` install with `pip install -e '.[dev]'` (was bare `-e .`) so `optimum` is available for the ONNX export step. Both scripts now run `scripts/export_onnx.py` after install, gated on whether the model file is already present at `~/.cache/writ/models/onnx/model.onnx`. The skip path prints a one-line note with the model path so re-runs are transparent. End state after bootstrap: the daemon can start immediately on the production ONNX path without a separate manual export step. The `[fallback]` group is NOT installed by default; operators who want the SentenceTransformer fallback path must run `pip install -e '.[fallback]'` explicitly.
- `writ/retrieval/pipeline.py` fallback branch wraps the inline `from sentence_transformers import SentenceTransformer` in `try / except ImportError` and raises a `RuntimeError` naming the `[fallback]` extras install command when the operator has set `WRIT_ALLOW_EMBEDDING_FALLBACK=1` but the library is missing. Matches the actionable-error shape of the ONNX-unavailable case introduced in commit `dae679a`. Daemons configured for fallback now fail at startup with a clear remediation message rather than at first request with a bare `ImportError` traceback.
- `writ/cli.py` `writ compress` command wraps the inline `sentence_transformers` import. On `ImportError`, it now exits via `typer.Exit(code=1)` with a `rich`-formatted stderr message naming the `[fallback]` install command. Maintainer-only command; previously raised a bare `ImportError` traceback.
- `writ/graph/integrity.py::detect_redundant()` replaces the silent `try / except ImportError: return []` with `raise RuntimeError`. The empty-list silent-degradation behavior produced output indistinguishable from "no redundancies found" when `sentence-transformers` was not installed, the same bug class fixed for the ONNX silent fallback in commit `dae679a`. The new `RuntimeError` names the missing library, the `pip install -e '.[fallback]'` install command, and the `skip_redundancy=True` opt-out flag for callers that intentionally want to exclude this check (the integrity benchmark uses this opt-out, for example).
- `writ/graph/integrity.py::run_all_checks()` catches the new `RuntimeError` from `detect_redundant()` when `skip_redundancy=False`. The conflicts, orphans, stale, and confidence-default checks still run and report; the redundancy outcome is surfaced via a new `findings['redundancy_unavailable']` key carrying the error message. Degrade-loud-but-continue: a missing optional dep for one of five checks does not kill the integrity scan.
- `writ/cli.py` `writ validate` command prints `"Redundancy check skipped: <reason>"` to stderr when `findings['redundancy_unavailable']` is set, structurally parallel to the existing "Redundant (N):" block. Users who run `writ validate` against an install without `[fallback]` now see explicitly that the redundancy check could not run, rather than reading "no redundancies found" as the silent default.
- **Finding 9 (hardcoded credential drift, fixed repo-wide):** ~20 sites across `scripts/`, `benchmarks/`, and `tests/` previously declared `NEO4J_URI / NEO4J_USER / NEO4J_PASSWORD` as hardcoded literal constants or passed the literals inline to `Neo4jConnection()`. The codebase's claim ("Neo4j credentials are read from `writ.toml`") only held for `writ/cli.py` and `writ/server.py`; everywhere else, credentials were divergent copies. All ~20 sites now read via `writ.config.get_neo4j_uri / get_neo4j_user / get_neo4j_password`. `tests/test_config_integration.py` extends the existing meta-test (which previously covered three files) with a new parametrized `TestRepoWideNoHardcodedCreds` class that asserts no Python file under `writ/`, `scripts/`, `benchmarks/`, or `tests/` contains the canonical default password literal outside a documented allowlist (`writ/config.py` itself and the meta-test file). The meta-test now references `DEFAULT_NEO4J_PASSWORD` from `writ.config` rather than duplicating the literal, both for correctness (a future canonical-default change propagates automatically) and to avoid tripping the credential-literal pre-write scanner on the meta-test file itself.
- **Finding 10 (ONNX ranking flake, rewritten and unskipped):** `tests/test_embeddings.py::TestOnnxRankingStability::test_top5_identical_on_ground_truth` was skip-marked in commit `231ee41` because it produced 4 ADJACENT-SWAP divergences between PyTorch and ONNX top-5 rankings when run in isolation, while passing in the full `make test` suite. The flake was test-order dependent: the assertion relied on whatever corpus state Neo4j happened to be in when the test ran, and adjacent-swap inside top-5 is float32-precision noise that surfaces differently across corpus shapes. The replacement test (`test_top1_and_top5_set_equivalent_pt_vs_onnx`) declares a fixed inline corpus of 12 rules and 8 queries, embeds both with PyTorch and ONNX, and asserts top-1 strict equality AND top-5 SET equality. No Neo4j, no `build_pipeline`, no dependency on test execution order. The relaxed top-5-as-set assertion captures the production-meaningful property (the rules surfaced as relevant) without false-positives on adjacent-swap reordering. Skips gracefully if `sentence-transformers` is not installed (it lives in the `[fallback]` extras group per Finding D). Now runs as part of `make test`, deterministic across 3 sequential isolated runs.
- `templates/settings.README.md` now documents the standalone-only nature of both the rendered permissions block and the rendered CLAUDE.md, and points plugin-mode users at `scripts/patch-global-config.sh`.
- README "Install as a Claude Code plugin" section now references `scripts/patch-global-config.sh` so plugin users do not miss the global-config setup (permissions plus CLAUDE.md).
- `SKILL.md` server-requirements and architecture-reference sections now distinguish the standalone install path (`install-harness-config.sh`) from the plugin install path (`patch-global-config.sh`).
- `HANDBOOK.md` Getting started section adds a one-line pointer at the plugin install path and `patch-global-config.sh`.
- `docs/install-writ.md` recommends `install-harness-config.sh` (full install) and `patch-global-config.sh` (non-destructive permission/CLAUDE.md update) instead of the previous `cp` of `templates/settings.json`. The update-path and Known-limitations sections now reflect both options.
- `docs/plugin-validation.md` fresh-install smoke test includes a `patch-global-config.sh` step plus grep verifications that the `AskUserQuestion` deny rule and the Writ-flavored `CLAUDE.md` landed.
- `docs/SUBMISSION.md` pre-submission checklist now describes the README install steps as "install + bootstrap + patch-global-config" rather than the previous two-line shape.

### Notes

- Standalone-install users (whose `~/.claude/settings.json` was rendered from `templates/settings.json`) can re-run `bash scripts/install-harness-config.sh` to pick up the new permission entries. The installer is idempotent and backs up before overwriting.
- Mutating `writ` subcommands (`add`, `edit`, `import-markdown`, `export`, `compress`, `migrate`, `propose`, `review`, `feedback`, `serve`) remain gated behind explicit human approval. They are intentionally not in the allowlist; only their idempotent or read-only counterparts are auto-allowed.
- Combined with the explicit ONNX contract in commit `dae679a`, the production embedding path is now both declared (`pyproject.toml` lists `onnxruntime`) and enforced (`build_pipeline()` raises `RuntimeError` when `OnnxEmbeddingModel` cannot construct and the fallback override is unset). Existing installs that produced silently-degraded daemons will, after upgrade, either start correctly with ONNX or refuse to start with an actionable error message naming `scripts/export_onnx.py`, the override env var, and the venv install steps. This is desirable behavior, but it is a user-visible change: daemons that used to start by silently switching to the SentenceTransformer fallback will now require either the model file plus `onnxruntime` on the production path, or an explicit `WRIT_ALLOW_EMBEDDING_FALLBACK=1` plus `pip install -e '.[fallback]'` to permit the fallback.
- **Behavior change for existing users** following the `[fallback]` move. Existing standalone installs whose `.venv` was built before this change already have `sentence-transformers` from the prior core-deps declaration; the daemon continues to work without explicit action. Users who recreate their venv (`rm -rf .venv && bash scripts/bootstrap.sh`) get the lean install: no `sentence-transformers`, no `torch`, no CUDA libraries. Users who explicitly relied on `WRIT_ALLOW_EMBEDDING_FALLBACK=1` and re-bootstrap need to additionally run `pip install -e '.[fallback]'` to restore the fallback path. The startup `RuntimeError` names this command if hit.
- Plugin-mode users running `bash $(claude plugin path writ)/scripts/bootstrap-plugin.sh` get the same lean profile after re-bootstrap. Plugin install paths are unaffected for users who do not re-bootstrap.

## [1.0.1] - 2026-05-11

Patch release completing the v1 vision: Writ is now installable as a Claude Code plugin published through a same-repo marketplace. The standalone skill install path at `~/.claude/skills/writ/` is unchanged and continues to work byte-identically to v1.0.0; the plugin path is purely additive.

### Added

- `.claude-plugin/marketplace.json` declaring a same-repo, single-plugin marketplace catalog (`name: writ`, owner `infinri`, plugin source `./`).
- `.claude-plugin/plugin.json` rewritten to conform to the official plugin schema (`name`, `version`, `description`, `author`, `homepage`, `repository`, `license`, `keywords`, plus the four component-path fields `skills`/`commands`/`agents`/`hooks`). The previously declared `permissions`, `defaultEnabled`, and `lifecycle` fields were never honored by Claude Code and have been dropped.
- `hooks/hooks.json` plugin auto-discovery manifest covering all 32 hook event registrations using `${CLAUDE_PLUGIN_ROOT}` paths so the plugin can be upgraded without rewiring hooks.
- `hooks/scripts/session-start-bootstrap.sh`, a SessionStart probe that detects venv/Neo4j/daemon state on fresh plugin installs, prints actionable setup instructions when prerequisites are missing, and launches `writ serve` in the background when everything is in place. Always exits 0; never blocks the session.
- `scripts/bootstrap-plugin.sh`, the plugin-aware one-time setup script. Creates the venv outside the plugin cache dir so it survives plugin upgrades, brings up Neo4j, ingests the rule bible, and starts the daemon. Idempotent.
- `templates/settings.README.md` documenting the two install paths (plugin auto-discovery via `hooks/hooks.json` versus legacy standalone via `templates/settings.json` rendered into `~/.claude/settings.json`).
- `docs/plugin-validation.md`, a maintainer reference for validating a Writ release (static `claude plugin validate`, pytest skeleton, fresh-install smoke test, rollback procedure).
- `docs/SUBMISSION.md`, the Anthropic plugin marketplace submission packet (pre-submission checklist, listing copy, screenshots checklist, submission procedure).
- `.github/workflows/publish.yml`, the tag-triggered GitHub Actions workflow that builds sdist + wheel and publishes to PyPI via Trusted Publisher OIDC.

### Changed

- `pyproject.toml` PyPI distribution name renamed from `writ` (taken by an unrelated package) to `claude-writ`. The Python module name (`import writ`) and the console script (`writ`) are unchanged. Standard PyPI metadata added: `readme`, `keywords`, `classifiers`, and `[project.urls]` (Homepage, Repository, Issues, Changelog, Documentation).
- Plugin-mode venv lives at `${CLAUDE_PLUGIN_DATA:-$HOME/.cache/writ}/.venv`, and the package is installed there via `pip install -e ${CLAUDE_PLUGIN_ROOT}`. Editable installs let plugin upgrades that rewrite the cache dir keep working without a venv rebuild. Standalone installs continue to use `${WRIT_DIR}/.venv`.
- `scripts/ensure-server.sh`, `scripts/stop-server.sh`, and `.claude/hooks/writ-rag-inject.sh` learned dual-mode `${CLAUDE_PLUGIN_ROOT}` branches. When the env var is set by Claude Code, `WRIT_DIR` and the venv path resolve against the plugin install; when unset, the original `dirname` walk runs. Standalone behavior is byte-identical.
- `pyproject.toml`, `SKILL.md` frontmatter, and the marketplace/plugin manifests all declare version `1.0.1`.

### Notes

- `templates/settings.json` is still the source of truth for standalone installs. The plugin path uses `hooks/hooks.json` instead. Keep registrations in sync between the two if you edit either.
- Existing standalone installs at `~/.claude/skills/writ/` continue working unchanged. See README "Switching from the standalone install to the plugin" if you'd rather move to the plugin path; the Neo4j named volume `writ-neo4j-data` is shared between modes, so the rule corpus survives the switch.

## [1.0.0] - 2026-05-10

First production release. Writ ships as a Claude Code harness with two co-equal layers (hybrid-RAG knowledge service plus session-aware enforcement) over a Neo4j-backed knowledge graph.

### Released

**Knowledge layer (the librarian).** FastAPI service on `localhost:8765` running a five-stage hybrid retrieval pipeline:
- Stage 1: Domain filter (sub-millisecond, post-filter on candidate set).
- Stage 2: BM25 keyword (Tantivy, in-memory; trigger-field boost 2.0x, body 0.5x).
- Stage 3: ANN vector (hnswlib over ONNX `all-MiniLM-L6-v2` embeddings, LRU cache 1024, HNSW persistence with corpus-hash invalidation).
- Stage 4: Graph traversal (pre-computed adjacency cache; built once at startup, O(1) lookup).
- Stage 5: Two-pass ranking (reciprocal-rank fusion + weighted linear combination over BM25, vector, severity, confidence, graph proximity, bundle cohesion; sticky tiebreak for prompt-cache stability).

Live latency at the 276-rule corpus: **0.590 ms p95 end-to-end** (17x headroom on the 10 ms budget). Synthetic scale curve holds at 0.557 ms p95 through 10K rules with 726x context reduction vs whole-corpus stuffing.

**Enforcement layer (the process keeper).** 30 hook scripts under `.claude/hooks/`, wired via `templates/settings.json`, plus a 2,090-line session state machine in `bin/lib/writ-session.py`. Four-mode system (Conversation, Debug, Review, Work) with two Work-mode gates (`phase-a` plan approval, `test-skeletons` test approval). Approval requires a one-time token written by the actual user-typed approval path; agent self-approval via raw bash is structurally blocked.

**Public rulebook (220 rules across 12 domains).** Security, Clean Code, DRY, SOLID, Architecture, Testing, Error Handling, Performance & Caching, Scaling, API Design, Process & Lifecycle, Documentation. Inventory in `out-of-the-box-rules.md`. Live corpus extends this with Writ-specific rules (ENF-PROC-*, FW-M2-*, PHP-*, PY-*, META-*) for a total of 276 rules / 30 mandatory.

**Static-analysis backing for mandatory rules.** Six cross-language regex analyzers in `bin/run-analysis.sh` enforce the 19 public-rulebook mandatory rules:
- `analyze_security_injection`: SQL injection, XSS, command injection, SSRF, deserialization, CSRF.
- `analyze_security_auth_authz`: weak password hashes, non-CSPRNG tokens, mass assignment, missing route auth, unvalidated request body, file-upload sinks.
- `analyze_security_crypto_headers`: hardcoded secrets (Stripe, AWS, GitHub, PEM), AES ECB, weak RNG in crypto context, `verify=False`.
- `analyze_security_data_protection`: PII identifiers in logger calls.
- `analyze_performance_n_plus_one`: loop-body DB calls with the loop variable.
- `analyze_scaling_stateless`: module-level user/session globals.

**AI rule proposal with structural gate.** `POST /propose` runs five checks (schema validation, mechanical-enforcement requirement for mandatory rules, specificity against a 10-pattern vague-language blocklist, redundancy/novelty thresholds at 0.95/0.85 cosine, conflict detection). Accepted rules enter as `authority: ai-provisional`, `confidence: speculative`.

**Frequency-driven graduation.** Stop-hook auto-feedback correlates loaded rules with static-analysis pass/fail and posts to `/feedback`. Graduation at n=50 and ratio>=0.75 substitutes the empirical ratio for the static confidence weight at query time.

**Sub-agent isolation.** Two flags compose cleanly: `is_subagent` (set on SubagentStart, bypasses gates and budget skips) and `is_orchestrator` (set on `mode set work --orchestrator`, suppresses broad RAG injection on the master and emits a compact status line instead).

### Architecture invariants

- **Pre-computation philosophy.** Tantivy index, hnswlib index, ONNX model, adjacency cache, and abstraction summaries are all built at startup from Neo4j and served from memory. Nothing is computed at query time that could have been computed earlier.
- **Mandatory-vs-retrieved structural split.** Mandatory rules are excluded from BM25 and the vector store at index-build time. They are loaded out-of-band by hooks with their own 5,000-token budget cap. No change to ranking weights, embedding model, or graph traversal can cause a mandatory rule to disappear from agent context.
- **Authority preference.** Human-authored rules outrank AI-authored rules at equal relevance (hard rerank within a configurable score band).
- **Sticky rule ordering.** Within a 0.02 score band, the ranker stabilizes injection order from `last_injected_rule_ids` for prompt-cache stability across turns.

### Verification (cited from the v1 release commit)

- 1,441 tests pass, 15 skipped, 0 failed.
- 12 contractual benchmark targets pass.
- Live service: 276 rules, 30 mandatory, index state warm.
- MRR@5 (ambiguous, n=19): 0.4886 (floor 0.45).
- Hit rate (Phase 6 ground-truth corpus, n=165): 0.7636 (floor 0.75).
- Methodology MRR@5 (n=40): 0.8583 (unchanged from Phase-0 baseline).

### Documentation

`README.md`, `HANDBOOK.md`, `PROMOTIONAL-BRIEF.md`, `SCALE_BENCHMARK_RESULTS.md`, `SKILL.md`, `CONTRIBUTING.md`, plus `out-of-the-box-rules.md` for the public rule inventory. Detailed codebase deep-dives in `docs/extraction/01` through `docs/extraction/12`. Install instructions in `docs/install-writ.md`. Monthly review template in `docs/monthly-reviews/TEMPLATE.md`. Historical pressure-run records preserved in `docs/pressure-runs/`.

### Known limitations

- Retrieval-quality floors were lowered during the Phase 1-5 public-rulebook expansion (MRR@5 from 0.78 to 0.45, hit-rate from 0.90 to 0.75) as the ambiguous-evaluation set held constant at 19 queries while the corpus grew 3.8x. The Phase 6 plan in the roadmap is to regenerate the ground-truth corpus and raise the floors back up.
- `POST /pre-write-check` still emits a `[ENF-GATE-FINAL]` deny string when the path contains `"COMPLETE"`, while `ENF-GATE-FINAL` itself was removed from the corpus during the 2026-05-10 cleanup. Known drift in `writ/server.py:1075-1083`, not load-bearing.
- The synthetic scale benchmark restores only Rule nodes; do not regenerate the curve without first re-exporting and re-importing the methodology corpus.
