"""Tests for the declarative filter types.

Pins:
- URL contract (annotation + default produced for each Filter subclass).
- The ``to_query_param()`` bridge to the legacy ``QueryParam`` shape.
- ``ChoiceFilter.value_type`` tightens validation when the choice
  universe is fixed at startup (e.g. post kinds).
"""

from typing import Literal, get_args, get_origin

from src.framework.dispatch.filters import ChoiceFilter, Filter, TextFilter
from src.framework.dispatch.resource_routes import QueryParam


def test_text_filter_url_contract_is_optional_str():
    f = TextFilter(name="q", label="Search")
    assert f.annotation == (str | None)
    assert f.default is None
    assert f.kind == "text"


def test_text_filter_to_query_param_round_trip():
    f = TextFilter(name="q", label="Search", placeholder="Type to search")
    qp = f.to_query_param()
    assert isinstance(qp, QueryParam)
    assert qp.name == "q"
    assert qp.annotation == (str | None)
    assert qp.default is None


def test_text_filter_display_label_falls_back_to_name():
    f = TextFilter(name="q")
    assert f.display_label == "q"


def test_text_filter_display_label_uses_explicit_label():
    f = TextFilter(name="q", label="Search posts")
    assert f.display_label == "Search posts"


def test_choice_filter_single_value_url_contract():
    f = ChoiceFilter(
        name="kind",
        label="Type",
        choices=(("referral", "Seeking"), ("opening", "Offering")),
    )
    assert f.multi is False
    assert f.annotation == (str | None)
    assert f.default is None
    assert f.kind == "choice"


def test_choice_filter_multi_url_contract_is_list_of_str():
    f = ChoiceFilter(
        name="state",
        label="State",
        choices=(("NY", "New York"), ("NJ", "New Jersey")),
        multi=True,
    )
    ann = f.annotation
    # `list[str] | None` — union with `list[str]` on one side.
    origin = get_origin(ann)
    args = get_args(ann)
    assert origin is not None  # it's a union
    assert any(get_origin(a) is list for a in args if a is not type(None))


def test_choice_filter_value_type_tightens_annotation():
    """A `Literal` `value_type` constrains the param to declared
    values — FastAPI rejects unknown ones with 422 at the route layer."""
    kinds = Literal["referral", "opening"]
    f = ChoiceFilter(
        name="kind",
        label="Type",
        choices=(("referral", "Seeking"),),
        value_type=kinds,
    )
    # annotation should be `kinds | None`
    args = get_args(f.annotation)
    assert kinds in args
    assert type(None) in args


def test_choice_filter_radio_flag_defaults_to_false():
    """`radio=True` is the radio-toggle render opt-in for single-select
    `ChoiceFilter`s; the default `False` keeps the historical `<select>`
    rendering for every other single-select filter."""
    f = ChoiceFilter(name="kind", choices=(("a", "A"),))
    assert f.radio is False
    f = ChoiceFilter(name="kind", choices=(("a", "A"),), radio=True)
    assert f.radio is True


def test_choice_filter_to_query_param_preserves_default_and_annotation():
    f = ChoiceFilter(
        name="kind",
        label="Type",
        choices=(("a", "A"),),
    )
    qp = f.to_query_param()
    assert qp.name == "kind"
    assert qp.annotation == f.annotation
    assert qp.default == f.default


def test_filter_is_frozen_dataclass():
    """Specs are module-level constants; mutating a Filter after
    construction is always a bug. `dataclass(frozen=True)` makes it a
    `FrozenInstanceError`."""
    import dataclasses

    f = TextFilter(name="q")
    try:
        f.name = "other"  # type: ignore[misc]
    except dataclasses.FrozenInstanceError:
        return
    raise AssertionError("Filter should be frozen")


def test_filter_base_class_is_abstract_for_annotation():
    """The base `Filter` shouldn't be used directly — subclasses
    provide `annotation` / `default`. Hitting the base raises a clear
    NotImplementedError rather than silently producing a broken URL."""
    base = Filter(name="x")
    import pytest

    with pytest.raises(NotImplementedError):
        _ = base.annotation
    with pytest.raises(NotImplementedError):
        _ = base.default
