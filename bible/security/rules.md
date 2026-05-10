<!-- RULE START: SEC-INJ-CMD-001 -->
## Rule SEC-INJ-CMD-001

**Domain**: security
**Severity**: Critical
**Scope**: Component
**Mandatory**: true
**Mechanical_Enforcement_Path**: bin/run-analysis.sh::analyze_security_injection

### Trigger
When invoking shell commands from application code, especially when any argument could derive from user input.

### Statement
Shell commands must be invoked with an argument list, not a single string interpreted by a shell. Python: `subprocess.run([cmd, arg1, arg2])` (no `shell=True`). Node: `child_process.execFile`/`spawn` (not `exec`). PHP: explicit array arguments, never `shell_exec` with concatenated input.

### Violation
```python
subprocess.run(f"convert {user_filename} out.png", shell=True)
```
```javascript
child_process.exec(`grep ${pattern} ${file}`);
```

### Pass
```python
subprocess.run(["convert", user_filename, "out.png"])
```
```javascript
child_process.execFile("grep", [pattern, file]);
```

### Enforcement
Mechanically enforced by bin/run-analysis.sh::analyze_security_injection: regex flags `subprocess.run(`/`subprocess.Popen(` with `shell=True`, bare `os.system(`/`os.popen(`, `child_process.exec(`/`execSync(`, PHP `shell_exec`/`exec(`/`system(`/`passthru(` with non-constant args.

### Rationale
Shell command injection lets an attacker execute arbitrary OS commands. The argument-list invocation removes the shell as an interpreter, which removes the entire injection class.

<!-- RULE END: SEC-INJ-CMD-001 -->
---

<!-- RULE START: SEC-INJ-CMD-002 -->
## Rule SEC-INJ-CMD-002

**Domain**: security
**Severity**: High
**Scope**: Component
**Mandatory**: false

### Trigger
When using language-level eval, exec, or dynamic code-string evaluators (Python `eval`/`exec`, JavaScript `eval`/`new Function`, PHP `eval`).

### Statement
Dynamic code-string evaluation is prohibited when any input to the code string is not a literal constant. If dynamic dispatch is required, use a lookup table, dispatch dict, or registry pattern instead.

### Violation
```python
expr = request.GET["expr"]
result = eval(expr)
```
```javascript
const result = new Function(`return ${userExpr}`)();
```

### Pass
```python
OPS = {"sum": sum, "max": max, "min": min}
op = OPS.get(request.GET["op"])
if op is None:
    raise BadRequest("unknown op")
result = op(values)
```

### Enforcement
Mechanically enforced by bin/run-analysis.sh::analyze_security_injection: regex flags `eval(`, `exec(`, `new Function(`, PHP `eval(` and Python `compile(`+`exec(` patterns.

### Rationale
Dynamic code evaluation is a worse form of command injection: it gives the attacker the full execution environment of your process, including database connections and secrets. The lookup-table pattern covers nearly every legitimate dynamic-dispatch case.

<!-- RULE END: SEC-INJ-CMD-002 -->
---

<!-- RULE START: SEC-INJ-CSRF-001 -->
## Rule SEC-INJ-CSRF-001

**Domain**: security
**Severity**: Critical
**Scope**: Component
**Mandatory**: true
**Mechanical_Enforcement_Path**: bin/run-analysis.sh::analyze_security_injection

### Trigger
When implementing any HTTP endpoint that mutates server state (POST, PUT, PATCH, DELETE) and is reachable from a browser session.

### Statement
State-changing requests must be validated against an anti-CSRF token: synchronizer token, double-submit cookie, SameSite=Strict cookies plus origin check, or the framework's built-in CSRF middleware. Cross-origin state changes without a token are violations.

### Violation
```python
@app.route('/api/account/delete', methods=['POST'])
def delete_account():
    user.delete()
    return ok
# No CSRF token check; any malicious site can trigger deletion.
```

### Pass
```python
# Django: CsrfViewMiddleware enabled in settings; @csrf_protect on view.
# Flask: flask-wtf with CSRFProtect(app) and {{ csrf_token() }} in forms.
# FastAPI: starlette-csrf or app-level CSRF dependency.
# All same shape: token verified before mutation runs.
```

### Enforcement
Mechanically enforced by bin/run-analysis.sh::analyze_security_injection: framework-aware presence check (Django middleware enabled, Flask-WTF CSRFProtect initialized, etc.). Where framework support exists, opting out (`@csrf_exempt`) requires a documented justification.

### Rationale
Cross-site request forgery is the inverse of XSS: a malicious site causing the victim's authenticated browser to submit a request on their behalf. The token defense is universally available in modern frameworks; missing it is a clear violation.

<!-- RULE END: SEC-INJ-CSRF-001 -->
---

<!-- RULE START: SEC-INJ-DESER-001 -->
## Rule SEC-INJ-DESER-001

**Domain**: security
**Severity**: Critical
**Scope**: Component
**Mandatory**: true
**Mechanical_Enforcement_Path**: bin/run-analysis.sh::analyze_security_injection

### Trigger
When deserializing data received from any external or untrusted source (cookies, request bodies, files, queues, databases populated by other tenants).

### Statement
Untrusted data must never be deserialized with formats that allow code execution: Python `pickle`, PHP `unserialize`, Java `ObjectInputStream`, YAML `yaml.load` without `SafeLoader`, Ruby Marshal. Use JSON, MessagePack, or a typed schema (Protobuf, JSON Schema, Pydantic) instead.

### Violation
```python
import pickle
user_data = pickle.loads(request.cookies["session"])
```
```python
import yaml
config = yaml.load(file_content)  # uses Loader=Loader by default
```

### Pass
```python
import json
user_data = json.loads(request.cookies["session"])
```
```python
import yaml
config = yaml.safe_load(file_content)
# Or: Pydantic model validation for typed deserialization.
```

### Enforcement
Mechanically enforced by bin/run-analysis.sh::analyze_security_injection: regex flags `pickle.loads(`, `pickle.load(`, `yaml.load(` without `SafeLoader=`, PHP `unserialize(`, Java `ObjectInputStream`.

### Rationale
Insecure deserialization is one of the OWASP top categories because the impact is full RCE with very little attacker effort. The safe formats (JSON, typed schemas) cover every legitimate use case.

<!-- RULE END: SEC-INJ-DESER-001 -->
---

<!-- RULE START: SEC-INJ-HEADER-001 -->
## Rule SEC-INJ-HEADER-001

**Domain**: security
**Severity**: High
**Scope**: Component
**Mandatory**: false

### Trigger
When setting HTTP response headers whose values derive from user input (redirects with user-supplied URL, content-disposition with user filename, custom headers echoing request data).

### Statement
Response header values constructed from user input must reject or escape CR (`\r`, `%0d`) and LF (`\n`, `%0a`). Most frameworks reject newlines in header values automatically; custom header writers must do the same.

### Violation
```python
@app.route('/redirect')
def redirect_to():
    url = request.GET["next"]
    response = Response()
    response.headers["Location"] = url
    return response
# next='/home\r\nSet-Cookie: admin=1' injects a cookie
```

### Pass
```python
@app.route('/redirect')
def redirect_to():
    url = request.GET["next"]
    if "\r" in url or "\n" in url:
        raise BadRequest("invalid url")
    return redirect(url)
# Better: use framework redirect() which rejects newlines and validates url.
```

### Enforcement
Code review. Custom check: response.headers[X] = Y where Y derives from request input without explicit newline rejection.

### Rationale
Header injection (CRLF injection) lets attackers inject Set-Cookie or split the response into two responses. Modern frameworks generally reject it, but custom header writes bypass the framework's check.

<!-- RULE END: SEC-INJ-HEADER-001 -->
---

<!-- RULE START: SEC-INJ-LDAP-001 -->
## Rule SEC-INJ-LDAP-001

**Domain**: security
**Severity**: High
**Scope**: Component
**Mandatory**: false

### Trigger
When constructing LDAP search filters or DNs from any non-constant value.

### Statement
LDAP filter and DN construction must use the bind/parameter APIs provided by the LDAP client library, never string formatting. Special LDAP characters (`*`, `(`, `)`, `\`, NUL) in user input must be escaped before they reach the filter.

### Violation
```python
filter_str = f"(uid={username})"
conn.search_s(BASE_DN, ldap.SCOPE_SUBTREE, filter_str)
# username='*' returns every user
```

### Pass
```python
from ldap.filter import escape_filter_chars
filter_str = f"(uid={escape_filter_chars(username)})"
conn.search_s(BASE_DN, ldap.SCOPE_SUBTREE, filter_str)
```

### Enforcement
Code review. Custom ruff plugin or grep for LDAP search calls with non-constant filter strings.

### Rationale
LDAP injection is less common than SQL injection but the same shape: user input becomes filter syntax. `(uid=*)` is the LDAP equivalent of `1=1`. Escaping is mandatory when constants aren't an option.

<!-- RULE END: SEC-INJ-LDAP-001 -->
---

<!-- RULE START: SEC-INJ-LOG-001 -->
## Rule SEC-INJ-LOG-001

**Domain**: security
**Severity**: Medium
**Scope**: Component
**Mandatory**: false

### Trigger
When user-controlled values are written to application logs.

### Statement
Log values that originate from user input must be sanitized to prevent log injection or forging: strip or escape CR/LF, structure log entries as JSON or key-value pairs (one record per line) so injected newlines cannot fake additional log entries.

### Violation
```python
logger.info(f"User logged in: {user_input}")
# user_input='alice\nUSER DELETED root' fakes a deletion record
```

### Pass
```python
logger.info("user_login", extra={"user": user_input})
# Structured logger serializes to a single JSON line; embedded \n is escaped.
```

### Enforcement
Code review. Custom check on print()/logger calls with f-strings containing user-attribute references.

### Rationale
Forged log entries undermine incident response: an attacker can simulate evidence of someone else's actions. Structured logging removes the ambiguity by treating values as values, not as line content.

<!-- RULE END: SEC-INJ-LOG-001 -->
---

<!-- RULE START: SEC-INJ-PATH-001 -->
## Rule SEC-INJ-PATH-001

**Domain**: security
**Severity**: Critical
**Scope**: Component
**Mandatory**: false

### Trigger
When file paths are constructed from user input (uploads, downloads, includes, template loading, archive extraction).

### Statement
User-supplied path components must be validated against path traversal: reject `..`, null bytes, and absolute paths; resolve to a canonical path; verify the result is within the intended base directory. The base directory check uses canonical paths on both sides.

### Violation
```python
def serve(filename):
    with open(f"/var/uploads/{filename}") as f:
        return f.read()
# filename='../../etc/passwd' escapes the base
```

### Pass
```python
import os
BASE = os.path.realpath("/var/uploads")
def serve(filename):
    candidate = os.path.realpath(os.path.join(BASE, filename))
    if not candidate.startswith(BASE + os.sep):
        raise PermissionError("path traversal")
    with open(candidate) as f:
        return f.read()
```

### Enforcement
Code review. Static analysis can flag `os.path.join` followed by `open(` with non-constant first argument.

### Rationale
Path traversal is the simplest form of arbitrary file disclosure, and it consistently appears in real incidents. The realpath + prefix-check pattern is the only structurally safe form; everything else is filtering that misses cases (URL-encoded `..`, double encoding, Windows path separators).

<!-- RULE END: SEC-INJ-PATH-001 -->
---

<!-- RULE START: SEC-INJ-REDIR-001 -->
## Rule SEC-INJ-REDIR-001

**Domain**: security
**Severity**: High
**Scope**: Component
**Mandatory**: false

### Trigger
When an endpoint redirects the user to a URL supplied or influenced by request parameters (login-success redirects, return-to flows, deeplink handlers).

### Statement
Redirect destinations from user input must be validated against an allowlist of internal paths or an explicit list of permitted external hosts. Open redirect is a violation even when the receiving endpoint is otherwise harmless.

### Violation
```python
@app.route('/login')
def login():
    next_url = request.GET.get("next", "/")
    return redirect(next_url)
# next=//evil.example.com/phish is an open redirect
```

### Pass
```python
from urllib.parse import urlparse
ALLOWED_HOSTS = {"", "app.example.com"}  # empty string == relative path
@app.route('/login')
def login():
    next_url = request.GET.get("next", "/")
    parsed = urlparse(next_url)
    if parsed.netloc not in ALLOWED_HOSTS:
        next_url = "/"
    return redirect(next_url)
```

### Enforcement
Code review. Framework-specific redirect helpers (Django's `url_has_allowed_host_and_scheme`) provide a vetted check.

### Rationale
Open redirect is a phishing accelerator: attackers send links that look like they go to your domain and bounce the user to a credential-harvesting site. The allowlist pattern prevents that.

<!-- RULE END: SEC-INJ-REDIR-001 -->
---

<!-- RULE START: SEC-INJ-SQL-001 -->
## Rule SEC-INJ-SQL-001

**Domain**: security
**Severity**: Critical
**Scope**: Component
**Mandatory**: true
**Mechanical_Enforcement_Path**: bin/run-analysis.sh::analyze_security_injection

### Trigger
When writing SQL strings that include any variable, user input, or function return value.

### Statement
Parameterized queries only. SQL must never be built by string concatenation, format, f-string, or interpolation of any value that is not a literal constant. Every dynamic value enters through a bind parameter.

### Violation
```python
cursor.execute(f"SELECT * FROM users WHERE id = {user_id}")
# or
query = "SELECT * FROM users WHERE email = '" + email + "'"
cursor.execute(query)
```

### Pass
```python
cursor.execute(
    "SELECT * FROM users WHERE id = :user_id AND status = :status",
    {"user_id": user_id, "status": status},
)
```

### Enforcement
Mechanically enforced by bin/run-analysis.sh::analyze_security_injection: regex scan flags f-strings, .format(), and `+`-concatenation in proximity to execute/cursor/raw-query call sites. PHPStan + PHPCS catch the equivalent PHP patterns.

### Rationale
SQL injection remains the single most common high-severity web vulnerability. Parameterization is the only structurally safe pattern: it removes the user-input-as-code attack surface entirely instead of trying to sanitize it.

<!-- RULE END: SEC-INJ-SQL-001 -->
---

<!-- RULE START: SEC-INJ-SQL-002 -->
## Rule SEC-INJ-SQL-002

**Domain**: security
**Severity**: Critical
**Scope**: Component
**Mandatory**: false

### Trigger
When using ORM raw-query escape hatches (Django `raw()`, SQLAlchemy `text()`, Doctrine `getNativeQuery`, Eloquent `DB::raw`).

### Statement
ORM raw-query methods must use the ORM's parameter binding, never string interpolation. Escape hatches bypass the ORM's automatic parameterization; bound parameters bring it back.

### Violation
```python
# Django
User.objects.raw(f"SELECT * FROM users WHERE id = {user_id}")
# SQLAlchemy
session.execute(text(f"SELECT * FROM users WHERE id = {user_id}"))
```

### Pass
```python
# Django
User.objects.raw("SELECT * FROM users WHERE id = %s", [user_id])
# SQLAlchemy
session.execute(text("SELECT * FROM users WHERE id = :id"), {"id": user_id})
```

### Enforcement
Code review. Static analysis (custom ruff plugin or grep for ORM raw-method names with non-constant args) can flag the most common cases.

### Rationale
ORM raw-query methods are an injection vector hidden by a layer that usually protects the developer. The pattern is dangerous precisely because it looks like ORM code.

<!-- RULE END: SEC-INJ-SQL-002 -->
---

<!-- RULE START: SEC-INJ-SQL-003 -->
## Rule SEC-INJ-SQL-003

**Domain**: security
**Severity**: High
**Scope**: Component
**Mandatory**: false

### Trigger
When calling stored procedures from application code.

### Statement
Stored procedure invocations must pass arguments as bound parameters, never as part of the procedure call string.

### Violation
```python
cursor.execute(f"CALL get_user('{user_id}')")
```

### Pass
```python
cursor.callproc("get_user", [user_id])
# or
cursor.execute("CALL get_user(%s)", [user_id])
```

### Enforcement
Code review. Same SQL-concat detector flags the procedure-call form.

### Rationale
Stored procedures do not magically sanitize their inputs. Concatenation into a CALL statement is just SQL injection with a procedure name.

<!-- RULE END: SEC-INJ-SQL-003 -->
---

<!-- RULE START: SEC-INJ-SSRF-001 -->
## Rule SEC-INJ-SSRF-001

**Domain**: security
**Severity**: Critical
**Scope**: Component
**Mandatory**: true
**Mechanical_Enforcement_Path**: bin/run-analysis.sh::analyze_security_injection

### Trigger
When making outbound HTTP/network requests where the destination URL or host derives from user input (webhooks, URL previews, profile-image fetches, ingest jobs that follow a user-supplied link).

### Statement
Outbound requests with user-supplied destinations must validate the resolved host against an allowlist of permitted destinations. Block all RFC1918 ranges (10/8, 172.16/12, 192.168/16), loopback (127/8, ::1), link-local (169.254/16), cloud metadata IPs (169.254.169.254), and IPv4-mapped IPv6 forms of all of the above. Resolution and connection must use the same address to prevent DNS rebinding.

### Violation
```python
def fetch_preview(url):
    return requests.get(url, timeout=5).text
# url='http://169.254.169.254/latest/meta-data/' reads cloud creds
```

### Pass
```python
import ipaddress, socket
from urllib.parse import urlparse
ALLOWED_SCHEMES = {"http", "https"}
def fetch_preview(url):
    parsed = urlparse(url)
    if parsed.scheme not in ALLOWED_SCHEMES:
        raise ValueError("scheme not allowed")
    addr = socket.gethostbyname(parsed.hostname)
    if ipaddress.ip_address(addr).is_private or ipaddress.ip_address(addr).is_loopback:
        raise ValueError("internal address blocked")
    return requests.get(url, timeout=5).text
```

### Enforcement
Mechanically enforced by bin/run-analysis.sh::analyze_security_injection: regex flags `requests.get(`/`requests.post(`/`urllib.urlopen(`/`fetch(` with non-constant URL arguments. Static analysis cannot fully prove SSRF safety; the rule still requires reviewer attention.

### Rationale
SSRF is the canonical way attackers reach internal services from a public web app. Cloud metadata services (AWS IMDSv1, GCP, Azure) are the highest-impact target: they hand out credentials with no authentication. An allowlist is the only structurally safe pattern.

<!-- RULE END: SEC-INJ-SSRF-001 -->
---

<!-- RULE START: SEC-INJ-SSTI-001 -->
## Rule SEC-INJ-SSTI-001

**Domain**: security
**Severity**: Critical
**Scope**: Component
**Mandatory**: false

### Trigger
When user input could reach a template-rendering engine as the template string itself, not as a value passed to a fixed template.

### Statement
Template engines (Jinja2, Twig, Handlebars, ERB) must never receive user input as the template body. User values are arguments passed to a fixed template; the template itself is always a literal or a file path under developer control.

### Violation
```python
from jinja2 import Template
template = Template(request.POST["body"])
result = template.render(name=user.name)
# body='{{config.SECRET_KEY}}' leaks secrets
```

### Pass
```python
from jinja2 import Template
TEMPLATE = Template("Hello {{ name }}, your message: {{ body }}")
result = TEMPLATE.render(name=user.name, body=request.POST["body"])
```

### Enforcement
Code review. Static analysis: flag `Template(`/`new Template(`/`compile_template(` with non-constant args.

### Rationale
Server-side template injection often gives full RCE because template engines expose object internals (Python `.__class__.__mro__`, Java reflection). Treating the template body as code, not data, removes the entire class.

<!-- RULE END: SEC-INJ-SSTI-001 -->
---

<!-- RULE START: SEC-INJ-XSS-001 -->
## Rule SEC-INJ-XSS-001

**Domain**: security
**Severity**: Critical
**Scope**: Component
**Mandatory**: true
**Mechanical_Enforcement_Path**: bin/run-analysis.sh::analyze_security_injection

### Trigger
When user-supplied content is rendered in HTML, including server-rendered templates, JSX, and Vue/Svelte/Blade templates.

### Statement
All user-supplied content must be rendered through the framework's automatic escaping: React JSX `{value}`, Vue/Blade/Jinja2 `{{ value }}`, Twig `{{ value }}`, Angular interpolation. Never bypass framework escaping for user data.

### Violation
```jsx
<div dangerouslySetInnerHTML={{ __html: userComment }} />
```
```php
{!! $userComment !!}
```

### Pass
```jsx
<div>{userComment}</div>
```
```php
{{ $userComment }}
```

### Enforcement
Mechanically enforced by bin/run-analysis.sh::analyze_security_injection: regex scan flags `dangerouslySetInnerHTML`, `v-html`, `{!! !!}`, `innerHTML =`, `outerHTML =`, `document.write(`, and `$()`.html(` with non-constant args.

### Rationale
Cross-site scripting is endemic on the public web. Every modern framework provides automatic context-aware escaping; bypassing it removes the structural defense and falls back to manual sanitization, which is almost never done correctly.

<!-- RULE END: SEC-INJ-XSS-001 -->
---

<!-- RULE START: SEC-INJ-XSS-002 -->
## Rule SEC-INJ-XSS-002

**Domain**: security
**Severity**: Critical
**Scope**: Component
**Mandatory**: false

### Trigger
When writing JSX, Vue, Svelte, Blade, or other template code that touches any rendering API capable of inserting raw HTML.

### Statement
Never use `dangerouslySetInnerHTML`, `v-html`, `{!! !!}`, Svelte `{@html}`, or any equivalent unsafe-render API. If raw HTML is genuinely required (rich-text editor output), the content must be sanitized through a vetted library (DOMPurify, HTMLPurifier) before reaching the API.

### Violation
```jsx
function Comment({ html }) {
  return <div dangerouslySetInnerHTML={{ __html: html }} />;
}
```

### Pass
```jsx
import DOMPurify from 'dompurify';
function Comment({ html }) {
  return <div dangerouslySetInnerHTML={{ __html: DOMPurify.sanitize(html) }} />;
}
// Better: render as a tree of components rather than raw HTML.
```

### Enforcement
Mechanically enforced by bin/run-analysis.sh::analyze_security_injection alongside SEC-INJ-XSS-001.

### Rationale
The unsafe-render APIs exist for legitimate cases (already-sanitized HTML from a server-side library), but in practice they are used for user content without sanitization. Treating their presence as a code-smell forces the author to justify why sanitization is safe at this seam.

<!-- RULE END: SEC-INJ-XSS-002 -->
---

<!-- RULE START: SEC-INJ-XSS-003 -->
## Rule SEC-INJ-XSS-003

**Domain**: security
**Severity**: High
**Scope**: Component
**Mandatory**: false

### Trigger
When manipulating the DOM in vanilla JavaScript with user-controlled values.

### Statement
Direct DOM mutation methods that interpret strings as HTML (`innerHTML`, `outerHTML`, `document.write`, `$.html()`) must never receive user data. Use `textContent`, `innerText`, or framework-rendered nodes instead.

### Violation
```javascript
document.getElementById('msg').innerHTML = '<b>' + userMessage + '</b>';
```

### Pass
```javascript
const el = document.getElementById('msg');
const bold = document.createElement('b');
bold.textContent = userMessage;
el.replaceChildren(bold);
```

### Enforcement
Mechanically enforced by bin/run-analysis.sh::analyze_security_injection.

### Rationale
Manual DOM manipulation is rarely tested as carefully as the framework-rendered paths. The textContent/createElement form is both safe and clearer about its intent.

<!-- RULE END: SEC-INJ-XSS-003 -->
