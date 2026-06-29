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
import json, os, re, sys
file_path = sys.argv[1]
lang = sys.argv[2]
# Seed scripts contain literal example code from the public rulebook as
# documentation (rule.violation / rule.pass_example strings). Skip them.
basename = os.path.basename(file_path)
if basename.startswith("seed_") and basename.endswith(".py"):
    sys.exit(0)
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

# ── Security auth/authz/validation scan (cross-language) ─────────────────────
# Phase 1B 2026-05-10. Regex-based detector for the 8 mandatory rules across
# 1B Authentication, 1C Authorization, 1D Input Validation. Some rules
# (DEFAULT, TENANT, SERVER, IDOR) are structural -- this analyzer flags
# common patterns rather than proving safety; reviewer judgment closes the
# remaining gap.
analyze_security_auth_authz() {
  local file="$1"
  local lang="$2"

  python3 - <<'PYEOF' "$file" "$lang"
import json, os, re, sys
file_path = sys.argv[1]
lang = sys.argv[2]
basename = os.path.basename(file_path)
if basename.startswith("seed_") and basename.endswith(".py"):
    sys.exit(0)
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
        "tool": "writ-auth-scan/" + tool,
        "message": message,
    }))

# Proximity helper: does the rest of the file mention a marker within
# `window` lines of `line_no` (1-indexed)? Used for password/token context.
def near(line_no, marker_re, window=2):
    lo = max(0, line_no - 1 - window)
    hi = min(len(lines), line_no - 1 + window + 1)
    return any(re.search(marker_re, lines[i]) for i in range(lo, hi))

PASSWORD_CTX = re.compile(r"\b(password|passwd|pwd|passhash)\b", re.IGNORECASE)
TOKEN_CTX = re.compile(
    r"\b(token|session|secret|csrf|nonce|reset|verify|api_?key|sessid|salt|seed)\b",
    re.IGNORECASE,
)

# Direct-match patterns -- no proximity needed.
DIRECT = [
    # SEC-AUTHZ-MASS-001: mass assignment from request body
    (r"\b\w+\s*\(\s*\*\*\s*request\.(?:json|body|POST|data|args)", "SEC-AUTHZ-MASS-001", "mass-assign-py",
     "Mass assignment from request body: validate through a schema or permit/allowlist first", "error"),
    (r"Object\.assign\s*\(\s*\w+\s*,\s*req\.body\b", "SEC-AUTHZ-MASS-001", "mass-assign-node",
     "Object.assign(model, req.body): use an allowlist or schema validator", "error"),
    (r"\.update_attributes\s*\(\s*params\b", "SEC-AUTHZ-MASS-001", "mass-assign-rails",
     "update_attributes(params): use strong parameters (.permit(...))", "error"),
    (r"new\s+\w+\s*\(\s*req\.body\s*\)", "SEC-AUTHZ-MASS-001", "mass-assign-node-ctor",
     "new Model(req.body): validate through a schema first", "error"),
    # SEC-VAL-FILE-001: file upload to web root or without content check
    (r"request\.files\s*\[[^\]]+\]\.save\s*\(", "SEC-VAL-FILE-001", "upload-save-flask",
     "request.files[...].save(): verify by magic bytes + store outside web root + use sanitized filename", "error"),
    (r"\$request\s*->\s*file\s*\([^)]*\)\s*->\s*(?:store|move|save)\s*\(", "SEC-VAL-FILE-001", "upload-save-laravel",
     "$request->file(...)->store/move: verify by magic bytes and use random storage name", "error"),
    (r"multer\s*\(\s*\{[^}]*dest\s*:", "SEC-VAL-FILE-001", "upload-multer",
     "multer({ dest: ... }): also verify mime/magic bytes server-side", "error"),
]

# Context-sensitive patterns -- only flag when accompanying identifier is nearby.
CONTEXT = [
    # SEC-AUTH-HASH-001: weak password hash
    (r"\bhashlib\.(md5|sha1|sha256|sha512)\s*\(", "SEC-AUTH-HASH-001", "weak-hash-py",
     PASSWORD_CTX, 2,
     "Weak hash on password: use bcrypt, argon2, or scrypt", "error"),
    (r"\bcrypto\.createHash\s*\(\s*['\"](md5|sha1|sha256|sha512)['\"]", "SEC-AUTH-HASH-001", "weak-hash-node",
     PASSWORD_CTX, 2,
     "Weak hash on password: use bcrypt, argon2, or scrypt", "error"),
    (r"\b(md5|sha1|hash)\s*\(\s*\$\w*pass", "SEC-AUTH-HASH-001", "weak-hash-php",
     PASSWORD_CTX, 0,
     "Weak hash on password: use password_hash() with PASSWORD_BCRYPT or PASSWORD_ARGON2ID", "error"),
    # SEC-AUTH-TOKEN-001: non-CSPRNG for security-sensitive value
    (r"\bMath\.random\s*\(\s*\)", "SEC-AUTH-TOKEN-001", "weak-rng-node",
     TOKEN_CTX, 2,
     "Math.random() for security-sensitive value: use crypto.randomBytes()", "error"),
    (r"\brandom\.(random|choice|choices|randint|randrange|uniform)\s*\(", "SEC-AUTH-TOKEN-001", "weak-rng-py",
     TOKEN_CTX, 2,
     "random.* for security-sensitive value: use secrets.token_urlsafe() or secrets.token_bytes()", "error"),
    (r"\b(mt_rand|rand|srand)\s*\(", "SEC-AUTH-TOKEN-001", "weak-rng-php",
     TOKEN_CTX, 2,
     "mt_rand/rand for security-sensitive value: use random_bytes() or random_int()", "error"),
]

# Heuristic structural checks (file-level rather than per-line).
# SEC-AUTHZ-ENFORCE-001 / SEC-AUTHZ-DEFAULT-001: route handlers without an
# explicit authorization decorator/dependency.
ROUTE_DECORATOR = re.compile(
    r"@(?:app|router|bp|blueprint)\.(?:route|get|post|put|delete|patch)\s*\("
    r"|@router\.(?:get|post|put|delete|patch)\s*\("
    r"|@app\.(?:get|post|put|delete|patch)\s*\("
)
AUTH_GUARD = re.compile(
    r"@(?:login_required|admin_required|permission_required|authentication_required|authorize|policy)"
    r"|Depends\s*\(\s*(?:get_current_user|get_current_active_user|require_admin|require_auth|require_role|verify_token|oauth2_scheme)"
    r"|permission_classes\s*=\s*\[",
    re.IGNORECASE,
)
# B26: a route may authenticate by a MANUAL call rather than a decorator /
# Depends(...) -- e.g. `principal = await validate_api_key(db, x_api_key)`
# followed by a 401 on missing/invalid (mirrors Iris api/ingest.py /
# api/query.py). The decorator-only check false-flagged these as unauthed and
# HARD-BLOCKED the write (ENF-POST-007). Recognize three manual-auth signals:
#   (1) a call to a known validator inside the handler body, OR
#   (2) a credential header read (X-API-Key / Authorization / token) AND a
#       401 / Unauthorized raise in the same body, OR
#   (3) a per-route `# writ:manual-auth` escape directive on the decorator
#       line or first body line (operator asserts a reviewed manual-auth route
#       the heuristics still miss).
MANUAL_AUTH = re.compile(
    r"\b(?:validate_api_key|verify_api_key|verify_token|verify_credentials|"
    r"authenticate_request|authenticate|check_auth|require_auth|require_admin|"
    r"require_role|get_current_user|current_user|resolve_principal|"
    r"authorize_request|is_authorized)\s*\(",
    re.IGNORECASE,
)
CRED_HEADER = re.compile(
    r"\b(?:X-API-Key|X-Auth-Token|Authorization|api_?key|access_?token|bearer)\b",
    re.IGNORECASE,
)
UNAUTHORIZED = re.compile(
    r"\b401\b|HTTPException\s*\([^)]*401|abort\s*\(\s*401|"
    r"status_code\s*[:=]\s*401|raise\s+(?:Unauthorized|AuthenticationError|"
    r"NotAuthenticated)|return\s+.*\b401\b",
    re.IGNORECASE,
)
# Handler body = stacked decorators + def header + indented body, stopping at
# the next top-level statement. Wider than the old 6-line window so a manual
# auth call deeper in the body is seen.
def _handler_body(lines, i):
    j = i
    while j < len(lines) and lines[j].lstrip().startswith("@"):
        j += 1
    while j < len(lines) and lines[j].strip() == "":
        j += 1
    if j < len(lines) and re.match(r"\s*(async\s+)?def\s", lines[j]):
        j += 1
    while j < len(lines):
        ln = lines[j]
        if ln == "" or ln.startswith((" ", "\t")) or ln.lstrip().startswith(("#", "//")):
            j += 1
            continue
        break
    return "\n".join(lines[i:j])

# B29/unblock: a file-level `# writ:noauth` directive asserts the module is an
# intentionally auth-less service (e.g. the Writ RAG daemon is localhost-only,
# bound to 127.0.0.1 -- B17). When present, skip the missing-auth-decorator
# scan for this file. The other security scans (mass assignment, weak hash,
# weak RNG, body validation) still run -- this waives only the route-decorator
# check, not the rest of the security rules.
_noauth_directive = any("writ:noauth" in _l for _l in lines)
if not _noauth_directive:
    for i, line in enumerate(lines):
        if ROUTE_DECORATOR.search(line):
            body = _handler_body(lines, i)
            if "writ:manual-auth" in body:
                continue
            authed = (
                AUTH_GUARD.search(body)
                or MANUAL_AUTH.search(body)
                or (CRED_HEADER.search(body) and UNAUTHORIZED.search(body))
            )
            if not authed:
                emit(i + 1, "SEC-AUTHZ-ENFORCE-001", "missing-auth-decorator",
                     "Route handler without explicit auth check (login_required / Depends(auth) / permission_classes / manual validate_api_key + 401 / # writ:manual-auth): "
                     "endpoints default to deny per SEC-AUTHZ-DEFAULT-001", "error")

# SEC-VAL-SERVER-001: handler reads request body without an intervening
# schema validation call. Conservative: flag handlers that read
# request.json/body and never call .validate( or a *Schema/*Model constructor.
HANDLER_HEADER = re.compile(r"def\s+\w+\s*\(.*\)\s*:\s*$")
BODY_ACCESS = re.compile(r"request\.(?:json|body|POST|data|args)|req\.body")
SCHEMA_CALL = re.compile(
    r"\.validate\s*\(|"
    r"\b[A-Z]\w+(?:Create|Update|Schema|Model|Payload|Request|Input|Dto)\s*\(|"
    r"BaseModel|pydantic|Marshmallow|joi\.|Joi\.|zod\.|z\.object\b"
)
i = 0
while i < len(lines):
    if HANDLER_HEADER.search(lines[i]):
        body_end = i + 1
        while body_end < len(lines):
            stripped = lines[body_end]
            if stripped and not stripped.startswith((" ", "\t")) and not stripped.startswith(("#", "//")):
                break
            body_end += 1
        body_block = "\n".join(lines[i: body_end])
        if BODY_ACCESS.search(body_block) and not SCHEMA_CALL.search(body_block):
            emit(i + 1, "SEC-VAL-SERVER-001", "unvalidated-body",
                 "Handler reads request body without schema validation: validate through a typed schema "
                 "(Pydantic/Marshmallow/Zod/Joi) before business logic", "warning")
        i = body_end
    else:
        i += 1

# Apply per-line patterns.
for line_no, line in enumerate(lines, start=1):
    stripped = line.lstrip()
    if stripped.startswith(("#", "//", "*")):
        continue
    for pat, rule, tool, msg, severity in DIRECT:
        if re.search(pat, line):
            emit(line_no, rule, tool, msg, severity)
    for pat, rule, tool, ctx_re, window, msg, severity in CONTEXT:
        if re.search(pat, line) and near(line_no, ctx_re, window):
            emit(line_no, rule, tool, msg, severity)
PYEOF
}

# ── Security crypto/headers scan (cross-language) ────────────────────────────
# Phase 1C 2026-05-10. Detects hardcoded secrets (SEC-CRYPTO-KEY-001) plus
# CSPRNG context for crypto-specific identifiers (SEC-CRYPTO-RAND-001).
# Overlap with the auth-token CSPRNG detector is intentional: tokens are a
# subset of security-sensitive randomness, and crypto-specific identifiers
# (iv, nonce, salt) add new context to flag.
analyze_security_crypto_headers() {
  local file="$1"
  local lang="$2"

  python3 - <<'PYEOF' "$file" "$lang"
import json, os, re, sys
file_path = sys.argv[1]
lang = sys.argv[2]
basename = os.path.basename(file_path)
if basename.startswith("seed_") and basename.endswith(".py"):
    sys.exit(0)
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
        "tool": "writ-crypto-scan/" + tool,
        "message": message,
    }))

def near(line_no, marker_re, window=2):
    lo = max(0, line_no - 1 - window)
    hi = min(len(lines), line_no - 1 + window + 1)
    return any(re.search(marker_re, lines[i]) for i in range(lo, hi))

# SEC-CRYPTO-KEY-001: hardcoded secret patterns.
SECRET_PATTERNS = [
    (r"['\"](sk_live_[A-Za-z0-9]{16,})['\"]", "stripe-live", "Stripe live secret in source"),
    (r"['\"](sk_test_[A-Za-z0-9]{16,})['\"]", "stripe-test", "Stripe test secret in source (rotate before production)"),
    (r"['\"](AKIA[0-9A-Z]{16})['\"]", "aws-access-key", "AWS access key ID in source"),
    (r"['\"](xox[baprs]-[A-Za-z0-9-]{10,})['\"]", "slack-token", "Slack token in source"),
    (r"['\"](ghp_[A-Za-z0-9]{20,})['\"]", "github-pat", "GitHub personal access token in source"),
    (r"['\"](gho_[A-Za-z0-9]{20,})['\"]", "github-oauth", "GitHub OAuth token in source"),
    (r"-----BEGIN (RSA |DSA |EC |OPENSSH |PGP )?PRIVATE KEY-----", "pem-private-key",
     "PEM-encoded private key in source"),
]

# Identifier-based: API_KEY = "...", SECRET = "...", PASSWORD = "...", etc.
IDENT_ASSIGN = re.compile(
    r"\b(?:[A-Z_]*(?:API_?KEY|SECRET|PASSWORD|TOKEN|PRIVATE_?KEY|ACCESS_?KEY|AUTH_?KEY)[A-Z_]*)"
    r"\s*[:=]\s*['\"]([^'\"]{8,})['\"]"
)
# Lowercase variant (Python attribute / dict key assignment).
IDENT_ASSIGN_LOWER = re.compile(
    r"\b(?:api_key|secret|password|token|private_key|access_key|auth_key)\b"
    r"\s*[:=]\s*['\"]([^'\"]{8,})['\"]",
    re.IGNORECASE,
)

# Allowlist: obvious placeholders the linter should not flag.
PLACEHOLDER = re.compile(
    r"^(your[-_]?|example|placeholder|change[-_]?me|fake|dummy|test|sample|todo|xxx+|\.\.\.|<.+>)",
    re.IGNORECASE,
)

# SEC-CRYPTO-RAND-001: non-CSPRNG near crypto-specific identifiers.
CRYPTO_RNG = [
    (r"\bMath\.random\s*\(\s*\)", "weak-rng-crypto-node",
     "Math.random() near crypto identifier: use crypto.randomBytes()"),
    (r"\brandom\.(random|choice|choices|randint|randrange|uniform|getrandbits)\s*\(",
     "weak-rng-crypto-py",
     "random.* near crypto identifier: use secrets.token_bytes() or os.urandom()"),
    (r"\b(mt_rand|rand|srand)\s*\(", "weak-rng-crypto-php",
     "mt_rand/rand near crypto identifier: use random_bytes() or random_int()"),
]
CRYPTO_CTX = re.compile(
    r"\b(iv|nonce|salt|aes|gcm|cbc|aead|encrypt|cipher|hmac|signing[_-]?key)\b",
    re.IGNORECASE,
)

# SEC-CRYPTO-CERT-001: disabled cert verification.
CERT_DISABLE = [
    (r"\bverify\s*=\s*False\b", "verify-false-py",
     "verify=False disables TLS cert validation -- forbidden outside scoped local-dev paths"),
    (r"rejectUnauthorized\s*:\s*false", "reject-unauth-node",
     "rejectUnauthorized: false disables TLS cert validation"),
    (r"InsecureSkipVerify\s*:\s*true", "insecure-skip-go",
     "InsecureSkipVerify: true disables TLS cert validation"),
    (r"CURLOPT_SSL_VERIFYPEER\s*,\s*(false|0|FALSE)", "curl-verifypeer-php",
     "CURLOPT_SSL_VERIFYPEER false disables TLS cert validation"),
]

# SEC-CRYPTO-ALGO-001: forbidden symmetric algorithms and modes.
WEAK_CIPHER = [
    (r"AES\.MODE_ECB\b", "aes-ecb",
     "AES ECB mode: pattern-leaking; use AES-GCM or ChaCha20-Poly1305"),
    (r"\b(?:DES|TripleDES|3DES)\.new\s*\(", "des-cipher",
     "DES/3DES symmetric cipher: forbidden; use AES-256-GCM"),
    (r"\bARC4\.new\s*\(", "rc4-cipher", "RC4 cipher: forbidden"),
]

for line_no, line in enumerate(lines, start=1):
    stripped = line.lstrip()
    if stripped.startswith(("#", "//", "*")):
        continue

    # Hardcoded-secret patterns.
    for pat, tool, msg in SECRET_PATTERNS:
        if re.search(pat, line):
            emit(line_no, "SEC-CRYPTO-KEY-001", tool, msg, "error")

    # Identifier-based credential assignment.
    for ident_re in (IDENT_ASSIGN, IDENT_ASSIGN_LOWER):
        m = ident_re.search(line)
        if m:
            literal = m.group(1)
            if not PLACEHOLDER.match(literal):
                emit(line_no, "SEC-CRYPTO-KEY-001", "credential-literal-assign",
                     f"Credential assigned to string literal in source (load from env or secrets manager)",
                     "error")

    # CSPRNG context: only flag when crypto-specific identifier is nearby.
    for pat, tool, msg in CRYPTO_RNG:
        if re.search(pat, line) and near(line_no, CRYPTO_CTX, window=2):
            emit(line_no, "SEC-CRYPTO-RAND-001", tool, msg, "error")

    # Cert validation disable.
    for pat, tool, msg in CERT_DISABLE:
        if re.search(pat, line):
            emit(line_no, "SEC-CRYPTO-CERT-001", tool, msg, "error")

    # Weak symmetric algorithms.
    for pat, tool, msg in WEAK_CIPHER:
        if re.search(pat, line):
            emit(line_no, "SEC-CRYPTO-ALGO-001", tool, msg, "error")
PYEOF
}

# ── Security data-protection scan (cross-language) ───────────────────────────
# Phase 1D 2026-05-10. Detects PII passed to logger calls (SEC-DATA-PII-001).
# Heuristic: flag logger calls that reference PII-shaped identifiers.
# False positives accepted; reviewer judgment closes the gap.
analyze_security_data_protection() {
  local file="$1"
  local lang="$2"

  python3 - <<'PYEOF' "$file" "$lang"
import json, os, re, sys
file_path = sys.argv[1]
lang = sys.argv[2]
basename = os.path.basename(file_path)
if basename.startswith("seed_") and basename.endswith(".py"):
    sys.exit(0)
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
        "tool": "writ-data-scan/" + tool,
        "message": message,
    }))

# Logger call shapes across languages.
LOGGER_CALL = re.compile(
    r"\b(?:logger|logging|log|console|Log)\.(?:debug|info|warn(?:ing)?|error|fatal|trace|exception)\s*\("
    r"|\bprint\s*\("
    r"|\bSystem\.out\.println\s*\("
    r"|\berror_log\s*\("
)
# PII-shaped identifiers / keys.
PII_IDENT = re.compile(
    r"\b(?:e?mail(?:_?address)?|phone(?:_?number)?|ssn|sin|nin|social_?security|"
    r"dob|date_?of_?birth|street_?address|home_?address|"
    r"credit_?card(?:_?number)?|cc_?number|card_?pan|cvv|"
    r"passport(?:_?number)?|drivers_?license|tax_?id|national_?id)\b",
    re.IGNORECASE,
)
# Allowlist: hashed/redacted/masked variants are safe.
SAFE_SUFFIX = re.compile(r"_(hash|hashed|digest|redacted|masked|fingerprint|token)\b", re.IGNORECASE)

for line_no, line in enumerate(lines, start=1):
    stripped = line.lstrip()
    if stripped.startswith(("#", "//", "*")):
        continue
    if LOGGER_CALL.search(line):
        for m in PII_IDENT.finditer(line):
            start = m.start()
            tail = line[start: start + 60]
            if SAFE_SUFFIX.search(tail):
                continue
            emit(line_no, "SEC-DATA-PII-001", "pii-in-log",
                 f"Logger call references PII identifier '{m.group(0)}': redact, hash, or omit before logging",
                 "error")
            break  # one finding per line
PYEOF
}

# ── Performance N+1 scan (cross-language) ────────────────────────────────────
# Phase 3B 2026-05-10. Detects probable N+1 query patterns: a loop body
# that contains an ORM/DB access referencing the loop variable. Heuristic;
# false positives accepted, reported as warning rather than error.
analyze_performance_n_plus_one() {
  local file="$1"
  local lang="$2"

  python3 - <<'PYEOF' "$file" "$lang"
import json, os, re, sys
file_path = sys.argv[1]
lang = sys.argv[2]
basename = os.path.basename(file_path)
if basename.startswith("seed_") and basename.endswith(".py"):
    sys.exit(0)
try:
    with open(file_path, encoding="utf-8", errors="replace") as f:
        src = f.read()
except OSError:
    sys.exit(0)

lines = src.splitlines()

def emit(line_no, rule, tool, message, severity="warning"):
    print(json.dumps({
        "file": file_path,
        "line": line_no,
        "severity": severity,
        "rule": rule,
        "tool": "writ-perf-scan/" + tool,
        "message": message,
    }))

# Loop headers across languages.
FOR_LOOP = re.compile(
    r"\bfor\s+(\w+)\s+in\s+|"
    r"\bforeach\s*\(\s*\$\w+\s+as\s+\$(\w+)\s*\)|"
    r"\.forEach\s*\(\s*(?:\(?\s*(\w+)|function\s*\(\s*(\w+))|"
    r"\.map\s*\(\s*(?:\(?\s*(\w+)|function\s*\(\s*(\w+))"
)
# ORM/DB access methods that suggest a query.
DB_ACCESS = re.compile(
    r"\.(query|filter|filter_by|get|first|find|where|raw|execute|fetch|fetchall|fetchone|"
    r"objects\.get|objects\.filter|select|update|find_one|find_by_id|"
    r"findOne|findById|findOneBy)\s*\("
)

for i, line in enumerate(lines):
    stripped = line.lstrip()
    if stripped.startswith(("#", "//", "*")):
        continue
    m = FOR_LOOP.search(line)
    if not m:
        continue
    loop_var = next((g for g in m.groups() if g), None)
    if not loop_var:
        continue
    # Inspect next 10 lines for DB access that references the loop variable.
    indent = len(line) - len(line.lstrip())
    for j in range(i + 1, min(len(lines), i + 12)):
        body_line = lines[j]
        if not body_line.strip():
            continue
        # Stop if dedented out of the loop body.
        body_indent = len(body_line) - len(body_line.lstrip())
        if body_indent <= indent and body_line.strip():
            break
        if DB_ACCESS.search(body_line) and re.search(rf"\b{re.escape(loop_var)}\b", body_line):
            emit(j + 1, "PERF-QUERY-001", "loop-with-db-access",
                 f"Possible N+1: loop variable '{loop_var}' used in DB call inside loop body. "
                 f"Consider joins, eager loading, or batch fetching.",
                 "warning")
            break
PYEOF
}

# ── Scaling stateless scan ───────────────────────────────────────────────────
# Phase 4 2026-05-10. Detects module-level mutable globals whose names
# suggest user/session/cart state (SCALE-STATELESS-001). Conservative:
# only flags names that strongly imply per-request mutable state.
analyze_scaling_stateless() {
  local file="$1"
  local lang="$2"

  python3 - <<'PYEOF' "$file" "$lang"
import json, os, re, sys
file_path = sys.argv[1]
lang = sys.argv[2]
basename = os.path.basename(file_path)
if basename.startswith("seed_") and basename.endswith(".py"):
    sys.exit(0)
try:
    with open(file_path, encoding="utf-8", errors="replace") as f:
        src = f.read()
except OSError:
    sys.exit(0)

lines = src.splitlines()

def emit(line_no, rule, tool, message, severity="warning"):
    print(json.dumps({
        "file": file_path,
        "line": line_no,
        "severity": severity,
        "rule": rule,
        "tool": "writ-scale-scan/" + tool,
        "message": message,
    }))

# Module-level (indent == 0) mutable global with a state-suggesting name.
STATE_NAME = re.compile(
    r"^([A-Z_]*(?:USER|SESSION|CART|LOGIN|TOKEN|AUTH|CACHE|STORE|STATE)[A-Z_]*"
    r"|_?(?:user_?cache|session_?store|user_?carts|sessions|carts|active_users|user_state))\s*"
    r"(?::\s*[^=]+)?\s*=\s*(\{|\[|set\(\)|dict\(\)|list\(\)|defaultdict|OrderedDict|deque)",
    re.IGNORECASE,
)

for line_no, line in enumerate(lines, start=1):
    # Module-level only -- no leading whitespace.
    if line[:1] in (" ", "\t"):
        continue
    stripped = line.lstrip()
    if stripped.startswith(("#", "//", "*")):
        continue
    m = STATE_NAME.match(line)
    if m:
        emit(line_no, "SCALE-STATELESS-001", "module-state-global",
             f"Module-level mutable global '{m.group(1)}' suggests in-process user/session state; "
             f"move to external store (Redis, DB) for horizontal scaling.",
             "warning")
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

  # Cross-language auth/authz/validation scan (SEC-AUTH-*, SEC-AUTHZ-*,
  # SEC-VAL-* mandatory rules from the public rulebook, Phase 1B 2026-05-10).
  auth_result=$(analyze_security_auth_authz "$file" "$lang")
  if [ -n "$auth_result" ]; then
    ALL_FINDINGS="${ALL_FINDINGS}${auth_result}"$'\n'
    if echo "$auth_result" | grep -q '"severity": "error"'; then
      HAS_ERRORS=1
    fi
  fi

  # Cross-language crypto/headers scan (SEC-CRYPTO-* mandatory rules
  # from the public rulebook, Phase 1C 2026-05-10).
  crypto_result=$(analyze_security_crypto_headers "$file" "$lang")
  if [ -n "$crypto_result" ]; then
    ALL_FINDINGS="${ALL_FINDINGS}${crypto_result}"$'\n'
    if echo "$crypto_result" | grep -q '"severity": "error"'; then
      HAS_ERRORS=1
    fi
  fi

  # Cross-language data-protection scan (SEC-DATA-PII-001 from the public
  # rulebook, Phase 1D 2026-05-10).
  data_result=$(analyze_security_data_protection "$file" "$lang")
  if [ -n "$data_result" ]; then
    ALL_FINDINGS="${ALL_FINDINGS}${data_result}"$'\n'
    if echo "$data_result" | grep -q '"severity": "error"'; then
      HAS_ERRORS=1
    fi
  fi

  # Cross-language N+1 scan (PERF-QUERY-001 from the public rulebook,
  # Phase 3B 2026-05-10). Reports warnings; never blocks writes.
  perf_result=$(analyze_performance_n_plus_one "$file" "$lang")
  if [ -n "$perf_result" ]; then
    ALL_FINDINGS="${ALL_FINDINGS}${perf_result}"$'\n'
  fi

  # Stateless-process scan (SCALE-STATELESS-001 from the public rulebook,
  # Phase 4 2026-05-10). Reports warnings; never blocks writes.
  scale_result=$(analyze_scaling_stateless "$file" "$lang")
  if [ -n "$scale_result" ]; then
    ALL_FINDINGS="${ALL_FINDINGS}${scale_result}"$'\n'
  fi
done

# Output as JSON array
echo "$ALL_FINDINGS" | json_array

exit $HAS_ERRORS
