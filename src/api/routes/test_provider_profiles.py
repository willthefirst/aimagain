import uuid

import pytest
from httpx import AsyncClient
from selectolax.parser import HTMLParser
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from src.models import (
    ProviderCertification,
    ProviderEducation,
    ProviderLicensure,
    ProviderProfile,
    User,
)
from src.repositories.audit_repository import AuditRepository
from tests.helpers import (
    certification_payload,
    create_test_user,
    education_payload,
    licensure_payload,
    make_provider_certification,
    make_provider_education,
    make_provider_licensure,
    make_provider_profile,
    promote_to_admin,
    provider_profile_payload,
)

pytestmark = pytest.mark.asyncio


# --- Helpers -------------------------------------------------------------


async def _seed_profile_for(
    db_test_session_manager: async_sessionmaker[AsyncSession],
    *,
    user_id: uuid.UUID,
    **overrides,
) -> uuid.UUID:
    """Insert a profile owned by `user_id` and return its id."""
    profile = make_provider_profile(user_id=user_id, **overrides)
    async with db_test_session_manager() as session:
        async with session.begin():
            session.add(profile)
        await session.refresh(profile)
        return profile.id


async def _seed_other_user_with_profile(
    db_test_session_manager: async_sessionmaker[AsyncSession],
) -> tuple[uuid.UUID, uuid.UUID]:
    """Create a second user + their profile. Returns (user_id, profile_id)."""
    other = create_test_user(username=f"other-{uuid.uuid4()}")
    async with db_test_session_manager() as session:
        async with session.begin():
            session.add(other)
    profile_id = await _seed_profile_for(db_test_session_manager, user_id=other.id)
    return other.id, profile_id


async def _audit_rows_for(
    db_test_session_manager: async_sessionmaker[AsyncSession],
    *,
    resource_type: str,
    resource_id: uuid.UUID,
):
    async with db_test_session_manager() as session:
        repo = AuditRepository(session)
        return await repo.list_for_resource(
            resource_type=resource_type, resource_id=resource_id
        )


# --- Profile create ------------------------------------------------------


async def test_create_profile_happy_path(
    authenticated_client: AsyncClient,
    db_test_session_manager: async_sessionmaker[AsyncSession],
    logged_in_user: User,
):
    """POST /provider-profiles with a form-encoded body returns 201 + id and
    persists the profile and an audit row."""
    response = await authenticated_client.post(
        "/provider-profiles",
        data=provider_profile_payload(practice_name="Acme Therapy"),
    )

    assert response.status_code == 201
    new_id = uuid.UUID(response.json()["id"])
    assert response.headers["Location"] == f"/provider-profiles/{new_id}"
    assert response.headers["HX-Redirect"] == f"/provider-profiles/{new_id}/form"

    async with db_test_session_manager() as session:
        result = await session.execute(
            select(ProviderProfile).filter(ProviderProfile.id == new_id)
        )
        persisted = result.scalars().first()
        assert persisted is not None
        assert persisted.user_id == logged_in_user.id
        assert persisted.practice_name == "Acme Therapy"

    rows = await _audit_rows_for(
        db_test_session_manager,
        resource_type="provider_profile",
        resource_id=new_id,
    )
    assert len(rows) == 1
    assert rows[0].action == "create_provider_profile"
    assert rows[0].actor_id == logged_in_user.id


async def test_create_profile_returns_400_if_already_exists(
    authenticated_client: AsyncClient,
    db_test_session_manager: async_sessionmaker[AsyncSession],
    logged_in_user: User,
):
    """The one-profile-per-user uniqueness rule surfaces as 400 on second POST."""
    first = await authenticated_client.post(
        "/provider-profiles", data=provider_profile_payload()
    )
    assert first.status_code == 201

    second = await authenticated_client.post(
        "/provider-profiles", data=provider_profile_payload(practice_name="Other")
    )
    assert second.status_code == 400


async def test_create_profile_rejects_unknown_field(
    authenticated_client: AsyncClient,
    logged_in_user: User,
):
    """`extra='forbid'` on the schema rejects unknown form fields with 422."""
    response = await authenticated_client.post(
        "/provider-profiles",
        data=provider_profile_payload(user_id=str(uuid.uuid4())),
    )
    assert response.status_code == 422


# --- Profile reads -------------------------------------------------------


async def test_get_profile_renders_detail_page(
    authenticated_client: AsyncClient,
    db_test_session_manager: async_sessionmaker[AsyncSession],
    logged_in_user: User,
):
    """`GET /provider-profiles/{id}` renders the read-only HTML detail page
    with practice fields and an Edit link for the owner."""
    profile_id = await _seed_profile_for(
        db_test_session_manager, user_id=logged_in_user.id, practice_name="Mine"
    )
    licensure = make_provider_licensure(
        profile_id=profile_id, license_type="lcsw", license_number="L-99999"
    )
    async with db_test_session_manager() as session:
        async with session.begin():
            session.add(licensure)

    response = await authenticated_client.get(f"/provider-profiles/{profile_id}")

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/html")
    tree = HTMLParser(response.text)
    assert "Mine" in tree.css_first("h1").text()
    # Licensure section renders the seeded row.
    assert "L-99999" in response.text
    # Owner sees an Edit link, no edit forms (read-only).
    assert tree.css_first(f'a[href="/provider-profiles/{profile_id}/form"]') is not None
    assert tree.css_first("form") is None


async def test_get_profile_hides_edit_link_for_non_owner(
    authenticated_client: AsyncClient,
    db_test_session_manager: async_sessionmaker[AsyncSession],
    logged_in_user: User,
):
    """A non-owner viewing someone else's profile sees the detail content
    but no Edit link."""
    other = create_test_user(username=f"other-{uuid.uuid4()}")
    async with db_test_session_manager() as session:
        async with session.begin():
            session.add(other)
    profile_id = await _seed_profile_for(db_test_session_manager, user_id=other.id)

    response = await authenticated_client.get(f"/provider-profiles/{profile_id}")

    assert response.status_code == 200
    tree = HTMLParser(response.text)
    assert tree.css_first(f'a[href="/provider-profiles/{profile_id}/form"]') is None


async def test_get_profile_returns_404_for_unknown_id(
    authenticated_client: AsyncClient,
    logged_in_user: User,
):
    response = await authenticated_client.get(f"/provider-profiles/{uuid.uuid4()}")
    assert response.status_code == 404


async def test_get_my_profile_renders_detail_page(
    authenticated_client: AsyncClient,
    db_test_session_manager: async_sessionmaker[AsyncSession],
    logged_in_user: User,
):
    """`GET /provider-profiles/me` renders the same detail template for the
    requesting user's profile."""
    profile_id = await _seed_profile_for(
        db_test_session_manager, user_id=logged_in_user.id, practice_name="Solo"
    )

    response = await authenticated_client.get("/provider-profiles/me")

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/html")
    tree = HTMLParser(response.text)
    assert "Solo" in tree.css_first("h1").text()
    # Owner — Edit link is present.
    assert tree.css_first(f'a[href="/provider-profiles/{profile_id}/form"]') is not None


async def test_get_my_profile_returns_404_when_not_created(
    authenticated_client: AsyncClient,
    logged_in_user: User,
):
    response = await authenticated_client.get("/provider-profiles/me")
    assert response.status_code == 404


# --- Profile listing -----------------------------------------------------


async def test_list_profiles_renders_html_for_public(
    test_client: AsyncClient,
    db_test_session_manager: async_sessionmaker[AsyncSession],
):
    """The list endpoint requires no authentication and renders an HTML
    page with one entry per persisted profile."""
    other = create_test_user(username=f"public-{uuid.uuid4()}")
    async with db_test_session_manager() as session:
        async with session.begin():
            session.add(other)
    profile_id = await _seed_profile_for(
        db_test_session_manager, user_id=other.id, practice_name="Open House"
    )

    response = await test_client.get("/provider-profiles")

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/html")
    tree = HTMLParser(response.text)
    items = tree.css("ul.profiles-list li")
    assert len(items) == 1
    assert tree.css_first(f'a[href="/provider-profiles/{profile_id}"]') is not None
    assert "Open House" in response.text


async def test_list_profiles_renders_empty_state(
    test_client: AsyncClient,
):
    """With no persisted profiles, the page renders a friendly empty
    message instead of an empty `<ul>`."""
    response = await test_client.get("/provider-profiles")
    assert response.status_code == 200
    assert "No provider profiles found" in response.text
    tree = HTMLParser(response.text)
    assert tree.css_first("ul.profiles-list") is None


async def test_list_profiles_filters_by_license_type(
    test_client: AsyncClient,
    db_test_session_manager: async_sessionmaker[AsyncSession],
):
    """`?license_type=` keeps only profiles holding a matching licensure;
    the filter form preselects the active value."""
    user_a = create_test_user(username=f"ua-{uuid.uuid4()}")
    user_b = create_test_user(username=f"ub-{uuid.uuid4()}")
    async with db_test_session_manager() as session:
        async with session.begin():
            session.add(user_a)
            session.add(user_b)
    profile_a = await _seed_profile_for(
        db_test_session_manager, user_id=user_a.id, practice_name="A clinic"
    )
    profile_b = await _seed_profile_for(
        db_test_session_manager, user_id=user_b.id, practice_name="B clinic"
    )

    async with db_test_session_manager() as session:
        async with session.begin():
            session.add(
                make_provider_licensure(profile_id=profile_a, license_type="psyd")
            )
            session.add(
                make_provider_licensure(profile_id=profile_b, license_type="lcsw")
            )

    response = await test_client.get("/provider-profiles?license_type=psyd")

    assert response.status_code == 200
    tree = HTMLParser(response.text)
    items = tree.css("ul.profiles-list li")
    assert len(items) == 1
    assert tree.css_first(f'a[href="/provider-profiles/{profile_a}"]') is not None
    assert tree.css_first(f'a[href="/provider-profiles/{profile_b}"]') is None
    # Filter form preserves the active selection.
    selected = tree.css_first('select[name="license_type"] option[selected]')
    assert selected is not None
    assert selected.attributes.get("value") == "psyd"


# --- Profile update ------------------------------------------------------


async def test_patch_profile_updates_fields(
    authenticated_client: AsyncClient,
    db_test_session_manager: async_sessionmaker[AsyncSession],
    logged_in_user: User,
):
    profile_id = await _seed_profile_for(
        db_test_session_manager, user_id=logged_in_user.id, practice_name="Old Name"
    )

    response = await authenticated_client.patch(
        f"/provider-profiles/{profile_id}",
        data={"practice_name": "New Name"},
    )

    assert response.status_code == 200
    assert response.json()["practice_name"] == "New Name"
    assert response.headers["HX-Redirect"] == f"/provider-profiles/{profile_id}/form"

    async with db_test_session_manager() as session:
        refreshed = (
            (
                await session.execute(
                    select(ProviderProfile).filter(ProviderProfile.id == profile_id)
                )
            )
            .scalars()
            .first()
        )
        assert refreshed.practice_name == "New Name"


async def test_patch_profile_returns_403_if_not_owner(
    authenticated_client: AsyncClient,
    db_test_session_manager: async_sessionmaker[AsyncSession],
    logged_in_user: User,
):
    _, other_profile_id = await _seed_other_user_with_profile(db_test_session_manager)

    response = await authenticated_client.patch(
        f"/provider-profiles/{other_profile_id}",
        data={"practice_name": "Hijack"},
    )
    assert response.status_code == 403


# --- Profile delete ------------------------------------------------------


async def test_delete_profile_returns_204_and_cascades(
    authenticated_client: AsyncClient,
    db_test_session_manager: async_sessionmaker[AsyncSession],
    logged_in_user: User,
):
    profile_id = await _seed_profile_for(
        db_test_session_manager, user_id=logged_in_user.id
    )
    async with db_test_session_manager() as session:
        async with session.begin():
            session.add(make_provider_licensure(profile_id=profile_id))
            session.add(make_provider_education(profile_id=profile_id))
            session.add(make_provider_certification(profile_id=profile_id))

    response = await authenticated_client.delete(f"/provider-profiles/{profile_id}")
    assert response.status_code == 204

    async with db_test_session_manager() as session:
        assert (
            await session.execute(
                select(ProviderProfile).filter(ProviderProfile.id == profile_id)
            )
        ).scalars().first() is None
        # Sub-rows cascade-deleted via FK ON DELETE CASCADE + ORM cascade.
        assert (
            await session.execute(
                select(ProviderLicensure).filter(
                    ProviderLicensure.profile_id == profile_id
                )
            )
        ).scalars().first() is None
        assert (
            await session.execute(
                select(ProviderEducation).filter(
                    ProviderEducation.profile_id == profile_id
                )
            )
        ).scalars().first() is None
        assert (
            await session.execute(
                select(ProviderCertification).filter(
                    ProviderCertification.profile_id == profile_id
                )
            )
        ).scalars().first() is None


async def test_delete_profile_returns_403_if_not_owner(
    authenticated_client: AsyncClient,
    db_test_session_manager: async_sessionmaker[AsyncSession],
    logged_in_user: User,
):
    _, other_profile_id = await _seed_other_user_with_profile(db_test_session_manager)

    response = await authenticated_client.delete(
        f"/provider-profiles/{other_profile_id}"
    )
    assert response.status_code == 403


# --- Licensure sub-resource ---------------------------------------------


async def test_create_licensure_happy_path(
    authenticated_client: AsyncClient,
    db_test_session_manager: async_sessionmaker[AsyncSession],
    logged_in_user: User,
):
    profile_id = await _seed_profile_for(
        db_test_session_manager, user_id=logged_in_user.id
    )

    response = await authenticated_client.post(
        f"/provider-profiles/{profile_id}/licensures",
        data=licensure_payload(license_number="L-99999"),
    )

    assert response.status_code == 201
    new_id = uuid.UUID(response.json()["id"])
    assert response.headers["HX-Redirect"] == f"/provider-profiles/{profile_id}/form"

    async with db_test_session_manager() as session:
        persisted = (
            (
                await session.execute(
                    select(ProviderLicensure).filter(ProviderLicensure.id == new_id)
                )
            )
            .scalars()
            .first()
        )
        assert persisted is not None
        assert persisted.license_number == "L-99999"
        assert persisted.profile_id == profile_id


async def test_create_licensure_returns_403_if_not_owner(
    authenticated_client: AsyncClient,
    db_test_session_manager: async_sessionmaker[AsyncSession],
    logged_in_user: User,
):
    _, other_profile_id = await _seed_other_user_with_profile(db_test_session_manager)

    response = await authenticated_client.post(
        f"/provider-profiles/{other_profile_id}/licensures",
        data=licensure_payload(),
    )
    assert response.status_code == 403


async def test_create_licensure_returns_404_for_unknown_profile(
    authenticated_client: AsyncClient,
    logged_in_user: User,
):
    response = await authenticated_client.post(
        f"/provider-profiles/{uuid.uuid4()}/licensures",
        data=licensure_payload(),
    )
    assert response.status_code == 404


async def test_patch_licensure_updates_fields(
    authenticated_client: AsyncClient,
    db_test_session_manager: async_sessionmaker[AsyncSession],
    logged_in_user: User,
):
    profile_id = await _seed_profile_for(
        db_test_session_manager, user_id=logged_in_user.id
    )
    licensure = make_provider_licensure(profile_id=profile_id, license_number="L-1")
    async with db_test_session_manager() as session:
        async with session.begin():
            session.add(licensure)
        await session.refresh(licensure)
        licensure_id = licensure.id

    response = await authenticated_client.patch(
        f"/provider-profiles/{profile_id}/licensures/{licensure_id}",
        data={"license_number": "L-2"},
    )

    assert response.status_code == 200
    assert response.json()["license_number"] == "L-2"


async def test_patch_licensure_returns_404_for_mismatched_profile(
    authenticated_client: AsyncClient,
    db_test_session_manager: async_sessionmaker[AsyncSession],
    logged_in_user: User,
):
    """A licensure_id that belongs to a different profile must 404, not silently
    update across profile boundaries."""
    my_profile_id = await _seed_profile_for(
        db_test_session_manager, user_id=logged_in_user.id
    )
    _, other_profile_id = await _seed_other_user_with_profile(db_test_session_manager)
    other_licensure = make_provider_licensure(profile_id=other_profile_id)
    async with db_test_session_manager() as session:
        async with session.begin():
            session.add(other_licensure)
        await session.refresh(other_licensure)
        other_licensure_id = other_licensure.id

    response = await authenticated_client.patch(
        f"/provider-profiles/{my_profile_id}/licensures/{other_licensure_id}",
        data={"license_number": "stolen"},
    )
    assert response.status_code == 404


async def test_delete_licensure_returns_204(
    authenticated_client: AsyncClient,
    db_test_session_manager: async_sessionmaker[AsyncSession],
    logged_in_user: User,
):
    profile_id = await _seed_profile_for(
        db_test_session_manager, user_id=logged_in_user.id
    )
    licensure = make_provider_licensure(profile_id=profile_id)
    async with db_test_session_manager() as session:
        async with session.begin():
            session.add(licensure)
        await session.refresh(licensure)
        licensure_id = licensure.id

    response = await authenticated_client.delete(
        f"/provider-profiles/{profile_id}/licensures/{licensure_id}"
    )
    assert response.status_code == 204

    async with db_test_session_manager() as session:
        assert (
            await session.execute(
                select(ProviderLicensure).filter(ProviderLicensure.id == licensure_id)
            )
        ).scalars().first() is None


# --- Education / certification happy paths ------------------------------


async def test_create_education_happy_path(
    authenticated_client: AsyncClient,
    db_test_session_manager: async_sessionmaker[AsyncSession],
    logged_in_user: User,
):
    profile_id = await _seed_profile_for(
        db_test_session_manager, user_id=logged_in_user.id
    )

    response = await authenticated_client.post(
        f"/provider-profiles/{profile_id}/educations",
        data=education_payload(institution="Test U"),
    )

    assert response.status_code == 201
    new_id = uuid.UUID(response.json()["id"])

    async with db_test_session_manager() as session:
        persisted = (
            (
                await session.execute(
                    select(ProviderEducation).filter(ProviderEducation.id == new_id)
                )
            )
            .scalars()
            .first()
        )
        assert persisted is not None
        assert persisted.institution == "Test U"


async def test_create_certification_happy_path(
    authenticated_client: AsyncClient,
    db_test_session_manager: async_sessionmaker[AsyncSession],
    logged_in_user: User,
):
    profile_id = await _seed_profile_for(
        db_test_session_manager, user_id=logged_in_user.id
    )

    response = await authenticated_client.post(
        f"/provider-profiles/{profile_id}/certifications",
        data=certification_payload(certifying_body="Test Cert Body"),
    )

    assert response.status_code == 201
    new_id = uuid.UUID(response.json()["id"])

    async with db_test_session_manager() as session:
        persisted = (
            (
                await session.execute(
                    select(ProviderCertification).filter(
                        ProviderCertification.id == new_id
                    )
                )
            )
            .scalars()
            .first()
        )
        assert persisted is not None
        assert persisted.certifying_body == "Test Cert Body"


# --- Create form page (GET /provider-profiles/form) ----------------------


async def test_get_provider_profile_form_renders(
    authenticated_client: AsyncClient,
    logged_in_user: User,
):
    """`GET /provider-profiles/form` renders the create form posting to
    the JSON API."""
    response = await authenticated_client.get("/provider-profiles/form")
    assert response.status_code == 200
    tree = HTMLParser(response.text)
    form = tree.css_first("form")
    assert form is not None
    assert form.attributes.get("hx-post") == "/provider-profiles"
    # Required practice fields are present.
    assert tree.css_first('input[name="practice_name"]') is not None
    assert tree.css_first('input[name="location_city"]') is not None
    assert tree.css_first('input[name="location_zip"]') is not None
    # State select with all 51 entries (50 states + DC) plus a placeholder.
    state_select = tree.css_first('select[name="location_state"]')
    assert state_select is not None
    state_options = state_select.css("option")
    assert len(state_options) == 52  # 51 + placeholder
    # Availability selects with three real options + placeholder.
    in_person = tree.css_first('select[name="in_person_sessions"]')
    virtual = tree.css_first('select[name="virtual_sessions"]')
    assert in_person is not None
    assert virtual is not None
    assert len(in_person.css("option")) == 4
    assert len(virtual.css("option")) == 4


async def test_get_provider_profile_form_unauthenticated_redirects(
    test_client: AsyncClient,
):
    response = await test_client.get(
        "/provider-profiles/form",
        headers={"accept": "text/html"},
        follow_redirects=False,
    )
    assert response.status_code == 302
    assert "/auth/login" in response.headers["location"]
    assert "next=/provider-profiles/form" in response.headers["location"]


async def test_form_route_does_not_shadow_get_by_id(
    authenticated_client: AsyncClient,
    db_test_session_manager: async_sessionmaker[AsyncSession],
    logged_in_user: User,
):
    """A real UUID still hits the read-by-id route — `/form` is matched
    only as the literal segment, not as a UUID path param."""
    profile_id = await _seed_profile_for(
        db_test_session_manager, user_id=logged_in_user.id
    )
    response = await authenticated_client.get(f"/provider-profiles/{profile_id}")
    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/html")
    # The detail page links back to the edit form for the same id, which is
    # only present when the profile was actually loaded.
    assert f"/provider-profiles/{profile_id}/form" in response.text


# --- Edit form page (GET /provider-profiles/{id}/form) -------------------


async def test_owner_can_open_edit_form(
    authenticated_client: AsyncClient,
    db_test_session_manager: async_sessionmaker[AsyncSession],
    logged_in_user: User,
):
    """Owner sees the edit form pre-filled with profile fields and any
    existing credential sub-rows."""
    profile_id = await _seed_profile_for(
        db_test_session_manager,
        user_id=logged_in_user.id,
        practice_name="Acme Counseling",
    )
    licensure = make_provider_licensure(
        profile_id=profile_id, license_type="lcsw", license_number="L-12345"
    )
    async with db_test_session_manager() as session:
        async with session.begin():
            session.add(licensure)

    response = await authenticated_client.get(f"/provider-profiles/{profile_id}/form")
    assert response.status_code == 200
    tree = HTMLParser(response.text)
    practice_input = tree.css_first('input[name="practice_name"]')
    assert practice_input is not None
    assert practice_input.attributes.get("value") == "Acme Counseling"
    practice_form = tree.css_first(f'form[hx-patch="/provider-profiles/{profile_id}"]')
    assert practice_form is not None
    # The seeded licensure should be rendered in the licensures list.
    assert "L-12345" in response.text
    # Sub-section add forms target the right URLs.
    assert (
        tree.css_first(f'form[hx-post="/provider-profiles/{profile_id}/licensures"]')
        is not None
    )
    assert (
        tree.css_first(f'form[hx-post="/provider-profiles/{profile_id}/educations"]')
        is not None
    )
    assert (
        tree.css_first(
            f'form[hx-post="/provider-profiles/{profile_id}/certifications"]'
        )
        is not None
    )


async def test_admin_can_open_edit_form_for_any_profile(
    authenticated_client: AsyncClient,
    db_test_session_manager: async_sessionmaker[AsyncSession],
    logged_in_user: User,
):
    await promote_to_admin(db_test_session_manager, logged_in_user.email)
    _other_user_id, profile_id = await _seed_other_user_with_profile(
        db_test_session_manager
    )
    response = await authenticated_client.get(f"/provider-profiles/{profile_id}/form")
    assert response.status_code == 200


async def test_non_owner_cannot_open_edit_form(
    authenticated_client: AsyncClient,
    db_test_session_manager: async_sessionmaker[AsyncSession],
    logged_in_user: User,
):
    _other_user_id, profile_id = await _seed_other_user_with_profile(
        db_test_session_manager
    )
    response = await authenticated_client.get(f"/provider-profiles/{profile_id}/form")
    assert response.status_code == 403


async def test_edit_form_returns_404_for_unknown_id(
    authenticated_client: AsyncClient,
    logged_in_user: User,
):
    response = await authenticated_client.get(f"/provider-profiles/{uuid.uuid4()}/form")
    assert response.status_code == 404


async def test_edit_form_unauthenticated_redirects(
    test_client: AsyncClient,
):
    profile_id = uuid.uuid4()
    response = await test_client.get(
        f"/provider-profiles/{profile_id}/form",
        headers={"accept": "text/html"},
        follow_redirects=False,
    )
    assert response.status_code == 302
    assert "/auth/login" in response.headers["location"]
