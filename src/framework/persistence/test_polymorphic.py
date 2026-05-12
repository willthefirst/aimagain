"""Unit tests for the generic `DiscriminatorRegistry`.

Independent of any concrete entity. Uses a fixture Spec dataclass so a
broken assumption fails here instead of via a mystery error in the post
registry.
"""

from dataclasses import dataclass

import pytest

from src.framework.persistence.polymorphic import DiscriminatorRegistry


@dataclass(frozen=True)
class _FixtureSpec:
    name: str
    payload: type


class _AlphaModel:
    pass


class _BetaModel:
    pass


def _make_registry(column: str = "kind") -> DiscriminatorRegistry[_FixtureSpec]:
    return DiscriminatorRegistry(
        column=column,
        specs={
            "alpha": _FixtureSpec(name="alpha", payload=_AlphaModel),
            "beta": _FixtureSpec(name="beta", payload=_BetaModel),
        },
    )


def test_getitem_returns_spec():
    reg = _make_registry()
    assert reg["alpha"].payload is _AlphaModel
    assert reg["beta"].payload is _BetaModel


def test_getitem_missing_raises_keyerror():
    reg = _make_registry()
    with pytest.raises(KeyError):
        reg["gamma"]


def test_get_returns_spec_or_none():
    reg = _make_registry()
    assert reg.get("alpha").payload is _AlphaModel
    assert reg.get("nope") is None


def test_names_is_declaration_order():
    reg = _make_registry()
    assert reg.names == ("alpha", "beta")


def test_values_and_items_iterate():
    reg = _make_registry()
    assert [s.name for s in reg.values()] == ["alpha", "beta"]
    assert [(k, s.name) for k, s in reg.items()] == [
        ("alpha", "alpha"),
        ("beta", "beta"),
    ]


def test_iter_yields_keys():
    reg = _make_registry()
    assert list(reg) == ["alpha", "beta"]


def test_check_sql_renders_in_clause():
    reg = _make_registry(column="kind")
    assert reg.check_sql() == "kind IN ('alpha', 'beta')"


def test_check_sql_uses_configured_column():
    reg = _make_registry(column="type")
    assert reg.check_sql() == "type IN ('alpha', 'beta')"


def test_check_sql_single_entry():
    reg: DiscriminatorRegistry[_FixtureSpec] = DiscriminatorRegistry(
        column="kind",
        specs={"only": _FixtureSpec(name="only", payload=_AlphaModel)},
    )
    assert reg.check_sql() == "kind IN ('only')"


def test_reverse_index_builds_from_key_fn():
    reg = _make_registry()
    by_payload = reg.reverse_index(lambda s: s.payload)
    assert by_payload[_AlphaModel].name == "alpha"
    assert by_payload[_BetaModel].name == "beta"
    assert set(by_payload) == {_AlphaModel, _BetaModel}


def test_reverse_index_collisions_last_wins():
    """Documented semantic: last-wins, matching dict-comprehension behavior."""
    reg: DiscriminatorRegistry[_FixtureSpec] = DiscriminatorRegistry(
        column="kind",
        specs={
            "first": _FixtureSpec(name="first", payload=_AlphaModel),
            "second": _FixtureSpec(name="second", payload=_AlphaModel),
        },
    )
    by_payload = reg.reverse_index(lambda s: s.payload)
    assert by_payload[_AlphaModel].name == "second"
