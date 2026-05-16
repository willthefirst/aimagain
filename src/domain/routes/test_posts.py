import uuid

import pytest
from httpx import AsyncClient
from selectolax.parser import HTMLParser
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from src.domain.models import (
    ClientReferralDetail,
    Post,
    Provider,
    ProviderAvailabilityDetail,
    User,
)
from src.framework.audit.repository import AuditRepository
from tests.helpers import (
    client_referral_payload,
    create_test_user,
    make_client_referral_detail,
    make_provider,
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


def _provider_availability_post(
    *, practice_name: str, owner_id, provider: Provider | None = None, **overrides
) -> Post:
    """Build a `kind='provider_availability'` Post + its spec-compliant
    detail + the linked Provider profile. The Provider is auto-created
    with the given `practice_name` unless one is passed explicitly.
    SQLAlchemy save-update cascade persists the Provider when the Post
    is added to a session — callers do `session.add(post)` and the
    Provider goes in too with the right FK order."""
    if provider is None:
        provider = make_provider(owner_id=owner_id, practice_name=practice_name)
    if provider.id is None:
        provider.id = uuid.uuid4()
    post = Post(kind="provider_availability", owner_id=owner_id)
    detail = make_provider_availability_detail(provider_id=provider.id, **overrides)
    # Wire the Provider through the relationship so save-update cascade
    # persists it when the Post is added to a session.
    detail.provider = provider
    post.provider_availability_detail = detail
    return post


def _make_test_post(owner: User, *, description: str | None = None) -> Post:
    return _client_referral_post(
        description=description or f"post-{uuid.uuid4()}",
        owner_id=owner.id,
    )


# --- Listing -------------------------------------------------------------


async def test_list_client_referral_item_shape(
    authenticated_client: AsyncClient,
    db_test_session_manager: async_sessionmaker[AsyncSession],
    logged_in_user: User,
):
    """A `client_referral` renders as a single dense `<li>` in
    `#posts-list`: a `Seeking` kind chip (`<mark data-kind-chip>`), the
    description as the link target (the seeker's own words are the
    lead), and a `·`-joined meta tail covering location / format / ages
    / languages / insurance."""
    author = create_test_user(username=f"author-{uuid.uuid4()}")
    description = f"item-{uuid.uuid4()}"
    post = _client_referral_post(
        description=description,
        owner_id=author.id,
        location_city="Seattle",
        location_state="WA",
        location_in_person="yes",
        location_virtual="yes",
        age_groups=["adolescents_14_18", "adults_25_64"],
        languages=["en", "es"],
        insurance="in_network",
    )
    async with db_test_session_manager() as session:
        async with session.begin():
            session.add(author)
            session.add(post)

    response = await authenticated_client.get("/posts")
    assert response.status_code == 200
    tree = HTMLParser(response.text)
    item = tree.css_first("#posts-list > div")
    assert item is not None
    assert item.attributes.get("data-kind") == "client_referral"

    # Kind chip: rendered when no `?kind=` filter is active.
    chip = item.css_first("[data-kind-chip]")
    assert chip is not None
    assert chip.attributes.get("data-kind-chip") == "client_referral"
    assert chip.text(strip=True) == "Seeking"

    # Description is the link target — the lead text is the seeker's
    # own words, not a synthesized headline.
    lead = item.css_first("a")
    assert lead is not None
    assert lead.attributes.get("href") == f"/posts/{post.id}"
    assert lead.text(strip=True) == description

    # Meta tail carries the location, format, ages, languages.
    # Insurance posture deliberately dropped from listing meta — it's
    # noisy in a Craigslist-style feed; readers go to the detail page
    # for in-network carriers + sliding-scale specifics.
    item_text = item.text()
    assert "Seattle, WA" in item_text
    assert "In-person + Virtual" in item_text
    assert "Adolescents 14–18" in item_text  # en-dash
    assert "English" in item_text and "Spanish" in item_text


async def test_list_client_referral_falls_back_to_synthesized_title(
    authenticated_client: AsyncClient,
    db_test_session_manager: async_sessionmaker[AsyncSession],
    logged_in_user: User,
):
    """A `client_referral` with an empty description (defensive — the
    wire schema requires one today, but persisted blanks could exist)
    falls back to the synthesized `Seeking in <city>, <state>` headline
    so the row is never link-text-empty."""
    author = create_test_user(username=f"author-{uuid.uuid4()}")
    post = _client_referral_post(
        description="",
        owner_id=author.id,
        location_city="Boise",
        location_state="ID",
    )
    async with db_test_session_manager() as session:
        async with session.begin():
            session.add(author)
            session.add(post)

    response = await authenticated_client.get("/posts")
    assert response.status_code == 200
    tree = HTMLParser(response.text)
    lead = tree.css_first("#posts-list > div a")
    assert lead is not None
    assert lead.text(strip=True) == "Seeking in Boise, ID"


async def test_list_provider_availability_item_shape(
    authenticated_client: AsyncClient,
    db_test_session_manager: async_sessionmaker[AsyncSession],
    logged_in_user: User,
):
    """A `provider_availability` `<li>` uses the linked Provider's
    `practice_name` as the lead (in `<strong>`) and renders a
    `Providing` chip — the standardized counterpart to `Seeking`."""
    author = create_test_user(username=f"author-{uuid.uuid4()}")
    practice_name = f"Practice-{uuid.uuid4()}"
    post = _provider_availability_post(
        practice_name=practice_name,
        owner_id=author.id,
        provider=make_provider(
            owner_id=author.id,
            practice_name=practice_name,
            location_city="Portland",
            location_state="OR",
            in_person_sessions="yes",
            virtual_sessions="no",
            accepts_in_network=True,
            accepts_out_of_network=False,
            sliding_scale=True,
        ),
    )
    async with db_test_session_manager() as session:
        async with session.begin():
            session.add(author)
            session.add(post.provider_availability_detail.provider)
            session.add(post)

    response = await authenticated_client.get("/posts")
    assert response.status_code == 200
    tree = HTMLParser(response.text)
    item = tree.css_first("#posts-list > div")
    assert item is not None
    assert item.attributes.get("data-kind") == "provider_availability"

    chip = item.css_first("[data-kind-chip]")
    assert chip is not None
    assert chip.text(strip=True) == "Providing"

    # Practice name is in <strong> inside the lead link.
    lead = item.css_first("a")
    assert lead is not None
    assert lead.css_first("strong").text(strip=True) == practice_name

    item_text = item.text()
    assert "Portland, OR" in item_text
    assert "In-person" in item_text


async def test_list_lead_contains_full_description_no_backend_truncation(
    authenticated_client: AsyncClient,
    db_test_session_manager: async_sessionmaker[AsyncSession],
    logged_in_user: User,
):
    """The lead `<a>` contains the post's full description text — no
    server-side `truncate()`. Visual clamping is CSS's job
    (`-webkit-line-clamp: 2` on the title `<p>`), so long descriptions
    stay in the DOM where `?q=` ILIKE filtering, search engines, and
    screen readers can see them. A regression that re-introduced a
    backend `truncate(N)` would silently lose text past N chars in
    the DOM and break this test."""
    author = create_test_user(username=f"author-{uuid.uuid4()}")
    # Description longer than any plausible visual-clamp budget — if
    # the backend truncates, this string won't appear intact in the DOM.
    description = (
        "Looking for a long-term outpatient therapist for a 17-year-old "
        "(she/her) with complex PTSD, emerging self-injury, and a recent "
        "psychiatric hospitalization. Mom is engaged and willing to do "
        "family work. We need someone trauma-trained who can hold a frame "
        "and ideally has DBT skills training to draw on. Aetna in-network "
        "preferred but we can flex on insurance for the right fit."
    )
    post = _client_referral_post(description=description, owner_id=author.id)
    async with db_test_session_manager() as session:
        async with session.begin():
            session.add(author)
            session.add(post)

    response = await authenticated_client.get("/posts")
    assert response.status_code == 200
    tree = HTMLParser(response.text)
    lead = tree.css_first("#posts-list > div a")
    assert lead is not None
    assert lead.text(strip=True) == description


async def test_list_meta_is_an_inline_list_of_li_chunks(
    authenticated_client: AsyncClient,
    db_test_session_manager: async_sessionmaker[AsyncSession],
    logged_in_user: User,
):
    """Each metadata fact is its own `<li>` inside a nested `<ul>`
    after the title link — the inline-list pattern. The `·` visual
    separator lives in CSS (`#posts-list > div > ul > li + li::before`)
    rather than the markup, so the DOM text has no `·` glyphs. A
    regression that collapsed the chunks back into a single
    `·`-joined string (or onto the title line) would fail here.

    Also: no owner-username link in the listing row. The author lives
    on the detail page; the listing reads as Craigslist, not as a feed
    of posts-by-people."""
    author = create_test_user(username=f"author-{uuid.uuid4()}")
    post = _client_referral_post(
        description="meta-shape",
        owner_id=author.id,
        location_city="Seattle",
        location_state="WA",
        location_in_person="yes",
        location_virtual="no",
        age_groups=["adolescents_14_18"],
        languages=["en"],
        insurance="in_network",
    )
    async with db_test_session_manager() as session:
        async with session.begin():
            session.add(author)
            session.add(post)

    response = await authenticated_client.get("/posts")
    assert response.status_code == 200
    tree = HTMLParser(response.text)
    item = tree.css_first("#posts-list > div")
    assert item is not None

    # Metadata is a nested `<ul>` of `<li>` chunks above the title —
    # the inline-list pattern. Date and the kind chip both live in
    # this list so the whole line reads uniformly. The outer
    # `#posts-list` `<ul>` keeps Pico-default bullets; the inner one
    # is styled inline by CSS in base.html.
    meta_chunks = item.css("ul > li")
    # date + Seeking + location + format + ages = 5 chunks.
    # (English-only languages are dropped by the macro since `en` is
    # the default; insurance is no longer in the listing meta —
    # readers go to the detail page for that.)
    assert len(meta_chunks) == 5
    rendered = [li.text(strip=True) for li in meta_chunks]
    # The first chunk is the formatted date — content depends on
    # `now()`, so just check it's non-empty rather than pin a value.
    assert rendered[0]
    assert rendered[1:] == [
        "Seeking",
        "Seattle, WA",
        "In-person",
        "Adolescents 14–18",
    ]
    # No `·` separator anywhere in the parsed DOM text — the glyph
    # lives in CSS `::before content`, not the HTML.
    assert "·" not in item.text()

    # No owner-username link in the listing row — only the lead link.
    links = item.css("a")
    assert len(links) == 1
    assert links[0].attributes.get("href") == f"/posts/{post.id}"
    assert author.username not in item.text()


async def test_list_renders_readable_date_format(
    authenticated_client: AsyncClient,
    db_test_session_manager: async_sessionmaker[AsyncSession],
    logged_in_user: User,
):
    """The leading date renders Craigslist-style (`May 15`) via the
    `format_post_date` Jinja filter — *not* the raw ISO `YYYY-MM-DD`
    that `post.created_at.date()` produced before. The date is the
    first chunk in the meta `<ul>`."""
    from datetime import datetime, timezone

    author = create_test_user(username=f"author-{uuid.uuid4()}")
    post = _client_referral_post(description="d", owner_id=author.id)
    # Force a known timestamp so the format assertion is stable.
    post.created_at = datetime(2025, 5, 15, 14, 30, tzinfo=timezone.utc)
    async with db_test_session_manager() as session:
        async with session.begin():
            session.add(author)
            session.add(post)

    response = await authenticated_client.get("/posts")
    assert response.status_code == 200
    tree = HTMLParser(response.text)
    item = tree.css_first("#posts-list > div")
    assert item is not None
    # First chunk of the meta `<ul>` is the leading date.
    date_cell = item.css_first("ul > li")
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
    post = _client_referral_post(description="crumb-x", owner_id=logged_in_user.id)
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


async def test_detail_renders_kind_chip_in_header(
    authenticated_client: AsyncClient,
    db_test_session_manager: async_sessionmaker[AsyncSession],
    logged_in_user: User,
):
    """The detail page header carries the kind chip + posted-by/posted-
    at metadata. App-wide H1 removal dropped the synthesized title
    that used to mirror the listing row; the chip now carries the
    "where am I" information."""
    post = _client_referral_post(
        description="header-echo",
        owner_id=logged_in_user.id,
        location_city="Boise",
        location_state="ID",
    )
    async with db_test_session_manager() as session:
        async with session.begin():
            session.add(post)
        await session.refresh(post)
        post_id = post.id

    response = await authenticated_client.get(f"/posts/{post_id}")
    assert response.status_code == 200
    tree = HTMLParser(response.text)
    chip = tree.css_first("article [data-kind-chip]")
    assert chip is not None
    assert chip.attributes.get("data-kind-chip") == "client_referral"
    assert chip.text(strip=True) == "Seeking"


async def test_detail_provider_availability_uses_providing_label(
    authenticated_client: AsyncClient,
    db_test_session_manager: async_sessionmaker[AsyncSession],
    logged_in_user: User,
):
    """The provider_availability detail header uses the standardized
    `Providing` chip — matched to the listing row, replacing the
    earlier `Offering` label."""
    practice_name = f"Practice-{uuid.uuid4()}"
    post = _provider_availability_post(
        practice_name=practice_name, owner_id=logged_in_user.id
    )
    async with db_test_session_manager() as session:
        async with session.begin():
            session.add(post)
        await session.refresh(post)
        post_id = post.id

    response = await authenticated_client.get(f"/posts/{post_id}")
    assert response.status_code == 200
    tree = HTMLParser(response.text)
    chip = tree.css_first("article [data-kind-chip]")
    assert chip is not None
    assert chip.text(strip=True) == "Providing"


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
    items = tree.css("#posts-list > div")
    assert len(items) == 1
    item_text = items[0].text()
    assert description in item_text
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
    items = tree.css("#posts-list > div")
    assert len(items) == 2
    assert newer.client_referral_detail.description in items[0].text()
    assert older.client_referral_detail.description in items[1].text()


# --- Update (PATCH) ------------------------------------------------------


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


async def test_list_page_renders_filter_form(
    authenticated_client: AsyncClient,
    logged_in_user: User,
):
    """The shared `index_filters.html` macro renders `<select name="kind">`
    + `<input type="search" name="q">` above the table. With no `?kind=`,
    the kind `<select>`'s "Any" placeholder option is selected."""
    response = await authenticated_client.get("/posts")
    assert response.status_code == 200
    tree = HTMLParser(response.text)

    form = tree.css_first("form.index-filters")
    assert form is not None
    assert form.attributes.get("action") == "/posts"

    kind_select = tree.css_first('form.index-filters select[name="kind"]')
    assert kind_select is not None
    options = kind_select.css("option")
    # Empty-string attribute values come back as `None` from selectolax;
    # treat them as the "Any" placeholder slot.
    values = [o.attributes.get("value") for o in options]
    assert None in values  # "Any" placeholder (value="")
    assert "client_referral" in values
    assert "provider_availability" in values
    # The "Any" placeholder is selected when no kind is in the URL.
    # `<option selected>` is a valueless attribute — selectolax stores
    # it as a `selected: None` key, so test for key presence.
    any_option = next(o for o in options if o.attributes.get("value") is None)
    assert "selected" in any_option.attributes
    assert any_option.text().strip() == "Any"

    q_input = tree.css_first('form.index-filters input[type="search"][name="q"]')
    assert q_input is not None


async def test_list_filters_by_kind_seeking(
    authenticated_client: AsyncClient,
    db_test_session_manager: async_sessionmaker[AsyncSession],
    logged_in_user: User,
):
    """`?kind=client_referral` keeps only seeking posts; the kind
    `<select>` preselects the matching option."""
    author = create_test_user(username=f"author-{uuid.uuid4()}")
    referral = _client_referral_post(
        description=f"ref-{uuid.uuid4()}", owner_id=author.id
    )
    availability = _provider_availability_post(
        practice_name=f"clinic-{uuid.uuid4()}", owner_id=author.id
    )
    async with db_test_session_manager() as session:
        async with session.begin():
            session.add(author)
            session.add(availability.provider_availability_detail.provider)
            session.add(referral)
            session.add(availability)

    response = await authenticated_client.get("/posts?kind=client_referral")
    assert response.status_code == 200
    tree = HTMLParser(response.text)
    rows = tree.css("#posts-list > div")
    assert len(rows) == 1
    assert rows[0].attributes.get("data-kind") == "client_referral"
    # The kind <select> preselects the seeking option.
    options = tree.css('form.index-filters select[name="kind"] option')
    selected_option = next(o for o in options if "selected" in o.attributes)
    assert selected_option.attributes.get("value") == "client_referral"
    # The kind chip is hidden on the cards when a single kind is selected —
    # it would be constant for every card on this page.
    assert tree.css("#posts-list > div [data-kind-chip]") == []


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
    `client_referral_detail` or `provider_availability_detail`."""
    author = create_test_user(username=f"author-{uuid.uuid4()}")
    seeking_match = _client_referral_post(
        description="needle-in-seeking", owner_id=author.id
    )
    seeking_miss = _client_referral_post(
        description="haystack-only-here", owner_id=author.id
    )
    offering_match = _provider_availability_post(
        practice_name=f"clinic-{uuid.uuid4()}",
        owner_id=author.id,
        description="needle-in-offering",
    )
    async with db_test_session_manager() as session:
        async with session.begin():
            session.add(author)
            session.add(offering_match.provider_availability_detail.provider)
            session.add(seeking_match)
            session.add(seeking_miss)
            session.add(offering_match)

    response = await authenticated_client.get("/posts?q=needle")
    assert response.status_code == 200
    tree = HTMLParser(response.text)
    rows = tree.css("#posts-list > div")
    # Both `needle-*` posts match across the polymorphic OR. The
    # `haystack-*` seeker is filtered out.
    assert len(rows) == 2
    kinds = sorted(r.attributes.get("data-kind") for r in rows)
    assert kinds == ["client_referral", "provider_availability"]
    # `q` value is echoed back into the input so the form reflects the URL.
    q_input = tree.css_first('form.index-filters input[name="q"]')
    assert q_input.attributes.get("value") == "needle"


async def test_list_combines_kind_and_q_with_and(
    authenticated_client: AsyncClient,
    db_test_session_manager: async_sessionmaker[AsyncSession],
    logged_in_user: User,
):
    """`?kind=client_referral&q=needle` ANDs both predicates — only
    seeking posts whose description matches."""
    author = create_test_user(username=f"author-{uuid.uuid4()}")
    seeking_match = _client_referral_post(
        description="needle-seeking", owner_id=author.id
    )
    offering_with_needle = _provider_availability_post(
        practice_name=f"clinic-{uuid.uuid4()}",
        owner_id=author.id,
        description="needle-offering",
    )
    async with db_test_session_manager() as session:
        async with session.begin():
            session.add(author)
            session.add(offering_with_needle.provider_availability_detail.provider)
            session.add(seeking_match)
            session.add(offering_with_needle)

    response = await authenticated_client.get("/posts?kind=client_referral&q=needle")
    assert response.status_code == 200
    tree = HTMLParser(response.text)
    rows = tree.css("#posts-list > div")
    assert len(rows) == 1
    assert rows[0].attributes.get("data-kind") == "client_referral"


# --- Per-column filters: posted_by / state / city / age_group / language ---


async def test_list_filters_by_posted_by_username(
    authenticated_client: AsyncClient,
    db_test_session_manager: async_sessionmaker[AsyncSession],
    logged_in_user: User,
):
    """`?posted_by=substr` filters by ILIKE on owner.username."""
    alice = create_test_user(username=f"alice-{uuid.uuid4()}")
    bob = create_test_user(username=f"bob-{uuid.uuid4()}")
    alice_post = _client_referral_post(description="a", owner_id=alice.id)
    bob_post = _client_referral_post(description="b", owner_id=bob.id)
    async with db_test_session_manager() as session:
        async with session.begin():
            session.add(alice)
            session.add(bob)
            session.add(alice_post)
            session.add(bob_post)

    response = await authenticated_client.get("/posts?posted_by=alice")
    assert response.status_code == 200
    tree = HTMLParser(response.text)
    rows = tree.css("#posts-list > div")
    assert len(rows) == 1
    assert rows[0].attributes.get("data-row-id") == str(alice_post.id)
    # The text input echoes the URL value.
    posted_by_input = tree.css_first('form.index-filters input[name="posted_by"]')
    assert posted_by_input.attributes.get("value") == "alice"


async def test_list_filters_by_state_across_polymorphic_paths(
    authenticated_client: AsyncClient,
    db_test_session_manager: async_sessionmaker[AsyncSession],
    logged_in_user: User,
):
    """`?state=NY&state=NJ` matches both detail tables: seeking's
    `client_referral_detail.location_state` and offering's
    `provider_availability_detail.provider.location_state`."""
    author = create_test_user(username=f"author-{uuid.uuid4()}")
    seeking_ny = _client_referral_post(
        description="seeking-ny", owner_id=author.id, location_state="NY"
    )
    seeking_ca = _client_referral_post(
        description="seeking-ca", owner_id=author.id, location_state="CA"
    )
    offering_nj = _provider_availability_post(
        practice_name=f"clinic-{uuid.uuid4()}",
        owner_id=author.id,
        provider=make_provider(
            owner_id=author.id,
            practice_name=f"clinic-{uuid.uuid4()}",
            location_state="NJ",
        ),
    )
    offering_tx = _provider_availability_post(
        practice_name=f"clinic-{uuid.uuid4()}",
        owner_id=author.id,
        provider=make_provider(
            owner_id=author.id,
            practice_name=f"clinic-{uuid.uuid4()}",
            location_state="TX",
        ),
    )
    async with db_test_session_manager() as session:
        async with session.begin():
            session.add(author)
            session.add(offering_nj.provider_availability_detail.provider)
            session.add(offering_tx.provider_availability_detail.provider)
            session.add(seeking_ny)
            session.add(seeking_ca)
            session.add(offering_nj)
            session.add(offering_tx)

    response = await authenticated_client.get("/posts?state=NY&state=NJ")
    assert response.status_code == 200
    tree = HTMLParser(response.text)
    rows = tree.css("#posts-list > div")
    row_ids = {r.attributes.get("data-row-id") for r in rows}
    assert row_ids == {str(seeking_ny.id), str(offering_nj.id)}
    # Both NY and NJ options are preselected in the multi-<select>.
    options = tree.css('form.index-filters select[name="state"] option')
    selected = {
        o.attributes.get("value") for o in options if "selected" in o.attributes
    }
    assert selected == {"NY", "NJ"}


async def test_list_filters_by_city_substring_across_polymorphic_paths(
    authenticated_client: AsyncClient,
    db_test_session_manager: async_sessionmaker[AsyncSession],
    logged_in_user: User,
):
    """`?city=spring` ILIKE-matches `location_city` on both detail tables."""
    author = create_test_user(username=f"author-{uuid.uuid4()}")
    seeking_match = _client_referral_post(
        description="s", owner_id=author.id, location_city="Springfield"
    )
    seeking_miss = _client_referral_post(
        description="s", owner_id=author.id, location_city="Hartford"
    )
    offering_match = _provider_availability_post(
        practice_name=f"clinic-{uuid.uuid4()}",
        owner_id=author.id,
        provider=make_provider(
            owner_id=author.id,
            practice_name=f"clinic-{uuid.uuid4()}",
            location_city="Spring Hill",
        ),
    )
    async with db_test_session_manager() as session:
        async with session.begin():
            session.add(author)
            session.add(offering_match.provider_availability_detail.provider)
            session.add(seeking_match)
            session.add(seeking_miss)
            session.add(offering_match)

    response = await authenticated_client.get("/posts?city=spring")
    assert response.status_code == 200
    tree = HTMLParser(response.text)
    row_ids = {r.attributes.get("data-row-id") for r in tree.css("#posts-list > div")}
    assert row_ids == {str(seeking_match.id), str(offering_match.id)}


async def test_list_filters_by_age_group_json_contains(
    authenticated_client: AsyncClient,
    db_test_session_manager: async_sessionmaker[AsyncSession],
    logged_in_user: User,
):
    """`?age_group=adults_25_64` matches posts whose detail's
    `age_groups` JSON array contains that token, on either side."""
    author = create_test_user(username=f"author-{uuid.uuid4()}")
    seeking_match = _client_referral_post(
        description="s",
        owner_id=author.id,
        age_groups=["adults_25_64"],
    )
    seeking_miss = _client_referral_post(
        description="s",
        owner_id=author.id,
        age_groups=["children_0_5"],
    )
    offering_match = _provider_availability_post(
        practice_name=f"clinic-{uuid.uuid4()}",
        owner_id=author.id,
        age_groups=["adults_25_64", "older_adults_65_plus"],
    )
    async with db_test_session_manager() as session:
        async with session.begin():
            session.add(author)
            session.add(offering_match.provider_availability_detail.provider)
            session.add(seeking_match)
            session.add(seeking_miss)
            session.add(offering_match)

    response = await authenticated_client.get("/posts?age_group=adults_25_64")
    assert response.status_code == 200
    tree = HTMLParser(response.text)
    row_ids = {r.attributes.get("data-row-id") for r in tree.css("#posts-list > div")}
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
    spanish_seeker = _client_referral_post(
        description="s", owner_id=author.id, languages=["en", "es"]
    )
    english_only = _client_referral_post(
        description="e", owner_id=author.id, languages=["en"]
    )
    async with db_test_session_manager() as session:
        async with session.begin():
            session.add(author)
            session.add(spanish_seeker)
            session.add(english_only)

    response = await authenticated_client.get("/posts?language=es")
    assert response.status_code == 200
    tree = HTMLParser(response.text)
    rows = tree.css("#posts-list > div")
    assert len(rows) == 1
    assert rows[0].attributes.get("data-row-id") == str(spanish_seeker.id)


async def test_list_renders_one_control_per_declared_filter(
    authenticated_client: AsyncClient,
    logged_in_user: User,
):
    """The filter form has a `<label>` per declared filter on
    POST_ENTITY. This is the exportable-pattern guarantee — adding a
    Filter to the spec lights up a control on the page without any
    template edit."""
    response = await authenticated_client.get("/posts")
    assert response.status_code == 200
    tree = HTMLParser(response.text)
    form = tree.css_first("form.index-filters")
    assert form is not None
    # Every Filter declared on POST_ENTITY appears once.
    labels = {l.text().strip().split("\n")[0].strip() for l in form.css("label")}
    expected = {
        "Type",
        "Description",
        "Posted by",
        "State",
        "City",
        "Age groups",
        "Languages",
    }
    assert expected <= labels


# --- Chrome: edit form cancel link --------------------------------------


async def test_edit_client_referral_form_renders_cancel(
    authenticated_client: AsyncClient,
    db_test_session_manager: async_sessionmaker[AsyncSession],
    logged_in_user: User,
):
    """Edit form keeps a bottom Cancel link to the post detail page."""
    post = _client_referral_post(description="x", owner_id=logged_in_user.id)
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


async def test_client_referral_form_renders_languages_multi_select(
    authenticated_client: AsyncClient,
    logged_in_user: User,
):
    """`languages` on CR renders via `field_for`'s multi_select arm (#428),
    same shape as PA."""
    response = await authenticated_client.get("/posts/form?kind=client_referral")
    assert response.status_code == 200
    tree = HTMLParser(response.text)
    boxes = tree.css('input[type="checkbox"][name="languages"]')
    values = {b.attributes.get("value") for b in boxes}
    assert values == {"en", "es"}


async def test_client_referral_form_renders_age_groups_multi_select(
    authenticated_client: AsyncClient,
    logged_in_user: User,
):
    """`age_groups` on CR renders via the multi-select arm (#432),
    mirroring PA's `age_groups` (#430)."""
    response = await authenticated_client.get("/posts/form?kind=client_referral")
    assert response.status_code == 200
    tree = HTMLParser(response.text)
    boxes = tree.css('input[type="checkbox"][name="age_groups"]')
    values = {b.attributes.get("value") for b in boxes}
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
    form. The picker has one link per kind round-tripping back with
    `?kind=…`."""
    response = await authenticated_client.get("/posts/form")
    assert response.status_code == 200
    tree = HTMLParser(response.text)
    # No `<input name="kind">` — that lives on the kind-specific forms,
    # not the picker.
    assert tree.css_first('input[name="kind"]') is None
    # Each registered kind has a link on the picker.
    assert tree.css_first('a[href="/posts/form?kind=client_referral"]') is not None
    assert (
        tree.css_first('a[href="/posts/form?kind=provider_availability"]') is not None
    )


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
    assert tree.css_first('a[href="/posts/form?kind=client_referral"]') is not None


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
    # The kind chunk renders `Seeking` (not the longer `client referral`
    # label) — the chip text is what the user actually sees.
    assert "Seeking" in page


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
        # Practice name lives on the linked Provider post-#448; dereference.
        assert refreshed.provider_availability_detail.provider.practice_name == original
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
        # `description` is a valid PA Update field — schema passes; the 400
        # comes from the post-validation kind-mismatch check, which is the
        # behavior under test. (Practice name moved to Provider post-#448
        # and is no longer a PA wire field, so it can't be used here.)
        data={"kind": "provider_availability", "description": "hijack"},
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
    # PA points at a Provider via `provider_id` (#448); seed one owned by
    # the requesting user so the FK resolves at write time.
    provider = make_provider(owner_id=logged_in_user.id, practice_name=practice_name)
    async with db_test_session_manager() as session:
        async with session.begin():
            session.add(provider)

    response = await authenticated_client.post(
        "/posts",
        data=provider_availability_payload(provider_id=str(provider.id)),
    )

    assert response.status_code == 201
    new_id = uuid.UUID(response.json()["id"])

    async with db_test_session_manager() as session:
        result = await session.execute(select(Post).filter(Post.id == new_id))
        persisted = result.scalars().first()
        assert persisted is not None
        assert persisted.kind == "provider_availability"
        assert persisted.provider_availability_detail.provider_id == provider.id
        assert (
            persisted.provider_availability_detail.provider.practice_name
            == practice_name
        )
        # Insurance posture / sliding-scale / cost live on Provider (#449),
        # not PA. The linked Provider's defaults match the `make_provider`
        # factory: self-pay-only, no carriers, no sliding scale.
        assert (
            persisted.provider_availability_detail.provider.accepts_in_network is False
        )
        assert (
            persisted.provider_availability_detail.provider.accepts_out_of_network
            is False
        )
        assert persisted.provider_availability_detail.provider.sliding_scale is False
        assert persisted.client_referral_detail is None
        assert persisted.owner_id == logged_in_user.id

    async with db_test_session_manager() as session:
        repo = AuditRepository(session)
        rows = await repo.list_for_resource(resource_type="post", resource_id=new_id)
        assert len(rows) == 1
        assert rows[0].action == "create_post"
        assert rows[0].before is None
        expected = provider_availability_payload(provider_id=str(provider.id))
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
    """Whitespace stripping applies to PA's remaining free-text wire fields.
    (Practice-name whitespace stripping is exercised on Provider post-#448.)"""
    provider = make_provider(owner_id=logged_in_user.id)
    async with db_test_session_manager() as session:
        async with session.begin():
            session.add(provider)

    response = await authenticated_client.post(
        "/posts",
        data=provider_availability_payload(
            provider_id=str(provider.id), description="  Lead pitch  "
        ),
    )
    assert response.status_code == 201
    new_id = uuid.UUID(response.json()["id"])

    async with db_test_session_manager() as session:
        result = await session.execute(select(Post).filter(Post.id == new_id))
        persisted = result.scalars().first()
        assert persisted.provider_availability_detail.description == "Lead pitch"


@pytest.mark.parametrize(
    "payload",
    [
        {"kind": "provider_availability"},  # missing every required field
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
    db_test_session_manager: async_sessionmaker[AsyncSession],
    logged_in_user: User,
):
    """`GET /posts/form?kind=provider_availability` renders the kind-specific
    create form. Per #448, the form needs the user to own at least one
    Provider profile (otherwise it shows the create-a-provider stub)."""
    provider = make_provider(owner_id=logged_in_user.id)
    async with db_test_session_manager() as session:
        async with session.begin():
            session.add(provider)

    response = await authenticated_client.get("/posts/form?kind=provider_availability")
    assert response.status_code == 200
    tree = HTMLParser(response.text)
    form = tree.css_first("form")
    assert form is not None
    assert form.attributes.get("hx-post") == "/posts"
    # `provider_id` is now a <select> over the user's owned Providers (#448).
    assert tree.css_first("select#provider_id") is not None
    kind_input = tree.css_first('input[name="kind"]')
    assert kind_input is not None
    assert kind_input.attributes.get("value") == "provider_availability"


async def test_provider_availability_form_renders_free_text_fields(
    authenticated_client: AsyncClient,
    db_test_session_manager: async_sessionmaker[AsyncSession],
    logged_in_user: User,
):
    """The three free-text fields render through `field_for` — `description`
    and `referral_instructions` as `<textarea>` (driven by the `HtmlTextarea`
    marker on the schema), `website` as `<input type="url">` (driven by
    `HtmlUrl` — #446). A regression where either marker stops being picked
    up would render fields as the wrong control and silently break the form."""
    provider = make_provider(owner_id=logged_in_user.id)
    async with db_test_session_manager() as session:
        async with session.begin():
            session.add(provider)

    response = await authenticated_client.get("/posts/form?kind=provider_availability")
    assert response.status_code == 200
    tree = HTMLParser(response.text)
    assert tree.css_first("textarea#description") is not None
    assert tree.css_first("textarea#referral_instructions") is not None
    website = tree.css_first("input#website")
    assert website is not None
    assert website.attributes.get("type") == "url"


async def test_provider_availability_form_renders_languages_multi_select(
    authenticated_client: AsyncClient,
    db_test_session_manager: async_sessionmaker[AsyncSession],
    logged_in_user: User,
):
    """`languages` renders as a multi-select checkbox group via `field_for`'s
    new `list[Literal[*T]]` arm (#425). Confirms the schema-driven multi-
    select dispatch is wired end-to-end."""
    provider = make_provider(owner_id=logged_in_user.id)
    async with db_test_session_manager() as session:
        async with session.begin():
            session.add(provider)

    response = await authenticated_client.get("/posts/form?kind=provider_availability")
    assert response.status_code == 200
    tree = HTMLParser(response.text)
    boxes = tree.css('input[type="checkbox"][name="languages"]')
    values = {b.attributes.get("value") for b in boxes}
    assert values == {"en", "es"}
    assert "English" in response.text
    assert "Spanish" in response.text


async def test_provider_availability_form_renders_age_groups_multi_select(
    authenticated_client: AsyncClient,
    db_test_session_manager: async_sessionmaker[AsyncSession],
    logged_in_user: User,
):
    """`age_groups` renders as a 7-option multi-select checkbox group via
    `field_for`'s `list[Literal[*T]]` arm (#430). First 7-option consumer
    of the multi-select rails."""
    provider = make_provider(owner_id=logged_in_user.id)
    async with db_test_session_manager() as session:
        async with session.begin():
            session.add(provider)

    response = await authenticated_client.get("/posts/form?kind=provider_availability")
    assert response.status_code == 200
    tree = HTMLParser(response.text)
    boxes = tree.css('input[type="checkbox"][name="age_groups"]')
    values = {b.attributes.get("value") for b in boxes}
    assert values == {
        "children_0_5",
        "children_6_10",
        "preteens_11_13",
        "adolescents_14_18",
        "young_adults_19_24",
        "adults_25_64",
        "older_adults_65_plus",
    }


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
    # The kind chunk renders `Providing` (not the longer `provider
    # availability` label) — the chip text is what the user sees.
    assert "Providing" in page


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
    form with the linked Provider preselected in the dropdown."""
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
    # The linked Provider's row appears as the selected `<option>` (#448).
    provider_select = tree.css_first("select#provider_id")
    assert provider_select is not None
    selected = provider_select.css_first("option[selected]")
    assert selected is not None
    assert selected.text(strip=True) == practice_name
    kind_input = tree.css_first('input[name="kind"]')
    assert kind_input is not None
    assert kind_input.attributes.get("value") == "provider_availability"


async def test_owner_can_patch_provider_availability_description(
    authenticated_client: AsyncClient,
    db_test_session_manager: async_sessionmaker[AsyncSession],
    logged_in_user: User,
):
    """Patch a PA field (`description`) and confirm round-trip + read body.
    (Practice name moved to Provider post-#448 and is no longer a PA wire
    field — the parallel test for renaming a practice lives on Provider.)"""
    post = _provider_availability_post(practice_name="orig", owner_id=logged_in_user.id)
    async with db_test_session_manager() as session:
        async with session.begin():
            session.add(post)

    new_description = f"Renamed-{uuid.uuid4()}"
    response = await authenticated_client.patch(
        f"/posts/{post.id}",
        data={
            "kind": "provider_availability",
            "description": new_description,
        },
    )
    assert response.status_code == 200
    assert response.headers.get("HX-Redirect") == f"/posts/{post.id}"
    body = response.json()
    assert body["kind"] == "provider_availability"
    assert body["description"] == new_description
    assert "title" not in body and "body" not in body

    async with db_test_session_manager() as session:
        result = await session.execute(select(Post).filter(Post.id == post.id))
        refreshed = result.scalars().first()
        assert refreshed.provider_availability_detail.description == new_description


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
    """Per #448 the PA audit snapshot records `provider_id` instead of the
    six fields that moved to Provider (`practice_name`, `location_*`,
    `*_sessions`)."""
    practice_name = f"doomed-{uuid.uuid4()}"
    post = _provider_availability_post(
        practice_name=practice_name, owner_id=logged_in_user.id
    )
    provider_id = post.provider_availability_detail.provider_id
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
            **provider_availability_payload(provider_id=str(provider_id)),
            "owner_id": str(logged_in_user.id),
        }
        assert rows[0].after is None
