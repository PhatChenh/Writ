<!-- RULE START: DB-SQL-002 -->
## Rule DB-SQL-002

**Domain**: Database / SQL
**Severity**: Medium
**Scope**: Entity
**Mandatory**: false

### Trigger
When a raw SQL query is constructed using string concatenation (`.` operator in PHP) across more than 2 fragments without conditional logic requiring the split.

### Statement
Define SQL in a single heredoc or multi-line string. Split only when conditional WHERE clauses or dynamic JOINs require it.

### Violation
```php
$sql = "SELECT o.order_id, o.customer_id, c.name " .
       "FROM sales_order o " .
       "JOIN customer_entity c ON c.entity_id = o.customer_id " .
       "WHERE o.status = :status";
// Fragmented -- hard to copy for debugging, easy to miss trailing spaces
```

### Pass
```php
$sql = <<<SQL
SELECT o.order_id, o.customer_id, c.name
FROM sales_order o
JOIN customer_entity c ON c.entity_id = o.customer_id
WHERE o.status = :status
SQL;
// Single heredoc -- copy-paste ready, no trailing-space bugs
```

### Enforcement
Code review.

### Rationale
Fragmented SQL is harder to read, copy for debugging, and audit for security issues. Missing trailing spaces in concatenated fragments is a common source of syntax errors.

<!-- RULE END: DB-SQL-002 -->
---

<!-- RULE START: DB-SQL-003 -->
## Rule DB-SQL-003

**Domain**: Database / SQL
**Severity**: Medium
**Scope**: Entity
**Mandatory**: false

### Trigger
When writing any SQL query longer than one line.

### Statement
Format SQL vertically. Each JOIN on its own line with ON condition. Column lists comma-separated per line. WHERE conditions on separate lines with AND/OR alignment.

### Violation
```php
$sql = "SELECT o.order_id, o.customer_id, c.name FROM sales_order o JOIN customer_entity c ON c.entity_id = o.customer_id LEFT JOIN customer_address_entity a ON a.parent_id = c.entity_id WHERE o.status = :status AND o.created_at > :startDate ORDER BY o.created_at DESC";
```

### Pass
```php
$sql = <<<SQL
SELECT
    o.order_id,
    o.customer_id,
    c.name
FROM sales_order o
JOIN customer_entity c ON c.entity_id = o.customer_id
LEFT JOIN customer_address_entity a ON a.parent_id = c.entity_id
WHERE o.status = :status
    AND o.created_at > :startDate
ORDER BY o.created_at DESC
SQL;
```

### Enforcement
Code review.

### Rationale
Readable SQL is easier to review, debug, and maintain. Vertical formatting makes complex queries scannable and diff-friendly.

<!-- RULE END: DB-SQL-003 -->
