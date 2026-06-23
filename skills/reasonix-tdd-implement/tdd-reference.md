# TDD Reference

Companion to [SKILL.md](SKILL.md). Read this before first use. Defines testing philosophy, mocking rules, and refactoring guidance.

---

## Philosophy

**Core principle:** Tests verify behavior through public interfaces, not implementation details. Code can change entirely; tests shouldn't break.

**Good tests** exercise real code paths through public APIs. They describe _what_ the system does, not _how_. A good test reads like a specification — "user can checkout with valid cart" tells you exactly what capability exists. These tests survive refactors because they don't care about internal structure.

**Bad tests** are coupled to implementation. They mock internal collaborators, test private methods, or verify through external means (querying a database directly instead of using the interface). Warning sign: test breaks when you refactor, but behavior hasn't changed.

---

## Vertical Slicing (Tracer Bullets)

**DO NOT write all tests first, then all implementation.** This is "horizontal slicing" — it produces bad tests.

Why horizontal fails:
- Tests written in bulk test _imagined_ behavior, not _actual_ behavior
- You end up testing the _shape_ of things (data structures, function signatures)
- Tests become insensitive to real changes — pass when behavior breaks, fail when behavior is fine
- You commit to test structure before understanding the implementation

**Correct approach:** One test → one implementation → repeat. Each test responds to what you learned from the previous cycle.

**Tracer bullet:** The first test in a phase should prove the path works end-to-end. Pick the core happy-path behavior — if this works, the architecture is sound.

---

## Good vs Bad Tests

### Good: Tests Observable Behavior

```python
# Tests WHAT the system does via its public API
def test_captured_note_is_retrievable_by_title():
    result = capture(sample_file)
    assert result.is_success
    found = search("sample title")
    assert len(found) == 1
    assert found[0].title == "sample title"
```

Characteristics:
- Tests behavior users/callers care about
- Uses public API only
- Survives internal refactors
- Describes WHAT, not HOW
- One logical assertion per test

### Bad: Tests Implementation Details

```python
# Tests HOW the system works internally
def test_capture_calls_storage_upsert(mock_storage):
    capture(sample_file)
    mock_storage.upsert.assert_called_once_with(expected_note)
```

Red flags:
- Mocking internal collaborators
- Testing private methods
- Asserting on call counts/order
- Test breaks on refactor without behavior change
- Test name describes HOW not WHAT
- Verifying through external means instead of interface

```python
# BAD: Bypasses interface to verify
def test_create_user_saves_to_database(db):
    create_user(name="Alice")
    row = db.execute("SELECT * FROM users WHERE name = ?", ("Alice",)).fetchone()
    assert row is not None

# GOOD: Verifies through interface
def test_created_user_is_retrievable():
    user = create_user(name="Alice")
    retrieved = get_user(user.id)
    assert retrieved.name == "Alice"
```

---

## When to Mock

Mock at **system boundaries** only:

| Mock | Don't Mock |
|------|-----------|
| External APIs (payment, email, LLM) | Your own classes/modules |
| Databases (sometimes — prefer test DB) | Internal collaborators |
| Time / randomness | Anything you control |
| File system (sometimes) | |

### Designing for Mockability

**1. Dependency injection** — Pass external deps in, don't create internally:

```python
# Easy to mock
def process_note(content: str, llm_client: LLMClient) -> Summary:
    return llm_client.summarize(content)

# Hard to mock
def process_note(content: str) -> Summary:
    client = ClaudeClient(os.environ["API_KEY"])
    return client.summarize(content)
```

**2. SDK-style interfaces** — Specific functions per operation, not one generic fetcher:

```python
# GOOD: Each function independently mockable
class NoteStore(Protocol):
    def get(self, id: str) -> Note: ...
    def save(self, note: Note) -> None: ...
    def search(self, query: str) -> list[Note]: ...

# BAD: Generic interface requires conditional mock logic
class Store(Protocol):
    def execute(self, operation: str, **kwargs) -> Any: ...
```

### Mock Rules

1. **Never test mock behavior.** If assertion checks that a mock was called, you're testing the mock, not the code. Test real behavior or remove the mock.

2. **Mock with understanding, not fear.** Before mocking any dependency: know what side effects the real method has, know whether your test depends on them, mock at the lowest level that removes the slow/external part.

3. **Use complete mocks.** When mocking a data structure (API response, config), mirror the full real structure — not just fields your test uses. Partial mocks hide structural assumptions.

4. **Never mock "to be safe."** If mock setup exceeds 50% of the test, consider an integration test instead.

---

## Deep Modules

From "A Philosophy of Software Design" — look for these during refactor:

**Deep module** = small interface + lots of implementation hidden inside

```
┌─────────────────────┐
│   Small Interface   │  ← Few methods, simple params
├─────────────────────┤
│                     │
│  Deep Implementation│  ← Complex logic hidden
│                     │
└─────────────────────┘
```

**Shallow module** = large interface + little implementation (avoid)

```
┌─────────────────────────────────┐
│       Large Interface           │  ← Many methods, complex params
├─────────────────────────────────┤
│  Thin Implementation            │  ← Just passes through
└─────────────────────────────────┘
```

When designing interfaces, ask:
- Can I reduce the number of methods?
- Can I simplify the parameters?
- Can I hide more complexity inside?

---

## Interface Design for Testability

1. **Accept dependencies, don't create them** — enables DI for testing
2. **Return results, don't produce side effects** — assertions on return values are simpler than observing mutations
3. **Small surface area** — fewer methods = fewer tests needed, fewer params = simpler test setup

---

## Refactoring (Post-Green Only)

**Never refactor while RED.** Get to GREEN first.

After all tests pass, look for:

| Candidate | Action |
|-----------|--------|
| Duplication | Extract function/class |
| Long methods | Break into private helpers (keep tests on public interface) |
| Shallow modules | Combine or deepen |
| Feature envy | Move logic to where data lives |
| Primitive obsession | Introduce value objects |
| Existing code | New code may reveal problems in old code |

Run tests after each refactor step. One change at a time.

---

## Testing Red Flags — Stop and Course-Correct

Any of these mean something went wrong:

- [ ] Assertion checks for `*-mock` test IDs
- [ ] Methods exist only in test files (test-only production methods)
- [ ] Mock setup is >50% of the test
- [ ] Test fails when you remove the mock (testing mock, not behavior)
- [ ] Can't explain why the mock is needed
- [ ] Test passes on first run (never saw it fail — skipped RED)
- [ ] Keeping deleted code "as reference"
- [ ] Rationalizing "just this once"
- [ ] Test name contains "and" (testing two behaviors)
- [ ] Test would break on refactor without behavior change

---

## Never Add Test-Only Methods to Production Classes

If a method exists solely for test cleanup or inspection, it doesn't belong in production. Put it in test utilities (`tests/helpers/`, `conftest.py`, or a test fixture).

Gate: Before adding any method to a production class, ask: "Is this only called by tests?" If yes → test utilities.
