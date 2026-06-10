import uuid

import pytest
from httpx import AsyncClient
from selectolax.parser import HTMLParser
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from src.domain.models import (
    Clinician,
    User,
    Verification,
)
from src.framework.audit.repository import AuditRepository
from tests.helpers import (
    clinician_payload,
    create_test_user,
    make_clinician,
    make_clinician_licensure,
    make_clinician_with_org,
    make_organization_row,
    promote_to_admin,
)

pytestmark = pytest.mark.asyncio


# --- Helpers -------------------------------------------------------------


async def _seed_org(
    db_test_session_manager: async_sessionmaker[AsyncSession],
    *,
    owner_id: uuid.UUID,
    name: str = "Acme Therapy",
) -> uuid.UUID:
    """Insert a root Organization and return its id. Used by tests that
    attach clinicians to orgs via the affiliation sub-resource."""
    org = make_organization_row(owner_id=owner_id, name=name)
    async with db_test_session_manager() as session:
        async with session.begin():
            session.add(org)
    return org.id


async def _seed_clinician_for(
    db_test_session_manager: async_sessionmaker[AsyncSession],
    *,
    user_id: uuid.UUID,
    **overrides,
) -> uuid.UUID:
    """Insert a clinician owned by `user_id` and return its id."""
    clinician = make_clinician_with_org(owner_id=user_id, **overrides)
    async with db_test_session_manager() as session:
        async with session.begin():
            session.add(clinician)
        await session.refresh(clinician)
        return clinician.id


async def _clinician_id_for(
    db_test_session_manager: async_sessionmaker[AsyncSession],
    clinician_id: uuid.UUID,
) -> uuid.UUID:
    """Return the clinician_id — the id passed in IS the clinician_id."""
    return clinician_id


async def _seed_other_user_with_clinician(
    db_test_session_manager: async_sessionmaker[AsyncSession],
) -> tuple[uuid.UUID, uuid.UUID]:
    """Create a second user + their clinician. Returns (user_id, clinician_id)."""
    other = create_test_user(username=f"other-{uuid.uuid4()}")
    async with db_test_session_manager() as session:
        async with session.begin():
            session.add(other)
    clinician_id = await _seed_clinician_for(db_test_session_manager, user_id=other.id)
    return other.id, clinician_id


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


# --- Clinician create ------------------------------------------------------


async def test_create_clinician_happy_path(
    authenticated_client: AsyncClient,
    db_test_session_manager: async_sessionmaker[AsyncSession],
    logged_in_user: User,
):
    """POST /clinicians with the minimal form-encoded body (first / last
    / NPI) returns 201 + id and persists the clinician with no
    affiliation. Audit row is written."""
    response = await authenticated_client.post(
        "/clinicians",
        data=clinician_payload(),
    )

    assert response.status_code == 201, response.text
    new_id = uuid.UUID(response.json()["id"])
    assert response.headers["Location"] == f"/clinicians/{new_id}"
    # Post-create now redirects to the homepage — the NPPES gate runs
    # before this point, so a successful response means the clinician
    # is already verified and there's no half-built row to nudge the
    # user into editing. See `CLINICIAN_ENTITY.create_redirect` in
    # `src/domain/specs/clinician.py`.
    assert response.headers["HX-Redirect"] == "/"

    async with db_test_session_manager() as session:
        result = await session.execute(select(Clinician).filter(Clinician.id == new_id))
        persisted = result.scalars().first()
        assert persisted is not None
        assert persisted.owner_id == logged_in_user.id
        # No affiliation on minimal create — added later via the
        # affiliation sub-resource on the edit page.
        assert persisted.org_id is None
        assert persisted.org is None
        assert persisted.npi == "1234567890"

    rows = await _audit_rows_for(
        db_test_session_manager,
        resource_type="clinician",
        resource_id=new_id,
    )
    assert len(rows) == 1
    assert rows[0].action == "create_clinician"
    assert rows[0].actor_id == logged_in_user.id


async def test_create_clinician_requires_npi(
    authenticated_client: AsyncClient,
    logged_in_user: User,
):
    """NPI is required on create — submitting blank 422s."""
    response = await authenticated_client.post(
        "/clinicians",
        data={"first_name": "Jane", "last_name": "Smith", "npi": ""},
    )
    assert response.status_code == 422


async def test_create_clinician_form_error_render_is_wired(
    authenticated_client: AsyncClient,
    logged_in_user: User,
):
    """Integration smoke for `CLINICIAN_ENTITY.form_error_render`.

    HX-Request POST with an empty `first_name` (a `StrippedText` field
    that rejects blank input) → 422 + HTML fragment with the inline
    error landed on the `first_name` input. Same shape as the
    organizations / programs smokes.
    """
    response = await authenticated_client.post(
        "/clinicians",
        data={"first_name": "", "last_name": "Smith", "npi": "1234567890"},
        headers={"HX-Request": "true"},
    )
    assert response.status_code == 422, response.text
    assert response.headers["content-type"].startswith("text/html")
    body = response.text
    field_at = body.index('name="first_name"')
    window = body[max(0, field_at - 200) : field_at + 200]
    assert 'aria-invalid="true"' in window, window
    assert "<!DOCTYPE" not in body
    assert "<html" not in body
    assert "Bedlam Connect" not in body


async def test_create_clinician_allows_multiple_per_user(
    authenticated_client: AsyncClient,
    db_test_session_manager: async_sessionmaker[AsyncSession],
    logged_in_user: User,
):
    """A user may own multiple clinicians. Two successive POSTs both
    return 201 and persist as distinct rows owned by the same user.

    Both payloads keep the default Jane / Smith name so the autouse
    NPPES mock's verified response (see
    `tests/fixtures.mock_nppes_default_match`) doesn't trip the
    inline-create name-mismatch gate."""
    first = await authenticated_client.post(
        "/clinicians",
        data=clinician_payload(npi="1111111111"),
    )
    assert first.status_code == 201, first.text
    first_id = uuid.UUID(first.json()["id"])

    second = await authenticated_client.post(
        "/clinicians",
        data=clinician_payload(npi="2222222222"),
    )
    assert second.status_code == 201, second.text
    second_id = uuid.UUID(second.json()["id"])

    assert first_id != second_id

    async with db_test_session_manager() as session:
        result = await session.execute(
            select(Clinician).filter(Clinician.owner_id == logged_in_user.id)
        )
        owned = result.scalars().all()
        assert {p.id for p in owned} == {first_id, second_id}


# --- Clinician reads -------------------------------------------------------


async def test_get_clinician_renders_detail_page(
    authenticated_client: AsyncClient,
    db_test_session_manager: async_sessionmaker[AsyncSession],
    logged_in_user: User,
):
    """`GET /clinicians/{id}` renders the read-only HTML detail page
    with practice fields and an Edit link for the owner."""
    clinician_id = await _seed_clinician_for(
        db_test_session_manager, user_id=logged_in_user.id, practice_name="Mine"
    )
    clinician_id = await _clinician_id_for(db_test_session_manager, clinician_id)
    licensure = make_clinician_licensure(
        clinician_id=clinician_id, license_type="lcsw", license_number="L-99999"
    )
    async with db_test_session_manager() as session:
        async with session.begin():
            session.add(licensure)

    response = await authenticated_client.get(f"/clinicians/{clinician_id}")

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/html")
    tree = HTMLParser(response.text)
    # Licensure section renders the seeded row.
    assert "L-99999" in response.text
    # Owner sees an Edit link, no edit forms (read-only) in the page body.
    # (The header dropdown link is not a form — scoping to main is still
    #  the right approach for future-proofing, but the original reason no
    #  longer applies.)
    assert tree.css_first(f'a[href="/clinicians/{clinician_id}/form"]') is not None
    assert tree.css_first("main form") is None
    # Regression for #594 — the practice name lives in the header
    # `<strong>` only. The facts list relabels its row "Organization"
    # so the same string is not repeated under a "Practice name" `<dt>`.
    assert "<dt>Practice name</dt>" not in response.text


async def test_get_clinician_detail_shows_verification_badge(
    authenticated_client: AsyncClient,
    db_test_session_manager: async_sessionmaker[AsyncSession],
    logged_in_user: User,
):
    """`GET /clinicians/{id}` shows the verification badge when a
    verification row exists (#707)."""
    clinician_id = await _seed_clinician_for(
        db_test_session_manager, user_id=logged_in_user.id, practice_name="Verified"
    )
    async with db_test_session_manager() as session:
        async with session.begin():
            session.add(Verification(clinician_id=clinician_id, status="verified"))

    response = await authenticated_client.get(f"/clinicians/{clinician_id}")
    assert response.status_code == 200
    assert "Verified" in response.text
    assert "icon-shield-check" in response.text


async def test_get_clinician_detail_shows_no_badge_without_verification(
    authenticated_client: AsyncClient,
    db_test_session_manager: async_sessionmaker[AsyncSession],
    logged_in_user: User,
):
    """No verification run → no badge rendered (#707)."""
    clinician_id = await _seed_clinician_for(
        db_test_session_manager, user_id=logged_in_user.id, practice_name="Unverified"
    )
    response = await authenticated_client.get(f"/clinicians/{clinician_id}")
    assert response.status_code == 200
    assert "icon-shield-check" not in response.text
    assert "icon-shield-x" not in response.text


async def test_get_clinician_detail_renders_stacked_affiliation_cards(
    authenticated_client: AsyncClient,
    db_test_session_manager: async_sessionmaker[AsyncSession],
    logged_in_user: User,
):
    """`GET /clinicians/{id}` renders one stacked card per ClinicianAffiliation
    after #642 PR 2. Seed a Clinician with two affiliations (the one
    `Clinician.__init__` builds from the create payload + a second one
    appended) and assert both org names render and both
    `[data-testid="affiliation-card"]` blocks appear, in the order
    `clinician.clinician_affiliations` returns (oldest first by `created_at`).
    """
    from src.domain.models import ClinicianAffiliation

    clinician_id = await _seed_clinician_for(
        db_test_session_manager,
        user_id=logged_in_user.id,
        practice_name="Bedlam Health",
        location_city="Brooklyn",
        location_state="NY",
        location_zip="11201",
    )
    # Append a second ClinicianAffiliation at a different Org.
    second_org_id = await _seed_org(
        db_test_session_manager,
        owner_id=logged_in_user.id,
        name="Wellspring",
    )
    clinician_id = await _clinician_id_for(db_test_session_manager, clinician_id)
    async with db_test_session_manager() as session:
        async with session.begin():
            session.add(
                ClinicianAffiliation(
                    clinician_id=clinician_id,
                    org_id=second_org_id,
                    location_city="Queens",
                    location_state="NY",
                    location_zip="11101",
                    in_person_sessions="yes",
                    virtual_sessions="please_contact",
                    accepts_out_of_network=True,
                    in_network_carriers=[],
                    sliding_scale=True,
                    cost="$220/session",
                )
            )

    response = await authenticated_client.get(f"/clinicians/{clinician_id}")

    assert response.status_code == 200
    tree = HTMLParser(response.text)
    cards = tree.css('article[data-testid="affiliation-card"]')
    assert len(cards) == 2, f"expected one card per affiliation, got {len(cards)}"
    # Both org names render — one card per practice.
    assert "Bedlam Health" in response.text
    assert "Wellspring" in response.text
    # Per-affiliation address rendered inside each card (not just at
    # the clinician header) — the location belongs to the affiliation.
    assert "Brooklyn" in response.text
    assert "Queens" in response.text
    # Each card links its heading to the owning Organization.
    org_links_in_cards = []
    for card in cards:
        anchor = card.css_first("header.entity-header a[href^='/organizations/']")
        assert anchor is not None
        org_links_in_cards.append(anchor.attributes.get("href"))
    assert f"/organizations/{second_org_id}" in org_links_in_cards


async def test_get_clinician_hides_edit_link_for_non_owner(
    authenticated_client: AsyncClient,
    db_test_session_manager: async_sessionmaker[AsyncSession],
    logged_in_user: User,
):
    """A non-owner viewing someone else's clinician sees the detail content
    but no Edit link."""
    other = create_test_user(username=f"other-{uuid.uuid4()}")
    async with db_test_session_manager() as session:
        async with session.begin():
            session.add(other)
    clinician_id = await _seed_clinician_for(db_test_session_manager, user_id=other.id)

    response = await authenticated_client.get(f"/clinicians/{clinician_id}")

    assert response.status_code == 200
    tree = HTMLParser(response.text)
    assert tree.css_first(f'a[href="/clinicians/{clinician_id}/form"]') is None


def _delete_clinician_button(tree: HTMLParser, clinician_id: uuid.UUID):
    return tree.css_first(f'button[hx-delete="/clinicians/{clinician_id}"]')


async def test_get_clinician_renders_delete_button_for_owner(
    authenticated_client: AsyncClient,
    db_test_session_manager: async_sessionmaker[AsyncSession],
    logged_in_user: User,
):
    """The owner's detail view carries a Delete button in the toolbar
    actions alongside Edit. The button is an `hx-delete` confirm button
    (per `_shared/actions.html::confirm_delete_button`)."""
    clinician_id = await _seed_clinician_for(
        db_test_session_manager, user_id=logged_in_user.id, practice_name="Mine"
    )

    response = await authenticated_client.get(f"/clinicians/{clinician_id}")
    tree = HTMLParser(response.text)
    button = _delete_clinician_button(tree, clinician_id)
    assert button is not None
    assert "Delete" in button.text()
    assert button.attributes.get("hx-confirm")


async def test_get_clinician_hides_delete_button_for_non_owner(
    authenticated_client: AsyncClient,
    db_test_session_manager: async_sessionmaker[AsyncSession],
    logged_in_user: User,
):
    """A non-owner viewing another user's clinician sees neither the Edit
    link nor the Delete button — both gated on `can_edit`."""
    other = create_test_user(username=f"other-{uuid.uuid4()}")
    async with db_test_session_manager() as session:
        async with session.begin():
            session.add(other)
    clinician_id = await _seed_clinician_for(db_test_session_manager, user_id=other.id)

    response = await authenticated_client.get(f"/clinicians/{clinician_id}")
    tree = HTMLParser(response.text)
    assert _delete_clinician_button(tree, clinician_id) is None


# --- Clinician listing -----------------------------------------------------


async def test_list_clinicians_renders_html(
    superuser_client: AsyncClient,
    db_test_session_manager: async_sessionmaker[AsyncSession],
):
    """`GET /clinicians` renders an HTML page with one entry per
    persisted clinician, regardless of which user owns it.

    After #642 PR 3 the Practice cell no longer wraps in an
    `a[href="/clinicians/{id}"]` anchor — each org name is its own
    link to the owning Organization. The Clinician id still rides on
    the row via `data-row-id` so per-row chrome (and tests) can scope
    to it; the next-PR clinician name column will surface the
    clinician-detail link. The headline assertion here pins the org
    link shape and the row's `data-row-id`."""
    other = create_test_user(username=f"other-{uuid.uuid4()}")
    async with db_test_session_manager() as session:
        async with session.begin():
            session.add(other)
    clinician_id = await _seed_clinician_for(
        db_test_session_manager, user_id=other.id, practice_name="Open House"
    )

    response = await superuser_client.get("/clinicians")

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/html")
    tree = HTMLParser(response.text)
    rows = tree.css("#clinicians-list article.entity-card")
    assert len(rows) == 1
    assert rows[0].attributes.get("data-row-id") == str(clinician_id)
    # Org name renders as a link to the owning Organization.
    practice_cell = rows[0].css_first('div[data-fact="practice"] dd')
    assert practice_cell is not None
    org_anchor = practice_cell.css_first("a[href^='/organizations/']")
    assert org_anchor is not None
    assert org_anchor.text(strip=True) == "Open House"


async def test_list_clinicians_row_shows_all_affiliations(
    authenticated_client: AsyncClient,
    db_test_session_manager: async_sessionmaker[AsyncSession],
    logged_in_user: User,
):
    """After #642 PR 3 each Clinician row reflects **every** affiliation
    it holds, not just the primary. Seed a Clinician with two
    affiliations at different Orgs / cities and assert both org names
    and both city/state pairs render inside the single row's Practice
    and Location cells. The Insurance cell unions in-network carriers
    across affiliations — pin one carrier per side and assert both
    show up."""
    from src.domain.models import ClinicianAffiliation

    clinician_id = await _seed_clinician_for(
        db_test_session_manager,
        user_id=logged_in_user.id,
        practice_name="Bedlam Health",
        location_city="Brooklyn",
        location_state="NY",
        location_zip="11201",
        in_network_carriers=["aetna"],
    )
    second_org_id = await _seed_org(
        db_test_session_manager,
        owner_id=logged_in_user.id,
        name="Wellspring",
    )
    clinician_id = await _clinician_id_for(db_test_session_manager, clinician_id)
    async with db_test_session_manager() as session:
        async with session.begin():
            session.add(
                ClinicianAffiliation(
                    clinician_id=clinician_id,
                    org_id=second_org_id,
                    location_city="Queens",
                    location_state="NY",
                    location_zip="11101",
                    in_person_sessions="yes",
                    virtual_sessions="please_contact",
                    accepts_out_of_network=True,
                    in_network_carriers=["anthem_bcbs"],
                    sliding_scale=False,
                    cost=None,
                )
            )

    response = await authenticated_client.get("/clinicians")

    assert response.status_code == 200
    tree = HTMLParser(response.text)
    rows = tree.css(f'article[data-row-id="{clinician_id}"]')
    assert (
        len(rows) == 1
    ), "expected a single row per Clinician (not one per affiliation)"
    practice_cell = rows[0].css_first('div[data-fact="practice"] dd')
    location_cell = rows[0].css_first('div[data-fact="location"] dd')
    insurance_cell = rows[0].css_first('div[data-fact="insurance"] dd')
    assert practice_cell is not None
    assert location_cell is not None
    assert insurance_cell is not None
    practice_text = practice_cell.text(strip=True)
    location_text = location_cell.text(strip=True)
    insurance_text = insurance_cell.text(strip=True)
    assert "Bedlam Health" in practice_text
    assert "Wellspring" in practice_text
    assert "Brooklyn" in location_text
    assert "Queens" in location_text
    # Each org chip is its own link to the owning Organization.
    org_links = practice_cell.css("a[href^='/organizations/']")
    org_hrefs = {a.attributes.get("href") for a in org_links}
    assert f"/organizations/{second_org_id}" in org_hrefs
    assert len(org_links) == 2, "expected one anchor per affiliation"
    # Insurance cell unions in-network carriers from both affiliations.
    assert "Aetna" in insurance_text
    # `anthem_bcbs` renders as "Anthem / BCBS" via INSURANCE_CARRIER_LABELS.
    assert "Anthem" in insurance_text or "BCBS" in insurance_text
    # The second affiliation accepts OON → roll-up surfaces Out-of-network.
    assert "Out-of-network" in insurance_text


async def test_list_clinicians_row_dedupes_identical_locations(
    authenticated_client: AsyncClient,
    db_test_session_manager: async_sessionmaker[AsyncSession],
    logged_in_user: User,
):
    """Two affiliations in the same city+state collapse to one chip in
    the Location cell — guards against "Brooklyn, NY · Brooklyn, NY"
    when a clinician holds two affiliations at different Orgs in the
    same city. Org chips intentionally don't dedupe (each Org is its
    own link)."""
    from src.domain.models import ClinicianAffiliation

    clinician_id = await _seed_clinician_for(
        db_test_session_manager,
        user_id=logged_in_user.id,
        practice_name="Bedlam Health",
        location_city="Brooklyn",
        location_state="NY",
        location_zip="11201",
    )
    second_org_id = await _seed_org(
        db_test_session_manager,
        owner_id=logged_in_user.id,
        name="Wellspring",
    )
    clinician_id = await _clinician_id_for(db_test_session_manager, clinician_id)
    async with db_test_session_manager() as session:
        async with session.begin():
            session.add(
                ClinicianAffiliation(
                    clinician_id=clinician_id,
                    org_id=second_org_id,
                    location_city="Brooklyn",
                    location_state="NY",
                    location_zip="11201",
                    in_person_sessions="yes",
                    virtual_sessions="please_contact",
                    accepts_out_of_network=False,
                    in_network_carriers=[],
                    sliding_scale=False,
                    cost=None,
                )
            )

    response = await authenticated_client.get("/clinicians")
    assert response.status_code == 200
    tree = HTMLParser(response.text)
    location_cell = tree.css_first(
        f'article[data-row-id="{clinician_id}"] div[data-fact="location"] dd'
    )
    assert location_cell is not None
    location_text = location_cell.text(strip=True)
    # "Brooklyn, NY" appears exactly once after the dedupe.
    assert (
        location_text.count("Brooklyn") == 1
    ), f"expected one Brooklyn chip, got: {location_text!r}"
    # Both org chips still render (org_id dedup is intentionally
    # off — two affiliations at different Orgs both get a link).
    practice_cell = tree.css_first(
        f'article[data-row-id="{clinician_id}"] div[data-fact="practice"] dd'
    )
    assert practice_cell is not None
    assert len(practice_cell.css("a[href^='/organizations/']")) == 2


async def test_list_clinicians_shows_licensure_states(
    superuser_client: AsyncClient,
    db_test_session_manager: async_sessionmaker[AsyncSession],
):
    """Each list row surfaces the clinician's licensure issuing states in
    its "Licensed in" cell so matches against `?issuing_state=` are
    visually obvious — a CT-located clinician holding a CA license shows
    `CA, CT` and the user can see why they appeared in a CA filter
    (#458 follow-up)."""
    other = create_test_user(username=f"other-{uuid.uuid4()}")
    async with db_test_session_manager() as session:
        async with session.begin():
            session.add(other)
    clinician_id = await _seed_clinician_for(
        db_test_session_manager,
        user_id=other.id,
        practice_name="Multi-state Care",
        location_state="CT",
    )
    clinician_id = await _clinician_id_for(db_test_session_manager, clinician_id)
    async with db_test_session_manager() as session:
        async with session.begin():
            session.add(
                make_clinician_licensure(
                    clinician_id=clinician_id,
                    license_type="lcsw",
                    issuing_state="CA",
                )
            )
            session.add(
                make_clinician_licensure(
                    clinician_id=clinician_id,
                    license_type="lpc",
                    issuing_state="CT",
                )
            )

    response = await superuser_client.get("/clinicians")

    assert response.status_code == 200
    tree = HTMLParser(response.text)
    licensed_in_cell = tree.css_first(
        f'article[data-row-id="{clinician_id}"] div[data-fact="licensed_in"] dd'
    )
    assert licensed_in_cell is not None
    assert licensed_in_cell.text(strip=True) == "CA, CT"


async def test_list_owner_me_scopes_to_viewer_owned_clinicians(
    authenticated_client: AsyncClient,
    db_test_session_manager: async_sessionmaker[AsyncSession],
    logged_in_user: User,
):
    """``?owner=me`` filters the directory to clinicians the viewer
    owns. Unlike the default directory listing, the verified-only
    filter is bypassed when ``owner=me`` so the viewer's in-flight,
    unverified row still surfaces — owners need to see what they've
    created before NPPES verification lands."""
    other = create_test_user(username=f"other-{uuid.uuid4()}")
    async with db_test_session_manager() as session:
        async with session.begin():
            session.add(other)
    await _seed_clinician_for(
        db_test_session_manager, user_id=other.id, practice_name="Stranger Clinic"
    )
    own_id = await _seed_clinician_for(
        db_test_session_manager,
        user_id=logged_in_user.id,
        practice_name="My Clinic",
    )

    response = await authenticated_client.get("/clinicians?owner=me")
    assert response.status_code == 200
    tree = HTMLParser(response.text)
    rows = tree.css("#clinicians-list article.entity-card")
    assert len(rows) == 1, "?owner=me must return only the viewer's own clinician"
    assert rows[0].attributes.get("data-row-id") == str(own_id)
    assert "My Clinic" in response.text
    assert "Stranger Clinic" not in response.text


async def test_list_clinicians_renders_create_toolbar_action(
    superuser_client: AsyncClient,
):
    """`/clinicians` (Directory) carries a 'Create clinician' toolbar
    button — matches the orgs/programs/posts list convention so an
    authenticated user always has a discoverable Create entry point.
    The route's auth is `AUTHENTICATED` (creation is not gated to
    owners/admins), so the button shows to every authenticated viewer."""
    response = await superuser_client.get("/clinicians")
    assert response.status_code == 200
    tree = HTMLParser(response.text)
    action = None
    for anchor in tree.css('menu.toolbar-right > li > a[role="button"]'):
        if "Create clinician" in (anchor.text() or ""):
            action = anchor
            break
    assert (
        action is not None
    ), "Create clinician toolbar action is missing on /clinicians"
    assert action.attributes.get("href") == "/clinicians/form"


async def test_list_clinicians_renders_empty_state(
    superuser_client: AsyncClient,
):
    """With no persisted clinicians, the page renders a friendly empty
    message instead of an empty `<table>`. The browse-layout sidebar
    embeds the filter widgets inline on the list page; its header carries
    the link to `/clinicians/search`."""
    response = await superuser_client.get("/clinicians")
    assert response.status_code == 200
    assert "No clinicians found" in response.text
    tree = HTMLParser(response.text)
    assert tree.css_first("#clinicians-list") is None
    # Browse layout: sidebar has the filter widgets inline.
    sidebar = tree.css_first(".filter-sidebar")
    assert sidebar is not None, "Expected .filter-sidebar on /clinicians"
    # Sidebar links to the full search page. (The toolbar never renders
    # a filter link — pinned structurally in
    # framework/templates/test_views.py.)
    sidebar_link = sidebar.css_first("a[href*='/clinicians/search']")
    assert sidebar_link is not None, "Expected sidebar link to /clinicians/search"
    # Multi-choice ChoiceFilters render as search-checkbox-fieldset with
    # single-click checkboxes (#583). No checkbox is preselected when the
    # filter is inactive.
    for filter_name in ("license_type", "issuing_state"):
        boxes = sidebar.css(f'input[type="checkbox"][name="{filter_name}"]')
        assert boxes, f"{filter_name} should render at least one checkbox in sidebar"
        assert not any(
            "checked" in b.attributes for b in boxes
        ), f"{filter_name} should have no preselected checkbox when filter is inactive"
    # The legacy `<select multiple>` listbox should be gone.
    assert sidebar.css_first("select[multiple]") is None


async def test_list_clinicians_filters_by_license_type(
    superuser_client: AsyncClient,
    db_test_session_manager: async_sessionmaker[AsyncSession],
):
    """`?license_type=` keeps only clinicians holding a matching licensure;
    the filter form preselects the active value."""
    user_a = create_test_user(username=f"ua-{uuid.uuid4()}")
    user_b = create_test_user(username=f"ub-{uuid.uuid4()}")
    async with db_test_session_manager() as session:
        async with session.begin():
            session.add(user_a)
            session.add(user_b)
    clinician_a_id = await _seed_clinician_for(
        db_test_session_manager, user_id=user_a.id, practice_name="A clinic"
    )
    clinician_b_id = await _seed_clinician_for(
        db_test_session_manager, user_id=user_b.id, practice_name="B clinic"
    )
    clinician_a = await _clinician_id_for(db_test_session_manager, clinician_a_id)
    clinician_b = await _clinician_id_for(db_test_session_manager, clinician_b_id)

    async with db_test_session_manager() as session:
        async with session.begin():
            session.add(
                make_clinician_licensure(clinician_id=clinician_a, license_type="psyd")
            )
            session.add(
                make_clinician_licensure(clinician_id=clinician_b, license_type="lcsw")
            )

    response = await superuser_client.get("/clinicians?license_type=psyd")

    assert response.status_code == 200
    tree = HTMLParser(response.text)
    rows = tree.css("#clinicians-list article.entity-card")
    assert len(rows) == 1
    # After #642 PR 3 the row scopes by `data-row-id` (the Clinician id);
    # the row's Practice cell anchors out to Orgs, not to the clinician.
    assert tree.css_first(f'article[data-row-id="{clinician_a_id}"]') is not None
    assert tree.css_first(f'article[data-row-id="{clinician_b_id}"]') is None
    # The browse-layout sidebar preselects the active filter value.
    sidebar = tree.css_first(".filter-sidebar")
    assert sidebar is not None
    checked = sidebar.css_first(
        'input[type="checkbox"][name="license_type"][value="psyd"]'
    )
    assert (
        checked is not None
    ), "Active license_type filter should be preselected in sidebar"
    assert "checked" in checked.attributes
    # The search page re-renders the form with the active value preselected.
    # Multi-choice filters now render as checkboxes (#583), so the
    # active value surfaces as a `checked` `<input type="checkbox">`.
    search = await superuser_client.get("/clinicians/search?license_type=psyd")
    assert search.status_code == 200
    checked = HTMLParser(search.text).css_first(
        'input[type="checkbox"][name="license_type"][value="psyd"]'
    )
    assert checked is not None
    assert "checked" in checked.attributes


async def test_list_clinicians_treats_empty_filter_values_as_absent(
    superuser_client: AsyncClient,
    db_test_session_manager: async_sessionmaker[AsyncSession],
):
    """Pressing "Apply" on the filter form with no selection submits
    `?license_type=&issuing_state=` — empty values, not absent. The
    `StripEmptyQueryParamsMiddleware` removes those pairs at request
    entry so the route's declared defaults fire and every clinician
    renders, the same as visiting `/clinicians` with no query string.
    Without the middleware the empty strings reach the repo's filter
    and zero rows match (the bug this regression test guards)."""
    other = create_test_user(username=f"empty-filter-{uuid.uuid4()}")
    async with db_test_session_manager() as session:
        async with session.begin():
            session.add(other)
    await _seed_clinician_for(
        db_test_session_manager, user_id=other.id, practice_name="Filter Test"
    )

    response = await superuser_client.get("/clinicians?license_type=&issuing_state=")

    assert response.status_code == 200
    tree = HTMLParser(response.text)
    rows = tree.css("#clinicians-list article.entity-card")
    assert len(rows) == 1, "Empty filter values should not exclude rows"


# --- Chrome: toolbar + form affordances --------------------------------


async def test_clinicians_list_has_browse_layout_with_filter_sidebar(
    superuser_client: AsyncClient,
):
    """`/clinicians` list uses the framework browse layout: an inline
    `.filter-sidebar` on the left (driven by the spec's declared filters)
    and a `.browse-results` column on the right. The Create action lives
    in the toolbar; the sidebar carries the filter controls and a link to
    the full `/clinicians/search` page."""
    response = await superuser_client.get("/clinicians")
    assert response.status_code == 200
    tree = HTMLParser(response.text)
    # Browse layout
    assert tree.css_first(".browse-layout") is not None, "Missing .browse-layout"
    sidebar = tree.css_first(".filter-sidebar")
    assert sidebar is not None, "Missing .filter-sidebar"
    # Sidebar has filter controls (license_type is a multi-choice filter)
    fieldsets = sidebar.css("fieldset.search-checkbox-fieldset")
    assert fieldsets, "No filter fieldsets in .filter-sidebar"
    # Toolbar carries the Create action; the framework guarantees no
    # filter link in the toolbar (see test_views.py).
    action_menu = tree.css_first("menu.toolbar-right")
    assert action_menu is not None
    assert "Create clinician" in action_menu.text()


async def test_clinician_detail_favorite_toggle_lives_in_toolbar(
    authenticated_client: AsyncClient,
    db_test_session_manager: async_sessionmaker[AsyncSession],
    logged_in_user: User,
):
    """The favorite/unfavorite button is a primary resource action and
    renders inside the toolbar, not in `<footer>` or any `.entity-card`
    body. Pins the chrome rule in `src/framework/templates/README.md`."""
    other = create_test_user(username=f"other-{uuid.uuid4()}")
    async with db_test_session_manager() as session:
        async with session.begin():
            session.add(other)
    clinician_id = await _seed_clinician_for(db_test_session_manager, user_id=other.id)

    response = await authenticated_client.get(f"/clinicians/{clinician_id}")
    assert response.status_code == 200
    tree = HTMLParser(response.text)
    favorite_selector = f'button[hx-post="/users/me/favorites/{clinician_id}"]'
    assert tree.css_first(f".toolbar {favorite_selector}") is not None
    # The favorite button is not duplicated inside any detail-card body.
    assert tree.css_first(f".entity-card {favorite_selector}") is None


async def test_clinician_form_new_renders_form_actions_cluster(
    authenticated_client: AsyncClient,
    logged_in_user: User,
):
    """`GET /clinicians/form` renders the standardized Save/Cancel
    cluster (the `form_actions` macro). Cancel on the create page
    points at the collection so a user can bail without leaving the
    app's resource scope — matches the edit page's bottom Cancel."""
    response = await authenticated_client.get("/clinicians/form")
    assert response.status_code == 200
    tree = HTMLParser(response.text)
    actions = tree.css_first(".form-actions")
    assert actions is not None
    cancel = tree.css_first('.form-actions a[href="/clinicians"][role="button"]')
    assert cancel is not None
    assert cancel.text(strip=True) == "Cancel"


async def test_clinician_form_edit_renders_cancel(
    authenticated_client: AsyncClient,
    db_test_session_manager: async_sessionmaker[AsyncSession],
    logged_in_user: User,
):
    """`GET /clinicians/{id}/form` keeps a bottom "Cancel" link pointing
    at the detail page (a deliberate "abandon this edit" affordance —
    see `src/framework/templates/README.md`)."""
    clinician_id = await _seed_clinician_for(
        db_test_session_manager,
        user_id=logged_in_user.id,
        practice_name="Edit Me",
    )
    response = await authenticated_client.get(f"/clinicians/{clinician_id}/form")
    assert response.status_code == 200
    tree = HTMLParser(response.text)
    cancel = tree.css_first(f'a[href="/clinicians/{clinician_id}"][role="button"]')
    assert cancel is not None
    assert cancel.text(strip=True) == "Cancel"


# --- Clinician update ------------------------------------------------------


async def test_patch_clinician_updates_fields(
    authenticated_client: AsyncClient,
    db_test_session_manager: async_sessionmaker[AsyncSession],
    logged_in_user: User,
):
    """``PATCH /clinicians/{id}`` rewrites the person-level fields
    (`first_name`, `last_name`, `npi`). Practice posture (location,
    availability, insurance, cost, org) lives on `ClinicianAffiliation`
    and is patched via its own endpoint after #1308."""
    clinician_id = await _seed_clinician_for(
        db_test_session_manager, user_id=logged_in_user.id, practice_name="Old Name"
    )

    response = await authenticated_client.patch(
        f"/clinicians/{clinician_id}",
        data={"first_name": "Janet"},
    )

    assert response.status_code == 200
    assert response.json()["first_name"] == "Janet"
    assert response.headers["HX-Redirect"] == f"/clinicians/{clinician_id}/form"

    async with db_test_session_manager() as session:
        refreshed = (
            (
                await session.execute(
                    select(Clinician).filter(Clinician.id == clinician_id)
                )
            )
            .scalars()
            .first()
        )
        assert refreshed.first_name == "Janet"


async def test_patch_clinician_returns_403_if_not_owner(
    authenticated_client: AsyncClient,
    db_test_session_manager: async_sessionmaker[AsyncSession],
    logged_in_user: User,
):
    _, other_clinician_id = await _seed_other_user_with_clinician(
        db_test_session_manager
    )

    response = await authenticated_client.patch(
        f"/clinicians/{other_clinician_id}",
        data={"first_name": "Hijacked"},
    )
    assert response.status_code == 403


async def test_patch_clinician_rejects_per_affiliation_fields(
    authenticated_client: AsyncClient,
    db_test_session_manager: async_sessionmaker[AsyncSession],
    logged_in_user: User,
):
    """`ClinicianUpdate` is extra="forbid"; per-affiliation fields
    (`org_id`, location, sessions, insurance, cost) are no longer
    accepted on `PATCH /clinicians/{id}` — they belong on the
    affiliation's own PATCH. A stale client that sends them gets a
    422, not a silent drop."""
    clinician_id = await _seed_clinician_for(
        db_test_session_manager, user_id=logged_in_user.id, practice_name="Mine"
    )

    response = await authenticated_client.patch(
        f"/clinicians/{clinician_id}",
        data={"first_name": "Janet", "in_person_sessions": "yes"},
    )
    assert response.status_code == 422


# --- Clinician delete ------------------------------------------------------


async def test_delete_clinician_returns_204(
    authenticated_client: AsyncClient,
    db_test_session_manager: async_sessionmaker[AsyncSession],
    logged_in_user: User,
):
    """Deleting a Clinician via DELETE /clinicians/{id} returns 204 and
    removes the Clinician row (credentials cascade-delete with the Clinician
    since credential FKs use ondelete='CASCADE')."""
    clinician_id = await _seed_clinician_for(
        db_test_session_manager, user_id=logged_in_user.id
    )

    response = await authenticated_client.delete(f"/clinicians/{clinician_id}")
    assert response.status_code == 204

    async with db_test_session_manager() as session:
        assert (
            await session.execute(
                select(Clinician).filter(Clinician.id == clinician_id)
            )
        ).scalars().first() is None


# --- Licensure sub-resource ---------------------------------------------


async def test_patch_licensure_updates_fields(
    authenticated_client: AsyncClient,
    db_test_session_manager: async_sessionmaker[AsyncSession],
    logged_in_user: User,
):
    clinician_id = await _seed_clinician_for(
        db_test_session_manager, user_id=logged_in_user.id
    )
    clinician_id = await _clinician_id_for(db_test_session_manager, clinician_id)
    licensure = make_clinician_licensure(
        clinician_id=clinician_id, license_number="L-1"
    )
    async with db_test_session_manager() as session:
        async with session.begin():
            session.add(licensure)
        await session.refresh(licensure)
        licensure_id = licensure.id

    response = await authenticated_client.patch(
        f"/clinicians/{clinician_id}/licensures/{licensure_id}",
        data={"license_number": "L-2"},
    )

    assert response.status_code == 200
    assert response.json()["license_number"] == "L-2"


async def test_patch_licensure_returns_404_for_mismatched_clinician(
    authenticated_client: AsyncClient,
    db_test_session_manager: async_sessionmaker[AsyncSession],
    logged_in_user: User,
):
    """A licensure_id that belongs to a different clinician must 404, not silently
    update across clinician boundaries."""
    my_clinician_id = await _seed_clinician_for(
        db_test_session_manager, user_id=logged_in_user.id
    )
    _, other_clinician_id = await _seed_other_user_with_clinician(
        db_test_session_manager
    )
    other_clinician_id = await _clinician_id_for(
        db_test_session_manager, other_clinician_id
    )
    other_licensure = make_clinician_licensure(clinician_id=other_clinician_id)
    async with db_test_session_manager() as session:
        async with session.begin():
            session.add(other_licensure)
        await session.refresh(other_licensure)
        other_licensure_id = other_licensure.id

    response = await authenticated_client.patch(
        f"/clinicians/{my_clinician_id}/licensures/{other_licensure_id}",
        data={"license_number": "stolen"},
    )
    assert response.status_code == 404


# --- ClinicianAffiliation sub-resource CRUD (#642 PR 1) --------------------------


async def test_post_affiliation_creates_additional_row(
    authenticated_client: AsyncClient,
    db_test_session_manager: async_sessionmaker[AsyncSession],
    logged_in_user: User,
):
    """`POST /clinicians/{id}/clinician_affiliations` adds a new ClinicianAffiliation to
    the Clinician. The framework's generic create handler succeeds for
    every row past the first one (which `Clinician.__init__` already
    built from the wire payload)."""
    from src.domain.models import ClinicianAffiliation

    clinician_id = await _seed_clinician_for(
        db_test_session_manager, user_id=logged_in_user.id
    )
    second_org_id = await _seed_org(
        db_test_session_manager,
        owner_id=logged_in_user.id,
        name="Second Practice",
    )

    response = await authenticated_client.post(
        f"/clinicians/{clinician_id}/clinician_affiliations",
        data={
            "org_id": str(second_org_id),
            "location_city": "Queens",
            "location_state": "NY",
            "location_zip": "11101",
            "in_person_sessions": "yes",
            "virtual_sessions": "please_contact",
            "accepts_out_of_network": "true",
            "sliding_scale": "true",
            "cost": "$220/session",
        },
    )

    assert response.status_code in (200, 201), response.text
    async with db_test_session_manager() as session:
        rows = (
            (
                await session.execute(
                    select(ClinicianAffiliation).where(
                        ClinicianAffiliation.clinician_id == clinician_id
                    )
                )
            )
            .scalars()
            .all()
        )
    assert len(rows) == 2
    extra = next(a for a in rows if a.location_city == "Queens")
    assert extra.org_id == second_org_id
    assert extra.clinician_id == rows[0].clinician_id
    assert extra.sliding_scale is True
    assert extra.cost == "$220/session"


async def test_patch_affiliation_updates_fields(
    authenticated_client: AsyncClient,
    db_test_session_manager: async_sessionmaker[AsyncSession],
    logged_in_user: User,
):
    """`PATCH /clinicians/{id}/clinician_affiliations/{aff_id}` partially updates
    the row. Pinned because the framework's update handler resolves the
    affiliation through the new `ClinicianAffiliationRepository`."""
    clinician_id = await _seed_clinician_for(
        db_test_session_manager, user_id=logged_in_user.id
    )
    # The Clinician's `__init__` already built one ClinicianAffiliation — patch it.
    async with db_test_session_manager() as session:
        from src.domain.models import ClinicianAffiliation

        aff_id = (
            await session.execute(
                select(ClinicianAffiliation.id).where(
                    ClinicianAffiliation.clinician_id == clinician_id
                )
            )
        ).scalar_one()

    response = await authenticated_client.patch(
        f"/clinicians/{clinician_id}/clinician_affiliations/{aff_id}",
        data={"sliding_scale": "true", "cost": "$999/session"},
    )

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["sliding_scale"] is True
    assert body["cost"] == "$999/session"


async def test_delete_affiliation_removes_row(
    authenticated_client: AsyncClient,
    db_test_session_manager: async_sessionmaker[AsyncSession],
    logged_in_user: User,
):
    """`DELETE /clinicians/{id}/clinician_affiliations/{aff_id}` removes the row.
    The Clinician can be left with zero Affiliations — readers fall
    back to `None` via the property proxies. (PR 3's Clinician-row
    rollup is the user-facing fix for empty-affiliations Clinicians.)"""
    from src.domain.models import ClinicianAffiliation

    clinician_id = await _seed_clinician_for(
        db_test_session_manager, user_id=logged_in_user.id
    )
    async with db_test_session_manager() as session:
        aff_id = (
            await session.execute(
                select(ClinicianAffiliation.id).where(
                    ClinicianAffiliation.clinician_id == clinician_id
                )
            )
        ).scalar_one()

    response = await authenticated_client.delete(
        f"/clinicians/{clinician_id}/clinician_affiliations/{aff_id}"
    )

    assert response.status_code in (200, 204)
    async with db_test_session_manager() as session:
        remaining = (
            (
                await session.execute(
                    select(ClinicianAffiliation).where(
                        ClinicianAffiliation.clinician_id == clinician_id
                    )
                )
            )
            .scalars()
            .all()
        )
    assert remaining == []


async def test_delete_affiliation_returns_404_for_mismatched_clinician(
    authenticated_client: AsyncClient,
    db_test_session_manager: async_sessionmaker[AsyncSession],
    logged_in_user: User,
):
    """An affiliation_id that belongs to a different clinician must 404 —
    the framework's URL-vs-row consistency check (configured via
    `child_parent_match_attr="clinician_id"` on `CLINICIAN_AFFILIATION_ENTITY`)
    blocks cross-clinician deletes."""
    from src.domain.models import ClinicianAffiliation

    my_clinician_id = await _seed_clinician_for(
        db_test_session_manager, user_id=logged_in_user.id
    )
    _, other_clinician_id = await _seed_other_user_with_clinician(
        db_test_session_manager
    )
    async with db_test_session_manager() as session:
        other_aff_id = (
            await session.execute(
                select(ClinicianAffiliation.id).where(
                    ClinicianAffiliation.clinician_id == other_clinician_id
                )
            )
        ).scalar_one()

    response = await authenticated_client.delete(
        f"/clinicians/{my_clinician_id}/clinician_affiliations/{other_aff_id}"
    )
    assert response.status_code == 404


async def test_owner_edit_form_renders_affiliations_section(
    authenticated_client: AsyncClient,
    db_test_session_manager: async_sessionmaker[AsyncSession],
    logged_in_user: User,
):
    """The clinician edit page surfaces every `ClinicianAffiliation` row
    in a dedicated section. The DB model calls them affiliations
    (clinician × org); the UI surfaces them as "Practices" because
    that's what they are to the user — including the solo case where
    `org_id` is NULL. Inline add + per-row delete are present."""
    clinician_id = await _seed_clinician_for(
        db_test_session_manager, user_id=logged_in_user.id
    )

    response = await authenticated_client.get(f"/clinicians/{clinician_id}/form")
    assert response.status_code == 200
    tree = HTMLParser(response.text)

    headings = [h.text(strip=True) for h in tree.css("h2")]
    assert "Practices" in headings

    # The inline add form posts to /clinicians/{id}/clinician_affiliations.
    add_form = tree.css_first(
        f'form[hx-post="/clinicians/{clinician_id}/clinician_affiliations"]'
    )
    assert add_form is not None
    assert add_form.css_first('select[name="org_id"]') is not None
    assert add_form.css_first('input[name="location_city"]') is not None

    # The existing primary affiliation renders as a row with a
    # delete button pointing at its own URL.
    from src.domain.models import ClinicianAffiliation

    async with db_test_session_manager() as session:
        aff_id = (
            await session.execute(
                select(ClinicianAffiliation.id).where(
                    ClinicianAffiliation.clinician_id == clinician_id
                )
            )
        ).scalar_one()
    delete_button = tree.css_first(
        f'button[hx-delete="/clinicians/{clinician_id}/clinician_affiliations/{aff_id}"]'
    )
    assert delete_button is not None


# --- Education / certification happy paths ------------------------------


# --- Create form page (GET /clinicians/form) ----------------------


async def test_get_clinician_form_renders_minimal_fields(
    authenticated_client: AsyncClient,
    logged_in_user: User,
):
    """`GET /clinicians/form` renders the minimal create form (first
    name + last name + NPI) posting to the JSON API. Affiliation,
    location, availability, and insurance fields are deliberately
    absent — they live on the edit page once the row exists."""
    response = await authenticated_client.get("/clinicians/form")
    assert response.status_code == 200
    tree = HTMLParser(response.text)
    form = tree.css_first("main form")
    assert form is not None
    assert form.attributes.get("hx-post") == "/clinicians"
    # The three required inputs are present.
    assert tree.css_first('input[name="first_name"]') is not None
    assert tree.css_first('input[name="last_name"]') is not None
    npi = tree.css_first('input[name="npi"]')
    assert npi is not None
    assert npi.attributes.get("pattern") == r"\d{10}"
    assert npi.attributes.get("maxlength") == "10"
    # Fields that moved to the edit flow are NOT on the create form.
    for absent in (
        "org_id",
        "solo_practice",
        "location_city",
        "location_state",
        "location_zip",
        "in_person_sessions",
        "virtual_sessions",
        "accepts_out_of_network",
        "sliding_scale",
        "in_network_carriers",
        "cost",
    ):
        assert (
            tree.css_first(f'[name="{absent}"]') is None
        ), f"{absent} should not appear on the minimal create form"


# --- Edit form page (GET /clinicians/{id}/form) -------------------


async def test_owner_can_open_edit_form(
    authenticated_client: AsyncClient,
    db_test_session_manager: async_sessionmaker[AsyncSession],
    logged_in_user: User,
):
    """Owner sees the edit form pre-filled with the person-level
    Clinician fields (first/last/npi) plus the credential and
    affiliation sub-rows. Practice posture moved off this form in
    #1308 — `org_id` / location / sessions / insurance now live on
    each affiliation's own row."""
    clinician_id = await _seed_clinician_for(
        db_test_session_manager,
        user_id=logged_in_user.id,
        practice_name="Acme Counseling",
    )
    clinician_id = await _clinician_id_for(db_test_session_manager, clinician_id)
    licensure = make_clinician_licensure(
        clinician_id=clinician_id, license_type="lcsw", license_number="L-12345"
    )
    async with db_test_session_manager() as session:
        async with session.begin():
            session.add(licensure)

    response = await authenticated_client.get(f"/clinicians/{clinician_id}/form")
    assert response.status_code == 200
    tree = HTMLParser(response.text)
    practice_form = tree.css_first(f'form[hx-patch="/clinicians/{clinician_id}"]')
    assert practice_form is not None
    # Person-level inputs are present on the clinician PATCH form.
    assert practice_form.css_first('input[name="first_name"]') is not None
    assert practice_form.css_first('input[name="last_name"]') is not None
    assert practice_form.css_first('input[name="npi"]') is not None
    # Per-affiliation posture inputs (`org_id`, `location_city`,
    # `in_person_sessions`, etc.) are NOT on the clinician form — they
    # belong to each affiliation's own row below.
    assert practice_form.css_first('select[name="org_id"]') is None
    assert practice_form.css_first('input[name="location_city"]') is None
    assert practice_form.css_first('select[name="in_person_sessions"]') is None
    # The seeded licensure should be rendered in the licensures list.
    assert "L-12345" in response.text
    # Sub-section add forms target the right URLs.
    assert (
        tree.css_first(f'form[hx-post="/clinicians/{clinician_id}/licensures"]')
        is not None
    )
    assert (
        tree.css_first(f'form[hx-post="/clinicians/{clinician_id}/educations"]')
        is not None
    )
    assert (
        tree.css_first(f'form[hx-post="/clinicians/{clinician_id}/certifications"]')
        is not None
    )


async def test_owner_edit_form_renders_credentials_as_rows(
    authenticated_client: AsyncClient,
    db_test_session_manager: async_sessionmaker[AsyncSession],
    logged_in_user: User,
):
    """Credential lists render as `.credential-row` blocks (not raw
    `<li>`s) — bold type label, muted meta line, owner-side Delete
    button. The owning `<section>` already provides the framing; rows
    stay flat to avoid the card-on-card look."""
    clinician_id = await _seed_clinician_for(
        db_test_session_manager,
        user_id=logged_in_user.id,
        practice_name="Acme Counseling",
    )
    clinician_id = await _clinician_id_for(db_test_session_manager, clinician_id)
    licensure = make_clinician_licensure(
        clinician_id=clinician_id,
        license_type="lcsw",
        license_number="L-12345",
        issuing_state="CA",
    )
    async with db_test_session_manager() as session:
        async with session.begin():
            session.add(licensure)

    response = await authenticated_client.get(f"/clinicians/{clinician_id}/form")
    tree = HTMLParser(response.text)
    # After #642 PR 1 the affiliations section also renders rows via
    # `.credential-list .credential-row` (it reuses the same partial);
    # locate the licensure row by its hx-delete URL, not by section
    # ordering.
    delete = tree.css_first(
        f'button[hx-delete="/clinicians/{clinician_id}/licensures/{licensure.id}"]'
    )
    assert delete is not None
    assert delete.text(strip=True) == "Delete"
    row = delete.parent  # `.credential-row`
    while row is not None and "credential-row" not in (
        row.attributes.get("class") or ""
    ):
        row = row.parent
    assert row is not None
    assert (
        row.css_first("strong").text(strip=True)
        == "Licensed Clinical Social Worker (LCSW)"
    )
    meta = row.css_first(".credential-row-text small")
    assert meta is not None
    assert "L-12345" in meta.text()
    assert "CA" in meta.text()


async def test_owner_edit_form_renders_solo_affiliation_without_crashing(
    authenticated_client: AsyncClient,
    db_test_session_manager: async_sessionmaker[AsyncSession],
    logged_in_user: User,
):
    """Solo clinician path: a `ClinicianAffiliation` with `org_id` NULL
    (the shape #1311 introduced for solo practitioners) renders without
    dereferencing `aff.org.name`. The row label falls back to
    "Solo practice" and the section heading reads "Practices" — the UI
    drops the "affiliation" word in the solo case, matching how the
    user thinks about it."""
    from src.domain.models import Clinician, ClinicianAffiliation

    clinician = make_clinician(
        owner_id=logged_in_user.id,
        first_name="Janet",
        last_name="Solo",
    )
    clinician.clinician_affiliations = [ClinicianAffiliation(clinician=clinician)]
    async with db_test_session_manager() as session:
        async with session.begin():
            session.add(clinician)
        await session.refresh(clinician)
    clinician_id = clinician.id

    response = await authenticated_client.get(f"/clinicians/{clinician_id}/form")
    assert response.status_code == 200
    tree = HTMLParser(response.text)
    # Section heading is "Practices", not "Affiliations".
    headings = [h.text(strip=True) for h in tree.css("h2")]
    assert "Practices" in headings
    assert "Affiliations" not in headings
    # The solo affiliation row's label falls back to "Solo practice".
    async with db_test_session_manager() as session:
        loaded = await session.get(Clinician, clinician_id)
        aff_id = loaded.clinician_affiliations[0].id
    delete = tree.css_first(
        f'button[hx-delete="/clinicians/{clinician_id}/clinician_affiliations/{aff_id}"]'
    )
    assert delete is not None
    row = delete.parent
    while row is not None and "credential-row" not in (
        row.attributes.get("class") or ""
    ):
        row = row.parent
    assert row is not None
    assert row.css_first("strong").text(strip=True) == "Solo practice"


async def test_admin_can_open_edit_form_for_any_clinician(
    authenticated_client: AsyncClient,
    db_test_session_manager: async_sessionmaker[AsyncSession],
    logged_in_user: User,
):
    await promote_to_admin(db_test_session_manager, logged_in_user.email)
    _other_user_id, clinician_id = await _seed_other_user_with_clinician(
        db_test_session_manager
    )
    response = await authenticated_client.get(f"/clinicians/{clinician_id}/form")
    assert response.status_code == 200


async def test_non_owner_cannot_open_edit_form(
    authenticated_client: AsyncClient,
    db_test_session_manager: async_sessionmaker[AsyncSession],
    logged_in_user: User,
):
    _other_user_id, clinician_id = await _seed_other_user_with_clinician(
        db_test_session_manager
    )
    response = await authenticated_client.get(f"/clinicians/{clinician_id}/form")
    assert response.status_code == 403


# --- Pagination ---------------------------------------------------------


async def test_list_renders_no_pagination_footer_for_single_page(
    authenticated_client: AsyncClient,
    db_test_session_manager: async_sessionmaker[AsyncSession],
    logged_in_user: User,
):
    """A result that fits on a single page renders no Prev/Next chrome.
    Pins the `pagination` macro's single-page suppression rule."""
    await _seed_clinician_for(db_test_session_manager, user_id=logged_in_user.id)
    response = await authenticated_client.get("/clinicians")
    assert response.status_code == 200
    tree = HTMLParser(response.text)
    assert tree.css_first('nav[aria-label="Pagination"]') is None


async def test_list_paginates_when_over_per_page(
    authenticated_client: AsyncClient,
    db_test_session_manager: async_sessionmaker[AsyncSession],
    logged_in_user: User,
    monkeypatch,
):
    """Page 1 shows up to `DEFAULT_PAGE_SIZE` rows and a Next link;
    page 2 shows the rest and a Prev link. Monkeypatches the page
    size down to keep the seed cheap — the framework's `handle_list`
    reads the constant from `mounts.list_.DEFAULT_PAGE_SIZE`, so that's
    where the patch lives."""
    monkeypatch.setattr("src.framework.dispatch.mounts.list_.DEFAULT_PAGE_SIZE", 2)
    for _ in range(3):
        await _seed_clinician_for(db_test_session_manager, user_id=logged_in_user.id)

    response = await authenticated_client.get("/clinicians")
    assert response.status_code == 200
    tree = HTMLParser(response.text)
    rows = tree.css("#clinicians-list article.entity-card")
    assert len(rows) == 2
    pagination = tree.css_first('nav[aria-label="Pagination"]')
    assert pagination is not None
    assert pagination.css_first('a[rel="next"]') is not None
    assert pagination.css_first('a[rel="prev"]') is None

    response2 = await authenticated_client.get("/clinicians?page=2")
    assert response2.status_code == 200
    tree2 = HTMLParser(response2.text)
    rows2 = tree2.css("#clinicians-list article.entity-card")
    assert len(rows2) == 1
    pagination2 = tree2.css_first('nav[aria-label="Pagination"]')
    assert pagination2 is not None
    assert pagination2.css_first('a[rel="prev"]') is not None
    assert pagination2.css_first('a[rel="next"]') is None


async def test_list_pagination_preserves_query_params(
    authenticated_client: AsyncClient,
    db_test_session_manager: async_sessionmaker[AsyncSession],
    logged_in_user: User,
    monkeypatch,
):
    """A page-link from `/clinicians?foo=bar&page=1` round-trips
    `foo=bar` — the Next link must preserve query state so the user
    doesn't lose their filter when navigating. `base_query()` is
    filter-agnostic: anything in the URL except `page=` carries over,
    so any extra param works as the test signal."""
    monkeypatch.setattr("src.framework.dispatch.mounts.list_.DEFAULT_PAGE_SIZE", 1)
    for _ in range(2):
        await _seed_clinician_for(db_test_session_manager, user_id=logged_in_user.id)

    response = await authenticated_client.get("/clinicians?ignored_param=foo")
    assert response.status_code == 200
    tree = HTMLParser(response.text)
    next_link = tree.css_first('nav[aria-label="Pagination"] a[rel="next"]')
    assert next_link is not None
    href = next_link.attributes.get("href", "")
    assert "ignored_param=foo" in href
    assert "page=2" in href


# --- Ownership-list subresources (openings / referrals) ------------------


async def _add_post_for(
    db_test_session_manager: async_sessionmaker[AsyncSession],
    *,
    owner_id: uuid.UUID,
    detail,
    detail_relationship: str,
):
    """Persist a Post + per-kind detail row owned by `owner_id`."""
    from src.domain.models import Post
    from src.framework.persistence.base_repository import BaseRepository

    kind_map = {
        "opening_detail": "clinician_opening",
        "referral_detail": "referral",
    }
    async with db_test_session_manager() as session:
        async with session.begin():
            post = Post(kind=kind_map[detail_relationship], owner_id=owner_id)
            repo = BaseRepository(session)
            await repo.create_polymorphic(
                post, detail, detail_relationship=detail_relationship
            )


async def test_get_clinician_openings_empty_state(
    authenticated_client: AsyncClient,
    db_test_session_manager: async_sessionmaker[AsyncSession],
    logged_in_user: User,
):
    """`GET /clinicians/{id}/openings` renders the empty state when the
    clinician has posted no openings."""
    clinician_id = await _seed_clinician_for(
        db_test_session_manager, user_id=logged_in_user.id
    )
    response = await authenticated_client.get(f"/clinicians/{clinician_id}/openings")
    assert response.status_code == 200
    tree = HTMLParser(response.text)
    assert tree.css_first("#clinician-openings-list") is None
    empty = tree.css_first(".post-feed-empty")
    assert empty is not None
    assert "No openings posted" in empty.text()


async def test_get_clinician_openings_lists_only_this_clinician(
    authenticated_client: AsyncClient,
    db_test_session_manager: async_sessionmaker[AsyncSession],
    logged_in_user: User,
):
    """The list scopes to the path clinician: a second clinician's
    opening does not bleed into the first clinician's list."""
    from tests.helpers import make_opening_detail

    mine = await _seed_clinician_for(db_test_session_manager, user_id=logged_in_user.id)
    other = await _seed_clinician_for(
        db_test_session_manager, user_id=logged_in_user.id
    )
    await _add_post_for(
        db_test_session_manager,
        owner_id=logged_in_user.id,
        detail=make_opening_detail(clinician_id=mine),
        detail_relationship="opening_detail",
    )
    await _add_post_for(
        db_test_session_manager,
        owner_id=logged_in_user.id,
        detail=make_opening_detail(clinician_id=other),
        detail_relationship="opening_detail",
    )

    response = await authenticated_client.get(f"/clinicians/{mine}/openings")
    assert response.status_code == 200
    tree = HTMLParser(response.text)
    assert len(tree.css("#clinician-openings-list .post-feed-row")) == 1


async def test_get_clinician_referrals_lists_attributed(
    authenticated_client: AsyncClient,
    db_test_session_manager: async_sessionmaker[AsyncSession],
    logged_in_user: User,
):
    """`GET /clinicians/{id}/referrals` lists referrals attributed to the
    clinician via `referring_clinician_id`."""
    from tests.helpers import make_referral_detail

    clinician_id = await _seed_clinician_for(
        db_test_session_manager, user_id=logged_in_user.id
    )
    await _add_post_for(
        db_test_session_manager,
        owner_id=logged_in_user.id,
        detail=make_referral_detail(referring_clinician_id=clinician_id),
        detail_relationship="referral_detail",
    )

    response = await authenticated_client.get(f"/clinicians/{clinician_id}/referrals")
    assert response.status_code == 200
    tree = HTMLParser(response.text)
    assert len(tree.css("#clinician-referrals-list .post-feed-row")) == 1


async def test_get_clinician_openings_404_for_missing_clinician(
    authenticated_client: AsyncClient,
    logged_in_user: User,
):
    """A nonexistent clinician id 404s rather than rendering an empty list."""
    response = await authenticated_client.get(f"/clinicians/{uuid.uuid4()}/openings")
    assert response.status_code == 404


async def test_patch_clinician_npi_change_reruns_verification(
    authenticated_client: AsyncClient,
    db_test_session_manager: async_sessionmaker[AsyncSession],
    logged_in_user: User,
):
    """PATCH /clinicians/{id} changing `npi` re-runs NPPES verification via
    the `after_update` hook — the canonical replacement for the retired
    `POST /profile/clinician/{id}/identity` retry (#1166). `nppes_lookup` is
    patched so no real HTTP fires; LEIE points at the fixture CSV."""
    import os
    from pathlib import Path
    from unittest.mock import AsyncMock, patch

    from src.domain.logic.verifications import oig as oig_module
    from src.domain.logic.verifications.nppes import NppesResult

    leie_fixture = (
        Path(__file__).parent.parent
        / "logic"
        / "verifications"
        / "test_data"
        / "leie_sample.csv"
    )
    oig_module._reset_cache_for_tests()
    old_path = os.environ.get("LEIE_CSV_PATH")
    os.environ["LEIE_CSV_PATH"] = str(leie_fixture)
    try:
        clinician = make_clinician_with_org(
            owner_id=logged_in_user.id,
            npi="1111111111",
            npi_match_status="mismatch",
            first_name="Jane",
            last_name="Smith",
        )
        clinician.clinician_verified = False
        async with db_test_session_manager() as session:
            async with session.begin():
                session.add(clinician)
        clinician_id = clinician.id

        nppes_match = NppesResult(
            found=True, first_name="Jane", last_name="Smith", raw={}
        )
        with patch(
            "src.domain.logic.verifications.handlers.nppes_lookup",
            new=AsyncMock(return_value=nppes_match),
        ):
            response = await authenticated_client.patch(
                f"/clinicians/{clinician_id}",
                data={"npi": "9999999999"},
            )
        assert response.status_code == 200

        async with db_test_session_manager() as session:
            loaded = await session.get(Clinician, clinician_id)
            assert loaded.npi == "9999999999"
            # Re-verification ran and resolved the new NPI as a match.
            assert loaded.npi_match_status == "matched"
            rows = (
                (
                    await session.execute(
                        select(Verification).filter(
                            Verification.clinician_id == clinician_id
                        )
                    )
                )
                .scalars()
                .all()
            )
            assert any(r.event_type == "npi_resolved" for r in rows)
    finally:
        if old_path is None:
            os.environ.pop("LEIE_CSV_PATH", None)
        else:
            os.environ["LEIE_CSV_PATH"] = old_path
        oig_module._reset_cache_for_tests()
