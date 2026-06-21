"""Phase 1C of the public rulebook expansion: Cryptography + HTTP Headers + Rate Limiting.

Seeds 19 new SEC-CRYPTO-*, SEC-HDR-*, and SEC-RATE-* rules into the graph
(2 mandatory) and renames the legacy SEC-UNI-004 -> SEC-CRYPTO-KEY-001.

Idempotent. Re-runs MERGE existing rules with the same rule_id.

Per the public rulebook source: out-of-the-box-rules.md sections 1E, 1F, 1G.
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
    source_section: str = "1E",
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
        "source_attribution": f"out-of-the-box-rules.md section {source_section}",
        "source_commit": "",
    }


ANALYZER_PATH = "bin/run-analysis.sh::analyze_security_crypto_headers"

# ============================================================================
# 1E. Cryptography & Secrets (8 rules, 2 mandatory)
# ============================================================================
CRYPTO_RULES = [
    _rule(
        "SEC-CRYPTO-KEY-001",
        "critical",
        "component",
        "When any string literal in source code matches the shape of a credential: API keys, passwords, private keys, OAuth client secrets, bearer tokens, database passwords, signing secrets.",
        "No hardcoded secrets, API keys, passwords, or private keys may appear in source code or committed configuration files. Secrets are loaded at runtime from environment variables or a secret-management service.",
        "```python\nAPI_KEY = 'sk_live_EXAMPLE_DO_NOT_USE_1234567890'\nstripe.api_key = API_KEY\n```\n```php\nprivate const API_KEY = 'sk_live_EXAMPLE_DO_NOT_USE_1234567890';\n$this->client->setApiKey(self::API_KEY);\n```",
        "```python\nimport os\nstripe.api_key = os.environ['STRIPE_API_KEY']\n```\n```php\n$apiKey = $this->deploymentConfig->get('payment/gateway/api_key');\n```",
        f"Mechanically enforced by {ANALYZER_PATH}: regex flags string literals matching `sk_live_*`, `AKIA*`, `xoxb-*`, `ghp_*`, `pk-` patterns; identifier names containing 'api_key', 'secret', 'token', 'password' assigned to a string literal; PEM block headers in source. CI: git pre-commit secret scanning (gitleaks, truffleHog).",
        "Hardcoded secrets end up in git history, CI logs, error messages, container images, and any system that processes the codebase. Once committed, a secret is effectively public and must be rotated. The structural defense is to never commit them.",
        mandatory=True,
        mechanical_enforcement_path=ANALYZER_PATH,
        source_section="1E",
    ),
    _rule(
        "SEC-CRYPTO-KEY-002",
        "high",
        "component",
        "When loading secrets, API keys, or credentials at application startup.",
        "Secrets must be loaded from environment variables or a secret-management service (Vault, AWS Secrets Manager, GCP Secret Manager, Azure Key Vault). Loading from a config file committed to VCS is a violation, even when the file is in a 'secrets' directory.",
        "```python\nwith open('config/secrets.yaml') as f:\n    secrets = yaml.safe_load(f)\napi_key = secrets['stripe']  # secrets.yaml is in git\n```",
        "```python\nimport os\napi_key = os.environ['STRIPE_API_KEY']\n# or via a secrets-manager client\napi_key = secrets_client.get_secret_value('prod/stripe')['SecretString']\n```",
        "CI check that no config file matching common secret-file names is tracked in git. Code review.",
        "Even a 'private' git repo is a much wider blast surface than a secrets manager. Pulling secrets at runtime keeps the credential out of the build artifact and the version history.",
        source_section="1E",
    ),
    _rule(
        "SEC-CRYPTO-ALGO-001",
        "critical",
        "component",
        "When implementing symmetric encryption for data at rest, message authentication, or session-token sealing.",
        "Symmetric encryption must use AES-256-GCM, ChaCha20-Poly1305, or AES-256-SIV. ECB mode is forbidden. DES, 3DES, RC4, Blowfish are forbidden. Modes without authentication (CBC, CTR alone) require an explicit HMAC.",
        "```python\nfrom Crypto.Cipher import AES\ncipher = AES.new(key, AES.MODE_ECB)  # ECB leaks plaintext patterns\nct = cipher.encrypt(plaintext)\n```",
        "```python\nfrom cryptography.hazmat.primitives.ciphers.aead import AESGCM\naesgcm = AESGCM(key)\nnonce = os.urandom(12)\nct = aesgcm.encrypt(nonce, plaintext, associated_data=None)\n```",
        "Code review. Static analysis flags AES.MODE_ECB, AES.MODE_CBC without an HMAC, DES, 3DES, RC4 usage.",
        "ECB mode preserves plaintext patterns and is famously broken (the 'ECB penguin'). Unauthenticated modes allow ciphertext modification. AEAD modes are the structural defense; they bundle confidentiality and integrity.",
        source_section="1E",
    ),
    _rule(
        "SEC-CRYPTO-ALGO-002",
        "high",
        "component",
        "When generating asymmetric key pairs (RSA, EC, Ed25519) for signing, encryption, or TLS.",
        "RSA keys are minimum 2048 bits; new keys should be 3072 or 4096 bits. EC keys use P-256 or stronger, or Ed25519. RSA-1024, DSA-1024, and short-curve EC keys are forbidden.",
        "```python\nrsa.generate_private_key(public_exponent=65537, key_size=1024)\n```",
        "```python\nrsa.generate_private_key(public_exponent=65537, key_size=3072)\n# or\ned25519.Ed25519PrivateKey.generate()\n```",
        "Code review of key-generation call sites. Audit of stored key material for legacy short-key remnants.",
        "1024-bit RSA is within practical attack reach of well-funded adversaries. Modern minimums ensure keys remain secure across the lifetime of the data they protect.",
        source_section="1E",
    ),
    _rule(
        "SEC-CRYPTO-RAND-001",
        "critical",
        "component",
        "When generating any value used for security: encryption keys, IVs, nonces, salts, signing keys, password-reset tokens, MFA codes, session IDs.",
        "Cryptographic operations must use a CSPRNG. Python `secrets` / `os.urandom`, Node `crypto.randomBytes`, Java `SecureRandom`, PHP `random_bytes` / `random_int`. Non-cryptographic generators (`random`, `Math.random`, `rand`, `mt_rand`) are forbidden for security-sensitive values.",
        "```python\nimport random\niv = bytes([random.randint(0, 255) for _ in range(12)])\ncipher = AESGCM(key).encrypt(iv, plaintext, None)\n```",
        "```python\nimport os\niv = os.urandom(12)\ncipher = AESGCM(key).encrypt(iv, plaintext, None)\n```",
        f"Mechanically enforced by {ANALYZER_PATH}: regex flags Math.random, random.random/randint/choices, rand/mt_rand in proximity to identifiers 'iv', 'nonce', 'salt', 'key', 'token', 'secret'. Overlaps with SEC-AUTH-TOKEN-001 by design (auth tokens are a subset of security-sensitive values).",
        "Predictable IVs and salts collapse the security of AEAD encryption (nonce reuse in GCM is catastrophic) and password hashing (predictable salts enable rainbow tables). The CSPRNG distinction is structural.",
        mandatory=True,
        mechanical_enforcement_path=ANALYZER_PATH,
        source_section="1E",
    ),
    _rule(
        "SEC-CRYPTO-TLS-001",
        "high",
        "component",
        "When configuring TLS servers, HTTPS clients, or any code that establishes encrypted transport.",
        "TLS 1.2 is the minimum; TLS 1.0 and 1.1 are disabled. The cipher suite excludes RC4, DES, 3DES, MD5-based MACs, and export-grade ciphers. Server configuration explicitly sets the floor.",
        "```python\nctx = ssl.SSLContext(ssl.PROTOCOL_SSLv23)  # accepts SSL 3.0 / TLS 1.0\n```",
        "```python\nctx = ssl.SSLContext(ssl.PROTOCOL_TLS)\nctx.minimum_version = ssl.TLSVersion.TLSv1_2\nctx.set_ciphers('HIGH:!aNULL:!MD5:!RC4:!3DES')\n```",
        "Server config review (nginx ssl_protocols, Apache SSLProtocol, Go tls.Config MinVersion, Java sslContext.getProtocol). Mozilla SSL Configuration Generator as reference.",
        "TLS 1.0 and 1.1 carry known weaknesses (BEAST, POODLE, weak MACs). Modern servers and clients all support 1.2+. Raising the floor is configuration only -- no application impact.",
        source_section="1E",
    ),
    _rule(
        "SEC-CRYPTO-CERT-001",
        "medium",
        "component",
        "When configuring an HTTPS client (requests, axios, http.Client, curl, custom).",
        "Certificate validation must not be disabled outside of clearly-scoped local development paths. `verify=False`, `rejectUnauthorized: false`, `InsecureSkipVerify: true`, `-k`/`--insecure` are violations in any code path that runs in production.",
        "```python\nrequests.get('https://api.example.com/payments', verify=False)\n```",
        "```python\nrequests.get('https://api.example.com/payments', verify=True)\n```",
        "Static analysis. Linter rules: ruff S501 (Python), eslint-plugin-security (Node), gosec (Go), CodeQL (multi-language).",
        "Disabling certificate validation removes the entire point of HTTPS: there is no longer any guarantee about who is on the other end. MITM attacks become trivial on any network the attacker can influence.",
        source_section="1E",
    ),
    _rule(
        "SEC-CRYPTO-IV-001",
        "high",
        "component",
        "When performing symmetric encryption that requires an IV or nonce (AES-GCM, AES-CBC, ChaCha20-Poly1305).",
        "IVs and nonces must be unique per encryption operation, generated by a CSPRNG, never reused with the same key. For GCM, nonce reuse with the same key is catastrophic (allows full plaintext recovery of both messages).",
        "```python\nIV = b'\\x00' * 12  # global constant; reused for every message\naesgcm.encrypt(IV, plaintext, None)\n```",
        "```python\nimport os\nnonce = os.urandom(12)\nciphertext = aesgcm.encrypt(nonce, plaintext, None)\n# Store nonce alongside ciphertext.\n```",
        "Code review. Look for module-level IV/nonce constants or fixed-byte assignments.",
        "Nonce reuse in GCM is one of the most catastrophic crypto failures: an attacker who sees two GCM messages with the same key+nonce can recover plaintexts and forge new authenticated messages. Per-message randomness is non-negotiable.",
        source_section="1E",
    ),
]

# ============================================================================
# 1F. HTTP Security Headers & Transport (6 rules)
# ============================================================================
HEADER_RULES = [
    _rule(
        "SEC-HDR-CSP-001",
        "high",
        "component",
        "When configuring an application that serves HTML responses to browsers.",
        "Content-Security-Policy header must be set on HTML responses. `unsafe-inline` and `unsafe-eval` are forbidden unless documented with the specific framework constraint that requires them. Default-src defaults to 'self'.",
        "```python\n@app.after_request\ndef add_csp(response):\n    return response  # no CSP header\n```",
        "```python\n@app.after_request\ndef add_csp(response):\n    response.headers['Content-Security-Policy'] = (\n        \"default-src 'self'; script-src 'self' 'nonce-{nonce}'; object-src 'none';\"\n    )\n    return response\n```",
        "Middleware review. Browsers expose CSP violations via report-uri; track those in monitoring.",
        "CSP is defense-in-depth against XSS that survives a bypass of input escaping. A well-formed CSP downgrades an XSS that did slip through from full account takeover to a script that cannot load resources.",
        source_section="1F",
    ),
    _rule(
        "SEC-HDR-CORS-001",
        "critical",
        "component",
        "When configuring CORS middleware for an API that uses cookie-based or token-based authentication.",
        "Access-Control-Allow-Origin must never be `*` for credentialed requests (Access-Control-Allow-Credentials: true). Origins are listed explicitly or validated against an allowlist of internal origins.",
        "```python\napp.add_middleware(CORSMiddleware,\n    allow_origins=['*'],\n    allow_credentials=True)\n# Browsers actually reject this combination, but middleware that\n# echoes back the requesting origin while sending credentials is the\n# common variant of the same bug.\n```",
        "```python\napp.add_middleware(CORSMiddleware,\n    allow_origins=['https://app.example.com', 'https://admin.example.com'],\n    allow_credentials=True)\n```",
        "Middleware config review.",
        "Wildcard origins with credentials let any malicious site read authenticated API responses. The explicit-origin requirement is the only structural defense.",
        source_section="1F",
    ),
    _rule(
        "SEC-HDR-FRAME-001",
        "medium",
        "component",
        "When serving HTML responses that include any state-changing or sensitive UI.",
        "X-Frame-Options: DENY (or SAMEORIGIN) or `frame-ancestors` in CSP must be set. Pages reachable from a browser session are not embeddable in third-party frames unless explicitly permitted.",
        "```python\n# No X-Frame-Options; page can be framed and used for clickjacking.\n```",
        "```python\nresponse.headers['X-Frame-Options'] = 'DENY'\n# Or via CSP:\nresponse.headers['Content-Security-Policy'] += ' frame-ancestors \\'none\\';'\n```",
        "Middleware config review.",
        "Clickjacking overlays a transparent frame of the target site over a decoy page and tricks the user into clicking the framed UI. Frame-Options blocks the structural prerequisite.",
        source_section="1F",
    ),
    _rule(
        "SEC-HDR-HSTS-001",
        "high",
        "component",
        "When serving any HTTPS endpoint from a production domain.",
        "Strict-Transport-Security header is set with max-age at least 31536000 seconds (1 year). includeSubDomains is added once subdomains are HTTPS-ready. preload submitted for production-stable domains.",
        "```python\n# No HSTS header; first-visit downgrade-to-HTTP attack still possible.\n```",
        "```python\nresponse.headers['Strict-Transport-Security'] = (\n    'max-age=31536000; includeSubDomains; preload'\n)\n```",
        "Middleware config review. Verify with securityheaders.com.",
        "HSTS instructs browsers to never speak HTTP to the host again, which kills downgrade attacks. The header is zero-cost once HTTPS coverage is complete.",
        source_section="1F",
    ),
    _rule(
        "SEC-HDR-TYPE-001",
        "medium",
        "component",
        "When serving any response from the application server.",
        "X-Content-Type-Options: nosniff is set on all responses. Browsers must respect the declared Content-Type and not infer it from the body.",
        "```python\n# Missing header; user-uploaded PNG containing HTML gets sniffed as HTML and executed.\n```",
        "```python\nresponse.headers['X-Content-Type-Options'] = 'nosniff'\n```",
        "Middleware config review.",
        "MIME sniffing turns user-uploaded files into XSS vectors by reinterpreting a misdeclared file as something else. The nosniff header structurally disables the sniff.",
        source_section="1F",
    ),
    _rule(
        "SEC-HDR-REFERRER-001",
        "low",
        "component",
        "When serving HTML responses.",
        "Referrer-Policy is set to `no-referrer` or `strict-origin-when-cross-origin`. Default-leak of the full URL (which may contain tokens or PII) to third-party hosts is prevented.",
        "```python\n# Default referrer policy leaks full URL to every cross-origin request.\n```",
        "```python\nresponse.headers['Referrer-Policy'] = 'strict-origin-when-cross-origin'\n```",
        "Middleware config review.",
        "Referrer headers carry full URLs by default, which routinely leak password-reset tokens, search queries, and internal page paths to advertising and analytics endpoints.",
        source_section="1F",
    ),
]

# ============================================================================
# 1G. Rate Limiting & DoS Prevention (5 rules)
# ============================================================================
RATE_RULES = [
    _rule(
        "SEC-RATE-API-001",
        "high",
        "component",
        "When exposing public API endpoints (REST, GraphQL, RPC) to internet traffic.",
        "Public API endpoints must be rate-limited per client identity (API key, authenticated user, or source IP for unauthenticated). The limit applies at the application or gateway layer, not just at the network layer.",
        "```python\n@app.get('/api/search')\ndef search(q):\n    return expensive_search(q)\n# Unlimited; one bot can hammer the endpoint into a degraded state.\n```",
        "```python\n@app.get('/api/search')\n@limiter.limit('60 per minute', key_func=client_identity)\ndef search(q):\n    return expensive_search(q)\n```",
        "Middleware config review. API gateways (Kong, Tyk, AWS API Gateway) provide native support.",
        "Without rate limits, a single client can exhaust capacity for everyone else. Per-identity limits provide fairness and a per-tenant denial-of-service floor.",
        source_section="1G",
    ),
    _rule(
        "SEC-RATE-LOGIN-001",
        "high",
        "component",
        "When implementing authentication endpoints (login, password reset, MFA verify, token exchange).",
        "Authentication endpoints carry their own rate limit, distinct from the general API limit. Login limits are per account AND per IP (per-account stops credential stuffing of a known user; per-IP stops bulk username enumeration).",
        "```python\n@app.post('/login')\ndef login():\n    ...\n# Falls under the general /api 60-per-minute limit -- enough room for\n# 60 credential-stuffing attempts per minute per IP.\n```",
        "```python\n@app.post('/login')\n@limiter.limit('5 per 15 minutes', key_func=lambda: request.json['email'])\n@limiter.limit('20 per 15 minutes', key_func=get_remote_address)\ndef login():\n    ...\n```",
        "Code review.",
        "Login endpoints are the highest-value attack surface; a per-account limit defeats stuffing of a target user, and a per-IP limit defeats horizontal sweeps.",
        source_section="1G",
    ),
    _rule(
        "SEC-RATE-UPLOAD-001",
        "high",
        "component",
        "When implementing file upload endpoints.",
        "File upload endpoints enforce explicit size limits at the application layer: max bytes per file AND max bytes per request body. The application rejects oversized requests before reading them entirely into memory.",
        "```python\n@app.post('/upload')\ndef upload():\n    f = request.files['file']\n    f.save('/tmp/...')  # whatever the client sent, however large\n```",
        "```python\napp.config['MAX_CONTENT_LENGTH'] = 10 * 1024 * 1024  # 10 MB\n@app.post('/upload')\ndef upload():\n    f = request.files['file']\n    if len(f.read()) > 5 * 1024 * 1024:  # 5 MB per file\n        abort(413)\n    ...\n```",
        "Framework config review (Flask MAX_CONTENT_LENGTH, Django DATA_UPLOAD_MAX_MEMORY_SIZE, nginx client_max_body_size).",
        "Unbounded upload endpoints are a direct DoS vector: a single 4GB POST can exhaust memory or fill disk. Application-layer caps prevent the request from ever reaching that state.",
        source_section="1G",
    ),
    _rule(
        "SEC-RATE-QUERY-001",
        "medium",
        "component",
        "When implementing endpoints that trigger database queries based on user input (list, search, filter, export, GraphQL collection fields).",
        "Database queries triggered by user input must apply pagination with a maximum page size, and unbounded result sets are not returned. The default page size is small; the max is bounded.",
        "```python\n@app.get('/api/orders')\ndef list_orders():\n    return Order.query.all()  # could be 10 million rows\n```",
        "```python\n@app.get('/api/orders')\ndef list_orders():\n    page = int(request.args.get('page', 1))\n    per_page = min(int(request.args.get('per_page', 25)), 200)\n    return Order.query.paginate(page=page, per_page=per_page).items\n```",
        "Code review. GraphQL: depth-limit / cost-analysis plugins.",
        "An unbounded query is a database DoS waiting to happen: one user with a wide filter holds a worker and a connection for minutes. Bounded pagination caps the worst case.",
        source_section="1G",
    ),
    _rule(
        "SEC-RATE-BATCH-001",
        "medium",
        "component",
        "When implementing bulk/batch endpoints that accept an array of operations (bulk create, bulk update, multi-delete).",
        "Batch endpoints cap the number of items accepted per request AND apply a per-batch rate limit. Unbounded batch APIs let a single request consume disproportionate resources.",
        "```python\n@app.post('/api/users/bulk')\ndef bulk_create(users: list[UserCreate]):\n    return [User.create(**u.dict()) for u in users]\n```",
        "```python\nMAX_BATCH = 100\n@app.post('/api/users/bulk')\n@limiter.limit('10 per minute')\ndef bulk_create(users: list[UserCreate]):\n    if len(users) > MAX_BATCH:\n        abort(400)\n    return [User.create(**u.dict()) for u in users]\n```",
        "Code review.",
        "Batch endpoints amplify request cost without amplifying client cost; capping batch size keeps cost ratio bounded.",
        source_section="1G",
    ),
]


RULES = CRYPTO_RULES + HEADER_RULES + RATE_RULES


async def main() -> None:
    db = FalkorDBLiteConnection(
        get_falkordb_path(), get_falkordb_graph(),
        get_falkordb_module(), get_redis_bin(),
    )
    try:
        # 1. Rename legacy SEC-UNI-004 -> SEC-CRYPTO-KEY-001 by deleting
        #    the old ID. The new rule carries the broader public-rulebook
        #    semantics (cross-language, not just PHP Magento); the PHP
        #    deployment-config pass example is preserved in the new rule.
        rows = db._execute_query(
            "MATCH (r:Rule {rule_id: 'SEC-UNI-004'}) DETACH DELETE r RETURN count(r) AS n"
        )
        print("DELETED SEC-UNI-004 (absorbed into SEC-CRYPTO-KEY-001)")

        # 2. Upsert the 19 SEC-CRYPTO-*, SEC-HDR-*, SEC-RATE-* rules.
        created = updated = 0
        for rule in RULES:
            rows = db._execute_query(
                "MATCH (r:Rule {rule_id: $rid}) RETURN r.rule_id AS x", rid=rule["rule_id"]
            )
            exists = bool(rows)
            props = {k: v for k, v in rule.items() if k != "rule_id"}
            db._execute_query(
                """
                MERGE (r:Rule {rule_id: $rid})
                SET r += $props
                """,
                rid=rule["rule_id"], props=props,
            )
            if exists:
                updated += 1
                print(f"UPDATED {rule['rule_id']:30s} {'[M]' if rule['mandatory'] else '   '} {rule['severity']}")
            else:
                created += 1
                print(f"CREATED {rule['rule_id']:30s} {'[M]' if rule['mandatory'] else '   '} {rule['severity']}")

        print()
        print(f"Summary: {created} created, {updated} updated.")

        rows = db._execute_query("MATCH (r:Rule) RETURN count(r) AS n")
        print(f"Total rules: {rows[0]['n']}")
        rows = db._execute_query("MATCH (r:Rule) WHERE r.mandatory = true RETURN count(r) AS n")
        print(f"Mandatory: {rows[0]['n']}")
    finally:
        await db.close()


if __name__ == "__main__":
    asyncio.run(main())
