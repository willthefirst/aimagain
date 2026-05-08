# Contract tests

Pact-based contract tests verify that the **shape of the conversation** between an HTML form (consumer) and the API endpoint it posts to (provider) stays in sync. They do **not** verify business behavior — that's what the colocated unit tests under `src/<layer>/test_*.py` are for.

> **Status:** auth (registration), users (admin actions), and posts (create + edit forms, owner actions) currently have contract test pairs. Add a pair for any new HTML form (or htmx-driven action partial) per the conventions below.

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
├── manifest.py                        # CONTRACT_PAIRS — single source of truth per pair
├── test_manifest.py                   # Manifest-consistency tests (uniqueness, derived-state coverage)
├── artifacts/                         # Generated pact files and logs (gitignored except .gitkeep)
├── infrastructure/
│   ├── config.py                      # Hosts, ports; KNOWN_PROVIDER_STATES is derived from `manifest.py`
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
    │   └── test_post_owner_actions.py   # Owner-actions partial contract (Delete)
    ├── provider/
    │   ├── test_auth_verification.py            # Parametrized over `pairs_for_provider("auth-api")`
    │   ├── test_user_admin_actions_verification.py
    │   └── test_posts_verification.py           # Parametrized over every `posts-api` pair in the manifest
    └── shared/
        ├── consumer_test_base.py      # BaseConsumerTest abstract class
        ├── helpers.py                 # Pact + Playwright glue
        ├── mock_data_factory.py       # Mock data + dependency-override configs; `make_post_stub`
        └── provider_verification_base.py  # `verify_pair(pair, provider_server)` + decorator helpers
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

Provider tests carry `pytest.mark.provider` (applied directly to the parametrized test functions in `tests/provider/test_*_verification.py`), so `-m provider` filters them. Per-provider marks (`auth`, `users`, `posts`) are also registered in `pyproject.toml` so per-API filtering (`-m posts`) is also valid. Each pair's `pytest_marks` field in [`manifest.py`](manifest.py) records the same set as documentation — keeping them in sync is a manual discipline today (see follow-up note in the manifest's docstring). Consumer tests are not currently marked, so there is no symmetric `-m consumer` filter.

## Adding a contract test pair

When you add a new HTML form (per [`src/api/routes/RESOURCE_GRAMMAR.md`](../../src/api/routes/RESOURCE_GRAMMAR.md) — every form-bearing resource MUST have a contract test pair):

1. **(If the consumer needs an HTML stub page)** add a flag to `ConsumerServerConfig` in `infrastructure/servers/consumer.py` and a `_setup_*_stub` function that mounts the page. Reference the setup function as the pair's `consumer_setup_fn` in step 3.
2. **Add constants** for the API path, consumer/provider Pact names, and a unique Pact port to `constants.py`. (Provider states no longer need to be appended to `KNOWN_PROVIDER_STATES` separately — the manifest entry's `provider_state` is what drives that list.)
3. **Add a `ContractPair` entry** to [`manifest.py`](manifest.py): consumer + provider names, port, `provider_state` string, `pytest_marks` tuple, and the optional `consumer_setup_fn` / `handler_mocks_factory` callables. The provider verification test under `tests/provider/test_<resource>_verification.py` parametrizes over `pairs_for_provider(provider_name)` automatically — no per-pair subclass needed.
4. **Write the consumer test** (`tests/consumer/test_<resource>_form.py`) — drive the form with Playwright and assert the intercepted request matches a Pact expectation.
5. **(If the route needs handler-level mocks)** add a `MockDataFactory.create_<resource>_dependency_config()` classmethod returning `{handler_path: {"return_value_config": ...}}`, and reference it as `handler_mocks_factory` on the manifest entry. For Post-shaped stubs, use `make_post_stub(kind, **field_overrides)` from `tests/shared/mock_data_factory.py` — it reads the per-kind detail relationship and field tuple from `REGISTERED_KINDS` in [`src/models/posts/post_kinds.py`](../../src/models/posts/post_kinds.py).
6. **(If the provider name is new)** create `tests/provider/test_<resource>_verification.py` with a parametrized test function (see existing files as templates — they're 8 lines each, parametrized over `pairs_for_provider`).

## Related documentation

- [`../../CLAUDE.md`](../../CLAUDE.md) — definition of done
- [`../../src/api/routes/RESOURCE_GRAMMAR.md`](../../src/api/routes/RESOURCE_GRAMMAR.md) — resource conventions, including the "form-bearing resource → contract test pair" rule
- [`../README.md`](../README.md) — colocated-test convention this directory is the exception to
