"""Tests for SQLAlchemy column-group mixins (#451).

Post-remodel, both location-carrying models declare their columns
inline: ``ReferralDetail`` and ``ClinicianAffiliation`` each carry a
``(city, state)`` pair (no ZIP — both model a practice/client region,
not a postal address) rather than mixing in :class:`LocationMixin`. The
mixin still exists (it owns the full ``(city, state, zip)`` triple +ZIP
+ the ``location`` dict view) for any future consumer; these tests pin
the inline column contract on the two real tables and the mixin's
module home.
"""

from src.domain.models import ClinicianAffiliation, ReferralDetail
from src.framework.persistence.mixins import LocationMixin


def test_consumer_tables_carry_the_location_column_names():
    """``ClinicianAffiliation`` and ``ReferralDetail`` each carry a flat
    ``(city, state)`` pair and no ZIP — both model a region, not a
    postal address. Pin the contract so a column rename or an accidental
    ZIP reintroduction surfaces here.
    """
    aff_cols = {c.name for c in ClinicianAffiliation.__table__.columns}
    assert {"location_city", "location_state"} <= aff_cols
    assert "location_zip" not in aff_cols
    # Referral side: city + state only, no zip.
    ref_cols = {c.name for c in ReferralDetail.__table__.columns}
    assert {"location_city", "location_state"} <= ref_cols
    assert "location_zip" not in ref_cols


def test_location_columns_nullability_per_table():
    """ReferralDetail keeps ``NOT NULL`` on ``location_state`` but allows
    ``NULL`` on ``location_city`` — a referral only needs a city for
    in-person sessions, enforced conditionally on the wire by
    ``REFERRAL_CONDITIONAL_RULES`` (see
    ``src/domain/logic/posts/conditional_fields.py``), not by a column
    constraint. ClinicianAffiliation allows ``NULL`` on both
    ``location_city`` and ``location_state`` (location is deferred in the
    fast-path onboarding wizard). Pin every direction so a regression
    surfaces immediately."""
    assert ReferralDetail.__table__.c["location_state"].nullable is False
    assert ReferralDetail.__table__.c["location_city"].nullable is True
    for name in ("location_city", "location_state"):
        aff_col = ClinicianAffiliation.__table__.c[name]
        assert aff_col.nullable is True, f"ClinicianAffiliation.{name} must be nullable"


def test_check_constraint_is_table_prefixed_per_consumer():
    """CHECK names are table-prefixed
    (``ck_<table>_location_state``), so each consumer's
    ``__table_args__`` owns its own copy. Pin both so a future "share the
    constraint" attempt fails loud."""
    a_ck_names = {c.name for c in ClinicianAffiliation.__table__.constraints if c.name}
    cr_ck_names = {c.name for c in ReferralDetail.__table__.constraints if c.name}
    assert "ck_clinician_affiliations_location_state" in a_ck_names
    assert "ck_referral_details_location_state" in cr_ck_names


def test_location_columns_are_per_table_not_shared_instance_state():
    """Each table must get its own Column objects — pin that the inline
    declarations on the two tables are distinct objects bound to their
    own table."""
    a_city = ClinicianAffiliation.__table__.c.location_city
    cr_city = ReferralDetail.__table__.c.location_city
    assert a_city is not cr_city
    assert a_city.table.name == "clinician_affiliations"
    assert cr_city.table.name == "referral_details"


def test_location_mixin_module_export():
    """Surface-level smoke that the mixin lives where the README
    documents (``src/framework/persistence/mixins.py``)."""
    assert LocationMixin.__module__ == "src.framework.persistence.mixins"
