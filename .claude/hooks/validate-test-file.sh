#!/usr/bin/env bash
# Phase 2: Gate 5 Tier 1 test-file assertion gate (ENF-PROC-TDD-001).
#
# PreToolUse on Write matching src/**/*.{py,js,ts,php,go,rs,java}.
# Denies if no corresponding test file exists with lexical assertion markers.
# Bypass: session.mode == "prototype" (reserved for throwaway work).
# Feature-flag gated.
set -euo pipefail
HOOK_DIR="$(cd "$(dirname "$0")" && pwd)"
WRIT_DIR="$(cd "$HOOK_DIR/../.." && pwd)"
SESSION_HELPER="$WRIT_DIR/bin/lib/writ-session.py"
source "$WRIT_DIR/bin/lib/common.sh"

PARSED=$(parse_hook_stdin)
SESSION_ID=$(detect_session_id "$PARSED")
[ -z "$SESSION_ID" ] && exit 0
is_work_mode "$SESSION_ID" || exit 0

# Prototype mode bypass (Section 0.4 decision 2, manual trigger only).
MODE=$(python3 "$SESSION_HELPER" mode get "$SESSION_ID" 2>/dev/null | tr -d '[:space:]')
[ "$MODE" = "prototype" ] && exit 0

FILE=$(parsed_field "$PARSED" "file_path")
[ -z "$FILE" ] && exit 0

DENY=$(python3 - "$FILE" <<'PY'
import os, re, sys
f = sys.argv[1]
ext = os.path.splitext(f)[1].lstrip(".")
# Only apply to source files.
if ext not in {"py", "js", "ts", "php", "go", "rs", "java"}:
    sys.exit(0)
# Compute a repo-relative path so the regex below doesn't false-positive
# on absolute paths whose parent directories happen to be named src/lib/app/writ
# (e.g. the Writ skill itself lives under .../skills/writ/, which previously
# caused this gate to misfire on tests/ writes).
repo = os.getcwd()
try:
    rel = os.path.relpath(f, repo)
except ValueError:
    rel = f
# Test files are never production code -- exempt them up front so files under
# tests/ never trip the "production code without a failing test" gate.
norm = rel.replace(os.sep, "/")
if norm.startswith("tests/") or "/tests/" in norm or norm.startswith("test/") or "/test/" in norm:
    sys.exit(0)
# Only apply to files under src/, lib/, app/, or writ/ at the repo root or
# immediately under a recognized package directory. Anchor the regex to the
# repo-relative path so /writ/ as an ancestor of the repo does not match.
if not re.match(r"^(src|lib|app|writ)/", norm):
    sys.exit(0)

base = os.path.basename(f)
stem = os.path.splitext(base)[0]
parts = norm.split("/")
subdir = "/".join(parts[1:-1])  # path between the top pkg dir and the file
marker_re = re.compile(r"\b(assert|expect|should|test_|it\(|describe\()\w*")

# --- B13: candidate test paths ---------------------------------------------
# Backward-compatible basename candidates PLUS directory-qualified mirrors so
# `lib/a/index.ts` and `lib/b/index.ts` map to DISTINCT test files (no more
# `tests/index.test.ts` collision). `sub` injects the mirrored subdir.
def _with_sub(rel_dir, *names):
    out = []
    for n in names:
        out.append(f"tests/{n}")
        if rel_dir:
            out.append(f"tests/{rel_dir}/{n}")
    return out

candidates = []
if ext == "py":
    candidates += _with_sub(subdir, f"test_{stem}.py", f"test_{stem}s.py")
elif ext in {"js", "ts"}:
    candidates += _with_sub(subdir, f"{stem}.test.{ext}", f"{stem}.spec.{ext}")
elif ext == "php":
    candidates += _with_sub(subdir, f"Unit/{stem}Test.php", f"{stem}Test.php")
elif ext == "go":
    candidates += [f.replace(".go", "_test.go")]  # Go tests are colocated
elif ext == "rs":
    candidates += _with_sub(subdir, f"{stem}.rs")
elif ext == "java":
    candidates += [f"src/test/java/{stem}Test.java"]

# PASS A -- a mapped test file exists and carries assertion markers.
for c in candidates:
    path = os.path.join(repo, c)
    if os.path.isfile(path):
        try:
            with open(path) as fh:
                if marker_re.search(fh.read()):
                    sys.exit(0)
        except OSError:
            pass

# PASS B (B13) -- intent-named test: ANY tests/ file that (a) has assertion
# markers AND (b) imports/references THIS impl. Lets a test be named for the
# behavior it covers instead of mirroring the impl filename. Kept strict (an
# import/require line that names the impl path or a distinctive stem) so a
# bare mention elsewhere does not false-accept.
no_ext = os.path.splitext(norm)[0]            # e.g. lib/storage/index
seg2 = "/".join(no_ext.split("/")[-2:])       # e.g. storage/index
GENERIC = {"index", "main", "mod", "init", "app", "lib", "__init__", "types"}
ref_pats = [re.escape(no_ext).replace("/", r"[/.]"),
            re.escape(seg2).replace("/", r"[/.]")]
if stem.lower() not in GENERIC and len(stem) >= 3:
    ref_pats.append(r"\b" + re.escape(stem) + r"\b")
ref_re = re.compile("|".join(ref_pats))
import_re = re.compile(r"^\s*(import|from|export|const|let|var|require|use|include|require_once|@import)\b|require\(")

def _references_impl(text):
    if not marker_re.search(text):
        return False
    for line in text.splitlines():
        if import_re.search(line) and ref_re.search(line):
            return True
    return False

SKIP_DIRS = {".git", "node_modules", "vendor", ".venv", "__pycache__", "dist", "build"}
found = False
for tdir in ("tests", "test", "__tests__", "spec"):
    root_dir = os.path.join(repo, tdir)
    if not os.path.isdir(root_dir):
        continue
    for dpath, dnames, fnames in os.walk(root_dir):
        dnames[:] = [d for d in dnames if d not in SKIP_DIRS]
        for fn in fnames:
            if os.path.splitext(fn)[1].lstrip(".") not in {"py", "js", "ts", "php", "go", "rs", "java"}:
                continue
            try:
                with open(os.path.join(dpath, fn)) as fh:
                    if _references_impl(fh.read()):
                        found = True
                        break
            except OSError:
                pass
        if found:
            break
    if found:
        break
if found:
    sys.exit(0)

# No mapped test and no intent-named test references this impl.
print(f"ENF-PROC-TDD-001: writing '{os.path.relpath(f, repo)}' requires a test with assertions. Either create a mapped test (one of: {', '.join(candidates)}) OR an intent-named test under tests/ that imports this module and asserts. Bypass: set session.mode=prototype for throwaway work.")
PY
)

if [ -n "$DENY" ]; then
    python3 -c "
import json
print(json.dumps({
    'hookSpecificOutput': {
        'hookEventName': 'PreToolUse',
        'permissionDecision': 'deny',
        'permissionDecisionReason': '''$DENY'''
    }
}))"
fi
exit 0
