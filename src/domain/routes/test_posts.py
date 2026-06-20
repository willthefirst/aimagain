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
    make_clinician,
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
    # Wire the affiliation the opening announces — production posts
    # always carry it (`_resolve_affiliation_context`), and the view
    # reads practice facts (org, location, payment) from here, not
    # through the clinician's primary-affiliation proxies.
    detail.clinician_affiliation = clinician.primary_clinician_affiliation
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
    `_picker.html` macro — one card per kind. Headings come from
    `POST_KINDS[k].noun` (the SOT after #1330); descriptions come from
    `POST_KINDS[k].picker_description`. Tiles for kinds whose
    capability the viewer doesn't hold render as a locked-CTA instead
    of a navigable `?kind=` link. For the default test user (no
    verified email, no claims, no programs):

    - `program_intake` is locked on `capabilities.check_program_intake`
      (REASON_PROGRAM_INTAKE_LOCKED — email + verified org rep + owned
      program).
    - `referral` and `clinician_opening` are locked on
      `capabilities.can_act_as_provider`
      (REASON_NOT_A_VERIFIED_PROVIDER — email + (Claim A OR Claim B)).
    """
    response = await authenticated_client.get("/posts/form")
    assert response.status_code == 200
    body = response.text
    for heading in ("Referral", "Opening", "Program intake"):
        assert heading in body
    # All three tiles are locked for the default test user, so none of
    # them carry a navigable `?kind=` link.
    for kind in ("referral", "clinician_opening", "program_intake"):
        assert f"?kind={kind}" not in body
    assert 'data-locked-cta="program_intake_locked"' in body
    assert 'data-locked-cta="network_unverified"' in body
    # The picker no longer wraps its heading in a `<header>` band
    # (#1330 — the cards render flatter via Pico's default chrome).
    assert "<header>" not in body


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
    filter is a multi-select with every registered kind as a choice.
    The visible labels come from `POST_KINDS[k].noun` — the same SOT
    the /posts/form picker headings read from (#1330), so the sidebar
    and the picker can't drift."""
    response = await authenticated_client.get("/posts/search")
    assert response.status_code == 200
    tree = HTMLParser(response.text)
    kind_inputs = tree.css('form [name="kind"]')
    assert kind_inputs, "/posts/search did not render a `kind` input"
    values = {inp.attributes.get("value") for inp in kind_inputs}
    assert {"referral", "clinician_opening", "program_intake"} <= values
    # Visible labels match the canonical nouns (capital-case). Scope
    # to the `kind` fieldset's <label>s to avoid catching other
    # checkbox labels on the page.
    fieldset = next(
        fs
        for fs in tree.css("fieldset.search-checkbox-fieldset")
        if fs.css_first("legend") and fs.css_first("legend").text(strip=True) == "Type"
    )
    visible = {lbl.text(strip=True) for lbl in fieldset.css("label")}
    assert {"Referral", "Opening", "Program intake"} <= visible


async def test_search_uses_framework_filter_form(
    authenticated_client: AsyncClient,
    logged_in_user,
):
    """`/posts/search` uses the shared `filter_field` macro from
    `_shared/_filter_field.html` — the same macro that renders the inline
    sidebar on `/posts`. Both surfaces are driven by the spec's declared
    Filter objects, so control shapes and labels stay in sync automatically."""
    response = await authenticated_client.get("/posts/search")
    assert response.status_code == 200
    tree = HTMLParser(response.text)
    # The framework macro uses search-checkbox-fieldset for multi-choice filters.
    sections = tree.css("fieldset.search-checkbox-fieldset")
    assert (
        sections
    ), "/posts/search did not render any search-checkbox-fieldset elements"
    legends = [s.css_first("legend").text(strip=True) for s in sections]
    # Multi-choice filters from the spec: kind(Type), state(State), age_group,
    # language, level_of_care, modality, insurance.
    assert "Type" in legends, f"Expected 'Type' legend in /posts/search: {legends}"
    assert (
        "Level of care" in legends
    ), f"Expected 'Level of care' in /posts/search: {legends}"
    assert "Insurance" in legends, f"Expected 'Insurance' in /posts/search: {legends}"


async def test_list_has_browse_layout_with_filter_sidebar(
    authenticated_client: AsyncClient,
    logged_in_user,
):
    """`/posts` list renders a `.browse-layout` with a `.filter-sidebar` that
    embeds the framework filter form inline. The sidebar uses the same
    `filter_field` macro as `/posts/search` so both surfaces stay in sync."""
    response = await authenticated_client.get("/posts")
    assert response.status_code == 200
    tree = HTMLParser(response.text)
    sidebar = tree.css_first(".filter-sidebar")
    assert sidebar, "/posts did not render a .filter-sidebar element"
    # Framework filter_field macro renders multi-choice filters as
    # search-checkbox-fieldset fieldsets with plain text legends.
    sections = sidebar.css("fieldset.search-checkbox-fieldset")
    assert sections, "/posts sidebar did not render any filter fieldsets"
    legends = [s.css_first("legend").text(strip=True) for s in sections]
    assert "Type" in legends, f"Expected 'Type' legend in sidebar: {legends}"
    assert "Insurance" in legends, f"Expected 'Insurance' legend in sidebar: {legends}"


# --- List filter: ?kind= narrows the feed --------------------------------


async def test_list_kind_filter_narrows_to_one_kind(
    authenticated_client: AsyncClient,
    db_test_session_manager: async_sessionmaker[AsyncSession],
    logged_in_user,
):
    """`/posts?kind=referral` narrows the feed to that kind. Without
    a filter the feed includes every kind in the database."""
    author = create_test_user(username=f"a-{uuid.uuid4()}")
    org = Organization(owner_id=author.id, name=f"Org {uuid.uuid4()}")
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
    against the clinician_opening kind. HX-Request POST with an invalid
    `clinician_affiliation_id` (a non-UUID string) returns 422 + HTML
    and the response surfaces the failing field's inline error.

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
    # Force a 422 on the required affiliation FK by sending a non-UUID
    # value — the only required wire field on the thin opening shape
    # (#1358 PR-f sub-3).
    payload["clinician_affiliation_id"] = "not-a-uuid"

    response = await authenticated_client.post(
        "/posts",
        data=payload,
        headers={"HX-Request": "true"},
    )
    assert response.status_code == 422, response.text
    assert response.headers["content-type"].startswith("text/html")
    assert 'name="clinician_affiliation_id"' in response.text
    aff_start = response.text.index('name="clinician_affiliation_id"')
    aff_block = response.text[max(0, aff_start - 200) : aff_start + 200]
    assert 'aria-invalid="true"' in aff_block, aff_block
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
    # `multi_select_field` renders a `<div role="group" id="age_groups">`
    # wrapper; the aria-invalid lives on the group, not on each checkbox.
    assert 'id="age_groups"' in response.text
    group_start = response.text.index('id="age_groups"')
    age_block = response.text[max(0, group_start - 200) : group_start + 200]
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


@pytest.mark.parametrize("kind", ["referral", "clinician_opening"])
async def test_create_form_picker_labels_person_first_with_org(
    kind: str,
    authenticated_client: AsyncClient,
    db_test_session_manager: async_sessionmaker[AsyncSession],
    logged_in_user,
):
    """The practice picker labels each affiliation **person first, org as
    disambiguator** — `"<First Last> · <Org Name>"` when the affiliation
    points at an organization. The label was just `<Org Name>` before
    #1308 — that erased the person entirely when one user owned multiple
    clinicians, and broke entirely once solo clinicians (whose
    affiliation has `org_id` NULL) became a first-class state."""
    clinician = make_clinician_with_org(
        owner_id=logged_in_user.id,
        practice_name="Brooklyn Therapy",
        first_name="Jane",
        last_name="Smith",
    )
    async with db_test_session_manager() as session:
        async with session.begin():
            session.add(clinician)
    affiliation_id = clinician.clinician_affiliations[0].id

    response = await authenticated_client.get(f"/posts/form?kind={kind}")
    assert response.status_code == 200

    tree = HTMLParser(response.text)
    select = tree.css_first(f'select[name="{_CLINICIAN_FIELD[kind]}"]')
    assert select is not None
    option = next(
        o
        for o in select.css("option")
        if o.attributes.get("value") == str(affiliation_id)
    )
    assert option.text(strip=True) == "Jane Smith · Brooklyn Therapy"


@pytest.mark.parametrize("kind", ["referral", "clinician_opening"])
async def test_create_form_picker_labels_solo_with_name_only(
    kind: str,
    authenticated_client: AsyncClient,
    db_test_session_manager: async_sessionmaker[AsyncSession],
    logged_in_user,
):
    """Solo clinician: the affiliation row has `org_id` NULL — the label
    is just the clinician's name (no `" · …"` suffix), because there is
    no organizational entity to disclose."""
    from src.domain.models import ClinicianAffiliation

    clinician = make_clinician(
        owner_id=logged_in_user.id,
        first_name="Janet",
        last_name="Solo",
    )
    # Force a stub affiliation with no org — mirrors the PR 2 stub shape.
    clinician.clinician_affiliations = [ClinicianAffiliation(clinician=clinician)]
    async with db_test_session_manager() as session:
        async with session.begin():
            session.add(clinician)
    affiliation_id = clinician.clinician_affiliations[0].id

    response = await authenticated_client.get(f"/posts/form?kind={kind}")
    assert response.status_code == 200

    tree = HTMLParser(response.text)
    select = tree.css_first(f'select[name="{_CLINICIAN_FIELD[kind]}"]')
    assert select is not None
    option = next(
        o
        for o in select.css("option")
        if o.attributes.get("value") == str(affiliation_id)
    )
    assert option.text(strip=True) == "Janet Solo"


# --- Referral form: section labels --------------------------------------


async def test_referral_form_uses_client_oriented_section_labels(
    authenticated_client: AsyncClient,
    db_test_session_manager: async_sessionmaker[AsyncSession],
    logged_in_user,
):
    """The referral form's structured fields describe the CLIENT (the
    person being placed), not the referrer — so the section legends and
    labels say so. Pins the client-oriented copy introduced when the
    referral/opening data-home split was surfaced in the UI: the payment
    section is the client's coverage, the provider-attribute fields are
    grouped under "Provider sought", and the languages label names the
    client."""
    clinician = make_clinician_with_org(owner_id=logged_in_user.id)
    async with db_test_session_manager() as session:
        async with session.begin():
            session.add(clinician)

    response = await authenticated_client.get("/posts/form?kind=referral")
    assert response.status_code == 200
    tree = HTMLParser(response.text)
    # Parse to text so HTML-escaped apostrophes (`&#39;`) decode.
    page_text = tree.body.text()
    assert "Client's coverage" in page_text
    assert "Provider sought" in page_text
    assert "Languages the client speaks" in page_text
    # The checkbox still binds the same wire field; only its label changed.
    assert "bill the client's carrier" in page_text
    assert (
        tree.css_first('input[name="accepts_in_network"]') is not None
    ), "renaming the section must not drop the accepts_in_network field"


async def test_opening_create_form_renders_practice_profile_preview(
    authenticated_client: AsyncClient,
    db_test_session_manager: async_sessionmaker[AsyncSession],
    logged_in_user,
):
    """The opening create form shows a read-only preview of the selected
    practice's steady-state profile (the same `affiliation_facts` rows
    the practice page and the post detail render), so the author sees the
    full post without navigating away. The default (first) affiliation's
    card renders visible; the picker's value drives which card the inline
    script reveals."""
    clinician = make_clinician_with_org(
        owner_id=logged_in_user.id, practice_name="Acme Health"
    )
    clinician.id = clinician.id or uuid.uuid4()
    aff = clinician.primary_clinician_affiliation
    aff.services = ["psychotherapy"]
    aff.sliding_scale = True
    aff.website = "https://acme.example.com"
    async with db_test_session_manager() as session:
        async with session.begin():
            session.add(clinician)

    response = await authenticated_client.get("/posts/form?kind=clinician_opening")
    assert response.status_code == 200
    tree = HTMLParser(response.text)

    wrap = tree.css_first('[data-profile-preview="clinician_affiliation_id"]')
    assert wrap is not None, "no practice-profile preview container on the opening form"
    card = tree.css_first(f'div[data-preview-for="{aff.id}"]')
    assert card is not None, "no preview card for the affiliation"
    # The default (first) affiliation's card is visible without JS.
    assert "hidden" not in card.attributes, "first preview card should be visible"
    # Profile rows come from the shared affiliation_facts macro.
    assert card.css_first('div[data-fact="services"]') is not None
    assert "Psychotherapy" in card.text()
    assert "Sliding scale" in card.text()
    assert "https://acme.example.com" in card.text()


async def test_intake_create_form_renders_program_profile_preview(
    authenticated_client: AsyncClient,
    db_test_session_manager: async_sessionmaker[AsyncSession],
    logged_in_user,
):
    """The intake create form shows a read-only preview of the selected
    program's steady-state profile via the shared `program_facts` macro.
    Requires a verified org rep who owns a program (the
    `check_program_intake` gate)."""
    org = make_organization_row(owner_id=logged_in_user.id, name="Acme Health")
    rep = OrgRepresentation(
        user_id=logged_in_user.id,
        org_id=org.id,
        role="coordinator",
        authority_method="admin_review",
        authority_status="verified",
    )
    program = make_program(
        owner_id=logged_in_user.id,
        org_id=org.id,
        services=["group_therapy"],
        website="https://riseiop.example.com",
    )
    program.organization = org
    async with db_test_session_manager() as session:
        async with session.begin():
            session.add(org)
            session.add(rep)
            session.add(program)

    response = await authenticated_client.get("/posts/form?kind=program_intake")
    assert response.status_code == 200
    tree = HTMLParser(response.text)

    wrap = tree.css_first('[data-profile-preview="program_id"]')
    assert wrap is not None, "no program-profile preview container on the intake form"
    card = tree.css_first(f'div[data-preview-for="{program.id}"]')
    assert card is not None, "no preview card for the program"
    assert "hidden" not in card.attributes, "first preview card should be visible"
    assert card.css_first('div[data-fact="services"]') is not None
    assert "Group therapy" in card.text()
    assert "https://riseiop.example.com" in card.text()


# --- Anonymization gate (can_act_as_provider) ---------------------------------


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
    Create CTA — `can_act_as_provider` is the single gate for posting."""
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


async def test_detail_hides_message_form_and_shows_cta_for_unverified(
    authenticated_client: AsyncClient,
    db_test_session_manager: async_sessionmaker[AsyncSession],
    logged_in_user,
):
    """Unverified users see a locked Message CTA (no form, no contact
    info) on post detail — the inline form is not rendered, and the
    poster's email address is not sent to the browser. Replaces the
    prior `mailto:`-button assertion: the same `can_act_as_provider`
    gate now hides the form instead of disabling a button."""
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
    assert author.email not in response.text
    tree = HTMLParser(response.text)
    assert tree.css_first(f"form[hx-post='/posts/{post.id}/message']") is None
    assert "Message" in response.text


async def test_detail_shows_message_form_for_verified(
    authenticated_client: AsyncClient,
    db_test_session_manager: async_sessionmaker[AsyncSession],
    logged_in_user,
):
    """Verified users (Claim A active) see the inline message form on
    the post detail page — POSTs to `/posts/{id}/message`, which
    dispatches the transactional email server-side. The poster's raw
    email address is never sent to the browser; the form route
    resolves the recipient from the post row."""
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
    assert author_email not in response.text
    tree = HTMLParser(response.text)
    form = tree.css_first(f"form[hx-post='/posts/{post.id}/message']")
    assert form is not None
    assert form.css_first("textarea[name='body']") is not None


async def test_detail_redacts_identity_rows_as_locked_placeholders_for_unverified(
    authenticated_client: AsyncClient,
    db_test_session_manager: async_sessionmaker[AsyncSession],
    logged_in_user,
):
    """A viewer who can't read the full feed sees the provider identity
    and address rows on post detail as `locked_field` / `locked_name`
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

    # The rows still render (the viewer knows the detail exists). The
    # provider row carries the withheld clinician + org behind
    # `locked_name`; the address carries a `locked_field`.
    for fact_key in ("provider", "address"):
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


async def test_opening_detail_splits_post_facts_from_practice_profile_card(
    authenticated_client: AsyncClient,
    db_test_session_manager: async_sessionmaker[AsyncSession],
    logged_in_user,
):
    """Opening detail renders the post's own facts (schedule notes) in
    the top facts block and the steady-state practice profile inside the
    `practice-profile` owner-context card — profile rows (services,
    availability, insurance, website) live in the card, not the flat
    grid, so it's structurally obvious which page edits them."""
    # A verified viewer so the provider identity links render un-redacted.
    viewer_clinician = make_clinician_with_org(
        owner_id=logged_in_user.id, npi="1234567890"
    )
    viewer_clinician.npi_match_status = "matched"
    viewer_clinician.clinician_verified = True
    author = create_test_user(username=f"author-{uuid.uuid4()}")
    clinician = make_clinician_with_org(owner_id=author.id, practice_name="Acme Health")
    clinician.id = clinician.id or uuid.uuid4()
    aff = clinician.primary_clinician_affiliation
    aff.services = ["psychotherapy"]
    aff.sliding_scale = True
    aff.website = "https://acme.example.com"
    aff.referral_instructions = "Email intake@acme.example.com."
    post = _opening_post(owner_id=author.id, clinician=clinician)
    post.opening_detail.schedule_text = "Mornings only"
    async with db_test_session_manager() as session:
        async with session.begin():
            session.add(viewer_clinician)
            session.add(author)
            session.add(post)

    response = await authenticated_client.get(f"/posts/{post.id}")
    assert response.status_code == 200
    tree = HTMLParser(response.text)

    card = tree.css_first('article[data-row-id="provider-profile"]')
    assert card is not None, "owner-context card should render"
    # The provider identity row carries the clinician (linked) followed
    # by the org (linked) — the shared `provider_ref` denotation.
    provider_dd = card.css_first('div[data-fact="provider"] dd')
    assert provider_dd is not None, "provider identity row should render"
    assert (
        provider_dd.css_first(f"a[href='/clinicians/{clinician.id}']") is not None
    ), "clinician name should link to the clinician detail page"
    assert (
        provider_dd.css_first(f"a[href='/organizations/{clinician.org.id}']")
        is not None
    ), "org name should link to the organization detail page"
    # Profile rows live inside the card...
    for fact_key in ("services", "insurance", "website", "referral_instructions"):
        assert (
            card.css_first(f'div[data-fact="{fact_key}"]') is not None
        ), f"{fact_key} should render inside the provider-profile card"
    assert "Sliding scale" in card.text()
    # ...post-own facts live outside it, in the top facts block.
    row = tree.css_first('div[data-fact="schedule_notes"]')
    assert row is not None, "schedule_notes should render on the detail page"


async def test_intake_detail_renders_program_profile_card(
    authenticated_client: AsyncClient,
    db_test_session_manager: async_sessionmaker[AsyncSession],
    logged_in_user,
):
    """Intake detail renders the program's steady-state profile inside
    the `provider-profile` owner-context card via `program_facts`, with
    the provider identity row linking the program and its org."""
    # A verified viewer so the provider identity links render un-redacted.
    viewer_clinician = make_clinician_with_org(
        owner_id=logged_in_user.id, npi="1234567890"
    )
    viewer_clinician.npi_match_status = "matched"
    viewer_clinician.clinician_verified = True
    author = create_test_user(username=f"author-{uuid.uuid4()}")
    org = make_organization_row(owner_id=author.id, name="Acme Health")
    program = make_program(
        owner_id=author.id,
        org_id=org.id,
        services=["group_therapy"],
        website="https://riseiop.example.com",
    )
    program.organization = org
    post = _intake_post(owner_id=author.id, org_id=org.id, program=program)
    async with db_test_session_manager() as session:
        async with session.begin():
            session.add(viewer_clinician)
            session.add(author)
            session.add(post)

    response = await authenticated_client.get(f"/posts/{post.id}")
    assert response.status_code == 200
    tree = HTMLParser(response.text)

    card = tree.css_first('article[data-row-id="provider-profile"]')
    assert card is not None, "program owner-context card should render"
    provider_dd = card.css_first('div[data-fact="provider"] dd')
    assert provider_dd is not None, "provider identity row should render"
    assert (
        provider_dd.css_first(f"a[href='/programs/{program.id}']") is not None
    ), "program name should link to the program detail page"
    assert (
        provider_dd.css_first(f"a[href='/organizations/{org.id}']") is not None
    ), "org name should link to the organization detail page"
    for fact_key in ("services", "website"):
        assert (
            card.css_first(f'div[data-fact="{fact_key}"]') is not None
        ), f"{fact_key} should render inside the provider-profile card"


# --- POST /posts/{id}/message (in-app contact form) --------------------------


async def test_message_send_unverified_user_is_forbidden(
    authenticated_client: AsyncClient,
    db_test_session_manager: async_sessionmaker[AsyncSession],
    logged_in_user,
    monkeypatch,
):
    """A claimless viewer can't see the form (existing visibility gate),
    so the route must also reject the request server-side. Mirrors the
    `can_act_as_provider` gate that hid the prior `mailto:` button."""
    send_mock = pytest.importorskip("unittest.mock").AsyncMock()
    monkeypatch.setattr("src.domain.routes.posts.send_post_message_email", send_mock)

    author = create_test_user(username=f"author-{uuid.uuid4()}")
    post = _referral_post(owner_id=author.id)
    async with db_test_session_manager() as session:
        async with session.begin():
            session.add(author)
            session.add(post)

    response = await authenticated_client.post(
        f"/posts/{post.id}/message", json={"body": "hello"}
    )
    assert response.status_code == 403
    assert send_mock.call_count == 0


async def test_message_send_verified_user_dispatches_email(
    authenticated_client: AsyncClient,
    db_test_session_manager: async_sessionmaker[AsyncSession],
    logged_in_user,
    monkeypatch,
):
    """Verified-network viewer (`can_act_as_provider=True`) reaches the
    handler and we hand the post + sender + body to the domain email
    wrapper. Tests for `Reply-To`, recipient, and link shape live in
    `src/domain/logic/posts/test_emails.py` — this test only pins the
    handoff."""
    from unittest.mock import AsyncMock

    send_mock = AsyncMock()
    monkeypatch.setattr("src.domain.routes.posts.send_post_message_email", send_mock)

    clinician = make_clinician_with_org(owner_id=logged_in_user.id, npi="1234567890")
    clinician.npi_match_status = "matched"
    clinician.clinician_verified = True
    author = create_test_user(username=f"author-{uuid.uuid4()}")
    post = _referral_post(owner_id=author.id)
    async with db_test_session_manager() as session:
        async with session.begin():
            session.add(clinician)
            session.add(author)
            session.add(post)

    response = await authenticated_client.post(
        f"/posts/{post.id}/message",
        json={"body": "I have a referral that matches"},
    )
    assert response.status_code == 200
    assert "Message sent" in response.text
    assert send_mock.call_count == 1
    kwargs = send_mock.call_args.kwargs
    assert kwargs["post"].id == post.id
    assert kwargs["sender"].id == logged_in_user.id
    assert kwargs["body"] == "I have a referral that matches"


async def test_message_send_404_when_post_missing(
    authenticated_client: AsyncClient,
    db_test_session_manager: async_sessionmaker[AsyncSession],
    logged_in_user,
    monkeypatch,
):
    """Unknown post id returns 404 — even for an authorized sender.
    The `can_act_as_provider` check fires first, so the user must clear
    that gate before the missing-post path is reachable."""
    from unittest.mock import AsyncMock

    send_mock = AsyncMock()
    monkeypatch.setattr("src.domain.routes.posts.send_post_message_email", send_mock)

    clinician = make_clinician_with_org(owner_id=logged_in_user.id, npi="1234567890")
    clinician.npi_match_status = "matched"
    clinician.clinician_verified = True
    async with db_test_session_manager() as session:
        async with session.begin():
            session.add(clinician)

    response = await authenticated_client.post(
        f"/posts/{uuid.uuid4()}/message", json={"body": "hi"}
    )
    assert response.status_code == 404
    assert send_mock.call_count == 0


async def test_message_send_rejects_blank_body(
    authenticated_client: AsyncClient,
    db_test_session_manager: async_sessionmaker[AsyncSession],
    logged_in_user,
    monkeypatch,
):
    """Empty / whitespace-only bodies are 422 — no point shipping a
    blank email."""
    from unittest.mock import AsyncMock

    send_mock = AsyncMock()
    monkeypatch.setattr("src.domain.routes.posts.send_post_message_email", send_mock)

    clinician = make_clinician_with_org(owner_id=logged_in_user.id, npi="1234567890")
    clinician.npi_match_status = "matched"
    clinician.clinician_verified = True
    author = create_test_user(username=f"author-{uuid.uuid4()}")
    post = _referral_post(owner_id=author.id)
    async with db_test_session_manager() as session:
        async with session.begin():
            session.add(clinician)
            session.add(author)
            session.add(post)

    response = await authenticated_client.post(
        f"/posts/{post.id}/message", json={"body": "   "}
    )
    assert response.status_code == 422
    assert send_mock.call_count == 0
