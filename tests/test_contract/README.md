# Contract tests

Pact-based contract tests verify that the **shape of the conversation** between an HTML form (consumer) and the API endpoint it posts to (provider) stays in sync. They do **not** verify business behavior — that's what the colocated unit tests under `src/<layer>/test_*.py` are for.

The current set of contract pairs lives in [`manifest.py`](manifest.py)'s `CONTRACT_PAIRS` — that's the registry. Per [`src/domain/routes/RESOURCE_GRAMMAR.md`](../../src/domain/routes/RESOURCE_GRAMMAR.md), every resource exposing an HTML form (or htmx-driven action partial) MUST have a contract pair; add new pairs there using the conventions below.

The rule is enforced by [`scripts/dev/contract_form_coverage_check.py`](../../scripts/dev/contract_form_coverage_check.py), which runs in `dev lint` and as a pre-commit hook. It walks every `<form>` in `src/{domain,framework}/templates/` and asserts the submit URL appears in either `CONTRACT_PAIRS[*].endpoints` or that script's `FORMS_WITHOUT_PAIRS` allowlist. A new literal-URL form without a pair fails CI loudly — see the failure-message template in the script for the exact escape hatches.

## Why this directory exists outside the colocated convention

The rest of the repo's tests live next to their source ([`tests/README.md`](../README.md)). Contract tests can't, because each test inherently spans **two** layers:

- **Consumer side** lives with `src/domain/templates/<form>.html` (and the `/form` page route in `src/domain/routes/`).
- **Provider side** lives with the API route handler in `src/domain/routes/<resource>.py`.

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
├── infrastructure/                    # Server orchestration + Pact/Playwright glue
│   ├── config.py                      # Hosts, ports; KNOWN_PROVIDER_STATES derived from manifest.py
│   ├── servers/                       # Consumer + provider subprocess managers
│   └── utilities/                     # MockAuthManager, setup_pact, Playwright route interception
└── tests/
    ├── consumer/                      # One test_<form>.py per HTML form under test
    ├── provider/                      # One test_<api>_verification.py per API the manifest groups by
    └── shared/                        # BaseConsumerTest, mock_data_factory, provider_verification_base
```

The `consumer/` and `provider/` directories are the registries — each new contract pair adds files there alongside its `manifest.py` entry. `find tests/test_contract -name 'test_*.py'` enumerates them.

## Running

Contract tests are excluded from default `dev test` runs (`addopts` in `pyproject.toml` carries `--ignore=tests/test_contract`). Invoke them by passing the directory explicitly — pytest collects consumer tests first (alphabetical), then provider, in one session:

```bash
# Run all contract tests in one session (consumer + provider)
dev test tests/test_contract

# Or by file
dev test tests/test_contract/tests/consumer/test_auth_form.py
```

Consumer tests must run before provider tests in any single session — the consumer run *generates* the pact JSON files in `artifacts/pacts/` that the provider run *verifies against*. Running both with one invocation (above) handles this ordering automatically.

Provider tests carry `pytest.mark.provider` (applied directly to the parametrized test functions in `tests/provider/test_*_verification.py`), so `-m provider` filters them. Per-API marks are registered in `pyproject.toml` and applied via each pair's `pytest_marks` field in [`manifest.py`](manifest.py); keeping the two in sync is a manual discipline (see follow-up note in the manifest's docstring). Consumer tests are not marked, so there is no symmetric `-m consumer` filter.

## Adding a contract test pair

When you add a new HTML form (per [`src/domain/routes/RESOURCE_GRAMMAR.md`](../../src/domain/routes/RESOURCE_GRAMMAR.md) — every form-bearing resource MUST have a contract test pair):

1. **(If the consumer needs an HTML stub page)** add a flag to `ConsumerServerConfig` in `infrastructure/servers/consumer.py` and a `_setup_*_stub` function that mounts the page. Reference the setup function as the pair's `consumer_setup_fn` in step 3.
2. **Add constants** for the API path, consumer/provider Pact names, and a unique Pact port to `constants.py`. (Provider states no longer need to be appended to `KNOWN_PROVIDER_STATES` separately — the manifest entry's `provider_state` is what drives that list.)
3. **Add a `ContractPair` entry** to [`manifest.py`](manifest.py): consumer + provider names, port, `provider_state` string, `pytest_marks` tuple, and the optional `consumer_setup_fn` / `handler_mocks_factory` callables. The provider verification test under `tests/provider/test_<resource>_verification.py` parametrizes over `pairs_for_provider(provider_name)` automatically — no per-pair subclass needed.
4. **Write the consumer test** (`tests/consumer/test_<resource>_form.py`) — drive the form with Playwright and assert the intercepted request matches a Pact expectation.
5. **(If the route needs handler-level mocks)** add a `MockDataFactory.create_<resource>_dependency_config()` classmethod returning `{handler_path: {"return_value_config": ...}}`, and reference it as `handler_mocks_factory` on the manifest entry. For Post-shaped stubs, use `make_post_stub(kind, **field_overrides)` from `tests/shared/mock_data_factory.py` — it reads the per-kind detail relationship and field tuple from `POST_KINDS` in [`src/domain/models/posts/post_kinds.py`](../../src/domain/models/posts/post_kinds.py).
6. **(If the provider name is new)** create `tests/provider/test_<resource>_verification.py` with a parametrized test function (see existing files as templates — they're 8 lines each, parametrized over `pairs_for_provider`).

## Related documentation

- [`../../CLAUDE.md`](../../CLAUDE.md) — definition of done
- [`../../src/domain/routes/RESOURCE_GRAMMAR.md`](../../src/domain/routes/RESOURCE_GRAMMAR.md) — resource conventions, including the "form-bearing resource → contract test pair" rule
- [`../README.md`](../README.md) — colocated-test convention this directory is the exception to
