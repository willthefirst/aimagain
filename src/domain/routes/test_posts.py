import uuid

import pytest
from httpx import AsyncClient
from selectolax.parser import HTMLParser
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from src.domain.models import (
    OpeningDetail,
    Post,
    Program,
    Provider,
    ReferralDetail,
    User,
)
from src.framework.audit.repository import AuditRepository
from tests.helpers import (
    create_test_user,
    make_opening_detail,
    make_organization_row,
    make_program,
    make_provider_with_org,
    make_referral_detail,
    opening_payload,
    program_availability_payload,
    promote_to_admin,
    referral_payload,
)

# Mark all tests in this module as async
pytestmark = pytest.mark.asyncio


def _referral_post(*, description: str, owner_id, **overrides) -> Post:
    """Build a `kind='referral'` Post + its spec-compliant detail.
    Per-field overrides flow through to the detail row."""
    post = Post(kind="referral", owner_id=owner_id)
    post.referral_detail = make_referral_detail(description=description, **overrides)
    return post


def _opening_post(
    *, practice_name: str, owner_id, provider: Provider | None = None, **overrides
) -> Post:
    """Build a `kind='opening'` Post + its spec-compliant
    detail + the linked Provider profile. The Provider is auto-created
    with the given `practice_name` unless one is passed explicitly.
    SQLAlchemy save-update cascade persists the Provider when the Post
    is added to a session — callers do `session.add(post)` and the
    Provider goes in too with the right FK order."""
    if provider is None:
        provider = make_provider_with_org(
            owner_id=owner_id, practice_name=practice_name
        )
    if provider.id is None:
        provider.id = uuid.uuid4()
    post = Post(kind="opening", owner_id=owner_id)
    detail = make_opening_detail(provider_id=provider.id, **overrides)
    # Wire the Provider through the relationship so save-update cascade
    # persists it when the Post is added to a session.
    detail.provider = provider
    post.opening_detail = detail
    return post


def _make_test_post(owner: User, *, description: str | None = None) -> Post:
    return _referral_post(
        description=description or f"post-{uuid.uuid4()}",
        owner_id=owner.id,
    )


# --- Listing -------------------------------------------------------------


async def test_list_referral_item_shape(
    authenticated_client: AsyncClient,
    db_test_session_manager: async_sessionmaker[AsyncSession],
    logged_in_user: User,
):
    """A `referral` renders as a card `<article>` in
    `#posts-list`. The header reads "<Age noun> <gender> (<range>)"
    (e.g. "Adolescent male (14–18)") and links to the detail page;
    state is demoted to the demographics column as a `📍 City, ST`
    location chunk. The body is a
    three-column grid: services with icons (left), labeled facts
    `<dl>` (middle), and referring-provider attribution (right). The
    description never appears in the row — it lives on the detail
    page. The kind is signaled by the `data-kind` attribute (which
    the CSS turns into a 4px left-edge color)."""
    author = create_test_user(username=f"author-{uuid.uuid4()}")
    description = f"item-{uuid.uuid4()}"
    post = _referral_post(
        description=description,
        owner_id=author.id,
        location_city="Seattle",
        location_state="WA",
        location_in_person="yes",
        location_virtual="yes",
        age_groups=["adolescents_14_18", "adults_25_64"],
        gender="male",
        languages=["en", "es"],
        network_preference="in_network_required",
        insurance_carrier="cigna",
        services=["psychotherapy", "medication_management"],
    )
    async with db_test_session_manager() as session:
        async with session.begin():
            session.add(author)
            session.add(post)

    response = await authenticated_client.get("/posts")
    assert response.status_code == 200
    tree = HTMLParser(response.text)
    item = tree.css_first("#posts-list > article")
    assert item is not None
    assert item.attributes.get("data-kind") == "referral"

    # Header line: link text is the age + gender combo (no state —
    # state moved to the demographics column for CR). Modality chips
    # (icon + short label) sit next to the headline.
    header_link = item.css_first("header.entity-header a")
    assert header_link is not None
    assert header_link.attributes.get("href") == f"/posts/{post.id}"
    # `age_groups[0]` = adolescents_14_18 + gender=male.
    assert header_link.text(strip=True) == "Adolescent male (14–18)"
    modality_chips = [
        chip.text(strip=True)
        for chip in item.css("header.entity-header > .post-modality")
    ]
    assert modality_chips == ["Virtual", "In-person"]

    # No text kind-chip anywhere in the listing row.
    assert item.css_first("[data-kind-chip]") is None

    # Description is not in the row text — it stays on the detail page.
    assert description not in item.text()

    # Services column lists each service with an inline icon and label.
    service_items = item.css("section.entity-icon-list > ul > li")
    service_labels = [li.text(strip=True) for li in service_items]
    assert "Psychotherapy" in service_labels
    assert "Medication management" in service_labels
    # Each service item carries a Lucide `<i>` icon (decorative).
    assert all(li.css_first("i[class^=icon-]") is not None for li in service_items)

    # Demographics column: location chunk (City, ST) + languages +
    # insurance posture. CR's age + gender live in the headline, not
    # here.
    facts_text = item.css_first("section.entity-facts").text()
    location = item.css_first("section.entity-facts dl > div.entity-location")
    assert location is not None
    assert location.css_first("dt > i[class^=icon-]") is not None
    assert location.css_first("dd").text(strip=True) == "Seattle, WA"
    assert "In-network" in facts_text
    assert "English, Spanish" in facts_text
    # Age + gender labels do not appear in the demographics column for CR.
    assert "Adolescent" not in facts_text
    assert "Adult" not in facts_text

    # Contact band lives in `<footer class="entity-footer">` — just the
    # Email CTA. The username + practice name no longer render in the
    # footer; the headline already identifies who you're contacting.
    footer = item.css_first("footer.entity-footer")
    assert author.username not in footer.text()
    mailto = footer.css_first("a")
    assert mailto is not None
    assert mailto.attributes.get("href") == f"mailto:{author.email}"
    assert mailto.attributes.get("target") == "_blank"
    assert mailto.text(strip=True) == "Email"


async def test_list_referral_header_is_age_gender_combo(
    authenticated_client: AsyncClient,
    db_test_session_manager: async_sessionmaker[AsyncSession],
    logged_in_user: User,
):
    """The `referral` card header reads `<Age noun> [<gender>]
    (<range>)` — the age + gender combo is the identity for a CR (CR
    posts have no client name). Gender values that don't slot in
    (`prefer_not_to_say`, `gender_diverse`) drop the gender word, and
    the headline becomes `<Age noun> (<range>)`. State lives in the
    demographics column (a location chunk), not in the header."""
    author = create_test_user(username=f"author-{uuid.uuid4()}")
    post = _referral_post(
        description="",
        owner_id=author.id,
        location_city="Boise",
        location_state="ID",
        age_groups=["young_adults_19_24"],
        gender="female",
    )
    async with db_test_session_manager() as session:
        async with session.begin():
            session.add(author)
            session.add(post)

    response = await authenticated_client.get("/posts")
    assert response.status_code == 200
    tree = HTMLParser(response.text)
    item = tree.css_first("#posts-list > article")
    lead = item.css_first("header.entity-header a")
    assert lead is not None
    assert lead.text(strip=True) == "Young adult female (19–24)"
    # State is *not* in the header anymore.
    assert "ID" not in item.css_first("header.entity-header").text()
    # ...but it does appear in the demographics column's location chunk.
    location = item.css_first("section.entity-facts dl > div.entity-location")
    assert location is not None
    assert location.css_first("dd").text(strip=True) == "Boise, ID"


async def test_list_opening_item_shape(
    authenticated_client: AsyncClient,
    db_test_session_manager: async_sessionmaker[AsyncSession],
    logged_in_user: User,
):
    """An `opening` card header is just the practice name —
    location surfaces via the icon-only `entity-location` row in the
    demographics column (same treatment referral cards use), not in
    the header line. Kind is signaled by the `data-kind` left-edge
    color, not a text chip. Insurance posture is rendered in the
    demographics column, derived from the linked provider's
    `in_network_carriers` (non-empty wins the badge)."""
    author = create_test_user(username=f"author-{uuid.uuid4()}")
    practice_name = f"Practice-{uuid.uuid4()}"
    post = _opening_post(
        practice_name=practice_name,
        owner_id=author.id,
        provider=make_provider_with_org(
            owner_id=author.id,
            practice_name=practice_name,
            location_city="Portland",
            location_state="OR",
            in_person_sessions="yes",
            virtual_sessions="no",
            in_network_carriers=["aetna"],
            accepts_out_of_network=False,
            sliding_scale=True,
        ),
    )
    async with db_test_session_manager() as session:
        async with session.begin():
            session.add(author)
            session.add(post.opening_detail.provider)
            session.add(post)

    response = await authenticated_client.get("/posts")
    assert response.status_code == 200
    tree = HTMLParser(response.text)
    item = tree.css_first("#posts-list > article")
    assert item is not None
    assert item.attributes.get("data-kind") == "opening"

    # No text kind-chip in the listing row.
    assert item.css_first("[data-kind-chip]") is None

    # Header link text: just the practice name (location moves to the
    # demographics column via `entity-location`). The in-person
    # posture renders as a `<span.post-modality>` chip (icon + label)
    # next to the link; virtual=no, so no virtual chip.
    lead = item.css_first("header.entity-header a")
    assert lead is not None
    assert lead.text(strip=True) == practice_name
    location_row = item.css_first("section.entity-facts dl > div.entity-location")
    assert location_row is not None
    assert "Portland, OR" in location_row.text()
    modality_chips = [
        chip.text(strip=True)
        for chip in item.css("header.entity-header > .post-modality")
    ]
    assert modality_chips == ["In-person"]

    # Demographics column shows the posture; non-empty in_network_carriers
    # wins the priority even though sliding_scale is also set.
    facts_text = item.css_first("section.entity-facts").text()
    assert "In-network" in facts_text

    # Contact band lives in `<footer class="entity-footer">` — just the
    # Email CTA. Practice name is in the headline, not duplicated here.
    footer = item.css_first("footer.entity-footer")
    footer_text = footer.text()
    assert practice_name not in footer_text
    assert author.username not in footer_text
    mailto = footer.css_first("a")
    assert mailto is not None
    assert mailto.attributes.get("href") == f"mailto:{author.email}"


async def test_list_services_column_heading_is_kind_aware(
    authenticated_client: AsyncClient,
    db_test_session_manager: async_sessionmaker[AsyncSession],
    logged_in_user: User,
):
    """The left-column heading reads "Seeking" for `referral`
    and "Providing" for `opening`. The generic "Services"
    label carried opposite meanings on the two kinds (what the post is
    asking for vs. what the post is offering); the verb forms reuse
    the chip vocabulary that already names the left-edge colors."""
    author = create_test_user(username=f"author-{uuid.uuid4()}")
    cr_post = _referral_post(
        description="cr",
        owner_id=author.id,
        services=["psychotherapy"],
    )
    pa_practice = f"Practice-{uuid.uuid4()}"
    pa_post = _opening_post(
        practice_name=pa_practice,
        owner_id=author.id,
        services=["psychotherapy"],
        settings=["outpatient"],
    )
    async with db_test_session_manager() as session:
        async with session.begin():
            session.add(author)
            session.add(pa_post.opening_detail.provider)
            session.add(cr_post)
            session.add(pa_post)

    response = await authenticated_client.get("/posts")
    assert response.status_code == 200
    tree = HTMLParser(response.text)
    cards = {
        a.attributes.get("data-row-id"): a for a in tree.css("#posts-list > article")
    }
    cr_heading = cards[str(cr_post.id)].css_first("section.entity-icon-list h4")
    pa_heading = cards[str(pa_post.id)].css_first("section.entity-icon-list h4")
    assert cr_heading is not None and cr_heading.text(strip=True) == "Seeking"
    assert pa_heading is not None and pa_heading.text(strip=True) == "Providing"


async def test_list_services_priority_sorted_psychotherapy_and_medmgmt_first(
    authenticated_client: AsyncClient,
    db_test_session_manager: async_sessionmaker[AsyncSession],
    logged_in_user: User,
):
    """`psychotherapy` and `medication_management` lead the services
    list regardless of storage order — they're the two services a
    reader is overwhelmingly likeliest to be scanning for, so they get
    top billing. The remaining services follow in
    `REFERRAL_SERVICES` declaration order."""
    author = create_test_user(username=f"author-{uuid.uuid4()}")
    # Storage order puts the priority items last; the template must
    # re-order so they appear first regardless of input order.
    post = _referral_post(
        description="cr",
        owner_id=author.id,
        services=[
            "evaluation",
            "case_management",
            "medication_management",
            "psychotherapy",
        ],
    )
    async with db_test_session_manager() as session:
        async with session.begin():
            session.add(author)
            session.add(post)

    response = await authenticated_client.get("/posts")
    assert response.status_code == 200
    tree = HTMLParser(response.text)
    items = tree.css("#posts-list > article section.entity-icon-list > ul > li")
    labels = [li.text(strip=True) for li in items]
    assert labels[:2] == ["Psychotherapy", "Medication management"]
    # The non-priority items keep enum declaration order.
    assert labels[2:] == ["Evaluation", "Case management"]


async def test_list_demographics_diverge_by_kind(
    authenticated_client: AsyncClient,
    db_test_session_manager: async_sessionmaker[AsyncSession],
    logged_in_user: User,
):
    """CR and PA cards carry different demographics shapes: CR's center
    column leads with a location chunk (icon `<dt>` + `City, ST`) and
    omits age + gender entirely (both live in the headline). PA's
    center column carries the "Ages" cohort chunk (and a "Genders"
    chunk when set), no location row."""
    author = create_test_user(username=f"author-{uuid.uuid4()}")
    cr_post = _referral_post(
        description="cr",
        owner_id=author.id,
        age_groups=["adolescents_14_18"],
    )
    pa_practice = f"Practice-{uuid.uuid4()}"
    pa_post = _opening_post(
        practice_name=pa_practice,
        owner_id=author.id,
        age_groups=["adolescents_14_18", "adults_25_64"],
    )
    async with db_test_session_manager() as session:
        async with session.begin():
            session.add(author)
            session.add(pa_post.opening_detail.provider)
            session.add(cr_post)
            session.add(pa_post)

    response = await authenticated_client.get("/posts")
    assert response.status_code == 200
    tree = HTMLParser(response.text)
    cards = {
        a.attributes.get("data-row-id"): a for a in tree.css("#posts-list > article")
    }
    cr_card = cards[str(cr_post.id)]
    pa_card = cards[str(pa_post.id)]
    cr_labels = [
        dt.text(strip=True) for dt in cr_card.css("section.entity-facts dl dt")
    ]
    pa_labels = [
        dt.text(strip=True) for dt in pa_card.css("section.entity-facts dl dt")
    ]
    # CR omits Age + Gender (they're in the headline) and adds a
    # location chunk whose `<dt>` is icon-only (empty text).
    assert "Age" not in cr_labels and "Gender" not in cr_labels
    assert (
        cr_card.css_first("section.entity-facts dl > div.entity-location") is not None
    )
    # PA carries the cohort chunk AND the icon-only location row
    # (same shape as CR's location chunk) — both kinds locate their
    # location in the demographics column for visual consistency.
    assert "Ages" in pa_labels and "Age" not in pa_labels
    assert (
        pa_card.css_first("section.entity-facts dl > div.entity-location") is not None
    )


async def test_list_pa_footer_carries_email_cta_only(
    authenticated_client: AsyncClient,
    db_test_session_manager: async_sessionmaker[AsyncSession],
    logged_in_user: User,
):
    """For a `opening` card the footer band carries just
    the Email CTA — practice name is already in the headline, so the
    footer doesn't re-name the contact. The CTA is a Pico-styled
    `role="button"` anchor with the visible label "Email"; the raw
    address is in the `href` only."""
    author = create_test_user(username=f"author-{uuid.uuid4()}")
    practice_name = f"Practice-{uuid.uuid4()}"
    post = _opening_post(
        practice_name=practice_name,
        owner_id=author.id,
    )
    async with db_test_session_manager() as session:
        async with session.begin():
            session.add(author)
            session.add(post.opening_detail.provider)
            session.add(post)

    response = await authenticated_client.get("/posts")
    assert response.status_code == 200
    tree = HTMLParser(response.text)
    footer = tree.css_first("#posts-list > article footer.entity-footer")
    assert footer is not None
    text = footer.text()
    # Neither name renders in the footer — only the Email CTA.
    assert practice_name not in text
    assert author.username not in text
    mailto = footer.css_first("a")
    assert mailto is not None
    assert mailto.attributes.get("href") == f"mailto:{author.email}"
    assert mailto.attributes.get("target") == "_blank"
    assert "noopener" in (mailto.attributes.get("rel") or "")
    # CTA label is the verb "Email", not the raw address — the
    # address is in the href, not the text content.
    assert mailto.attributes.get("role") == "button"
    assert mailto.text(strip=True) == "Email"
    assert author.email not in mailto.text()


async def test_list_does_not_render_description_prose(
    authenticated_client: AsyncClient,
    db_test_session_manager: async_sessionmaker[AsyncSession],
    logged_in_user: User,
):
    """The description never appears in the listing row — it lives on
    the detail page where the reader has committed to reading. The
    card header is the kind label + state (CR) or the practice name +
    state (PA); the body columns are services / labeled facts /
    contact. A regression that re-introduced the description into the
    row would surface this string in the DOM."""
    author = create_test_user(username=f"author-{uuid.uuid4()}")
    description = (
        "Looking for a long-term outpatient therapist for a 17-year-old "
        "(she/her) with complex PTSD. Aetna in-network preferred."
    )
    post = _referral_post(description=description, owner_id=author.id)
    async with db_test_session_manager() as session:
        async with session.begin():
            session.add(author)
            session.add(post)

    response = await authenticated_client.get("/posts")
    assert response.status_code == 200
    tree = HTMLParser(response.text)
    item = tree.css_first("#posts-list > article")
    assert item is not None
    # No fragment of the description appears anywhere in the row.
    assert "complex PTSD" not in item.text()
    assert "Aetna" not in item.text()


async def test_list_meta_is_a_dl_of_labeled_key_value_chunks(
    authenticated_client: AsyncClient,
    db_test_session_manager: async_sessionmaker[AsyncSession],
    logged_in_user: User,
):
    """Each metadata fact is a `<dt>`/`<dd>` pair (wrapped in a
    `<div>`, the HTML5 grouping construct inside `<dl>`) in the
    demographics column (`section.entity-facts`). For CR the first
    chunk is a location row: an icon-only `<dt>` (`aria-label`
    carries the meaning) + `City, ST` value. Other chunks have a
    visible text `<dt>` label (e.g. "Insurance"). Modality lives in
    the header, not here.

    The author's username appears in the `Contact` column (the
    third grid column) — a deliberate change from the earlier
    Craigslist-style row where the author was hidden. The header
    link is the only `<a>` in the card; the contact text is a plain
    `<p>` with the bare username (no `@` prefix), matching how PA
    renders the practice name."""
    author = create_test_user(username=f"author-{uuid.uuid4()}")
    post = _referral_post(
        description="meta-shape",
        owner_id=author.id,
        location_city="Seattle",
        location_state="WA",
        location_in_person="yes",
        location_virtual="no",
        age_groups=["adolescents_14_18"],
        languages=["en"],
        network_preference="in_network_required",
    )
    async with db_test_session_manager() as session:
        async with session.begin():
            session.add(author)
            session.add(post)

    response = await authenticated_client.get("/posts")
    assert response.status_code == 200
    tree = HTMLParser(response.text)
    item = tree.css_first("#posts-list > article")
    assert item is not None

    # Demographics `<dl>` chunks for CR. English-only languages are
    # dropped (default); insurance posture renders; age + gender are
    # absent (they're in the headline).
    meta_chunks = item.css("section.entity-facts dl > div")
    # Location + Insurance = 2 chunks.
    assert len(meta_chunks) == 2
    labels = [chunk.css_first("dt").text(strip=True) for chunk in meta_chunks]
    # First `<dt>` is icon-only (no visible text); second is "Insurance".
    assert labels == ["", "Insurance"]
    assert meta_chunks[0].attributes.get("class") == "entity-location"
    assert meta_chunks[0].css_first("dt").attributes.get("aria-label") == "Location"
    assert meta_chunks[0].css_first("dt > i[class^=icon-]") is not None
    values = [chunk.css_first("dd").text(strip=True) for chunk in meta_chunks]
    assert values == ["Seattle, WA", "In-network"]

    # Header carries the age headline + an "In-person" modality chip
    # (virtual=no). The fixture's gender default is `prefer_not_to_say`,
    # so the gender word drops out. State lives in the location chunk
    # of the demographics column, not in the header.
    header_text = item.css_first("header.entity-header").text()
    assert "Adolescent (14–18)" in header_text
    assert "WA" not in header_text
    modality_chips = [
        chip.text(strip=True)
        for chip in item.css("header.entity-header > .post-modality")
    ]
    assert modality_chips == ["In-person"]

    # Two `<a>`s per card: the header link to the detail page and
    # the Email CTA in the footer. The footer carries only the CTA;
    # the name (username for CR, practice for PA) lives in the
    # headline, not duplicated here.
    header_link = item.css_first("header.entity-header a")
    assert header_link is not None
    assert header_link.attributes.get("href") == f"/posts/{post.id}"
    footer = item.css_first("footer.entity-footer")
    assert author.username not in footer.text()
    mailto = footer.css_first("a")
    assert mailto is not None
    assert mailto.attributes.get("href") == f"mailto:{author.email}"
    assert mailto.attributes.get("target") == "_blank"
    assert "noopener" in (mailto.attributes.get("rel") or "")


async def test_list_renders_readable_date_format(
    authenticated_client: AsyncClient,
    db_test_session_manager: async_sessionmaker[AsyncSession],
    logged_in_user: User,
):
    """The date renders Craigslist-style (`May 15`) via the
    `format_post_date` Jinja filter — *not* the raw ISO `YYYY-MM-DD`
    that `post.created_at.date()` produced before. The date sits in
    the card header's right-aligned `<small>`."""
    from datetime import datetime, timezone

    author = create_test_user(username=f"author-{uuid.uuid4()}")
    post = _referral_post(description="d", owner_id=author.id)
    # Force a known timestamp so the format assertion is stable.
    post.created_at = datetime(2025, 5, 15, 14, 30, tzinfo=timezone.utc)
    async with db_test_session_manager() as session:
        async with session.begin():
            session.add(author)
            session.add(post)

    response = await authenticated_client.get("/posts")
    assert response.status_code == 200
    tree = HTMLParser(response.text)
    item = tree.css_first("#posts-list > article")
    assert item is not None
    date_cell = item.css_first("header.entity-header small")
    assert date_cell is not None
    rendered = date_cell.text(strip=True)
    # `May 15` for current-year posts; `May 15, 2025` once we cross a
    # year boundary. Either is acceptable — both prove the raw ISO
    # `2025-05-15` is gone.
    assert rendered in {"May 15", "May 15, 2025"}


async def test_detail_renders_breadcrumb(
    authenticated_client: AsyncClient,
    db_test_session_manager: async_sessionmaker[AsyncSession],
    logged_in_user: User,
):
    """Post detail renders the Pico breadcrumb (`Posts › Post`) above
    the page toolbar. The trailing `<li>` is marked `aria-current="page"`
    so screen readers identify it as the current page; visual styling
    comes from Pico's `nav[aria-label="breadcrumb"]` defaults."""
    post = _referral_post(description="crumb-x", owner_id=logged_in_user.id)
    async with db_test_session_manager() as session:
        async with session.begin():
            session.add(post)
        await session.refresh(post)
        post_id = post.id

    response = await authenticated_client.get(f"/posts/{post_id}")
    assert response.status_code == 200
    tree = HTMLParser(response.text)
    crumb = tree.css_first('nav[aria-label="breadcrumb"]')
    assert crumb is not None
    items = crumb.css("ul > li")
    assert [li.text(strip=True) for li in items] == ["Posts", "Post"]
    parent_link = items[0].css_first("a")
    assert parent_link is not None
    assert parent_link.attributes.get("href") == "/posts"
    assert "aria-current" in items[-1].attributes
    assert items[-1].attributes.get("aria-current") == "page"
    # Current page has no link inside — it's the leaf.
    assert items[-1].css_first("a") is None


async def test_detail_omits_kind_chip_and_meta_line(
    authenticated_client: AsyncClient,
    db_test_session_manager: async_sessionmaker[AsyncSession],
    logged_in_user: User,
):
    """The detail page no longer renders a `data-kind-chip` "Seeking by
    <user> · <date>" meta line — the breadcrumb above and the kind-
    colored left edge already convey kind + collection context, so
    repeating it as a chip in the card body is redundant."""
    cr_post = _referral_post(
        description="cr",
        owner_id=logged_in_user.id,
        location_city="Boise",
        location_state="ID",
    )
    pa_post = _opening_post(
        practice_name=f"Practice-{uuid.uuid4()}", owner_id=logged_in_user.id
    )
    async with db_test_session_manager() as session:
        async with session.begin():
            session.add(pa_post.opening_detail.provider)
            session.add(cr_post)
            session.add(pa_post)
        await session.refresh(cr_post)
        await session.refresh(pa_post)

    for post_id in (cr_post.id, pa_post.id):
        response = await authenticated_client.get(f"/posts/{post_id}")
        assert response.status_code == 200
        tree = HTMLParser(response.text)
        assert tree.css_first("article [data-kind-chip]") is None
        assert tree.css_first("article .entity-meta") is None


async def test_detail_age_label_is_singular_for_cr_and_appears_once(
    authenticated_client: AsyncClient,
    db_test_session_manager: async_sessionmaker[AsyncSession],
    logged_in_user: User,
):
    """A `referral` post represents one seeker, so the
    demographics row labels their age cohort as ``Age`` (singular) and
    renders the row exactly once. The duplicate row that existed pre-
    refactor (one from the location/age elif, one from a CR-specific
    expanded block) was a bug."""
    post = _referral_post(
        description="age-label",
        owner_id=logged_in_user.id,
        age_groups=["adults_25_64"],
    )
    async with db_test_session_manager() as session:
        async with session.begin():
            session.add(post)
        await session.refresh(post)
        post_id = post.id

    response = await authenticated_client.get(f"/posts/{post_id}")
    assert response.status_code == 200
    tree = HTMLParser(response.text)
    labels = [
        dt.text(strip=True) for dt in tree.css("article section.entity-facts dl dt")
    ]
    assert labels.count("Age") == 1
    assert "Ages" not in labels


async def test_detail_ages_label_is_plural_for_pa_and_appears_once(
    authenticated_client: AsyncClient,
    db_test_session_manager: async_sessionmaker[AsyncSession],
    logged_in_user: User,
):
    """An `opening` post advertises a cohort the practice
    accepts, so the demographics row labels it ``Ages`` (plural) and
    renders the row exactly once."""
    post = _opening_post(
        practice_name=f"Practice-{uuid.uuid4()}",
        owner_id=logged_in_user.id,
        age_groups=["adolescents_14_18", "adults_25_64"],
    )
    async with db_test_session_manager() as session:
        async with session.begin():
            session.add(post.opening_detail.provider)
            session.add(post)
        await session.refresh(post)
        post_id = post.id

    response = await authenticated_client.get(f"/posts/{post_id}")
    assert response.status_code == 200
    tree = HTMLParser(response.text)
    labels = [
        dt.text(strip=True) for dt in tree.css("article section.entity-facts dl dt")
    ]
    assert labels.count("Ages") == 1
    assert "Age" not in labels


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
    items = tree.css("#posts-list > article")
    assert len(items) == 1
    # The description doesn't appear in the listing row (lives on the
    # detail page); the card header link is what we look for.
    assert items[0].css_first("header.entity-header a") is not None
    assert "No posts found" not in tree.body.text()


async def test_list_posts_orders_newest_first(
    authenticated_client: AsyncClient,
    db_test_session_manager: async_sessionmaker[AsyncSession],
    logged_in_user: User,
):
    """GET /posts orders results by created_at DESC. Descriptions don't
    appear in the listing row, so the ordering check uses the row's
    `data-row-id` attribute (set to the post UUID by the macro)."""
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
    items = tree.css("#posts-list > article")
    assert len(items) == 2
    assert items[0].attributes.get("data-row-id") == str(newer.id)
    assert items[1].attributes.get("data-row-id") == str(older.id)


# --- Update (PATCH) ------------------------------------------------------


async def test_non_owner_cannot_patch_post(
    authenticated_client: AsyncClient,
    db_test_session_manager: async_sessionmaker[AsyncSession],
    logged_in_user: User,
):
    """A non-owner non-admin gets 403 and the post is not mutated."""
    other = create_test_user(username=f"other-{uuid.uuid4()}")
    post = _referral_post(description="orig", owner_id=other.id)
    async with db_test_session_manager() as session:
        async with session.begin():
            session.add(other)
            session.add(post)

    response = await authenticated_client.patch(
        f"/posts/{post.id}",
        data={"kind": "referral", "description": "hijack"},
    )
    assert response.status_code == 403

    async with db_test_session_manager() as session:
        result = await session.execute(select(Post).filter(Post.id == post.id))
        refreshed = result.scalars().first()
        assert refreshed.referral_detail.description == "orig"


async def test_admin_can_patch_anyone_post(
    authenticated_client: AsyncClient,
    db_test_session_manager: async_sessionmaker[AsyncSession],
    logged_in_user: User,
):
    await promote_to_admin(db_test_session_manager, logged_in_user.email)
    other = create_test_user(username=f"other-{uuid.uuid4()}")
    post = _referral_post(description="orig", owner_id=other.id)
    async with db_test_session_manager() as session:
        async with session.begin():
            session.add(other)
            session.add(post)

    response = await authenticated_client.patch(
        f"/posts/{post.id}",
        data={"kind": "referral", "description": "moderated"},
    )
    assert response.status_code == 200
    assert response.json()["description"] == "moderated"


# --- Chrome abstraction --------------------------------------------------


async def test_list_page_renders_single_segment_breadcrumb(
    authenticated_client: AsyncClient,
    logged_in_user: User,
):
    """Every page in the chrome contract carries a breadcrumb. List
    pages are the root of the resource hierarchy and render as a
    single segment (the resource label, no parent link, marked
    `aria-current="page"`). Detail and form pages extend that with
    `Resource › … › Current`. Pin the shape on `/posts` so the
    abstraction doesn't drift template-by-template."""
    response = await authenticated_client.get("/posts")
    assert response.status_code == 200
    tree = HTMLParser(response.text)
    items = tree.css('nav[aria-label="breadcrumb"] ul > li')
    assert [li.text(strip=True) for li in items] == ["Posts"]
    assert items[0].attributes.get("aria-current") == "page"
    assert items[0].css_first("a") is None


# --- Zone bar ------------------------------------------------------------


async def test_list_page_renders_create_post_button_in_toolbar_right(
    authenticated_client: AsyncClient,
    logged_in_user: User,
):
    """The /posts zone bar parks a `Create post` link on the right; it
    routes to `/posts/form` (no `?kind=`), which renders the kind picker.
    Before the zone bar existed, the kind picker was reachable only by
    typing the URL — pin the UI entry point so it doesn't regress."""
    response = await authenticated_client.get("/posts")
    assert response.status_code == 200
    tree = HTMLParser(response.text)
    link = tree.css_first('.toolbar .toolbar-right a[href="/posts/form"]')
    assert link is not None
    assert link.attributes.get("role") == "button"
    assert link.text().strip() == "Create post"


# --- Filter form ---------------------------------------------------------


async def test_list_page_toolbar_has_only_filter_link_and_actions(
    authenticated_client: AsyncClient,
    logged_in_user: User,
):
    """The toolbar carries exactly two zones: the filter link on the
    left, the page-action `<menu>` on the right. No segmented control
    and no sort form."""
    response = await authenticated_client.get("/posts")
    assert response.status_code == 200
    tree = HTMLParser(response.text)
    # Neither segmented nor sort form is rendered.
    assert tree.css_first("form.toolbar-segmented") is None
    assert tree.css_first("form.toolbar-sort") is None
    # Filter link and action menu both present.
    assert tree.css_first("a.toolbar-filter-link") is not None
    assert tree.css_first("menu.toolbar-right") is not None


async def test_list_page_links_to_search(
    authenticated_client: AsyncClient,
    logged_in_user: User,
):
    """The toolbar's filter link points at `/posts/search`."""
    response = await authenticated_client.get("/posts")
    assert response.status_code == 200
    tree = HTMLParser(response.text)
    link = tree.css_first("a.toolbar-filter-link")
    assert link is not None
    assert (link.attributes.get("href") or "").startswith("/posts/search")


async def test_list_filters_by_kind_seeking(
    authenticated_client: AsyncClient,
    db_test_session_manager: async_sessionmaker[AsyncSession],
    logged_in_user: User,
):
    """`?kind=referral` keeps only seeking posts; the kind
    `<select>` preselects the matching option."""
    author = create_test_user(username=f"author-{uuid.uuid4()}")
    referral = _referral_post(description=f"ref-{uuid.uuid4()}", owner_id=author.id)
    availability = _opening_post(
        practice_name=f"clinic-{uuid.uuid4()}", owner_id=author.id
    )
    async with db_test_session_manager() as session:
        async with session.begin():
            session.add(author)
            session.add(availability.opening_detail.provider)
            session.add(referral)
            session.add(availability)

    response = await authenticated_client.get("/posts?kind=referral")
    assert response.status_code == 200
    tree = HTMLParser(response.text)
    rows = tree.css("#posts-list > article")
    assert len(rows) == 1
    assert rows[0].attributes.get("data-kind") == "referral"
    # The toolbar's filter link summarizes the active filter inline.
    link = tree.css_first("a.toolbar-filter-link")
    assert link is not None
    assert "Seeking" in link.text()
    # The kind chip is hidden on the cards when a single kind is selected —
    # it would be constant for every card on this page.
    assert tree.css("#posts-list > article [data-kind-chip]") == []


async def test_list_rejects_unknown_kind(
    authenticated_client: AsyncClient,
    logged_in_user: User,
):
    """An unknown `kind=` value is rejected as a 422 by FastAPI — the
    `ChoiceFilter.value_type=Literal[*POST_KINDS.names]` declaration on
    the spec keeps the tight validation the legacy `QueryParam` had."""
    response = await authenticated_client.get("/posts?kind=not_a_real_kind")
    assert response.status_code == 422


async def test_list_filters_by_free_text_q_across_both_detail_tables(
    authenticated_client: AsyncClient,
    db_test_session_manager: async_sessionmaker[AsyncSession],
    logged_in_user: User,
):
    """`?q=needle` finds posts whose description matches on either
    `referral_detail` or `opening_detail`."""
    author = create_test_user(username=f"author-{uuid.uuid4()}")
    seeking_match = _referral_post(description="needle-in-seeking", owner_id=author.id)
    seeking_miss = _referral_post(description="haystack-only-here", owner_id=author.id)
    offering_match = _opening_post(
        practice_name=f"clinic-{uuid.uuid4()}",
        owner_id=author.id,
        description="needle-in-offering",
    )
    async with db_test_session_manager() as session:
        async with session.begin():
            session.add(author)
            session.add(offering_match.opening_detail.provider)
            session.add(seeking_match)
            session.add(seeking_miss)
            session.add(offering_match)

    response = await authenticated_client.get("/posts?q=needle")
    assert response.status_code == 200
    tree = HTMLParser(response.text)
    rows = tree.css("#posts-list > article")
    # Both `needle-*` posts match across the polymorphic OR. The
    # `haystack-*` seeker is filtered out.
    assert len(rows) == 2
    kinds = sorted(r.attributes.get("data-kind") for r in rows)
    assert kinds == ["opening", "referral"]
    # The toolbar's filter link summarizes the active value inline.
    link = tree.css_first("a.toolbar-filter-link")
    assert link is not None
    assert "needle" in link.text()


async def test_list_combines_kind_and_q_with_and(
    authenticated_client: AsyncClient,
    db_test_session_manager: async_sessionmaker[AsyncSession],
    logged_in_user: User,
):
    """`?kind=referral&q=needle` ANDs both predicates — only
    seeking posts whose description matches."""
    author = create_test_user(username=f"author-{uuid.uuid4()}")
    seeking_match = _referral_post(description="needle-seeking", owner_id=author.id)
    offering_with_needle = _opening_post(
        practice_name=f"clinic-{uuid.uuid4()}",
        owner_id=author.id,
        description="needle-offering",
    )
    async with db_test_session_manager() as session:
        async with session.begin():
            session.add(author)
            session.add(offering_with_needle.opening_detail.provider)
            session.add(seeking_match)
            session.add(offering_with_needle)

    response = await authenticated_client.get("/posts?kind=referral&q=needle")
    assert response.status_code == 200
    tree = HTMLParser(response.text)
    rows = tree.css("#posts-list > article")
    assert len(rows) == 1
    assert rows[0].attributes.get("data-kind") == "referral"


# --- Per-column filters: posted_by / state / city / age_group / language ---


async def test_list_filters_by_posted_by_username(
    authenticated_client: AsyncClient,
    db_test_session_manager: async_sessionmaker[AsyncSession],
    logged_in_user: User,
):
    """`?posted_by=substr` filters by ILIKE on owner.username."""
    alice = create_test_user(username=f"alice-{uuid.uuid4()}")
    bob = create_test_user(username=f"bob-{uuid.uuid4()}")
    alice_post = _referral_post(description="a", owner_id=alice.id)
    bob_post = _referral_post(description="b", owner_id=bob.id)
    async with db_test_session_manager() as session:
        async with session.begin():
            session.add(alice)
            session.add(bob)
            session.add(alice_post)
            session.add(bob_post)

    response = await authenticated_client.get("/posts?posted_by=alice")
    assert response.status_code == 200
    tree = HTMLParser(response.text)
    rows = tree.css("#posts-list > article")
    assert len(rows) == 1
    assert rows[0].attributes.get("data-row-id") == str(alice_post.id)
    # The toolbar's filter link summarizes the active value inline.
    link = tree.css_first("a.toolbar-filter-link")
    assert link is not None
    assert "alice" in link.text()


async def test_list_filters_by_state_across_polymorphic_paths(
    authenticated_client: AsyncClient,
    db_test_session_manager: async_sessionmaker[AsyncSession],
    logged_in_user: User,
):
    """`?state=NY&state=NJ` matches both detail tables: seeking's
    `referral_detail.location_state` and offering's
    `opening_detail.provider.location_state`."""
    author = create_test_user(username=f"author-{uuid.uuid4()}")
    seeking_ny = _referral_post(
        description="seeking-ny", owner_id=author.id, location_state="NY"
    )
    seeking_ca = _referral_post(
        description="seeking-ca", owner_id=author.id, location_state="CA"
    )
    offering_nj = _opening_post(
        practice_name=f"clinic-{uuid.uuid4()}",
        owner_id=author.id,
        provider=make_provider_with_org(
            owner_id=author.id,
            practice_name=f"clinic-{uuid.uuid4()}",
            location_state="NJ",
        ),
    )
    offering_tx = _opening_post(
        practice_name=f"clinic-{uuid.uuid4()}",
        owner_id=author.id,
        provider=make_provider_with_org(
            owner_id=author.id,
            practice_name=f"clinic-{uuid.uuid4()}",
            location_state="TX",
        ),
    )
    async with db_test_session_manager() as session:
        async with session.begin():
            session.add(author)
            session.add(offering_nj.opening_detail.provider)
            session.add(offering_tx.opening_detail.provider)
            session.add(seeking_ny)
            session.add(seeking_ca)
            session.add(offering_nj)
            session.add(offering_tx)

    response = await authenticated_client.get("/posts?state=NY&state=NJ")
    assert response.status_code == 200
    tree = HTMLParser(response.text)
    rows = tree.css("#posts-list > article")
    row_ids = {r.attributes.get("data-row-id") for r in rows}
    assert row_ids == {str(seeking_ny.id), str(offering_nj.id)}
    # The toolbar's filter link shows both values inline (within the
    # cutoff of two inline chips).
    link = tree.css_first("a.toolbar-filter-link")
    assert link is not None
    assert "NY" in link.text()
    assert "NJ" in link.text()


async def test_list_filters_by_city_substring_across_polymorphic_paths(
    authenticated_client: AsyncClient,
    db_test_session_manager: async_sessionmaker[AsyncSession],
    logged_in_user: User,
):
    """`?city=spring` ILIKE-matches `location_city` on both detail tables."""
    author = create_test_user(username=f"author-{uuid.uuid4()}")
    seeking_match = _referral_post(
        description="s", owner_id=author.id, location_city="Springfield"
    )
    seeking_miss = _referral_post(
        description="s", owner_id=author.id, location_city="Hartford"
    )
    offering_match = _opening_post(
        practice_name=f"clinic-{uuid.uuid4()}",
        owner_id=author.id,
        provider=make_provider_with_org(
            owner_id=author.id,
            practice_name=f"clinic-{uuid.uuid4()}",
            location_city="Spring Hill",
        ),
    )
    async with db_test_session_manager() as session:
        async with session.begin():
            session.add(author)
            session.add(offering_match.opening_detail.provider)
            session.add(seeking_match)
            session.add(seeking_miss)
            session.add(offering_match)

    response = await authenticated_client.get("/posts?city=spring")
    assert response.status_code == 200
    tree = HTMLParser(response.text)
    row_ids = {
        r.attributes.get("data-row-id") for r in tree.css("#posts-list > article")
    }
    assert row_ids == {str(seeking_match.id), str(offering_match.id)}


async def test_list_filters_by_age_group_json_contains(
    authenticated_client: AsyncClient,
    db_test_session_manager: async_sessionmaker[AsyncSession],
    logged_in_user: User,
):
    """`?age_group=adults_25_64` matches posts whose detail's
    `age_groups` JSON array contains that token, on either side."""
    author = create_test_user(username=f"author-{uuid.uuid4()}")
    seeking_match = _referral_post(
        description="s",
        owner_id=author.id,
        age_groups=["adults_25_64"],
    )
    seeking_miss = _referral_post(
        description="s",
        owner_id=author.id,
        age_groups=["children_0_5"],
    )
    offering_match = _opening_post(
        practice_name=f"clinic-{uuid.uuid4()}",
        owner_id=author.id,
        age_groups=["adults_25_64", "older_adults_65_plus"],
    )
    async with db_test_session_manager() as session:
        async with session.begin():
            session.add(author)
            session.add(offering_match.opening_detail.provider)
            session.add(seeking_match)
            session.add(seeking_miss)
            session.add(offering_match)

    response = await authenticated_client.get("/posts?age_group=adults_25_64")
    assert response.status_code == 200
    tree = HTMLParser(response.text)
    row_ids = {
        r.attributes.get("data-row-id") for r in tree.css("#posts-list > article")
    }
    assert row_ids == {str(seeking_match.id), str(offering_match.id)}


async def test_list_filters_by_language_json_contains(
    authenticated_client: AsyncClient,
    db_test_session_manager: async_sessionmaker[AsyncSession],
    logged_in_user: User,
):
    """`?language=es` matches posts whose detail's `languages` JSON
    array contains `"es"`. Tokens are double-quote-delimited so `"en"`
    doesn't accidentally match a token like `"en_GB"`."""
    author = create_test_user(username=f"author-{uuid.uuid4()}")
    spanish_seeker = _referral_post(
        description="s", owner_id=author.id, languages=["en", "es"]
    )
    english_only = _referral_post(description="e", owner_id=author.id, languages=["en"])
    async with db_test_session_manager() as session:
        async with session.begin():
            session.add(author)
            session.add(spanish_seeker)
            session.add(english_only)

    response = await authenticated_client.get("/posts?language=es")
    assert response.status_code == 200
    tree = HTMLParser(response.text)
    rows = tree.css("#posts-list > article")
    assert len(rows) == 1
    assert rows[0].attributes.get("data-row-id") == str(spanish_seeker.id)


async def test_search_page_renders_one_control_per_filter(
    authenticated_client: AsyncClient,
    logged_in_user: User,
):
    """`/posts/search` renders one control per declared `Filter` on
    POST_ENTITY — `kind` is the single-select `ChoiceFilter(radio=True)`
    rendered as a toggle radio-button group with an "Any" reset."""
    response = await authenticated_client.get("/posts/search")
    assert response.status_code == 200
    tree = HTMLParser(response.text)
    form = tree.css_first("form.search-form")
    assert form is not None
    assert form.attributes.get("action") == "/posts"
    text = " ".join(n.text().strip() for n in form.css("label, legend"))
    expected = {
        "Type",
        "Description",
        "Posted by",
        "State",
        "City",
        "Age groups",
        "Languages",
    }
    for label in expected:
        assert label in text, f"missing search-form control for {label!r}"
    # `kind` is a radio toggle (ChoiceFilter(radio=True)) — one radio per
    # value plus an "Any" reset (`value=""`, surfaced by selectolax as
    # `None` on the attribute dict).
    radios = form.css('input[type="radio"][name="kind"]')
    values = {r.attributes.get("value") for r in radios}
    assert values == {
        None,
        "referral",
        "opening",
        "program_availability",
    }


async def test_toolbar_inline_active_filter_summary_collapses_beyond_two(
    authenticated_client: AsyncClient,
    db_test_session_manager: async_sessionmaker[AsyncSession],
    logged_in_user: User,
):
    """With three active filters, the toolbar's filter link shows the
    first two inline and collapses the rest to ``+1 more filter``."""
    author = create_test_user(username=f"author-{uuid.uuid4()}")
    async with db_test_session_manager() as session:
        async with session.begin():
            session.add(author)

    response = await authenticated_client.get(
        "/posts?kind=referral&q=needle&posted_by=alice"
    )
    assert response.status_code == 200
    tree = HTMLParser(response.text)
    link = tree.css_first("a.toolbar-filter-link")
    assert link is not None
    text = link.text()
    # First filter declared on POST_ENTITY is `kind`, then `q`; the
    # third (`posted_by`) collapses into the "+N more filters" tail.
    assert "Seeking" in text
    assert "needle" in text
    assert "+1 more filter" in text
    # No Clear-all link in the toolbar — clearing happens on the
    # search page's form.
    assert tree.css_first("a.toolbar-clear-all") is None


async def test_toolbar_empty_filter_link_reads_as_filters(
    authenticated_client: AsyncClient,
    logged_in_user: User,
):
    """With no active filters, the toolbar's filter link reads
    ``Filters`` and no Clear-all link is rendered."""
    response = await authenticated_client.get("/posts")
    assert response.status_code == 200
    tree = HTMLParser(response.text)
    link = tree.css_first("a.toolbar-filter-link")
    assert link is not None
    assert link.text().strip() == "Filters"
    assert tree.css_first("a.toolbar-clear-all") is None


async def test_toolbar_has_no_separator_between_filter_link_and_actions(
    authenticated_client: AsyncClient,
    logged_in_user: User,
):
    """No glyph separator between the filter link and the action
    menu — gap alone delineates them."""
    response = await authenticated_client.get("/posts")
    assert response.status_code == 200
    tree = HTMLParser(response.text)
    assert tree.css_first(".toolbar .toolbar-separator") is None


# --- Chrome: edit form cancel link --------------------------------------


async def test_edit_referral_form_renders_cancel(
    authenticated_client: AsyncClient,
    db_test_session_manager: async_sessionmaker[AsyncSession],
    logged_in_user: User,
):
    """Edit form keeps a bottom Cancel link to the post detail page."""
    post = _referral_post(description="x", owner_id=logged_in_user.id)
    async with db_test_session_manager() as session:
        async with session.begin():
            session.add(post)
        await session.refresh(post)
        post_id = post.id

    response = await authenticated_client.get(f"/posts/{post_id}/form")
    assert response.status_code == 200
    tree = HTMLParser(response.text)
    cancel = tree.css_first(f'a[href="/posts/{post_id}"][role="button"]')
    assert cancel is not None
    assert cancel.text(strip=True) == "Cancel"


# --- Edit form page (GET /posts/{id}/form) -------------------------------


async def test_admin_can_open_edit_form_for_any_post(
    authenticated_client: AsyncClient,
    db_test_session_manager: async_sessionmaker[AsyncSession],
    logged_in_user: User,
):
    await promote_to_admin(db_test_session_manager, logged_in_user.email)
    other = create_test_user(username=f"other-{uuid.uuid4()}")
    post = _referral_post(description="d", owner_id=other.id)
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
    post = _referral_post(description="d", owner_id=other.id)
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
    post = _referral_post(description="d", owner_id=logged_in_user.id)
    async with db_test_session_manager() as session:
        async with session.begin():
            session.add(post)

    response = await authenticated_client.get(f"/posts/{post.id}")
    assert response.status_code == 200
    tree = HTMLParser(response.text)
    edit_link = tree.css_first(f"a[href='/posts/{post.id}/form']")
    assert edit_link is not None
    assert edit_link.attributes.get("role") == "button"


async def test_detail_page_shows_edit_link_for_admin(
    authenticated_client: AsyncClient,
    db_test_session_manager: async_sessionmaker[AsyncSession],
    logged_in_user: User,
):
    await promote_to_admin(db_test_session_manager, logged_in_user.email)
    other = create_test_user(username=f"other-{uuid.uuid4()}")
    post = _referral_post(description="d", owner_id=other.id)
    async with db_test_session_manager() as session:
        async with session.begin():
            session.add(other)
            session.add(post)

    response = await authenticated_client.get(f"/posts/{post.id}")
    assert response.status_code == 200
    tree = HTMLParser(response.text)
    assert tree.css_first(f"a[href='/posts/{post.id}/form']") is not None


async def test_detail_page_hides_edit_link_for_stranger(
    authenticated_client: AsyncClient,
    db_test_session_manager: async_sessionmaker[AsyncSession],
    logged_in_user: User,
):
    other = create_test_user(username=f"other-{uuid.uuid4()}")
    post = _referral_post(description="d", owner_id=other.id)
    async with db_test_session_manager() as session:
        async with session.begin():
            session.add(other)
            session.add(post)

    response = await authenticated_client.get(f"/posts/{post.id}")
    assert response.status_code == 200
    tree = HTMLParser(response.text)
    assert tree.css_first(f"a[href='/posts/{post.id}/form']") is None
    assert tree.css_first(f"button[hx-delete='/posts/{post.id}']") is None


async def test_detail_page_delete_button_for_owner(
    authenticated_client: AsyncClient,
    db_test_session_manager: async_sessionmaker[AsyncSession],
    logged_in_user: User,
):
    """The owner sees a Delete button wired to DELETE /posts/{id} with a
    confirmation prompt."""
    post = _referral_post(description="d", owner_id=logged_in_user.id)
    async with db_test_session_manager() as session:
        async with session.begin():
            session.add(post)

    response = await authenticated_client.get(f"/posts/{post.id}")
    assert response.status_code == 200
    tree = HTMLParser(response.text)
    button = tree.css_first(f"button[hx-delete='/posts/{post.id}']")
    assert button is not None
    assert button.text().strip() == "Delete"
    assert button.attributes.get("hx-confirm")


async def test_detail_page_delete_button_for_admin(
    authenticated_client: AsyncClient,
    db_test_session_manager: async_sessionmaker[AsyncSession],
    logged_in_user: User,
):
    """An admin viewing another user's post sees the Delete button too."""
    await promote_to_admin(db_test_session_manager, logged_in_user.email)
    other = create_test_user(username=f"other-{uuid.uuid4()}")
    post = _referral_post(description="d", owner_id=other.id)
    async with db_test_session_manager() as session:
        async with session.begin():
            session.add(other)
            session.add(post)

    response = await authenticated_client.get(f"/posts/{post.id}")
    assert response.status_code == 200
    tree = HTMLParser(response.text)
    button = tree.css_first(f"button[hx-delete='/posts/{post.id}']")
    assert button is not None


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
    post = _referral_post(description="d", owner_id=other.id)
    async with db_test_session_manager() as session:
        async with session.begin():
            session.add(other)
            session.add(post)

    response = await authenticated_client.patch(
        f"/posts/{post.id}",
        data={"kind": "referral", "description": "moderated"},
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
    post = _referral_post(description="d", owner_id=other.id)
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


async def test_create_referral_happy_path(
    authenticated_client: AsyncClient,
    db_test_session_manager: async_sessionmaker[AsyncSession],
    logged_in_user: User,
):
    """`POST /posts` with `kind='referral'` persists with the right
    detail row and audit row."""
    description = f"needs-{uuid.uuid4()}"

    response = await authenticated_client.post(
        "/posts",
        data=referral_payload(description=description),
    )

    assert response.status_code == 201
    new_id = uuid.UUID(response.json()["id"])

    async with db_test_session_manager() as session:
        result = await session.execute(select(Post).filter(Post.id == new_id))
        persisted = result.scalars().first()
        assert persisted is not None
        assert persisted.kind == "referral"
        assert persisted.referral_detail.description == description
        assert persisted.referral_detail.location_state == "IL"
        assert persisted.owner_id == logged_in_user.id

    async with db_test_session_manager() as session:
        repo = AuditRepository(session)
        rows = await repo.list_for_resource(resource_type="post", resource_id=new_id)
        assert len(rows) == 1
        assert rows[0].action == "create_post"
        assert rows[0].before is None
        expected = referral_payload(description=description)
        expected.pop("kind")
        assert rows[0].after == {
            "kind": "referral",
            "owner_id": str(logged_in_user.id),
            **expected,
        }


async def test_create_referral_strips_whitespace(
    authenticated_client: AsyncClient,
    db_test_session_manager: async_sessionmaker[AsyncSession],
    logged_in_user: User,
):
    response = await authenticated_client.post(
        "/posts",
        data=referral_payload(description="  needs help  "),
    )
    assert response.status_code == 201
    new_id = uuid.UUID(response.json()["id"])

    async with db_test_session_manager() as session:
        result = await session.execute(select(Post).filter(Post.id == new_id))
        persisted = result.scalars().first()
        assert persisted.referral_detail.description == "needs help"


@pytest.mark.parametrize(
    "payload",
    [
        {"kind": "referral"},  # missing every required field
        referral_payload(description=""),
        referral_payload(description="   "),
        referral_payload(location_zip="abc"),  # non-numeric ZIP
        referral_payload(location_state="ZZ"),  # not a US state
        referral_payload(network_preference="bring_cash"),  # not in NETWORK_PREFERENCES
        referral_payload(
            insurance_carrier="my_local_co_op"
        ),  # not in INSURANCE_CARRIERS
        referral_payload(title="bleed"),  # cross-kind field bleed
        referral_payload(evil=True),  # unknown field
        {"kind": "unknown_kind", "description": "ok"},
    ],
)
async def test_create_referral_rejects_invalid_payload(
    payload,
    authenticated_client: AsyncClient,
    logged_in_user: User,
):
    response = await authenticated_client.post("/posts", data=payload)
    assert response.status_code == 422


async def test_get_referral_form_renders(
    authenticated_client: AsyncClient,
    logged_in_user: User,
):
    """`GET /posts/form?kind=referral` renders the kind-specific
    create form."""
    response = await authenticated_client.get("/posts/form?kind=referral")
    assert response.status_code == 200
    tree = HTMLParser(response.text)
    form = tree.css_first("form")
    assert form is not None
    assert form.attributes.get("hx-post") == "/posts"
    assert tree.css_first("textarea#description") is not None
    kind_input = tree.css_first('input[name="kind"]')
    assert kind_input is not None
    assert kind_input.attributes.get("value") == "referral"


async def test_referral_form_renders_languages_multi_select(
    authenticated_client: AsyncClient,
    logged_in_user: User,
):
    """`languages` on CR renders via `field_for`'s multi_select arm (#428)
    — the unified `<select multiple>` widget shared by every multi-select
    field on the site."""
    response = await authenticated_client.get("/posts/form?kind=referral")
    assert response.status_code == 200
    tree = HTMLParser(response.text)
    select = tree.css_first('select[name="languages"][multiple]')
    assert select is not None
    values = {o.attributes.get("value") for o in select.css("option")}
    assert values == {"en", "es"}


async def test_referral_form_renders_age_groups_multi_select(
    authenticated_client: AsyncClient,
    logged_in_user: User,
):
    """`age_groups` on CR renders via the multi-select arm (#432),
    mirroring PA's `age_groups` (#430) — the unified `<select multiple>`
    widget."""
    response = await authenticated_client.get("/posts/form?kind=referral")
    assert response.status_code == 200
    tree = HTMLParser(response.text)
    select = tree.css_first('select[name="age_groups"][multiple]')
    assert select is not None
    values = {o.attributes.get("value") for o in select.css("option")}
    assert values == {
        "children_0_5",
        "children_6_10",
        "preteens_11_13",
        "adolescents_14_18",
        "young_adults_19_24",
        "adults_25_64",
        "older_adults_65_plus",
    }


async def test_get_post_form_no_kind_renders_picker(
    authenticated_client: AsyncClient,
    logged_in_user: User,
):
    """`GET /posts/form` without a `kind` query parameter renders the
    kind picker (`posts/form_new.html`) — not a kind-specific create
    form. The picker is a `.kind-picker` chooser with one option card
    per kind: each card is an `<a class="kind-picker-option">`
    carrying a Lucide icon, a title, and a 1-line description, and
    its href round-trips back to `/posts/form?kind=…`."""
    response = await authenticated_client.get("/posts/form")
    assert response.status_code == 200
    tree = HTMLParser(response.text)
    # No `<input name="kind">` — that lives on the kind-specific forms,
    # not the picker.
    assert tree.css_first('input[name="kind"]') is None
    # The chooser wrapper is the new `kind-picker` class — pin it so
    # any future rewrite has to update this test deliberately.
    assert tree.css_first(".kind-picker") is not None
    # Each registered kind has an option card with the kind-specific
    # accent (`data-kind`), title, and description.
    referral_option = tree.css_first(
        'a.kind-picker-option[data-kind="referral"][href="/posts/form?kind=referral"]'
    )
    assert referral_option is not None
    assert referral_option.css_first(".kind-picker-icon") is not None
    assert "Refer a client to a provider" in referral_option.text()
    assert "needs care" in referral_option.text()

    opening_option = tree.css_first(
        'a.kind-picker-option[data-kind="opening"][href="/posts/form?kind=opening"]'
    )
    assert opening_option is not None
    assert "Announce availability for new clients" in opening_option.text()
    assert "open slots" in opening_option.text()

    program_option = tree.css_first(
        'a.kind-picker-option[data-kind="program_availability"]'
        '[href="/posts/form?kind=program_availability"]'
    )
    assert program_option is not None
    assert "Announce program intake" in program_option.text()
    assert "cohort" in program_option.text()


async def test_get_post_form_treats_empty_kind_as_absent(
    authenticated_client: AsyncClient,
    logged_in_user: User,
):
    """`GET /posts/form?kind=` should behave the same as no `kind=` at
    all — render the picker rather than 422 against the `Literal[...]`
    annotation. The middleware strips the empty pair at request entry
    so FastAPI sees the param as absent and the route's default
    (`None` → picker) fires."""
    response = await authenticated_client.get("/posts/form?kind=")
    assert response.status_code == 200
    tree = HTMLParser(response.text)
    assert tree.css_first('input[name="kind"]') is None
    assert tree.css_first('a[href="/posts/form?kind=referral"]') is not None


async def test_list_renders_referral_row(
    authenticated_client: AsyncClient,
    db_test_session_manager: async_sessionmaker[AsyncSession],
    logged_in_user: User,
):
    """`GET /posts` renders a referral card whose header link
    is the age + gender combo (e.g. `Adult (25–64)` with the default
    `prefer_not_to_say` gender). State lives in the location chunk of
    the demographics column. The kind is also conveyed by the
    `data-kind` left-edge color."""
    author = create_test_user(username=f"author-{uuid.uuid4()}")
    post = _referral_post(
        description=f"crsummary-{uuid.uuid4()}",
        owner_id=author.id,
    )

    async with db_test_session_manager() as session:
        async with session.begin():
            session.add(author)
            session.add(post)

    response = await authenticated_client.get("/posts")
    assert response.status_code == 200
    tree = HTMLParser(response.text)
    item = tree.css_first("#posts-list > article")
    assert item is not None
    assert item.attributes.get("data-kind") == "referral"
    # Default fixture: age_groups=["adults_25_64"], gender="prefer_not_to_say".
    # State (IL) lives in the demographics location chunk, not the header.
    assert item.css_first("header.entity-header a").text().strip() == "Adult (25–64)"


async def test_get_referral_detail_renders(
    authenticated_client: AsyncClient,
    db_test_session_manager: async_sessionmaker[AsyncSession],
    logged_in_user: User,
):
    author = create_test_user(username=f"author-{uuid.uuid4()}")
    description = f"detail-{uuid.uuid4()}"
    post = _referral_post(description=description, owner_id=author.id)

    async with db_test_session_manager() as session:
        async with session.begin():
            session.add(author)
            session.add(post)

    response = await authenticated_client.get(f"/posts/{post.id}")
    assert response.status_code == 200
    page = response.text
    assert description in page
    # The author's username no longer renders on the detail page —
    # the redundant meta line ("Seeking by <user> · <date>") was
    # removed; the author's identity surfaces only via the
    # mailto: link in the footer (`post.owner.email`, not username).
    assert author.email in page


async def test_owner_can_open_referral_edit_form(
    authenticated_client: AsyncClient,
    db_test_session_manager: async_sessionmaker[AsyncSession],
    logged_in_user: User,
):
    """The owner of a referral sees the kind-specific edit form
    pre-filled with the current description."""
    description = f"edit-{uuid.uuid4()}"
    post = _referral_post(description=description, owner_id=logged_in_user.id)
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
    assert kind_input.attributes.get("value") == "referral"


async def test_owner_can_patch_referral_description(
    authenticated_client: AsyncClient,
    db_test_session_manager: async_sessionmaker[AsyncSession],
    logged_in_user: User,
):
    """`PATCH /posts/{id}` with `kind='referral'` updates the
    description and returns a per-kind flat body."""
    post = _referral_post(description="orig", owner_id=logged_in_user.id)
    async with db_test_session_manager() as session:
        async with session.begin():
            session.add(post)

    new_description = f"updated-{uuid.uuid4()}"
    response = await authenticated_client.patch(
        f"/posts/{post.id}",
        data={"kind": "referral", "description": new_description},
    )
    assert response.status_code == 200
    assert response.headers.get("HX-Redirect") == f"/posts/{post.id}"
    body = response.json()
    assert body["kind"] == "referral"
    assert body["description"] == new_description
    assert "title" not in body and "body" not in body

    async with db_test_session_manager() as session:
        result = await session.execute(select(Post).filter(Post.id == post.id))
        refreshed = result.scalars().first()
        assert refreshed.referral_detail.description == new_description


async def test_patch_opening_with_referral_payload_does_not_mutate(
    authenticated_client: AsyncClient,
    db_test_session_manager: async_sessionmaker[AsyncSession],
    logged_in_user: User,
):
    """A opening post can't be patched with a referral
    payload — kind is part of the resource identity. The 400 must fire
    before any mutation, and no audit row may be written."""
    original = f"orig-{uuid.uuid4()}"
    post = _opening_post(practice_name=original, owner_id=logged_in_user.id)
    async with db_test_session_manager() as session:
        async with session.begin():
            session.add(post)
    post_id = post.id

    response = await authenticated_client.patch(
        f"/posts/{post_id}",
        data={"kind": "referral", "description": "hijack"},
    )
    assert response.status_code == 400

    async with db_test_session_manager() as session:
        result = await session.execute(select(Post).filter(Post.id == post_id))
        refreshed = result.scalars().first()
        assert refreshed.kind == "opening"
        # Practice name lives on the linked Provider's Organization (#524).
        assert refreshed.opening_detail.provider.org.name == original
        assert refreshed.referral_detail is None

    async with db_test_session_manager() as session:
        repo = AuditRepository(session)
        rows = await repo.list_for_resource(resource_type="post", resource_id=post_id)
        assert rows == []


async def test_patch_referral_with_opening_payload_does_not_mutate(
    authenticated_client: AsyncClient,
    db_test_session_manager: async_sessionmaker[AsyncSession],
    logged_in_user: User,
):
    """Reverse direction: a referral can't be patched with a
    opening payload either. Same invariant — kind is fixed
    once set."""
    original_description = f"orig-{uuid.uuid4()}"
    post = _referral_post(description=original_description, owner_id=logged_in_user.id)
    async with db_test_session_manager() as session:
        async with session.begin():
            session.add(post)
    post_id = post.id

    response = await authenticated_client.patch(
        f"/posts/{post_id}",
        # `description` is a valid PA Update field — schema passes; the 400
        # comes from the post-validation kind-mismatch check, which is the
        # behavior under test. (Practice name moved to Provider post-#448
        # and is no longer a PA wire field, so it can't be used here.)
        data={"kind": "opening", "description": "hijack"},
    )
    assert response.status_code == 400

    async with db_test_session_manager() as session:
        result = await session.execute(select(Post).filter(Post.id == post_id))
        refreshed = result.scalars().first()
        assert refreshed.kind == "referral"
        assert refreshed.referral_detail.description == original_description
        assert refreshed.opening_detail is None

    async with db_test_session_manager() as session:
        repo = AuditRepository(session)
        rows = await repo.list_for_resource(resource_type="post", resource_id=post_id)
        assert rows == []


async def test_owner_can_delete_referral(
    authenticated_client: AsyncClient,
    db_test_session_manager: async_sessionmaker[AsyncSession],
    logged_in_user: User,
):
    """`DELETE /posts/{id}` works for referral; cascades the detail."""
    post = _referral_post(description="doomed", owner_id=logged_in_user.id)
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
                    select(ReferralDetail).filter(ReferralDetail.post_id == post_id)
                )
            )
            .scalars()
            .first()
        )
        assert post_row is None
        assert detail_row is None


async def test_delete_referral_writes_audit_row(
    authenticated_client: AsyncClient,
    db_test_session_manager: async_sessionmaker[AsyncSession],
    logged_in_user: User,
):
    """Audit before-snapshot for a referral delete uses the
    kind-specific snapshot shape."""
    description = f"doomed-{uuid.uuid4()}"
    post = _referral_post(description=description, owner_id=logged_in_user.id)
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
            **referral_payload(description=description),
            "owner_id": str(logged_in_user.id),
        }
        assert rows[0].after is None


# --- Provider availability kind: end-to-end ------------------------------


async def test_create_opening_happy_path(
    authenticated_client: AsyncClient,
    db_test_session_manager: async_sessionmaker[AsyncSession],
    logged_in_user: User,
):
    """`POST /posts` with `kind='opening'` persists with
    the right detail row + audit row."""
    practice_name = f"Acme-{uuid.uuid4()}"
    # PA points at a Provider via `provider_id` (#448); seed one owned by
    # the requesting user so the FK resolves at write time.
    provider = make_provider_with_org(
        owner_id=logged_in_user.id, practice_name=practice_name
    )
    async with db_test_session_manager() as session:
        async with session.begin():
            session.add(provider)

    response = await authenticated_client.post(
        "/posts",
        data=opening_payload(provider_id=str(provider.id)),
    )

    assert response.status_code == 201
    new_id = uuid.UUID(response.json()["id"])

    async with db_test_session_manager() as session:
        result = await session.execute(select(Post).filter(Post.id == new_id))
        persisted = result.scalars().first()
        assert persisted is not None
        assert persisted.kind == "opening"
        assert persisted.opening_detail.provider_id == provider.id
        assert persisted.opening_detail.provider.org.name == practice_name
        # Insurance posture / sliding-scale / cost live on Provider, not
        # PA. The `make_provider` factory defaults are: empty carrier list
        # (no in-network) + `accepts_out_of_network=True`, no sliding scale.
        assert persisted.opening_detail.provider.in_network_carriers == []
        assert persisted.opening_detail.provider.accepts_out_of_network is True
        assert persisted.opening_detail.provider.sliding_scale is False
        assert persisted.referral_detail is None
        assert persisted.owner_id == logged_in_user.id

    async with db_test_session_manager() as session:
        repo = AuditRepository(session)
        rows = await repo.list_for_resource(resource_type="post", resource_id=new_id)
        assert len(rows) == 1
        assert rows[0].action == "create_post"
        assert rows[0].before is None
        expected = opening_payload(provider_id=str(provider.id))
        expected.pop("kind")
        assert rows[0].after == {
            "kind": "opening",
            "owner_id": str(logged_in_user.id),
            **expected,
        }


async def test_create_opening_strips_whitespace(
    authenticated_client: AsyncClient,
    db_test_session_manager: async_sessionmaker[AsyncSession],
    logged_in_user: User,
):
    """Whitespace stripping applies to PA's remaining free-text wire fields.
    (Practice-name whitespace stripping is exercised on Provider post-#448.)"""
    provider = make_provider_with_org(owner_id=logged_in_user.id)
    async with db_test_session_manager() as session:
        async with session.begin():
            session.add(provider)

    response = await authenticated_client.post(
        "/posts",
        data=opening_payload(
            provider_id=str(provider.id), description="  Lead pitch  "
        ),
    )
    assert response.status_code == 201
    new_id = uuid.UUID(response.json()["id"])

    async with db_test_session_manager() as session:
        result = await session.execute(select(Post).filter(Post.id == new_id))
        persisted = result.scalars().first()
        assert persisted.opening_detail.description == "Lead pitch"


@pytest.mark.parametrize(
    "payload",
    [
        {"kind": "opening"},  # missing every required field
        opening_payload(payment_situation="cash_only"),
        opening_payload(title="bleed"),  # cross-kind bleed
        opening_payload(evil=True),  # unknown field
    ],
)
async def test_create_opening_rejects_invalid_payload(
    payload,
    authenticated_client: AsyncClient,
    logged_in_user: User,
):
    response = await authenticated_client.post("/posts", data=payload)
    assert response.status_code == 422


async def test_get_opening_form_renders(
    authenticated_client: AsyncClient,
    db_test_session_manager: async_sessionmaker[AsyncSession],
    logged_in_user: User,
):
    """`GET /posts/form?kind=opening` renders the kind-specific
    create form. Per #448, the form needs the user to own at least one
    Provider profile (otherwise it shows the create-a-provider stub)."""
    provider = make_provider_with_org(owner_id=logged_in_user.id)
    async with db_test_session_manager() as session:
        async with session.begin():
            session.add(provider)

    response = await authenticated_client.get("/posts/form?kind=opening")
    assert response.status_code == 200
    tree = HTMLParser(response.text)
    form = tree.css_first("form")
    assert form is not None
    assert form.attributes.get("hx-post") == "/posts"
    # `provider_id` is now a <select> over the user's owned Providers (#448).
    assert tree.css_first("select#provider_id") is not None
    kind_input = tree.css_first('input[name="kind"]')
    assert kind_input is not None
    assert kind_input.attributes.get("value") == "opening"


async def test_opening_form_renders_free_text_fields(
    authenticated_client: AsyncClient,
    db_test_session_manager: async_sessionmaker[AsyncSession],
    logged_in_user: User,
):
    """The three free-text fields render through `field_for` — `description`
    and `referral_instructions` as `<textarea>` (driven by the `HtmlTextarea`
    marker on the schema), `website` as `<input type="url">` (driven by
    `HtmlUrl` — #446). A regression where either marker stops being picked
    up would render fields as the wrong control and silently break the form."""
    provider = make_provider_with_org(owner_id=logged_in_user.id)
    async with db_test_session_manager() as session:
        async with session.begin():
            session.add(provider)

    response = await authenticated_client.get("/posts/form?kind=opening")
    assert response.status_code == 200
    tree = HTMLParser(response.text)
    assert tree.css_first("textarea#description") is not None
    assert tree.css_first("textarea#referral_instructions") is not None
    website = tree.css_first("input#website")
    assert website is not None
    assert website.attributes.get("type") == "url"


async def test_opening_form_renders_languages_multi_select(
    authenticated_client: AsyncClient,
    db_test_session_manager: async_sessionmaker[AsyncSession],
    logged_in_user: User,
):
    """`languages` renders as a `<select multiple>` via `field_for`'s
    `list[Literal[*T]]` arm (#425). Confirms the schema-driven multi-
    select dispatch is wired end-to-end through the unified widget."""
    provider = make_provider_with_org(owner_id=logged_in_user.id)
    async with db_test_session_manager() as session:
        async with session.begin():
            session.add(provider)

    response = await authenticated_client.get("/posts/form?kind=opening")
    assert response.status_code == 200
    tree = HTMLParser(response.text)
    select = tree.css_first('select[name="languages"][multiple]')
    assert select is not None
    values = {o.attributes.get("value") for o in select.css("option")}
    assert values == {"en", "es"}
    assert "English" in response.text
    assert "Spanish" in response.text


async def test_opening_form_renders_age_groups_multi_select(
    authenticated_client: AsyncClient,
    db_test_session_manager: async_sessionmaker[AsyncSession],
    logged_in_user: User,
):
    """`age_groups` renders as a 7-option `<select multiple>` via
    `field_for`'s `list[Literal[*T]]` arm (#430). First 7-option consumer
    of the multi-select rails."""
    provider = make_provider_with_org(owner_id=logged_in_user.id)
    async with db_test_session_manager() as session:
        async with session.begin():
            session.add(provider)

    response = await authenticated_client.get("/posts/form?kind=opening")
    assert response.status_code == 200
    tree = HTMLParser(response.text)
    select = tree.css_first('select[name="age_groups"][multiple]')
    assert select is not None
    values = {o.attributes.get("value") for o in select.css("option")}
    assert values == {
        "children_0_5",
        "children_6_10",
        "preteens_11_13",
        "adolescents_14_18",
        "young_adults_19_24",
        "adults_25_64",
        "older_adults_65_plus",
    }


async def test_list_renders_opening_row(
    authenticated_client: AsyncClient,
    db_test_session_manager: async_sessionmaker[AsyncSession],
    logged_in_user: User,
):
    """`GET /posts` renders a opening card whose header
    link IS the practice name (PA posts identify by their practice;
    the `Provider Availability` kind label is dropped from the title
    as redundant)."""
    author = create_test_user(username=f"author-{uuid.uuid4()}")
    practice_name = f"Practice-{uuid.uuid4()}"
    post = _opening_post(practice_name=practice_name, owner_id=author.id)

    async with db_test_session_manager() as session:
        async with session.begin():
            session.add(author)
            session.add(post)

    response = await authenticated_client.get("/posts")
    assert response.status_code == 200
    tree = HTMLParser(response.text)
    item = tree.css_first("#posts-list > article")
    assert item is not None
    assert item.attributes.get("data-kind") == "opening"
    assert practice_name in item.css_first("header.entity-header a").text()


async def test_get_opening_detail_renders(
    authenticated_client: AsyncClient,
    db_test_session_manager: async_sessionmaker[AsyncSession],
    logged_in_user: User,
):
    author = create_test_user(username=f"author-{uuid.uuid4()}")
    practice_name = f"Detail-{uuid.uuid4()}"
    post = _opening_post(practice_name=practice_name, owner_id=author.id)

    async with db_test_session_manager() as session:
        async with session.begin():
            session.add(author)
            session.add(post)

    response = await authenticated_client.get(f"/posts/{post.id}")
    assert response.status_code == 200
    page = response.text
    assert practice_name in page
    # The author's username no longer renders on the detail page —
    # the redundant meta line ("Providing by <user> · <date>") was
    # removed; the author's identity surfaces only via the
    # mailto: link in the footer (`post.owner.email`, not username).
    assert author.email in page


async def test_owner_can_open_opening_edit_form(
    authenticated_client: AsyncClient,
    db_test_session_manager: async_sessionmaker[AsyncSession],
    logged_in_user: User,
):
    """The owner of a opening sees the kind-specific edit
    form with the linked Provider preselected in the dropdown."""
    practice_name = f"Edit-{uuid.uuid4()}"
    post = _opening_post(practice_name=practice_name, owner_id=logged_in_user.id)
    async with db_test_session_manager() as session:
        async with session.begin():
            session.add(post)

    response = await authenticated_client.get(f"/posts/{post.id}/form")
    assert response.status_code == 200
    tree = HTMLParser(response.text)
    form = tree.css_first("form")
    assert form is not None
    assert form.attributes.get("hx-patch") == f"/posts/{post.id}"
    # The linked Provider's row appears as the selected `<option>` (#448).
    provider_select = tree.css_first("select#provider_id")
    assert provider_select is not None
    selected = provider_select.css_first("option[selected]")
    assert selected is not None
    assert selected.text(strip=True) == practice_name
    kind_input = tree.css_first('input[name="kind"]')
    assert kind_input is not None
    assert kind_input.attributes.get("value") == "opening"


async def test_owner_can_patch_opening_description(
    authenticated_client: AsyncClient,
    db_test_session_manager: async_sessionmaker[AsyncSession],
    logged_in_user: User,
):
    """Patch a PA field (`description`) and confirm round-trip + read body.
    (Practice name moved to Provider post-#448 and is no longer a PA wire
    field — the parallel test for renaming a practice lives on Provider.)"""
    post = _opening_post(practice_name="orig", owner_id=logged_in_user.id)
    async with db_test_session_manager() as session:
        async with session.begin():
            session.add(post)

    new_description = f"Renamed-{uuid.uuid4()}"
    response = await authenticated_client.patch(
        f"/posts/{post.id}",
        data={
            "kind": "opening",
            "description": new_description,
        },
    )
    assert response.status_code == 200
    assert response.headers.get("HX-Redirect") == f"/posts/{post.id}"
    body = response.json()
    assert body["kind"] == "opening"
    assert body["description"] == new_description
    assert "title" not in body and "body" not in body

    async with db_test_session_manager() as session:
        result = await session.execute(select(Post).filter(Post.id == post.id))
        refreshed = result.scalars().first()
        assert refreshed.opening_detail.description == new_description


async def test_owner_can_delete_opening(
    authenticated_client: AsyncClient,
    db_test_session_manager: async_sessionmaker[AsyncSession],
    logged_in_user: User,
):
    """`DELETE /posts/{id}` works for opening; cascades the detail."""
    post = _opening_post(practice_name="doomed", owner_id=logged_in_user.id)
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
                    select(OpeningDetail).filter(OpeningDetail.post_id == post_id)
                )
            )
            .scalars()
            .first()
        )
        assert post_row is None
        assert detail_row is None


async def test_delete_opening_writes_audit_row(
    authenticated_client: AsyncClient,
    db_test_session_manager: async_sessionmaker[AsyncSession],
    logged_in_user: User,
):
    """Per #448 the PA audit snapshot records `provider_id` instead of the
    six fields that moved to Provider (`practice_name`, `location_*`,
    `*_sessions`)."""
    practice_name = f"doomed-{uuid.uuid4()}"
    post = _opening_post(practice_name=practice_name, owner_id=logged_in_user.id)
    provider_id = post.opening_detail.provider_id
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
            **opening_payload(provider_id=str(provider_id)),
            "owner_id": str(logged_in_user.id),
        }
        assert rows[0].after is None


# --- Program availability kind: end-to-end -------------------------------


async def _seed_program_for_user(
    db_test_session_manager,
    *,
    owner_id: uuid.UUID,
    org_name: str = "RISE IOP at CHC",
    program_name: str = "RISE Intensive Outpatient",
) -> Program:
    """Seed an Org + a Program owned by ``owner_id`` (#541). Returns the
    persisted Program. The Org is found-or-created by name so multiple
    Programs in one test can share the same Org."""
    org = make_organization_row(owner_id=owner_id, name=org_name)
    program = make_program(owner_id=owner_id, org_id=org.id, name=program_name)
    async with db_test_session_manager() as session:
        async with session.begin():
            session.add(org)
            session.add(program)
        await session.refresh(program)
    return program


async def test_create_program_availability_happy_path(
    authenticated_client: AsyncClient,
    db_test_session_manager: async_sessionmaker[AsyncSession],
    logged_in_user: User,
):
    """`POST /posts` with `kind='program_availability'` persists the
    parent + detail rows and writes a single `create_post` audit row."""
    program = await _seed_program_for_user(
        db_test_session_manager, owner_id=logged_in_user.id
    )

    response = await authenticated_client.post(
        "/posts",
        data=program_availability_payload(program_id=str(program.id)),
    )
    assert response.status_code == 201
    new_id = uuid.UUID(response.json()["id"])

    async with db_test_session_manager() as session:
        result = await session.execute(select(Post).filter(Post.id == new_id))
        persisted = result.scalars().first()
        assert persisted is not None
        assert persisted.kind == "program_availability"
        assert persisted.program_availability_detail.program_id == program.id
        assert persisted.opening_detail is None
        assert persisted.referral_detail is None
        assert persisted.owner_id == logged_in_user.id

    async with db_test_session_manager() as session:
        repo = AuditRepository(session)
        rows = await repo.list_for_resource(resource_type="post", resource_id=new_id)
        assert len(rows) == 1
        assert rows[0].action == "create_post"


async def test_create_program_availability_rejects_unowned_program(
    authenticated_client: AsyncClient,
    db_test_session_manager: async_sessionmaker[AsyncSession],
    logged_in_user: User,
):
    """``payload_authz`` (#541): a POST whose ``program_id`` points at
    another user's Program returns 403."""
    other = create_test_user(username=f"other-{uuid.uuid4()}")
    async with db_test_session_manager() as session:
        async with session.begin():
            session.add(other)
    other_program = await _seed_program_for_user(
        db_test_session_manager,
        owner_id=other.id,
        org_name=f"Others-{uuid.uuid4()}",
    )

    response = await authenticated_client.post(
        "/posts",
        data=program_availability_payload(program_id=str(other_program.id)),
    )
    assert response.status_code == 403


async def test_create_program_availability_rejects_nonexistent_program(
    authenticated_client: AsyncClient,
    logged_in_user: User,
):
    """A POST with a bogus ``program_id`` returns 404 (no info leak;
    also avoids the 500 the FK would otherwise produce)."""
    bogus = uuid.uuid4()
    response = await authenticated_client.post(
        "/posts", data=program_availability_payload(program_id=str(bogus))
    )
    assert response.status_code == 404


async def test_create_program_availability_superuser_bypass(
    authenticated_client: AsyncClient,
    db_test_session_manager: async_sessionmaker[AsyncSession],
    logged_in_user: User,
):
    """Superusers bypass the ``payload_authz`` Program-ownership check."""
    await promote_to_admin(db_test_session_manager, logged_in_user.email)
    other = create_test_user(username=f"other-{uuid.uuid4()}")
    async with db_test_session_manager() as session:
        async with session.begin():
            session.add(other)
    other_program = await _seed_program_for_user(
        db_test_session_manager,
        owner_id=other.id,
        org_name=f"Others-{uuid.uuid4()}",
    )

    response = await authenticated_client.post(
        "/posts",
        data=program_availability_payload(program_id=str(other_program.id)),
    )
    assert response.status_code == 201


async def test_get_program_availability_form_renders_program_picker(
    authenticated_client: AsyncClient,
    db_test_session_manager: async_sessionmaker[AsyncSession],
    logged_in_user: User,
):
    """`GET /posts/form?kind=program_availability` renders a Program-
    picker scoped to the user's owned Programs (#541)."""
    program = await _seed_program_for_user(
        db_test_session_manager, owner_id=logged_in_user.id
    )
    # An unowned Program in the DB to confirm it does NOT appear.
    other = create_test_user(username=f"other-{uuid.uuid4()}")
    async with db_test_session_manager() as session:
        async with session.begin():
            session.add(other)
    other_program = await _seed_program_for_user(
        db_test_session_manager,
        owner_id=other.id,
        org_name=f"Others-{uuid.uuid4()}",
        program_name="Other Program",
    )

    response = await authenticated_client.get("/posts/form?kind=program_availability")
    assert response.status_code == 200
    tree = HTMLParser(response.text)
    select = tree.css_first("select#program_id")
    assert select is not None
    values = {opt.attributes.get("value") for opt in select.css("option")}
    assert str(program.id) in values
    assert str(other_program.id) not in values
    kind_input = tree.css_first('input[name="kind"]')
    assert kind_input is not None
    assert kind_input.attributes.get("value") == "program_availability"


async def test_patch_program_availability_rejects_unowned_program(
    authenticated_client: AsyncClient,
    db_test_session_manager: async_sessionmaker[AsyncSession],
    logged_in_user: User,
):
    """The ``payload_authz`` hook fires on PATCH too — repointing
    ``program_id`` at another user's Program is 403."""
    program = await _seed_program_for_user(
        db_test_session_manager, owner_id=logged_in_user.id
    )

    # Create the post the normal way.
    response = await authenticated_client.post(
        "/posts", data=program_availability_payload(program_id=str(program.id))
    )
    assert response.status_code == 201
    post_id = uuid.UUID(response.json()["id"])

    # Now an unowned target Program.
    other = create_test_user(username=f"other-{uuid.uuid4()}")
    async with db_test_session_manager() as session:
        async with session.begin():
            session.add(other)
    other_program = await _seed_program_for_user(
        db_test_session_manager,
        owner_id=other.id,
        org_name=f"Others-{uuid.uuid4()}",
    )

    response = await authenticated_client.patch(
        f"/posts/{post_id}",
        data={
            "kind": "program_availability",
            "program_id": str(other_program.id),
        },
    )
    assert response.status_code == 403


# --- Provider-availability payload_authz coverage (gap closed by #541) ---


async def test_create_opening_rejects_unowned_provider(
    authenticated_client: AsyncClient,
    db_test_session_manager: async_sessionmaker[AsyncSession],
    logged_in_user: User,
):
    """Coverage for the security gap closed alongside #541: pre-existing
    PA posts had a schema docstring claiming "the route handler verifies
    ownership at write time" but no handler implemented the check.
    The dispatching ``payload_authz`` callable on `POST_ENTITY` closes
    that gap — a POST referencing another user's Provider is 403."""
    other = create_test_user(username=f"other-{uuid.uuid4()}")
    provider = make_provider_with_org(owner_id=other.id, practice_name="Other Co")
    async with db_test_session_manager() as session:
        async with session.begin():
            session.add(other)
            session.add(provider)

    response = await authenticated_client.post(
        "/posts",
        data=opening_payload(provider_id=str(provider.id)),
    )
    assert response.status_code == 403


async def test_create_opening_rejects_nonexistent_provider(
    authenticated_client: AsyncClient,
    logged_in_user: User,
):
    """A POST with a bogus ``provider_id`` returns 404 (no info leak)."""
    bogus = uuid.uuid4()
    response = await authenticated_client.post(
        "/posts",
        data=opening_payload(provider_id=str(bogus)),
    )
    assert response.status_code == 404
