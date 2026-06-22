# Known Test Failures (pre-existing debt)

_Last updated: 2026-06-22 (Phase 6 install + verification)._

**Baseline:** `1680 passed / 55 failed / 19 skipped` running the full suite with the bootstrap
venv `python3` (≥ 3.11) on PATH and the daemon stopped:

```bash
WRIT_PORT=8765 bash scripts/stop-server.sh
PATH="$HOME/.cache/writ/.venv/bin:$PATH" ~/.cache/writ/.venv/bin/python -m pytest tests/ -q -p no:cacheprovider
```

**None of the 55 are Phase 6 regressions** — Phase 6 touched `bootstrap-plugin.sh`, `hooks.json`,
`writ-session-end.sh`, `pyproject.toml`, the project-rule engine/skills, and `writ-memory-policy-guard.sh`.
Verified: failing-test set is a strict subset of the pre-Phase-6 set, and the files Phase 6 touched
are all green. These are pre-existing fork / plugin-migration / environment debt.

> **Two large *non-bug* factors already resolved at run time** (not in this count):
> - **`python3` = 3.9.** macOS CommandLineTools `python3` can't import the ≥3.10 syntax helpers, so
>   test subprocesses return empty stdout → JSONDecodeError. ~80 "failures" vanish when a ≥3.11
>   `python3` is first on PATH. Run the suite as shown above.
> - **Legacy skill path.** Tests hardcode `SKILL_DIR = ~/.claude/skills/writ`. The plugin model
>   installs bare-name skills, so that dir is absent. A compat symlink restores it (cleared ~300
>   errors): `ln -sfn <repo> ~/.claude/skills/writ`.

---

## The 55, by root cause

### A. settings.json → hooks.json registration drift (~9) — EASY FIX
`test_pre_write_dispatch` (3), `test_cwd_changed` (2), `test_compaction_hooks` (2),
`test_instructions_loaded` (2).
Each asserts a hook is registered in `~/.claude/settings.json`. The plugin model registers hooks in
the plugin's `hooks/hooks.json`, not user settings. **Fix:** repoint each test's settings loader to
`<repo>/hooks/hooks.json` — exactly the fix already applied to
`tests/test_session_end.py::TestSessionEndRegistration` (use it as the template). Left unfixed only
because Phase 6 scoped to "tests adjacent to my edits"; these are mechanical and safe to batch.

### B. `writ import-markdown` asyncio teardown (16)
`test_import_markdown_unified`. The subprocess `writ import-markdown bible/` exits non-zero with
"Event loop stopped before Future …" (asyncio/FalkorDB teardown wart). **NOT a real break** —
`import-markdown` works in production (bootstrap ingests all 276 rules with it). Test-harness only.
**Fix direction:** make the CLI's `asyncio.run` teardown clean (await/close ordering in
`writ/cli.py import_markdown`), or mark these tests for the known teardown noise. Upstream async —
touches `writ/` core (adapt-only caution).

### C. phase5 analyzer assertions (12 + a few)
`test_phase5_analyzers` (12), `test_phase5_cli` (2), `test_phase5_dashboard` (1),
`test_exit_code_audit` (1), `test_methodology_companion_orchestrator` (1). Assertions like
`assert 0 == 1` — analyzers (`writ analyze-friction` family) return 0 rows where 1 is expected.
Likely fixture/seed data or analyzer-logic drift. Upstream logic — needs per-test investigation.

### D. Optional fallback dep not installed (2)
`test_integrity` — `ModuleNotFoundError: sentence_transformers` (`writ/graph/integrity.py:89`). This
is the **SentenceTransformer embedding fallback**, intentionally an optional extra
(`pip install -e ".[fallback]"`, gated behind `WRIT_ALLOW_EMBEDDING_FALLBACK=1`). **Fix:** either
install the `[fallback]` extra or guard the test with `importorskip`. Low priority (ONNX is the
production path).

### E. envsubst-dependent non-plugin installer (6)
`test_harness_installer` — `test_settings_is_valid_json_after_render` etc. render templates via
`envsubst`, which isn't installed here, and exercise the **non-plugin** `install-harness-config.sh`
path (unused in the plugin model). **Fix:** `brew install gettext`, or skip when `envsubst` absent,
or retire these tests if the non-plugin install path is dead.

### F. Misc (≈4)
`test_phase3_approval_flow` (2) — agent `.md` front-matter `name` assertions (check vs the Phase 4
`writ-plan-reviewer` rename). `test_phase3b_export_subagent_roles` (2),
`test_post_suite_restoration` (1). Per-test investigation needed; low volume.

---

## Environment requirements surfaced (document, not bugs)

- **`python3` ≥ 3.11 on PATH** to run the suite (test subprocesses call bare `python3`).
- **Daemon stopped** when running prod-graph tests (`test_import_markdown`, `test_integrity`,
  `test_post_suite_restoration`) — they open `.writ/graph.db` directly and a running daemon holds
  the single-writer lock.
- **`~/.claude/skills/writ` present** (plugin home or compat symlink) — many tests hardcode it.
- **bash 4+ preferred.** macOS default bash 3.2 mis-parses heredoc + embedded-quote combos. The one
  hook this actually broke (`writ-memory-policy-guard.sh`, deny path) was fixed by extracting its
  Python to `.claude/hooks/lib/memory_policy_match.py` (no inline heredoc). Other hooks pass
  `bash -n` under 3.2.
