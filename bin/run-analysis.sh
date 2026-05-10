#!/bin/bash
# Standalone static analysis runner.
# Replaces shell-hook analysis and static-analysis agent bash commands.
# Returns structured JSON array of findings.
#
# Usage:
#   bin/run-analysis.sh <file> [file2 ...]
#   bin/run-analysis.sh --project-root /path/to/project <file> [file2 ...]
#
# Output: JSON array of { file, line, severity, rule, tool, message }
# Exit code: 0 = all clean, 1 = errors found, 2 = tool not available

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
source "$SCRIPT_DIR/lib/common.sh"

# ── Argument parsing ─────────────────────────────────────────────────────────
PROJECT_ROOT=""
FILES=()

while [[ $# -gt 0 ]]; do
  case "$1" in
    --project-root) PROJECT_ROOT="$2"; shift 2 ;;
    *) FILES+=("$1"); shift ;;
  esac
done

if [ ${#FILES[@]} -eq 0 ]; then
  echo '{"error": "No files specified. Usage: run-analysis.sh [--project-root DIR] file1 [file2 ...]"}'
  exit 2
fi

# Auto-detect project root from first file if not specified
if [ -z "$PROJECT_ROOT" ]; then
  PROJECT_ROOT=$(detect_project_root "${FILES[0]}")
fi

# ── Per-language analysis functions ──────────────────────────────────────────

analyze_php() {
  local file="$1" findings=""
  local level=$(read_project_config "$PROJECT_ROOT" ".claude/phpstan-level" "8")
  local standard=$(read_project_config "$PROJECT_ROOT" ".claude/phpcs-standard" "PSR12")

  # PHPStan
  local phpstan=$(find_tool "$PROJECT_ROOT" "vendor/bin/phpstan" "phpstan")
  if [ -n "$phpstan" ]; then
    local output
    local exit_code
    output=$("$phpstan" analyse "$file" --level="$level" --no-progress --error-format=json 2>/dev/null) && exit_code=0 || exit_code=$?

    # Parse JSON output if available, fall back to raw
    local parsed
    parsed=$(python3 -c "
import json, sys
try:
    data = json.loads('''$output''')
    for f_data in data.get('files', {}).values():
        for msg in f_data.get('messages', []):
            print(json.dumps({
                'file': '$file',
                'line': msg.get('line', 0),
                'severity': 'error',
                'rule': 'ENF-POST-007',
                'tool': 'phpstan-level-$level',
                'message': msg.get('message', '')
            }))
except (json.JSONDecodeError, Exception):
    pass
" 2>/dev/null)

    if [ -z "$parsed" ] && [ $exit_code -ne 0 ]; then
      # Fallback: raw output parsing
      local raw_exit
      output=$("$phpstan" analyse "$file" --level="$level" --no-progress 2>&1) && raw_exit=0 || raw_exit=$?
      if [ $raw_exit -ne 0 ] || echo "$output" | grep -q "errors"; then
        parsed=$(python3 -c "
import json, sys, re
output = sys.argv[1]
for match in re.finditer(r'Line\s+(\d+)\s*\n\s*(.*?)(?=\n\s*(?:Line|\d+ error|$))', output, re.DOTALL):
    line_num = int(match.group(1))
    msg = match.group(2).strip()
    print(json.dumps({
        'file': '$file',
        'line': line_num,
        'severity': 'error',
        'rule': 'ENF-POST-007',
        'tool': 'phpstan-level-$level',
        'message': msg
    }))
" "$output" 2>/dev/null)
      fi
    fi
    [ -n "$parsed" ] && findings="${findings}${parsed}"$'\n'
  else
    findings="${findings}$(python3 -c "
import json
print(json.dumps({
    'file': '$file', 'line': 0, 'severity': 'warning',
    'rule': 'ENF-POST-007', 'tool': 'phpstan',
    'message': 'PHPStan not found. Install: composer require --dev phpstan/phpstan'
}))" 2>/dev/null)"$'\n'
  fi

  # PHPCS
  local phpcs=$(find_tool "$PROJECT_ROOT" "vendor/bin/phpcs" "phpcs")
  if [ -n "$phpcs" ]; then
    local output
    output=$("$phpcs" "$file" --standard="$standard" --report=json 2>/dev/null) || true

    local parsed
    parsed=$(python3 -c "
import json, sys
try:
    data = json.loads('''$output''')
    for path, f_data in data.get('files', {}).items():
        for msg in f_data.get('messages', []):
            print(json.dumps({
                'file': '$file',
                'line': msg.get('line', 0),
                'severity': msg.get('type', 'error').lower(),
                'rule': 'ENF-POST-007',
                'tool': 'phpcs-$standard',
                'message': msg.get('message', '')
            }))
except (json.JSONDecodeError, Exception):
    pass
" 2>/dev/null)
    [ -n "$parsed" ] && findings="${findings}${parsed}"$'\n'
  fi

  echo -n "$findings"
}

analyze_xml() {
  local file="$1"
  if command -v xmllint &>/dev/null; then
    local output exit_code
    output=$(xmllint --noout "$file" 2>&1) && exit_code=0 || exit_code=$?
    if [ $exit_code -ne 0 ]; then
      python3 -c "
import json, sys, re
output = sys.argv[1]
for match in re.finditer(r':(\d+):\s*(.*)', output):
    print(json.dumps({
        'file': '$file',
        'line': int(match.group(1)),
        'severity': 'error',
        'rule': 'ENF-POST-007',
        'tool': 'xmllint',
        'message': match.group(2).strip()
    }))
" "$output" 2>/dev/null
    fi
  else
    python3 -c "
import json
print(json.dumps({
    'file': '$file', 'line': 0, 'severity': 'warning',
    'rule': 'ENF-POST-007', 'tool': 'xmllint',
    'message': 'xmllint not found. Install: sudo apt install libxml2-utils'
}))" 2>/dev/null
  fi
}

analyze_js_ts() {
  local file="$1"
  local eslint=$(find_tool "$PROJECT_ROOT" "node_modules/.bin/eslint" "eslint")
  if [ -n "$eslint" ]; then
    local output
    output=$("$eslint" "$file" --format=json 2>/dev/null) || true

    python3 -c "
import json, sys
try:
    data = json.loads('''$output''')
    for result in data:
        for msg in result.get('messages', []):
            sev = 'error' if msg.get('severity', 0) == 2 else 'warning'
            rule_id = msg.get('ruleId', 'unknown')
            print(json.dumps({
                'file': '$file',
                'line': msg.get('line', 0),
                'severity': sev,
                'rule': 'ENF-POST-007',
                'tool': f'eslint/{rule_id}',
                'message': msg.get('message', '')
            }))
except (json.JSONDecodeError, Exception):
    pass
" 2>/dev/null
  else
    python3 -c "
import json
print(json.dumps({
    'file': '$file', 'line': 0, 'severity': 'warning',
    'rule': 'ENF-POST-007', 'tool': 'eslint',
    'message': 'ESLint not found. Install: npm install --save-dev eslint'
}))" 2>/dev/null
  fi
}

analyze_python() {
  local file="$1"
  if command -v ruff &>/dev/null; then
    local output
    output=$(ruff check "$file" --output-format=json 2>/dev/null) || true

    python3 -c "
import json, sys
try:
    data = json.loads('''$output''')
    for item in data:
        print(json.dumps({
            'file': '$file',
            'line': item.get('location', {}).get('row', 0),
            'severity': 'error',
            'rule': 'ENF-POST-007',
            'tool': 'ruff/' + item.get('code', 'unknown'),
            'message': item.get('message', '')
        }))
except (json.JSONDecodeError, Exception):
    pass
" 2>/dev/null
  elif command -v flake8 &>/dev/null; then
    local output
    output=$(flake8 "$file" --format='%(path)s:%(row)d:%(col)d: %(code)s %(text)s' 2>&1) || true
    python3 -c "
import json, sys, re
output = sys.argv[1]
for match in re.finditer(r':(\d+):\d+:\s+(\S+)\s+(.*)', output):
    print(json.dumps({
        'file': '$file',
        'line': int(match.group(1)),
        'severity': 'error',
        'rule': 'ENF-POST-007',
        'tool': 'flake8/' + match.group(2),
        'message': match.group(3).strip()
    }))
" "$output" 2>/dev/null
  else
    python3 -c "
import json
print(json.dumps({
    'file': '$file', 'line': 0, 'severity': 'warning',
    'rule': 'ENF-POST-007', 'tool': 'python-lint',
    'message': 'No Python linter found. Install: pip install ruff'
}))" 2>/dev/null
  fi
}

analyze_rust() {
  local file="$1"
  if command -v cargo &>/dev/null && [ -n "$PROJECT_ROOT" ]; then
    local output
    output=$(cd "$PROJECT_ROOT" && cargo check --message-format=json 2>/dev/null) || true

    python3 -c "
import json, sys
for line in '''$output'''.strip().split('\n'):
    if not line.strip():
        continue
    try:
        data = json.loads(line)
        if data.get('reason') == 'compiler-message':
            msg = data.get('message', {})
            spans = msg.get('spans', [])
            line_num = spans[0].get('line_start', 0) if spans else 0
            fname = spans[0].get('file_name', '$file') if spans else '$file'
            print(json.dumps({
                'file': fname,
                'line': line_num,
                'severity': msg.get('level', 'error'),
                'rule': 'ENF-POST-007',
                'tool': 'cargo-check',
                'message': msg.get('message', '')
            }))
    except (json.JSONDecodeError, Exception):
        pass
" 2>/dev/null
  fi
}

analyze_go() {
  local file="$1"
  if command -v go &>/dev/null; then
    local output
    output=$(go vet "$file" 2>&1) || true
    if [ -n "$output" ]; then
      python3 -c "
import json, sys, re
output = sys.argv[1]
for match in re.finditer(r':(\d+)(?::\d+)?:\s*(.*)', output):
    print(json.dumps({
        'file': '$file',
        'line': int(match.group(1)),
        'severity': 'error',
        'rule': 'ENF-POST-007',
        'tool': 'go-vet',
        'message': match.group(2).strip()
    }))
" "$output" 2>/dev/null
    fi
  fi
}

analyze_graphql() {
  local file="$1"
  if [ -z "$PROJECT_ROOT" ]; then return; fi

  python3 -c "
import json, re, os, glob as g

with open('$file') as f:
    content = f.read()

findings = []
for match in re.finditer(r'(?:class|cacheIdentity):\s*\"([^\"]+)\"', content):
    classname = match.group(1)
    classpath = classname.replace('\\\\', '/').replace('\\\\', '/')
    basename = os.path.basename(classpath) + '.php'
    dirpart = os.path.dirname(classpath)

    found = False
    for root, dirs, files in os.walk('$PROJECT_ROOT'):
        if basename in files and (not dirpart or dirpart in root.replace(os.sep, '/')):
            found = True
            break

    if not found:
        findings.append({
            'file': '$file',
            'line': content[:match.start()].count('\n') + 1,
            'severity': 'error',
            'rule': 'ENF-GATE-FINAL',
            'tool': 'graphql-class-ref',
            'message': f'Class \"{classname}\" not found on disk (expected: {classpath}.php)'
        })

for f in findings:
    print(json.dumps(f))
" 2>/dev/null
}

# ── Security injection scan (cross-language, SEC-INJ-* rules) ────────────────
# Phase 1A 2026-05-10. Regex-based detector for the 6 mandatory SEC-INJ-*
# rules plus the high-severity siblings (XSS-003, CMD-002, PATH-001, LDAP-001,
# SSTI-001, HEADER-001, LOG-001, REDIR-001). Cannot fully prove safety;
# flags the patterns that should never appear without a reviewer-confirmed
# justification.
analyze_security_injection() {
  local file="$1"
  local lang="$2"

  python3 - <<PYEOF "$file" "$lang"
import json, re, sys
file_path = sys.argv[1]
lang = sys.argv[2]
try:
    with open(file_path, encoding="utf-8", errors="replace") as f:
        src = f.read()
except OSError:
    sys.exit(0)

lines = src.splitlines()

def emit(line_no, rule, tool, message, severity="error"):
    print(json.dumps({
        "file": file_path,
        "line": line_no,
        "severity": severity,
        "rule": rule,
        "tool": "writ-injection-scan/" + tool,
        "message": message,
    }))

PATTERNS = [
    # SEC-INJ-SQL-001: SQL string concatenation / interpolation near execute()
    (r"\.execute\s*\(\s*f[\"']", "SEC-INJ-SQL-001", "sql-fstring",
     "f-string SQL in .execute(): use bound parameters instead", "error"),
    (r"\.execute\s*\([^)]*\+\s*['\"]?\s*\w", "SEC-INJ-SQL-001", "sql-concat",
     "string concatenation in .execute(): use bound parameters instead", "error"),
    (r"\.raw\s*\(\s*f[\"']", "SEC-INJ-SQL-002", "orm-raw-fstring",
     "f-string in ORM .raw(): pass parameters as a list/dict", "error"),
    # SEC-INJ-XSS-001/002: dangerous render APIs
    (r"dangerouslySetInnerHTML", "SEC-INJ-XSS-002", "react-unsafe-html",
     "dangerouslySetInnerHTML: render as text or sanitize via DOMPurify", "error"),
    (r"\bv-html\s*=", "SEC-INJ-XSS-002", "vue-unsafe-html",
     "v-html: render as text or sanitize", "error"),
    (r"\{!![^!]+!!\}", "SEC-INJ-XSS-002", "blade-unsafe",
     "Blade {!! !!} raw output: use {{ }} or sanitize", "error"),
    (r"\{@html\b", "SEC-INJ-XSS-002", "svelte-unsafe-html",
     "Svelte {@html}: sanitize before rendering", "error"),
    # SEC-INJ-XSS-003: vanilla DOM mutation with HTML
    (r"\.innerHTML\s*=", "SEC-INJ-XSS-003", "dom-innerhtml",
     "innerHTML assignment: use textContent or framework-rendered nodes", "error"),
    (r"\.outerHTML\s*=", "SEC-INJ-XSS-003", "dom-outerhtml",
     "outerHTML assignment: replace via createElement instead", "error"),
    (r"document\.write\s*\(", "SEC-INJ-XSS-003", "document-write",
     "document.write(): use DOM API instead", "error"),
    # SEC-INJ-CMD-001: shell command construction
    (r"subprocess\.(run|Popen|call|check_output|check_call)\s*\([^)]*shell\s*=\s*True", "SEC-INJ-CMD-001", "subprocess-shell",
     "subprocess with shell=True: pass argument list instead", "error"),
    (r"\bos\.system\s*\(", "SEC-INJ-CMD-001", "os-system",
     "os.system(): use subprocess with argument list", "error"),
    (r"\bos\.popen\s*\(", "SEC-INJ-CMD-001", "os-popen",
     "os.popen(): use subprocess.run with argument list", "error"),
    (r"child_process\.exec(?:Sync)?\s*\(", "SEC-INJ-CMD-001", "node-exec",
     "child_process.exec(): use execFile or spawn with argument list", "error"),
    # PHP shell exec functions
    (r"\bshell_exec\s*\(", "SEC-INJ-CMD-001", "php-shell-exec",
     "shell_exec(): use escapeshellarg or argument-list invocation", "error"),
    (r"\bpassthru\s*\(", "SEC-INJ-CMD-001", "php-passthru",
     "passthru(): pass constant command, escape arguments", "error"),
    # SEC-INJ-CMD-002: eval / dynamic-code evaluators
    (r"\beval\s*\(", "SEC-INJ-CMD-002", "eval",
     "eval(): use a lookup table or dispatch dict instead", "error"),
    (r"new\s+Function\s*\(", "SEC-INJ-CMD-002", "new-function",
     "new Function(): replace with a lookup table or registry", "error"),
    # SEC-INJ-DESER-001: insecure deserialization
    (r"\bpickle\.loads?\s*\(", "SEC-INJ-DESER-001", "pickle",
     "pickle.loads(): never deserialize untrusted data; use JSON or typed schema", "error"),
    (r"\byaml\.load\s*\((?![^)]*Loader\s*=\s*\w*SafeLoader)", "SEC-INJ-DESER-001", "yaml-unsafe",
     "yaml.load() without SafeLoader: use yaml.safe_load() instead", "error"),
    (r"\bunserialize\s*\(", "SEC-INJ-DESER-001", "php-unserialize",
     "PHP unserialize(): use json_decode or typed schema", "error"),
    (r"ObjectInputStream", "SEC-INJ-DESER-001", "java-objectinputstream",
     "Java ObjectInputStream: use a typed schema (JSON/Protobuf)", "error"),
    # SEC-INJ-SSTI-001: server-side template injection
    (r"\bTemplate\s*\(\s*(?!['\"])", "SEC-INJ-SSTI-001", "template-dynamic",
     "Template() with non-literal argument: never pass user input as template body", "error"),
    # SEC-INJ-LOG-001: log injection
    # (advisory severity in the source; flagged but not error)
    (r"(logger|logging)\.[a-z]+\s*\(\s*f[\"'][^\"']*\{[a-zA-Z_]", "SEC-INJ-LOG-001", "log-fstring",
     "f-string log with embedded values: use structured logger fields", "warning"),
]

for line_no, line in enumerate(lines, start=1):
    # Skip lines that look like comments to reduce false positives on
    # documentation examples within the rules themselves. Comment markers:
    # Python #, JS/Java/PHP //, /* ... */ ranges are not tracked here.
    stripped = line.lstrip()
    if stripped.startswith(("#", "//", "*")):
        continue
    for pat, rule, tool, msg, severity in PATTERNS:
        if re.search(pat, line):
            emit(line_no, rule, tool, msg, severity)
PYEOF
}

# ── Main loop ────────────────────────────────────────────────────────────────
ALL_FINDINGS=""
HAS_ERRORS=0

for file in "${FILES[@]}"; do
  if [ ! -f "$file" ]; then
    ALL_FINDINGS="${ALL_FINDINGS}$(python3 -c "
import json
print(json.dumps({
    'file': '$file', 'line': 0, 'severity': 'error',
    'rule': 'ENF-POST-007', 'tool': 'filesystem',
    'message': 'File does not exist'
}))" 2>/dev/null)"$'\n'
    HAS_ERRORS=1
    continue
  fi

  lang=$(detect_language "$file")
  case "$lang" in
    php)        result=$(analyze_php "$file") ;;
    xml)        result=$(analyze_xml "$file") ;;
    javascript|typescript) result=$(analyze_js_ts "$file") ;;
    python)     result=$(analyze_python "$file") ;;
    rust)       result=$(analyze_rust "$file") ;;
    go)         result=$(analyze_go "$file") ;;
    graphql)    result=$(analyze_graphql "$file") ;;
    *)          result="" ;;
  esac

  if [ -n "$result" ]; then
    ALL_FINDINGS="${ALL_FINDINGS}${result}"$'\n'
    # Check if any finding has severity=error
    if echo "$result" | grep -q '"severity": "error"'; then
      HAS_ERRORS=1
    fi
  fi

  # Cross-language injection-prevention scan (SEC-INJ-* rules from the
  # public rulebook, Phase 1A 2026-05-10). Runs in addition to the
  # per-language analyzer above.
  inj_result=$(analyze_security_injection "$file" "$lang")
  if [ -n "$inj_result" ]; then
    ALL_FINDINGS="${ALL_FINDINGS}${inj_result}"$'\n'
    if echo "$inj_result" | grep -q '"severity": "error"'; then
      HAS_ERRORS=1
    fi
  fi
done

# Output as JSON array
echo "$ALL_FINDINGS" | json_array

exit $HAS_ERRORS
