# Contract tests

Pact-based contract tests verify that the **shape of the conversation** between an HTML form (consumer) and the API endpoint it posts to (provider) stays in sync. They do **not** verify business behavior — that's what the colocated unit tests under `src/<layer>/test_*.py` are for.

> **Status:** auth (registration), users (admin actions), and posts (create form, client_referral edit form, owner actions) currently have contract test pairs. Add a pair for any new HTML form (or htmx-driven action partial) per the conventions below.

## Why this directory exists outside the colocated convention

The rest of the repo's tests live next to their source ([`tests/README.md`](../README.md)). Contract tests can't, because each test inherently spans **two** layers:

- **Consumer side** lives with `src/templates/<form>.html` (and the `/form` page route in `src/api/routes/`).
- **Provider side** lives with the API route handler in `src/api/routes/<resource>.py`.

A single test asserts both ends agree, so it can't sit on either side without lying about its scope. `tests/test_contract/` is the documented exception. Everywhere else the colocation rule still applies.

## Philosophy: testing the waiter, not the chef

For each `<form>` → endpoint pair, contract tests verify only protocol-level facts:

- `Content-Type` header is what the route expects (e.g. `application/json` vs `application/x-www-form-urlencoded`)
- All required fields are present in the body
- HTTP method and path match
- Response status / `Location` header (for redirects) are what the form's success path assumes

They explicitly do **not** verify whether users exist, permissions hold, validation rules fire, or anything else that requires running real business logic. The provider side keeps the route layer real and **monkey-patches the business-logic handler** to a fixed return value; the consumer side runs in a Playwright browser with the API call intercepted and forwarded to a Pact mock.

| Test type | What it verifies | What it mocks |
| --- | --- | --- |
| Consumer contract | Browser-issued request shape | The whole provider API |
| Provider contract | Route layer parses the request and returns the documented shape | Business-logic handlers only |
| Colocated unit/integration tests (under `src/`) | Behavior, validation, persistence | External services, where appropriate |

## Layout

```
tests/test_contract/
├── README.md                          # This file
├── conftest.py                        # Session fixtures: consumer server, provider server, browser, page
├── constants.py                       # Shared test data + Pact identifiers
├── artifacts/                         # Generated pact files and logs (gitignored except .gitkeep)
├── infrastructure/
│   ├── config.py                      # Hosts, ports, KNOWN_PROVIDER_STATES
│   ├── servers/
│   │   ├── base.py                    # ServerManager: subprocess lifecycle + health-poll
│   │   ├── consumer.py                # Hosts the HTML pages under test
│   │   └── provider.py                # Runs src.main:app with handler-level mocks
│   └── utilities/
│       ├── mocks.py                   # MockAuthManager + monkey-patch helpers
│       ├── pact_helpers.py            # setup_pact()
│       └── playwright_helpers.py      # Pact ↔ Playwright route interception
└── tests/
    ├── consumer/
    │   ├── test_auth_form.py            # Registration form contract
    │   ├── test_user_admin_actions.py   # Admin-actions partial contract
    │   ├── test_post_form.py            # New-post form contract
    │   ├── test_post_edit_form.py       # Edit-post form contract (client_referral)
    │   └── test_post_owner_actions.py   # Owner-actions partial contract (Delete)
    ├── provider/
    │   ├── test_auth_verification.py
    │   ├── test_user_admin_actions_verification.py
    │   └── test_posts_verification.py   # Verifies post create + edit + owner-actions pacts
    └── shared/
        ├── consumer_test_base.py      # BaseConsumerTest abstract class
        ├── helpers.py                 # Pact + Playwright glue
        ├── mock_data_factory.py       # Mock data + dependency-override configs
        └── provider_verification_base.py
```

## Running

Contract tests are excluded from default `dev test` runs (`addopts` in `pyproject.toml` carries `--ignore=tests/test_contract`). Invoke them by passing the directory explicitly — pytest collects consumer tests first (alphabetical), then provider, in one session:

```bash
# Run all contract tests in one session (consumer + provider)
dev test tests/test_contract

# Or by file
dev test tests/test_contract/tests/consumer/test_auth_form.py
```

Consumer tests must run before provider tests in any single session — the consumer run *generates* the pact JSON files in `artifacts/pacts/` that the provider run *verifies against*. Running both with one invocation (above) handles this ordering automatically.

Provider tests carry `pytest.mark.provider` (set via `BaseProviderVerification.pytest_marks`), so `-m provider` works to filter those. Consumer tests are not currently marked, so there is no symmetric `-m consumer` filter.

## Adding a contract test pair

When you add a new HTML form (per [`src/api/routes/RESOURCE_GRAMMAR.md`](../../src/api/routes/RESOURCE_GRAMMAR.md) — every form-bearing resource MUST have a contract test pair):

1. **Add a flag** to `ConsumerServerConfig` in `infrastructure/servers/consumer.py` and a corresponding `app.include_router(...)` call so the consumer server can mount your form's page route.
2. **Add constants** for the API path, provider state, consumer/provider Pact names, and a unique Pact port to `constants.py`. Append the provider state string to `KNOWN_PROVIDER_STATES` in `infrastructure/config.py`.
3. **Write the consumer test** (`tests/consumer/test_<resource>_form.py`) — drive the form with Playwright and assert the intercepted request matches a Pact expectation.
4. **Add a `MockDataFactory.create_<resource>_dependency_config()`** mapping the route's business-logic handler import path (the one used by `from ... import` inside the route module) to a mock return value.
5. **Write the provider test** (`tests/provider/test_<resource>_verification.py`) — subclass `BaseProviderVerification` and call `verify_pact(provider_server)` under the dependency-override decorator.

## Related documentation

- [`../../CLAUDE.md`](../../CLAUDE.md) — definition of done
- [`../../src/api/routes/RESOURCE_GRAMMAR.md`](../../src/api/routes/RESOURCE_GRAMMAR.md) — resource conventions, including the "form-bearing resource → contract test pair" rule
- [`../README.md`](../README.md) — colocated-test convention this directory is the exception to
