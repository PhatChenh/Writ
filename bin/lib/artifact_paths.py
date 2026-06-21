#!/usr/bin/env python3
"""Project-agnostic build-pipeline artifact classifier.

Owns the knowledge of WHERE each pipeline artifact lands (design / spec /
research / plan / handoff), so the quality/validation hooks
(validate-design-doc, writ-quality-judge, validate-handoff) do not hardcode a
single path convention. Mirrors the test_paths.py config pattern.

Configuration precedence:
  1. <cwd>/.claude/writ.json  (project-local, key "artifacts")
  2. <skill>/bin/lib/artifact-paths-defaults.json  (bundled)

If the project file has `extends_defaults: true` (default), project artifact
globs override defaults of the same type and any remaining defaults survive.
If `extends_defaults: false`, defaults are dropped entirely.

CLI:
  classify <file>   -> artifact type (design|spec|research|plan|handoff), or empty
  globs <type>      -> the resolved globs for one type, one per line

Always exits 0; bash callers treat empty stdout as no-match.
"""
from __future__ import annotations

import argparse
import fnmatch
import json
import os
import sys
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
DEFAULTS_PATH = SCRIPT_DIR / "artifact-paths-defaults.json"

last_load_error: str | None = None


def _read_json(path: Path) -> dict:
    with path.open() as f:
        return json.load(f)


def load_config(cwd: Path | str | None = None) -> dict:
    """Merge bundled defaults with optional <cwd>/.claude/writ.json `artifacts`."""
    global last_load_error
    last_load_error = None

    defaults = _read_json(DEFAULTS_PATH).get("artifacts", {})
    if cwd is None:
        return defaults
    project_path = Path(cwd) / ".claude" / "writ.json"
    if not project_path.is_file():
        return defaults

    try:
        project = _read_json(project_path)
    except (json.JSONDecodeError, ValueError) as exc:
        last_load_error = f"{project_path}: {exc}"
        return defaults

    project_arts = project.get("artifacts", {}) or {}
    if not project_arts:
        return defaults
    if not project.get("extends_defaults", True):
        return project_arts
    merged = dict(defaults)
    merged.update(project_arts)  # project overrides per-type
    return merged


def _matches(file_path: str, globs: list[str]) -> bool:
    """Match against the repo-relative path and the bare absolute path.

    Hooks pass an absolute file_path; globs are repo-relative. Trying both the
    cwd-relative form and a `*/`-prefixed glob keeps matching robust whether or
    not the daemon CWD equals the repo root.
    """
    rel = file_path
    try:
        rel = os.path.relpath(file_path, os.getcwd())
    except ValueError:
        pass
    rel = rel.replace(os.sep, "/")
    for g in globs:
        if fnmatch.fnmatch(rel, g) or fnmatch.fnmatch(file_path, "*/" + g):
            return True
    return False


def classify(file_path: str, config: dict) -> str:
    for art_type, globs in config.items():
        if _matches(file_path, globs or []):
            return art_type
    return ""


def main() -> int:
    parser = argparse.ArgumentParser()
    sub = parser.add_subparsers(dest="cmd", required=True)
    p_classify = sub.add_parser("classify")
    p_classify.add_argument("file")
    p_globs = sub.add_parser("globs")
    p_globs.add_argument("type")
    args = parser.parse_args()

    config = load_config(os.getcwd())
    if args.cmd == "classify":
        print(classify(args.file, config))
    elif args.cmd == "globs":
        for g in config.get(args.type, []) or []:
            print(g)
    return 0


if __name__ == "__main__":
    sys.exit(main())
