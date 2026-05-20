"""Face invariants for the polymorphic post entity.

Two URL families exist:

  - `REFERRAL_ENTITY` at `/referrals` — kind-locked leaf
    (`kind='referral'`), uses the `ReferralCreate` / `ReferralUpdate`
    per-kind schemas.
  - `OPENING_ENTITY` at `/openings` — subset-supertype listing both
    availability subkinds (`kind ∈ {clinician_opening,
    program_intake}`), uses the `OpeningsCreate` / `OpeningsUpdate`
    discriminated-union adapters scoped to the subset.

These tests pin the invariants that the URL split rests on so a future
edit that drifts one face from its declared shape trips a failing test
instead of silently breaking the URL contract.
"""

from src.domain.models import POST_KINDS
from src.domain.specs.posts import OPENING_ENTITY, REFERRAL_ENTITY

_FACES = (REFERRAL_ENTITY, OPENING_ENTITY)


def test_url_collections_are_unique():
    collections = [f.url_collection for f in _FACES]
    assert collections == ["referrals", "openings"]
    assert len(set(collections)) == len(collections)


def test_referral_face_is_kind_locked():
    assert REFERRAL_ENTITY.discriminator_value == "referral"
    assert REFERRAL_ENTITY.discriminator_values is None


def test_openings_face_is_subset_supertype():
    """`/openings` lists both availability subkinds and dispatches
    create / edit by `?kind=X`."""
    assert OPENING_ENTITY.discriminator_value is None
    assert OPENING_ENTITY.discriminator_values == (
        "clinician_opening",
        "program_intake",
    )


def test_face_kind_bindings_are_registered_in_post_kinds():
    """Every kind a face references must be in the registry; the
    framework already validates this at construction time, but pinning
    here keeps the registry-aware contract obvious to readers."""
    assert REFERRAL_ENTITY.discriminator_value in POST_KINDS.names
    for kind in OPENING_ENTITY.discriminator_values:
        assert kind in POST_KINDS.names


def test_both_faces_share_one_audited_resource():
    """`audit_log.resource_type` is a single string per row; both faces
    must share one `AuditedResource` instance so audit rows persist as
    ``"post"`` regardless of which URL family wrote them. A drift here
    would split the audit history and break audit-log readers that
    filter by ``resource_type='post'``."""
    assert REFERRAL_ENTITY.audit is OPENING_ENTITY.audit
    assert REFERRAL_ENTITY.audit.type == "post"


def test_both_faces_share_the_post_kinds_registry():
    """Faces still need the registry to look up per-kind detail models
    on create/update (handle_create / handle_update walk
    `spec.discriminator[payload.kind]`)."""
    for face in _FACES:
        assert face.discriminator is POST_KINDS


def test_faces_drop_kind_filter_on_search_form():
    """The six surviving filters (q, posted_by, state, city, age_group,
    language) appear on every face's search form. The seventh filter
    (`kind`) lived on the old supertype only — `/referrals` is locked to
    one kind, and `/openings` is bound to its subset by the framework's
    `discriminator_values` lock, so a user-facing kind picker would be
    redundant on both."""
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


def test_referral_face_uses_per_kind_adapter():
    """`/referrals` is kind-locked; its adapter is the single-kind
    `ReferralCreate` / `ReferralUpdate` so form submissions only accept
    ``kind="referral"``."""
    from src.domain.logic.posts.schema import ReferralCreate, ReferralUpdate

    assert REFERRAL_ENTITY.create_adapter_class is ReferralCreate
    assert REFERRAL_ENTITY.update_adapter_class is ReferralUpdate


def test_openings_face_uses_subset_union_adapter():
    """`/openings` is subset-supertype; its adapter is a discriminated
    union over the two availability subkinds, so the Pydantic layer
    rejects ``kind="referral"`` payloads with 422 before the handler
    runs. The adapter arrives at the spec pre-wrapped in a TypeAdapter,
    so `create_adapter_class` / `update_adapter_class` stay `None` and
    `create_adapter` / `update_adapter` carry the adapters."""
    from src.domain.logic.posts.schema import (
        openings_create_adapter,
        openings_update_adapter,
    )

    assert OPENING_ENTITY.create_adapter is openings_create_adapter
    assert OPENING_ENTITY.update_adapter is openings_update_adapter
    assert OPENING_ENTITY.create_adapter_class is None
    assert OPENING_ENTITY.update_adapter_class is None
