"""Tests for `GET /admin/audit` — the superuser-only audit log viewer.

Pins the auth ladder (anonymous → login, non-admin → 403, admin → 200),
the newest-first row rendering, and the `?page=` pagination seam.
"""

import uuid
from datetime import datetime, timedelta, timezone

import pytest
from httpx import AsyncClient
from selectolax.parser import HTMLParser
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from src.domain.models import User
from src.framework.audit.repository import AuditRepository
from tests.helpers import promote_to_admin

pytestmark = pytest.mark.asyncio


async def _record_rows(
    db_test_session_manager: async_sessionmaker[AsyncSession], n: int
) -> None:
    """Seed n system-actor rows with distinct, ascending `created_at`.

    `created_at`'s server default has second resolution on SQLite, so
    same-second rows order arbitrarily (stable `id` tie-break only) —
    explicit timestamps make newest-first assertable."""
    base = datetime.now(timezone.utc) - timedelta(hours=1)
    async with db_test_session_manager() as session:
        repo = AuditRepository(session)
        for i in range(n):
            row = await repo.record(
                actor_id=None,
                resource_type="post",
                resource_id=uuid.uuid4(),
                action=f"test_action_{i}",
                after={"marker": i},
            )
            row.created_at = base + timedelta(seconds=i)
        await session.commit()


async def test_anonymous_gets_401_and_browser_redirects_to_login(
    test_client: AsyncClient,
):
    """API-shaped requests get the raw 401; browser-shaped requests ride
    the global 401 handler to `/auth/login?next=...`."""
    response = await test_client.get("/admin/audit")
    assert response.status_code == 401

    response = await test_client.get("/admin/audit", headers={"accept": "text/html"})
    assert response.status_code == 302
    assert response.headers["location"] == "/auth/login?next=/admin/audit"


async def test_non_superuser_gets_403(authenticated_client: AsyncClient):
    """`current_admin_user` rejects a regular signed-in user before the
    handler runs — no audit data leaks to non-admins."""
    response = await authenticated_client.get("/admin/audit")
    assert response.status_code == 403


async def test_superuser_sees_rows_newest_first(
    authenticated_client: AsyncClient,
    logged_in_user: User,
    db_test_session_manager: async_sessionmaker[AsyncSession],
):
    await promote_to_admin(db_test_session_manager, logged_in_user.email)
    await _record_rows(db_test_session_manager, 3)

    response = await authenticated_client.get("/admin/audit")
    assert response.status_code == 200

    tree = HTMLParser(response.text)
    actions = [c.text(strip=True) for c in tree.css("#audit-list td code")]
    # Our three rows render newest-first. The fixture user's own
    # registration may also have audit rows, so assert relative order
    # of the seeded markers rather than an exact full-table match.
    seeded = [a for a in actions if a.startswith("test_action_")]
    assert seeded == ["test_action_2", "test_action_1", "test_action_0"]
    # The system-actor rows render the "system" placeholder.
    assert "system" in response.text


async def test_pagination_slices_pages(
    authenticated_client: AsyncClient,
    logged_in_user: User,
    db_test_session_manager: async_sessionmaker[AsyncSession],
):
    """With more rows than one page holds, page 1 links to page 2 and
    page 2 holds the remainder — the `+1` probe / `paginate` seam wired
    through `AUDIT_PAGE_SIZE`."""
    from src.domain.routes.admin import AUDIT_PAGE_SIZE

    await promote_to_admin(db_test_session_manager, logged_in_user.email)
    await _record_rows(db_test_session_manager, AUDIT_PAGE_SIZE + 1)

    response = await authenticated_client.get("/admin/audit")
    assert response.status_code == 200
    page_one = HTMLParser(response.text)
    assert len(page_one.css("#audit-list tbody tr")) == AUDIT_PAGE_SIZE
    next_link = page_one.css_first('.pagination-nav a[rel="next"]')
    assert next_link is not None
    assert next_link.attributes.get("href") == "?page=2"

    response = await authenticated_client.get("/admin/audit?page=2")
    assert response.status_code == 200
    page_two = HTMLParser(response.text)
    # The remainder: our +1 row plus whatever fixture-registration rows
    # spilled over — a non-empty, less-than-full page.
    remainder = page_two.css("#audit-list tbody tr")
    assert 0 < len(remainder) < AUDIT_PAGE_SIZE
    assert page_two.css_first('.pagination-nav a[rel="prev"]') is not None
