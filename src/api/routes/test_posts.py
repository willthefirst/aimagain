import uuid

import pytest
from httpx import AsyncClient
from selectolax.parser import HTMLParser
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from src.models import (
    ClientReferralDetail,
    Post,
    ProviderAvailabilityDetail,
    User,
)
from src.repositories.audit_repository import AuditRepository
from tests.helpers import (
    client_referral_payload,
    create_test_user,
    make_client_referral_detail,
    make_provider_availability_detail,
    promote_to_admin,
    provider_availability_payload,
)

# Mark all tests in this module as async
pytestmark = pytest.mark.asyncio


def _client_referral_post(*, description: str, owner_id, **overrides) -> Post:
    """Build a `kind='client_referral'` Post + its spec-compliant detail.
    Per-field overrides flow through to the detail row."""
    post = Post(kind="client_referral", owner_id=owner_id)
    post.client_referral_detail = make_client_referral_detail(
        description=description, **overrides
    )
    return post


def _provider_availability_post(*, practice_name: str, owner_id, **overrides) -> Post:
    """Build a `kind='provider_availability'` Post + its spec-compliant detail."""
    post = Post(kind="provider_availability", owner_id=owner_id)
    post.provider_availability_detail = make_provider_availability_detail(
        practice_name=practice_name, **overrides
    )
    return post


def _make_test_post(owner: User, *, description: str | None = None) -> Post:
    return _client_referral_post(
        description=description or f"post-{uuid.uuid4()}",
        owner_id=owner.id,
    )


# --- Listing -------------------------------------------------------------


# PHASE2_REDUNDANT: framework-shaped — mount_list empty state.
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
    description = f"post-{uuid.uuid4()}"

    async with db_test_session_manager() as session:
        async with session.begin():
            session.add(other)
            session.add(_make_test_post(other, description=description))

    response = await authenticated_client.get("/posts")

    assert response.status_code == 200
    tree = HTMLParser(response.text)
    items = tree.css("#post-list > li")
    assert len(items) == 1
    item_text = items[0].text()
    assert description in item_text
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
    older = _make_test_post(author, description=f"older-{uuid.uuid4()}")
    newer = _make_test_post(author, description=f"newer-{uuid.uuid4()}")

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
    items = tree.css("#post-list > li")
    assert len(items) == 2
    assert newer.client_referral_detail.description in items[0].text()
    assert older.client_referral_detail.description in items[1].text()


# --- Update (PATCH) ------------------------------------------------------


# PHASE2_REDUNDANT: framework-shaped — write_authz binding on mount_update.
async def test_non_owner_cannot_patch_post(
    authenticated_client: AsyncClient,
    db_test_session_manager: async_sessionmaker[AsyncSession],
    logged_in_user: User,
):
    """A non-owner non-admin gets 403 and the post is not mutated."""
    other = create_test_user(username=f"other-{uuid.uuid4()}")
    post = _client_referral_post(description="orig", owner_id=other.id)
    async with db_test_session_manager() as session:
        async with session.begin():
            session.add(other)
            session.add(post)

    response = await authenticated_client.patch(
        f"/posts/{post.id}",
        data={"kind": "client_referral", "description": "hijack"},
    )
    assert response.status_code == 403

    async with db_test_session_manager() as session:
        result = await session.execute(select(Post).filter(Post.id == post.id))
        refreshed = result.scalars().first()
        assert refreshed.client_referral_detail.description == "orig"


# PHASE2_REDUNDANT: framework-shaped — admin override on mount_update.
async def test_admin_can_patch_anyone_post(
    authenticated_client: AsyncClient,
    db_test_session_manager: async_sessionmaker[AsyncSession],
    logged_in_user: User,
):
    await promote_to_admin(db_test_session_manager, logged_in_user.email)
    other = create_test_user(username=f"other-{uuid.uuid4()}")
    post = _client_referral_post(description="orig", owner_id=other.id)
    async with db_test_session_manager() as session:
        async with session.begin():
            session.add(other)
            session.add(post)

    response = await authenticated_client.patch(
        f"/posts/{post.id}",
        data={"kind": "client_referral", "description": "moderated"},
    )
    assert response.status_code == 200
    assert response.json()["description"] == "moderated"


# --- Create form page (GET /posts/form) ----------------------------------


async def test_list_page_links_to_create_forms(
    authenticated_client: AsyncClient,
    logged_in_user: User,
):
    response = await authenticated_client.get("/posts")
    assert response.status_code == 200
    tree = HTMLParser(response.text)
    cr_link = tree.css_first('a[href="/posts/form?kind=client_referral"]')
    assert cr_link is not None
    pa_link = tree.css_first('a[href="/posts/form?kind=provider_availability"]')
    assert pa_link is not None


# --- Edit form page (GET /posts/{id}/form) -------------------------------


async def test_admin_can_open_edit_form_for_any_post(
    authenticated_client: AsyncClient,
    db_test_session_manager: async_sessionmaker[AsyncSession],
    logged_in_user: User,
):
    await promote_to_admin(db_test_session_manager, logged_in_user.email)
    other = create_test_user(username=f"other-{uuid.uuid4()}")
    post = _client_referral_post(description="d", owner_id=other.id)
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
    post = _client_referral_post(description="d", owner_id=other.id)
    async with db_test_session_manager() as session:
        async with session.begin():
            session.add(other)
            session.add(post)

    response = await authenticated_client.get(f"/posts/{post.id}/form")
    assert response.status_code == 403


# --- Owner-actions partial visibility on detail page ---------------------


async def test_detail_page_shows_edit_link_for_owner(
    authenticated_client: AsyncClient,
    db_test_session_manager: async_sessionmaker[AsyncSession],
    logged_in_user: User,
):
    post = _client_referral_post(description="d", owner_id=logged_in_user.id)
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
    post = _client_referral_post(description="d", owner_id=other.id)
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
    post = _client_referral_post(description="d", owner_id=other.id)
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
    post = _client_referral_post(description="d", owner_id=logged_in_user.id)
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
    post = _client_referral_post(description="d", owner_id=other.id)
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


async def test_admin_patch_audit_actor_is_admin_not_owner(
    authenticated_client: AsyncClient,
    db_test_session_manager: async_sessionmaker[AsyncSession],
    logged_in_user: User,
):
    """When an admin edits another user's post, the audit row's actor is
    the admin (the requester), not the post owner."""
    await promote_to_admin(db_test_session_manager, logged_in_user.email)
    other = create_test_user(username=f"other-{uuid.uuid4()}")
    post = _client_referral_post(description="d", owner_id=other.id)
    async with db_test_session_manager() as session:
        async with session.begin():
            session.add(other)
            session.add(post)

    response = await authenticated_client.patch(
        f"/posts/{post.id}",
        data={"kind": "client_referral", "description": "moderated"},
    )
    assert response.status_code == 200

    async with db_test_session_manager() as session:
        repo = AuditRepository(session)
        rows = await repo.list_for_resource(resource_type="post", resource_id=post.id)
        assert len(rows) == 1
        assert rows[0].actor_id == logged_in_user.id  # admin, not other
        assert rows[0].after["description"] == "moderated"
        assert rows[0].after["owner_id"] == str(other.id)


# --- Delete (DELETE) -----------------------------------------------------


async def test_admin_delete_audit_actor_is_admin_not_owner(
    authenticated_client: AsyncClient,
    db_test_session_manager: async_sessionmaker[AsyncSession],
    logged_in_user: User,
):
    """When an admin deletes another user's post, the audit row's actor is
    the admin (the requester), not the post owner."""
    await promote_to_admin(db_test_session_manager, logged_in_user.email)
    other = create_test_user(username=f"other-{uuid.uuid4()}")
    post = _client_referral_post(description="d", owner_id=other.id)
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


# --- Client referral kind: end-to-end ------------------------------------


async def test_create_client_referral_happy_path(
    authenticated_client: AsyncClient,
    db_test_session_manager: async_sessionmaker[AsyncSession],
    logged_in_user: User,
):
    """`POST /posts` with `kind='client_referral'` persists with the right
    detail row and audit row."""
    description = f"needs-{uuid.uuid4()}"

    response = await authenticated_client.post(
        "/posts",
        data=client_referral_payload(description=description),
    )

    assert response.status_code == 201
    new_id = uuid.UUID(response.json()["id"])

    async with db_test_session_manager() as session:
        result = await session.execute(select(Post).filter(Post.id == new_id))
        persisted = result.scalars().first()
        assert persisted is not None
        assert persisted.kind == "client_referral"
        assert persisted.client_referral_detail.description == description
        assert persisted.client_referral_detail.location_state == "IL"
        assert persisted.owner_id == logged_in_user.id

    async with db_test_session_manager() as session:
        repo = AuditRepository(session)
        rows = await repo.list_for_resource(resource_type="post", resource_id=new_id)
        assert len(rows) == 1
        assert rows[0].action == "create_post"
        assert rows[0].before is None
        expected = client_referral_payload(description=description)
        expected.pop("kind")
        assert rows[0].after == {
            "kind": "client_referral",
            "owner_id": str(logged_in_user.id),
            **expected,
        }


async def test_create_client_referral_strips_whitespace(
    authenticated_client: AsyncClient,
    db_test_session_manager: async_sessionmaker[AsyncSession],
    logged_in_user: User,
):
    response = await authenticated_client.post(
        "/posts",
        data=client_referral_payload(description="  needs help  "),
    )
    assert response.status_code == 201
    new_id = uuid.UUID(response.json()["id"])

    async with db_test_session_manager() as session:
        result = await session.execute(select(Post).filter(Post.id == new_id))
        persisted = result.scalars().first()
        assert persisted.client_referral_detail.description == "needs help"


@pytest.mark.parametrize(
    "payload",
    [
        {"kind": "client_referral"},  # missing every required field
        client_referral_payload(description=""),
        client_referral_payload(description="   "),
        client_referral_payload(location_zip="abc"),  # non-numeric ZIP
        client_referral_payload(location_state="ZZ"),  # not a US state
        client_referral_payload(insurance="cash_only"),  # not in INSURANCE_OPTIONS
        client_referral_payload(title="bleed"),  # cross-kind field bleed
        client_referral_payload(evil=True),  # unknown field
        {"kind": "unknown_kind", "description": "ok"},
    ],
)
async def test_create_client_referral_rejects_invalid_payload(
    payload,
    authenticated_client: AsyncClient,
    logged_in_user: User,
):
    response = await authenticated_client.post("/posts", data=payload)
    assert response.status_code == 422


async def test_get_client_referral_form_renders(
    authenticated_client: AsyncClient,
    logged_in_user: User,
):
    """`GET /posts/form?kind=client_referral` renders the kind-specific
    create form."""
    response = await authenticated_client.get("/posts/form?kind=client_referral")
    assert response.status_code == 200
    tree = HTMLParser(response.text)
    form = tree.css_first("form")
    assert form is not None
    assert form.attributes.get("hx-post") == "/posts"
    assert tree.css_first("textarea#description") is not None
    kind_input = tree.css_first('input[name="kind"]')
    assert kind_input is not None
    assert kind_input.attributes.get("value") == "client_referral"


async def test_get_post_form_default_kind_is_client_referral(
    authenticated_client: AsyncClient,
    logged_in_user: User,
):
    """`GET /posts/form` without a `kind` query parameter renders the
    first registered kind's form (currently client_referral)."""
    response = await authenticated_client.get("/posts/form")
    assert response.status_code == 200
    tree = HTMLParser(response.text)
    kind_input = tree.css_first('input[name="kind"]')
    assert kind_input is not None
    assert kind_input.attributes.get("value") == "client_referral"


async def test_get_post_form_treats_empty_kind_as_absent(
    authenticated_client: AsyncClient,
    logged_in_user: User,
):
    """`GET /posts/form?kind=` should fall back to the default kind
    rather than 422 against the `Literal[...]` annotation. The
    middleware strips the empty pair at request entry so FastAPI sees
    the param as absent and the route's default (`POST_KIND_NAMES[0]`)
    fires."""
    response = await authenticated_client.get("/posts/form?kind=")
    assert response.status_code == 200
    tree = HTMLParser(response.text)
    kind_input = tree.css_first('input[name="kind"]')
    assert kind_input is not None
    assert kind_input.attributes.get("value") == "client_referral"


async def test_list_renders_client_referral_row(
    authenticated_client: AsyncClient,
    db_test_session_manager: async_sessionmaker[AsyncSession],
    logged_in_user: User,
):
    """`GET /posts` lists a client_referral with a kind label."""
    author = create_test_user(username=f"author-{uuid.uuid4()}")
    description = f"crsummary-{uuid.uuid4()}"
    post = _client_referral_post(description=description, owner_id=author.id)

    async with db_test_session_manager() as session:
        async with session.begin():
            session.add(author)
            session.add(post)

    response = await authenticated_client.get("/posts")
    assert response.status_code == 200
    page = response.text
    assert description in page
    assert "client referral" in page.lower()


async def test_get_client_referral_detail_renders(
    authenticated_client: AsyncClient,
    db_test_session_manager: async_sessionmaker[AsyncSession],
    logged_in_user: User,
):
    author = create_test_user(username=f"author-{uuid.uuid4()}")
    description = f"detail-{uuid.uuid4()}"
    post = _client_referral_post(description=description, owner_id=author.id)

    async with db_test_session_manager() as session:
        async with session.begin():
            session.add(author)
            session.add(post)

    response = await authenticated_client.get(f"/posts/{post.id}")
    assert response.status_code == 200
    page = response.text
    assert description in page
    assert author.username in page


async def test_owner_can_open_client_referral_edit_form(
    authenticated_client: AsyncClient,
    db_test_session_manager: async_sessionmaker[AsyncSession],
    logged_in_user: User,
):
    """The owner of a client_referral sees the kind-specific edit form
    pre-filled with the current description."""
    description = f"edit-{uuid.uuid4()}"
    post = _client_referral_post(description=description, owner_id=logged_in_user.id)
    async with db_test_session_manager() as session:
        async with session.begin():
            session.add(post)

    response = await authenticated_client.get(f"/posts/{post.id}/form")
    assert response.status_code == 200
    tree = HTMLParser(response.text)
    form = tree.css_first("form")
    assert form is not None
    assert form.attributes.get("hx-patch") == f"/posts/{post.id}"
    description_input = tree.css_first("textarea#description")
    assert description_input is not None
    assert description in description_input.text()
    kind_input = tree.css_first('input[name="kind"]')
    assert kind_input is not None
    assert kind_input.attributes.get("value") == "client_referral"


async def test_owner_can_patch_client_referral_description(
    authenticated_client: AsyncClient,
    db_test_session_manager: async_sessionmaker[AsyncSession],
    logged_in_user: User,
):
    """`PATCH /posts/{id}` with `kind='client_referral'` updates the
    description and returns a per-kind flat body."""
    post = _client_referral_post(description="orig", owner_id=logged_in_user.id)
    async with db_test_session_manager() as session:
        async with session.begin():
            session.add(post)

    new_description = f"updated-{uuid.uuid4()}"
    response = await authenticated_client.patch(
        f"/posts/{post.id}",
        data={"kind": "client_referral", "description": new_description},
    )
    assert response.status_code == 200
    assert response.headers.get("HX-Redirect") == f"/posts/{post.id}"
    body = response.json()
    assert body["kind"] == "client_referral"
    assert body["description"] == new_description
    assert "title" not in body and "body" not in body

    async with db_test_session_manager() as session:
        result = await session.execute(select(Post).filter(Post.id == post.id))
        refreshed = result.scalars().first()
        assert refreshed.client_referral_detail.description == new_description


async def test_patch_provider_availability_with_client_referral_payload_does_not_mutate(
    authenticated_client: AsyncClient,
    db_test_session_manager: async_sessionmaker[AsyncSession],
    logged_in_user: User,
):
    """A provider_availability post can't be patched with a client_referral
    payload — kind is part of the resource identity. The 400 must fire
    before any mutation, and no audit row may be written."""
    original = f"orig-{uuid.uuid4()}"
    post = _provider_availability_post(
        practice_name=original, owner_id=logged_in_user.id
    )
    async with db_test_session_manager() as session:
        async with session.begin():
            session.add(post)
    post_id = post.id

    response = await authenticated_client.patch(
        f"/posts/{post_id}",
        data={"kind": "client_referral", "description": "hijack"},
    )
    assert response.status_code == 400

    async with db_test_session_manager() as session:
        result = await session.execute(select(Post).filter(Post.id == post_id))
        refreshed = result.scalars().first()
        assert refreshed.kind == "provider_availability"
        assert refreshed.provider_availability_detail.practice_name == original
        assert refreshed.client_referral_detail is None

    async with db_test_session_manager() as session:
        repo = AuditRepository(session)
        rows = await repo.list_for_resource(resource_type="post", resource_id=post_id)
        assert rows == []


async def test_patch_client_referral_with_provider_availability_payload_does_not_mutate(
    authenticated_client: AsyncClient,
    db_test_session_manager: async_sessionmaker[AsyncSession],
    logged_in_user: User,
):
    """Reverse direction: a client_referral can't be patched with a
    provider_availability payload either. Same invariant — kind is fixed
    once set."""
    original_description = f"orig-{uuid.uuid4()}"
    post = _client_referral_post(
        description=original_description, owner_id=logged_in_user.id
    )
    async with db_test_session_manager() as session:
        async with session.begin():
            session.add(post)
    post_id = post.id

    response = await authenticated_client.patch(
        f"/posts/{post_id}",
        data={"kind": "provider_availability", "practice_name": "hijack"},
    )
    assert response.status_code == 400

    async with db_test_session_manager() as session:
        result = await session.execute(select(Post).filter(Post.id == post_id))
        refreshed = result.scalars().first()
        assert refreshed.kind == "client_referral"
        assert refreshed.client_referral_detail.description == original_description
        assert refreshed.provider_availability_detail is None

    async with db_test_session_manager() as session:
        repo = AuditRepository(session)
        rows = await repo.list_for_resource(resource_type="post", resource_id=post_id)
        assert rows == []


async def test_owner_can_delete_client_referral(
    authenticated_client: AsyncClient,
    db_test_session_manager: async_sessionmaker[AsyncSession],
    logged_in_user: User,
):
    """`DELETE /posts/{id}` works for client_referral; cascades the detail."""
    post = _client_referral_post(description="doomed", owner_id=logged_in_user.id)
    async with db_test_session_manager() as session:
        async with session.begin():
            session.add(post)
    post_id = post.id

    response = await authenticated_client.delete(f"/posts/{post_id}")
    assert response.status_code == 204

    async with db_test_session_manager() as session:
        post_row = (
            (await session.execute(select(Post).filter(Post.id == post_id)))
            .scalars()
            .first()
        )
        detail_row = (
            (
                await session.execute(
                    select(ClientReferralDetail).filter(
                        ClientReferralDetail.post_id == post_id
                    )
                )
            )
            .scalars()
            .first()
        )
        assert post_row is None
        assert detail_row is None


async def test_delete_client_referral_writes_audit_row(
    authenticated_client: AsyncClient,
    db_test_session_manager: async_sessionmaker[AsyncSession],
    logged_in_user: User,
):
    """Audit before-snapshot for a client_referral delete uses the
    kind-specific snapshot shape."""
    description = f"doomed-{uuid.uuid4()}"
    post = _client_referral_post(description=description, owner_id=logged_in_user.id)
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
        assert rows[0].action == "delete_post"
        assert rows[0].before == {
            **client_referral_payload(description=description),
            "owner_id": str(logged_in_user.id),
        }
        assert rows[0].after is None


# --- Provider availability kind: end-to-end ------------------------------


async def test_create_provider_availability_happy_path(
    authenticated_client: AsyncClient,
    db_test_session_manager: async_sessionmaker[AsyncSession],
    logged_in_user: User,
):
    """`POST /posts` with `kind='provider_availability'` persists with
    the right detail row + audit row."""
    practice_name = f"Acme-{uuid.uuid4()}"

    response = await authenticated_client.post(
        "/posts",
        data=provider_availability_payload(practice_name=practice_name),
    )

    assert response.status_code == 201
    new_id = uuid.UUID(response.json()["id"])

    async with db_test_session_manager() as session:
        result = await session.execute(select(Post).filter(Post.id == new_id))
        persisted = result.scalars().first()
        assert persisted is not None
        assert persisted.kind == "provider_availability"
        assert persisted.provider_availability_detail.practice_name == practice_name
        assert persisted.provider_availability_detail.sliding_scale is False
        assert persisted.client_referral_detail is None
        assert persisted.owner_id == logged_in_user.id

    async with db_test_session_manager() as session:
        repo = AuditRepository(session)
        rows = await repo.list_for_resource(resource_type="post", resource_id=new_id)
        assert len(rows) == 1
        assert rows[0].action == "create_post"
        assert rows[0].before is None
        expected = provider_availability_payload(practice_name=practice_name)
        expected.pop("kind")
        assert rows[0].after == {
            "kind": "provider_availability",
            "owner_id": str(logged_in_user.id),
            **expected,
        }


async def test_create_provider_availability_strips_whitespace(
    authenticated_client: AsyncClient,
    db_test_session_manager: async_sessionmaker[AsyncSession],
    logged_in_user: User,
):
    response = await authenticated_client.post(
        "/posts",
        data=provider_availability_payload(practice_name="  Acme  "),
    )
    assert response.status_code == 201
    new_id = uuid.UUID(response.json()["id"])

    async with db_test_session_manager() as session:
        result = await session.execute(select(Post).filter(Post.id == new_id))
        persisted = result.scalars().first()
        assert persisted.provider_availability_detail.practice_name == "Acme"


@pytest.mark.parametrize(
    "payload",
    [
        {"kind": "provider_availability"},  # missing every required field
        provider_availability_payload(practice_name=""),
        provider_availability_payload(practice_name="   "),
        provider_availability_payload(location_state="ZZ"),  # not a US state
        provider_availability_payload(payment_situation="cash_only"),
        provider_availability_payload(title="bleed"),  # cross-kind bleed
        provider_availability_payload(evil=True),  # unknown field
    ],
)
async def test_create_provider_availability_rejects_invalid_payload(
    payload,
    authenticated_client: AsyncClient,
    logged_in_user: User,
):
    response = await authenticated_client.post("/posts", data=payload)
    assert response.status_code == 422


async def test_get_provider_availability_form_renders(
    authenticated_client: AsyncClient,
    logged_in_user: User,
):
    """`GET /posts/form?kind=provider_availability` renders the kind-specific
    create form."""
    response = await authenticated_client.get("/posts/form?kind=provider_availability")
    assert response.status_code == 200
    tree = HTMLParser(response.text)
    form = tree.css_first("form")
    assert form is not None
    assert form.attributes.get("hx-post") == "/posts"
    assert tree.css_first("input#practice_name") is not None
    kind_input = tree.css_first('input[name="kind"]')
    assert kind_input is not None
    assert kind_input.attributes.get("value") == "provider_availability"


async def test_list_renders_provider_availability_row(
    authenticated_client: AsyncClient,
    db_test_session_manager: async_sessionmaker[AsyncSession],
    logged_in_user: User,
):
    """`GET /posts` lists a provider_availability with a kind label."""
    author = create_test_user(username=f"author-{uuid.uuid4()}")
    practice_name = f"Practice-{uuid.uuid4()}"
    post = _provider_availability_post(practice_name=practice_name, owner_id=author.id)

    async with db_test_session_manager() as session:
        async with session.begin():
            session.add(author)
            session.add(post)

    response = await authenticated_client.get("/posts")
    assert response.status_code == 200
    page = response.text
    assert practice_name in page
    assert "provider availability" in page.lower()


async def test_get_provider_availability_detail_renders(
    authenticated_client: AsyncClient,
    db_test_session_manager: async_sessionmaker[AsyncSession],
    logged_in_user: User,
):
    author = create_test_user(username=f"author-{uuid.uuid4()}")
    practice_name = f"Detail-{uuid.uuid4()}"
    post = _provider_availability_post(practice_name=practice_name, owner_id=author.id)

    async with db_test_session_manager() as session:
        async with session.begin():
            session.add(author)
            session.add(post)

    response = await authenticated_client.get(f"/posts/{post.id}")
    assert response.status_code == 200
    page = response.text
    assert practice_name in page
    assert author.username in page


async def test_owner_can_open_provider_availability_edit_form(
    authenticated_client: AsyncClient,
    db_test_session_manager: async_sessionmaker[AsyncSession],
    logged_in_user: User,
):
    """The owner of a provider_availability sees the kind-specific edit
    form pre-filled with the current practice name."""
    practice_name = f"Edit-{uuid.uuid4()}"
    post = _provider_availability_post(
        practice_name=practice_name, owner_id=logged_in_user.id
    )
    async with db_test_session_manager() as session:
        async with session.begin():
            session.add(post)

    response = await authenticated_client.get(f"/posts/{post.id}/form")
    assert response.status_code == 200
    tree = HTMLParser(response.text)
    form = tree.css_first("form")
    assert form is not None
    assert form.attributes.get("hx-patch") == f"/posts/{post.id}"
    practice_input = tree.css_first("input#practice_name")
    assert practice_input is not None
    assert practice_input.attributes.get("value") == practice_name
    kind_input = tree.css_first('input[name="kind"]')
    assert kind_input is not None
    assert kind_input.attributes.get("value") == "provider_availability"


async def test_owner_can_patch_provider_availability_practice_name(
    authenticated_client: AsyncClient,
    db_test_session_manager: async_sessionmaker[AsyncSession],
    logged_in_user: User,
):
    post = _provider_availability_post(practice_name="orig", owner_id=logged_in_user.id)
    async with db_test_session_manager() as session:
        async with session.begin():
            session.add(post)

    new_practice_name = f"Renamed-{uuid.uuid4()}"
    response = await authenticated_client.patch(
        f"/posts/{post.id}",
        data={
            "kind": "provider_availability",
            "practice_name": new_practice_name,
        },
    )
    assert response.status_code == 200
    assert response.headers.get("HX-Redirect") == f"/posts/{post.id}"
    body = response.json()
    assert body["kind"] == "provider_availability"
    assert body["practice_name"] == new_practice_name
    assert "title" not in body and "body" not in body and "description" not in body

    async with db_test_session_manager() as session:
        result = await session.execute(select(Post).filter(Post.id == post.id))
        refreshed = result.scalars().first()
        assert refreshed.provider_availability_detail.practice_name == new_practice_name


async def test_owner_can_delete_provider_availability(
    authenticated_client: AsyncClient,
    db_test_session_manager: async_sessionmaker[AsyncSession],
    logged_in_user: User,
):
    """`DELETE /posts/{id}` works for provider_availability; cascades the detail."""
    post = _provider_availability_post(
        practice_name="doomed", owner_id=logged_in_user.id
    )
    async with db_test_session_manager() as session:
        async with session.begin():
            session.add(post)
    post_id = post.id

    response = await authenticated_client.delete(f"/posts/{post_id}")
    assert response.status_code == 204

    async with db_test_session_manager() as session:
        post_row = (
            (await session.execute(select(Post).filter(Post.id == post_id)))
            .scalars()
            .first()
        )
        detail_row = (
            (
                await session.execute(
                    select(ProviderAvailabilityDetail).filter(
                        ProviderAvailabilityDetail.post_id == post_id
                    )
                )
            )
            .scalars()
            .first()
        )
        assert post_row is None
        assert detail_row is None


async def test_delete_provider_availability_writes_audit_row(
    authenticated_client: AsyncClient,
    db_test_session_manager: async_sessionmaker[AsyncSession],
    logged_in_user: User,
):
    practice_name = f"doomed-{uuid.uuid4()}"
    post = _provider_availability_post(
        practice_name=practice_name, owner_id=logged_in_user.id
    )
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
        assert rows[0].action == "delete_post"
        assert rows[0].before == {
            **provider_availability_payload(practice_name=practice_name),
            "owner_id": str(logged_in_user.id),
        }
        assert rows[0].after is None
