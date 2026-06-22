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
    make_clinician_certification,
    make_clinician_education,
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
    """`GET /clinicians/{id}` is a dispatching picker (#1336): person-
    level identity in the H1 + subtitle band, plus four cards deep-
    linking to the sub-resource list pages. The owner toolbar carries
    Edit / Delete; no inline sub-resource data appears on this page
    (it lives on `/clinicians/{id}/<sub>` after the restyle)."""
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
    # Inline sub-resource data is NOT on the detail page anymore — it
    # lives on each sub-resource's own list page.
    assert "L-99999" not in response.text
    # Toolbar carries the owner's Edit link.
    assert tree.css_first(f'a[href="/clinicians/{clinician_id}/form"]') is not None
    assert tree.css_first("main form") is None
    # Four picker cards, deep-linking to the four sub-resource list
    # pages mounted in #1335. The picker macro renders one
    # `article.picker-option` per option (no `<header>` band after
    # #1330) with the link inside `<h2><a>`.
    cards = tree.css("main article.picker-option")
    assert len(cards) == 4
    hrefs = {card.css_first("h2 a").attributes.get("href") for card in cards}
    assert hrefs == {
        f"/clinicians/{clinician_id}/clinician_affiliations",
        f"/clinicians/{clinician_id}/licensures",
        f"/clinicians/{clinician_id}/educations",
        f"/clinicians/{clinician_id}/certifications",
    }
    headings = {card.css_first("h2 a").text(strip=True) for card in cards}
    assert headings == {"Practices", "Licensures", "Education", "Certifications"}


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


# --- Consolidated read summary (I5 / #1523) -------------------------------


async def test_get_clinician_detail_surfaces_consolidated_summary(
    authenticated_client: AsyncClient,
    db_test_session_manager: async_sessionmaker[AsyncSession],
    logged_in_user: User,
):
    """The detail page leads with a consolidated read summary (mock §6):
    a non-redacted viewer sees the clinician's licenses and affiliation
    surfaced inline (drawn from the sub-resources) so the page reads
    like a profile, without having to click into each sub-resource list.
    The summary is keyed by stable `data-fact` selectors per the
    `sections.html::fact` contract."""
    clinician_id = await _seed_clinician_for(
        db_test_session_manager,
        user_id=logged_in_user.id,
        practice_name="Acme Therapy",
    )
    licensure = make_clinician_licensure(
        clinician_id=clinician_id, license_type="lcsw", issuing_state="IL"
    )
    async with db_test_session_manager() as session:
        async with session.begin():
            session.add(licensure)

    response = await authenticated_client.get(f"/clinicians/{clinician_id}")

    assert response.status_code == 200
    tree = HTMLParser(response.text)
    licenses = tree.css_first('[data-fact="summary_licenses"]')
    assert licenses is not None, "consolidated summary must surface Licenses"
    assert "Licensed Clinical Social Worker (LCSW)" in licenses.text()
    assert "(IL)" in licenses.text()
    affiliation = tree.css_first('[data-fact="summary_affiliation"]')
    assert affiliation is not None, "consolidated summary must surface Affiliation"
    assert "Acme Therapy" in affiliation.text()
    # Additive: the management picker is still reachable below the summary.
    assert len(tree.css("main article.picker-option")) == 4


async def test_get_clinician_detail_summary_redacts_location_for_non_network_viewer(
    authenticated_client: AsyncClient,
    db_test_session_manager: async_sessionmaker[AsyncSession],
    logged_in_user: User,
):
    """Redaction is preserved (mock §6): a non-owner viewer who isn't a
    verified provider sees the locked name and no identifying Location /
    Insurance rows in the summary, matching the `_clinician_card.html`
    redaction contract. The non-identifying credential rows (Licenses)
    still render."""
    other = create_test_user(username=f"other-{uuid.uuid4()}")
    async with db_test_session_manager() as session:
        async with session.begin():
            session.add(other)
    clinician_id = await _seed_clinician_for(
        db_test_session_manager, user_id=other.id, practice_name="Acme Therapy"
    )
    licensure = make_clinician_licensure(clinician_id=clinician_id)
    async with db_test_session_manager() as session:
        async with session.begin():
            session.add(licensure)

    response = await authenticated_client.get(f"/clinicians/{clinician_id}")

    assert response.status_code == 200
    tree = HTMLParser(response.text)
    # Identifying practice facts are withheld from a non-network visitor.
    assert tree.css_first('[data-fact="summary_location"]') is None
    assert tree.css_first('[data-fact="summary_insurance"]') is None
    # Non-identifying credentials still surface.
    assert tree.css_first('[data-fact="summary_licenses"]') is not None


# --- Owner-vs-visitor toolbar action (I5 / #1523) -------------------------


async def test_get_clinician_owner_sees_edit_not_message(
    authenticated_client: AsyncClient,
    db_test_session_manager: async_sessionmaker[AsyncSession],
    logged_in_user: User,
):
    """The owner's toolbar carries the management Edit action and no
    visitor Message affordance — the owner manages, they don't message
    themselves (mock §6)."""
    clinician_id = await _seed_clinician_for(
        db_test_session_manager, user_id=logged_in_user.id
    )

    response = await authenticated_client.get(f"/clinicians/{clinician_id}")
    tree = HTMLParser(response.text)
    assert tree.css_first(f'a[href="/clinicians/{clinician_id}/form"]') is not None
    toolbar = tree.css_first("menu.toolbar-right")
    assert toolbar is not None
    assert "Message" not in toolbar.text()


async def test_get_clinician_non_owner_non_provider_sees_locked_message(
    authenticated_client: AsyncClient,
    db_test_session_manager: async_sessionmaker[AsyncSession],
    logged_in_user: User,
):
    """A non-owner viewer who isn't a verified provider sees the Message
    affordance in its locked state — reusing the same `_locked` gating
    the post detail footer applies. Clicking opens the verify-to-message
    popover rather than messaging directly."""
    other = create_test_user(username=f"other-{uuid.uuid4()}")
    async with db_test_session_manager() as session:
        async with session.begin():
            session.add(other)
    clinician_id = await _seed_clinician_for(db_test_session_manager, user_id=other.id)

    response = await authenticated_client.get(f"/clinicians/{clinician_id}")
    tree = HTMLParser(response.text)
    toolbar = tree.css_first("menu.toolbar-right")
    assert toolbar is not None
    assert "Message" in toolbar.text()
    locked = toolbar.css_first("[data-locked-cta]")
    assert locked is not None, "non-provider Message must be the locked affordance"
    assert locked.attributes.get("data-locked-cta") == "network_unverified"
    # No Edit link for a non-owner.
    assert tree.css_first(f'a[href="/clinicians/{clinician_id}/form"]') is None


async def test_get_clinician_non_owner_provider_sees_live_message(
    authenticated_client: AsyncClient,
    db_test_session_manager: async_sessionmaker[AsyncSession],
    logged_in_user: User,
):
    """A non-owner viewer who clears `can_act_as_provider` (a verified
    clinician, but not an admin) sees a live Message action linking to
    the target clinician's owner — where contact happens. No locked
    state, no Edit link (they aren't the owner). We make the viewer a
    verified provider by giving them their *own* verified clinician
    (`make_clinician_with_org` defaults `clinician_verified=True`), which
    flips `can_act_as_provider` without granting edit rights on the
    clinician they're viewing — exactly the verified-visitor case."""
    # Viewer's own verified clinician → `can_act_as_provider` True.
    await _seed_clinician_for(
        db_test_session_manager, user_id=logged_in_user.id, practice_name="My Practice"
    )
    other = create_test_user(username=f"other-{uuid.uuid4()}")
    async with db_test_session_manager() as session:
        async with session.begin():
            session.add(other)
    clinician_id = await _seed_clinician_for(db_test_session_manager, user_id=other.id)

    response = await authenticated_client.get(f"/clinicians/{clinician_id}")
    tree = HTMLParser(response.text)
    toolbar = tree.css_first("menu.toolbar-right")
    assert toolbar is not None
    message_link = toolbar.css_first(f'a[href="/users/{other.id}"]')
    assert message_link is not None, "verified visitor must get a live Message link"
    assert "Message" in message_link.text()
    assert message_link.css_first("[data-locked-cta]") is None
    assert tree.css_first(f'a[href="/clinicians/{clinician_id}/form"]') is None


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
    rows = tree.css("#clinicians-list article")
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
                    accepts_out_of_network=True,
                    in_network_carriers=["anthem_bcbs"],
                    sliding_scale=False,
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
                    accepts_out_of_network=False,
                    in_network_carriers=[],
                    sliding_scale=False,
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
    rows = tree.css("#clinicians-list article")
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
    embeds the filter widgets inline on the list page; the results column's
    `.filter-summary` header carries the link to `/clinicians/search`."""
    response = await superuser_client.get("/clinicians")
    assert response.status_code == 200
    assert "No clinicians found" in response.text
    tree = HTMLParser(response.text)
    assert tree.css_first("#clinicians-list") is None
    # Browse layout: sidebar has the filter widgets inline.
    sidebar = tree.css_first(".filter-sidebar")
    assert sidebar is not None, "Expected .filter-sidebar on /clinicians"
    # The full-search link lives in the results column's filter-summary
    # header (not the sidebar, not the toolbar — pinned structurally in
    # framework/templates/test_views.py), and is present even on the empty
    # state.
    summary_link = tree.css_first(
        ".browse-results .filter-summary a[href*='/clinicians/search']"
    )
    assert (
        summary_link is not None
    ), "Expected filter-summary link to /clinicians/search"
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
    rows = tree.css("#clinicians-list article")
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
    rows = tree.css("#clinicians-list article")
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
    renders inside the toolbar, not in `<footer>` or anywhere else on
    the page. Pins the chrome rule in `src/framework/templates/README.md`."""
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
    # The favorite button is not duplicated anywhere else on the page.
    assert len(tree.css(favorite_selector)) == 1


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


async def test_get_licensure_new_form_renders(
    authenticated_client: AsyncClient,
    db_test_session_manager: async_sessionmaker[AsyncSession],
    logged_in_user: User,
):
    """`GET /clinicians/{id}/licensures/form` is the canonical create-form
    page (mounted via parent-aware `mount_form` after the canonical-pattern
    conversion). The rendered form POSTs to the collection URL."""
    clinician_id = await _seed_clinician_for(
        db_test_session_manager, user_id=logged_in_user.id
    )
    clinician_id = await _clinician_id_for(db_test_session_manager, clinician_id)

    response = await authenticated_client.get(
        f"/clinicians/{clinician_id}/licensures/form"
    )
    assert response.status_code == 200
    tree = HTMLParser(response.text)
    add_form = tree.css_first(f'form[hx-post="/clinicians/{clinician_id}/licensures"]')
    assert add_form is not None
    assert add_form.css_first('select[name="license_type"]') is not None


async def test_get_licensure_edit_form_renders_with_prefilled_values(
    authenticated_client: AsyncClient,
    db_test_session_manager: async_sessionmaker[AsyncSession],
    logged_in_user: User,
):
    """`GET /clinicians/{id}/licensures/{lic_id}/form` is the canonical
    edit-form page; renders with the licensure's current values prefilled,
    and the Delete + Attest active affordances live in the actions
    cluster (strict canonical — no per-row buttons on the list page)."""
    clinician_id = await _seed_clinician_for(
        db_test_session_manager, user_id=logged_in_user.id
    )
    clinician_id = await _clinician_id_for(db_test_session_manager, clinician_id)
    licensure = make_clinician_licensure(
        clinician_id=clinician_id,
        license_type="lcsw",
        license_number="L-2025",
        issuing_state="CA",
    )
    async with db_test_session_manager() as session:
        async with session.begin():
            session.add(licensure)
        await session.refresh(licensure)
    lic_id = licensure.id

    response = await authenticated_client.get(
        f"/clinicians/{clinician_id}/licensures/{lic_id}/form"
    )
    assert response.status_code == 200
    tree = HTMLParser(response.text)
    # Form patches to the resource detail URL.
    edit_form = tree.css_first(
        f'form[hx-patch="/clinicians/{clinician_id}/licensures/{lic_id}"]'
    )
    assert edit_form is not None
    # License number prefilled.
    number_input = edit_form.css_first('input[name="license_number"]')
    assert number_input is not None
    assert number_input.attributes.get("value") == "L-2025"
    # Delete sits in the actions cluster.
    delete = tree.css_first(
        f'button[hx-delete="/clinicians/{clinician_id}/licensures/{lic_id}"]'
    )
    assert delete is not None
    # Attest active lives here when the row hasn't been attested yet.
    attest = tree.css_first(
        f'button[hx-put="/clinicians/{clinician_id}/licensures/{lic_id}/attestation"]'
    )
    assert attest is not None


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
            "accepts_out_of_network": "true",
            "sliding_scale": "true",
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


async def test_post_solo_affiliation_with_no_org(
    authenticated_client: AsyncClient,
    db_test_session_manager: async_sessionmaker[AsyncSession],
    logged_in_user: User,
):
    """`POST /clinicians/{id}/clinician_affiliations` with no `org_id`
    creates a solo practice row (`org_id` NULL, sessions / location
    NULL). The user picks the "(Solo practice — no organization)"
    option in the inline add-practice form; the form posts an empty
    `org_id` value, which `WirePayload` coerces to None."""
    from src.domain.models import ClinicianAffiliation

    clinician_id = await _seed_clinician_for(
        db_test_session_manager, user_id=logged_in_user.id
    )

    response = await authenticated_client.post(
        f"/clinicians/{clinician_id}/clinician_affiliations",
        # Mirrors what the inline add-practice form posts when the user
        # picks "(Solo practice)" and leaves the optional fields blank.
        data={
            "org_id": "",
            "location_city": "",
            "location_state": "",
            "accepts_out_of_network": "true",
            "sliding_scale": "false",
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
    solo = next(a for a in rows if a.org_id is None)
    assert solo.location_city is None


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
        data={"sliding_scale": "true", "website": "https://drsmith.example.com"},
    )

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["sliding_scale"] is True
    assert body["website"] == "https://drsmith.example.com"


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


async def test_clinician_edit_form_has_no_inline_subresource_ui(
    authenticated_client: AsyncClient,
    db_test_session_manager: async_sessionmaker[AsyncSession],
    logged_in_user: User,
):
    """After #1336 the clinician edit form is **person-level only** —
    the inline lists for affiliations / licensures / educations /
    certifications moved onto each sub-resource's own list page
    (`/clinicians/{id}/<sub>`). The picker on the detail page is what
    deep-links into them."""
    clinician_id = await _seed_clinician_for(
        db_test_session_manager, user_id=logged_in_user.id
    )

    response = await authenticated_client.get(f"/clinicians/{clinician_id}/form")
    assert response.status_code == 200
    tree = HTMLParser(response.text)

    # The sub-resource POST/DELETE forms that used to live inline are gone.
    # (The form's own `<h2>` section headings — emitted by `form_section`
    # since the fieldset→section port — are person-level field groups, not
    # subresource UI, so we pin the absence of the actual CRUD affordances
    # below rather than "no headings at all".)
    for collection in (
        "clinician_affiliations",
        "licensures",
        "educations",
        "certifications",
    ):
        assert (
            tree.css_first(f'form[hx-post="/clinicians/{clinician_id}/{collection}"]')
            is None
        )
        # No delete buttons for sub-resource rows on this page either.
        assert (
            tree.css_first(
                f'button[hx-delete^="/clinicians/{clinician_id}/{collection}/"]'
            )
            is None
        )


# --- Education / certification happy paths ------------------------------


async def test_get_education_new_form_renders(
    authenticated_client: AsyncClient,
    db_test_session_manager: async_sessionmaker[AsyncSession],
    logged_in_user: User,
):
    """Canonical create-form page for educations (PR 3 conversion)."""
    clinician_id = await _seed_clinician_for(
        db_test_session_manager, user_id=logged_in_user.id
    )
    clinician_id = await _clinician_id_for(db_test_session_manager, clinician_id)

    response = await authenticated_client.get(
        f"/clinicians/{clinician_id}/educations/form"
    )
    assert response.status_code == 200
    tree = HTMLParser(response.text)
    add_form = tree.css_first(f'form[hx-post="/clinicians/{clinician_id}/educations"]')
    assert add_form is not None
    assert add_form.css_first('select[name="education_type"]') is not None


async def test_get_education_edit_form_renders_with_prefilled_values(
    authenticated_client: AsyncClient,
    db_test_session_manager: async_sessionmaker[AsyncSession],
    logged_in_user: User,
):
    """Edit form prefills the institution + delete sits in actions."""
    clinician_id = await _seed_clinician_for(
        db_test_session_manager, user_id=logged_in_user.id
    )
    clinician_id = await _clinician_id_for(db_test_session_manager, clinician_id)
    education = make_clinician_education(
        clinician_id=clinician_id, institution="Test University"
    )
    async with db_test_session_manager() as session:
        async with session.begin():
            session.add(education)
        await session.refresh(education)
    edu_id = education.id

    response = await authenticated_client.get(
        f"/clinicians/{clinician_id}/educations/{edu_id}/form"
    )
    assert response.status_code == 200
    tree = HTMLParser(response.text)
    edit_form = tree.css_first(
        f'form[hx-patch="/clinicians/{clinician_id}/educations/{edu_id}"]'
    )
    assert edit_form is not None
    institution = edit_form.css_first('input[name="institution"]')
    assert institution is not None
    assert institution.attributes.get("value") == "Test University"
    delete = tree.css_first(
        f'button[hx-delete="/clinicians/{clinician_id}/educations/{edu_id}"]'
    )
    assert delete is not None


async def test_get_certification_new_form_renders(
    authenticated_client: AsyncClient,
    db_test_session_manager: async_sessionmaker[AsyncSession],
    logged_in_user: User,
):
    """Canonical create-form page for certifications (PR 3 conversion)."""
    clinician_id = await _seed_clinician_for(
        db_test_session_manager, user_id=logged_in_user.id
    )
    clinician_id = await _clinician_id_for(db_test_session_manager, clinician_id)

    response = await authenticated_client.get(
        f"/clinicians/{clinician_id}/certifications/form"
    )
    assert response.status_code == 200
    tree = HTMLParser(response.text)
    add_form = tree.css_first(
        f'form[hx-post="/clinicians/{clinician_id}/certifications"]'
    )
    assert add_form is not None
    assert add_form.css_first('select[name="certification_type"]') is not None


async def test_get_certification_edit_form_renders_with_prefilled_values(
    authenticated_client: AsyncClient,
    db_test_session_manager: async_sessionmaker[AsyncSession],
    logged_in_user: User,
):
    """Edit form prefills the certifying_body + delete sits in actions."""
    clinician_id = await _seed_clinician_for(
        db_test_session_manager, user_id=logged_in_user.id
    )
    clinician_id = await _clinician_id_for(db_test_session_manager, clinician_id)
    certification = make_clinician_certification(
        clinician_id=clinician_id, certifying_body="Test Board"
    )
    async with db_test_session_manager() as session:
        async with session.begin():
            session.add(certification)
        await session.refresh(certification)
    cert_id = certification.id

    response = await authenticated_client.get(
        f"/clinicians/{clinician_id}/certifications/{cert_id}/form"
    )
    assert response.status_code == 200
    tree = HTMLParser(response.text)
    edit_form = tree.css_first(
        f'form[hx-patch="/clinicians/{clinician_id}/certifications/{cert_id}"]'
    )
    assert edit_form is not None
    body = edit_form.css_first('input[name="certifying_body"]')
    assert body is not None
    assert body.attributes.get("value") == "Test Board"
    delete = tree.css_first(
        f'button[hx-delete="/clinicians/{clinician_id}/certifications/{cert_id}"]'
    )
    assert delete is not None


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
    Clinician fields (first/last/npi) only. Practice posture, licensures,
    educations, and certifications each live on their own list page
    after #1336."""
    clinician_id = await _seed_clinician_for(
        db_test_session_manager,
        user_id=logged_in_user.id,
        practice_name="Acme Counseling",
    )

    response = await authenticated_client.get(f"/clinicians/{clinician_id}/form")
    assert response.status_code == 200
    tree = HTMLParser(response.text)
    practice_form = tree.css_first(f'form[hx-patch="/clinicians/{clinician_id}"]')
    assert practice_form is not None
    # Person-level inputs are present on the clinician PATCH form.
    assert practice_form.css_first('input[name="first_name"]') is not None
    assert practice_form.css_first('input[name="last_name"]') is not None
    assert practice_form.css_first('input[name="npi"]') is not None
    # Per-affiliation posture inputs are not on the clinician form.
    assert practice_form.css_first('select[name="org_id"]') is None
    assert practice_form.css_first('input[name="location_city"]') is None
    assert practice_form.css_first('select[name="in_person_sessions"]') is None


# Placeholder docstring kept to anchor the section comment that
# follows. The actual solo-affiliation rendering is now pinned at the
# affiliations list page level (`test_get_clinician_affiliations_*`).
async def test_clinician_edit_form_renders_for_solo_clinician(
    authenticated_client: AsyncClient,
    db_test_session_manager: async_sessionmaker[AsyncSession],
    logged_in_user: User,
):
    """Solo clinician path: a `ClinicianAffiliation` with `org_id` NULL
    (the shape #1311 introduced for solo practitioners) doesn't break
    the edit form, because the form is now person-level only and never
    derefs affiliation fields."""
    from src.domain.models import ClinicianAffiliation

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
    # Person-level form renders for the solo (org_id NULL) shape.
    assert tree.css_first(f'form[hx-patch="/clinicians/{clinician_id}"]') is not None


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


# --- Person-level matching-dimension fields (#1358 PR-a/c/f) ---------------


async def test_clinician_edit_form_renders_matching_dimension_fields(
    authenticated_client: AsyncClient,
    db_test_session_manager: async_sessionmaker[AsyncSession],
    logged_in_user: User,
):
    """`GET /clinicians/{id}/form` renders the person-level matching-
    dimension fields the schema-reconciliation work added (#1358 PR-a/c/f):

    * `affirming_identities` — multi-checkbox sourced from
      `AFFIRMING_IDENTITIES` (clinician's self-claim, symmetric to the
      Referral form's request-side mirror).
    * `languages` — multi-checkbox sourced from `LANGUAGES`. Person-level
      (#1358 PR-f); the model column server-defaults to ``["en"]`` so a
      freshly-created clinician renders with English pre-checked.
    * `clinical_niches` — free-form comma-separated tag input,
      mirroring the splitter pattern PR #1403 introduced on the
      Referral form.
    """
    clinician_id = await _seed_clinician_for(
        db_test_session_manager, user_id=logged_in_user.id
    )

    response = await authenticated_client.get(f"/clinicians/{clinician_id}/form")
    assert response.status_code == 200
    tree = HTMLParser(response.text)

    # affirming_identities — multi_select_field renders a
    # `<div role="group" id="affirming_identities">` wrapper around
    # per-value checkboxes.
    ai_group = tree.css_first('div[role="group"]#affirming_identities')
    assert ai_group is not None, "no affirming_identities checkbox group"
    assert (
        tree.css_first(
            'input[type="checkbox"][name="affirming_identities"][value="lgbtq"]'
        )
        is not None
    ), "affirming_identities is missing the `lgbtq` option"

    # languages — same multi_select_field shape as affirming_identities.
    # English ("en") is in `LANGUAGES`; the model server-default
    # of `["en"]` makes it pre-checked on a fresh row.
    lang_group = tree.css_first('div[role="group"]#languages')
    assert lang_group is not None, "no languages checkbox group"
    en_box = tree.css_first('input[type="checkbox"][name="languages"][value="en"]')
    assert en_box is not None, "languages is missing the `en` option"
    assert (
        "checked" in en_box.attributes
    ), "languages[en] should be pre-checked on a freshly-created clinician"

    # clinical_niches — text input under the staging name
    # `_clinical_niches_input`; the inline splitter script rewrites it
    # to repeated hidden `clinical_niches` inputs on submit.
    niches_input = tree.css_first('input[name="_clinical_niches_input"]')
    assert (
        niches_input is not None
    ), "no _clinical_niches_input text field (clinical_niches tag input)"
    assert (
        tree.css_first("#clinical-niches-hidden") is not None
    ), "no #clinical-niches-hidden container for the niche splitter"


async def test_clinician_edit_form_prefills_matching_dimension_fields(
    authenticated_client: AsyncClient,
    db_test_session_manager: async_sessionmaker[AsyncSession],
    logged_in_user: User,
):
    """The edit form pre-checks any stored affirming-identity / language
    tokens and pre-populates the clinical-niches text input with a
    comma-joined view of the persisted tags. Asserts the round-trip-
    display path matches what the form would have accepted on submit."""
    clinician_id = await _seed_clinician_for(
        db_test_session_manager,
        user_id=logged_in_user.id,
        affirming_identities=["lgbtq", "trans"],
        languages=["en", "es", "zh"],
        clinical_niches=["DGBI", "ADHD in women"],
    )

    response = await authenticated_client.get(f"/clinicians/{clinician_id}/form")
    assert response.status_code == 200
    tree = HTMLParser(response.text)

    # Both selected affirming-identity checkboxes are pre-checked.
    for tok in ("lgbtq", "trans"):
        box = tree.css_first(
            f'input[type="checkbox"][name="affirming_identities"][value="{tok}"]'
        )
        assert box is not None, f"affirming_identities option {tok!r} missing"
        assert (
            "checked" in box.attributes
        ), f"affirming_identities[{tok}] should be pre-checked on edit"

    # All three stored languages are pre-checked.
    for tok in ("en", "es", "zh"):
        box = tree.css_first(f'input[type="checkbox"][name="languages"][value="{tok}"]')
        assert box is not None, f"languages option {tok!r} missing"
        assert (
            "checked" in box.attributes
        ), f"languages[{tok}] should be pre-checked on edit"

    # The clinical_niches text input is pre-populated with a comma-
    # joined view of the persisted tags. Order matches storage order.
    niches_input = tree.css_first('input[name="_clinical_niches_input"]')
    assert niches_input is not None
    assert (
        niches_input.attributes.get("value") == "DGBI, ADHD in women"
    ), niches_input.attributes.get("value")


async def test_patch_clinician_persists_matching_dimensions_round_trip(
    authenticated_client: AsyncClient,
    db_test_session_manager: async_sessionmaker[AsyncSession],
    logged_in_user: User,
):
    """End-to-end: PATCH `/clinicians/{id}` with affirming_identities,
    languages, and clinical_niches persists the values, and the detail
    page (`GET /clinicians/{id}`) renders the row labels back. Pins the
    wire shape the splitter script synthesizes (repeated `clinical_niches`
    pairs), the repeated-key shape multi-checkbox fields use for
    `affirming_identities` / `languages`, and the partial-update
    semantics of `ClinicianUpdate`."""
    clinician_id = await _seed_clinician_for(
        db_test_session_manager, user_id=logged_in_user.id
    )

    # Use form-urlencoded content with repeated keys to mirror the
    # wire shape the splitter script synthesizes on submit. Passing
    # `data=[(k, v), ...]` to httpx's AsyncClient hits the sync-only
    # multipart encoder; building the body explicitly avoids that.
    from urllib.parse import urlencode

    patch = await authenticated_client.patch(
        f"/clinicians/{clinician_id}",
        content=urlencode(
            [
                ("affirming_identities", "lgbtq"),
                ("affirming_identities", "neurodiversity"),
                ("languages", "en"),
                ("languages", "es"),
                ("clinical_niches", "DGBI"),
                ("clinical_niches", "ADHD in women"),
            ]
        ),
        headers={"Content-Type": "application/x-www-form-urlencoded"},
    )
    assert patch.status_code in (200, 204), patch.text

    async with db_test_session_manager() as session:
        row = await session.get(Clinician, clinician_id)
        assert list(row.affirming_identities) == ["lgbtq", "neurodiversity"]
        assert list(row.languages) == ["en", "es"]
        assert list(row.clinical_niches) == ["DGBI", "ADHD in women"]

    detail = await authenticated_client.get(f"/clinicians/{clinician_id}")
    assert detail.status_code == 200
    body = detail.text
    # Section labels (the row's `<dt>` text) — label-lookup wins, raw
    # tokens shouldn't appear.
    assert "Affirming identities" in body
    assert "Languages" in body
    assert "Clinical niches" in body
    # Free-form niches render verbatim.
    assert "DGBI" in body
    assert "ADHD in women" in body


async def test_clinician_detail_renders_matching_dimension_rows(
    authenticated_client: AsyncClient,
    db_test_session_manager: async_sessionmaker[AsyncSession],
    logged_in_user: User,
):
    """The clinician detail page (`/clinicians/{id}`) surfaces each
    person-level matching-dimension row when the row has values for it.
    `languages` (#1358 PR-f) is now editable via the form (the round-
    trip is asserted in
    :func:`test_patch_clinician_persists_matching_dimensions_round_trip`)
    but the detail page renders it as a labeled row identically to the
    affirming-identities row. Display labels (`AFFIRMING_IDENTITY_LABELS`
    / `LANGUAGE_LABELS`) are looked up; free-form `clinical_niches`
    renders verbatim."""
    clinician_id = await _seed_clinician_for(
        db_test_session_manager,
        user_id=logged_in_user.id,
        affirming_identities=["lgbtq"],
        clinical_niches=["DGBI"],
        languages=["en", "es"],
    )

    response = await authenticated_client.get(f"/clinicians/{clinician_id}")
    assert response.status_code == 200
    tree = HTMLParser(response.text)

    # Each row is identified by a `data-fact="<key>"` wrapper.
    assert tree.css_first('[data-fact="affirming_identities"]') is not None
    assert tree.css_first('[data-fact="languages"]') is not None
    assert tree.css_first('[data-fact="clinical_niches"]') is not None
    body = response.text
    assert "Affirming identities" in body
    assert "Languages" in body
    assert "Clinical niches" in body
    assert "DGBI" in body


async def test_clinician_detail_hides_matching_dimension_rows_when_empty(
    authenticated_client: AsyncClient,
    db_test_session_manager: async_sessionmaker[AsyncSession],
    logged_in_user: User,
):
    """A clinician with no affirming-identity / niche claims and the
    default `languages=["en"]` shows only the Languages row (the
    column has a NOT NULL default of `["en"]` at the model layer).
    The affirming-identity and clinical-niche rows are guarded by
    `{% if view.x %}` and suppress cleanly when the list is empty."""
    clinician_id = await _seed_clinician_for(
        db_test_session_manager, user_id=logged_in_user.id
    )

    response = await authenticated_client.get(f"/clinicians/{clinician_id}")
    assert response.status_code == 200
    tree = HTMLParser(response.text)
    assert tree.css_first('[data-fact="affirming_identities"]') is None
    assert tree.css_first('[data-fact="clinical_niches"]') is None
    # `languages` defaults to ["en"] at the model layer, so the row
    # renders here even without an explicit value.
    assert tree.css_first('[data-fact="languages"]') is not None


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
    rows = tree.css("#clinicians-list article")
    assert len(rows) == 2
    pagination = tree.css_first('nav[aria-label="Pagination"]')
    assert pagination is not None
    assert pagination.css_first('a[rel="next"]') is not None
    assert pagination.css_first('a[rel="prev"]') is None

    response2 = await authenticated_client.get("/clinicians?page=2")
    assert response2.status_code == 200
    tree2 = HTMLParser(response2.text)
    rows2 = tree2.css("#clinicians-list article")
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


# --- Sub-resource list pages (#1336) ------------------------------------


@pytest.mark.parametrize(
    "collection",
    ["clinician_affiliations", "licensures", "educations", "certifications"],
)
async def test_get_clinician_subresource_list_responds_200(
    collection: str,
    authenticated_client: AsyncClient,
    db_test_session_manager: async_sessionmaker[AsyncSession],
    logged_in_user: User,
):
    """Each clinician sub-resource has its own `GET /clinicians/{id}/<sub>`
    page (`mount_related_list` from #1336). The pages render the existing
    inline add-form + per-row delete affordances for that sub-resource —
    same data the PR 2 picker on `/clinicians/{id}` deep-links into."""
    clinician_id = await _seed_clinician_for(
        db_test_session_manager, user_id=logged_in_user.id
    )
    response = await authenticated_client.get(
        f"/clinicians/{clinician_id}/{collection}"
    )
    assert response.status_code == 200, response.text


async def test_get_clinician_licensures_renders_existing_rows(
    authenticated_client: AsyncClient,
    db_test_session_manager: async_sessionmaker[AsyncSession],
    logged_in_user: User,
):
    """An existing licensure renders as a whole-row navigation link to its
    edit page on the canonical sub-resource list page. No inline add form
    or per-row delete button — those live in the toolbar and on the edit
    page respectively after the canonical-pattern conversion."""
    clinician_id = await _seed_clinician_for(
        db_test_session_manager, user_id=logged_in_user.id
    )
    clinician_id = await _clinician_id_for(db_test_session_manager, clinician_id)
    licensure = make_clinician_licensure(
        clinician_id=clinician_id, license_type="lcsw", license_number="L-9999"
    )
    async with db_test_session_manager() as session:
        async with session.begin():
            session.add(licensure)
        await session.refresh(licensure)
    lic_id = licensure.id

    response = await authenticated_client.get(f"/clinicians/{clinician_id}/licensures")
    assert response.status_code == 200
    tree = HTMLParser(response.text)
    # The row renders as a `_shared/_card.html` article whose headline
    # link points at the edit page — same vocabulary every top-level
    # list page uses.
    row = tree.css_first(f'article[data-row-id="{lic_id}"]')
    assert row is not None
    headline_link = row.css_first(
        f'h3 a[href="/clinicians/{clinician_id}/licensures/{lic_id}/form"]'
    )
    assert headline_link is not None
    # Toolbar carries the "Create licensure" link to the new-form page.
    create_link = tree.css_first(
        f'a[href="/clinicians/{clinician_id}/licensures/form"][role="button"]'
    )
    assert create_link is not None
    # No inline add form on the canonical list page.
    assert (
        tree.css_first(f'form[hx-post="/clinicians/{clinician_id}/licensures"]') is None
    )
    # No per-row delete button — Delete moves to the edit page's actions.
    assert (
        tree.css_first(
            f'button[hx-delete="/clinicians/{clinician_id}/licensures/{lic_id}"]'
        )
        is None
    )


async def test_get_clinician_affiliations_list_is_readonly_canonical_shape(
    authenticated_client: AsyncClient,
    db_test_session_manager: async_sessionmaker[AsyncSession],
    logged_in_user: User,
):
    """After PR 4's canonical-pattern conversion, the affiliations list
    page has no inline add form and no per-row delete button — same
    shape as the credential lists. Create lives in the toolbar; Delete
    moves to the row's edit page."""
    clinician_id = await _seed_clinician_for(
        db_test_session_manager, user_id=logged_in_user.id
    )
    response = await authenticated_client.get(
        f"/clinicians/{clinician_id}/clinician_affiliations"
    )
    assert response.status_code == 200
    tree = HTMLParser(response.text)
    # No inline add form.
    assert (
        tree.css_first(
            f'form[hx-post="/clinicians/{clinician_id}/clinician_affiliations"]'
        )
        is None
    )
    # Toolbar carries Create.
    create_link = tree.css_first(
        f'a[href="/clinicians/{clinician_id}/clinician_affiliations/form"][role="button"]'
    )
    assert create_link is not None


async def test_get_clinician_affiliation_new_form_carries_org_picker(
    authenticated_client: AsyncClient,
    db_test_session_manager: async_sessionmaker[AsyncSession],
    logged_in_user: User,
):
    """The dedicated affiliation create-form page renders the Org picker
    populated with the viewer's owned Orgs. Plumbed through the spec's
    `form_extras_path` → `clinician_form_extras` (shared with the
    clinician edit page so the same orgs surface in both places)."""
    clinician_id = await _seed_clinician_for(
        db_test_session_manager, user_id=logged_in_user.id
    )
    await _seed_org(
        db_test_session_manager, owner_id=logged_in_user.id, name="My Practice LLC"
    )
    response = await authenticated_client.get(
        f"/clinicians/{clinician_id}/clinician_affiliations/form"
    )
    assert response.status_code == 200
    tree = HTMLParser(response.text)
    add_form = tree.css_first(
        f'form[hx-post="/clinicians/{clinician_id}/clinician_affiliations"]'
    )
    assert add_form is not None
    org_select = add_form.css_first('select[name="org_id"]')
    assert org_select is not None
    option_labels = [o.text(strip=True) for o in org_select.css("option")]
    assert any("My Practice LLC" in lbl for lbl in option_labels)


# --- Steady-state how-to-refer UI ---------------------------------------
#
# After the #1358 remodel, the per-(clinician × org) **steady-state
# practice profile** (services / settings / modalities / age_groups /
# genders / cost / delivery format) moved off `ClinicianAffiliation`
# onto `OpeningDetail` (the opening post). The affiliation now carries
# only location, insurance posture, and the how-to-refer fields
# (`website`, `referral_instructions`), so `_form_affiliation.html`
# surfaces just those two free-text fields.
# `currently_accepting_new_patients` is a server-managed cache flipped by
# the OpeningDetail lifecycle; the list page renders it as a read-only
# "Accepting new patients" badge.


async def test_get_clinician_affiliation_new_form_renders_how_to_refer_fields(
    authenticated_client: AsyncClient,
    db_test_session_manager: async_sessionmaker[AsyncSession],
    logged_in_user: User,
):
    """The create form carries inputs for the how-to-refer fields the
    affiliation still owns (`website`, `referral_instructions`)."""
    clinician_id = await _seed_clinician_for(
        db_test_session_manager, user_id=logged_in_user.id
    )
    response = await authenticated_client.get(
        f"/clinicians/{clinician_id}/clinician_affiliations/form"
    )
    assert response.status_code == 200
    tree = HTMLParser(response.text)
    add_form = tree.css_first(
        f'form[hx-post="/clinicians/{clinician_id}/clinician_affiliations"]'
    )
    assert add_form is not None
    for name in ("website", "referral_instructions"):
        assert (
            add_form.css_first(f'[name="{name}"]') is not None
        ), f"create form missing input name={name}"


async def test_get_clinician_affiliation_edit_form_prefills_how_to_refer_fields(
    authenticated_client: AsyncClient,
    db_test_session_manager: async_sessionmaker[AsyncSession],
    logged_in_user: User,
):
    """The edit form pre-fills persisted how-to-refer values so the user
    sees what they previously saved before patching."""
    from src.domain.models import ClinicianAffiliation

    clinician_id = await _seed_clinician_for(
        db_test_session_manager, user_id=logged_in_user.id
    )
    async with db_test_session_manager() as session:
        async with session.begin():
            aff = (
                await session.execute(
                    select(ClinicianAffiliation).where(
                        ClinicianAffiliation.clinician_id == clinician_id
                    )
                )
            ).scalar_one()
            aff.website = "https://drsmith.example.com"
            aff.referral_instructions = "Email intake@example.com."
        aff_id = aff.id

    response = await authenticated_client.get(
        f"/clinicians/{clinician_id}/clinician_affiliations/{aff_id}/form"
    )
    assert response.status_code == 200, response.text
    tree = HTMLParser(response.text)

    website_input = tree.css_first('input[name="website"]')
    assert website_input is not None
    assert website_input.attributes.get("value") == "https://drsmith.example.com"
    ref_textarea = tree.css_first('textarea[name="referral_instructions"]')
    assert ref_textarea is not None
    assert "intake@example.com" in (ref_textarea.text() or "")


async def test_post_affiliation_persists_how_to_refer_fields(
    authenticated_client: AsyncClient,
    db_test_session_manager: async_sessionmaker[AsyncSession],
    logged_in_user: User,
):
    """POST with the how-to-refer fields creates a row carrying them —
    the create form's round-trip pin."""
    from src.domain.models import ClinicianAffiliation

    clinician_id = await _seed_clinician_for(
        db_test_session_manager, user_id=logged_in_user.id
    )
    response = await authenticated_client.post(
        f"/clinicians/{clinician_id}/clinician_affiliations",
        data={
            "website": "https://example.com",
            "referral_instructions": "Email intake@example.com.",
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
    # Find the newly created row (the seed clinician comes with one
    # default affiliation; the POST added a second).
    new_row = next(r for r in rows if (r.website or "") == "https://example.com")
    assert new_row.website == "https://example.com"
    assert new_row.referral_instructions == "Email intake@example.com."


async def test_patch_affiliation_updates_how_to_refer_fields(
    authenticated_client: AsyncClient,
    db_test_session_manager: async_sessionmaker[AsyncSession],
    logged_in_user: User,
):
    """PATCH replaces the how-to-refer free-text fields on the row —
    the wire-to-DB round-trip pin."""
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

    response = await authenticated_client.patch(
        f"/clinicians/{clinician_id}/clinician_affiliations/{aff_id}",
        data={
            "website": "https://updated.example.com",
            "referral_instructions": "Call the front desk.",
        },
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["website"] == "https://updated.example.com"
    assert body["referral_instructions"] == "Call the front desk."


async def test_clinician_affiliations_list_hides_accepting_badge_when_false(
    authenticated_client: AsyncClient,
    db_test_session_manager: async_sessionmaker[AsyncSession],
    logged_in_user: User,
):
    """`currently_accepting_new_patients=False` (the default) suppresses
    the "Accepting new patients" badge entirely."""
    clinician_id = await _seed_clinician_for(
        db_test_session_manager, user_id=logged_in_user.id
    )
    response = await authenticated_client.get(
        f"/clinicians/{clinician_id}/clinician_affiliations"
    )
    assert response.status_code == 200
    assert "Accepting new patients" not in response.text


async def test_get_affiliation_edit_form_404s_for_non_owner(
    authenticated_client: AsyncClient,
    db_test_session_manager: async_sessionmaker[AsyncSession],
    logged_in_user: User,
):
    """Only the Clinician's owner (or admin) can reach the affiliation
    edit form — `OWNER_OR_ADMIN` policy on the spec. A non-owner sees
    a 404 (not 403), matching the per-row delete/patch behavior."""
    from src.domain.models import ClinicianAffiliation

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

    response = await authenticated_client.get(
        f"/clinicians/{other_clinician_id}/clinician_affiliations/{other_aff_id}/form"
    )
    assert response.status_code in (403, 404)


async def test_patch_affiliation_profile_blocked_for_non_owner(
    authenticated_client: AsyncClient,
    db_test_session_manager: async_sessionmaker[AsyncSession],
    logged_in_user: User,
):
    """A non-owner can't PATCH another clinician's affiliation profile —
    the auth policy applies to every field on the affiliation."""
    from src.domain.models import ClinicianAffiliation

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

    response = await authenticated_client.patch(
        f"/clinicians/{other_clinician_id}/clinician_affiliations/{other_aff_id}",
        data={"website": "https://hijacked.example.com"},
    )
    assert response.status_code in (403, 404)


@pytest.mark.parametrize(
    "collection",
    ["clinician_affiliations", "licensures", "educations", "certifications"],
)
async def test_get_clinician_subresource_list_404_for_missing_clinician(
    collection: str,
    authenticated_client: AsyncClient,
    logged_in_user: User,
):
    """A nonexistent clinician id 404s for every sub-resource list page,
    same shape as the existing openings list (mount_related_list runs
    the parent lookup before the handler)."""
    response = await authenticated_client.get(
        f"/clinicians/{uuid.uuid4()}/{collection}"
    )
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
