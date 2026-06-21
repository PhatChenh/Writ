"""Phase 1D of the public rulebook expansion: Data Protection + Dependencies.

Seeds 10 new SEC-DATA-* and SEC-DEP-* rules into the graph (1 mandatory),
renames the legacy SEC-UNI-003 -> SEC-DATA-PII-002 (broader public-rulebook
phrasing), and deletes ENF-SEC-002 as a duplicate of SEC-DATA-PII-002.

Idempotent. Re-runs MERGE existing rules with the same rule_id.

Per the public rulebook source: out-of-the-box-rules.md sections 1H, 1I.
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
    source_section: str = "1H",
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


ANALYZER_PATH = "bin/run-analysis.sh::analyze_security_data_protection"

# ============================================================================
# 1H. Data Protection & Privacy (6 rules, 1 mandatory)
# ============================================================================
DATA_RULES = [
    _rule(
        "SEC-DATA-PII-001",
        "critical",
        "component",
        "When logging any value that may contain personally identifiable information: emails, phone numbers, addresses, SSNs, government IDs, credit-card numbers, dates of birth, full names paired with other identifiers.",
        "PII must never be written to plaintext logs. Either omit the value, hash it deterministically (for join-key utility), or redact to a token (`<redacted-email>`). The application is responsible for the redaction; relying on log-pipeline scrubbers downstream is a violation.",
        "```python\nlogger.info('User signed up', extra={'email': user.email, 'phone': user.phone})\n```",
        "```python\nlogger.info('User signed up', extra={\n    'user_id': user.id,\n    'email_hash': hash_pii(user.email),\n})\n```",
        f"Mechanically enforced by {ANALYZER_PATH}: regex flags logger calls that pass identifiers matching email/phone/ssn/dob/address/credit_card/passport/license patterns. False positives accepted; reviewer confirms.",
        "Logs are the most-replicated artifact a production system produces: they flow through stdout, CloudWatch, Splunk, S3, backups, devops laptops, and incident-response snapshots. PII in logs is functionally a permanent leak.",
        mandatory=True,
        mechanical_enforcement_path=ANALYZER_PATH,
        source_section="1H",
    ),
    _rule(
        "SEC-DATA-PII-002",
        "high",
        "component",
        "When designing API response shapes for endpoints that return user, account, or domain-entity data.",
        "API responses explicitly select which fields to include via a response schema or serializer. Returning the full entity (`return user`, `return model.to_dict()`) is a violation. The serializer enforces the field allowlist; fields the requester is not authorized to see are excluded at the data layer, not redacted in middleware.",
        "```python\n@app.get('/users/{user_id}')\ndef get_user(user_id):\n    user = User.query.get(user_id)\n    return user.to_dict()  # ships password_hash, tokens, internal flags\n```",
        "```python\nclass UserPublic(BaseModel):\n    id: int\n    name: str\n    avatar_url: str | None\n\n@app.get('/users/{user_id}')\ndef get_user(user_id):\n    user = User.query.get(user_id)\n    return UserPublic.from_orm(user)\n```",
        "Code review. Look for `to_dict()`, `model_dump()`, `__dict__` returned directly from a handler. Pydantic + response_model parameter (FastAPI) makes the allowlist explicit and enforced.",
        "Over-fetching is one of the most common privacy bugs: developers add a field for one consumer (admin UI) and forget the same response shape ships to every other consumer (public profile, mobile app, third-party integration). Explicit serializers contain the blast radius of new fields.",
        source_section="1H",
    ),
    _rule(
        "SEC-DATA-ENCRYPT-001",
        "high",
        "component",
        "When storing sensitive data: government IDs, financial account numbers, health records, credentials, biometric data, encryption keys, recovery codes.",
        "Sensitive data must be encrypted at rest. Acceptable mechanisms: database-level transparent encryption (TDE), field-level encryption with a KMS-managed key, application-level encryption with envelope-encrypted keys. Storing such data in plaintext columns is a violation.",
        "```python\nclass User(Base):\n    ssn = Column(String)  # plaintext\n    health_record = Column(JSON)  # plaintext\n```",
        "```python\nclass User(Base):\n    ssn_encrypted = Column(EncryptedString(key=kms.get_key('pii')))\n    health_record_encrypted = Column(EncryptedJSON(key=kms.get_key('phi')))\n```",
        "Schema review. Database-level encryption (PostgreSQL pgcrypto, MySQL transparent encryption) verifies at the platform layer.",
        "Database leaks are the highest-impact security event a service can suffer: a single backup snapshot reveals every user's data. Field-level encryption raises the bar so that a leak yields ciphertext, not records.",
        source_section="1H",
    ),
    _rule(
        "SEC-DATA-MASK-001",
        "medium",
        "component",
        "When error handlers, exception middleware, or stack-trace renderers may return error details to clients.",
        "Error responses must never expose internal paths, query text, schema details, library versions, stack traces, or env-var content to end users. Production handlers return a generic message with a correlation ID; the full detail goes to logs.",
        "```python\n@app.errorhandler(500)\ndef handle_500(e):\n    return {'error': str(e), 'traceback': traceback.format_exc()}, 500\n```",
        "```python\n@app.errorhandler(500)\ndef handle_500(e):\n    correlation_id = uuid.uuid4().hex\n    logger.exception('Unhandled error', extra={'correlation_id': correlation_id})\n    return {'error': 'Internal error', 'correlation_id': correlation_id}, 500\n```",
        "Framework config review (Flask DEBUG=False in prod, Django DEBUG=False, FastAPI custom exception_handlers, Express custom error middleware). E2E test that production error responses never include `traceback`, file paths, or SQL text.",
        "Stack traces in HTTP responses leak file paths, library versions, and code structure that aid reconnaissance. Generic messages plus correlation IDs preserve debuggability without exposing internals.",
        source_section="1H",
    ),
    _rule(
        "SEC-DATA-RETAIN-001",
        "medium",
        "component",
        "When designing schemas, batch jobs, or background processes that retain user data.",
        "Data retention must follow a documented policy with explicit lifetimes. Indefinite storage of user-generated content or analytics data requires a documented justification (legal obligation, contractual). A retention sweep job purges data past lifetime.",
        "```python\n# Audit log table grows forever; no retention sweep.\n# Search index keeps deleted records.\n```",
        "```python\n# audit_log: retained 90 days then purged.\n# search_index: synced from canonical store nightly; deletes propagate.\n```",
        "Schema review documenting retention per table. Audit job logs deletion counts.",
        "Long-retained data is a long-running liability: a leak today exposes data from years past. A retention policy bounds the exposure window structurally.",
        source_section="1H",
    ),
    _rule(
        "SEC-DATA-EXPORT-001",
        "medium",
        "component",
        "When implementing endpoints that return bulk data exports (CSV, JSON dump, ZIP archive, third-party data sync).",
        "Data export endpoints must implement access controls (the same authz as the underlying records, plus an explicit 'can-export' permission) and audit logging (who exported what, when). Per-request rate limits cap exfil volume.",
        "```python\n@app.get('/admin/users/export')\n@admin_required\ndef export_users():\n    return csv_of(User.query.all())\n# No audit log; no rate limit; no per-record permission check.\n```",
        "```python\n@app.get('/admin/users/export')\n@admin_required\n@require_permission('users.export')\n@limiter.limit('1 per hour')\ndef export_users():\n    audit_log.write('users-export', user=current_user, count=User.query.count())\n    return csv_of(User.query.all())\n```",
        "Code review.",
        "Bulk-export endpoints are the highest-leverage exfiltration paths in a compromised account. Explicit permissions plus audit logging plus rate limits provide defense-in-depth.",
        source_section="1H",
    ),
]

# ============================================================================
# 1I. Dependency & Supply Chain (4 rules)
# ============================================================================
DEP_RULES = [
    _rule(
        "SEC-DEP-AUDIT-001",
        "high",
        "component",
        "When adding, updating, or pinning a dependency in package.json, requirements.txt, pyproject.toml, Gemfile, composer.json, go.mod, Cargo.toml.",
        "No direct dependency may have a known critical-or-high-severity CVE. Acceptable mechanisms: npm audit, pip-audit, cargo audit, bundler-audit, composer audit, GitHub Dependabot, Snyk. The check runs in CI and gates merge.",
        "```\n# package.json carries lodash@4.17.4 with prototype-pollution CVE.\n```",
        "```\n# CI step:\n# npm audit --audit-level=high  -- exits 1 on critical/high\n```",
        "CI gate (npm audit, pip-audit, cargo audit). Dependabot/Renovate auto-PRs for vulnerable upgrades. Code review on bypass justifications.",
        "Most exploited vulnerabilities in modern services are dependency CVEs (Log4Shell, Spring4Shell, prototype-pollution chains). The audit step is mechanical and prevents the regression.",
        source_section="1I",
    ),
    _rule(
        "SEC-DEP-LOCK-001",
        "medium",
        "component",
        "When the project has a package manager that supports lockfiles.",
        "Lockfiles (package-lock.json, yarn.lock, poetry.lock, Cargo.lock, Gemfile.lock, composer.lock) are committed and used for installs in CI and production. `npm install` without an existing lockfile, `pip install` without `--require-hashes`, or production builds that resolve loose versions are violations.",
        "```\n# .gitignore contains package-lock.json; every install resolves\n# differently; supply-chain attacks have one fewer barrier.\n```",
        "```\n# package-lock.json committed; CI runs `npm ci` (not `npm install`).\n# pip: requirements.txt generated with `pip-compile --generate-hashes`.\n```",
        "CI/build config review.",
        "Lockfiles make installs deterministic: identical inputs produce identical outputs. A typosquat or compromised version published mid-window cannot enter the build without an explicit lockfile update.",
        source_section="1I",
    ),
    _rule(
        "SEC-DEP-PIN-001",
        "medium",
        "component",
        "When declaring dependency versions in manifest files.",
        "Dependencies are pinned to an exact version or a narrow range (`~1.2.3`, `>=1.2,<1.3`), not open-ended (`*`, `^1.0.0` on critical libs, `latest`). Lockfiles capture exact resolution; manifests bound which resolutions are acceptable.",
        "```json\n{\n  \"dependencies\": {\n    \"left-pad\": \"*\",\n    \"jsonwebtoken\": \"latest\"\n  }\n}\n```",
        "```json\n{\n  \"dependencies\": {\n    \"left-pad\": \"~1.3.0\",\n    \"jsonwebtoken\": \"^9.0.2\"\n  }\n}\n```",
        "Manifest review.",
        "Open-ended versions silently take new releases on every install, which has historically included malicious or breaking changes. Narrow ranges plus a lockfile bound the surprise.",
        source_section="1I",
    ),
    _rule(
        "SEC-DEP-REVIEW-001",
        "low",
        "component",
        "When opening a pull request that adds a new dependency to a manifest file.",
        "New dependency additions are documented in the PR description: what library, what it does, why this one over alternatives, license, maintainer activity (commits in last 6 months, weekly downloads). A reviewer signs off on the addition specifically.",
        "```\n# PR diff adds `left-pad@^1.3.0`. PR description: \"misc changes\".\n```",
        "```\n# PR description includes:\n# - New dep: left-pad@^1.3.0 (MIT). Used to format ledger output.\n# - Considered: native String#padStart (rejected: target Node < 8).\n# - Repo activity: last commit 2 months ago, 600k weekly downloads.\n```",
        "PR template + reviewer checklist. CODEOWNERS for manifest files routes adds to security-aware reviewers.",
        "Adding a dependency is a long-term commitment to a third party's security posture. The review forces a deliberate choice and creates an artifact for incident response when the dep is later compromised.",
        source_section="1I",
    ),
]


RULES = DATA_RULES + DEP_RULES


async def main() -> None:
    db = FalkorDBLiteConnection(
        get_falkordb_path(), get_falkordb_graph(),
        get_falkordb_module(), get_redis_bin(),
    )
    try:
        # 1. Rename legacy SEC-UNI-003 -> SEC-DATA-PII-002 by deleting
        #    the old ID.
        db._execute_query(
            "MATCH (r:Rule {rule_id: 'SEC-UNI-003'}) DETACH DELETE r"
        )
        print("DELETED SEC-UNI-003 (absorbed into SEC-DATA-PII-002)")

        # 2. Delete ENF-SEC-002 as a duplicate of SEC-DATA-PII-002
        #    (both required field allowlists in API responses).
        db._execute_query(
            "MATCH (r:Rule {rule_id: 'ENF-SEC-002'}) DETACH DELETE r"
        )
        print("DELETED ENF-SEC-002 (duplicate of SEC-DATA-PII-002)")

        # 3. Upsert the 10 SEC-DATA-*, SEC-DEP-* rules.
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
