"""Tests for ``make_post_stub`` — the contract-test Post-stub factory.

The stub's per-column default values are inferred from the SQLAlchemy
column type. These tests pin the type-dispatch rules (JSON → ``[]``,
Boolean → ``False``, Uuid → fresh ``UUID``, Text → enum default or
``"stub <name>"``) so future detail-model changes can't silently
re-introduce the "stub age_groups" crashes that motivated the
introspection rewrite.

The acceptance test at the bottom (`test_stub_renders_detail_html`)
renders the real ``posts/detail.html`` template against each kind's
stub — that's the canary: if a future detail-model column needs
special treatment (e.g. a new enum-typed Text column with no
``_ENUM_DEFAULTS`` entry), the canary fails at test time rather
than waiting for the next contract pair to surface it.
"""

import uuid
from datetime import datetime, timezone

import pytest

from src.domain.models import POST_KINDS
from tests.test_contract.tests.shared.mock_data_factory import make_post_stub

_KINDS = ["referral", "clinician_opening", "program_intake"]


# --- Defaults: per-column type-dispatch --------------------------------


@pytest.mark.parametrize("kind", _KINDS)
def test_json_columns_default_to_empty_list(kind):
    """JSON columns (`age_groups`, `languages`, `services`, etc.) are
    iterated in the detail template. An empty list is the safe default
    — the template's `{% for x in ... %}` blocks render nothing
    without crashing."""
    post = make_post_stub(kind, owner_id=uuid.uuid4())
    detail = getattr(post, POST_KINDS[kind].detail_relationship)
    # Every kind carries at least these JSON columns.
    for json_field in ("age_groups", "languages", "services", "desired_times"):
        if hasattr(detail, json_field):
            assert (
                getattr(detail, json_field) == []
            ), f"{kind}.{json_field} expected []; got {getattr(detail, json_field)!r}"


def test_pa_and_program_settings_default_to_empty_list():
    """PA + program detail rows carry `settings`; CR does not. The
    default applies wherever the column exists."""
    for kind in ("clinician_opening", "program_intake"):
        post = make_post_stub(kind, owner_id=uuid.uuid4())
        detail = getattr(post, POST_KINDS[kind].detail_relationship)
        assert detail.settings == []


def test_pa_and_program_genders_default_to_empty_list():
    """PA + program hold `genders` as a list; CR has a scalar `gender`."""
    for kind in ("clinician_opening", "program_intake"):
        post = make_post_stub(kind, owner_id=uuid.uuid4())
        detail = getattr(post, POST_KINDS[kind].detail_relationship)
        assert detail.genders == []


def test_uuid_columns_get_fresh_uuids():
    """PA's `provider_id` and program's `program_id` are Uuid columns
    — the stub generates a fresh UUID per call so two consecutive
    stubs don't share an id."""
    pa1 = make_post_stub("clinician_opening", owner_id=uuid.uuid4())
    pa2 = make_post_stub("clinician_opening", owner_id=uuid.uuid4())
    pid1 = pa1.opening_detail.provider_id
    pid2 = pa2.opening_detail.provider_id
    assert isinstance(pid1, uuid.UUID)
    assert isinstance(pid2, uuid.UUID)
    assert pid1 != pid2


def test_text_columns_get_stub_string():
    """Free-text columns (CR's `description`, PA's `schedule_text`,
    etc.) fall through to the readable ``"stub <name>"`` placeholder."""
    cr = make_post_stub("referral", owner_id=uuid.uuid4())
    assert cr.referral_detail.description == "stub description"
    assert cr.referral_detail.location_city == "stub location_city"
    assert cr.referral_detail.treatment_modality == "stub treatment_modality"

    pa = make_post_stub("clinician_opening", owner_id=uuid.uuid4())
    assert pa.opening_detail.description == "stub description"
    assert pa.opening_detail.schedule_text == "stub schedule_text"
    assert pa.opening_detail.website == "stub website"


# --- Defaults: enum-typed Text columns (per-kind registry) -------------


def test_cr_enum_defaults_render_via_label_dict():
    """CR's enum-typed Text columns must default to valid enum
    members so the detail template's display-label lookup resolves.
    Pin each column to its `_ENUM_DEFAULTS["referral"]` value."""
    cr = make_post_stub("referral", owner_id=uuid.uuid4())
    d = cr.referral_detail
    assert d.location_in_person == "no"
    assert d.location_virtual == "no"
    assert d.gender == "prefer_not_to_say"
    assert d.network_preference == "no_preference"
    assert d.location_state == "NY"
    # `insurance_carrier` is nullable + gated on
    # `network_preference != "no_preference"`. None keeps the detail
    # template's gating clean.
    assert d.insurance_carrier is None


def test_pa_has_no_enum_text_columns_on_detail_row():
    """PA's enum-typed fields (in_person_sessions, virtual_sessions,
    in_network_carriers, ...) live on the linked Provider, not on the
    detail row itself. The detail row has no CHECK-constrained Text
    columns, so the enum-defaults registry for PA is empty."""
    pa = make_post_stub("clinician_opening", owner_id=uuid.uuid4())
    # All fields on the detail row are list-typed JSON, Uuid, or
    # plain Text — none are enum-checked.
    assert isinstance(pa.opening_detail.services, list)
    assert isinstance(pa.opening_detail.provider_id, uuid.UUID)
    assert pa.opening_detail.description == "stub description"


# --- Overrides ---------------------------------------------------------


def test_field_overrides_replace_defaults():
    """Callers passing ``**field_overrides`` win over the per-column
    default — gives stubs an escape hatch for fields the default
    doesn't fit (e.g. supplying a populated services list to render
    multiple icon rows)."""
    post = make_post_stub(
        "referral",
        owner_id=uuid.uuid4(),
        services=["psychotherapy", "medication_management"],
        gender="female",
        description="Looking for a therapist.",
    )
    d = post.referral_detail
    assert d.services == ["psychotherapy", "medication_management"]
    assert d.gender == "female"
    assert d.description == "Looking for a therapist."


def test_field_overrides_for_unknown_field_are_passed_through():
    """The factory doesn't filter overrides against the spec — a
    caller can attach an unrelated attribute (e.g. a relationship that
    isn't a column) and it ends up on the `SimpleNamespace`. Useful
    for adding `provider` (PA) / `program` (program) relationships
    that the column-driven defaults can't populate."""
    post = make_post_stub(
        "clinician_opening",
        owner_id=uuid.uuid4(),
        provider=object(),  # arbitrary stand-in for the relationship
    )
    assert post.opening_detail.provider is not None


# --- Acceptance: template render canary --------------------------------


def test_stub_renders_detail_html_without_errors():
    """The canary test for the whole factory: render each kind's
    detail template against its stub. If a future detail-model column
    needs special treatment (e.g. a new enum-typed Text column) and
    someone forgot to add an `_ENUM_DEFAULTS` entry, the template
    crashes here at test time rather than waiting for a contract pair
    to fail with a Playwright timeout.

    Two URL families exist: `/referrals` (kind-locked leaf) and
    `/openings` (subset-supertype listing both availability subkinds).
    The canary walks all three kinds; both availability subkinds
    render through the same `openings/detail.html` because the
    /openings face owns them end-to-end."""
    from src.framework.rendering.templating import templates

    env = templates.env

    # Map kind -> (URL family, context variable name used by the
    # template). The variable name is `spec.name` from the entity spec
    # that owns the URL family. /referrals uses `referral`; /openings
    # uses `opening` (singular umbrella term, both subkinds bind to it).
    _KIND_TO_FAMILY_AND_VAR = {
        "referral": ("referrals", "referral"),
        "clinician_opening": ("openings", "opening"),
        "program_intake": ("openings", "opening"),
    }
    for kind in _KINDS:
        family, var = _KIND_TO_FAMILY_AND_VAR[kind]
        template = env.get_template(f"{family}/detail.html")
        post = make_post_stub(kind, owner_id=uuid.uuid4())

        class _RequestStub:
            class _Url:
                path = f"/{family}/stub"

            url = _Url()

            class _QueryParams:
                @staticmethod
                def get(_):
                    return None

            query_params = _QueryParams()

        # The detail template reads the post under the face's
        # `spec.name`-derived context key. /referrals uses `referral`;
        # /openings uses `opening` (the umbrella name for both
        # availability subkinds).
        html = template.render(
            **{var: post},
            entity_name=var,
            request=_RequestStub(),
            can_edit=True,
            is_authenticated=True,
            is_admin=False,
            current_username="tester",
            current_user_id=uuid.uuid4(),
            is_development=False,
        )
        # Sanity: the post card lands in the output with the right
        # `data-kind`. If a render error caused a stack trace partway
        # through, the article wouldn't be present.
        assert f'data-kind="{kind}"' in html, (
            f"{family}/detail.html for kind={kind!r} did not render the post "
            "card; the template probably crashed mid-render"
        )


# --- Meta: stub shape sanity -------------------------------------------


@pytest.mark.parametrize("kind", _KINDS)
def test_stub_populates_only_its_kind_detail_relationship(kind):
    """The stub sets `<kind>_detail` on the post and leaves the other
    kinds' detail relationships at None so template
    `{% if post.X_detail %}` checks behave the way they would for a
    real persisted post."""
    post = make_post_stub(kind, owner_id=uuid.uuid4())
    own_rel = POST_KINDS[kind].detail_relationship
    assert getattr(post, own_rel) is not None
    for other_kind, other_spec in POST_KINDS.items():
        if other_kind == kind:
            continue
        assert getattr(post, other_spec.detail_relationship) is None


def test_stub_sets_post_metadata():
    """Every stub carries `id`, `kind`, `owner_id`, `owner`,
    `created_at`, `updated_at` — the fields any template reads
    regardless of kind."""
    pid = uuid.uuid4()
    oid = uuid.uuid4()
    post = make_post_stub(
        "referral",
        post_id=pid,
        owner_id=oid,
        owner_username="alice",
    )
    assert post.id == pid
    assert post.kind == "referral"
    assert post.owner_id == oid
    assert post.owner.username == "alice"
    assert isinstance(post.created_at, datetime)
    assert post.created_at.tzinfo == timezone.utc
