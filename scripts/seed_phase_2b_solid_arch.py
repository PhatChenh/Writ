"""Phase 2B of the public rulebook expansion: SOLID + Architecture.

Seeds 24 new SOLID-* and ARCH-* rules into the graph (0 mandatory) and renames
3 legacy ARCH-* rules to align with public-rulebook IDs:

  ARCH-ORG-001 -> ARCH-LAYER-001  (layer boundaries enforced)
  ARCH-EXT-001 -> SOLID-OCP-001   (extension via composition)
  ARCH-DI-001  -> SOLID-DIP-002   (constructor injection of abstractions)

ARCH-COMP-001 (inheritance depth <= 2) and ARCH-PE-* / ARCH-RES-*
project-specific rules are retained as Writ extensions.

Idempotent. Re-runs MERGE existing rules with the same rule_id.

Per the public rulebook source: out-of-the-box-rules.md sections 4, 5.
"""

from __future__ import annotations

import asyncio
from datetime import date

from writ.config import get_falkordb_path, get_falkordb_graph, get_falkordb_module, get_redis_bin
from writ.graph.db import FalkorDBLiteConnection

TODAY = date.today().isoformat()


def _rule(
    rid: str,
    domain: str,
    severity: str,
    scope: str,
    trigger: str,
    statement: str,
    violation: str,
    pass_example: str,
    enforcement: str,
    rationale: str,
    source_section: str,
) -> dict:
    return {
        "rule_id": rid,
        "domain": domain,
        "severity": severity,
        "scope": scope,
        "trigger": trigger,
        "statement": statement,
        "violation": violation,
        "pass_example": pass_example,
        "enforcement": enforcement,
        "rationale": rationale,
        "mandatory": False,
        "mechanical_enforcement_path": None,
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


# ============================================================================
# SOLID (12 rules)
# ============================================================================
SOLID_RULES = [
    _rule("SOLID-SRP-001", "architecture", "high", "component",
        "When designing or modifying a class.",
        "Each class has exactly one reason to change. A class that handles both HTTP parsing and business logic, both persistence and validation, both presentation and computation, is split.",
        "```python\nclass UserController:\n    def signup(self, request):\n        # Validates input, hashes password, saves to DB, sends welcome email,\n        # logs analytics, returns rendered HTML.\n        ...\n```",
        "```python\nclass UserController:\n    def signup(self, request):\n        payload = SignupInput(**request.json)\n        user = user_service.create(payload)\n        return render(user)\n\nclass UserService:\n    def create(self, payload):\n        ...\n```",
        "Code review.",
        "A class that knows about too many concerns changes for too many reasons. Single-responsibility classes evolve independently.",
        "4"),
    _rule("SOLID-SRP-002", "architecture", "medium", "component",
        "When implementing a route handler, controller method, or HTTP endpoint.",
        "Controllers and handlers delegate to a service layer. Business logic does not live in route functions. The handler's job: parse input, call a service, format output.",
        "```python\n@app.post('/orders')\ndef create_order(payload):\n    if payload.amount > customer.balance:\n        raise InsufficientFunds()\n    db.session.add(Order(...))\n    db.session.commit()\n    stripe.charge(...)\n    return jsonify({...})\n```",
        "```python\n@app.post('/orders')\ndef create_order(payload):\n    order = order_service.place(current_user, payload)\n    return jsonify(OrderResponse.from_orm(order).dict())\n```",
        "Code review.",
        "Business logic in controllers is untestable without HTTP plumbing and is invisible to non-HTTP callers (jobs, CLIs).",
        "4"),
    _rule("SOLID-SRP-003", "architecture", "medium", "component",
        "When organizing data access alongside business rules.",
        "Data access is separated from business rules via a repository or DAO layer. Services depend on repository interfaces; ORM queries are not inlined into business logic.",
        "```python\nclass OrderService:\n    def fulfill(self, order_id):\n        order = Order.query.filter_by(id=order_id).first()  # direct ORM\n        order.status = 'fulfilled'\n        db.session.commit()\n```",
        "```python\nclass OrderService:\n    def __init__(self, orders: OrderRepository):\n        self.orders = orders\n    def fulfill(self, order_id):\n        order = self.orders.get(order_id)\n        order.mark_fulfilled()\n        self.orders.save(order)\n```",
        "Code review.",
        "Mixing query syntax into services couples the service to an ORM. The repository layer is the seam where the storage technology can change.",
        "4"),
    _rule("SOLID-OCP-001", "architecture", "high", "component",
        "When extending behavior of existing modules, framework classes, or third-party libraries.",
        "Behavior is extended via composition, strategy, plugin/extension hooks, or framework-native mechanisms (decorators, observers, middleware). Modifying existing code to support a new variant is a violation; new variants are added without changing the old code path.",
        "```python\nclass OrderPricer:\n    def price(self, order):\n        if order.customer.tier == 'enterprise':\n            return self._enterprise_pricing(order)\n        elif order.customer.tier == 'startup':\n            return self._startup_pricing(order)\n        elif order.customer.tier == 'partner':\n            return self._partner_pricing(order)  # added this week\n        return self._standard_pricing(order)\n```",
        "```python\nclass OrderPricer:\n    def __init__(self, strategies: dict[str, PricingStrategy]):\n        self.strategies = strategies\n    def price(self, order):\n        strategy = self.strategies.get(order.customer.tier, self.strategies['standard'])\n        return strategy.price(order)\n```",
        "Code review. Framework-specific extension hooks (Magento plugins, Django middleware, FastAPI dependencies, Spring AOP).",
        "Closed-for-modification is the structural defense against regression: existing code paths keep working when new variants ship.",
        "4"),
    _rule("SOLID-OCP-002", "architecture", "medium", "component",
        "When writing a switch/match or chain of if/elif branches on a type discriminator.",
        "Switch/match on a type with more than 3 branches is replaced by polymorphism (subclass dispatch, strategy registry, visitor pattern) when the type set is extensible. Chains that hard-code every type prevent additions without editing every chain.",
        "```python\ndef render(event):\n    if event.kind == 'signup':\n        return render_signup(event)\n    elif event.kind == 'login':\n        return render_login(event)\n    elif event.kind == 'purchase':\n        return render_purchase(event)\n    elif event.kind == 'refund':  # added today\n        return render_refund(event)\n    # ... new event types ripple to every dispatcher\n```",
        "```python\nclass Event(Protocol):\n    def render(self): ...\n# Each event subclass implements its own render(). Dispatcher: event.render().\n```",
        "Code review.",
        "Long type switches mean each new type requires editing every dispatcher. Polymorphism puts the type-specific logic with the type.",
        "4"),
    _rule("SOLID-LSP-001", "architecture", "high", "component",
        "When implementing a subclass or interface implementation.",
        "Subclasses or implementations do not weaken preconditions (require less than the parent) or strengthen postconditions (return less than the parent guarantees). A consumer of the parent type works correctly with any subclass.",
        "```python\nclass List:\n    def add(self, item):  # no precondition stated\n        ...\nclass SortedList(List):\n    def add(self, item):\n        if not isinstance(item, Comparable):\n            raise TypeError()  # strengthens precondition; LSP violation\n        ...\n```",
        "```python\nclass List:\n    def add(self, item):\n        ...\nclass SortedList(List):\n    def add(self, item: Comparable):  # precondition reflected in type\n        ...\n# Or: SortedList does not extend List.\n```",
        "Code review.",
        "LSP violations turn polymorphism into a runtime trap: code that worked against the parent type breaks unpredictably with a subclass.",
        "4"),
    _rule("SOLID-LSP-002", "architecture", "medium", "component",
        "When overriding a method in a subclass.",
        "Overridden methods maintain the parent's return type contract. A method declared to return `User` does not return `None` in the override. A method declared to return non-empty list does not return `[]`. The contract is documented or implied; the override respects it.",
        "```python\nclass Repo:\n    def get(self, id) -> User: ...\nclass CachedRepo(Repo):\n    def get(self, id) -> User | None:  # weaker -- breaks callers\n        ...\n```",
        "```python\nclass Repo:\n    def get(self, id) -> User | None: ...\nclass CachedRepo(Repo):\n    def get(self, id) -> User | None: ...\n```",
        "Type checker (mypy strict, pyright). Code review.",
        "Return-type drift in overrides breaks every caller that assumed the parent's contract.",
        "4"),
    _rule("SOLID-ISP-001", "architecture", "medium", "component",
        "When defining an interface, protocol, or abstract base class.",
        "Interfaces contain only methods that all their consumers use. A 'fat interface' that some consumers ignore signals the interface should be split into smaller cohesive interfaces.",
        "```python\nclass Storage(Protocol):\n    def read(self, key): ...\n    def write(self, key, value): ...\n    def delete(self, key): ...\n    def stream(self, key): ...\n    def list(self, prefix): ...\n# A read-only consumer (config loader) must depend on all of these.\n```",
        "```python\nclass ReadStorage(Protocol):\n    def read(self, key): ...\nclass WriteStorage(ReadStorage):\n    def write(self, key, value): ...\n    def delete(self, key): ...\n# Read-only consumers depend on ReadStorage; write consumers on WriteStorage.\n```",
        "Code review.",
        "Fat interfaces force consumers to depend on methods they do not use, which propagates breaking changes through every implementation when an unrelated method changes.",
        "4"),
    _rule("SOLID-ISP-002", "architecture", "medium", "component",
        "When implementing an interface or abstract base class.",
        "If an implementation raises NotImplementedError for some interface methods, that signals the interface should be split. The pattern indicates a fat-interface design problem (overlaps with SOLID-ISP-001).",
        "```python\nclass NotificationChannel(ABC):\n    @abstractmethod\n    def send_email(self, to, body): ...\n    @abstractmethod\n    def send_sms(self, to, body): ...\n\nclass EmailOnly(NotificationChannel):\n    def send_email(self, to, body): ...\n    def send_sms(self, to, body):\n        raise NotImplementedError()  # interface mismatch\n```",
        "```python\nclass EmailChannel(Protocol):\n    def send_email(self, to, body): ...\nclass SMSChannel(Protocol):\n    def send_sms(self, to, body): ...\n```",
        "Code review.",
        "NotImplementedError in a production class is a runtime time bomb. The structural defense is a narrower interface.",
        "4"),
    _rule("SOLID-DIP-001", "architecture", "high", "component",
        "When a high-level module (service, business logic) depends on a low-level module (database driver, HTTP client, file system).",
        "High-level modules depend on abstractions (protocols, interfaces, ABCs), not on concrete implementations. The abstraction is owned by the high-level module; the implementation conforms to it.",
        "```python\nclass OrderService:\n    def __init__(self):\n        self.db = psycopg2.connect(...)  # concrete driver\n        self.payments = StripeClient()    # concrete vendor\n```",
        "```python\nclass OrderRepository(Protocol):\n    def save(self, order): ...\nclass PaymentGateway(Protocol):\n    def charge(self, amount, customer): ...\nclass OrderService:\n    def __init__(self, repo: OrderRepository, payments: PaymentGateway):\n        self.repo, self.payments = repo, payments\n```",
        "Code review.",
        "Concrete dependencies make business logic untestable, untransferable, and tightly coupled to vendor decisions. Abstractions invert the dependency.",
        "4"),
    _rule("SOLID-DIP-002", "architecture", "critical", "component",
        "When constructing a class that requires collaborators (services, repositories, gateways, clients).",
        "Dependencies are received via constructor injection, typed to an interface or protocol. Direct instantiation (`new ConcreteClass()`) is permitted only for DTOs, value objects, and known framework types. Application services receive their dependencies; they do not construct them.",
        "```python\nclass OrderService:\n    def __init__(self):\n        self.stripe = StripeClient()   # constructs concrete\n        self.email = SendgridClient()\n```",
        "```python\nclass OrderService:\n    def __init__(self, payments: PaymentGateway, email: EmailGateway):\n        self.payments = payments\n        self.email = email\n```",
        "Code review. DI container config (Spring, Magento DI, Symfony DI, Dagger).",
        "Injection makes dependencies visible and replaceable. Direct construction hides them and freezes substitutability.",
        "4"),
    _rule("SOLID-DIP-003", "architecture", "medium", "component",
        "When designing service-layer / domain-layer code.",
        "Framework-specific types do not leak into domain logic. Django QuerySets, Express Request objects, SQLAlchemy Session, ORM model classes are not consumed by domain services directly; they are adapted at the boundary.",
        "```python\nclass OrderService:\n    def place(self, request: flask.Request):  # framework leaks in\n        ...\n```",
        "```python\nclass OrderService:\n    def place(self, payload: OrderInput, actor: User):\n        ...\n# The controller adapts the framework Request -> OrderInput + actor.\n```",
        "Code review.",
        "Framework types in domain code make every domain method untestable without the framework and prevent reuse from non-framework callers (background jobs, CLI).",
        "4"),
]


# ============================================================================
# Architecture & Design Patterns (15 rules)
# ============================================================================
ARCH_RULES = [
    _rule("ARCH-LAYER-001", "architecture", "high", "component",
        "When designing or modifying multi-layer applications (presentation, service, data-access, infrastructure).",
        "Layer boundaries are enforced: presentation calls service, service calls data-access. Layers are not skipped (no controller talking directly to the ORM, no data-access calling the service layer). The dependency graph flows in one direction.",
        "```python\n@app.route('/orders')\ndef list_orders():\n    return Order.query.filter_by(user_id=current_user.id).all()\n# Presentation skipped service and data-access layers.\n```",
        "```python\n@app.route('/orders')\ndef list_orders():\n    return order_service.list_for(current_user)\n\nclass OrderService:\n    def list_for(self, user):\n        return self.orders.by_user(user.id)\n```",
        "Code review. Module-import linting (eslint import/no-restricted-paths, pylint).",
        "Layer skipping defeats the purpose of layers: business logic ends up duplicated across controllers, data access ends up scattered, and testing each layer in isolation becomes impossible.",
        "5"),
    _rule("ARCH-LAYER-002", "architecture", "medium", "component",
        "When defining domain models (entities, value objects, aggregates).",
        "Domain models have no framework imports. Django ORM Model, SQLAlchemy Base, Spring @Entity, Active Record annotations are framework concerns; the domain model is plain data + behavior. Framework types are converted at boundaries.",
        "```python\nfrom django.db import models\nclass User(models.Model):  # framework-coupled\n    name = models.CharField(max_length=255)\n    def is_eligible(self): ...\n```",
        "```python\n@dataclass\nclass User:\n    id: UserId\n    name: str\n    def is_eligible(self) -> bool: ...\n# UserRepository converts Django Model <-> User dataclass at boundary.\n```",
        "Code review.",
        "Framework-coupled domain models drag the framework into every test, every reuse, and every refactor. Plain models are portable.",
        "5"),
    _rule("ARCH-BOUNDARY-001", "architecture", "high", "component",
        "When integrating with external services (HTTP APIs, third-party SDKs, message queues, cloud services).",
        "External service calls are wrapped in an adapter/client class. Business logic invokes the adapter, never the raw HTTP/SDK call. The adapter centralizes retries, timeouts, error mapping, and observability.",
        "```python\nclass OrderService:\n    def charge(self, order):\n        resp = requests.post('https://api.stripe.com/v1/charges', ...)  # raw\n```",
        "```python\nclass PaymentGateway:\n    def charge(self, customer, amount): ...\nclass OrderService:\n    def charge(self, order):\n        return self.payments.charge(order.customer, order.amount)\n```",
        "Code review.",
        "Raw external calls in business code couple every caller to the vendor's API shape, error model, and retry semantics. Adapter classes isolate that surface.",
        "5"),
    _rule("ARCH-BOUNDARY-002", "architecture", "medium", "component",
        "When using a third-party library across multiple modules.",
        "Third-party library usage is concentrated in adapter modules. Imports of the library are confined; the rest of the codebase imports the adapter. Swapping the library affects one module, not the codebase.",
        "```python\n# 20 modules import requests directly; switching to httpx is a 20-file change.\n```",
        "```python\n# infra/http.py imports requests/httpx; everyone else imports infra.http.\n```",
        "Code review. Import linting can restrict imports of specific libraries to specific modules.",
        "Concentrated library use trades a one-line import for the ability to migrate the library later. Scattered imports trade short-term convenience for long-term lock-in.",
        "5"),
    _rule("ARCH-EVENT-001", "architecture", "medium", "component",
        "When two bounded contexts (subdomains, modules with separate responsibilities) need to communicate.",
        "Cross-domain communication uses events or messages, not direct method calls between bounded contexts. The sender publishes; the receiver subscribes. Coupling is one-way: events carry data, not references to receivers.",
        "```python\n# orders module:\nfrom inventory import reserve_items  # direct cross-context call\nreserve_items(order.items)\n```",
        "```python\n# orders module:\nevent_bus.publish(OrderPlaced(order_id=order.id, items=order.items))\n# inventory module subscribes to OrderPlaced and reserves.\n```",
        "Code review.",
        "Direct calls tangle bounded contexts: changes in inventory ripple to orders. Events keep contexts independently deployable and testable.",
        "5"),
    _rule("ARCH-DTO-001", "architecture", "medium", "component",
        "When passing data between layers (HTTP <-> service, service <-> data access, service <-> external).",
        "Data carriers are explicit DTOs (dataclasses, Pydantic models, Zod schemas, TypeScript types). Raw dicts passed through layers are violations: they lose type information, schema validation, and IDE support.",
        "```python\ndef create_order(data: dict):\n    user = data['user']\n    items = data['items']\n    # data shape is implicit; callers must know.\n```",
        "```python\n@dataclass\nclass CreateOrderInput:\n    user: UserRef\n    items: list[OrderItem]\n\ndef create_order(input: CreateOrderInput): ...\n```",
        "Code review.",
        "Raw dicts hide the contract between layers and propagate typos as runtime errors. DTOs make the contract explicit and machine-checkable.",
        "5"),
    _rule("ARCH-MIGRATION-001", "architecture", "high", "component",
        "When changing the database schema.",
        "Schema changes use versioned migrations (Alembic, Django migrations, Flyway, Liquibase, Rails migrations, Doctrine migrations). Manual DDL applied to production environments outside the migration system is a violation.",
        "```\n# DBA SSH-es into prod and runs `ALTER TABLE users ADD COLUMN ...`\n# No record in version control; schema and code drift.\n```",
        "```python\n# alembic/versions/2026_05_10_add_user_avatar.py\ndef upgrade(): op.add_column('users', sa.Column('avatar_url', sa.String()))\ndef downgrade(): op.drop_column('users', 'avatar_url')\n```",
        "CI gate that migrations run cleanly against a fresh database. Code review.",
        "Versioned migrations make schema state reproducible, reviewable, and rollback-able. Manual DDL turns the schema into a folk artifact.",
        "5"),
    _rule("ARCH-MIGRATION-002", "architecture", "medium", "component",
        "When writing a database migration.",
        "Migrations are reversible: both up and down are implemented. Irreversible changes (DROP COLUMN with data, DROP TABLE) are documented with the rationale in the migration file. Reversibility supports staged rollouts and incident rollback.",
        "```python\ndef upgrade(): op.drop_column('users', 'legacy_field')\ndef downgrade(): pass  # no way to recover the dropped data\n```",
        "```python\n# Step 1 migration: stop writing legacy_field; deploy.\n# Step 2 migration (later): drop column once confirmed unused.\n# Each step independently reversible.\n```",
        "Code review.",
        "Reversible migrations preserve the option to roll back without data loss. Irreversible changes are sometimes necessary but are explicit decisions.",
        "5"),
    _rule("ARCH-STATE-001", "architecture", "high", "component",
        "When modifying shared mutable state (module-level variables, singletons, in-memory caches, class-level state) from multi-threaded or async code.",
        "Shared mutable state is protected by explicit synchronization (locks, mutexes, atomic operations) or replaced by message-passing / immutable updates. Unguarded global mutation in concurrent code is a violation.",
        "```python\nCACHE = {}\ndef get_or_compute(key):\n    if key not in CACHE:\n        CACHE[key] = expensive(key)\n    return CACHE[key]\n# Two threads racing on the same key both run expensive().\n```",
        "```python\nimport threading\nCACHE: dict = {}\nLOCK = threading.Lock()\ndef get_or_compute(key):\n    with LOCK:\n        if key not in CACHE:\n            CACHE[key] = expensive(key)\n        return CACHE[key]\n# Or use functools.lru_cache (thread-safe).\n```",
        "Code review.",
        "Unguarded concurrent mutation produces nondeterministic bugs that are nearly impossible to reproduce. Synchronization or immutability removes the entire bug class.",
        "5"),
    _rule("ARCH-STATE-002", "architecture", "medium", "component",
        "When introducing state management for application UI.",
        "A single state-management pattern (Redux, Zustand, MobX, React Context, Vuex, Pinia, NgRx) is used per project. Mixing two patterns scatters state across incompatible mental models. The choice is documented and consistent.",
        "```\n# Some components read from Redux, others from Context, others from\n# local useState mirroring shared state. Bugs hide between the mirrors.\n```",
        "```\n# Project chose Zustand. All shared state lives in Zustand stores.\n# Local component state is allowed only for non-shared concerns.\n```",
        "Code review. ESLint rule restricting imports of competing libraries.",
        "Mixed state-management produces state that lives in multiple places at once and drifts. One pattern is the structural defense.",
        "5"),
    _rule("ARCH-IDEMPOTENT-001", "architecture", "high", "component",
        "When implementing a write endpoint that creates resources or triggers side effects (charges, emails, notifications).",
        "Write endpoints are idempotent: replaying the same request produces the same result, not duplicate side effects. Idempotency is implemented via an idempotency key supplied by the client and stored server-side until expiration.",
        "```python\n@app.post('/charge')\ndef charge():\n    stripe.charge(amount=request.json['amount'], customer=request.json['customer'])\n    return ok()\n# Network retry charges the customer twice.\n```",
        "```python\n@app.post('/charge')\ndef charge():\n    idem_key = request.headers['Idempotency-Key']\n    existing = IdempotencyRecord.find(idem_key)\n    if existing:\n        return existing.response\n    charge_id = stripe.charge(...)\n    IdempotencyRecord.save(idem_key, charge_id)\n    return charge_id\n```",
        "Code review.",
        "Retries are universal in distributed systems. Idempotency keys turn 'safe to retry' from hope into guarantee.",
        "5"),
    _rule("ARCH-ASYNC-001", "architecture", "high", "component",
        "When calling an async function (Python `async def`, Node `async`/`Promise`, Rust `async fn`).",
        "Async function results are awaited at all call sites. Fire-and-forget invocations (unawaited Promises, dropped coroutines, ignored futures) are forbidden unless explicitly justified and tracked (background task registry).",
        "```javascript\nasync function sendEmail(to) { ... }\n// Caller:\nsendEmail(user.email);  // unhandled Promise; failures invisible\n```",
        "```javascript\nawait sendEmail(user.email);\n// Or, when truly fire-and-forget:\nsendEmail(user.email).catch(err => logger.error('email failed', err));\n// Or, register with a task supervisor:\ntaskSupervisor.spawn(() => sendEmail(user.email));\n```",
        "Linter rule (eslint @typescript-eslint/no-floating-promises, ruff RUF006 / asyncio).",
        "Floating async work loses errors and timing. The await (or supervised spawn) is the structural defense.",
        "5"),
    _rule("ARCH-ASYNC-002", "architecture", "medium", "component",
        "When writing code that runs inside an async event loop (Python asyncio, Node, Tokio).",
        "Blocking calls inside the event loop are forbidden: no synchronous I/O, no `time.sleep` (use `asyncio.sleep`), no CPU-bound loops in the main coroutine. CPU-bound work runs in an executor; blocking I/O runs in a thread pool.",
        "```python\nasync def process(item):\n    response = requests.get(item.url)  # sync HTTP in async fn -- blocks loop\n    time.sleep(1)                       # blocks loop\n```",
        "```python\nasync def process(item):\n    response = await httpx.AsyncClient().get(item.url)\n    await asyncio.sleep(1)\n# CPU-bound: await loop.run_in_executor(None, cpu_heavy, item)\n```",
        "Linter rule (asyncio-blocker-style check). Code review.",
        "A single blocking call inside the event loop stalls every concurrent task. Async I/O preserves the concurrency model.",
        "5"),
    _rule("ARCH-ENV-001", "architecture", "medium", "component",
        "When implementing behavior that should differ across environments (dev, staging, prod).",
        "Environment-specific behavior is controlled by configuration values, not by `if env == 'prod'` branches in code. Per-environment config files / env vars carry the differences; code reads config, not the environment name.",
        "```python\nif os.environ['ENV'] == 'prod':\n    cache_ttl = 3600\nelse:\n    cache_ttl = 60\n```",
        "```python\ncache_ttl = int(os.environ['CACHE_TTL_SECONDS'])\n# Different .env / config / secret manager per environment.\n```",
        "Code review.",
        "Env-name branches couple code to a specific environment topology. Config-driven behavior travels: the same code runs anywhere if the config is right.",
        "5"),
    _rule("ARCH-FEATURE-001", "architecture", "medium", "component",
        "When introducing or removing a feature flag.",
        "Feature flags have an explicit expiration date and a documented cleanup plan (who removes the flag, when, and what the cleanup looks like). Permanent feature flags are violations: they accumulate as conditional spaghetti.",
        "```python\n# flags.is_enabled('new_billing_flow')  # added 2 years ago, never removed\n```",
        "```python\n# flags.is_enabled('new_billing_flow')  # owner: @alice; sunset: 2026-08-01\n# After sunset: flag is removed, both branches converged on the winner.\n```",
        "Flag registry with TTL/owner fields. PR template requires sunset date.",
        "Eternal feature flags accumulate as branches that never converge. Sunset dates create momentum to remove them.",
        "5"),
]


RULES = SOLID_RULES + ARCH_RULES


async def main() -> None:
    db = FalkorDBLiteConnection(
        get_falkordb_path(), get_falkordb_graph(),
        get_falkordb_module(), get_redis_bin(),
    )
    try:
        renames = [
            ("ARCH-ORG-001", "ARCH-LAYER-001"),
            ("ARCH-EXT-001", "SOLID-OCP-001"),
            ("ARCH-DI-001",  "SOLID-DIP-002"),
        ]
        for old, new in renames:
            db._execute_query("MATCH (r:Rule {rule_id: $old}) DETACH DELETE r", old=old)
            print(f"DELETED {old:20s} (absorbed into {new})")

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
                print(f"UPDATED {rule['rule_id']:30s} {rule['severity']}")
            else:
                created += 1
                print(f"CREATED {rule['rule_id']:30s} {rule['severity']}")

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
