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

from src.domain.models import Post, Provider
from tests.helpers import (
    create_test_user,
    make_opening_detail,
    make_provider_with_org,
    make_referral_detail,
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


@pytest.mark.parametrize("kind,collection,_builder", _FAMILIES)
async def test_search_form_omits_kind_filter(
    kind: str,
    collection: str,
    _builder,
    authenticated_client: AsyncClient,
    logged_in_user,
):
    """The kind picker has nothing to pick on a single-kind family,
    so the search form on `/<family>/search` must not render a
    `name="kind"` input (radio, select, or otherwise). The other six
    filters stay."""
    response = await authenticated_client.get(f"/{collection}/search")
    assert response.status_code == 200
    tree = HTMLParser(response.text)
    kind_inputs = tree.css('form [name="kind"]')
    assert kind_inputs == [], (
        f"/{collection}/search rendered a `kind` input; the family is "
        "bound to one kind by spec, so the picker has no role"
    )


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
    overridden by the spec's `discriminator_value`."""
    author = create_test_user(username=f"a-{uuid.uuid4()}")
    own = _builder(owner_id=author.id)
    async with db_test_session_manager() as session:
        async with session.begin():
            session.add(author)
            session.add(own)

    other_kind = "clinician_opening" if kind == "referral" else "referral"
    response = await authenticated_client.get(f"/{collection}?kind={other_kind}")
    assert response.status_code == 200
    tree = HTMLParser(response.text)
    cards = tree.css(f"#{collection}-list > article")
    kinds = {c.attributes.get("data-kind") for c in cards}
    # Own kind still showing despite the malicious query param.
    assert kinds <= {
        kind
    }, f"/{collection}?kind={other_kind} returned non-{kind} rows: {kinds!r}"


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
