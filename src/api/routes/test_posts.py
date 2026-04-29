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
