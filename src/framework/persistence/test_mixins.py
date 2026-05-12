"""Tests for SQLAlchemy column-group mixins (#451)."""

from src.domain.models import ClientReferralDetail, Provider
from src.framework.persistence.mixins import LocationMixin


def test_both_consumer_tables_carry_the_three_location_columns():
    """The mixin must contribute the same three column names to every
    consuming table. If the column names ever diverge between
    Provider and ClientReferralDetail, the mixin's whole reason to
    exist evaporates — surface that here."""
    for cls in (Provider, ClientReferralDetail):
        cols = {c.name for c in cls.__table__.columns}
        assert {"location_city", "location_state", "location_zip"} <= cols


def test_location_columns_are_not_null_on_each_table():
    """Both consumers want ``NOT NULL`` on the three columns. A bare
    ``Column(...)`` on a mixin is shared across subclasses and the
    nullability silently inverts on the second consumer — keep the
    invariant pinned here so a regression surfaces immediately."""
    for cls in (Provider, ClientReferralDetail):
        for name in ("location_city", "location_state", "location_zip"):
            col = cls.__table__.c[name]
            assert col.nullable is False, f"{cls.__name__}.{name} is nullable"


def test_check_constraint_is_table_prefixed_per_consumer():
    """The mixin deliberately does not contribute the
    ``location_state`` CHECK constraint — CHECK names are table-
    prefixed (``ck_<table>_location_state``), so each consumer's
    ``__table_args__`` owns its own copy. The mixin's docstring
    documents this; pin it as a test so a future "let's move the
    constraint into the mixin" attempt fails loud."""
    p_ck_names = {c.name for c in Provider.__table__.constraints if c.name}
    cr_ck_names = {c.name for c in ClientReferralDetail.__table__.constraints if c.name}
    assert "ck_providers_location_state" in p_ck_names
    assert "ck_client_referral_details_location_state" in cr_ck_names


def test_location_property_returns_dict_view():
    """The mixin exposes a Python-side ``location`` property that
    returns a dict view of the three columns. Pydantic Read schemas
    consume this via ``from_attributes=True`` — see
    :class:`src.domain.logic.providers.schema.ProviderRead`."""
    p = Provider(
        owner_id="00000000-0000-0000-0000-000000000001",
        practice_name="X",
        location_city="Boise",
        location_state="ID",
        location_zip="83702",
        in_person_sessions="yes",
        virtual_sessions="no",
    )
    assert p.location == {"city": "Boise", "state": "ID", "zip": "83702"}


def test_mixin_is_class_level_not_shared_instance_state():
    """Each consuming class must get its own Column objects — a
    regression test against the SQLAlchemy gotcha that bare
    ``Column(...)`` on a mixin is shared (via class-attribute lookup)
    across every subclass. ``declared_attr`` solves it; this test
    pins the assumption."""
    p_city = Provider.__table__.c.location_city
    cr_city = ClientReferralDetail.__table__.c.location_city
    assert p_city is not cr_city
    assert p_city.table.name == "providers"
    assert cr_city.table.name == "client_referral_details"


def test_location_mixin_module_export():
    """Surface-level smoke that the mixin lives where the README
    documents (``src/framework/persistence/mixins.py``)."""
    assert LocationMixin.__module__ == "src.framework.persistence.mixins"
