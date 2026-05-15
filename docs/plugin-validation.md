# Plugin validation procedure

How to verify a Writ release is ready to ship as a Claude Code plugin.

## 1. Static validation

```shell
claude plugin validate /path/to/Writ
```

Expected output: exit code 0, no `ERROR` or `WARNING` lines. The
validator checks:

- `.claude-plugin/marketplace.json` schema conformance
- `.claude-plugin/plugin.json` schema conformance
- Skill frontmatter in `SKILL.md`
- Hooks JSON syntax in `hooks/hooks.json`
- Agent and command frontmatter in `.claude/agents/`, `.claude/commands/`

## 2. Pytest skeleton

```shell
cd /path/to/Writ
.venv/bin/python3 -m pytest tests/plugin/ -v
```

Note: invoke pytest via the project venv (`.venv/bin/python3`), not the system `python3`. The system interpreter on many machines lacks `onnxruntime`, which causes `OnnxEmbeddingModel.__init__` to raise `ImportError` and `build_pipeline()` to silently fall through to the SentenceTransformer fallback. The bench would then measure a non-production code path. The `Makefile` already pins `PYTHON` to the venv; this command does the same explicitly.

Expected: all phase-A/B/C/D tests pass; only the `pytest.skip()`
markers remain: `test_bootstrap_plugin_idempotent` (requires shell
sandbox) and `test_fresh_install_marketplace_plugin_smoke` (requires
`WRIT_INTEGRATION_TESTS=1`).

## 3. Fresh-install smoke test (manual)

Clone to a clean dir; install into a throwaway Claude Code session;
verify all the moving parts:

```shell
TMP=/tmp/writ-fresh-$(uuidgen | head -c 8)
git clone https://github.com/infinri/Writ.git "$TMP"
claude plugin marketplace add "$TMP"
claude plugin install writ@writ
PLUGIN_DIR=$(claude plugin path writ)
bash "$PLUGIN_DIR/scripts/bootstrap-plugin.sh"
curl -fsS http://localhost:8765/health
# Expect: {"status":"healthy"}
test -f "${CLAUDE_PLUGIN_DATA:-$HOME/.cache/writ}/.venv/bin/python3" && echo OK
# Expect: OK

bash "$PLUGIN_DIR/scripts/patch-global-config.sh"
# Expect: "[settings] Patched ..." and "[CLAUDE.md] Created ..." (or
# "No changes needed" on re-runs, since the script is idempotent).
grep -q '"AskUserQuestion"' "$HOME/.claude/settings.json" && echo OK
# Expect: OK (deny rule landed)
grep -q 'Always read at session start' "$HOME/.claude/CLAUDE.md" && echo OK
# Expect: OK (template rendered)
```

Open a new Claude Code session and submit a prompt; verify a
`--- WRIT RULES ---` block appears in the context.

## 4. Rollback

If a release fails validation:

```shell
claude plugin uninstall writ@writ
claude plugin marketplace remove writ
git tag -d v1.1.0       # replace with the actual failing release tag
git push origin :refs/tags/v1.1.0  # if already pushed
```

The Neo4j Docker volume (`writ-neo4j-data`) persists across uninstalls;
no rule re-ingest is required for the next attempt.
