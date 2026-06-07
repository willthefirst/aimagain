"""URL invariants for the unified `/posts` whole-supertype face.

`Post` is a polymorphic supertype with three kinds (`referral`,
`clinician_opening`, `program_intake`) exposed under a single URL
family. This module pins the cross-kind invariants the framework's
whole-supertype dispatch buys us:

  - the list / search / form-picker routes respond 200;
  - `/posts/form` (no `?kind=`) renders the picker; `/posts/form?kind=X`
    renders the kind-specific create form;
  - the `kind` filter is exposed on `/posts/search` so a viewer can
    narrow the unified feed to one kind;
  - `?kind=<value>` on the list URL narrows results to that kind;
  - owner authz invariants survive the consolidation (non-owner can't
    patch/delete; admin can);
  - the `form_error_render` opt-in is wired end-to-end for each kind.

Per-kind detail-rendering assertions (which DOM elements a referral
card surfaces vs. an opening card vs. an intake card) are the long
tail and live in the kind-specific template / card-view tests.
"""

import uuid

import pytest
from httpx import AsyncClient
from selectolax.parser import HTMLParser
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from src.domain.models import Clinician, Organization, Post, Program
from src.domain.models.org_representations.org_representation import OrgRepresentation
from tests.helpers import (
    create_test_user,
    make_clinician_with_org,
    make_intake_detail,
    make_opening_detail,
    make_organization_row,
    make_program,
    make_referral_detail,
    opening_payload,
    promote_to_admin,
    referral_payload,
)

pytestmark = pytest.mark.asyncio


# --- Per-kind row builders -----------------------------------------------


def _referral_post(*, owner_id, description: str = "ref", **overrides) -> Post:
    post = Post(kind="referral", owner_id=owner_id)
    post.referral_detail = make_referral_detail(description=description, **overrides)
    return post


def _opening_post(
    *, owner_id, practice_name: str = "Practice", clinician: Clinician | None = None
) -> Post:
    if clinician is None:
        clinician = make_clinician_with_org(
            owner_id=owner_id, practice_name=practice_name
        )
    if clinician.id is None:
        clinician.id = uuid.uuid4()
    post = Post(kind="clinician_opening", owner_id=owner_id)
    detail = make_opening_detail(clinician_id=clinician.id)
    detail.clinician = clinician
    post.opening_detail = detail
    return post


def _intake_post(*, owner_id, org_id, program: Program | None = None) -> Post:
    """Build a `kind='program_intake'` Post row with a fresh Program +
    IntakeDetail attached. `org_id` is required because Program FKs to
    Organization and the test session needs the parent row present."""
    if program is None:
        program = make_program(owner_id=owner_id, org_id=org_id)
    if program.id is None:
        program.id = uuid.uuid4()
    post = Post(kind="program_intake", owner_id=owner_id)
    detail = make_intake_detail(program_id=program.id)
    detail.program = program
    post.intake_detail = detail
    return post


# Each kind paired with its row builder. The URL family is the same
# for every kind (`/posts`) — only the row's stored `kind` value differs.
_KINDS = [
    ("referral", _referral_post),
    ("clinician_opening", _opening_post),
]


# --- Routes mount + 200 smoke --------------------------------------------


async def test_list_route_responds_200(
    authenticated_client: AsyncClient,
    logged_in_user,
):
    """`/posts` responds 200 on an empty database."""
    response = await authenticated_client.get("/posts")
    assert response.status_code == 200


async def test_search_route_responds_200(
    authenticated_client: AsyncClient,
    logged_in_user,
):
    response = await authenticated_client.get("/posts/search")
    assert response.status_code == 200


async def test_form_new_picker_responds_200(
    authenticated_client: AsyncClient,
    logged_in_user,
):
    """`/posts/form` (no `?kind=`) renders the kind-picker page so the
    user can pick which kind to create. Rendered via the shared
    `_picker.html` macro — one card per kind, each deep-linking to
    `?kind=<value>`."""
    response = await authenticated_client.get("/posts/form")
    assert response.status_code == 200
    body = response.text
    for heading in ("Referral", "Clinician", "Organization"):
        assert f"<h2>{heading}</h2>" in body
    for kind in ("referral", "clinician_opening", "program_intake"):
        assert f"?kind={kind}" in body


@pytest.mark.parametrize("kind", ["referral", "clinician_opening", "program_intake"])
async def test_form_new_with_kind_responds_200(
    kind: str,
    authenticated_client: AsyncClient,
    logged_in_user,
):
    """`/posts/form?kind=<value>` renders the kind-specific create form
    (one per registered kind in `POST_KINDS`)."""
    response = await authenticated_client.get(f"/posts/form?kind={kind}")
    assert response.status_code == 200


# --- Search form: kind filter is present ---------------------------------


async def test_search_form_renders_kind_filter(
    authenticated_client: AsyncClient,
    logged_in_user,
):
    """The whole-supertype face exposes a `kind` filter on its search
    form so the viewer can narrow the unified feed to one kind. The
    filter is a multi-select with every registered kind as a choice."""
    response = await authenticated_client.get("/posts/search")
    assert response.status_code == 200
    tree = HTMLParser(response.text)
    kind_inputs = tree.css('form [name="kind"]')
    assert kind_inputs, "/posts/search did not render a `kind` input"
    values = {inp.attributes.get("value") for inp in kind_inputs}
    assert {"referral", "clinician_opening", "program_intake"} <= values


async def test_search_uses_shared_filter_form(
    authenticated_client: AsyncClient,
    logged_in_user,
):
    """`/posts/search` renders the same custom filter form component as the
    list-page sidebar — `posts-filter-section` fieldsets for Kind, Location,
    Level of care, Modality, Populations, and Insurance — not the generic
    framework search form (`search-checkbox-fieldset`)."""
    response = await authenticated_client.get("/posts/search")
    assert response.status_code == 200
    tree = HTMLParser(response.text)
    sections = tree.css("fieldset.posts-filter-section")
    legends = [s.css_first("legend").text(strip=True) for s in sections]
    assert legends == [
        "Kind",
        "Location",
        "Level of care",
        "Modality",
        "Populations",
        "Insurance",
    ], f"Unexpected filter sections on /posts/search: {legends}"
    # Generic framework fieldset class must not appear — the shared macro owns the form.
    assert not tree.css(
        "fieldset.search-checkbox-fieldset"
    ), "/posts/search should not render the generic framework search form"


async def test_list_sidebar_uses_shared_filter_form(
    authenticated_client: AsyncClient,
    logged_in_user,
):
    """`/posts` list sidebar renders the same `posts-filter-section` fieldsets
    as `/posts/search`, confirming both surfaces share the same component."""
    response = await authenticated_client.get("/posts")
    assert response.status_code == 200
    tree = HTMLParser(response.text)
    sidebar = tree.css_first(".posts-filter-sidebar")
    assert sidebar, "/posts did not render a .posts-filter-sidebar element"
    sections = sidebar.css("fieldset.posts-filter-section")
    legends = [s.css_first("legend").text(strip=True) for s in sections]
    assert legends == [
        "Kind",
        "Location",
        "Level of care",
        "Modality",
        "Populations",
        "Insurance",
    ], f"Unexpected filter sections in /posts sidebar: {legends}"


# --- List filter: ?kind= narrows the feed --------------------------------


async def test_list_kind_filter_narrows_to_one_kind(
    authenticated_client: AsyncClient,
    db_test_session_manager: async_sessionmaker[AsyncSession],
    logged_in_user,
):
    """`/posts?kind=referral` narrows the feed to that kind. Without
    a filter the feed includes every kind in the database."""
    author = create_test_user(username=f"a-{uuid.uuid4()}")
    org = Organization(owner_id=author.id, name=f"Org {uuid.uuid4()}", type="clinic")
    org.id = uuid.uuid4()
    org.root_org_id = org.id
    referral = _referral_post(owner_id=author.id)
    opening = _opening_post(owner_id=author.id)
    intake = _intake_post(owner_id=author.id, org_id=org.id)
    async with db_test_session_manager() as session:
        async with session.begin():
            session.add(author)
            session.add(org)
            session.add(referral)
            session.add(opening)
            session.add(intake)

    # No filter → every kind visible.
    response = await authenticated_client.get("/posts")
    assert response.status_code == 200
    kinds_unfiltered = {
        c.attributes.get("data-kind")
        for c in HTMLParser(response.text).css("#posts-list [data-kind]")
    }
    assert {"referral", "clinician_opening", "program_intake"} <= kinds_unfiltered

    # Filtered to one kind → only that kind.
    response = await authenticated_client.get("/posts?kind=referral")
    assert response.status_code == 200
    kinds_filtered = {
        c.attributes.get("data-kind")
        for c in HTMLParser(response.text).css("#posts-list [data-kind]")
    }
    assert kinds_filtered == {
        "referral"
    }, f"/posts?kind=referral returned: {kinds_filtered!r}"


# --- Detail / edit-form route works across kinds -------------------------


@pytest.mark.parametrize("kind,builder", _KINDS)
async def test_detail_route_works_for_each_kind(
    kind: str,
    builder,
    authenticated_client: AsyncClient,
    db_test_session_manager: async_sessionmaker[AsyncSession],
    logged_in_user,
):
    """`/posts/{id}` resolves any registered kind — no kind-lock 404
    on the whole-supertype face."""
    author = create_test_user(username=f"a-{uuid.uuid4()}")
    post = builder(owner_id=author.id)
    async with db_test_session_manager() as session:
        async with session.begin():
            session.add(author)
            session.add(post)

    response = await authenticated_client.get(f"/posts/{post.id}")
    assert response.status_code == 200


@pytest.mark.parametrize("kind,builder", _KINDS)
async def test_edit_form_route_works_for_each_kind(
    kind: str,
    builder,
    authenticated_client: AsyncClient,
    db_test_session_manager: async_sessionmaker[AsyncSession],
    logged_in_user,
):
    """`/posts/{id}/form` resolves any registered kind and dispatches
    to the kind-specific edit template."""
    author = logged_in_user
    post = builder(owner_id=author.id)
    async with db_test_session_manager() as session:
        async with session.begin():
            session.add(post)

    response = await authenticated_client.get(f"/posts/{post.id}/form")
    assert response.status_code == 200


# --- Owner authz invariants ----------------------------------------------


@pytest.mark.parametrize("kind,builder", _KINDS)
async def test_non_owner_cannot_patch(
    kind: str,
    builder,
    authenticated_client: AsyncClient,
    db_test_session_manager: async_sessionmaker[AsyncSession],
    logged_in_user,
):
    """A logged-in user who isn't the post owner (and isn't an admin)
    can't PATCH it — `auth_policy=OWNER_OR_ADMIN` is enforced on the
    unified face."""
    other = create_test_user(username=f"other-{uuid.uuid4()}")
    post = builder(owner_id=other.id)
    async with db_test_session_manager() as session:
        async with session.begin():
            session.add(other)
            session.add(post)

    response = await authenticated_client.patch(
        f"/posts/{post.id}",
        data={"description": "hacked", "kind": kind},
    )
    assert response.status_code == 403


@pytest.mark.parametrize("kind,builder", _KINDS)
async def test_admin_can_patch_anyone(
    kind: str,
    builder,
    authenticated_client: AsyncClient,
    db_test_session_manager: async_sessionmaker[AsyncSession],
    logged_in_user,
):
    """Admins keep the cross-owner write hatch — `OWNER_OR_ADMIN`'s
    "or admin" branch survives the consolidation."""
    await promote_to_admin(db_test_session_manager, logged_in_user.email)
    other = create_test_user(username=f"other-{uuid.uuid4()}")
    post = builder(owner_id=other.id)
    async with db_test_session_manager() as session:
        async with session.begin():
            session.add(other)
            session.add(post)

    response = await authenticated_client.patch(
        f"/posts/{post.id}",
        data={"description": "admin-patched", "kind": kind},
    )
    # PATCH bodies vary per kind; we don't pin success here — the
    # important assertion is "not 403". A 400 / 422 on body shape is
    # acceptable; a 403 would be the regression we want to catch.
    assert response.status_code != 403


# --- Form-error re-render (form_error_render opt-in) ---------------------


async def test_clinician_opening_create_form_error_render_is_wired(
    authenticated_client: AsyncClient,
    db_test_session_manager: async_sessionmaker[AsyncSession],
    logged_in_user,
):
    """Integration smoke for `POST_ENTITY.form_error_render` exercised
    against the clinician_opening kind. HX-Request POST with invalid
    `age_groups` returns 422 + HTML and the response surfaces the
    failing field's inline error.

    Structural contracts live in their owning layers, not here:

      - HX-Request vs not, 422 vs JSON, `form_errors` dict shape,
        kind-prefix stripping → `src/framework/dispatch/mounts/test_create.py`.
      - Pico-canonical `aria-invalid` + helper-slot rendering →
        `src/framework/templates/_shared/test_form_fields.py`.
    """
    clinician = make_clinician_with_org(owner_id=logged_in_user.id)
    async with db_test_session_manager() as session:
        async with session.begin():
            session.add(clinician)

    payload = opening_payload(clinician_id=str(clinician.id))
    payload["age_groups"] = []

    response = await authenticated_client.post(
        "/posts",
        data=payload,
        headers={"HX-Request": "true"},
    )
    assert response.status_code == 422, response.text
    assert response.headers["content-type"].startswith("text/html")
    assert 'name="age_groups"' in response.text
    age_block_start = response.text.index('name="age_groups"')
    age_block = response.text[max(0, age_block_start - 200) : age_block_start + 200]
    assert 'aria-invalid="true"' in age_block, age_block
    # Fragment-only response: the re-render returns just the `<form>`,
    # not the full `new_clinician_opening.html` page (which extends
    # base.html).
    assert "<!DOCTYPE" not in response.text
    assert "<html" not in response.text
    assert "Bedlam Connect" not in response.text


async def test_referral_create_form_error_render_is_wired(
    authenticated_client: AsyncClient,
    logged_in_user,
):
    """Integration smoke for `POST_ENTITY.form_error_render` exercised
    against the referral kind — same shape as the clinician_opening
    smoke above, confirms the declarative pattern generalizes across
    kinds. The referral form's `_form_referral.html` imports
    `_shared/form_fields.html` macros `with context`, so the per-field
    `error=`/`current=` are auto-resolved from `form_errors`/`form_values`
    without any template-side threading.
    """
    payload = referral_payload(age_groups=[])

    response = await authenticated_client.post(
        "/posts",
        data=payload,
        headers={"HX-Request": "true"},
    )
    assert response.status_code == 422, response.text
    assert response.headers["content-type"].startswith("text/html")
    assert 'name="age_groups"' in response.text
    age_block_start = response.text.index('name="age_groups"')
    age_block = response.text[max(0, age_block_start - 200) : age_block_start + 200]
    assert 'aria-invalid="true"' in age_block, age_block
    assert "<!DOCTYPE" not in response.text
    assert "<html" not in response.text
    assert "Bedlam Connect" not in response.text


# --- Clinician-profile gate on create forms ------------------------------


@pytest.mark.parametrize("kind", ["referral", "clinician_opening"])
async def test_create_form_gate_shown_when_no_clinician_profile(
    kind: str,
    authenticated_client: AsyncClient,
    logged_in_user,
):
    """GET /posts/form?kind=<kind> shows the clinician-profile gate when the
    requesting user has no clinician profiles, not the create form."""
    response = await authenticated_client.get(f"/posts/form?kind={kind}")
    assert response.status_code == 200
    assert "Create your clinician profile" in response.text
    # The post-create form fields should not be rendered.
    assert 'name="kind"' not in response.text


@pytest.mark.parametrize("kind", ["referral", "clinician_opening"])
async def test_create_form_shown_when_clinician_profile_exists(
    kind: str,
    authenticated_client: AsyncClient,
    db_test_session_manager: async_sessionmaker[AsyncSession],
    logged_in_user,
):
    """GET /posts/form?kind=<kind> renders the create form once the user has
    at least one clinician profile."""
    clinician = make_clinician_with_org(owner_id=logged_in_user.id)
    async with db_test_session_manager() as session:
        async with session.begin():
            session.add(clinician)

    response = await authenticated_client.get(f"/posts/form?kind={kind}")
    assert response.status_code == 200
    assert 'name="kind"' in response.text
    assert "Create your clinician profile" not in response.text


# Both clinician-authored kinds now expose a single practice picker named
# `clinician_affiliation_id` (one option per affiliation); the server
# derives the clinician FK from the chosen affiliation.
_CLINICIAN_FIELD = {
    "referral": "clinician_affiliation_id",
    "clinician_opening": "clinician_affiliation_id",
}


@pytest.mark.parametrize("kind", ["referral", "clinician_opening"])
async def test_create_form_preselects_first_clinician(
    kind: str,
    authenticated_client: AsyncClient,
    db_test_session_manager: async_sessionmaker[AsyncSession],
    logged_in_user,
):
    """The practice picker on new-post forms defaults to the user's first
    affiliation — no placeholder '-- ' option is rendered."""
    clinician = make_clinician_with_org(
        owner_id=logged_in_user.id, practice_name="First Practice"
    )
    async with db_test_session_manager() as session:
        async with session.begin():
            session.add(clinician)
    affiliation_id = clinician.clinician_affiliations[0].id

    response = await authenticated_client.get(f"/posts/form?kind={kind}")
    assert response.status_code == 200

    tree = HTMLParser(response.text)
    field_name = _CLINICIAN_FIELD[kind]
    select = tree.css_first(f'select[name="{field_name}"]')
    assert select is not None, f"no <select name={field_name!r}> in response"

    options = select.css("option")
    assert options, "practice select rendered no options"

    # No disabled placeholder.
    assert not any(
        o.attributes.get("disabled") is not None and "--" in (o.text() or "")
        for o in options
    ), "placeholder '--' option should not be present on new form"

    # First (and only) option is pre-selected.
    # selectolax stores boolean HTML attributes (e.g. `selected`) as None, so
    # key presence — not a non-None value — is the correct sentinel.
    assert (
        "selected" in options[0].attributes
    ), "first affiliation option should carry the 'selected' attribute"
    assert str(affiliation_id) in (
        options[0].attributes.get("value") or ""
    ), "selected option value should be the first affiliation's id"


# --- Anonymization gate (can_access_network) ---------------------------------


async def test_list_has_no_inline_verify_notice_for_unverified(
    authenticated_client: AsyncClient,
    logged_in_user,
):
    """The /posts list carries no inline verify notice, even for an
    unverified viewer. Poster names / contact are anonymized server-side;
    the single chrome `#onboarding-banner` is the only place that explains
    verification unlocks the full view — the old `posts-verify-notice` is
    gone."""
    response = await authenticated_client.get("/posts")
    assert response.status_code == 200
    assert "posts-verify-notice" not in response.text
    # No inline locked placeholder in the list body — locked affordances only
    # appear in the toolbar (locked_action for Create) and globally in the
    # locked-cta popovers rendered by base.html.
    tree = HTMLParser(response.text)
    main = tree.css_first("main")
    assert main is not None
    assert main.css_first("button.locked-ghost-btn") is None


# --- Toolbar Create CTA gate (posting-capable claim) -------------------------


async def test_list_hides_create_cta_for_claimless_user(
    authenticated_client: AsyncClient,
    logged_in_user,
):
    """The `/posts` toolbar 'Create' button is hidden for a user holding
    no posting-capable claim — clicking it would only land on a server
    403 / degraded form. Matches the per-kind post gate's universe."""
    response = await authenticated_client.get("/posts")
    assert response.status_code == 200
    tree = HTMLParser(response.text)
    assert (
        tree.css_first("a[href='/posts/form'][role='button']") is None
    ), "claimless user must not be offered the toolbar Create CTA"


async def test_list_shows_create_cta_for_claim_a_user(
    authenticated_client: AsyncClient,
    db_test_session_manager: async_sessionmaker[AsyncSession],
    logged_in_user,
):
    """A Claim-A (verified clinician) user sees the toolbar 'Create' CTA —
    the server post gate would let them through."""
    clinician = make_clinician_with_org(owner_id=logged_in_user.id, npi="1234567890")
    clinician.npi_match_status = "matched"
    clinician.clinician_verified = True
    async with db_test_session_manager() as session:
        async with session.begin():
            session.add(clinician)

    response = await authenticated_client.get("/posts")
    assert response.status_code == 200
    tree = HTMLParser(response.text)
    assert (
        tree.css_first("a[href='/posts/form'][role='button']") is not None
    ), "Claim-A user should be offered the toolbar Create CTA"


async def test_list_shows_create_cta_for_claim_b_org_rep(
    authenticated_client: AsyncClient,
    db_test_session_manager: async_sessionmaker[AsyncSession],
    logged_in_user,
):
    """A verified org rep (no clinician profile) must see the `/posts` toolbar
    Create CTA — `can_access_network` is the single gate for posting."""
    org = make_organization_row(owner_id=logged_in_user.id)
    rep = OrgRepresentation(
        user_id=logged_in_user.id,
        org_id=org.id,
        role="coordinator",
        authority_method="admin_review",
        authority_status="verified",
    )
    async with db_test_session_manager() as session:
        async with session.begin():
            session.add(org)
            session.add(rep)

    response = await authenticated_client.get("/posts")
    assert response.status_code == 200
    tree = HTMLParser(response.text)
    assert (
        tree.css_first("a[href='/posts/form'][role='button']") is not None
    ), "Claim-B org rep must be offered the toolbar Create CTA"


async def test_detail_hides_email_and_shows_cta_for_unverified(
    authenticated_client: AsyncClient,
    db_test_session_manager: async_sessionmaker[AsyncSession],
    logged_in_user,
):
    """Unverified users see a disabled Email button (not a mailto link) on
    post detail — contact info is not sent to the browser."""
    author = create_test_user(
        username=f"detail-author-{uuid.uuid4()}",
        email=f"detail-author-{uuid.uuid4()}@example.com",
    )
    post = _referral_post(owner_id=author.id)
    async with db_test_session_manager() as session:
        async with session.begin():
            session.add(author)
            session.add(post)

    response = await authenticated_client.get(f"/posts/{post.id}")
    assert response.status_code == 200
    assert f"mailto:{author.email}" not in response.text
    assert author.email not in response.text
    assert "disabled" in response.text
    assert "Email" in response.text


async def test_detail_shows_email_for_verified(
    authenticated_client: AsyncClient,
    db_test_session_manager: async_sessionmaker[AsyncSession],
    logged_in_user,
):
    """Verified users (Claim A active) see the poster's email button on the
    post detail page."""
    clinician = make_clinician_with_org(owner_id=logged_in_user.id, npi="1234567890")
    clinician.npi_match_status = "matched"
    clinician.clinician_verified = True
    author_email = f"detail-author-{uuid.uuid4()}@example.com"
    author = create_test_user(
        username=f"detail-author-{uuid.uuid4()}",
        email=author_email,
    )
    post = _referral_post(owner_id=author.id)
    async with db_test_session_manager() as session:
        async with session.begin():
            session.add(clinician)
            session.add(author)
            session.add(post)

    response = await authenticated_client.get(f"/posts/{post.id}")
    assert response.status_code == 200
    assert f"mailto:{author_email}" in response.text


async def test_detail_redacts_identity_rows_as_locked_placeholders_for_unverified(
    authenticated_client: AsyncClient,
    db_test_session_manager: async_sessionmaker[AsyncSession],
    logged_in_user,
):
    """A viewer who can't read the full feed sees the practice /
    organization / address rows on post detail as `locked_field`
    placeholders (lock icon + fix link), not silently dropped. The real
    links + address value are NOT emitted — withholding, not CSS-hiding."""
    author = create_test_user(username=f"author-{uuid.uuid4()}")
    clinician = make_clinician_with_org(owner_id=author.id, practice_name="Acme Health")
    clinician.id = clinician.id or uuid.uuid4()
    post = _opening_post(owner_id=author.id, clinician=clinician)
    org_id = clinician.org.id
    async with db_test_session_manager() as session:
        async with session.begin():
            session.add(author)
            session.add(post)

    response = await authenticated_client.get(f"/posts/{post.id}")
    assert response.status_code == 200
    tree = HTMLParser(response.text)

    # The rows still render (the viewer knows the detail exists)...
    for fact_key in ("practice", "organization", "address"):
        dd = tree.css_first(f'div[data-fact="{fact_key}"] dd')
        assert dd is not None, f"{fact_key} row should still render when redacted"
        assert (
            dd.css_first("button.locked-ghost-btn") is not None
        ), f"{fact_key} should render a locked placeholder"

    # ...but the real navigable links + the address value are withheld.
    assert tree.css_first(f"a[href='/clinicians/{clinician.id}']") is None
    assert tree.css_first(f"a[href='/organizations/{org_id}']") is None
    assert "Springfield, IL" not in response.text


async def test_detail_shows_identity_rows_for_verified_viewer(
    authenticated_client: AsyncClient,
    db_test_session_manager: async_sessionmaker[AsyncSession],
    logged_in_user,
):
    """A verified viewer (can read the full feed) sees the real practice /
    organization links and the full address — no locked placeholders."""
    viewer_clinician = make_clinician_with_org(
        owner_id=logged_in_user.id, npi="1234567890"
    )
    viewer_clinician.npi_match_status = "matched"
    viewer_clinician.clinician_verified = True

    author = create_test_user(username=f"author-{uuid.uuid4()}")
    clinician = make_clinician_with_org(owner_id=author.id, practice_name="Acme Health")
    clinician.id = clinician.id or uuid.uuid4()
    post = _opening_post(owner_id=author.id, clinician=clinician)
    async with db_test_session_manager() as session:
        async with session.begin():
            session.add(viewer_clinician)
            session.add(author)
            session.add(post)

    response = await authenticated_client.get(f"/posts/{post.id}")
    assert response.status_code == 200
    tree = HTMLParser(response.text)

    assert tree.css_first(f"a[href='/clinicians/{clinician.id}']") is not None
    assert "Springfield, IL" in response.text
    assert tree.css_first("button.locked-ghost-btn") is None
