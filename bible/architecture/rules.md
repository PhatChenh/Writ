<!-- RULE START: ARCH-ASYNC-001 -->
## Rule ARCH-ASYNC-001

**Domain**: architecture
**Severity**: High
**Scope**: Component
**Mandatory**: false

### Trigger
When calling an async function (Python `async def`, Node `async`/`Promise`, Rust `async fn`).

### Statement
Async function results are awaited at all call sites. Fire-and-forget invocations (unawaited Promises, dropped coroutines, ignored futures) are forbidden unless explicitly justified and tracked (background task registry).

### Violation
```javascript
async function sendEmail(to) { ... }
// Caller:
sendEmail(user.email);  // unhandled Promise; failures invisible
```

### Pass
```javascript
await sendEmail(user.email);
// Or, when truly fire-and-forget:
sendEmail(user.email).catch(err => logger.error('email failed', err));
// Or, register with a task supervisor:
taskSupervisor.spawn(() => sendEmail(user.email));
```

### Enforcement
Linter rule (eslint @typescript-eslint/no-floating-promises, ruff RUF006 / asyncio).

### Rationale
Floating async work loses errors and timing. The await (or supervised spawn) is the structural defense.

<!-- RULE END: ARCH-ASYNC-001 -->
---

<!-- RULE START: ARCH-ASYNC-002 -->
## Rule ARCH-ASYNC-002

**Domain**: architecture
**Severity**: Medium
**Scope**: Component
**Mandatory**: false

### Trigger
When writing code that runs inside an async event loop (Python asyncio, Node, Tokio).

### Statement
Blocking calls inside the event loop are forbidden: no synchronous I/O, no `time.sleep` (use `asyncio.sleep`), no CPU-bound loops in the main coroutine. CPU-bound work runs in an executor; blocking I/O runs in a thread pool.

### Violation
```python
async def process(item):
    response = requests.get(item.url)  # sync HTTP in async fn -- blocks loop
    time.sleep(1)                       # blocks loop
```

### Pass
```python
async def process(item):
    response = await httpx.AsyncClient().get(item.url)
    await asyncio.sleep(1)
# CPU-bound: await loop.run_in_executor(None, cpu_heavy, item)
```

### Enforcement
Linter rule (asyncio-blocker-style check). Code review.

### Rationale
A single blocking call inside the event loop stalls every concurrent task. Async I/O preserves the concurrency model.

<!-- RULE END: ARCH-ASYNC-002 -->
---

<!-- RULE START: ARCH-BOUNDARY-001 -->
## Rule ARCH-BOUNDARY-001

**Domain**: architecture
**Severity**: High
**Scope**: Component
**Mandatory**: false

### Trigger
When integrating with external services (HTTP APIs, third-party SDKs, message queues, cloud services).

### Statement
External service calls are wrapped in an adapter/client class. Business logic invokes the adapter, never the raw HTTP/SDK call. The adapter centralizes retries, timeouts, error mapping, and observability.

**Swap-seam scope.** Not every external dependency is a swap seam. Declare explicitly which dependencies are swap seams (e.g. payment gateway, AI provider, email sender, object store); foundational dependencies — the application framework, the ORM, a rendering/canvas library — are NOT swap seams and must not be hidden behind an adapter. Over-abstracting foundational dependencies adds indirection with no swap benefit.

**No automatic silent failover.** When an adapter call fails, surface a clean error to the caller and let it retry or re-pick; never silently route to a secondary provider inside the adapter. Silent failover hides failures, breaks least-surprise, and makes error budgets and cost/quality attribution untrackable. Retry and provider re-pick are the caller's decision.

### Violation
```python
class OrderService:
    def charge(self, order):
        resp = requests.post('https://api.stripe.com/v1/charges', ...)  # raw SDK in business code
```
```python
class PaymentAdapter:
    def charge(self, order):
        try:    return self._stripe.charge(...)
        except Exception:
            return self._paypal.charge(...)   # silent automatic failover to a second provider
```

### Pass
```python
class PaymentGateway:
    def charge(self, customer, amount): ...
class OrderService:
    def charge(self, order):
        return self.payments.charge(order.customer, order.amount)
```
```python
class PaymentAdapter:
    def charge(self, order):
        try:    return self._provider.charge(...)
        except ProviderError as e:
            raise ServiceError(f"payment failed: {e}")  # surface clean error; caller retries / re-picks
```

### Enforcement
Code review. Import linting can restrict raw provider-SDK imports to designated adapter modules.

### Rationale
Raw external calls in business code couple every caller to the vendor's API shape, error model, and retry semantics. Adapter classes isolate that surface. Declaring swap seams explicitly prevents the opposite error — abstracting everything (framework, ORM) for no payoff. Banning silent automatic failover keeps failure observable: the alert, the error budget, and the retry decision belong to the caller, not hidden inside the adapter.

<!-- RULE END: ARCH-BOUNDARY-001 -->
---

<!-- RULE START: ARCH-BOUNDARY-002 -->
## Rule ARCH-BOUNDARY-002

**Domain**: architecture
**Severity**: Medium
**Scope**: Component
**Mandatory**: false

### Trigger
When using a third-party library across multiple modules.

### Statement
Third-party library usage is concentrated in adapter modules. Imports of the library are confined; the rest of the codebase imports the adapter. Swapping the library affects one module, not the codebase.

### Violation
```python
# 20 modules import requests directly; switching to httpx is a 20-file change.
```

### Pass
```python
# infra/http.py imports requests/httpx; everyone else imports infra.http.
```

### Enforcement
Code review. Import linting can restrict imports of specific libraries to specific modules.

### Rationale
Concentrated library use trades a one-line import for the ability to migrate the library later. Scattered imports trade short-term convenience for long-term lock-in.

<!-- RULE END: ARCH-BOUNDARY-002 -->
---

<!-- RULE START: ARCH-DTO-001 -->
## Rule ARCH-DTO-001

**Domain**: architecture
**Severity**: Medium
**Scope**: Component
**Mandatory**: false

### Trigger
When passing data between layers (HTTP <-> service, service <-> data access, service <-> external).

### Statement
Data carriers are explicit DTOs (dataclasses, Pydantic models, Zod schemas, TypeScript types). Raw dicts passed through layers are violations: they lose type information, schema validation, and IDE support.

### Violation
```python
def create_order(data: dict):
    user = data['user']
    items = data['items']
    # data shape is implicit; callers must know.
```

### Pass
```python
@dataclass
class CreateOrderInput:
    user: UserRef
    items: list[OrderItem]

def create_order(input: CreateOrderInput): ...
```

### Enforcement
Code review.

### Rationale
Raw dicts hide the contract between layers and propagate typos as runtime errors. DTOs make the contract explicit and machine-checkable.

<!-- RULE END: ARCH-DTO-001 -->
---

<!-- RULE START: ARCH-ENV-001 -->
## Rule ARCH-ENV-001

**Domain**: architecture
**Severity**: Medium
**Scope**: Component
**Mandatory**: false

### Trigger
When implementing behavior that should differ across environments (dev, staging, prod).

### Statement
Environment-specific behavior is controlled by configuration values, not by `if env == 'prod'` branches in code. Per-environment config files / env vars carry the differences; code reads config, not the environment name.

### Violation
```python
if os.environ['ENV'] == 'prod':
    cache_ttl = 3600
else:
    cache_ttl = 60
```

### Pass
```python
cache_ttl = int(os.environ['CACHE_TTL_SECONDS'])
# Different .env / config / secret manager per environment.
```

### Enforcement
Code review.

### Rationale
Env-name branches couple code to a specific environment topology. Config-driven behavior travels: the same code runs anywhere if the config is right.

<!-- RULE END: ARCH-ENV-001 -->
---

<!-- RULE START: ARCH-EVENT-001 -->
## Rule ARCH-EVENT-001

**Domain**: architecture
**Severity**: Medium
**Scope**: Component
**Mandatory**: false

### Trigger
When two bounded contexts (subdomains, modules with separate responsibilities) need to communicate.

### Statement
Cross-domain communication uses events or messages, not direct method calls between bounded contexts. The sender publishes; the receiver subscribes. Coupling is one-way: events carry data, not references to receivers.

### Violation
```python
# orders module:
from inventory import reserve_items  # direct cross-context call
reserve_items(order.items)
```

### Pass
```python
# orders module:
event_bus.publish(OrderPlaced(order_id=order.id, items=order.items))
# inventory module subscribes to OrderPlaced and reserves.
```

### Enforcement
Code review.

### Rationale
Direct calls tangle bounded contexts: changes in inventory ripple to orders. Events keep contexts independently deployable and testable.

<!-- RULE END: ARCH-EVENT-001 -->
---

<!-- RULE START: ARCH-FEATURE-001 -->
## Rule ARCH-FEATURE-001

**Domain**: architecture
**Severity**: Medium
**Scope**: Component
**Mandatory**: false

### Trigger
When introducing or removing a feature flag.

### Statement
Feature flags have an explicit expiration date and a documented cleanup plan (who removes the flag, when, and what the cleanup looks like). Permanent feature flags are violations: they accumulate as conditional spaghetti.

### Violation
```python
# flags.is_enabled('new_billing_flow')  # added 2 years ago, never removed
```

### Pass
```python
# flags.is_enabled('new_billing_flow')  # owner: @alice; sunset: 2026-08-01
# After sunset: flag is removed, both branches converged on the winner.
```

### Enforcement
Flag registry with TTL/owner fields. PR template requires sunset date.

### Rationale
Eternal feature flags accumulate as branches that never converge. Sunset dates create momentum to remove them.

<!-- RULE END: ARCH-FEATURE-001 -->
---

<!-- RULE START: ARCH-IDEMPOTENT-001 -->
## Rule ARCH-IDEMPOTENT-001

**Domain**: architecture
**Severity**: High
**Scope**: Component
**Mandatory**: false

### Trigger
When implementing a write endpoint that creates resources or triggers side effects (charges, emails, notifications).

### Statement
Write endpoints are idempotent: replaying the same request produces the same result, not duplicate side effects. Idempotency is implemented via an idempotency key supplied by the client and stored server-side until expiration.

### Violation
```python
@app.post('/charge')
def charge():
    stripe.charge(amount=request.json['amount'], customer=request.json['customer'])
    return ok()
# Network retry charges the customer twice.
```

### Pass
```python
@app.post('/charge')
def charge():
    idem_key = request.headers['Idempotency-Key']
    existing = IdempotencyRecord.find(idem_key)
    if existing:
        return existing.response
    charge_id = stripe.charge(...)
    IdempotencyRecord.save(idem_key, charge_id)
    return charge_id
```

### Enforcement
Code review.

### Rationale
Retries are universal in distributed systems. Idempotency keys turn 'safe to retry' from hope into guarantee.

<!-- RULE END: ARCH-IDEMPOTENT-001 -->
---

<!-- RULE START: ARCH-LAYER-001 -->
## Rule ARCH-LAYER-001

**Domain**: architecture
**Severity**: High
**Scope**: Component
**Mandatory**: false

### Trigger
When designing or modifying multi-layer applications (presentation, service, data-access, infrastructure).

### Statement
Layer boundaries are enforced: presentation calls service, service calls data-access. Layers are not skipped (no controller talking directly to the ORM, no data-access calling the service layer). The dependency graph flows in one direction.

### Violation
```python
@app.route('/orders')
def list_orders():
    return Order.query.filter_by(user_id=current_user.id).all()
# Presentation skipped service and data-access layers.
```

### Pass
```python
@app.route('/orders')
def list_orders():
    return order_service.list_for(current_user)

class OrderService:
    def list_for(self, user):
        return self.orders.by_user(user.id)
```

### Enforcement
Code review. Module-import linting (eslint import/no-restricted-paths, pylint).

### Rationale
Layer skipping defeats the purpose of layers: business logic ends up duplicated across controllers, data access ends up scattered, and testing each layer in isolation becomes impossible.

<!-- RULE END: ARCH-LAYER-001 -->
---

<!-- RULE START: ARCH-LAYER-002 -->
## Rule ARCH-LAYER-002

**Domain**: architecture
**Severity**: Medium
**Scope**: Component
**Mandatory**: false

### Trigger
When defining domain models (entities, value objects, aggregates).

### Statement
Domain models have no framework imports. Django ORM Model, SQLAlchemy Base, Spring @Entity, Active Record annotations are framework concerns; the domain model is plain data + behavior. Framework types are converted at boundaries.

### Violation
```python
from django.db import models
class User(models.Model):  # framework-coupled
    name = models.CharField(max_length=255)
    def is_eligible(self): ...
```

### Pass
```python
@dataclass
class User:
    id: UserId
    name: str
    def is_eligible(self) -> bool: ...
# UserRepository converts Django Model <-> User dataclass at boundary.
```

### Enforcement
Code review.

### Rationale
Framework-coupled domain models drag the framework into every test, every reuse, and every refactor. Plain models are portable.

<!-- RULE END: ARCH-LAYER-002 -->
---

<!-- RULE START: ARCH-MIGRATION-001 -->
## Rule ARCH-MIGRATION-001

**Domain**: architecture
**Severity**: High
**Scope**: Component
**Mandatory**: false

### Trigger
When changing the database schema.

### Statement
Schema changes use versioned migrations (Alembic, Django migrations, Flyway, Liquibase, Rails migrations, Doctrine migrations). Manual DDL applied to production environments outside the migration system is a violation.

### Violation
```
# DBA SSH-es into prod and runs `ALTER TABLE users ADD COLUMN ...`
# No record in version control; schema and code drift.
```

### Pass
```python
# alembic/versions/2026_05_10_add_user_avatar.py
def upgrade(): op.add_column('users', sa.Column('avatar_url', sa.String()))
def downgrade(): op.drop_column('users', 'avatar_url')
```

### Enforcement
CI gate that migrations run cleanly against a fresh database. Code review.

### Rationale
Versioned migrations make schema state reproducible, reviewable, and rollback-able. Manual DDL turns the schema into a folk artifact.

<!-- RULE END: ARCH-MIGRATION-001 -->
---

<!-- RULE START: ARCH-MIGRATION-002 -->
## Rule ARCH-MIGRATION-002

**Domain**: architecture
**Severity**: Medium
**Scope**: Component
**Mandatory**: false

### Trigger
When writing a database migration.

### Statement
Migrations are reversible: both up and down are implemented. Irreversible changes (DROP COLUMN with data, DROP TABLE) are documented with the rationale in the migration file. Reversibility supports staged rollouts and incident rollback.

### Violation
```python
def upgrade(): op.drop_column('users', 'legacy_field')
def downgrade(): pass  # no way to recover the dropped data
```

### Pass
```python
# Step 1 migration: stop writing legacy_field; deploy.
# Step 2 migration (later): drop column once confirmed unused.
# Each step independently reversible.
```

### Enforcement
Code review.

### Rationale
Reversible migrations preserve the option to roll back without data loss. Irreversible changes are sometimes necessary but are explicit decisions.

<!-- RULE END: ARCH-MIGRATION-002 -->
---

<!-- RULE START: ARCH-STATE-001 -->
## Rule ARCH-STATE-001

**Domain**: architecture
**Severity**: High
**Scope**: Component
**Mandatory**: false

### Trigger
When modifying shared mutable state (module-level variables, singletons, in-memory caches, class-level state) from multi-threaded or async code.

### Statement
Shared mutable state is protected by explicit synchronization (locks, mutexes, atomic operations) or replaced by message-passing / immutable updates. Unguarded global mutation in concurrent code is a violation.

### Violation
```python
CACHE = {}
def get_or_compute(key):
    if key not in CACHE:
        CACHE[key] = expensive(key)
    return CACHE[key]
# Two threads racing on the same key both run expensive().
```

### Pass
```python
import threading
CACHE: dict = {}
LOCK = threading.Lock()
def get_or_compute(key):
    with LOCK:
        if key not in CACHE:
            CACHE[key] = expensive(key)
        return CACHE[key]
# Or use functools.lru_cache (thread-safe).
```

### Enforcement
Code review.

### Rationale
Unguarded concurrent mutation produces nondeterministic bugs that are nearly impossible to reproduce. Synchronization or immutability removes the entire bug class.

<!-- RULE END: ARCH-STATE-001 -->
---

<!-- RULE START: ARCH-STATE-002 -->
## Rule ARCH-STATE-002

**Domain**: architecture
**Severity**: Medium
**Scope**: Component
**Mandatory**: false

### Trigger
When introducing state management for application UI.

### Statement
A single state-management pattern (Redux, Zustand, MobX, React Context, Vuex, Pinia, NgRx) is used per project. Mixing two patterns scatters state across incompatible mental models. The choice is documented and consistent.

### Violation
```
# Some components read from Redux, others from Context, others from
# local useState mirroring shared state. Bugs hide between the mirrors.
```

### Pass
```
# Project chose Zustand. All shared state lives in Zustand stores.
# Local component state is allowed only for non-shared concerns.
```

### Enforcement
Code review. ESLint rule restricting imports of competing libraries.

### Rationale
Mixed state-management produces state that lives in multiple places at once and drifts. One pattern is the structural defense.

<!-- RULE END: ARCH-STATE-002 -->
---

<!-- RULE START: SOLID-DIP-001 -->
## Rule SOLID-DIP-001

**Domain**: architecture
**Severity**: High
**Scope**: Component
**Mandatory**: false

### Trigger
When a high-level module (service, business logic) depends on a low-level module (database driver, HTTP client, file system).

### Statement
High-level modules depend on abstractions (protocols, interfaces, ABCs), not on concrete implementations. The abstraction is owned by the high-level module; the implementation conforms to it.

### Violation
```python
class OrderService:
    def __init__(self):
        self.db = psycopg2.connect(...)  # concrete driver
        self.payments = StripeClient()    # concrete vendor
```

### Pass
```python
class OrderRepository(Protocol):
    def save(self, order): ...
class PaymentGateway(Protocol):
    def charge(self, amount, customer): ...
class OrderService:
    def __init__(self, repo: OrderRepository, payments: PaymentGateway):
        self.repo, self.payments = repo, payments
```

### Enforcement
Code review.

### Rationale
Concrete dependencies make business logic untestable, untransferable, and tightly coupled to vendor decisions. Abstractions invert the dependency.

<!-- RULE END: SOLID-DIP-001 -->
---

<!-- RULE START: SOLID-DIP-002 -->
## Rule SOLID-DIP-002

**Domain**: architecture
**Severity**: Critical
**Scope**: Component
**Mandatory**: false

### Trigger
When constructing a controller, route handler, or service-layer class that requires collaborators (services, repositories, gateways, clients) -- including any time such a class instantiates ("news up") its own dependencies with `new ConcreteClass()` instead of receiving them via constructor injection.

### Statement
Dependencies are received via constructor injection, typed to an interface or protocol. Direct instantiation (`new ConcreteClass()`) inside a controller or service-layer class is permitted only for DTOs, value objects, and known framework types. Application services and controllers receive their dependencies; they do not construct them.

### Violation
```python
class OrderService:
    def __init__(self):
        self.stripe = StripeClient()   # constructs concrete
        self.email = SendgridClient()
```

### Pass
```python
class OrderService:
    def __init__(self, payments: PaymentGateway, email: EmailGateway):
        self.payments = payments
        self.email = email
```

### Enforcement
Code review. DI container config (Spring, Magento DI, Symfony DI, Dagger).

### Rationale
Injection makes dependencies visible and replaceable. Direct construction hides them and freezes substitutability.

<!-- RULE END: SOLID-DIP-002 -->
---

<!-- RULE START: SOLID-DIP-003 -->
## Rule SOLID-DIP-003

**Domain**: architecture
**Severity**: Medium
**Scope**: Component
**Mandatory**: false

### Trigger
When designing service-layer / domain-layer code.

### Statement
Framework-specific types do not leak into domain logic. Django QuerySets, Express Request objects, SQLAlchemy Session, ORM model classes are not consumed by domain services directly; they are adapted at the boundary.

### Violation
```python
class OrderService:
    def place(self, request: flask.Request):  # framework leaks in
        ...
```

### Pass
```python
class OrderService:
    def place(self, payload: OrderInput, actor: User):
        ...
# The controller adapts the framework Request -> OrderInput + actor.
```

### Enforcement
Code review.

### Rationale
Framework types in domain code make every domain method untestable without the framework and prevent reuse from non-framework callers (background jobs, CLI).

<!-- RULE END: SOLID-DIP-003 -->
---

<!-- RULE START: SOLID-ISP-001 -->
## Rule SOLID-ISP-001

**Domain**: architecture
**Severity**: Medium
**Scope**: Component
**Mandatory**: false

### Trigger
When defining an interface, protocol, or abstract base class.

### Statement
Interfaces contain only methods that all their consumers use. A 'fat interface' that some consumers ignore signals the interface should be split into smaller cohesive interfaces.

### Violation
```python
class Storage(Protocol):
    def read(self, key): ...
    def write(self, key, value): ...
    def delete(self, key): ...
    def stream(self, key): ...
    def list(self, prefix): ...
# A read-only consumer (config loader) must depend on all of these.
```

### Pass
```python
class ReadStorage(Protocol):
    def read(self, key): ...
class WriteStorage(ReadStorage):
    def write(self, key, value): ...
    def delete(self, key): ...
# Read-only consumers depend on ReadStorage; write consumers on WriteStorage.
```

### Enforcement
Code review.

### Rationale
Fat interfaces force consumers to depend on methods they do not use, which propagates breaking changes through every implementation when an unrelated method changes.

<!-- RULE END: SOLID-ISP-001 -->
---

<!-- RULE START: SOLID-ISP-002 -->
## Rule SOLID-ISP-002

**Domain**: architecture
**Severity**: Medium
**Scope**: Component
**Mandatory**: false

### Trigger
When implementing an interface or abstract base class.

### Statement
If an implementation raises NotImplementedError for some interface methods, that signals the interface should be split. The pattern indicates a fat-interface design problem (overlaps with SOLID-ISP-001).

### Violation
```python
class NotificationChannel(ABC):
    @abstractmethod
    def send_email(self, to, body): ...
    @abstractmethod
    def send_sms(self, to, body): ...

class EmailOnly(NotificationChannel):
    def send_email(self, to, body): ...
    def send_sms(self, to, body):
        raise NotImplementedError()  # interface mismatch
```

### Pass
```python
class EmailChannel(Protocol):
    def send_email(self, to, body): ...
class SMSChannel(Protocol):
    def send_sms(self, to, body): ...
```

### Enforcement
Code review.

### Rationale
NotImplementedError in a production class is a runtime time bomb. The structural defense is a narrower interface.

<!-- RULE END: SOLID-ISP-002 -->
---

<!-- RULE START: SOLID-LSP-001 -->
## Rule SOLID-LSP-001

**Domain**: architecture
**Severity**: High
**Scope**: Component
**Mandatory**: false

### Trigger
When implementing a subclass or interface implementation.

### Statement
Subclasses or implementations do not weaken preconditions (require less than the parent) or strengthen postconditions (return less than the parent guarantees). A consumer of the parent type works correctly with any subclass.

### Violation
```python
class List:
    def add(self, item):  # no precondition stated
        ...
class SortedList(List):
    def add(self, item):
        if not isinstance(item, Comparable):
            raise TypeError()  # strengthens precondition; LSP violation
        ...
```

### Pass
```python
class List:
    def add(self, item):
        ...
class SortedList(List):
    def add(self, item: Comparable):  # precondition reflected in type
        ...
# Or: SortedList does not extend List.
```

### Enforcement
Code review.

### Rationale
LSP violations turn polymorphism into a runtime trap: code that worked against the parent type breaks unpredictably with a subclass.

<!-- RULE END: SOLID-LSP-001 -->
---

<!-- RULE START: SOLID-LSP-002 -->
## Rule SOLID-LSP-002

**Domain**: architecture
**Severity**: Medium
**Scope**: Component
**Mandatory**: false

### Trigger
When overriding a method in a subclass.

### Statement
Overridden methods maintain the parent's return type contract. A method declared to return `User` does not return `None` in the override. A method declared to return non-empty list does not return `[]`. The contract is documented or implied; the override respects it.

### Violation
```python
class Repo:
    def get(self, id) -> User: ...
class CachedRepo(Repo):
    def get(self, id) -> User | None:  # weaker -- breaks callers
        ...
```

### Pass
```python
class Repo:
    def get(self, id) -> User | None: ...
class CachedRepo(Repo):
    def get(self, id) -> User | None: ...
```

### Enforcement
Type checker (mypy strict, pyright). Code review.

### Rationale
Return-type drift in overrides breaks every caller that assumed the parent's contract.

<!-- RULE END: SOLID-LSP-002 -->
---

<!-- RULE START: SOLID-OCP-001 -->
## Rule SOLID-OCP-001

**Domain**: architecture
**Severity**: High
**Scope**: Component
**Mandatory**: false

### Trigger
When extending behavior of existing modules, framework classes, or third-party libraries.

### Statement
Behavior is extended via composition, strategy, plugin/extension hooks, or framework-native mechanisms (decorators, observers, middleware). Modifying existing code to support a new variant is a violation; new variants are added without changing the old code path.

### Violation
```python
class OrderPricer:
    def price(self, order):
        if order.customer.tier == 'enterprise':
            return self._enterprise_pricing(order)
        elif order.customer.tier == 'startup':
            return self._startup_pricing(order)
        elif order.customer.tier == 'partner':
            return self._partner_pricing(order)  # added this week
        return self._standard_pricing(order)
```

### Pass
```python
class OrderPricer:
    def __init__(self, strategies: dict[str, PricingStrategy]):
        self.strategies = strategies
    def price(self, order):
        strategy = self.strategies.get(order.customer.tier, self.strategies['standard'])
        return strategy.price(order)
```

### Enforcement
Code review. Framework-specific extension hooks (Magento plugins, Django middleware, FastAPI dependencies, Spring AOP).

### Rationale
Closed-for-modification is the structural defense against regression: existing code paths keep working when new variants ship.

<!-- RULE END: SOLID-OCP-001 -->
---

<!-- RULE START: SOLID-OCP-002 -->
## Rule SOLID-OCP-002

**Domain**: architecture
**Severity**: Medium
**Scope**: Component
**Mandatory**: false

### Trigger
When writing a switch/match or chain of if/elif branches on a type discriminator.

### Statement
Switch/match on a type with more than 3 branches is replaced by polymorphism (subclass dispatch, strategy registry, visitor pattern) when the type set is extensible. Chains that hard-code every type prevent additions without editing every chain.

### Violation
```python
def render(event):
    if event.kind == 'signup':
        return render_signup(event)
    elif event.kind == 'login':
        return render_login(event)
    elif event.kind == 'purchase':
        return render_purchase(event)
    elif event.kind == 'refund':  # added today
        return render_refund(event)
    # ... new event types ripple to every dispatcher
```

### Pass
```python
class Event(Protocol):
    def render(self): ...
# Each event subclass implements its own render(). Dispatcher: event.render().
```

### Enforcement
Code review.

### Rationale
Long type switches mean each new type requires editing every dispatcher. Polymorphism puts the type-specific logic with the type.

<!-- RULE END: SOLID-OCP-002 -->
---

<!-- RULE START: SOLID-SRP-001 -->
## Rule SOLID-SRP-001

**Domain**: architecture
**Severity**: High
**Scope**: Component
**Mandatory**: false

### Trigger
When designing or modifying a class.

### Statement
Each class has exactly one reason to change. A class that handles both HTTP parsing and business logic, both persistence and validation, both presentation and computation, is split.

### Violation
```python
class UserController:
    def signup(self, request):
        # Validates input, hashes password, saves to DB, sends welcome email,
        # logs analytics, returns rendered HTML.
        ...
```

### Pass
```python
class UserController:
    def signup(self, request):
        payload = SignupInput(**request.json)
        user = user_service.create(payload)
        return render(user)

class UserService:
    def create(self, payload):
        ...
```

### Enforcement
Code review.

### Rationale
A class that knows about too many concerns changes for too many reasons. Single-responsibility classes evolve independently.

<!-- RULE END: SOLID-SRP-001 -->
---

<!-- RULE START: SOLID-SRP-002 -->
## Rule SOLID-SRP-002

**Domain**: architecture
**Severity**: Medium
**Scope**: Component
**Mandatory**: false

### Trigger
When implementing a route handler, controller method, or HTTP endpoint.

### Statement
Controllers and handlers delegate to a service layer. Business logic does not live in route functions. The handler's job: parse input, call a service, format output.

### Violation
```python
@app.post('/orders')
def create_order(payload):
    if payload.amount > customer.balance:
        raise InsufficientFunds()
    db.session.add(Order(...))
    db.session.commit()
    stripe.charge(...)
    return jsonify({...})
```

### Pass
```python
@app.post('/orders')
def create_order(payload):
    order = order_service.place(current_user, payload)
    return jsonify(OrderResponse.from_orm(order).dict())
```

### Enforcement
Code review.

### Rationale
Business logic in controllers is untestable without HTTP plumbing and is invisible to non-HTTP callers (jobs, CLIs).

<!-- RULE END: SOLID-SRP-002 -->
---

<!-- RULE START: SOLID-SRP-003 -->
## Rule SOLID-SRP-003

**Domain**: architecture
**Severity**: Medium
**Scope**: Component
**Mandatory**: false

### Trigger
When organizing data access alongside business rules.

### Statement
Data access is separated from business rules via a repository or DAO layer. Services depend on repository interfaces; ORM queries are not inlined into business logic.

### Violation
```python
class OrderService:
    def fulfill(self, order_id):
        order = Order.query.filter_by(id=order_id).first()  # direct ORM
        order.status = 'fulfilled'
        db.session.commit()
```

### Pass
```python
class OrderService:
    def __init__(self, orders: OrderRepository):
        self.orders = orders
    def fulfill(self, order_id):
        order = self.orders.get(order_id)
        order.mark_fulfilled()
        self.orders.save(order)
```

### Enforcement
Code review.

### Rationale
Mixing query syntax into services couples the service to an ORM. The repository layer is the seam where the storage technology can change.

<!-- RULE END: SOLID-SRP-003 -->
