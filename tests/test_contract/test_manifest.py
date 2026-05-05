"""Tests guarding the contract-pair manifest as the single source of truth.

These tests are colocated with the manifest (not under
`tests/test_contract/tests/`) because they cover the manifest module
itself, not a contract pair. They are excluded from the default `dev test`
collection by `--ignore=tests/test_contract` in `pyproject.toml`, like
the rest of this directory; run them with `dev test tests/test_contract`.
"""

from tests.test_contract.infrastructure.config import KNOWN_PROVIDER_STATES
from tests.test_contract.manifest import (
    CONTRACT_PAIRS,
    combined_handler_mocks,
    known_provider_states,
    pairs_for_provider,
)


def test_known_provider_states_matches_manifest():
    """The exposed `KNOWN_PROVIDER_STATES` (consumed by `conftest.py`)
    is exactly what the manifest's `known_provider_states()` returns."""
    assert KNOWN_PROVIDER_STATES == known_provider_states()


def test_known_provider_states_are_deduped():
    """Multiple pairs may share a provider state (e.g. post-edit and
    post-owner-actions both target the same persisted post). The state
    list returned to the verifier must be deduplicated."""
    states = known_provider_states()
    assert len(states) == len(set(states))


def test_pact_ports_are_unique():
    """Each pair's mock-server port must be unique — collisions cause
    the second pair's pact-mock-server to fail to bind."""
    ports = [p.pact_port for p in CONTRACT_PAIRS]
    assert len(ports) == len(set(ports))


def test_consumer_names_are_unique():
    """Pact participant names are used as file-name prefixes for the
    generated `<consumer>-<provider>.json` pact files; duplicates would
    overwrite each other."""
    names = [p.consumer_name for p in CONTRACT_PAIRS]
    assert len(names) == len(set(names))


def test_pairs_for_provider_filters_correctly():
    """`pairs_for_provider` returns exactly the pairs whose
    `provider_name` matches; the union across providers covers the
    whole manifest."""
    providers = {p.provider_name for p in CONTRACT_PAIRS}
    seen: list = []
    for provider in providers:
        for pair in pairs_for_provider(provider):
            assert pair.provider_name == provider
            seen.append(pair)
    assert sorted(seen, key=lambda p: p.consumer_name) == sorted(
        CONTRACT_PAIRS, key=lambda p: p.consumer_name
    )


def test_combined_handler_mocks_merges_per_provider():
    """For every provider, `combined_handler_mocks(p)` covers exactly
    the union of its pairs' handler-mock keys.

    Compared by key set rather than full dict equality because some
    factories (e.g. `create_registration_dependency_config`) generate a
    fresh UUID per call — the dispatch-key surface is what matters.
    """
    providers = {p.provider_name for p in CONTRACT_PAIRS}
    for provider in providers:
        combined = combined_handler_mocks(provider)
        expected_keys: set = set()
        for pair in pairs_for_provider(provider):
            if pair.handler_mocks_factory is not None:
                expected_keys.update(pair.handler_mocks_factory().keys())
        assert set(combined.keys()) == expected_keys
