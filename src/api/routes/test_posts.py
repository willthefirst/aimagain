"""Route-layer tests for the kind-discriminated `/posts` API.

`Post` is polymorphic on `kind`: `client_referral` and `provider_availability`
each have their own child table (joined-table inheritance — see
`src/models/post.py`). These tests confirm:

- both kinds round-trip through POST/GET/DELETE
- the unified GET /posts timeline returns rows of every kind
- the schema's discriminated union rejects unknown / missing kinds
- audit rows snapshot the kind alongside the owner

PATCH and the edit form are intentionally absent in this PR — the kinds
carry no editable fields yet, so there is nothing to update. They return
when per-kind fields land.
"""

import uuid

import pytest
from httpx import AsyncClient
from selectolax.parser import HTMLParser
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from src.models import AuditLog, ClientReferral, Post, ProviderAvailability, User
from src.repositories.audit_repository import AuditRepository
from tests.helpers import create_test_user, promote_to_admin

pytestmark = pytest.mark.asyncio


def _make_client_referral(owner: User) -> ClientReferral:
    return ClientReferral(kind="client_referral", owner_id=owner.id)


def _make_provider_availability(owner: User) -> ProviderAvailability:
    return ProviderAvailability(kind="provider_availability", owner_id=owner.id)


# --- Listing -------------------------------------------------------------


async def test_list_posts_empty(
    authenticated_client: AsyncClient,
    logged_in_user: User,
):
    """GET /posts returns HTML with empty-state message when no posts exist."""
    response = await authenticated_client.get("/posts")

    assert response.status_code == 200
    assert "text/html" in response.headers["content-type"]

    tree = HTMLParser(response.text)
    assert "No posts found" in tree.body.text()


async def test_list_posts_shows_both_kinds(
    authenticated_client: AsyncClient,
    db_test_session_manager: async_sessionmaker[AsyncSession],
    logged_in_user: User,
):
    """A unified timeline surfaces every kind, each marked with its kind label."""
    other = create_test_user(username=f"author-{uuid.uuid4()}")

    async with db_test_session_manager() as session:
        async with session.begin():
            session.add(other)
            session.add(_make_client_referral(other))
            session.add(_make_provider_availability(other))

    response = await authenticated_client.get("/posts")
    assert response.status_code == 200

    tree = HTMLParser(response.text)
    items = tree.css("ul > li")
    assert len(items) == 2

    kinds_in_dom = {
        node.attributes.get("data-kind") for node in tree.css("span.post-kind")
    }
    assert kinds_in_dom == {"client_referral", "provider_availability"}


async def test_list_posts_orders_newest_first(
    authenticated_client: AsyncClient,
    db_test_session_manager: async_sessionmaker[AsyncSession],
    logged_in_user: User,
):
    """GET /posts orders results by created_at DESC across kinds."""
    from datetime import datetime, timedelta, timezone

    author = create_test_user(username=f"author-{uuid.uuid4()}")
    older = _make_client_referral(author)
    newer = _make_provider_availability(author)

    now = datetime.now(timezone.utc)
    older.created_at = now - timedelta(days=1)
    newer.created_at = now

    async with db_test_session_manager() as session:
        async with session.begin():
            session.add(author)
            session.add(older)
            session.add(newer)

    response = await authenticated_client.get("/posts")
    assert response.status_code == 200

    tree = HTMLParser(response.text)
    items = tree.css("ul > li")
    assert len(items) == 2
    assert "provider_availability" in items[0].text()
    assert "client_referral" in items[1].text()


async def test_list_posts_unauthenticated_redirects(
    test_client: AsyncClient,
):
    """Unauthenticated browser request to /posts is redirected to login."""
    response = await test_client.get(
        "/posts", headers={"accept": "text/html"}, follow_redirects=False
    )
    assert response.status_code == 302
    assert "/auth/login" in response.headers["location"]
    assert "next=/posts" in response.headers["location"]


# --- Detail page ---------------------------------------------------------


@pytest.mark.parametrize(
    "factory,expected_kind",
    [
        (_make_client_referral, "client_referral"),
        (_make_provider_availability, "provider_availability"),
    ],
)
async def test_get_post_detail_renders_kind(
    factory,
    expected_kind,
    authenticated_client: AsyncClient,
    db_test_session_manager: async_sessionmaker[AsyncSession],
    logged_in_user: User,
):
    """GET /posts/{id} renders the detail page and surfaces the post's kind."""
    author = create_test_user(username=f"author-{uuid.uuid4()}")
    post = factory(author)

    async with db_test_session_manager() as session:
        async with session.begin():
            session.add(author)
            session.add(post)

    response = await authenticated_client.get(f"/posts/{post.id}")
    assert response.status_code == 200
    page = response.text
    assert expected_kind in page
    assert author.username in page


async def test_get_post_detail_404(
    authenticated_client: AsyncClient,
    logged_in_user: User,
):
    """GET /posts/{unknown-id} returns 404."""
    response = await authenticated_client.get(f"/posts/{uuid.uuid4()}")
    assert response.status_code == 404


async def test_get_post_detail_malformed_uuid_422(
    authenticated_client: AsyncClient,
    logged_in_user: User,
):
    """GET /posts/{not-a-uuid} returns 422 (FastAPI path validation)."""
    response = await authenticated_client.get("/posts/not-a-uuid")
    assert response.status_code == 422


# --- Create --------------------------------------------------------------


@pytest.mark.parametrize(
    "kind,model_cls",
    [
        ("client_referral", ClientReferral),
        ("provider_availability", ProviderAvailability),
    ],
)
async def test_create_post_happy_path(
    kind,
    model_cls,
    authenticated_client: AsyncClient,
    db_test_session_manager: async_sessionmaker[AsyncSession],
    logged_in_user: User,
):
    """POST /posts persists a row of the requested kind, owned by the session
    user, with the right child table populated."""
    response = await authenticated_client.post("/posts", json={"kind": kind})

    assert response.status_code == 201
    payload = response.json()
    assert "id" in payload
    new_id = uuid.UUID(payload["id"])
    expected_location = f"/posts/{new_id}"
    assert response.headers.get("Location") == expected_location
    assert response.headers.get("HX-Redirect") == expected_location

    async with db_test_session_manager() as session:
        result = await session.execute(select(model_cls).filter(model_cls.id == new_id))
        persisted = result.scalars().first()
        assert persisted is not None
        assert persisted.kind == kind
        assert persisted.owner_id == logged_in_user.id


async def test_create_post_rejects_owner_id_in_payload(
    authenticated_client: AsyncClient,
    db_test_session_manager: async_sessionmaker[AsyncSession],
    logged_in_user: User,
):
    """A client sending owner_id is rejected with 422 (extra='forbid'); no
    post is persisted."""
    other = create_test_user(username=f"other-{uuid.uuid4()}")
    async with db_test_session_manager() as session:
        async with session.begin():
            session.add(other)

    response = await authenticated_client.post(
        "/posts",
        json={"kind": "client_referral", "owner_id": str(other.id)},
    )
    assert response.status_code == 422

    async with db_test_session_manager() as session:
        result = await session.execute(select(Post))
        assert result.scalars().first() is None


async def test_create_post_rejects_unknown_field(
    authenticated_client: AsyncClient,
    logged_in_user: User,
):
    """Unknown fields (including the old title/body) are rejected with 422."""
    response = await authenticated_client.post(
        "/posts", json={"kind": "client_referral", "title": "old", "body": "shape"}
    )
    assert response.status_code == 422


@pytest.mark.parametrize(
    "payload",
    [
        {},
        {"kind": "not_a_real_kind"},
    ],
)
async def test_create_post_missing_or_unknown_kind_422(
    payload,
    authenticated_client: AsyncClient,
    logged_in_user: User,
):
    response = await authenticated_client.post("/posts", json=payload)
    assert response.status_code == 422


async def test_create_post_unauthenticated_redirects(
    test_client: AsyncClient,
):
    """Anonymous request to POST /posts is redirected to login (HTML auth flow)."""
    response = await test_client.post(
        "/posts",
        json={"kind": "client_referral"},
        headers={"accept": "text/html"},
        follow_redirects=False,
    )
    assert response.status_code == 302
    assert "/auth/login" in response.headers["location"]


# --- Create form page (GET /posts/form) ----------------------------------


async def test_get_post_form_renders_kind_selector(
    authenticated_client: AsyncClient,
    logged_in_user: User,
):
    """GET /posts/form renders the form with a kind radio for both kinds."""
    response = await authenticated_client.get("/posts/form")

    assert response.status_code == 200
    assert "text/html" in response.headers["content-type"]

    tree = HTMLParser(response.text)
    form = tree.css_first("form")
    assert form is not None
    assert form.attributes.get("hx-post") == "/posts"
    assert form.attributes.get("hx-ext") == "json-enc"

    kinds_offered = {
        node.attributes.get("value")
        for node in tree.css('input[type="radio"][name="kind"]')
    }
    assert kinds_offered == {"client_referral", "provider_availability"}


async def test_get_post_form_unauthenticated_redirects(
    test_client: AsyncClient,
):
    response = await test_client.get(
        "/posts/form",
        headers={"accept": "text/html"},
        follow_redirects=False,
    )
    assert response.status_code == 302
    assert "/auth/login" in response.headers["location"]
    assert "next=/posts/form" in response.headers["location"]


async def test_form_route_does_not_shadow_detail_route(
    authenticated_client: AsyncClient,
    db_test_session_manager: async_sessionmaker[AsyncSession],
    logged_in_user: User,
):
    """Sanity check the /posts/form ordering — a real UUID still hits the detail route."""
    post = _make_client_referral(logged_in_user)
    async with db_test_session_manager() as session:
        async with session.begin():
            session.add(post)

    response = await authenticated_client.get(f"/posts/{post.id}")
    assert response.status_code == 200
    assert "client_referral" in response.text


async def test_list_page_links_to_create_form(
    authenticated_client: AsyncClient,
    logged_in_user: User,
):
    response = await authenticated_client.get("/posts")
    assert response.status_code == 200
    tree = HTMLParser(response.text)
    link = tree.css_first('a[href="/posts/form"]')
    assert link is not None
    assert "New post" in link.text()


# --- Owner-actions partial visibility on detail page ---------------------


async def test_detail_page_shows_owner_actions_for_owner(
    authenticated_client: AsyncClient,
    db_test_session_manager: async_sessionmaker[AsyncSession],
    logged_in_user: User,
):
    post = _make_client_referral(logged_in_user)
    async with db_test_session_manager() as session:
        async with session.begin():
            session.add(post)

    response = await authenticated_client.get(f"/posts/{post.id}")
    assert response.status_code == 200
    tree = HTMLParser(response.text)
    actions = tree.css_first("span.owner-actions")
    assert actions is not None


async def test_detail_page_shows_owner_actions_for_admin(
    authenticated_client: AsyncClient,
    db_test_session_manager: async_sessionmaker[AsyncSession],
    logged_in_user: User,
):
    await promote_to_admin(db_test_session_manager, logged_in_user.email)
    other = create_test_user(username=f"other-{uuid.uuid4()}")
    post = _make_client_referral(other)
    async with db_test_session_manager() as session:
        async with session.begin():
            session.add(other)
            session.add(post)

    response = await authenticated_client.get(f"/posts/{post.id}")
    assert response.status_code == 200
    tree = HTMLParser(response.text)
    assert tree.css_first("span.owner-actions") is not None


async def test_detail_page_hides_owner_actions_for_stranger(
    authenticated_client: AsyncClient,
    db_test_session_manager: async_sessionmaker[AsyncSession],
    logged_in_user: User,
):
    other = create_test_user(username=f"other-{uuid.uuid4()}")
    post = _make_client_referral(other)
    async with db_test_session_manager() as session:
        async with session.begin():
            session.add(other)
            session.add(post)

    response = await authenticated_client.get(f"/posts/{post.id}")
    assert response.status_code == 200
    tree = HTMLParser(response.text)
    assert tree.css_first("span.owner-actions") is None


async def test_detail_page_delete_button_for_owner(
    authenticated_client: AsyncClient,
    db_test_session_manager: async_sessionmaker[AsyncSession],
    logged_in_user: User,
):
    """The owner sees a Delete button wired to DELETE /posts/{id} with a
    confirmation prompt."""
    post = _make_client_referral(logged_in_user)
    async with db_test_session_manager() as session:
        async with session.begin():
            session.add(post)

    response = await authenticated_client.get(f"/posts/{post.id}")
    assert response.status_code == 200
    tree = HTMLParser(response.text)
    actions = tree.css_first("span.owner-actions")
    assert actions is not None
    button = actions.css_first("button")
    assert button is not None
    assert button.text().strip() == "Delete"
    assert button.attributes.get("hx-delete") == f"/posts/{post.id}"
    assert button.attributes.get("hx-confirm")


async def test_detail_page_delete_button_for_admin(
    authenticated_client: AsyncClient,
    db_test_session_manager: async_sessionmaker[AsyncSession],
    logged_in_user: User,
):
    """An admin viewing another user's post sees the Delete button too."""
    await promote_to_admin(db_test_session_manager, logged_in_user.email)
    other = create_test_user(username=f"other-{uuid.uuid4()}")
    post = _make_client_referral(other)
    async with db_test_session_manager() as session:
        async with session.begin():
            session.add(other)
            session.add(post)

    response = await authenticated_client.get(f"/posts/{post.id}")
    assert response.status_code == 200
    tree = HTMLParser(response.text)
    button = tree.css_first("span.owner-actions button")
    assert button is not None
    assert button.attributes.get("hx-delete") == f"/posts/{post.id}"


# --- Audit log -----------------------------------------------------------


@pytest.mark.parametrize(
    "kind",
    ["client_referral", "provider_availability"],
)
async def test_create_post_writes_audit_row(
    kind,
    authenticated_client: AsyncClient,
    db_test_session_manager: async_sessionmaker[AsyncSession],
    logged_in_user: User,
):
    """Each successful POST /posts writes exactly one audit row carrying the
    kind."""
    response = await authenticated_client.post("/posts", json={"kind": kind})
    assert response.status_code == 201
    new_id = uuid.UUID(response.json()["id"])

    async with db_test_session_manager() as session:
        repo = AuditRepository(session)
        rows = await repo.list_for_resource(resource_type="post", resource_id=new_id)
        assert len(rows) == 1
        row = rows[0]
        assert row.actor_id == logged_in_user.id
        assert row.action == "create_post"
        assert row.before is None
        assert row.after == {
            "kind": kind,
            "owner_id": str(logged_in_user.id),
        }


async def test_failed_create_writes_no_audit_row(
    authenticated_client: AsyncClient,
    db_test_session_manager: async_sessionmaker[AsyncSession],
    logged_in_user: User,
):
    """A 422 (schema rejection) must not leak an audit row."""
    response = await authenticated_client.post("/posts", json={"kind": "not_a_kind"})
    assert response.status_code == 422

    async with db_test_session_manager() as session:
        result = await session.execute(
            select(AuditLog).filter(AuditLog.resource_type == "post")
        )
        assert result.scalars().first() is None


# --- Delete (DELETE) -----------------------------------------------------


async def test_owner_can_delete_own_post(
    authenticated_client: AsyncClient,
    db_test_session_manager: async_sessionmaker[AsyncSession],
    logged_in_user: User,
):
    """DELETE by the owner returns 204, removes the row, and sets HX-Redirect."""
    post = _make_client_referral(logged_in_user)
    async with db_test_session_manager() as session:
        async with session.begin():
            session.add(post)

    response = await authenticated_client.delete(f"/posts/{post.id}")
    assert response.status_code == 204
    assert response.headers.get("HX-Redirect") == "/posts"

    async with db_test_session_manager() as session:
        result = await session.execute(select(Post).filter(Post.id == post.id))
        assert result.scalars().first() is None
        # Child row cascades.
        child = await session.execute(
            select(ClientReferral).filter(ClientReferral.id == post.id)
        )
        assert child.scalars().first() is None


async def test_admin_can_delete_anyone_post(
    authenticated_client: AsyncClient,
    db_test_session_manager: async_sessionmaker[AsyncSession],
    logged_in_user: User,
):
    """An admin can hard-delete a post owned by another user."""
    await promote_to_admin(db_test_session_manager, logged_in_user.email)
    other = create_test_user(username=f"other-{uuid.uuid4()}")
    post = _make_provider_availability(other)
    async with db_test_session_manager() as session:
        async with session.begin():
            session.add(other)
            session.add(post)

    response = await authenticated_client.delete(f"/posts/{post.id}")
    assert response.status_code == 204

    async with db_test_session_manager() as session:
        result = await session.execute(select(Post).filter(Post.id == post.id))
        assert result.scalars().first() is None


async def test_non_owner_cannot_delete_post(
    authenticated_client: AsyncClient,
    db_test_session_manager: async_sessionmaker[AsyncSession],
    logged_in_user: User,
):
    """A non-owner non-admin gets 403 and the post is preserved."""
    other = create_test_user(username=f"other-{uuid.uuid4()}")
    post = _make_client_referral(other)
    async with db_test_session_manager() as session:
        async with session.begin():
            session.add(other)
            session.add(post)

    response = await authenticated_client.delete(f"/posts/{post.id}")
    assert response.status_code == 403

    async with db_test_session_manager() as session:
        result = await session.execute(select(Post).filter(Post.id == post.id))
        refreshed = result.scalars().first()
        assert refreshed is not None


async def test_delete_404_for_unknown_post(
    authenticated_client: AsyncClient,
    logged_in_user: User,
):
    response = await authenticated_client.delete(f"/posts/{uuid.uuid4()}")
    assert response.status_code == 404


async def test_delete_unauthenticated_redirects(
    test_client: AsyncClient,
):
    response = await test_client.delete(
        f"/posts/{uuid.uuid4()}",
        headers={"accept": "text/html"},
        follow_redirects=False,
    )
    assert response.status_code == 302
    assert "/auth/login" in response.headers["location"]


async def test_delete_post_writes_audit_row(
    authenticated_client: AsyncClient,
    db_test_session_manager: async_sessionmaker[AsyncSession],
    logged_in_user: User,
):
    """Each successful DELETE writes one audit row capturing the pre-delete
    state in `before`, with `after=None`."""
    post = _make_provider_availability(logged_in_user)
    async with db_test_session_manager() as session:
        async with session.begin():
            session.add(post)
    post_id = post.id

    response = await authenticated_client.delete(f"/posts/{post_id}")
    assert response.status_code == 204

    async with db_test_session_manager() as session:
        repo = AuditRepository(session)
        rows = await repo.list_for_resource(resource_type="post", resource_id=post_id)
        assert len(rows) == 1
        row = rows[0]
        assert row.actor_id == logged_in_user.id
        assert row.action == "delete_post"
        assert row.before == {
            "kind": "provider_availability",
            "owner_id": str(logged_in_user.id),
        }
        assert row.after is None


async def test_unauthorized_delete_writes_no_audit_row(
    authenticated_client: AsyncClient,
    db_test_session_manager: async_sessionmaker[AsyncSession],
    logged_in_user: User,
):
    """A 403 on DELETE must not leak an audit row."""
    other = create_test_user(username=f"other-{uuid.uuid4()}")
    post = _make_client_referral(other)
    async with db_test_session_manager() as session:
        async with session.begin():
            session.add(other)
            session.add(post)

    response = await authenticated_client.delete(f"/posts/{post.id}")
    assert response.status_code == 403

    async with db_test_session_manager() as session:
        repo = AuditRepository(session)
        rows = await repo.list_for_resource(resource_type="post", resource_id=post.id)
        assert rows == []


async def test_admin_delete_audit_actor_is_admin_not_owner(
    authenticated_client: AsyncClient,
    db_test_session_manager: async_sessionmaker[AsyncSession],
    logged_in_user: User,
):
    """When an admin deletes another user's post, the audit row's actor is
    the admin (the requester), not the post owner."""
    await promote_to_admin(db_test_session_manager, logged_in_user.email)
    other = create_test_user(username=f"other-{uuid.uuid4()}")
    post = _make_client_referral(other)
    async with db_test_session_manager() as session:
        async with session.begin():
            session.add(other)
            session.add(post)
    post_id = post.id

    response = await authenticated_client.delete(f"/posts/{post_id}")
    assert response.status_code == 204

    async with db_test_session_manager() as session:
        repo = AuditRepository(session)
        rows = await repo.list_for_resource(resource_type="post", resource_id=post_id)
        assert len(rows) == 1
        assert rows[0].actor_id == logged_in_user.id  # admin, not other
        assert rows[0].before["owner_id"] == str(other.id)
        assert rows[0].after is None
