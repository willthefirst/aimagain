"""URL-family invariants for the three post resource families.

After #628 the polymorphic `Post` model is no longer exposed at a
shared `/posts` URL — each kind has its own URL family. This module
pins the cross-family invariants (parameterized over the three kinds)
that the framework's kind-lock plumbing buys us:

  - every URL responds 200 on the family's collection / form /
    search endpoint;
  - a row of one kind 404s when reached via another kind's URL
    family (e.g. `/referrals/{opening_id}` 404s);
  - `/<family>/form` goes straight to the create form — no picker;
  - the kind filter is absent from the search form (each family is
    bound to its own kind by `discriminator_value`);
  - owner authz invariants survive the URL split (non-owner can't
    patch/delete; admin can).

Per-kind detail-rendering assertions (which DOM elements a referral
card surfaces vs. an opening card vs. an intake card) are the long
tail and are deferred to a follow-up issue — the old `test_posts.py`
covered them but its 96 cases pinned the single-URL world. The
framework + spec + face tests (`test_post_faces.py`, the framework
dispatch suite) pin the structural invariants this PR rests on.
"""

import uuid

import pytest
from httpx import AsyncClient
from selectolax.parser import HTMLParser
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from src.domain.models import Organization, Post, Program, Provider
from tests.helpers import (
    create_test_user,
    make_intake_detail,
    make_opening_detail,
    make_program,
    make_provider_with_org,
    make_referral_detail,
    opening_payload,
    promote_to_admin,
)

pytestmark = pytest.mark.asyncio


# --- Per-kind row builders -----------------------------------------------


def _referral_post(*, owner_id, description: str = "ref", **overrides) -> Post:
    post = Post(kind="referral", owner_id=owner_id)
    post.referral_detail = make_referral_detail(description=description, **overrides)
    return post


def _opening_post(
    *, owner_id, practice_name: str = "Practice", provider: Provider | None = None
) -> Post:
    if provider is None:
        provider = make_provider_with_org(
            owner_id=owner_id, practice_name=practice_name
        )
    if provider.id is None:
        provider.id = uuid.uuid4()
    post = Post(kind="clinician_opening", owner_id=owner_id)
    detail = make_opening_detail(provider_id=provider.id)
    detail.provider = provider
    post.opening_detail = detail
    return post


def _intake_post(*, owner_id, org_id, program: Program | None = None) -> Post:
    """Build a `kind='program_intake'` Post row with a fresh Program +
    IntakeDetail attached. `org_id` is required because Program FKs to
    Organization and the test session needs the parent row present."""
    if program is None:
        program = make_program(owner_id=owner_id, org_id=org_id)
    if program.id is None:
        program.id = uuid.uuid4()
    post = Post(kind="program_intake", owner_id=owner_id)
    detail = make_intake_detail(program_id=program.id)
    detail.program = program
    post.intake_detail = detail
    return post


# Each kind paired with: its URL family, the row builder, and the
# context key the framework injects on the list page (one per
# `spec.url_collection`).
_FAMILIES = [
    ("referral", "referrals", _referral_post),
    ("clinician_opening", "openings", _opening_post),
]


# --- Routes mount + 200 smoke --------------------------------------------


@pytest.mark.parametrize("kind,collection,_builder", _FAMILIES)
async def test_list_route_responds_200(
    kind: str,
    collection: str,
    _builder,
    authenticated_client: AsyncClient,
    logged_in_user,
):
    """Each family's list route responds 200 on an empty database."""
    response = await authenticated_client.get(f"/{collection}")
    assert response.status_code == 200


@pytest.mark.parametrize("kind,collection,_builder", _FAMILIES)
async def test_search_route_responds_200(
    kind: str,
    collection: str,
    _builder,
    authenticated_client: AsyncClient,
    logged_in_user,
):
    response = await authenticated_client.get(f"/{collection}/search")
    assert response.status_code == 200


@pytest.mark.parametrize("kind,collection,_builder", _FAMILIES)
async def test_form_new_route_responds_200(
    kind: str,
    collection: str,
    _builder,
    authenticated_client: AsyncClient,
    logged_in_user,
):
    """`/<family>/form` goes straight to the create form — the kind
    picker that lived on the old `/posts/form` is gone; each family
    owns one kind. The page must render without a `?kind=` query
    param."""
    response = await authenticated_client.get(f"/{collection}/form")
    assert response.status_code == 200


# --- 404 on cross-family ID ----------------------------------------------


async def test_detail_404s_when_id_belongs_to_other_kind(
    authenticated_client: AsyncClient,
    db_test_session_manager: async_sessionmaker[AsyncSession],
    logged_in_user,
):
    """The kind-lock 404s a row of one kind when reached via another
    family's URL — e.g. `GET /referrals/{opening_id}` returns 404
    indistinguishably from a truly-missing row. This is the structural
    promise the URL split rests on; pinned at the route level."""
    author = create_test_user(username=f"a-{uuid.uuid4()}")
    referral = _referral_post(owner_id=author.id)
    opening = _opening_post(owner_id=author.id)
    async with db_test_session_manager() as session:
        async with session.begin():
            session.add(author)
            session.add(referral)
            session.add(opening)

    # `referral_id` reached via `/openings/` 404s.
    response = await authenticated_client.get(f"/openings/{referral.id}")
    assert response.status_code == 404
    # And vice versa.
    response = await authenticated_client.get(f"/referrals/{opening.id}")
    assert response.status_code == 404
    # Each is reachable through its own family.
    assert (
        await authenticated_client.get(f"/referrals/{referral.id}")
    ).status_code == 200
    assert (
        await authenticated_client.get(f"/openings/{opening.id}")
    ).status_code == 200


async def test_edit_form_404s_when_id_belongs_to_other_kind(
    authenticated_client: AsyncClient,
    db_test_session_manager: async_sessionmaker[AsyncSession],
    logged_in_user,
):
    """Same lock applies to `/<family>/{id}/form` — an edit URL for
    the wrong family 404s."""
    author = logged_in_user
    referral = _referral_post(owner_id=author.id)
    opening = _opening_post(owner_id=author.id)
    async with db_test_session_manager() as session:
        async with session.begin():
            session.add(referral)
            session.add(opening)

    response = await authenticated_client.get(f"/openings/{referral.id}/form")
    assert response.status_code == 404
    response = await authenticated_client.get(f"/referrals/{opening.id}/form")
    assert response.status_code == 404


# --- Search form: kind filter is gone ------------------------------------


async def test_search_form_omits_kind_filter_on_kind_locked_face(
    authenticated_client: AsyncClient,
    logged_in_user,
):
    """The kind picker has nothing to pick on a kind-locked family
    (`/referrals` is bound to `kind='referral'`), so its search form
    must not render a `name="kind"` input."""
    response = await authenticated_client.get("/referrals/search")
    assert response.status_code == 200
    tree = HTMLParser(response.text)
    kind_inputs = tree.css('form [name="kind"]')
    assert kind_inputs == [], (
        "/referrals/search rendered a `kind` input; the family is "
        "bound to one kind by spec, so the picker has no role"
    )


async def test_search_form_renders_kind_filter_on_subset_supertype_face(
    authenticated_client: AsyncClient,
    logged_in_user,
):
    """The subset-supertype face (`/openings`) lists two subkinds.
    Its search form must render a `name="kind"` input (multi-select
    checkbox group) so the viewer can narrow to one subkind without
    leaving the URL family."""
    response = await authenticated_client.get("/openings/search")
    assert response.status_code == 200
    tree = HTMLParser(response.text)
    kind_inputs = tree.css('form [name="kind"]')
    assert kind_inputs, "/openings/search did not render a `kind` input"
    # Both subkinds appear as checkbox values.
    values = {inp.attributes.get("value") for inp in kind_inputs}
    assert {"clinician_opening", "program_intake"} <= values


# --- List filter: row of another kind doesn't leak in --------------------


@pytest.mark.parametrize("kind,collection,_builder", _FAMILIES)
async def test_list_only_includes_own_kind(
    kind: str,
    collection: str,
    _builder,
    authenticated_client: AsyncClient,
    db_test_session_manager: async_sessionmaker[AsyncSession],
    logged_in_user,
):
    """A `/referrals` list contains only `kind=referral` rows even
    when other kinds exist in the database. The framework's
    `handle_list` forces `kind = spec.discriminator_value` regardless
    of any `?kind=…` an attacker tries to inject."""
    author = create_test_user(username=f"a-{uuid.uuid4()}")
    own = _builder(owner_id=author.id)
    other_kind_post = (
        _opening_post(owner_id=author.id)
        if kind == "referral"
        else _referral_post(owner_id=author.id)
    )
    async with db_test_session_manager() as session:
        async with session.begin():
            session.add(author)
            session.add(own)
            session.add(other_kind_post)

    response = await authenticated_client.get(f"/{collection}")
    assert response.status_code == 200
    tree = HTMLParser(response.text)
    cards = tree.css(f"#{collection}-list > article")
    kinds = {c.attributes.get("data-kind") for c in cards}
    assert kinds == {kind}, f"/{collection} leaked a non-{kind} row: {kinds!r}"


@pytest.mark.parametrize("kind,collection,_builder", _FAMILIES)
async def test_list_kind_query_param_does_not_override_lock(
    kind: str,
    collection: str,
    _builder,
    authenticated_client: AsyncClient,
    db_test_session_manager: async_sessionmaker[AsyncSession],
    logged_in_user,
):
    """An attacker-supplied `?kind=other` on the URL is silently
    dropped — kind-locked faces stomp it with `discriminator_value`,
    subset-supertype faces intersect it with `discriminator_values`
    and fall back to the full subset when the intersection is empty.
    Either way, no rows of the wrong kind leak in."""
    author = create_test_user(username=f"a-{uuid.uuid4()}")
    own = _builder(owner_id=author.id)
    async with db_test_session_manager() as session:
        async with session.begin():
            session.add(author)
            session.add(own)

    # Pick a kind that's NOT in this face's served set:
    # - /referrals serves {referral} → "clinician_opening" is foreign.
    # - /openings serves {clinician_opening, program_intake} → "referral" is foreign.
    other_kind = "clinician_opening" if kind == "referral" else "referral"
    response = await authenticated_client.get(f"/{collection}?kind={other_kind}")
    assert response.status_code == 200
    tree = HTMLParser(response.text)
    cards = tree.css(f"#{collection}-list > article")
    kinds_in_page = {c.attributes.get("data-kind") for c in cards}
    # Foreign-kind row never leaks in; for the subset face this means
    # the wrong-kind value was clamped out of the intersection. The
    # served set is the face's invariant — `/openings` may render
    # either subkind, `/referrals` may render only `referral`.
    if kind == "referral":
        assert kinds_in_page <= {"referral"}
    else:
        assert kinds_in_page <= {"clinician_opening", "program_intake"}


async def test_openings_kind_filter_narrows_to_one_subkind(
    authenticated_client: AsyncClient,
    db_test_session_manager: async_sessionmaker[AsyncSession],
    logged_in_user,
):
    """The subset-supertype face honors a `?kind=<one of subset>`
    filter: with both subkinds in the DB, `/openings?kind=clinician_opening`
    returns only clinician_opening rows."""
    author = create_test_user(username=f"a-{uuid.uuid4()}")
    org = Organization(owner_id=author.id, name=f"Org {uuid.uuid4()}", type="clinic")
    org.id = uuid.uuid4()
    org.root_org_id = org.id
    clinician_opening = _opening_post(owner_id=author.id)
    program_intake = _intake_post(owner_id=author.id, org_id=org.id)
    async with db_test_session_manager() as session:
        async with session.begin():
            session.add(author)
            session.add(org)
            session.add(clinician_opening)
            session.add(program_intake)

    # No filter → both subkinds visible.
    response = await authenticated_client.get("/openings")
    assert response.status_code == 200
    kinds_unfiltered = {
        c.attributes.get("data-kind")
        for c in HTMLParser(response.text).css("#openings-list > article")
    }
    assert {"clinician_opening", "program_intake"} <= kinds_unfiltered

    # Filtered to one subkind → only that subkind.
    response = await authenticated_client.get("/openings?kind=clinician_opening")
    assert response.status_code == 200
    kinds_filtered = {
        c.attributes.get("data-kind")
        for c in HTMLParser(response.text).css("#openings-list > article")
    }
    assert kinds_filtered == {
        "clinician_opening"
    }, f"/openings?kind=clinician_opening returned: {kinds_filtered!r}"


# --- Owner authz invariants ----------------------------------------------


@pytest.mark.parametrize("kind,collection,builder", _FAMILIES)
async def test_non_owner_cannot_patch(
    kind: str,
    collection: str,
    builder,
    authenticated_client: AsyncClient,
    db_test_session_manager: async_sessionmaker[AsyncSession],
    logged_in_user,
):
    """A logged-in user who isn't the post owner (and isn't an admin)
    can't PATCH it — the family routes still respect
    `auth_policy=OWNER_OR_ADMIN` shared by the supertype's old spec."""
    other = create_test_user(username=f"other-{uuid.uuid4()}")
    post = builder(owner_id=other.id)
    async with db_test_session_manager() as session:
        async with session.begin():
            session.add(other)
            session.add(post)

    response = await authenticated_client.patch(
        f"/{collection}/{post.id}",
        data={"description": "hacked", "kind": kind},
    )
    assert response.status_code == 403


@pytest.mark.parametrize("kind,collection,builder", _FAMILIES)
async def test_admin_can_patch_anyone(
    kind: str,
    collection: str,
    builder,
    authenticated_client: AsyncClient,
    db_test_session_manager: async_sessionmaker[AsyncSession],
    logged_in_user,
):
    """Admins keep the cross-owner write hatch — `auth_policy=
    OWNER_OR_ADMIN`'s "or admin" branch survives the URL split."""
    await promote_to_admin(db_test_session_manager, logged_in_user.email)
    other = create_test_user(username=f"other-{uuid.uuid4()}")
    post = builder(owner_id=other.id)
    async with db_test_session_manager() as session:
        async with session.begin():
            session.add(other)
            session.add(post)

    response = await authenticated_client.patch(
        f"/{collection}/{post.id}",
        data={"description": "admin-patched", "kind": kind},
    )
    # PATCH bodies vary per kind; we don't pin success here — the
    # important assertion is "not 403". A 400 / 422 on body shape is
    # acceptable; a 403 would be the regression we want to catch.
    assert response.status_code != 403


# --- Form-error re-render (form_error_render opt-in) ---------------------


async def test_clinician_opening_create_rerenders_form_with_age_groups_error_on_htmx(
    authenticated_client: AsyncClient,
    db_test_session_manager: async_sessionmaker[AsyncSession],
    logged_in_user,
):
    """`POST /openings` (`kind=clinician_opening`) on an HX-Request with
    an empty `age_groups` returns the form re-rendered with an inline
    error on the `age_groups` `<select>` — not a JSON 422. This is the
    first callsite of the `form_error_render` opt-in on `EntitySpec`
    (see `OPENING_ENTITY` and `mount_create`'s `_render_form_with_errors`).

    The user owns one Provider so the form template's
    `current_user.providers` gate passes; the wire-valid `opening_payload`
    is sent with `age_groups=[]` to trip the schema's `min_length=1`
    constraint without dragging in unrelated validation noise.
    """
    provider = make_provider_with_org(owner_id=logged_in_user.id)
    async with db_test_session_manager() as session:
        async with session.begin():
            session.add(provider)

    payload = opening_payload(provider_id=str(provider.id))
    payload["age_groups"] = []

    response = await authenticated_client.post(
        "/openings",
        data=payload,
        headers={"HX-Request": "true"},
    )
    # Status is 200 (not 422 or 201) so HTMX swaps the response body
    # via the form's `hx-target="this" hx-swap="outerHTML"`. The JSON
    # 422 contract is preserved for non-HTMX clients (a separate test
    # below pins that branch).
    assert response.status_code == 200, response.text
    assert response.headers["content-type"].startswith("text/html")

    tree = HTMLParser(response.text)
    age_select = tree.css_first('select[name="age_groups"]')
    assert age_select is not None, "age_groups select missing from re-rendered form"
    assert (
        age_select.attributes.get("aria-invalid") == "true"
    ), "age_groups select must carry aria-invalid='true' so Pico colors it red"
    # Pico's canonical one-small-per-field slot: the helper id stays
    # `<name>-helper` whether the small carries help text or the error
    # message. With `error=` set, the small contains the error message.
    error_small = tree.css_first("small#age_groups-helper")
    assert error_small is not None, "age_groups error small missing"
    # The small carries whatever Pydantic emits for the failure mode —
    # `httpx` drops empty-list form keys so the wire payload omits
    # `age_groups` entirely and Pydantic returns "Field required"; if a
    # client submits a single empty value `min_length=1` fires with
    # "at least 1 item". We only assert *some* message survives the
    # `loc`-stripping + dict-collapse path, not its exact wording.
    assert error_small.text().strip(), "age_groups error small is empty"


async def test_clinician_opening_create_returns_json_422_without_htmx(
    authenticated_client: AsyncClient,
    db_test_session_manager: async_sessionmaker[AsyncSession],
    logged_in_user,
):
    """The same POST without `HX-Request` falls through to the existing
    JSON 422 contract — `form_error_render` is HTMX-only by design so
    non-HTMX API clients keep their machine-readable error list."""
    provider = make_provider_with_org(owner_id=logged_in_user.id)
    async with db_test_session_manager() as session:
        async with session.begin():
            session.add(provider)

    payload = opening_payload(provider_id=str(provider.id))
    payload["age_groups"] = []

    response = await authenticated_client.post("/openings", data=payload)
    assert response.status_code == 422
    body = response.json()
    # The discriminated-union adapter prefixes `loc` with the kind for
    # nested errors; `age_groups` lives under `clinician_opening`. We
    # only assert the JSON-422 contract preserves the field name
    # somewhere in `loc`, not the exact tuple shape.
    locs = [tuple(err["loc"]) for err in body["detail"]]
    assert any("age_groups" in loc for loc in locs), body
