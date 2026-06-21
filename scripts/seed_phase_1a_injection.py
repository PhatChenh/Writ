"""Phase 1A of the public rulebook expansion: Injection Prevention.

Seeds 17 SEC-INJ-* rules into the graph (6 mandatory) and absorbs the legacy
DB-SQL-001 (rename + broaden) into SEC-INJ-SQL-001.

Idempotent. Re-runs MERGE existing rules with the same rule_id.

Per the public rulebook source: out-of-the-box-rules.md section 1A.
"""

from __future__ import annotations

import asyncio
from datetime import date

from writ.config import get_falkordb_path, get_falkordb_graph, get_falkordb_module, get_redis_bin
from writ.graph.db import FalkorDBLiteConnection

TODAY = date.today().isoformat()


def _rule(
    rid: str,
    severity: str,
    scope: str,
    trigger: str,
    statement: str,
    violation: str,
    pass_example: str,
    enforcement: str,
    rationale: str,
    mandatory: bool = False,
    mechanical_enforcement_path: str | None = None,
) -> dict:
    return {
        "rule_id": rid,
        "domain": "security",
        "severity": severity,
        "scope": scope,
        "trigger": trigger,
        "statement": statement,
        "violation": violation,
        "pass_example": pass_example,
        "enforcement": enforcement,
        "rationale": rationale,
        "mandatory": mandatory,
        "mechanical_enforcement_path": mechanical_enforcement_path,
        "confidence": "production-validated",
        "authority": "human",
        "times_seen_positive": 0,
        "times_seen_negative": 0,
        "last_validated": TODAY,
        "evidence": "doc:public-rulebook-2026-05",
        "staleness_window": 365,
        "always_on": False,
        "body": "",
        "source_attribution": "out-of-the-box-rules.md section 1A",
        "source_commit": "",
    }


ANALYZER_PATH = "bin/run-analysis.sh::analyze_security_injection"

RULES = [
    _rule(
        "SEC-INJ-SQL-001",
        "critical",
        "component",
        "When writing SQL strings that include any variable, user input, or function return value.",
        "Parameterized queries only. SQL must never be built by string concatenation, format, f-string, or interpolation of any value that is not a literal constant. Every dynamic value enters through a bind parameter.",
        "```python\ncursor.execute(f\"SELECT * FROM users WHERE id = {user_id}\")\n# or\nquery = \"SELECT * FROM users WHERE email = '\" + email + \"'\"\ncursor.execute(query)\n```",
        "```python\ncursor.execute(\n    \"SELECT * FROM users WHERE id = :user_id AND status = :status\",\n    {\"user_id\": user_id, \"status\": status},\n)\n```",
        f"Mechanically enforced by {ANALYZER_PATH}: regex scan flags f-strings, .format(), and `+`-concatenation in proximity to execute/cursor/raw-query call sites. PHPStan + PHPCS catch the equivalent PHP patterns.",
        "SQL injection remains the single most common high-severity web vulnerability. Parameterization is the only structurally safe pattern: it removes the user-input-as-code attack surface entirely instead of trying to sanitize it.",
        mandatory=True,
        mechanical_enforcement_path=ANALYZER_PATH,
    ),
    _rule(
        "SEC-INJ-SQL-002",
        "critical",
        "component",
        "When using ORM raw-query escape hatches (Django `raw()`, SQLAlchemy `text()`, Doctrine `getNativeQuery`, Eloquent `DB::raw`).",
        "ORM raw-query methods must use the ORM's parameter binding, never string interpolation. Escape hatches bypass the ORM's automatic parameterization; bound parameters bring it back.",
        "```python\n# Django\nUser.objects.raw(f\"SELECT * FROM users WHERE id = {user_id}\")\n# SQLAlchemy\nsession.execute(text(f\"SELECT * FROM users WHERE id = {user_id}\"))\n```",
        "```python\n# Django\nUser.objects.raw(\"SELECT * FROM users WHERE id = %s\", [user_id])\n# SQLAlchemy\nsession.execute(text(\"SELECT * FROM users WHERE id = :id\"), {\"id\": user_id})\n```",
        "Code review. Static analysis (custom ruff plugin or grep for ORM raw-method names with non-constant args) can flag the most common cases.",
        "ORM raw-query methods are an injection vector hidden by a layer that usually protects the developer. The pattern is dangerous precisely because it looks like ORM code.",
    ),
    _rule(
        "SEC-INJ-SQL-003",
        "high",
        "component",
        "When calling stored procedures from application code.",
        "Stored procedure invocations must pass arguments as bound parameters, never as part of the procedure call string.",
        "```python\ncursor.execute(f\"CALL get_user('{user_id}')\")\n```",
        "```python\ncursor.callproc(\"get_user\", [user_id])\n# or\ncursor.execute(\"CALL get_user(%s)\", [user_id])\n```",
        "Code review. Same SQL-concat detector flags the procedure-call form.",
        "Stored procedures do not magically sanitize their inputs. Concatenation into a CALL statement is just SQL injection with a procedure name.",
    ),
    _rule(
        "SEC-INJ-XSS-001",
        "critical",
        "component",
        "When user-supplied content is rendered in HTML, including server-rendered templates, JSX, and Vue/Svelte/Blade templates.",
        "All user-supplied content must be rendered through the framework's automatic escaping: React JSX `{value}`, Vue/Blade/Jinja2 `{{ value }}`, Twig `{{ value }}`, Angular interpolation. Never bypass framework escaping for user data.",
        "```jsx\n<div dangerouslySetInnerHTML={{ __html: userComment }} />\n```\n```php\n{!! $userComment !!}\n```",
        "```jsx\n<div>{userComment}</div>\n```\n```php\n{{ $userComment }}\n```",
        f"Mechanically enforced by {ANALYZER_PATH}: regex scan flags `dangerouslySetInnerHTML`, `v-html`, `{{!! !!}}`, `innerHTML =`, `outerHTML =`, `document.write(`, and `$()`.html(` with non-constant args.",
        "Cross-site scripting is endemic on the public web. Every modern framework provides automatic context-aware escaping; bypassing it removes the structural defense and falls back to manual sanitization, which is almost never done correctly.",
        mandatory=True,
        mechanical_enforcement_path=ANALYZER_PATH,
    ),
    _rule(
        "SEC-INJ-XSS-002",
        "critical",
        "component",
        "When writing JSX, Vue, Svelte, Blade, or other template code that touches any rendering API capable of inserting raw HTML.",
        "Never use `dangerouslySetInnerHTML`, `v-html`, `{!! !!}`, Svelte `{@html}`, or any equivalent unsafe-render API. If raw HTML is genuinely required (rich-text editor output), the content must be sanitized through a vetted library (DOMPurify, HTMLPurifier) before reaching the API.",
        "```jsx\nfunction Comment({ html }) {\n  return <div dangerouslySetInnerHTML={{ __html: html }} />;\n}\n```",
        "```jsx\nimport DOMPurify from 'dompurify';\nfunction Comment({ html }) {\n  return <div dangerouslySetInnerHTML={{ __html: DOMPurify.sanitize(html) }} />;\n}\n// Better: render as a tree of components rather than raw HTML.\n```",
        f"Mechanically enforced by {ANALYZER_PATH} alongside SEC-INJ-XSS-001.",
        "The unsafe-render APIs exist for legitimate cases (already-sanitized HTML from a server-side library), but in practice they are used for user content without sanitization. Treating their presence as a code-smell forces the author to justify why sanitization is safe at this seam.",
    ),
    _rule(
        "SEC-INJ-XSS-003",
        "high",
        "component",
        "When manipulating the DOM in vanilla JavaScript with user-controlled values.",
        "Direct DOM mutation methods that interpret strings as HTML (`innerHTML`, `outerHTML`, `document.write`, `$.html()`) must never receive user data. Use `textContent`, `innerText`, or framework-rendered nodes instead.",
        "```javascript\ndocument.getElementById('msg').innerHTML = '<b>' + userMessage + '</b>';\n```",
        "```javascript\nconst el = document.getElementById('msg');\nconst bold = document.createElement('b');\nbold.textContent = userMessage;\nel.replaceChildren(bold);\n```",
        f"Mechanically enforced by {ANALYZER_PATH}.",
        "Manual DOM manipulation is rarely tested as carefully as the framework-rendered paths. The textContent/createElement form is both safe and clearer about its intent.",
    ),
    _rule(
        "SEC-INJ-CMD-001",
        "critical",
        "component",
        "When invoking shell commands from application code, especially when any argument could derive from user input.",
        "Shell commands must be invoked with an argument list, not a single string interpreted by a shell. Python: `subprocess.run([cmd, arg1, arg2])` (no `shell=True`). Node: `child_process.execFile`/`spawn` (not `exec`). PHP: explicit array arguments, never `shell_exec` with concatenated input.",
        "```python\nsubprocess.run(f\"convert {user_filename} out.png\", shell=True)\n```\n```javascript\nchild_process.exec(`grep ${pattern} ${file}`);\n```",
        "```python\nsubprocess.run([\"convert\", user_filename, \"out.png\"])\n```\n```javascript\nchild_process.execFile(\"grep\", [pattern, file]);\n```",
        f"Mechanically enforced by {ANALYZER_PATH}: regex flags `subprocess.run(`/`subprocess.Popen(` with `shell=True`, bare `os.system(`/`os.popen(`, `child_process.exec(`/`execSync(`, PHP `shell_exec`/`exec(`/`system(`/`passthru(` with non-constant args.",
        "Shell command injection lets an attacker execute arbitrary OS commands. The argument-list invocation removes the shell as an interpreter, which removes the entire injection class.",
        mandatory=True,
        mechanical_enforcement_path=ANALYZER_PATH,
    ),
    _rule(
        "SEC-INJ-CMD-002",
        "high",
        "component",
        "When using language-level eval, exec, or dynamic code-string evaluators (Python `eval`/`exec`, JavaScript `eval`/`new Function`, PHP `eval`).",
        "Dynamic code-string evaluation is prohibited when any input to the code string is not a literal constant. If dynamic dispatch is required, use a lookup table, dispatch dict, or registry pattern instead.",
        "```python\nexpr = request.GET[\"expr\"]\nresult = eval(expr)\n```\n```javascript\nconst result = new Function(`return ${userExpr}`)();\n```",
        "```python\nOPS = {\"sum\": sum, \"max\": max, \"min\": min}\nop = OPS.get(request.GET[\"op\"])\nif op is None:\n    raise BadRequest(\"unknown op\")\nresult = op(values)\n```",
        f"Mechanically enforced by {ANALYZER_PATH}: regex flags `eval(`, `exec(`, `new Function(`, PHP `eval(` and Python `compile(`+`exec(` patterns.",
        "Dynamic code evaluation is a worse form of command injection: it gives the attacker the full execution environment of your process, including database connections and secrets. The lookup-table pattern covers nearly every legitimate dynamic-dispatch case.",
    ),
    _rule(
        "SEC-INJ-PATH-001",
        "critical",
        "component",
        "When file paths are constructed from user input (uploads, downloads, includes, template loading, archive extraction).",
        "User-supplied path components must be validated against path traversal: reject `..`, null bytes, and absolute paths; resolve to a canonical path; verify the result is within the intended base directory. The base directory check uses canonical paths on both sides.",
        "```python\ndef serve(filename):\n    with open(f\"/var/uploads/{filename}\") as f:\n        return f.read()\n# filename='../../etc/passwd' escapes the base\n```",
        "```python\nimport os\nBASE = os.path.realpath(\"/var/uploads\")\ndef serve(filename):\n    candidate = os.path.realpath(os.path.join(BASE, filename))\n    if not candidate.startswith(BASE + os.sep):\n        raise PermissionError(\"path traversal\")\n    with open(candidate) as f:\n        return f.read()\n```",
        "Code review. Static analysis can flag `os.path.join` followed by `open(` with non-constant first argument.",
        "Path traversal is the simplest form of arbitrary file disclosure, and it consistently appears in real incidents. The realpath + prefix-check pattern is the only structurally safe form; everything else is filtering that misses cases (URL-encoded `..`, double encoding, Windows path separators).",
    ),
    _rule(
        "SEC-INJ-LDAP-001",
        "high",
        "component",
        "When constructing LDAP search filters or DNs from any non-constant value.",
        "LDAP filter and DN construction must use the bind/parameter APIs provided by the LDAP client library, never string formatting. Special LDAP characters (`*`, `(`, `)`, `\\`, NUL) in user input must be escaped before they reach the filter.",
        "```python\nfilter_str = f\"(uid={username})\"\nconn.search_s(BASE_DN, ldap.SCOPE_SUBTREE, filter_str)\n# username='*' returns every user\n```",
        "```python\nfrom ldap.filter import escape_filter_chars\nfilter_str = f\"(uid={escape_filter_chars(username)})\"\nconn.search_s(BASE_DN, ldap.SCOPE_SUBTREE, filter_str)\n```",
        "Code review. Custom ruff plugin or grep for LDAP search calls with non-constant filter strings.",
        "LDAP injection is less common than SQL injection but the same shape: user input becomes filter syntax. `(uid=*)` is the LDAP equivalent of `1=1`. Escaping is mandatory when constants aren't an option.",
    ),
    _rule(
        "SEC-INJ-SSRF-001",
        "critical",
        "component",
        "When making outbound HTTP/network requests where the destination URL or host derives from user input (webhooks, URL previews, profile-image fetches, ingest jobs that follow a user-supplied link).",
        "Outbound requests with user-supplied destinations must validate the resolved host against an allowlist of permitted destinations. Block all RFC1918 ranges (10/8, 172.16/12, 192.168/16), loopback (127/8, ::1), link-local (169.254/16), cloud metadata IPs (169.254.169.254), and IPv4-mapped IPv6 forms of all of the above. Resolution and connection must use the same address to prevent DNS rebinding.",
        "```python\ndef fetch_preview(url):\n    return requests.get(url, timeout=5).text\n# url='http://169.254.169.254/latest/meta-data/' reads cloud creds\n```",
        "```python\nimport ipaddress, socket\nfrom urllib.parse import urlparse\nALLOWED_SCHEMES = {\"http\", \"https\"}\ndef fetch_preview(url):\n    parsed = urlparse(url)\n    if parsed.scheme not in ALLOWED_SCHEMES:\n        raise ValueError(\"scheme not allowed\")\n    addr = socket.gethostbyname(parsed.hostname)\n    if ipaddress.ip_address(addr).is_private or ipaddress.ip_address(addr).is_loopback:\n        raise ValueError(\"internal address blocked\")\n    return requests.get(url, timeout=5).text\n```",
        f"Mechanically enforced by {ANALYZER_PATH}: regex flags `requests.get(`/`requests.post(`/`urllib.urlopen(`/`fetch(` with non-constant URL arguments. Static analysis cannot fully prove SSRF safety; the rule still requires reviewer attention.",
        "SSRF is the canonical way attackers reach internal services from a public web app. Cloud metadata services (AWS IMDSv1, GCP, Azure) are the highest-impact target: they hand out credentials with no authentication. An allowlist is the only structurally safe pattern.",
        mandatory=True,
        mechanical_enforcement_path=ANALYZER_PATH,
    ),
    _rule(
        "SEC-INJ-SSTI-001",
        "critical",
        "component",
        "When user input could reach a template-rendering engine as the template string itself, not as a value passed to a fixed template.",
        "Template engines (Jinja2, Twig, Handlebars, ERB) must never receive user input as the template body. User values are arguments passed to a fixed template; the template itself is always a literal or a file path under developer control.",
        "```python\nfrom jinja2 import Template\ntemplate = Template(request.POST[\"body\"])\nresult = template.render(name=user.name)\n# body='{{config.SECRET_KEY}}' leaks secrets\n```",
        "```python\nfrom jinja2 import Template\nTEMPLATE = Template(\"Hello {{ name }}, your message: {{ body }}\")\nresult = TEMPLATE.render(name=user.name, body=request.POST[\"body\"])\n```",
        "Code review. Static analysis: flag `Template(`/`new Template(`/`compile_template(` with non-constant args.",
        "Server-side template injection often gives full RCE because template engines expose object internals (Python `.__class__.__mro__`, Java reflection). Treating the template body as code, not data, removes the entire class.",
    ),
    _rule(
        "SEC-INJ-HEADER-001",
        "high",
        "component",
        "When setting HTTP response headers whose values derive from user input (redirects with user-supplied URL, content-disposition with user filename, custom headers echoing request data).",
        "Response header values constructed from user input must reject or escape CR (`\\r`, `%0d`) and LF (`\\n`, `%0a`). Most frameworks reject newlines in header values automatically; custom header writers must do the same.",
        "```python\n@app.route('/redirect')\ndef redirect_to():\n    url = request.GET[\"next\"]\n    response = Response()\n    response.headers[\"Location\"] = url\n    return response\n# next='/home\\r\\nSet-Cookie: admin=1' injects a cookie\n```",
        "```python\n@app.route('/redirect')\ndef redirect_to():\n    url = request.GET[\"next\"]\n    if \"\\r\" in url or \"\\n\" in url:\n        raise BadRequest(\"invalid url\")\n    return redirect(url)\n# Better: use framework redirect() which rejects newlines and validates url.\n```",
        "Code review. Custom check: response.headers[X] = Y where Y derives from request input without explicit newline rejection.",
        "Header injection (CRLF injection) lets attackers inject Set-Cookie or split the response into two responses. Modern frameworks generally reject it, but custom header writes bypass the framework's check.",
    ),
    _rule(
        "SEC-INJ-LOG-001",
        "medium",
        "component",
        "When user-controlled values are written to application logs.",
        "Log values that originate from user input must be sanitized to prevent log injection or forging: strip or escape CR/LF, structure log entries as JSON or key-value pairs (one record per line) so injected newlines cannot fake additional log entries.",
        "```python\nlogger.info(f\"User logged in: {user_input}\")\n# user_input='alice\\nUSER DELETED root' fakes a deletion record\n```",
        "```python\nlogger.info(\"user_login\", extra={\"user\": user_input})\n# Structured logger serializes to a single JSON line; embedded \\n is escaped.\n```",
        "Code review. Custom check on print()/logger calls with f-strings containing user-attribute references.",
        "Forged log entries undermine incident response: an attacker can simulate evidence of someone else's actions. Structured logging removes the ambiguity by treating values as values, not as line content.",
    ),
    _rule(
        "SEC-INJ-DESER-001",
        "critical",
        "component",
        "When deserializing data received from any external or untrusted source (cookies, request bodies, files, queues, databases populated by other tenants).",
        "Untrusted data must never be deserialized with formats that allow code execution: Python `pickle`, PHP `unserialize`, Java `ObjectInputStream`, YAML `yaml.load` without `SafeLoader`, Ruby Marshal. Use JSON, MessagePack, or a typed schema (Protobuf, JSON Schema, Pydantic) instead.",
        "```python\nimport pickle\nuser_data = pickle.loads(request.cookies[\"session\"])\n```\n```python\nimport yaml\nconfig = yaml.load(file_content)  # uses Loader=Loader by default\n```",
        "```python\nimport json\nuser_data = json.loads(request.cookies[\"session\"])\n```\n```python\nimport yaml\nconfig = yaml.safe_load(file_content)\n# Or: Pydantic model validation for typed deserialization.\n```",
        f"Mechanically enforced by {ANALYZER_PATH}: regex flags `pickle.loads(`, `pickle.load(`, `yaml.load(` without `SafeLoader=`, PHP `unserialize(`, Java `ObjectInputStream`.",
        "Insecure deserialization is one of the OWASP top categories because the impact is full RCE with very little attacker effort. The safe formats (JSON, typed schemas) cover every legitimate use case.",
        mandatory=True,
        mechanical_enforcement_path=ANALYZER_PATH,
    ),
    _rule(
        "SEC-INJ-REDIR-001",
        "high",
        "component",
        "When an endpoint redirects the user to a URL supplied or influenced by request parameters (login-success redirects, return-to flows, deeplink handlers).",
        "Redirect destinations from user input must be validated against an allowlist of internal paths or an explicit list of permitted external hosts. Open redirect is a violation even when the receiving endpoint is otherwise harmless.",
        "```python\n@app.route('/login')\ndef login():\n    next_url = request.GET.get(\"next\", \"/\")\n    return redirect(next_url)\n# next=//evil.example.com/phish is an open redirect\n```",
        "```python\nfrom urllib.parse import urlparse\nALLOWED_HOSTS = {\"\", \"app.example.com\"}  # empty string == relative path\n@app.route('/login')\ndef login():\n    next_url = request.GET.get(\"next\", \"/\")\n    parsed = urlparse(next_url)\n    if parsed.netloc not in ALLOWED_HOSTS:\n        next_url = \"/\"\n    return redirect(next_url)\n```",
        "Code review. Framework-specific redirect helpers (Django's `url_has_allowed_host_and_scheme`) provide a vetted check.",
        "Open redirect is a phishing accelerator: attackers send links that look like they go to your domain and bounce the user to a credential-harvesting site. The allowlist pattern prevents that.",
    ),
    _rule(
        "SEC-INJ-CSRF-001",
        "critical",
        "component",
        "When implementing any HTTP endpoint that mutates server state (POST, PUT, PATCH, DELETE) and is reachable from a browser session.",
        "State-changing requests must be validated against an anti-CSRF token: synchronizer token, double-submit cookie, SameSite=Strict cookies plus origin check, or the framework's built-in CSRF middleware. Cross-origin state changes without a token are violations.",
        "```python\n@app.route('/api/account/delete', methods=['POST'])\ndef delete_account():\n    user.delete()\n    return ok\n# No CSRF token check; any malicious site can trigger deletion.\n```",
        "```python\n# Django: CsrfViewMiddleware enabled in settings; @csrf_protect on view.\n# Flask: flask-wtf with CSRFProtect(app) and {{ csrf_token() }} in forms.\n# FastAPI: starlette-csrf or app-level CSRF dependency.\n# All same shape: token verified before mutation runs.\n```",
        f"Mechanically enforced by {ANALYZER_PATH}: framework-aware presence check (Django middleware enabled, Flask-WTF CSRFProtect initialized, etc.). Where framework support exists, opting out (`@csrf_exempt`) requires a documented justification.",
        "Cross-site request forgery is the inverse of XSS: a malicious site causing the victim's authenticated browser to submit a request on their behalf. The token defense is universally available in modern frameworks; missing it is a clear violation.",
        mandatory=True,
        mechanical_enforcement_path=ANALYZER_PATH,
    ),
]


async def main() -> None:
    db = FalkorDBLiteConnection(
        get_falkordb_path(), get_falkordb_graph(),
        get_falkordb_module(), get_redis_bin(),
    )
    try:
        # 1. Absorb DB-SQL-001 into SEC-INJ-SQL-001 by deleting the legacy ID.
        # The new SEC-INJ-SQL-001 rule below covers the broader principle;
        # the named-bind style refinement from DB-SQL-001 is captured in its
        # pass_example. DB-SQL-002 and DB-SQL-003 remain (SQL formatting,
        # not in the public rulebook).
        db._execute_query(
            "MATCH (r:Rule {rule_id: 'DB-SQL-001'}) DETACH DELETE r"
        )
        print("DELETED DB-SQL-001 (absorbed into SEC-INJ-SQL-001)")

        # 2. Upsert the 17 SEC-INJ-* rules.
        created = updated = 0
        for rule in RULES:
            rows = db._execute_query(
                "MATCH (r:Rule {rule_id: $rid}) RETURN r.rule_id AS x",
                {"rid": rule["rule_id"]},
            )
            exists = bool(rows)
            # MERGE semantics on rule_id; SET overwrites all listed props.
            props = {k: v for k, v in rule.items() if k != "rule_id"}
            db._execute_query(
                """
                MERGE (r:Rule {rule_id: $rid})
                SET r += $props
                """,
                {"rid": rule["rule_id"], "props": props},
            )
            if exists:
                updated += 1
                print(f"UPDATED {rule['rule_id']:25s} {'[M]' if rule['mandatory'] else '   '} {rule['severity']}")
            else:
                created += 1
                print(f"CREATED {rule['rule_id']:25s} {'[M]' if rule['mandatory'] else '   '} {rule['severity']}")

        print()
        print(f"Summary: {created} created, {updated} updated.")

        # 3. Sanity check
        rows = db._execute_query("MATCH (r:Rule) RETURN count(r) AS n")
        print(f"Total rules: {rows[0]['n']}")
        rows = db._execute_query("MATCH (r:Rule) WHERE r.mandatory = true RETURN count(r) AS n")
        print(f"Mandatory: {rows[0]['n']}")
    finally:
        await db.close()


if __name__ == "__main__":
    asyncio.run(main())
