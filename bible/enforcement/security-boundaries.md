<!-- RULE START: ENF-SEC-001 -->
## Rule ENF-SEC-001

**Domain**: Security
**Severity**: Critical
**Scope**: Slice
**Mandatory**: true
**Mechanical_Enforcement_Path**: bin/run-analysis.sh:78 (PHPStan ownership check)

### Trigger
When generating code for any externally accessible endpoint (REST route, GraphQL resolver, admin controller, storefront controller, CLI command).

### Statement
Every endpoint must have a written Access Boundary Declaration presented and approved before implementation code is produced. The declaration must answer four questions: who can call it, how the caller is authenticated, what data ownership rules apply, and what happens when unauthorized.

### Violation
```
// Phase A output for a GraphQL resolver:
"The reservations query returns reservation data for a given order ID."
// No mention of who can call it, how ownership is verified, or what happens for unauthorized callers.
```

### Pass
```
// Phase A output for a GraphQL resolver:
"reservations(order_id:) Access Boundary:
  Who: Admin (unrestricted), Customer (own orders only), Anonymous (denied)
  Auth: Caller identity + type checked in resolver via $context->getUserType()
  Ownership: Authenticated user ID must match order.customer_id
  Unauthorized: GraphQlAuthorizationException"
```

### Enforcement
ENF-GATE-007 test skeletons must include unauthorized caller test, ownership violation test, and valid caller test. > **Framework-specific guidance**: See `bible/frameworks/magento/runtime-constraints.md` for Magento 2 patterns (`webapi.xml`, `$context->getUserId()`, `_isAllowed()`, `GraphQlAuthorizationException`).

### Rationale
The most common security gap in AI-generated code is omission -- endpoints that work correctly but never ask "who should be allowed to call this?" Forcing the declaration before implementation makes security a first-class design constraint, not an afterthought.

<!-- RULE END: ENF-SEC-001 -->
