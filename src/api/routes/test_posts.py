import uuid

import pytest
from httpx import AsyncClient
from selectolax.parser import HTMLParser
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from src.models import Post, User
from tests.helpers import create_test_user

# Mark all tests in this module as async
pytestmark = pytest.mark.asyncio


def _make_test_post(
    owner: User, *, title: str | None = None, body: str = "body"
) -> Post:
    return Post(
        title=title or f"post-{uuid.uuid4()}",
        body=body,
        owner_id=owner.id,
    )


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


async def test_list_posts_one_post(
    authenticated_client: AsyncClient,
    db_test_session_manager: async_sessionmaker[AsyncSession],
    logged_in_user: User,
):
    """GET /posts lists a single post belonging to another user."""
    other = create_test_user(username=f"author-{uuid.uuid4()}")
    title = f"post-{uuid.uuid4()}"

    async with db_test_session_manager() as session:
        async with session.begin():
            session.add(other)
            session.add(_make_test_post(other, title=title))

    response = await authenticated_client.get("/posts")

    assert response.status_code == 200
    tree = HTMLParser(response.text)
    items = tree.css("ul > li")
    assert len(items) == 1
    item_text = items[0].text()
    assert title in item_text
    assert other.username in item_text
    assert "No posts found" not in tree.body.text()


async def test_list_posts_orders_newest_first(
    authenticated_client: AsyncClient,
    db_test_session_manager: async_sessionmaker[AsyncSession],
    logged_in_user: User,
):
    """GET /posts orders results by created_at DESC."""
    from datetime import datetime, timedelta, timezone

    author = create_test_user(username=f"author-{uuid.uuid4()}")
    older = _make_test_post(author, title=f"older-{uuid.uuid4()}")
    newer = _make_test_post(author, title=f"newer-{uuid.uuid4()}")

    # Force created_at so the ordering check is deterministic regardless of
    # how fast successive inserts get the same default timestamp.
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
    assert newer.title in items[0].text()
    assert older.title in items[1].text()


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


async def test_get_post_detail_renders(
    authenticated_client: AsyncClient,
    db_test_session_manager: async_sessionmaker[AsyncSession],
    logged_in_user: User,
):
    """GET /posts/{id} renders the detail page for an existing post."""
    author = create_test_user(username=f"author-{uuid.uuid4()}")
    title = f"detail-{uuid.uuid4()}"
    body = f"body-{uuid.uuid4()}"
    post = Post(title=title, body=body, owner_id=author.id)

    async with db_test_session_manager() as session:
        async with session.begin():
            session.add(author)
            session.add(post)

    response = await authenticated_client.get(f"/posts/{post.id}")
    assert response.status_code == 200
    page = response.text
    assert title in page
    assert body in page
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


async def test_create_post_happy_path(
    authenticated_client: AsyncClient,
    db_test_session_manager: async_sessionmaker[AsyncSession],
    logged_in_user: User,
):
    """POST /posts persists the post owned by the session user and returns 201
    with Location + HX-Redirect headers."""
    title = f"new-{uuid.uuid4()}"
    body = f"body-{uuid.uuid4()}"

    response = await authenticated_client.post(
        "/posts", json={"title": title, "body": body}
    )

    assert response.status_code == 201
    payload = response.json()
    assert "id" in payload
    new_id = uuid.UUID(payload["id"])
    expected_location = f"/posts/{new_id}"
    assert response.headers.get("Location") == expected_location
    assert response.headers.get("HX-Redirect") == expected_location

    # Persisted, owned by the logged-in user
    async with db_test_session_manager() as session:
        result = await session.execute(select(Post).filter(Post.id == new_id))
        persisted = result.scalars().first()
        assert persisted is not None
        assert persisted.title == title
        assert persisted.body == body
        assert persisted.owner_id == logged_in_user.id


async def test_create_post_strips_whitespace(
    authenticated_client: AsyncClient,
    db_test_session_manager: async_sessionmaker[AsyncSession],
    logged_in_user: User,
):
    """Title and body are trimmed before persistence."""
    response = await authenticated_client.post(
        "/posts", json={"title": "  hello  ", "body": "  world  "}
    )
    assert response.status_code == 201
    new_id = uuid.UUID(response.json()["id"])

    async with db_test_session_manager() as session:
        result = await session.execute(select(Post).filter(Post.id == new_id))
        persisted = result.scalars().first()
        assert persisted.title == "hello"
        assert persisted.body == "world"


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
        json={"title": "t", "body": "b", "owner_id": str(other.id)},
    )
    assert response.status_code == 422

    # Nothing persisted
    async with db_test_session_manager() as session:
        result = await session.execute(select(Post))
        assert result.scalars().first() is None


async def test_create_post_rejects_unknown_field(
    authenticated_client: AsyncClient,
    logged_in_user: User,
):
    """Unknown fields are rejected with 422."""
    response = await authenticated_client.post(
        "/posts", json={"title": "t", "body": "b", "evil": True}
    )
    assert response.status_code == 422


@pytest.mark.parametrize(
    "payload",
    [
        {"body": "no title"},
        {"title": "no body"},
        {},
        {"title": "", "body": "b"},
        {"title": "t", "body": "   "},
    ],
)
async def test_create_post_missing_or_empty_fields_422(
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
        json={"title": "t", "body": "b"},
        headers={"accept": "text/html"},
        follow_redirects=False,
    )
    assert response.status_code == 302
    assert "/auth/login" in response.headers["location"]


# --- Update (PATCH) ------------------------------------------------------


async def _promote_to_admin(
    db_test_session_manager: async_sessionmaker[AsyncSession],
    user_email: str,
) -> None:
    async with db_test_session_manager() as session:
        async with session.begin():
            stmt = select(User).filter(User.email == user_email)
            result = await session.execute(stmt)
            user = result.scalars().first()
            assert user is not None, f"Test user {user_email} not found"
            user.is_superuser = True


async def test_owner_can_patch_title_only(
    authenticated_client: AsyncClient,
    db_test_session_manager: async_sessionmaker[AsyncSession],
    logged_in_user: User,
):
    """PATCH with only `title` updates title and leaves body untouched."""
    original_body = f"body-{uuid.uuid4()}"
    post = Post(title="orig", body=original_body, owner_id=logged_in_user.id)
    async with db_test_session_manager() as session:
        async with session.begin():
            session.add(post)

    new_title = f"new-{uuid.uuid4()}"
    response = await authenticated_client.patch(
        f"/posts/{post.id}", json={"title": new_title}
    )

    assert response.status_code == 200
    assert response.headers.get("HX-Refresh") == "true"
    body = response.json()
    assert body["title"] == new_title
    assert body["body"] == original_body

    async with db_test_session_manager() as session:
        result = await session.execute(select(Post).filter(Post.id == post.id))
        refreshed = result.scalars().first()
        assert refreshed.title == new_title
        assert refreshed.body == original_body


async def test_owner_can_patch_body_only(
    authenticated_client: AsyncClient,
    db_test_session_manager: async_sessionmaker[AsyncSession],
    logged_in_user: User,
):
    original_title = f"title-{uuid.uuid4()}"
    post = Post(title=original_title, body="orig", owner_id=logged_in_user.id)
    async with db_test_session_manager() as session:
        async with session.begin():
            session.add(post)

    response = await authenticated_client.patch(
        f"/posts/{post.id}", json={"body": "fresh"}
    )
    assert response.status_code == 200
    assert response.json()["title"] == original_title
    assert response.json()["body"] == "fresh"


async def test_owner_can_patch_both_fields(
    authenticated_client: AsyncClient,
    db_test_session_manager: async_sessionmaker[AsyncSession],
    logged_in_user: User,
):
    post = Post(title="t", body="b", owner_id=logged_in_user.id)
    async with db_test_session_manager() as session:
        async with session.begin():
            session.add(post)

    response = await authenticated_client.patch(
        f"/posts/{post.id}", json={"title": "T2", "body": "B2"}
    )
    assert response.status_code == 200
    assert response.json()["title"] == "T2"
    assert response.json()["body"] == "B2"


async def test_non_owner_cannot_patch_post(
    authenticated_client: AsyncClient,
    db_test_session_manager: async_sessionmaker[AsyncSession],
    logged_in_user: User,
):
    """A non-owner non-admin gets 403 and the post is not mutated."""
    other = create_test_user(username=f"other-{uuid.uuid4()}")
    post = Post(title="orig", body="orig", owner_id=other.id)
    async with db_test_session_manager() as session:
        async with session.begin():
            session.add(other)
            session.add(post)

    response = await authenticated_client.patch(
        f"/posts/{post.id}", json={"title": "hijack"}
    )
    assert response.status_code == 403

    async with db_test_session_manager() as session:
        result = await session.execute(select(Post).filter(Post.id == post.id))
        refreshed = result.scalars().first()
        assert refreshed.title == "orig"


async def test_admin_can_patch_anyone_post(
    authenticated_client: AsyncClient,
    db_test_session_manager: async_sessionmaker[AsyncSession],
    logged_in_user: User,
):
    await _promote_to_admin(db_test_session_manager, logged_in_user.email)
    other = create_test_user(username=f"other-{uuid.uuid4()}")
    post = Post(title="orig", body="orig", owner_id=other.id)
    async with db_test_session_manager() as session:
        async with session.begin():
            session.add(other)
            session.add(post)

    response = await authenticated_client.patch(
        f"/posts/{post.id}", json={"title": "moderated"}
    )
    assert response.status_code == 200
    assert response.json()["title"] == "moderated"


async def test_patch_404_for_unknown_post(
    authenticated_client: AsyncClient,
    logged_in_user: User,
):
    response = await authenticated_client.patch(
        f"/posts/{uuid.uuid4()}", json={"title": "x"}
    )
    assert response.status_code == 404


async def test_patch_rejects_owner_id_in_payload(
    authenticated_client: AsyncClient,
    db_test_session_manager: async_sessionmaker[AsyncSession],
    logged_in_user: User,
):
    """Even the owner cannot reassign owner_id via PATCH (server-managed)."""
    other = create_test_user(username=f"other-{uuid.uuid4()}")
    post = Post(title="t", body="b", owner_id=logged_in_user.id)
    async with db_test_session_manager() as session:
        async with session.begin():
            session.add(other)
            session.add(post)

    response = await authenticated_client.patch(
        f"/posts/{post.id}",
        json={"title": "t2", "owner_id": str(other.id)},
    )
    assert response.status_code == 422


@pytest.mark.parametrize(
    "payload",
    [
        {},
        {"title": None, "body": None},
        {"title": "   "},
        {"body": ""},
    ],
)
async def test_patch_invalid_body_422(
    payload,
    authenticated_client: AsyncClient,
    db_test_session_manager: async_sessionmaker[AsyncSession],
    logged_in_user: User,
):
    post = Post(title="t", body="b", owner_id=logged_in_user.id)
    async with db_test_session_manager() as session:
        async with session.begin():
            session.add(post)

    response = await authenticated_client.patch(f"/posts/{post.id}", json=payload)
    assert response.status_code == 422


async def test_patch_rejects_unknown_field(
    authenticated_client: AsyncClient,
    db_test_session_manager: async_sessionmaker[AsyncSession],
    logged_in_user: User,
):
    post = Post(title="t", body="b", owner_id=logged_in_user.id)
    async with db_test_session_manager() as session:
        async with session.begin():
            session.add(post)

    response = await authenticated_client.patch(
        f"/posts/{post.id}", json={"title": "x", "evil": True}
    )
    assert response.status_code == 422


async def test_patch_unauthenticated_redirects(
    test_client: AsyncClient,
):
    response = await test_client.patch(
        f"/posts/{uuid.uuid4()}",
        json={"title": "t"},
        headers={"accept": "text/html"},
        follow_redirects=False,
    )
    assert response.status_code == 302
    assert "/auth/login" in response.headers["location"]


# --- Create form page (GET /posts/form) ----------------------------------


async def test_get_post_form_renders(
    authenticated_client: AsyncClient,
    logged_in_user: User,
):
    """GET /posts/form renders the form for an authenticated user."""
    response = await authenticated_client.get("/posts/form")

    assert response.status_code == 200
    assert "text/html" in response.headers["content-type"]

    tree = HTMLParser(response.text)
    form = tree.css_first("form")
    assert form is not None
    assert form.attributes.get("hx-post") == "/posts"
    assert form.attributes.get("hx-ext") == "json-enc"
    assert tree.css_first("input#title") is not None
    assert tree.css_first("textarea#body") is not None


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
    post = Post(title="t", body="b", owner_id=logged_in_user.id)
    async with db_test_session_manager() as session:
        async with session.begin():
            session.add(post)

    response = await authenticated_client.get(f"/posts/{post.id}")
    assert response.status_code == 200
    assert "t" in response.text


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
