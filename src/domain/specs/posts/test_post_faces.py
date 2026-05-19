"""Per-kind face invariants for the polymorphic post entity.

The three faces (`REFERRAL_ENTITY`, `OPENING_ENTITY`, `INTAKE_ENTITY`)
are nearly-identical EntitySpecs differing only in `name`,
`url_collection`, `discriminator_value`, and the per-kind
create/update adapters. These tests pin the invariants that the URL
split rests on, so a future edit that drifts one face from the others
trips a failing test instead of silently breaking the URL family
contract.
"""

from src.domain.models import POST_KINDS
from src.domain.specs.posts import (
    INTAKE_ENTITY,
    OPENING_ENTITY,
    REFERRAL_ENTITY,
)

_FACES = (REFERRAL_ENTITY, OPENING_ENTITY, INTAKE_ENTITY)


def test_each_face_has_a_unique_url_collection():
    collections = [f.url_collection for f in _FACES]
    assert collections == ["referrals", "openings", "intakes"]
    assert len(set(collections)) == 3


def test_each_face_locks_to_its_own_kind():
    assert REFERRAL_ENTITY.discriminator_value == "referral"
    assert OPENING_ENTITY.discriminator_value == "opening"
    assert INTAKE_ENTITY.discriminator_value == "intake"


def test_each_face_kind_is_registered_in_post_kinds():
    """`discriminator_value` must be a known kind — the framework
    validates at construction time, but pinning here keeps the
    registry-aware contract obvious to readers."""
    for face in _FACES:
        assert face.discriminator_value in POST_KINDS.names


def test_all_faces_share_one_audited_resource():
    """`audit_log.resource_type` is a single string per row; the three
    faces must share one `AuditedResource` instance so audit rows
    persist as ``"post"`` regardless of which URL family wrote them.

    A drift here would split the audit history three ways and break
    audit-log readers that filter by ``resource_type='post'``."""
    assert REFERRAL_ENTITY.audit is OPENING_ENTITY.audit
    assert OPENING_ENTITY.audit is INTAKE_ENTITY.audit
    assert REFERRAL_ENTITY.audit.type == "post"


def test_all_faces_share_the_post_kinds_registry():
    """Faces still need the registry to look up per-kind detail models
    on create/update (handle_create / handle_update walk
    `spec.discriminator[payload.kind]`)."""
    for face in _FACES:
        assert face.discriminator is POST_KINDS


def test_faces_drop_kind_filter_on_search_form():
    """The six surviving filters (q, posted_by, state, city, age_group,
    language) appear on every face's search form. The seventh filter
    (`kind`) lived on the old supertype only — each face is bound to
    one kind by `discriminator_value`, so a kind picker on the search
    form would be misleading."""
    for face in _FACES:
        filter_names = [f.name for f in face.filters]
        assert "kind" not in filter_names
        assert set(filter_names) == {
            "q",
            "posted_by",
            "state",
            "city",
            "age_group",
            "language",
        }


def test_each_face_uses_per_kind_adapters():
    """Each face's `create_adapter` is the single-kind schema (e.g.
    `ReferralCreate`), not the discriminated union — so form submissions
    on `/referrals/form` go through `ReferralCreate` validation and only
    accept ``kind="referral"``."""
    from src.domain.logic.posts.schema import (
        IntakeCreate,
        IntakeUpdate,
        OpeningCreate,
        OpeningUpdate,
        ReferralCreate,
        ReferralUpdate,
    )

    assert REFERRAL_ENTITY.create_adapter_class is ReferralCreate
    assert REFERRAL_ENTITY.update_adapter_class is ReferralUpdate
    assert OPENING_ENTITY.create_adapter_class is OpeningCreate
    assert OPENING_ENTITY.update_adapter_class is OpeningUpdate
    assert INTAKE_ENTITY.create_adapter_class is IntakeCreate
    assert INTAKE_ENTITY.update_adapter_class is IntakeUpdate
