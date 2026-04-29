import uuid

import pytest
from httpx import AsyncClient
from selectolax.parser import HTMLParser
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from src.models import AuditLog, Post, User
from src.repositories.audit_repository import AuditRepository
from tests.helpers import create_test_user, promote_to_admin

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
    await promote_to_admin(db_test_session_manager, logged_in_user.email)
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


# --- Edit form page (GET /posts/{id}/form) -------------------------------


async def test_owner_can_open_edit_form(
    authenticated_client: AsyncClient,
    db_test_session_manager: async_sessionmaker[AsyncSession],
    logged_in_user: User,
):
    """The owner sees the edit form pre-filled with current values."""
    post = Post(title="orig title", body="orig body", owner_id=logged_in_user.id)
    async with db_test_session_manager() as session:
        async with session.begin():
            session.add(post)

    response = await authenticated_client.get(f"/posts/{post.id}/form")
    assert response.status_code == 200
    tree = HTMLParser(response.text)
    form = tree.css_first("form")
    assert form is not None
    assert form.attributes.get("hx-patch") == f"/posts/{post.id}"
    assert form.attributes.get("hx-ext") == "json-enc"
    title_input = tree.css_first("input#title")
    assert title_input is not None
    assert title_input.attributes.get("value") == "orig title"
    body_textarea = tree.css_first("textarea#body")
    assert body_textarea is not None
    assert "orig body" in body_textarea.text()


async def test_admin_can_open_edit_form_for_any_post(
    authenticated_client: AsyncClient,
    db_test_session_manager: async_sessionmaker[AsyncSession],
    logged_in_user: User,
):
    await promote_to_admin(db_test_session_manager, logged_in_user.email)
    other = create_test_user(username=f"other-{uuid.uuid4()}")
    post = Post(title="t", body="b", owner_id=other.id)
    async with db_test_session_manager() as session:
        async with session.begin():
            session.add(other)
            session.add(post)

    response = await authenticated_client.get(f"/posts/{post.id}/form")
    assert response.status_code == 200


async def test_non_owner_cannot_open_edit_form(
    authenticated_client: AsyncClient,
    db_test_session_manager: async_sessionmaker[AsyncSession],
    logged_in_user: User,
):
    other = create_test_user(username=f"other-{uuid.uuid4()}")
    post = Post(title="t", body="b", owner_id=other.id)
    async with db_test_session_manager() as session:
        async with session.begin():
            session.add(other)
            session.add(post)

    response = await authenticated_client.get(f"/posts/{post.id}/form")
    assert response.status_code == 403


async def test_edit_form_404_for_unknown_post(
    authenticated_client: AsyncClient,
    logged_in_user: User,
):
    response = await authenticated_client.get(f"/posts/{uuid.uuid4()}/form")
    assert response.status_code == 404


async def test_edit_form_unauthenticated_redirects(
    test_client: AsyncClient,
):
    response = await test_client.get(
        f"/posts/{uuid.uuid4()}/form",
        headers={"accept": "text/html"},
        follow_redirects=False,
    )
    assert response.status_code == 302
    assert "/auth/login" in response.headers["location"]


# --- Owner-actions partial visibility on detail page ---------------------


async def test_detail_page_shows_edit_link_for_owner(
    authenticated_client: AsyncClient,
    db_test_session_manager: async_sessionmaker[AsyncSession],
    logged_in_user: User,
):
    post = Post(title="t", body="b", owner_id=logged_in_user.id)
    async with db_test_session_manager() as session:
        async with session.begin():
            session.add(post)

    response = await authenticated_client.get(f"/posts/{post.id}")
    assert response.status_code == 200
    tree = HTMLParser(response.text)
    actions = tree.css_first("span.owner-actions")
    assert actions is not None
    edit_link = actions.css_first("a")
    assert edit_link is not None
    assert edit_link.attributes.get("href") == f"/posts/{post.id}/form"


async def test_detail_page_shows_edit_link_for_admin(
    authenticated_client: AsyncClient,
    db_test_session_manager: async_sessionmaker[AsyncSession],
    logged_in_user: User,
):
    await promote_to_admin(db_test_session_manager, logged_in_user.email)
    other = create_test_user(username=f"other-{uuid.uuid4()}")
    post = Post(title="t", body="b", owner_id=other.id)
    async with db_test_session_manager() as session:
        async with session.begin():
            session.add(other)
            session.add(post)

    response = await authenticated_client.get(f"/posts/{post.id}")
    assert response.status_code == 200
    tree = HTMLParser(response.text)
    assert tree.css_first("span.owner-actions") is not None


async def test_detail_page_hides_edit_link_for_stranger(
    authenticated_client: AsyncClient,
    db_test_session_manager: async_sessionmaker[AsyncSession],
    logged_in_user: User,
):
    other = create_test_user(username=f"other-{uuid.uuid4()}")
    post = Post(title="t", body="b", owner_id=other.id)
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
    post = Post(title="t", body="b", owner_id=logged_in_user.id)
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
    post = Post(title="t", body="b", owner_id=other.id)
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


async def test_create_post_writes_audit_row(
    authenticated_client: AsyncClient,
    db_test_session_manager: async_sessionmaker[AsyncSession],
    logged_in_user: User,
):
    """Each successful POST /posts writes exactly one audit row."""
    title = f"audited-{uuid.uuid4()}"
    body = f"body-{uuid.uuid4()}"

    response = await authenticated_client.post(
        "/posts", json={"title": title, "body": body}
    )
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
            "title": title,
            "body": body,
            "owner_id": str(logged_in_user.id),
        }


async def test_patch_post_writes_audit_row_with_before_and_after(
    authenticated_client: AsyncClient,
    db_test_session_manager: async_sessionmaker[AsyncSession],
    logged_in_user: User,
):
    """Each successful PATCH /posts/{id} writes one audit row capturing
    pre- and post-mutation snapshots."""
    post = Post(title="orig title", body="orig body", owner_id=logged_in_user.id)
    async with db_test_session_manager() as session:
        async with session.begin():
            session.add(post)

    response = await authenticated_client.patch(
        f"/posts/{post.id}", json={"title": "new title"}
    )
    assert response.status_code == 200

    async with db_test_session_manager() as session:
        repo = AuditRepository(session)
        rows = await repo.list_for_resource(resource_type="post", resource_id=post.id)
        assert len(rows) == 1
        row = rows[0]
        assert row.actor_id == logged_in_user.id
        assert row.action == "update_post"
        assert row.before == {
            "title": "orig title",
            "body": "orig body",
            "owner_id": str(logged_in_user.id),
        }
        assert row.after == {
            "title": "new title",
            "body": "orig body",
            "owner_id": str(logged_in_user.id),
        }


async def test_failed_create_writes_no_audit_row(
    authenticated_client: AsyncClient,
    db_test_session_manager: async_sessionmaker[AsyncSession],
    logged_in_user: User,
):
    """A 422 (schema rejection) must not leak an audit row — the discipline
    requires audit lands iff the mutation does."""
    response = await authenticated_client.post(
        "/posts", json={"title": "t", "body": "b", "evil": True}
    )
    assert response.status_code == 422

    async with db_test_session_manager() as session:
        # No specific resource_id to query — assert the post-typed audit
        # table is empty.
        result = await session.execute(
            select(AuditLog).filter(AuditLog.resource_type == "post")
        )
        assert result.scalars().first() is None


async def test_unauthorized_patch_writes_no_audit_row(
    authenticated_client: AsyncClient,
    db_test_session_manager: async_sessionmaker[AsyncSession],
    logged_in_user: User,
):
    """A 403 must not leak an audit row."""
    other = create_test_user(username=f"other-{uuid.uuid4()}")
    post = Post(title="t", body="b", owner_id=other.id)
    async with db_test_session_manager() as session:
        async with session.begin():
            session.add(other)
            session.add(post)

    response = await authenticated_client.patch(
        f"/posts/{post.id}", json={"title": "hijack"}
    )
    assert response.status_code == 403

    async with db_test_session_manager() as session:
        repo = AuditRepository(session)
        rows = await repo.list_for_resource(resource_type="post", resource_id=post.id)
        assert rows == []


async def test_admin_patch_audit_actor_is_admin_not_owner(
    authenticated_client: AsyncClient,
    db_test_session_manager: async_sessionmaker[AsyncSession],
    logged_in_user: User,
):
    """When an admin edits another user's post, the audit row's actor is
    the admin (the requester), not the post owner."""
    await promote_to_admin(db_test_session_manager, logged_in_user.email)
    other = create_test_user(username=f"other-{uuid.uuid4()}")
    post = Post(title="t", body="b", owner_id=other.id)
    async with db_test_session_manager() as session:
        async with session.begin():
            session.add(other)
            session.add(post)

    response = await authenticated_client.patch(
        f"/posts/{post.id}", json={"title": "moderated"}
    )
    assert response.status_code == 200

    async with db_test_session_manager() as session:
        repo = AuditRepository(session)
        rows = await repo.list_for_resource(resource_type="post", resource_id=post.id)
        assert len(rows) == 1
        assert rows[0].actor_id == logged_in_user.id  # admin, not other
        assert rows[0].after["title"] == "moderated"
        assert rows[0].after["owner_id"] == str(other.id)


# --- Delete (DELETE) -----------------------------------------------------


async def test_owner_can_delete_own_post(
    authenticated_client: AsyncClient,
    db_test_session_manager: async_sessionmaker[AsyncSession],
    logged_in_user: User,
):
    """DELETE by the owner returns 204, removes the row, and sets HX-Redirect."""
    post = Post(title="t", body="b", owner_id=logged_in_user.id)
    async with db_test_session_manager() as session:
        async with session.begin():
            session.add(post)

    response = await authenticated_client.delete(f"/posts/{post.id}")
    assert response.status_code == 204
    assert response.headers.get("HX-Redirect") == "/posts"

    async with db_test_session_manager() as session:
        result = await session.execute(select(Post).filter(Post.id == post.id))
        assert result.scalars().first() is None


async def test_admin_can_delete_anyone_post(
    authenticated_client: AsyncClient,
    db_test_session_manager: async_sessionmaker[AsyncSession],
    logged_in_user: User,
):
    """An admin can hard-delete a post owned by another user."""
    await promote_to_admin(db_test_session_manager, logged_in_user.email)
    other = create_test_user(username=f"other-{uuid.uuid4()}")
    post = Post(title="t", body="b", owner_id=other.id)
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
    post = Post(title="orig", body="orig", owner_id=other.id)
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
        assert refreshed.title == "orig"


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
    title = f"doomed-{uuid.uuid4()}"
    body = f"body-{uuid.uuid4()}"
    post = Post(title=title, body=body, owner_id=logged_in_user.id)
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
            "title": title,
            "body": body,
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
    post = Post(title="t", body="b", owner_id=other.id)
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
    post = Post(title="t", body="b", owner_id=other.id)
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
