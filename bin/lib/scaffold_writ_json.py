#!/usr/bin/env python3
"""Scaffold a per-repo .claude/writ.json when the layout isn't a built-in default.

Called by the SessionStart hook (writ-scaffold-config.sh). Conservative by
design: writes a config ONLY when it is confident, and never overwrites an
existing file. The bundled test-path defaults already cover the common `src/`
layout, so the one case worth scaffolding is a flat Python package (the
package dir lives at the repo root, e.g. `writ/`, not under `src/`).

Behaviour:
  - .claude/writ.json already exists           -> no-op (exit 0)
  - exactly one obvious top-level Python package
    dir (has __init__.py) AND it is not `src`  -> write a writ.json for it
  - anything ambiguous (0 or >1 packages, src
    layout, non-Python)                        -> no-op (defaults suffice, or
                                                  the user configures manually)

Usage: scaffold_writ_json.py <repo_root>
Always exits 0.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

_IGNORE = {
    "tests", "test", "docs", "doc", "scripts", "script", "examples",
    "venv", ".venv", "build", "dist", "node_modules", "vendor",
    ".git", ".claude", ".github", "__pycache__", "bin",
}


def find_flat_package(repo: Path) -> str | None:
    """Return the single top-level Python package dir name, or None if unsure."""
    pkgs = [
        p.name
        for p in repo.iterdir()
        if p.is_dir()
        and not p.name.startswith(".")
        and p.name not in _IGNORE
        and (p / "__init__.py").is_file()
    ]
    if len(pkgs) == 1:
        return pkgs[0]
    return None


def build_config(pkg: str) -> dict:
    return {
        "extends_defaults": True,
        "patterns": [
            {
                "name": f"{pkg}-python",
                "src_match": [f"*/{pkg}/*.py", f"{pkg}/*.py"],
                "test_match": ["*/tests/test_*.py", "tests/test_*.py"],
                "src_to_test_regex": rf"^.*/{pkg}/(?:.*/)?([^/]+)\.py$",
                "src_to_test_replace": "tests/test_{1}.py",
                "runner_command": "python -m pytest",
                "runner_config_file": "pyproject.toml",
            }
        ],
    }


def main(argv: list[str]) -> int:
    if not argv:
        return 0
    repo = Path(argv[0])
    if not repo.is_dir():
        return 0
    target = repo / ".claude" / "writ.json"
    if target.exists():
        return 0  # never overwrite; committed config travels with the repo

    # Only Python flat-package layout is auto-scaffolded today.
    if not (repo / "pyproject.toml").is_file() and not (repo / "setup.py").is_file():
        return 0
    pkg = find_flat_package(repo)
    if not pkg or pkg == "src":
        return 0  # src/ is a default; ambiguous -> leave to the user

    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(build_config(pkg), indent=2) + "\n")
    print(f"[Writ] scaffolded {target} for flat package '{pkg}/'", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
