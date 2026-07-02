<!-- RULE START: WRITOPS-AUTHOR-001 -->
## Rule WRITOPS-AUTHOR-001

**Domain**: writ-ops
**Severity**: High
**Scope**: Component
**Mandatory**: false

### Trigger
When authoring or editing a Writ rule (choosing its `Domain:` frontmatter) that is meant to surface via standard RAG retrieval.

### Statement
Default (semantic) retrieval silently excludes rules whose domain is `process`, `communication`, or `meta-authoring` (`methodology_domain_exclude` in the retrieval pipeline). A rule in those domains exists in the graph and is served by `/rule/{id}`, but never surfaces in standard `/query` injection. Rules intended for normal RAG injection must use any other domain; methodology-flavored rules that must inject go under `enforcement` or a topical domain.

### Violation
```text
Setting the frontmatter domain field to "process" for a rule meant to guide agents
— it will never inject via RAG. (NB: never write the literal bold Domain-colon
frontmatter pattern inside an example block; the importer greedily matches the
LAST occurrence in the rule block and silently reassigns the rule's domain.)
```

### Pass
```text
Set the frontmatter domain field to "enforcement" or a topical domain
(ui-ux, writ-ops, testing…) so the rule participates in default retrieval.
```

### Enforcement
After authoring + import, run one representative `/query` and confirm the new rule ID appears; a rule that never surfaces in its own trigger scenario is mis-domained.

### Rationale
THINK-* rules were silently invisible until moved to `enforcement`. An unretrievable rule is worse than no rule — it looks covered while covering nothing.

<!-- RULE END: WRITOPS-AUTHOR-001 -->
---

<!-- RULE START: WRITOPS-EVIDENCE-001 -->
## Rule WRITOPS-EVIDENCE-001

**Domain**: writ-ops
**Severity**: Medium
**Scope**: Component
**Mandatory**: false

### Trigger
When marking a TodoWrite item completed in a Writ work-mode session guarded by the verification-evidence gate (ENF-PROC-VERIFY-001).

### Statement
The gate keys evidence on the todo's `content[:40]` — the first 40 characters, exactly. Before marking a todo completed, post evidence via `writ-session.py verification-evidence <session-id> --todo "<first 40 chars of the todo content>" --command "<verify cmd>" --output "<observed output>"`. A mismatch in those 40 characters (paraphrase, trimmed whitespace, edited todo text) makes the evidence unmatched and the completion blocked.

### Violation
```bash
# todo content: "Ingest rules into Writ graph + verify retrieval"
writ-session.py verification-evidence $SID --todo "Ingest rules" …   # not content[:40] → no match
```

### Pass
```bash
writ-session.py verification-evidence $SID \
  --todo "Ingest rules into Writ graph + verify r" \
  --command "curl -s localhost:$PORT/rule/UIUX-FORM-001" \
  --output '{"rule":{"rule_id":"UIUX-FORM-001"…}'
```

### Enforcement
The gate itself blocks completion without matching evidence; this rule exists so agents key it correctly on the first try.

### Rationale
Exact-prefix keying is unforgiving by design; knowing the `content[:40]` contract avoids gate fights and fake-evidence workarounds.

<!-- RULE END: WRITOPS-EVIDENCE-001 -->
---

<!-- RULE START: WRITOPS-IMPORT-001 -->
## Rule WRITOPS-IMPORT-001

**Domain**: writ-ops
**Severity**: High
**Scope**: Component
**Mandatory**: false

### Trigger
When running `writ import-markdown` (bible re-seed, rule promotion, new rule domain) or any operation that writes the Writ graph from outside the daemon.

### Statement
The import requires the daemon stopped: the running server holds `graph.lock` and the CLI refuses to start. Full sequence: (1) stop the repo's daemon (per-repo port; find PID via `pgrep -f 'uvicorn writ.server'`), (2) run `writ import-markdown <dir>` (use `--dry-run` first to validate schema), (3) expect the triggered export to REWRITE and re-sort the bible markdown files (graph-canonical), (4) restart the daemon, (5) verify per WRITOPS-IMPORT-002. Never edit the exported markdown expecting it to be authoritative — the graph is.

### Violation
```bash
writ import-markdown bible   # while daemon runs → RuntimeError: graph DB is locked by PID …
# or: hand-editing exported rules.md and treating the file order/content as stable
```

### Pass
```bash
kill <daemon-pid> && sleep 2
writ import-markdown bible --dry-run && writ import-markdown bible
# restart daemon, then verify (WRITOPS-IMPORT-002)
```

### Enforcement
Import output shows node counts + "Exported N rules"; lock error means step 1 skipped.

### Rationale
The lock is held by the server process, and export-after-import is by design (graph-canonical authoring): markdown churn after import is expected, not corruption.

<!-- RULE END: WRITOPS-IMPORT-001 -->
---

<!-- RULE START: WRITOPS-IMPORT-002 -->
## Rule WRITOPS-IMPORT-002

**Domain**: writ-ops
**Severity**: High
**Scope**: Component
**Mandatory**: false

### Trigger
After a `writ import-markdown` completes and before claiming the new/changed rules are live.

### Statement
Import success output does not guarantee persistence: the embedded redis saves the RDB (`.writ/graph.db`) only on graceful shutdown or save-points, so a disturbed import leaves the graph file at its PRE-import snapshot — the next daemon restart silently resurrects old data (CLI `writ query` may still show new rules from a live orphan redis while the daemon does not). Verify all three before claiming done: (1) `.writ/graph.db` mtime advanced past the import time, (2) restarted daemon `/health` rule_count reflects the change, (3) daemon `/rule/<new-id>` returns the rule and a representative `/query` surfaces it. The embedded redis socket lives at `/tmp/writ-<md5(abs path of .writ dir)[:12]>/redis.sock` (hash of the directory, not the db file) for direct `redis-cli -s … GRAPH.QUERY` inspection.

### Violation
```bash
writ import-markdown bible && echo "rules live"   # RDB may still be pre-import
```

### Pass
```bash
writ import-markdown bible
ls -la .writ/graph.db                    # mtime advanced
# restart daemon…
curl -s localhost:$PORT/rule/NEW-ID-001  # 200 with rule body
curl -s -X POST localhost:$PORT/query -d '{"query":"<trigger scenario>"}'  # ID surfaces
```

### Enforcement
The three checks above are the definition of "import done"; skipping them is a verify-before-claim violation.

### Rationale
Observed failure: rules retrievable via CLI (live orphan redis) but absent from the daemon after restart — the RDB predated the import. Only the disk snapshot survives restarts.

<!-- RULE END: WRITOPS-IMPORT-002 -->
