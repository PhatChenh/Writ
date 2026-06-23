"""Writ CLI -- typer entrypoint for all writ commands."""

from __future__ import annotations

import asyncio
import json
import os
from pathlib import Path

import typer

from writ.config import get_falkordb_path, get_falkordb_graph, get_falkordb_module, get_redis_bin

DEFAULT_BIBLE_DIR = "bible/"
DEFAULT_HOST = "localhost"
# Honor the per-repo WRIT_PORT (derived in bin/lib/common.sh, D4-02 "A-auto")
# so `writ serve` with no --port binds the same port the hooks query. An
# explicit --port still wins; falls back to 8765 when WRIT_PORT is unset.
DEFAULT_PORT = int(os.environ.get("WRIT_PORT", "8765"))

app = typer.Typer(
    name="writ",
    help="Hybrid RAG knowledge retrieval service for AI coding rule enforcement.",
)


@app.command(name="analyze-friction")
def analyze_friction(
    log: Path = typer.Option(
        Path("workflow-friction.log"),
        help="Path to the friction log. Defaults to ./workflow-friction.log.",
    ),
    since: int = typer.Option(0, help="Only include events from the last N days (0 = all)."),
    top: int = typer.Option(10, help="Cap top-N rankings."),
    rotate: bool = typer.Option(False, help="Rotate log to .1 if it exceeds 5MB, then exit."),
    json_output: bool = typer.Option(False, "--json", help="Emit structured JSON instead of text."),
    rule: str | None = typer.Option(None, "--rule", help="Filter events to a single rule_id."),
    rule_effectiveness: bool = typer.Option(False, "--rule-effectiveness", help="Per-rule denial-stick-rate (Phase 5)."),
    skill_usage: bool = typer.Option(False, "--skill-usage", help="Skill loads vs playbook completion (Phase 5)."),
    playbook_compliance: bool = typer.Option(False, "--playbook-compliance", help="Per-playbook in-order compliance (Phase 5)."),
    graduation_candidates: bool = typer.Option(False, "--graduation-candidates", help="Rules ready to graduate (Phase 5)."),
    trim_candidates: bool = typer.Option(False, "--trim-candidates", help="Rules / skills with low activation (Phase 5)."),
    quality_judge_false_positives: bool = typer.Option(False, "--quality-judge-false-positives", help="Per-rubric override rates (Phase 5)."),
) -> None:
    """Summarize workflow-friction.log: event counts, hook p95s, top rules, gate activity.

    Phase 5 flags select a single analyzer and emit a focused report. They
    are mutually exclusive with each other and with the default summary.
    """
    from writ.analysis.friction import (
        load_events, summarize, format_report, rotate_if_needed,
        parse_log, aggregate_by_rule, aggregate_by_event,
        analyze_rule_effectiveness, analyze_skill_usage,
        analyze_playbook_compliance, analyze_graduation_candidates,
        analyze_trim_candidates, analyze_quality_judge_false_positives,
    )

    if rotate:
        rotated = rotate_if_needed(log)
        typer.echo(f"{'rotated' if rotated else 'no rotation needed'}: {log}")
        return

    # Phase 5: mutual exclusion of analyzer flags.
    phase5_flags = {
        "--rule-effectiveness": rule_effectiveness,
        "--skill-usage": skill_usage,
        "--playbook-compliance": playbook_compliance,
        "--graduation-candidates": graduation_candidates,
        "--trim-candidates": trim_candidates,
        "--quality-judge-false-positives": quality_judge_false_positives,
    }
    active = [name for name, on in phase5_flags.items() if on]
    if len(active) > 1:
        typer.echo(
            f"Error: flags {', '.join(active)} are mutually exclusive. Use one at a time.",
            err=True,
        )
        raise typer.Exit(code=2)

    # Phase 5 dispatch.
    if active:
        flag = active[0]
        events = parse_log(log)
        since_days = since if since > 0 else 0
        rows: list = []
        if flag == "--rule-effectiveness":
            rows = analyze_rule_effectiveness(events, since_days=since_days or 30, top=top)
            headers = ["rule_id", "activations", "stuck", "stick_rate", "rationalizations"]
            cells = [[r.rule_id, r.activations, r.stuck_denials,
                      f"{r.denial_stick_rate:.2f}", r.rationalizations] for r in rows]
        elif flag == "--skill-usage":
            rows = analyze_skill_usage(events, since_days=since_days or 60, top=top)
            headers = ["skill_id", "loads", "completions", "completion_rate"]
            cells = [[r.skill_id, r.loads, r.completions,
                      f"{r.completion_rate:.2f}"] for r in rows]
        elif flag == "--playbook-compliance":
            rows = analyze_playbook_compliance(events, since_days=since_days or 30, top=top)
            headers = ["playbook_id", "runs", "compliant", "skip_points"]
            cells = [[r.playbook_id, r.runs, r.compliant_runs,
                      ", ".join(r.common_skip_points)] for r in rows]
        elif flag == "--graduation-candidates":
            rows = analyze_graduation_candidates(events, top=top)
            headers = ["rule_id", "days_stable", "current", "recommended", "stick_rate"]
            cells = [[r.rule_id, r.days_stable, r.current_tier, r.recommended_tier,
                      f"{r.denial_stick_rate:.2f}"] for r in rows]
        elif flag == "--trim-candidates":
            rows = analyze_trim_candidates(events, since_days=since_days or 90, top=top)
            headers = ["entity", "type", "activations", "last_seen", "recommendation"]
            cells = [[r.entity_id, r.entity_type, r.activations_in_window,
                      r.last_activation or "-", r.recommendation] for r in rows]
        else:  # --quality-judge-false-positives
            rows = analyze_quality_judge_false_positives(events, since_days=since_days or 30, top=top)
            headers = ["rubric", "fails", "overrides", "override_rate"]
            cells = [[r.rubric, r.total_fails, r.overrides,
                      f"{r.override_rate:.2f}"] for r in rows]

        if json_output:
            typer.echo(json.dumps([r.model_dump() for r in rows]))
        else:
            typer.echo(" | ".join(str(h) for h in headers))
            typer.echo("-" * 60)
            for row in cells:
                typer.echo(" | ".join(str(c) for c in row))
        return

    # Phase 4 path: Pydantic-validated events with --json / --rule filters.
    if json_output or rule:
        events = parse_log(log)
        if rule:
            events = [e for e in events if e.rule_id == rule]
        payload = {
            "by_rule": aggregate_by_rule(events),
            "by_event": aggregate_by_event(events),
            "total": len(events),
        }
        if json_output:
            typer.echo(json.dumps(payload))
        else:
            typer.echo(f"Events matching rule={rule}: {payload['total']}")
            for rid, n in payload["by_rule"].items():
                typer.echo(f"  {rid}: {n}")
            for evt, n in payload["by_event"].items():
                typer.echo(f"  event={evt}: {n}")
        return

    events = load_events(log)
    since_days = since if since > 0 else None
    summary = summarize(events, top=top, since_days=since_days)
    typer.echo(format_report(summary))


@app.command(name="audit-session")
def audit_session(
    session_id: str = typer.Argument(..., help="The session id to audit."),
    log: Path = typer.Option(
        Path("workflow-friction.log"),
        help="Path to the friction log. Defaults to ./workflow-friction.log.",
    ),
    json_output: bool = typer.Option(False, "--json", help="Emit structured JSON instead of text."),
) -> None:
    """Per-session timeline + summary from workflow-friction.log.

    Filters the friction log to one session_id and presents:
      - Phase progression (planning -> testing -> implementation -> complete)
      - Mode + orchestrator state
      - Rule / skill / playbook loads with counts
      - Gate denials with the offending rule_id
      - Subagent dispatches
      - Always-on bundle injections
      - Token consumption breakdown by query_source

    Structured per-session audit -- filterable, machine-parseable,
    persists across compactions and session boundaries.
    """
    import json as _json
    from collections import Counter

    from writ.analysis.friction import load_events

    events = load_events(log)
    session_events = [e for e in events if e.get("session") == session_id]

    if not session_events:
        if json_output:
            typer.echo(_json.dumps({
                "session": session_id,
                "event_count": 0,
                "message": "no events found for this session",
            }))
        else:
            typer.echo(f"No events found for session {session_id} in {log}.")
        return

    # Aggregate signals.
    event_counts: Counter[str] = Counter()
    phase_transitions: list[dict] = []
    rule_loads: Counter[str] = Counter()
    skill_loads: Counter[str] = Counter()
    playbook_loads: Counter[str] = Counter()
    gate_denials: list[dict] = []
    subagents: list[dict] = []
    tokens_by_source: Counter[str] = Counter()
    always_on_injects = 0
    always_on_tokens = 0
    playbook_completions: list[dict] = []
    mode_changes: list[dict] = []

    for e in session_events:
        ev = e.get("event", "?")
        event_counts[ev] += 1

        if ev == "phase_advance":
            phase_transitions.append({
                "ts": e.get("ts"),
                "from": e.get("from_phase"),
                "to": e.get("to_phase"),
                "source": e.get("confirmation_source"),
            })
        elif ev == "rag_query":
            qs = e.get("query_source") or "unknown"
            tokens_by_source[qs] += int(e.get("tokens_injected") or 0)
            for rid in (e.get("rule_ids") or []):
                if isinstance(rid, str):
                    rule_loads[rid] += 1
                    if rid.startswith("SKL-"):
                        skill_loads[rid] += 1
                    elif rid.startswith("PBK-"):
                        playbook_loads[rid] += 1
        elif ev == "always_on_inject":
            always_on_injects += 1
            always_on_tokens += int(e.get("tokens") or 0)
        elif ev == "gate_denial":
            gate_denials.append({
                "ts": e.get("ts"),
                "rule_id": e.get("rule_id"),
            })
        elif ev in ("subagent_start", "subagent_complete"):
            subagents.append({
                "ts": e.get("ts"),
                "kind": ev,
                "type": e.get("subagent_type"),
            })
        elif ev == "playbook_step_complete":
            playbook_completions.append({
                "ts": e.get("ts"),
                "playbook_id": e.get("playbook_id"),
                "step_id": e.get("step_id"),
                "step_index": e.get("step_index"),
                "total_steps": e.get("total_steps"),
            })
        elif ev == "mode_change":
            mode_changes.append({
                "ts": e.get("ts"),
                "from": e.get("from_mode"),
                "to": e.get("to_mode"),
            })

    if json_output:
        typer.echo(_json.dumps({
            "session": session_id,
            "event_count": len(session_events),
            "first_ts": session_events[0].get("ts"),
            "last_ts": session_events[-1].get("ts"),
            "event_counts": dict(event_counts),
            "phase_transitions": phase_transitions,
            "mode_changes": mode_changes,
            "rule_loads": dict(rule_loads.most_common()),
            "skill_loads": dict(skill_loads.most_common()),
            "playbook_loads": dict(playbook_loads.most_common()),
            "gate_denials": gate_denials,
            "subagents": subagents,
            "playbook_completions": playbook_completions,
            "always_on_injects": always_on_injects,
            "always_on_tokens": always_on_tokens,
            "tokens_by_source": dict(tokens_by_source),
        }, indent=2))
        return

    # Text format.
    out: list[str] = []
    out.append(f"=== Session audit: {session_id} ===")
    out.append(f"Events: {len(session_events)} "
               f"(first={session_events[0].get('ts')}, last={session_events[-1].get('ts')})")

    if mode_changes:
        out.append("")
        out.append("Mode changes:")
        for m in mode_changes:
            out.append(f"  {m['ts']}  {m['from']} -> {m['to']}")

    if phase_transitions:
        out.append("")
        out.append("Phase progression:")
        for p in phase_transitions:
            out.append(f"  {p['ts']}  {p['from']} -> {p['to']}  ({p['source']})")

    out.append("")
    out.append("Tokens injected by source:")
    if always_on_injects:
        out.append(f"  always_on        {always_on_tokens:>6}  ({always_on_injects} injects)")
    for src, tok in tokens_by_source.most_common():
        out.append(f"  {src:<16} {tok:>6}")

    if skill_loads:
        out.append("")
        out.append("Skill loads:")
        for sid, n in skill_loads.most_common():
            out.append(f"  {sid:<32} {n}")

    if playbook_loads:
        out.append("")
        out.append("Playbook loads:")
        for pid, n in playbook_loads.most_common():
            out.append(f"  {pid:<32} {n}")

    if gate_denials:
        out.append("")
        out.append(f"Gate denials: {len(gate_denials)}")
        for g in gate_denials:
            out.append(f"  {g['ts']}  denied: {g['rule_id']}")

    if subagents:
        out.append("")
        out.append("Subagent dispatches:")
        for s in subagents:
            out.append(f"  {s['ts']}  {s['kind']:<18} {s['type']}")

    if playbook_completions:
        out.append("")
        out.append("Playbook step completions:")
        for c in playbook_completions:
            out.append(f"  {c['ts']}  {c['playbook_id']} step {c['step_index']}/{c['total_steps']} ({c['step_id']})")

    out.append("")
    out.append("Top event types:")
    for ev, n in event_counts.most_common(10):
        out.append(f"  {ev:<28} {n}")

    typer.echo("\n".join(out))


@app.command()
def serve(
    port: int = typer.Option(DEFAULT_PORT, help="Port to bind the service to."),
    host: str = typer.Option(DEFAULT_HOST, help="Host to bind the service to."),
) -> None:
    """Start Writ service. Pre-warms indexes into memory."""
    import uvicorn

    from writ.server import app as fastapi_app

    typer.echo(f"Starting Writ service on {host}:{port}")
    typer.echo("Pre-warming indexes...")
    uvicorn.run(fastapi_app, host=host, port=port, log_level="info")


@app.command(name="import-markdown")
def import_markdown(
    path: Path = typer.Argument(Path(DEFAULT_BIBLE_DIR), help="Path to Markdown source directory."),
    only: str | None = typer.Option(
        None,
        "--only",
        help="Comma-separated node_types to import (e.g. 'Rule', 'Skill,Playbook'). Default: import all.",
    ),
    dry_run: bool = typer.Option(
        False,
        "--dry-run",
        help="Parse and validate without writing to the database.",
    ),
) -> None:
    """Import bible content (Rules + methodology) into the graph. Validates schema. Triggers export."""
    from writ.graph.db import FalkorDBLiteConnection
    from writ.graph.methodology_ingest import (
        KNOWN_NODE_TYPES,
        ingest_path,
    )

    # Parse --only CSV.
    parsed_only: set[str] | None = None
    if only is not None:
        parsed_only = {tok.strip() for tok in only.split(",") if tok.strip()}
        if not parsed_only:
            parsed_only = None

    # Validate every --only token before any DB work; surface a clean error
    # with the unknown token AND the sorted list of valid types (API-ERROR-002).
    if parsed_only:
        unknown = sorted(parsed_only - KNOWN_NODE_TYPES)
        if unknown:
            valid = sorted(KNOWN_NODE_TYPES)
            typer.echo(
                f"Error: unknown --only type(s): {', '.join(unknown)}. "
                f"Valid types: {', '.join(valid)}.",
                err=True,
            )
            raise typer.Exit(code=2)

    async def _run() -> int:
        db = FalkorDBLiteConnection(
            get_falkordb_path(), get_falkordb_graph(),
            get_falkordb_module(), get_redis_bin(),
        )
        try:
            report = await ingest_path(
                path, db, only=parsed_only, dry_run=dry_run,
            )
            typer.echo(report.render())
            for err in report.errors:
                typer.echo(str(err), err=True)

            total_nodes = sum(report.counts_by_type.values())
            # Auto-export only on a full-corpus import against the canonical
            # bible root. On a subdirectory import (e.g. `bible/methodology/`)
            # the exporter would write the WHOLE graph back through a
            # file-location lookup that only sees files inside that subdir;
            # rules whose original files live outside the scope fall through
            # to `<output_dir>/<domain>/rules.md` and create bogus duplicates.
            is_default_root = (
                path.resolve() == Path(DEFAULT_BIBLE_DIR).resolve()
            )
            if (
                not dry_run
                and not report.errors
                and total_nodes > 0
                and parsed_only is None
                and is_default_root
            ):
                from writ.export import export_rules_to_markdown

                export_result = await export_rules_to_markdown(db, path)
                typer.echo(
                    f"Exported {export_result['rules_exported']} rules to {path}"
                )
            return 1 if report.errors else 0
        finally:
            await db.close()

    exit_code = asyncio.run(_run())
    if exit_code:
        raise typer.Exit(code=exit_code)


@app.command()
def validate(
    review_confidence: bool = typer.Option(
        False, "--review-confidence", help="List rules at migration default confidence."
    ),
    benchmark: bool = typer.Option(False, "--benchmark", help="Report integrity check duration."),
) -> None:
    """Run integrity checks: conflicts, orphans, staleness, redundancy."""
    import time

    from writ.graph.db import FalkorDBLiteConnection
    from writ.graph.integrity import IntegrityChecker

    async def _run() -> int:
        db = FalkorDBLiteConnection(
            get_falkordb_path(), get_falkordb_graph(),
            get_falkordb_module(), get_redis_bin(),
        )
        try:
            checker = IntegrityChecker(db)
            start = time.perf_counter()
            findings = await checker.run_all_checks()
            elapsed_ms = (time.perf_counter() - start) * 1000

            if findings["conflicts"]:
                typer.echo(f"\nConflicts ({len(findings['conflicts'])}):")
                for c in findings["conflicts"]:
                    typer.echo(f"  {c['rule_a']} <-> {c['rule_b']}")

            if findings["orphans"]:
                typer.echo(f"\nOrphans ({len(findings['orphans'])}):")
                for o in findings["orphans"]:
                    typer.echo(f"  {o}")

            if findings["stale"]:
                typer.echo(f"\nStale ({len(findings['stale'])}):")
                for s in findings["stale"]:
                    typer.echo(f"  {s['rule_id']} (expired {s['expired_on']})")

            if findings["redundant"]:
                typer.echo(f"\nRedundant ({len(findings['redundant'])}):")
                for r in findings["redundant"]:
                    typer.echo(f"  {r['rule_a']} ~ {r['rule_b']} ({r['similarity']})")
            if findings.get("redundancy_unavailable"):
                # Redundancy check could not run (missing optional dep).
                # Surface explicitly so the user does not read silence as
                # "no redundancies found." Same principle as the explicit
                # ONNX-fallback contract in writ/retrieval/pipeline.py
                # (commit dae679a): wire-format silence is indistinguishable
                # from a clean check; the gate must say which it is.
                typer.echo(
                    f"\nRedundancy check skipped: {findings['redundancy_unavailable']}",
                    err=True,
                )

            if findings.get("unreviewed"):
                u = findings["unreviewed"]
                typer.echo(f"\nUnreviewed AI-provisional: {u['message']}")

            if findings.get("frequency_stale"):
                typer.echo(f"\nFrequency stale ({len(findings['frequency_stale'])}):")
                for fs in findings["frequency_stale"][:10]:
                    typer.echo(f"  {fs['rule_id']} (last_seen: {fs.get('last_seen', 'never')})")

            if findings.get("graduation_flags"):
                typer.echo(f"\nGraduation flags ({len(findings['graduation_flags'])}):")
                for gf in findings["graduation_flags"]:
                    typer.echo(f"  {gf['rule_id']} (ratio: {gf['ratio']}, n={gf['n']})")

            if review_confidence:
                defaults = await checker.detect_confidence_defaults()
                typer.echo(f"\nRules at default confidence ({len(defaults)}):")
                for d in defaults:
                    typer.echo(f"  {d}")

            if benchmark:
                typer.echo(f"\nIntegrity check completed in {elapsed_ms:.1f}ms")

            if findings["exit_code"] == 0:
                typer.echo("\nAll checks passed.")
            else:
                typer.echo("\nFindings detected.")

            return findings["exit_code"]
        finally:
            await db.close()

    code = asyncio.run(_run())
    raise typer.Exit(code=code)


@app.command()
def add() -> None:
    """Add a new rule to the graph with relationship suggestion and validation."""
    from datetime import date

    from writ.authoring import (
        RuleIdCollisionError,
        check_conflicts,
        check_id_collision,
        check_redundancy,
        suggest_relationships,
    )
    from writ.graph.db import FalkorDBLiteConnection
    from writ.graph.schema import Rule
    from writ.retrieval.pipeline import build_pipeline
    from writ.retrieval.traversal import AdjacencyCache

    async def _run() -> None:
        # Collect required fields.
        rule_id = typer.prompt("rule_id (e.g., ARCH-NEW-001)")
        domain = typer.prompt("domain")
        severity = typer.prompt("severity (critical/high/medium/low)")
        scope = typer.prompt("scope (file/module/slice/pr/session)")
        trigger = typer.prompt("trigger")
        statement = typer.prompt("statement")
        violation = typer.prompt("violation")
        pass_example = typer.prompt("pass_example")
        enforcement = typer.prompt("enforcement")
        rationale = typer.prompt("rationale")

        rule_data = {
            "rule_id": rule_id,
            "domain": domain,
            "severity": severity,
            "scope": scope,
            "trigger": trigger,
            "statement": statement,
            "violation": violation,
            "pass_example": pass_example,
            "enforcement": enforcement,
            "rationale": rationale,
            "last_validated": date.today().isoformat(),
        }

        db = FalkorDBLiteConnection(
            get_falkordb_path(), get_falkordb_graph(),
            get_falkordb_module(), get_redis_bin(),
        )
        try:
            # ID collision check runs before schema validation so an author
            # re-using an existing rule_id fails fast without spending time
            # on the rest of the gate. MERGE in create_rule would silently
            # update the existing node otherwise.
            try:
                await check_id_collision(rule_id, db)
            except RuleIdCollisionError as e:
                typer.echo(f"rule_id already exists: {e.rule_id}")
                typer.echo(f"  existing statement: {e.existing.get('statement', '')[:100]}")
                typer.echo("Use `writ edit` to modify, or choose a different rule_id.")
                raise typer.Exit(code=1)

            # INV-6: Validate against schema before any graph write.
            try:
                Rule(**rule_data)
            except Exception as e:
                typer.echo(f"Validation error: {e}")
                raise typer.Exit(code=1)

            typer.echo("Building pipeline for relationship analysis...")
            pipeline = await build_pipeline(db)
            cache = AdjacencyCache()
            await cache.build_from_db(db)

            # Redundancy check.
            redundant = check_redundancy(rule_data, pipeline)
            if redundant:
                typer.echo("\nRedundancy warning (>= 0.95 cosine similarity):")
                for r in redundant:
                    typer.echo(f"  {r['rule_id']} (similarity: {r['similarity']})")
                    typer.echo(f"    {r['statement'][:100]}")

            # Relationship suggestions.
            suggestions = suggest_relationships(rule_data, pipeline)
            if suggestions:
                typer.echo("\nSuggested relationships:")
                for i, s in enumerate(suggestions, 1):
                    typer.echo(f"  {i}. {s['rule_id']} (score: {s['score']})")
                    typer.echo(f"     {s['statement'][:100]}")

            # Write rule to graph.
            await db.create_rule(rule_data)
            typer.echo(f"\nCreated rule: {rule_id}")

            # Offer to create edges for accepted suggestions.
            if suggestions:
                for s in suggestions:
                    edge_types = ["DEPENDS_ON", "SUPPLEMENTS", "CONFLICTS_WITH", "RELATED_TO"]
                    create = typer.confirm(f"Create edge to {s['rule_id']}?", default=False)
                    if create:
                        edge_type = typer.prompt(
                            f"Edge type ({'/'.join(edge_types)})",
                            default="RELATED_TO",
                        )
                        if edge_type in edge_types:
                            await db.create_edge(edge_type, rule_id, s["rule_id"])
                            typer.echo(f"  Created {edge_type} -> {s['rule_id']}")
                        else:
                            typer.echo(f"  Unknown edge type: {edge_type}, skipped.")

            # Conflict check after edges are created.
            await cache.build_from_db(db)
            conflicts = check_conflicts(rule_id, cache)
            if conflicts:
                typer.echo("\nConflict warning:")
                for c in conflicts:
                    typer.echo(f"  CONFLICTS_WITH {c['rule_id']}")

            # Auto-export after add (Phase 7).
            from writ.export import export_rules_to_markdown

            export_result = await export_rules_to_markdown(db, Path(DEFAULT_BIBLE_DIR))
            typer.echo(f"\nExported {export_result['rules_exported']} rules to {DEFAULT_BIBLE_DIR}")
        finally:
            await db.close()

    asyncio.run(_run())


@app.command()
def edit(
    rule_id: str = typer.Argument(..., help="ID of the rule to edit."),
) -> None:
    """Edit an existing rule in the graph."""
    from writ.authoring import check_conflicts, check_redundancy, suggest_relationships
    from writ.graph.db import FalkorDBLiteConnection
    from writ.graph.schema import Rule
    from writ.retrieval.pipeline import build_pipeline
    from writ.retrieval.traversal import AdjacencyCache

    async def _run() -> None:
        db = FalkorDBLiteConnection(
            get_falkordb_path(), get_falkordb_graph(),
            get_falkordb_module(), get_redis_bin(),
        )
        try:
            existing = await db.get_rule(rule_id)
            if existing is None:
                typer.echo(f"Rule not found: {rule_id}")
                raise typer.Exit(code=1)

            typer.echo(f"Editing rule: {rule_id}")
            typer.echo("Press Enter to keep current value.\n")

            fields = ["domain", "severity", "scope", "trigger", "statement",
                       "violation", "pass_example", "enforcement", "rationale"]
            updated = dict(existing)
            for field in fields:
                current = existing.get(field, "")
                display = str(current)[:80] if current else "(empty)"
                new_val = typer.prompt(f"{field} [{display}]", default=str(current))
                updated[field] = new_val

            # INV-6: Validate before write.
            try:
                Rule(**updated)
            except Exception as e:
                typer.echo(f"Validation error: {e}")
                raise typer.Exit(code=1)

            typer.echo("Building pipeline for relationship analysis...")
            pipeline = await build_pipeline(db)
            cache = AdjacencyCache()
            await cache.build_from_db(db)

            # Redundancy check on updated text.
            redundant = check_redundancy(updated, pipeline)
            # Filter out self from redundancy results.
            redundant = [r for r in redundant if r["rule_id"] != rule_id]
            if redundant:
                typer.echo("\nRedundancy warning:")
                for r in redundant:
                    typer.echo(f"  {r['rule_id']} (similarity: {r['similarity']})")

            # Re-suggest relationships.
            suggestions = suggest_relationships(updated, pipeline)
            if suggestions:
                typer.echo("\nSuggested relationships:")
                for i, s in enumerate(suggestions, 1):
                    typer.echo(f"  {i}. {s['rule_id']} (score: {s['score']})")

            # INV-7: MERGE = idempotent update.
            await db.create_rule(updated)
            typer.echo(f"\nUpdated rule: {rule_id}")

            # Offer edges.
            if suggestions:
                for s in suggestions:
                    create = typer.confirm(f"Create edge to {s['rule_id']}?", default=False)
                    if create:
                        edge_type = typer.prompt("Edge type", default="RELATED_TO")
                        await db.create_edge(edge_type, rule_id, s["rule_id"])
                        typer.echo(f"  Created {edge_type} -> {s['rule_id']}")

            # Conflict check.
            await cache.build_from_db(db)
            conflicts = check_conflicts(rule_id, cache)
            if conflicts:
                typer.echo("\nConflict warning:")
                for c in conflicts:
                    typer.echo(f"  CONFLICTS_WITH {c['rule_id']}")

            # Auto-export after edit (Phase 7).
            from writ.export import export_rules_to_markdown

            export_result = await export_rules_to_markdown(db, Path(DEFAULT_BIBLE_DIR))
            typer.echo(f"\nExported {export_result['rules_exported']} rules to {DEFAULT_BIBLE_DIR}")
        finally:
            await db.close()

    asyncio.run(_run())


@app.command()
def export(
    output: Path = typer.Argument(Path(DEFAULT_BIBLE_DIR), help="Output directory for generated Markdown."),
) -> None:
    """Regenerate Markdown from graph. Overwrites output directory."""
    from writ.export import export_rules_to_markdown
    from writ.graph.db import FalkorDBLiteConnection

    async def _run() -> None:
        db = FalkorDBLiteConnection(
            get_falkordb_path(), get_falkordb_graph(),
            get_falkordb_module(), get_redis_bin(),
        )
        try:
            result = await export_rules_to_markdown(db, output)
            typer.echo(f"Exported {result['rules_exported']} rules to {output}")
        finally:
            await db.close()

    asyncio.run(_run())


@app.command()
def compress() -> None:
    """Cluster rules into abstraction nodes for compressed retrieval."""
    import numpy as np

    try:
        from sentence_transformers import SentenceTransformer
    except ImportError as exc:
        # Approach C (Finding D): sentence-transformers moved out of
        # core deps because the production daemon does not import it.
        # `writ compress` is a maintainer-only command that regenerates
        # abstraction nodes via clustering, and that pipeline uses the
        # SentenceTransformer model. Surface the missing dep as an
        # actionable typer-style error rather than a bare ImportError
        # traceback; mirrors the shape of the ONNX-unavailable error
        # in writ/retrieval/pipeline.py (commit dae679a).
        typer.echo(
            "ERROR: `writ compress` requires the sentence-transformers "
            f"library, which could not be imported ({type(exc).__name__}: "
            f"{exc}).\n"
            "\n"
            "Production installs deliberately exclude this library (see "
            "pyproject.toml: it lives in the [fallback] extras group, "
            "not core dependencies). Install it with:\n"
            "    pip install -e '.[fallback]'\n"
            "Then re-run `writ compress`.",
            err=True,
        )
        raise typer.Exit(code=1) from exc

    from writ.compression.abstractions import generate_abstractions, write_abstractions_to_graph
    from writ.compression.clusters import evaluate_both
    from writ.graph.db import FalkorDBLiteConnection

    async def _run() -> None:
        db = FalkorDBLiteConnection(
            get_falkordb_path(), get_falkordb_graph(),
            get_falkordb_module(), get_redis_bin(),
        )
        try:
            # Load non-mandatory rules.
            all_rules = await db.get_all_rules()
            domain_rules = [r for r in all_rules if not r.get("mandatory", False)]
            if not domain_rules:
                typer.echo("No domain rules to cluster.")
                raise typer.Exit(code=0)

            typer.echo(f"Clustering {len(domain_rules)} domain rules...")
            model = SentenceTransformer("all-MiniLM-L6-v2")
            texts = [f"{r.get('trigger', '')} {r.get('statement', '')}" for r in domain_rules]
            embeddings = np.array(model.encode(texts), dtype=np.float32)

            comparison = evaluate_both(
                [r["rule_id"] for r in domain_rules], embeddings,
            )
            typer.echo(f"\nHDBSCAN: {len(comparison.hdbscan.clusters)} clusters, "
                       f"silhouette={comparison.hdbscan.silhouette:.3f}")
            typer.echo(f"k-means: {len(comparison.kmeans.clusters)} clusters, "
                       f"silhouette={comparison.kmeans.silhouette:.3f}")
            typer.echo(f"Chosen: {comparison.chosen} ({comparison.reason})")

            chosen_result = (
                comparison.hdbscan if comparison.chosen == "hdbscan" else comparison.kmeans
            )

            abstractions = generate_abstractions(chosen_result, domain_rules)
            count = await write_abstractions_to_graph(db, abstractions)

            avg_ratio = 0.0
            if abstractions:
                avg_ratio = sum(a["compression_ratio"] for a in abstractions) / len(abstractions)

            typer.echo(f"\nCreated {count} abstractions")
            typer.echo(f"Ungrouped rules: {len(chosen_result.ungrouped)}")
            typer.echo(f"Average compression ratio: {avg_ratio:.1f}x")
        finally:
            await db.close()

    asyncio.run(_run())


@app.command(name="role-prompt")
def role_prompt(
    role: str = typer.Argument(..., help="Subagent role name (writ-explorer, writ-planner, etc.) or ROL-* id."),
) -> None:
    """Print the graph-canonical prompt template for a SubagentRole.

    Phase 3 Section 8.2 release blocker: `writ review prompt <role>` returns
    graph-canonical text. Implemented as `writ role-prompt <role>` to avoid
    collision with the existing `writ review <rule_id>` command. The graph
    is the canonical source (plan Section 8.1 deliverable 2); .claude/agents
    files are exported from the graph.
    """
    import asyncio
    from writ.graph.db import FalkorDBLiteConnection

    async def _fetch() -> None:
        db = FalkorDBLiteConnection(
            get_falkordb_path(), get_falkordb_graph(),
            get_falkordb_module(), get_redis_bin(),
        )
        try:
            query = """
                MATCH (r:SubagentRole)
                WHERE r.name = $name
                   OR r.role_id = $name
                   OR r.role_id = 'ROL-' + toUpper(replace($name, 'writ-', '')) + '-001'
                RETURN r.role_id AS role_id, r.name AS name,
                       r.prompt_template AS prompt,
                       r.model_preference AS model
                LIMIT 1
            """
            role_rows = db._execute_query(query, {"name": role})
            rec = role_rows[0] if role_rows else None
            if rec is None:
                typer.echo(f"SubagentRole '{role}' not found in graph.", err=True)
                raise typer.Exit(code=1)
            typer.echo(f"# {rec['role_id']}  (name={rec['name']}, model={rec['model']})")
            typer.echo("")
            typer.echo(rec["prompt"])
        finally:
            await db.close()

    asyncio.run(_fetch())


@app.command()
def migrate() -> None:
    """One-time migration of existing rules into graph.

    Backward-compat shim: delegates to `writ import-markdown` with default args.
    """
    from writ.graph.db import FalkorDBLiteConnection
    from writ.graph.methodology_ingest import ingest_path

    path = Path(DEFAULT_BIBLE_DIR)

    async def _run() -> int:
        db = FalkorDBLiteConnection(
            get_falkordb_path(), get_falkordb_graph(),
            get_falkordb_module(), get_redis_bin(),
        )
        try:
            report = await ingest_path(path, db, only=None, dry_run=False)
            typer.echo(report.render())
            for err in report.errors:
                typer.echo(str(err), err=True)
            return 1 if report.errors else 0
        finally:
            await db.close()

    code = asyncio.run(_run())
    if code:
        raise typer.Exit(code=code)


@app.command()
def query(
    query_text: str = typer.Argument(..., help="Natural language query for rule retrieval."),
    domain: str | None = typer.Option(None, help="Filter by domain."),
    budget: int | None = typer.Option(None, help="Context budget in tokens."),
) -> None:
    """CLI rule query for testing retrieval quality."""
    from writ.graph.db import FalkorDBLiteConnection
    from writ.retrieval.pipeline import build_pipeline

    async def _run() -> None:
        db = FalkorDBLiteConnection(
            get_falkordb_path(), get_falkordb_graph(),
            get_falkordb_module(), get_redis_bin(),
        )
        try:
            typer.echo("Building pipeline (loading indexes)...")
            pipeline = await build_pipeline(db)
            typer.echo(f"Querying: {query_text}\n")
            result = pipeline.query(
                query_text=query_text,
                domain=domain,
                budget_tokens=budget,
            )
            typer.echo(f"Mode: {result['mode']} | Candidates: {result['total_candidates']} | Latency: {result['latency_ms']}ms\n")
            for i, rule in enumerate(result["rules"], 1):
                typer.echo(f"  {i}. [{rule['score']}] {rule['rule_id']}")
                if "statement" in rule:
                    typer.echo(f"     {rule['statement'][:100]}")
                typer.echo()
        finally:
            await db.close()

    asyncio.run(_run())


@app.command()
def feedback(
    rule_id: str = typer.Argument(..., help="Rule ID to record feedback for."),
    signal: str = typer.Argument(..., help="Signal: 'positive' or 'negative'."),
) -> None:
    """Record positive or negative feedback for a rule (hook integration)."""
    from writ.graph.db import FalkorDBLiteConnection

    if signal not in ("positive", "negative"):
        typer.echo(f"Invalid signal: {signal}. Must be 'positive' or 'negative'.")
        raise typer.Exit(code=1)

    async def _run() -> None:
        db = FalkorDBLiteConnection(
            get_falkordb_path(), get_falkordb_graph(),
            get_falkordb_module(), get_redis_bin(),
        )
        try:
            if signal == "positive":
                found = await db.increment_positive(rule_id)
            else:
                found = await db.increment_negative(rule_id)

            if not found:
                typer.echo(f"Rule not found: {rule_id}")
                raise typer.Exit(code=1)
            typer.echo(f"Recorded {signal} feedback for {rule_id}")
        finally:
            await db.close()

    asyncio.run(_run())


@app.command()
def propose(
    rule_id: str = typer.Option(..., help="Rule ID for the proposed rule."),
    domain: str = typer.Option(..., help="Domain of the rule."),
    severity: str = typer.Option(..., help="Severity (critical/high/medium/low)."),
    scope: str = typer.Option(..., help="Scope of the rule."),
    trigger: str = typer.Option(..., help="When this rule applies."),
    statement: str = typer.Option(..., help="What the rule requires."),
    violation: str = typer.Option(..., help="Example violation."),
    pass_example: str = typer.Option(..., help="Example of passing."),
    enforcement: str = typer.Option(..., help="How the rule is enforced."),
    rationale: str = typer.Option(..., help="Why this rule exists."),
    task_description: str = typer.Option("", help="What the AI was doing when it proposed this rule."),
) -> None:
    """Propose an AI-generated rule. Runs structural gate before ingestion."""
    from datetime import date

    from writ.gate import propose_rule
    from writ.graph.db import FalkorDBLiteConnection
    from writ.origin_context import DEFAULT_DB_PATH
    from writ.retrieval.pipeline import build_pipeline

    candidate = {
        "rule_id": rule_id,
        "domain": domain,
        "severity": severity,
        "scope": scope,
        "trigger": trigger,
        "statement": statement,
        "violation": violation,
        "pass_example": pass_example,
        "enforcement": enforcement,
        "rationale": rationale,
        "last_validated": date.today().isoformat(),
    }

    async def _run() -> None:
        db = FalkorDBLiteConnection(
            get_falkordb_path(), get_falkordb_graph(),
            get_falkordb_module(), get_redis_bin(),
        )
        try:
            typer.echo("Building pipeline...")
            pipeline = await build_pipeline(db)

            result = await propose_rule(
                candidate,
                pipeline,
                db,
                origin_db_path=DEFAULT_DB_PATH,
                task_description=task_description,
            )

            if result["accepted"]:
                typer.echo(f"Accepted: {result['rule_id']} (authority: ai-provisional)")
            else:
                typer.echo(f"Rejected: {result['rule_id']}")
                for reason in result.get("reasons", []):
                    typer.echo(f"  - {reason}")
        finally:
            await db.close()

    asyncio.run(_run())


@app.command()
def review(
    rule_id: str = typer.Argument(None, help="Rule ID to inspect. Omit to list all unreviewed."),
    promote: bool = typer.Option(False, "--promote", help="Promote AI-provisional to ai-promoted."),
    reject: bool = typer.Option(False, "--reject", help="Delete AI-provisional rule from graph."),
    downweight: bool = typer.Option(False, "--downweight", help="Set confidence floor (speculative)."),
    stats: bool = typer.Option(False, "--stats", help="Show review queue statistics."),
) -> None:
    """Review AI-proposed rules. List, inspect, promote, reject, or downweight."""
    from writ.graph.db import FalkorDBLiteConnection

    async def _run() -> None:
        db = FalkorDBLiteConnection(
            get_falkordb_path(), get_falkordb_graph(),
            get_falkordb_module(), get_redis_bin(),
        )
        try:
            if stats:
                counts = await db.count_by_authority()
                total = sum(counts.values())
                typer.echo("Review queue statistics:")
                for authority, count in sorted(counts.items()):
                    typer.echo(f"  {authority}: {count}")
                typer.echo(f"  total: {total}")
                return

            if rule_id is None:
                # List all ai-provisional rules.
                rules = await db.get_rules_by_authority("ai-provisional")
                if not rules:
                    typer.echo("No AI-provisional rules in queue.")
                    return
                typer.echo(f"Unreviewed AI-provisional rules ({len(rules)}):\n")
                for r in rules:
                    typer.echo(f"  {r.get('rule_id', '?')}")
                    typer.echo(f"    trigger: {str(r.get('trigger', ''))[:80]}")
                    typer.echo(f"    statement: {str(r.get('statement', ''))[:80]}")
                    typer.echo()
                return

            # Inspect or act on a specific rule.
            existing = await db.get_rule(rule_id)
            if existing is None:
                typer.echo(f"Rule not found: {rule_id}")
                raise typer.Exit(code=1)

            if promote:
                if existing.get("authority") != "ai-provisional":
                    typer.echo(f"Cannot promote: {rule_id} has authority '{existing.get('authority', 'human')}'")
                    raise typer.Exit(code=1)
                confirm = typer.confirm(f"Promote {rule_id} to ai-promoted?")
                if not confirm:
                    typer.echo("Cancelled.")
                    return
                await db.update_rule_authority(rule_id, "ai-promoted")
                await db.update_rule_confidence(rule_id, "peer-reviewed")
                typer.echo(f"Promoted: {rule_id} (authority: ai-promoted, confidence: peer-reviewed)")
                return

            if reject:
                if existing.get("authority") != "ai-provisional":
                    typer.echo(f"Cannot reject: {rule_id} has authority '{existing.get('authority', 'human')}'")
                    raise typer.Exit(code=1)
                confirm = typer.confirm(f"Delete {rule_id} from graph?")
                if not confirm:
                    typer.echo("Cancelled.")
                    return
                await db.delete_rule(rule_id)
                typer.echo(f"Rejected and deleted: {rule_id}")
                return

            if downweight:
                confirm = typer.confirm(f"Downweight {rule_id} to speculative confidence?")
                if not confirm:
                    typer.echo("Cancelled.")
                    return
                await db.update_rule_confidence(rule_id, "speculative")
                typer.echo(f"Downweighted: {rule_id} (confidence: speculative)")
                return

            # Default: inspect the rule.
            typer.echo(f"Rule: {rule_id}")
            typer.echo(f"  authority: {existing.get('authority', 'human')}")
            typer.echo(f"  domain: {existing.get('domain', '')}")
            typer.echo(f"  severity: {existing.get('severity', '')}")
            typer.echo(f"  confidence: {existing.get('confidence', '')}")
            typer.echo(f"  trigger: {existing.get('trigger', '')}")
            typer.echo(f"  statement: {existing.get('statement', '')}")

            # Show origin context if available.
            try:
                from writ.origin_context import OriginContextStore

                store = OriginContextStore()
                ctx = store.get(rule_id)
                store.close()
                if ctx:
                    typer.echo("\n  Origin context:")
                    typer.echo(f"    task: {ctx['task_description']}")
                    typer.echo(f"    query: {ctx.get('query_that_triggered', 'N/A')}")
                    typer.echo(f"    consulted: {', '.join(ctx.get('existing_rules_consulted', []))}")
                    typer.echo(f"    created: {ctx['created_at']}")
                else:
                    typer.echo("\n  Origin context: not recorded")
            except Exception:
                typer.echo("\n  Origin context: not available")

        finally:
            await db.close()

    asyncio.run(_run())


@app.command()
def status() -> None:
    """Health check: rule count, index status, last ingestion, stale rules."""
    import httpx

    try:
        resp = httpx.get(f"http://{DEFAULT_HOST}:{DEFAULT_PORT}/health", timeout=5.0)
        data = resp.json()
        typer.echo(json.dumps(data, indent=2))
    except httpx.ConnectError:
        typer.echo("Service not running. Start with: writ serve")
        raise typer.Exit(code=1)


if __name__ == "__main__":
    app()
