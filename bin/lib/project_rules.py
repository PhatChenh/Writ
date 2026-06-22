#!/usr/bin/env python3
"""Project-rule authoring engine (Phase 6 / D4-04, adapt-only).

Project-specific CONSTRAINTS are authored as Rule nodes with a `PROJ-` id
prefix and `authority=human`, then exported to the repo's committed
`docs/rules/` (the per-repo bible layer). The shared `bible/` (universal
corpus) is a separate layer seeded by-value into every repo's graph.

This script is a thin consumer of `writ.*` — it adds ZERO behaviour to Writ
core. It reuses `writ.gate.structural_gate` (conflict/dup screening),
`writ.export` helpers (markdown generation), and `writ.graph.db` (ingest).

Subcommands:
  author  — gate-check + ingest one constraint as authority=human, then export
  export  — write all PROJ- rules from the graph to docs/rules/ (filter by prefix)
  list    — print all PROJ- constraints verbatim (the "explicit load-all", no ranking)

Discriminator: the `PROJ-` rule_id prefix. NOT `authority` — bible rules also
import as authority=human (writ/graph/ingest.py:154), so authority cannot
separate project rules from the universal corpus.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
from datetime import date
from pathlib import Path

from writ.config import (
    get_falkordb_graph,
    get_falkordb_module,
    get_falkordb_path,
    get_redis_bin,
)
from writ.export import _build_file_content, group_rules_by_file, write_export_timestamp
from writ.gate import structural_gate
from writ.graph.db import FalkorDBLiteConnection
from writ.retrieval.pipeline import build_pipeline

PROJECT_PREFIX = "PROJ-"
DEFAULT_RULES_DIR = "docs/rules"

# Rule fields the author path requires (Rule schema non-empty fields).
REQUIRED_FIELDS = (
    "rule_id",
    "domain",
    "severity",
    "scope",
    "trigger",
    "statement",
    "violation",
    "pass_example",
    "enforcement",
    "rationale",
)


def _connect() -> FalkorDBLiteConnection:
    return FalkorDBLiteConnection(
        get_falkordb_path(),
        get_falkordb_graph(),
        get_falkordb_module(),
        get_redis_bin(),
    )


def _is_project_rule(rule: dict) -> bool:
    return str(rule.get("rule_id", "")).startswith(PROJECT_PREFIX)


# --------------------------------------------------------------------------- #
# export
# --------------------------------------------------------------------------- #
async def _export(db: FalkorDBLiteConnection, output_dir: Path) -> dict:
    """Export ONLY PROJ- rules to output_dir (grouped by domain -> file)."""
    all_rules = await db.get_all_rules()
    rules = [r for r in all_rules if _is_project_rule(r)]
    if not rules:
        # No project rules -> do NOT create docs/rules/ at all. Repos without
        # project constraints (e.g. the plugin repo itself) stay clean; nothing
        # to track until something is authored.
        return {"files_written": 0, "rules_exported": 0}
    output_dir.mkdir(parents=True, exist_ok=True)

    file_groups = group_rules_by_file(rules, output_dir)
    files_written = 0
    rules_exported = 0
    for rel_path, grouped in sorted(file_groups.items()):
        target = output_dir / rel_path
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(_build_file_content(grouped), encoding="utf-8")
        files_written += 1
        rules_exported += len(grouped)
    write_export_timestamp(output_dir)
    return {"files_written": files_written, "rules_exported": rules_exported}


# --------------------------------------------------------------------------- #
# list (explicit load-all, no ranking)
# --------------------------------------------------------------------------- #
async def _list(db: FalkorDBLiteConnection, as_json: bool) -> list[dict]:
    all_rules = await db.get_all_rules()
    return sorted(
        (r for r in all_rules if _is_project_rule(r)),
        key=lambda r: r.get("rule_id", ""),
    )


# --------------------------------------------------------------------------- #
# author
# --------------------------------------------------------------------------- #
async def _author(
    db: FalkorDBLiteConnection,
    candidate: dict,
    output_dir: Path,
    force: bool,
) -> dict:
    """Gate-check a constraint, ingest as authority=human, export docs/rules/."""
    # Provenance + ceilings: a human-decided project law.
    candidate["authority"] = "human"
    candidate.setdefault("confidence", "production-validated")
    candidate.setdefault("last_validated", date.today().isoformat())

    pipeline = await build_pipeline(db)
    gate = structural_gate(candidate, pipeline)

    if not gate.accepted and not force:
        return {
            "accepted": False,
            "rule_id": candidate.get("rule_id", ""),
            "reasons": gate.reasons,
            "similar_rules": gate.similar_rules,
        }

    clean = {k: v for k, v in candidate.items() if not k.startswith("_")}
    await db.create_rule(clean)

    export_result = await _export(db, output_dir)
    return {
        "accepted": True,
        "rule_id": candidate["rule_id"],
        "authority": "human",
        "forced": bool(force and not gate.accepted),
        "gate_reasons": gate.reasons,  # surfaced even when forced
        "export": export_result,
    }


# --------------------------------------------------------------------------- #
# CLI
# --------------------------------------------------------------------------- #
def _build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description="Project-rule authoring engine (PROJ- constraints).")
    p.add_argument(
        "--rules-dir",
        default=DEFAULT_RULES_DIR,
        help=f"Per-repo export dir (default: {DEFAULT_RULES_DIR}).",
    )
    sub = p.add_subparsers(dest="cmd", required=True)

    a = sub.add_parser("author", help="Gate-check + ingest one constraint, then export.")
    for f in REQUIRED_FIELDS:
        a.add_argument(f"--{f.replace('_', '-')}", required=True)
    a.add_argument("--source-attribution", default=None, help="e.g. ADR-0007 for a rule extracted from an ADR.")
    a.add_argument("--force", action="store_true", help="Ingest even if the gate rejects (records reasons).")

    sub.add_parser("export", help="Write all PROJ- rules to the export dir.")

    lst = sub.add_parser("list", help="Print all PROJ- constraints verbatim.")
    lst.add_argument("--json", action="store_true", help="Emit JSON instead of human text.")

    return p


def _candidate_from_args(args: argparse.Namespace) -> dict:
    c = {f: getattr(args, f) for f in REQUIRED_FIELDS}
    if not c["rule_id"].startswith(PROJECT_PREFIX):
        raise SystemExit(f"rule_id must start with '{PROJECT_PREFIX}' (got '{c['rule_id']}').")
    if args.source_attribution:
        c["source_attribution"] = args.source_attribution
    return c


def _print_constraints(rules: list[dict]) -> None:
    if not rules:
        print("(no project constraints authored in this repo)")
        return
    for r in rules:
        print(f"### {r.get('rule_id')} · [{r.get('severity', '?')}] {r.get('domain', '')}")
        print(f"**When:** {r.get('trigger', '')}")
        print(f"**Rule:** {r.get('statement', '')}")
        print(f"**Why:** {r.get('rationale', '')}")
        src = r.get("source_attribution")
        if src:
            print(f"**Source:** {src}")
        print()


def main(argv: list[str] | None = None) -> int:
    args = _build_parser().parse_args(argv)
    rules_dir = Path(args.rules_dir)

    async def _run() -> int:
        db = _connect()
        try:
            if args.cmd == "author":
                candidate = _candidate_from_args(args)
                result = await _author(db, candidate, rules_dir, args.force)
                print(json.dumps(result, indent=2))
                return 0 if result["accepted"] else 1
            if args.cmd == "export":
                result = await _export(db, rules_dir)
                print(json.dumps(result, indent=2))
                return 0
            if args.cmd == "list":
                rules = await _list(db, args.json)
                if args.json:
                    print(json.dumps(rules, indent=2, default=str))
                else:
                    _print_constraints(rules)
                return 0
            return 2
        finally:
            await db.close()

    return asyncio.run(_run())


if __name__ == "__main__":
    sys.exit(main())
