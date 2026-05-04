"""Route-layer tests for the kind-discriminated `/posts` API.

`Post` is polymorphic on `kind`: `client_referral` (multi-section intake
form: Client Location / Demographics / Description / Services / Insurance)
and `provider_availability` (specialty/region/accepting_new_clients) each
have their own child table (joined-table inheritance — see
`src/models/post.py`). These tests confirm:

- both kinds round-trip through POST/GET/PATCH/DELETE
- the unified GET /posts timeline returns rows of every kind
- the schema's discriminated unions reject unknown / missing kinds and
  enforce per-kind required fields
- both kinds have working PATCH + edit-form flows
- audit rows snapshot kind + per-kind fields alongside the owner
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


_DEFAULT_DESIRED_TIMES = ["monday_morning", "wednesday_evening"]
_DEFAULT_SERVICES = ["psychotherapy", "case_management"]


def _make_client_referral(
    owner: User,
    *,
    location_city: str = "Northampton",
    location_state: str = "MA",
    location_zip: str = "01060",
    location_in_person: str = "yes",
    location_virtual: str = "please_contact",
    desired_times: list[str] | None = None,
    client_dem_ages: str = "adults_25_64",
    language_preferred: str = "no",
    description: str = "needs placement",
    services: list[str] | None = None,
    services_psychotherapy_modality: str | None = "DBT",
    insurance: str = "in_network",
) -> ClientReferral:
    return ClientReferral(
        kind="client_referral",
        owner_id=owner.id,
        location_city=location_city,
        location_state=location_state,
        location_zip=location_zip,
        location_in_person=location_in_person,
        location_virtual=location_virtual,
        desired_times=(
            desired_times if desired_times is not None else list(_DEFAULT_DESIRED_TIMES)
        ),
        client_dem_ages=client_dem_ages,
        language_preferred=language_preferred,
        description=description,
        services=services if services is not None else list(_DEFAULT_SERVICES),
        services_psychotherapy_modality=services_psychotherapy_modality,
        insurance=insurance,
    )


def _make_provider_availability(
    owner: User,
    *,
    specialty: str = "psychiatry",
    region: str = "boston metro",
    accepting_new_clients: bool = True,
) -> ProviderAvailability:
    return ProviderAvailability(
        kind="provider_availability",
        owner_id=owner.id,
        specialty=specialty,
        region=region,
        accepting_new_clients=accepting_new_clients,
    )


_VALID_CLIENT_REFERRAL_PAYLOAD = {
    "kind": "client_referral",
    "location_city": "Northampton",
    "location_state": "MA",
    "location_zip": "01060",
    "location_in_person": "yes",
    "location_virtual": "please_contact",
    "desired_times": list(_DEFAULT_DESIRED_TIMES),
    "client_dem_ages": "adults_25_64",
    "language_preferred": "no",
    "description": "looking for outpatient placement",
    "services": list(_DEFAULT_SERVICES),
    "services_psychotherapy_modality": "DBT",
    "insurance": "in_network",
}

_VALID_PROVIDER_AVAILABILITY_PAYLOAD = {
    "kind": "provider_availability",
    "specialty": "psychiatry",
    "region": "boston metro",
    "accepting_new_clients": True,
}


def _client_referral_audit_snapshot(
    owner_id: uuid.UUID,
    *,
    location_city: str = "Northampton",
    location_state: str = "MA",
    location_zip: str = "01060",
    location_in_person: str = "yes",
    location_virtual: str = "please_contact",
    desired_times: list[str] | None = None,
    client_dem_ages: str = "adults_25_64",
    language_preferred: str = "no",
    description: str = "needs placement",
    services: list[str] | None = None,
    services_psychotherapy_modality: str | None = "DBT",
    insurance: str = "in_network",
) -> dict:
    """Build the expected `before`/`after` audit dict for a client_referral.

    Mirrors `PostAuditSnapshot`; provider_availability fields stay None.
    """
    return {
        "kind": "client_referral",
        "owner_id": str(owner_id),
        "location_city": location_city,
        "location_state": location_state,
        "location_zip": location_zip,
        "location_in_person": location_in_person,
        "location_virtual": location_virtual,
        "desired_times": (
            desired_times if desired_times is not None else list(_DEFAULT_DESIRED_TIMES)
        ),
        "client_dem_ages": client_dem_ages,
        "language_preferred": language_preferred,
        "description": description,
        "services": services if services is not None else list(_DEFAULT_SERVICES),
        "services_psychotherapy_modality": services_psychotherapy_modality,
        "insurance": insurance,
        "specialty": None,
        "region": None,
        "accepting_new_clients": None,
    }


# --- Listing -------------------------------------------------------------


async def test_list_posts_empty(
    authenticated_client: AsyncClient,
    logged_in_user: User,
):
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
    other = create_test_user(username=f"author-{uuid.uuid4()}")
    async with db_test_session_manager() as session:
        async with session.begin():
            session.add(other)
            session.add(
                _make_client_referral(other, description="referral-description")
            )
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
    # The client_referral row's link text uses its description.
    assert "referral-description" in tree.body.text()


async def test_list_posts_orders_newest_first(
    authenticated_client: AsyncClient,
    db_test_session_manager: async_sessionmaker[AsyncSession],
    logged_in_user: User,
):
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


async def test_list_posts_unauthenticated_redirects(test_client: AsyncClient):
    response = await test_client.get(
        "/posts", headers={"accept": "text/html"}, follow_redirects=False
    )
    assert response.status_code == 302
    assert "/auth/login" in response.headers["location"]
    assert "next=/posts" in response.headers["location"]


# --- Detail page ---------------------------------------------------------


async def test_detail_renders_client_referral_fields(
    authenticated_client: AsyncClient,
    db_test_session_manager: async_sessionmaker[AsyncSession],
    logged_in_user: User,
):
    author = create_test_user(username=f"author-{uuid.uuid4()}")
    post = _make_client_referral(
        author,
        description="placement",
        location_city="Boston",
        location_state="NY",
        insurance="out_of_network",
        desired_times=["tuesday_afternoon", "friday_evening"],
        services=["evaluation"],
    )
    async with db_test_session_manager() as session:
        async with session.begin():
            session.add(author)
            session.add(post)

    response = await authenticated_client.get(f"/posts/{post.id}")
    assert response.status_code == 200
    tree = HTMLParser(response.text)
    assert "client_referral" in response.text
    assert tree.css_first(".post-description").text(strip=True) == "placement"
    assert tree.css_first(".post-location-city").text(strip=True) == "Boston"
    assert tree.css_first(".post-location-state").text(strip=True) == "NY"

    insurance = tree.css_first(".post-insurance")
    assert insurance.attributes.get("data-insurance") == "out_of_network"

    time_slots = {
        node.attributes.get("data-time-slot")
        for node in tree.css(".post-desired-times li")
    }
    assert time_slots == {"tuesday_afternoon", "friday_evening"}

    services = {
        node.attributes.get("data-service") for node in tree.css(".post-services li")
    }
    assert services == {"evaluation"}


async def test_detail_renders_provider_availability_fields(
    authenticated_client: AsyncClient,
    db_test_session_manager: async_sessionmaker[AsyncSession],
    logged_in_user: User,
):
    author = create_test_user(username=f"author-{uuid.uuid4()}")
    post = _make_provider_availability(
        author,
        specialty="psychiatry",
        region="boston metro",
        accepting_new_clients=False,
    )
    async with db_test_session_manager() as session:
        async with session.begin():
            session.add(author)
            session.add(post)

    response = await authenticated_client.get(f"/posts/{post.id}")
    assert response.status_code == 200
    tree = HTMLParser(response.text)
    assert "provider_availability" in response.text
    assert tree.css_first(".post-specialty").text(strip=True) == "psychiatry"
    assert tree.css_first(".post-region").text(strip=True) == "boston metro"
    accepting = tree.css_first(".post-accepting-new-clients")
    assert accepting.attributes.get("data-accepting-new-clients") == "false"
    assert accepting.text(strip=True) == "no"


async def test_get_post_detail_404(
    authenticated_client: AsyncClient,
    logged_in_user: User,
):
    response = await authenticated_client.get(f"/posts/{uuid.uuid4()}")
    assert response.status_code == 404


async def test_get_post_detail_malformed_uuid_422(
    authenticated_client: AsyncClient,
    logged_in_user: User,
):
    response = await authenticated_client.get("/posts/not-a-uuid")
    assert response.status_code == 422


# --- Create --------------------------------------------------------------


async def test_create_client_referral_happy_path(
    authenticated_client: AsyncClient,
    db_test_session_manager: async_sessionmaker[AsyncSession],
    logged_in_user: User,
):
    response = await authenticated_client.post(
        "/posts", json=_VALID_CLIENT_REFERRAL_PAYLOAD
    )
    assert response.status_code == 201
    new_id = uuid.UUID(response.json()["id"])
    assert response.headers.get("Location") == f"/posts/{new_id}"

    async with db_test_session_manager() as session:
        result = await session.execute(
            select(ClientReferral).filter(ClientReferral.id == new_id)
        )
        persisted = result.scalars().first()
        assert persisted is not None
        assert persisted.kind == "client_referral"
        assert persisted.owner_id == logged_in_user.id
        assert persisted.location_city == "Northampton"
        assert persisted.location_state == "MA"
        assert persisted.location_zip == "01060"
        assert persisted.location_in_person == "yes"
        assert persisted.location_virtual == "please_contact"
        assert persisted.desired_times == _DEFAULT_DESIRED_TIMES
        assert persisted.client_dem_ages == "adults_25_64"
        assert persisted.language_preferred == "no"
        assert persisted.description == "looking for outpatient placement"
        assert persisted.services == _DEFAULT_SERVICES
        assert persisted.services_psychotherapy_modality == "DBT"
        assert persisted.insurance == "in_network"


async def test_create_client_referral_allows_empty_multiselects(
    authenticated_client: AsyncClient,
    db_test_session_manager: async_sessionmaker[AsyncSession],
    logged_in_user: User,
):
    """Form-submitted payloads omit `desired_times` / `services` when no
    checkbox is ticked — schema defaults both to `[]`."""
    payload = {**_VALID_CLIENT_REFERRAL_PAYLOAD}
    payload.pop("desired_times")
    payload.pop("services")
    payload.pop("services_psychotherapy_modality")

    response = await authenticated_client.post("/posts", json=payload)
    assert response.status_code == 201
    new_id = uuid.UUID(response.json()["id"])

    async with db_test_session_manager() as session:
        result = await session.execute(
            select(ClientReferral).filter(ClientReferral.id == new_id)
        )
        persisted = result.scalars().first()
        assert persisted.desired_times == []
        assert persisted.services == []
        assert persisted.services_psychotherapy_modality is None


async def test_create_provider_availability_happy_path(
    authenticated_client: AsyncClient,
    db_test_session_manager: async_sessionmaker[AsyncSession],
    logged_in_user: User,
):
    response = await authenticated_client.post(
        "/posts", json=_VALID_PROVIDER_AVAILABILITY_PAYLOAD
    )
    assert response.status_code == 201
    new_id = uuid.UUID(response.json()["id"])

    async with db_test_session_manager() as session:
        result = await session.execute(
            select(ProviderAvailability).filter(ProviderAvailability.id == new_id)
        )
        persisted = result.scalars().first()
        assert persisted is not None
        assert persisted.kind == "provider_availability"
        assert persisted.owner_id == logged_in_user.id
        assert persisted.specialty == "psychiatry"
        assert persisted.region == "boston metro"
        assert persisted.accepting_new_clients is True


async def test_create_post_strips_whitespace(
    authenticated_client: AsyncClient,
    db_test_session_manager: async_sessionmaker[AsyncSession],
    logged_in_user: User,
):
    payload = {
        **_VALID_CLIENT_REFERRAL_PAYLOAD,
        "location_city": "  Boston  ",
        "description": "  needs help  ",
    }
    response = await authenticated_client.post("/posts", json=payload)
    assert response.status_code == 201
    new_id = uuid.UUID(response.json()["id"])

    async with db_test_session_manager() as session:
        result = await session.execute(
            select(ClientReferral).filter(ClientReferral.id == new_id)
        )
        persisted = result.scalars().first()
        assert persisted.location_city == "Boston"
        assert persisted.description == "needs help"


async def test_create_post_rejects_owner_id_in_payload(
    authenticated_client: AsyncClient,
    db_test_session_manager: async_sessionmaker[AsyncSession],
    logged_in_user: User,
):
    other = create_test_user(username=f"other-{uuid.uuid4()}")
    async with db_test_session_manager() as session:
        async with session.begin():
            session.add(other)

    response = await authenticated_client.post(
        "/posts",
        json={**_VALID_CLIENT_REFERRAL_PAYLOAD, "owner_id": str(other.id)},
    )
    assert response.status_code == 422

    async with db_test_session_manager() as session:
        result = await session.execute(select(Post))
        assert result.scalars().first() is None


async def test_create_post_rejects_unknown_field(
    authenticated_client: AsyncClient,
    logged_in_user: User,
):
    response = await authenticated_client.post(
        "/posts", json={**_VALID_CLIENT_REFERRAL_PAYLOAD, "summary": "old"}
    )
    assert response.status_code == 422


@pytest.mark.parametrize(
    "payload",
    [
        {},
        {"kind": "not_a_real_kind"},
        # client_referral missing required fields
        {"kind": "client_referral"},
        # bad enum values
        {**_VALID_CLIENT_REFERRAL_PAYLOAD, "location_state": "ZZ"},
        {**_VALID_CLIENT_REFERRAL_PAYLOAD, "insurance": "self_pay"},
        {**_VALID_CLIENT_REFERRAL_PAYLOAD, "client_dem_ages": "EVERYONE"},
        # bad zip
        {**_VALID_CLIENT_REFERRAL_PAYLOAD, "location_zip": "1234"},
        # whitespace-only required fields
        {**_VALID_CLIENT_REFERRAL_PAYLOAD, "description": "   "},
        # bad multiselect element
        {**_VALID_CLIENT_REFERRAL_PAYLOAD, "services": ["telepathy"]},
    ],
)
async def test_create_post_rejects_invalid_payload(
    payload,
    authenticated_client: AsyncClient,
    logged_in_user: User,
):
    response = await authenticated_client.post("/posts", json=payload)
    assert response.status_code == 422


async def test_create_post_unauthenticated_redirects(test_client: AsyncClient):
    response = await test_client.post(
        "/posts",
        json=_VALID_CLIENT_REFERRAL_PAYLOAD,
        headers={"accept": "text/html"},
        follow_redirects=False,
    )
    assert response.status_code == 302
    assert "/auth/login" in response.headers["location"]


# --- Update (PATCH) ------------------------------------------------------


async def test_owner_can_patch_description_only(
    authenticated_client: AsyncClient,
    db_test_session_manager: async_sessionmaker[AsyncSession],
    logged_in_user: User,
):
    post = _make_client_referral(
        logged_in_user, description="orig", location_city="orig-city"
    )
    async with db_test_session_manager() as session:
        async with session.begin():
            session.add(post)

    response = await authenticated_client.patch(
        f"/posts/{post.id}",
        json={"kind": "client_referral", "description": "new"},
    )
    assert response.status_code == 200
    assert response.headers.get("HX-Refresh") == "true"

    async with db_test_session_manager() as session:
        result = await session.execute(
            select(ClientReferral).filter(ClientReferral.id == post.id)
        )
        refreshed = result.scalars().first()
        assert refreshed.description == "new"
        assert refreshed.location_city == "orig-city"  # untouched


async def test_owner_can_patch_multiple_fields(
    authenticated_client: AsyncClient,
    db_test_session_manager: async_sessionmaker[AsyncSession],
    logged_in_user: User,
):
    post = _make_client_referral(logged_in_user)
    async with db_test_session_manager() as session:
        async with session.begin():
            session.add(post)

    response = await authenticated_client.patch(
        f"/posts/{post.id}",
        json={
            "kind": "client_referral",
            "description": "D2",
            "insurance": "out_of_network",
            "location_state": "NY",
            "services": ["evaluation"],
        },
    )
    assert response.status_code == 200

    async with db_test_session_manager() as session:
        result = await session.execute(
            select(ClientReferral).filter(ClientReferral.id == post.id)
        )
        refreshed = result.scalars().first()
        assert refreshed.description == "D2"
        assert refreshed.insurance == "out_of_network"
        assert refreshed.location_state == "NY"
        assert refreshed.services == ["evaluation"]


async def test_non_owner_cannot_patch_post(
    authenticated_client: AsyncClient,
    db_test_session_manager: async_sessionmaker[AsyncSession],
    logged_in_user: User,
):
    other = create_test_user(username=f"other-{uuid.uuid4()}")
    post = _make_client_referral(other, description="orig")
    async with db_test_session_manager() as session:
        async with session.begin():
            session.add(other)
            session.add(post)

    response = await authenticated_client.patch(
        f"/posts/{post.id}",
        json={"kind": "client_referral", "description": "hijack"},
    )
    assert response.status_code == 403

    async with db_test_session_manager() as session:
        result = await session.execute(
            select(ClientReferral).filter(ClientReferral.id == post.id)
        )
        refreshed = result.scalars().first()
        assert refreshed.description == "orig"


async def test_admin_can_patch_anyone_post(
    authenticated_client: AsyncClient,
    db_test_session_manager: async_sessionmaker[AsyncSession],
    logged_in_user: User,
):
    await promote_to_admin(db_test_session_manager, logged_in_user.email)
    other = create_test_user(username=f"other-{uuid.uuid4()}")
    post = _make_client_referral(other, description="orig")
    async with db_test_session_manager() as session:
        async with session.begin():
            session.add(other)
            session.add(post)

    response = await authenticated_client.patch(
        f"/posts/{post.id}",
        json={"kind": "client_referral", "description": "moderated"},
    )
    assert response.status_code == 200


async def test_patch_404_for_unknown_post(
    authenticated_client: AsyncClient,
    logged_in_user: User,
):
    response = await authenticated_client.patch(
        f"/posts/{uuid.uuid4()}",
        json={"kind": "client_referral", "description": "x"},
    )
    assert response.status_code == 404


async def test_patch_kind_mismatch_returns_400(
    authenticated_client: AsyncClient,
    db_test_session_manager: async_sessionmaker[AsyncSession],
    logged_in_user: User,
):
    """The body's kind discriminator must match the persisted post's kind —
    a PATCH cannot repurpose a post's identity."""
    post = _make_provider_availability(logged_in_user)
    async with db_test_session_manager() as session:
        async with session.begin():
            session.add(post)

    response = await authenticated_client.patch(
        f"/posts/{post.id}",
        json={"kind": "client_referral", "description": "x"},
    )
    assert response.status_code == 400


async def test_owner_can_patch_provider_availability(
    authenticated_client: AsyncClient,
    db_test_session_manager: async_sessionmaker[AsyncSession],
    logged_in_user: User,
):
    post = _make_provider_availability(
        logged_in_user,
        specialty="orig",
        region="orig-region",
        accepting_new_clients=True,
    )
    async with db_test_session_manager() as session:
        async with session.begin():
            session.add(post)

    response = await authenticated_client.patch(
        f"/posts/{post.id}",
        json={
            "kind": "provider_availability",
            "specialty": "S2",
            "accepting_new_clients": False,
        },
    )
    assert response.status_code == 200

    async with db_test_session_manager() as session:
        result = await session.execute(
            select(ProviderAvailability).filter(ProviderAvailability.id == post.id)
        )
        refreshed = result.scalars().first()
        assert refreshed.specialty == "S2"
        assert refreshed.region == "orig-region"  # untouched
        assert refreshed.accepting_new_clients is False


async def test_patch_rejects_owner_id_in_payload(
    authenticated_client: AsyncClient,
    db_test_session_manager: async_sessionmaker[AsyncSession],
    logged_in_user: User,
):
    post = _make_client_referral(logged_in_user)
    other = create_test_user(username=f"other-{uuid.uuid4()}")
    async with db_test_session_manager() as session:
        async with session.begin():
            session.add(other)
            session.add(post)

    response = await authenticated_client.patch(
        f"/posts/{post.id}",
        json={
            "kind": "client_referral",
            "description": "d",
            "owner_id": str(other.id),
        },
    )
    assert response.status_code == 422


@pytest.mark.parametrize(
    "patch_body",
    [
        {},
        {"kind": "client_referral"},
        {"kind": "client_referral", "description": "   "},
        {
            "kind": "client_referral",
            "description": None,
            "insurance": None,
            "location_state": None,
        },
        {"kind": "client_referral", "insurance": "self_pay"},
        {"kind": "client_referral", "location_zip": "12"},
    ],
)
async def test_patch_invalid_body_422(
    patch_body,
    authenticated_client: AsyncClient,
    db_test_session_manager: async_sessionmaker[AsyncSession],
    logged_in_user: User,
):
    post = _make_client_referral(logged_in_user)
    async with db_test_session_manager() as session:
        async with session.begin():
            session.add(post)

    response = await authenticated_client.patch(f"/posts/{post.id}", json=patch_body)
    assert response.status_code == 422


async def test_patch_unauthenticated_redirects(test_client: AsyncClient):
    response = await test_client.patch(
        f"/posts/{uuid.uuid4()}",
        json={"kind": "client_referral", "description": "x"},
        headers={"accept": "text/html"},
        follow_redirects=False,
    )
    assert response.status_code == 302
    assert "/auth/login" in response.headers["location"]


# --- Create form page (GET /posts/form) ----------------------------------


async def test_get_post_form_renders_kind_and_field_clusters(
    authenticated_client: AsyncClient,
    logged_in_user: User,
):
    response = await authenticated_client.get("/posts/form")
    assert response.status_code == 200
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

    # client_referral cluster has all five sections.
    assert tree.css_first('input[name="location_city"]') is not None
    assert tree.css_first('select[name="location_state"]') is not None
    assert tree.css_first('input[name="location_zip"]') is not None
    assert tree.css_first('select[name="location_in_person"]') is not None
    assert tree.css_first('select[name="location_virtual"]') is not None
    # 21 desired_times checkboxes
    desired = tree.css('input[type="checkbox"][name="desired_times"]')
    assert len(desired) == 21
    assert tree.css_first('select[name="client_dem_ages"]') is not None
    assert tree.css_first('select[name="language_preferred"]') is not None
    assert tree.css_first('textarea[name="description"]') is not None
    # 5 service checkboxes
    services = tree.css('input[type="checkbox"][name="services"]')
    assert len(services) == 5
    assert tree.css_first('input[name="services_psychotherapy_modality"]') is not None
    assert tree.css_first('select[name="insurance"]') is not None


async def test_get_post_form_unauthenticated_redirects(test_client: AsyncClient):
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


# --- Edit form page (GET /posts/{id}/form) -------------------------------


async def test_owner_can_open_client_referral_edit_form(
    authenticated_client: AsyncClient,
    db_test_session_manager: async_sessionmaker[AsyncSession],
    logged_in_user: User,
):
    post = _make_client_referral(
        logged_in_user,
        description="orig description",
        location_city="orig-city",
        location_state="NY",
        insurance="out_of_network",
        desired_times=["thursday_morning"],
        services=["evaluation"],
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

    description = tree.css_first('textarea[name="description"]')
    assert description is not None
    assert "orig description" in description.text()

    state = tree.css_first('select[name="location_state"] option[selected]')
    assert state is not None
    assert state.attributes.get("value") == "NY"

    insurance = tree.css_first('select[name="insurance"] option[selected]')
    assert insurance is not None
    assert insurance.attributes.get("value") == "out_of_network"

    city = tree.css_first('input[name="location_city"]')
    assert city is not None
    assert city.attributes.get("value") == "orig-city"

    checked_times = {
        node.attributes.get("value")
        for node in tree.css('input[type="checkbox"][name="desired_times"]')
        if "checked" in node.attributes
    }
    assert checked_times == {"thursday_morning"}

    checked_services = {
        node.attributes.get("value")
        for node in tree.css('input[type="checkbox"][name="services"]')
        if "checked" in node.attributes
    }
    assert checked_services == {"evaluation"}

    # Hidden discriminator so the PATCH body carries the right `kind`.
    discriminator = tree.css_first('input[type="hidden"][name="kind"]')
    assert discriminator is not None
    assert discriminator.attributes.get("value") == "client_referral"


async def test_admin_can_open_edit_form_for_any_post(
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

    response = await authenticated_client.get(f"/posts/{post.id}/form")
    assert response.status_code == 200


async def test_non_owner_cannot_open_edit_form(
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

    response = await authenticated_client.get(f"/posts/{post.id}/form")
    assert response.status_code == 403


async def test_edit_form_404_for_unknown_post(
    authenticated_client: AsyncClient,
    logged_in_user: User,
):
    response = await authenticated_client.get(f"/posts/{uuid.uuid4()}/form")
    assert response.status_code == 404


async def test_owner_can_open_provider_availability_edit_form(
    authenticated_client: AsyncClient,
    db_test_session_manager: async_sessionmaker[AsyncSession],
    logged_in_user: User,
):
    post = _make_provider_availability(
        logged_in_user,
        specialty="orig-specialty",
        region="orig-region",
        accepting_new_clients=False,
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

    discriminator = tree.css_first('input[type="hidden"][name="kind"]')
    assert discriminator.attributes.get("value") == "provider_availability"
    assert (
        tree.css_first('input[name="specialty"]').attributes.get("value")
        == "orig-specialty"
    )
    assert (
        tree.css_first('input[name="region"]').attributes.get("value") == "orig-region"
    )
    accepting_no = tree.css_first(
        'input[type="radio"][name="accepting_new_clients"][value="false"][checked]'
    )
    assert accepting_no is not None


async def test_edit_form_unauthenticated_redirects(test_client: AsyncClient):
    response = await test_client.get(
        f"/posts/{uuid.uuid4()}/form",
        headers={"accept": "text/html"},
        follow_redirects=False,
    )
    assert response.status_code == 302
    assert "/auth/login" in response.headers["location"]


# --- Owner-actions partial visibility on detail page ---------------------


async def test_detail_shows_edit_link_for_client_referral_owner(
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
    assert actions.css_first(f'a[href="/posts/{post.id}/form"]') is not None


async def test_detail_shows_edit_link_for_provider_availability_owner(
    authenticated_client: AsyncClient,
    db_test_session_manager: async_sessionmaker[AsyncSession],
    logged_in_user: User,
):
    post = _make_provider_availability(logged_in_user)
    async with db_test_session_manager() as session:
        async with session.begin():
            session.add(post)

    response = await authenticated_client.get(f"/posts/{post.id}")
    assert response.status_code == 200
    tree = HTMLParser(response.text)
    actions = tree.css_first("span.owner-actions")
    assert actions is not None
    assert actions.css_first(f'a[href="/posts/{post.id}/form"]') is not None


async def test_detail_hides_owner_actions_for_stranger(
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


async def test_detail_delete_button_for_owner(
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
    button = tree.css_first("span.owner-actions button")
    assert button is not None
    assert button.text().strip() == "Delete"
    assert button.attributes.get("hx-delete") == f"/posts/{post.id}"
    assert button.attributes.get("hx-confirm")


# --- Audit log -----------------------------------------------------------


async def test_create_client_referral_writes_audit_row(
    authenticated_client: AsyncClient,
    db_test_session_manager: async_sessionmaker[AsyncSession],
    logged_in_user: User,
):
    response = await authenticated_client.post(
        "/posts", json=_VALID_CLIENT_REFERRAL_PAYLOAD
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
        assert row.after == _client_referral_audit_snapshot(
            logged_in_user.id,
            description="looking for outpatient placement",
        )


async def test_create_provider_availability_audit_includes_kind_fields(
    authenticated_client: AsyncClient,
    db_test_session_manager: async_sessionmaker[AsyncSession],
    logged_in_user: User,
):
    """The audit snapshot is shape-uniform across kinds: each kind's fields
    fill in the snapshot, the rest stay None."""
    response = await authenticated_client.post(
        "/posts", json=_VALID_PROVIDER_AVAILABILITY_PAYLOAD
    )
    assert response.status_code == 201
    new_id = uuid.UUID(response.json()["id"])

    async with db_test_session_manager() as session:
        repo = AuditRepository(session)
        rows = await repo.list_for_resource(resource_type="post", resource_id=new_id)
        assert len(rows) == 1
        snapshot = rows[0].after
        assert snapshot["kind"] == "provider_availability"
        assert snapshot["owner_id"] == str(logged_in_user.id)
        assert snapshot["specialty"] == "psychiatry"
        assert snapshot["region"] == "boston metro"
        assert snapshot["accepting_new_clients"] is True
        # client_referral fields stay None on a provider_availability snapshot.
        for field in (
            "location_city",
            "location_state",
            "location_zip",
            "location_in_person",
            "location_virtual",
            "desired_times",
            "client_dem_ages",
            "language_preferred",
            "description",
            "services",
            "services_psychotherapy_modality",
            "insurance",
        ):
            assert snapshot[field] is None


async def test_patch_writes_audit_row_with_before_and_after(
    authenticated_client: AsyncClient,
    db_test_session_manager: async_sessionmaker[AsyncSession],
    logged_in_user: User,
):
    post = _make_client_referral(
        logged_in_user, description="orig", insurance="in_network"
    )
    async with db_test_session_manager() as session:
        async with session.begin():
            session.add(post)

    response = await authenticated_client.patch(
        f"/posts/{post.id}",
        json={
            "kind": "client_referral",
            "description": "new",
            "insurance": "out_of_network",
        },
    )
    assert response.status_code == 200

    async with db_test_session_manager() as session:
        repo = AuditRepository(session)
        rows = await repo.list_for_resource(resource_type="post", resource_id=post.id)
        assert len(rows) == 1
        row = rows[0]
        assert row.action == "update_post"
        assert row.before == _client_referral_audit_snapshot(
            logged_in_user.id, description="orig", insurance="in_network"
        )
        assert row.after == _client_referral_audit_snapshot(
            logged_in_user.id, description="new", insurance="out_of_network"
        )


async def test_failed_create_writes_no_audit_row(
    authenticated_client: AsyncClient,
    db_test_session_manager: async_sessionmaker[AsyncSession],
    logged_in_user: User,
):
    response = await authenticated_client.post("/posts", json={"kind": "not_a_kind"})
    assert response.status_code == 422

    async with db_test_session_manager() as session:
        result = await session.execute(
            select(AuditLog).filter(AuditLog.resource_type == "post")
        )
        assert result.scalars().first() is None


async def test_unauthorized_patch_writes_no_audit_row(
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

    response = await authenticated_client.patch(
        f"/posts/{post.id}",
        json={"kind": "client_referral", "description": "hijack"},
    )
    assert response.status_code == 403

    async with db_test_session_manager() as session:
        repo = AuditRepository(session)
        rows = await repo.list_for_resource(resource_type="post", resource_id=post.id)
        assert rows == []


# --- Delete (DELETE) -----------------------------------------------------


async def test_owner_can_delete_own_post(
    authenticated_client: AsyncClient,
    db_test_session_manager: async_sessionmaker[AsyncSession],
    logged_in_user: User,
):
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
    await promote_to_admin(db_test_session_manager, logged_in_user.email)
    other = create_test_user(username=f"other-{uuid.uuid4()}")
    post = _make_provider_availability(other)
    async with db_test_session_manager() as session:
        async with session.begin():
            session.add(other)
            session.add(post)

    response = await authenticated_client.delete(f"/posts/{post.id}")
    assert response.status_code == 204


async def test_non_owner_cannot_delete_post(
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

    response = await authenticated_client.delete(f"/posts/{post.id}")
    assert response.status_code == 403


async def test_delete_404_for_unknown_post(
    authenticated_client: AsyncClient,
    logged_in_user: User,
):
    response = await authenticated_client.delete(f"/posts/{uuid.uuid4()}")
    assert response.status_code == 404


async def test_delete_unauthenticated_redirects(test_client: AsyncClient):
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
    post = _make_client_referral(
        logged_in_user, description="doomed", insurance="in_network"
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
        row = rows[0]
        assert row.action == "delete_post"
        assert row.before == _client_referral_audit_snapshot(
            logged_in_user.id, description="doomed", insurance="in_network"
        )
        assert row.after is None
