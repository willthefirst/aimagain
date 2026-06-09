"""Redaction behaviour of the shared `_clinician_card.html` macro.

`CLINICIAN_ENTITY` no longer carries a `read_policy` (see
`src/domain/specs/clinician.py`) — the directory page renders for every
authenticated viewer. Identifying fields (name, practice org name,
location) instead redact per-row at render time when the viewer lacks
provider-network access AND isn't the owner. The viewer's own rows
always render un-redacted so they can self-manage what they created
before clearing network verification.

These tests render the macro directly with synthetic clinicians + viewer
ids to pin the four combinations:

    | can_access_network | owner == viewer | rendered                       |
    | ------------------ | --------------- | ------------------------------ |
    | True               | any             | un-redacted (network bypass)   |
    | False              | True            | un-redacted (owner override)   |
    | False              | False           | redacted: locked_name + locked_field |

The owner-self bypass is the new contract; without it a verified-network
flip would suddenly hide a user's own clinician from them.
"""

from __future__ import annotations

import textwrap
import uuid
from types import SimpleNamespace

from jinja2 import Environment
from selectolax.parser import HTMLParser

from src.framework.templates._test_env import make_test_env


def _make_env() -> Environment:
    return make_test_env()


def _clinician(*, owner_id, org_name="Open House", city="Brooklyn", state="NY"):
    """Build the minimal duck-typed clinician the card reads."""
    org = SimpleNamespace(id=uuid.uuid4(), name=org_name)
    aff = SimpleNamespace(
        org=org,
        org_id=org.id,
        location_city=city,
        location_state=state,
    )
    return SimpleNamespace(
        id=uuid.uuid4(),
        owner_id=owner_id,
        clinician_affiliations=[aff],
        licensures=[SimpleNamespace(issuing_state="NY")],
        first_name="Jane",
        last_name="Doe",
    )


def _render_card(
    env: Environment,
    *,
    clinician,
    can_access_network: bool,
    current_user_id,
) -> str:
    """Render the card macro with the chrome context the macro reads."""
    snippet = textwrap.dedent("""\
        {%- from "_shared/_clinician_card.html" import clinician_card with context -%}
        {{ clinician_card(clinician) }}
        """)
    return env.from_string(snippet).render(
        clinician=clinician,
        can_access_network=can_access_network,
        current_user_id=current_user_id,
    )


def test_un_redacted_when_viewer_has_network_access() -> None:
    """A network-verified viewer sees every identifying field — the
    `not can_access_network` half of the redaction predicate fails, so
    redaction never fires regardless of ownership."""
    env = _make_env()
    other_id, viewer_id = uuid.uuid4(), uuid.uuid4()
    html = _render_card(
        env,
        clinician=_clinician(owner_id=other_id),
        can_access_network=True,
        current_user_id=viewer_id,
    )
    tree = HTMLParser(html)
    assert tree.css_first(".locked-ghost-btn") is None
    assert "Jane Doe" in html
    practice = tree.css_first('div[data-fact="practice"] dd')
    assert practice is not None and "Open House" in practice.text()
    location = tree.css_first('div[data-fact="location"] dd')
    assert location is not None and "Brooklyn" in location.text()


def test_un_redacted_when_viewer_owns_the_row() -> None:
    """Owner-self bypass: a non-network viewer sees their OWN clinician
    un-redacted so they can manage what they created before clearing
    network verification."""
    env = _make_env()
    viewer_id = uuid.uuid4()
    html = _render_card(
        env,
        clinician=_clinician(owner_id=viewer_id),
        can_access_network=False,
        current_user_id=viewer_id,
    )
    tree = HTMLParser(html)
    assert tree.css_first(".locked-ghost-btn") is None
    assert "Jane Doe" in html


def test_redacted_when_viewer_not_owner_and_not_network() -> None:
    """The redaction branch: a non-network viewer looking at another
    user's row sees the headline name replaced by `locked_name`'s
    `<button class="locked-ghost-btn">Dr. J. Doe</button>` placeholder,
    and the practice + location rows replaced by `locked_field`'s
    redacted-dots placeholder."""
    env = _make_env()
    other_id, viewer_id = uuid.uuid4(), uuid.uuid4()
    html = _render_card(
        env,
        clinician=_clinician(owner_id=other_id),
        can_access_network=False,
        current_user_id=viewer_id,
    )
    tree = HTMLParser(html)
    # Headline: locked_name placeholder, not the real name. No <a> wraps
    # the H3 because the card macro skips the anchor when `headline_url`
    # is None.
    h3 = tree.css_first("h3")
    assert h3 is not None
    assert "Jane Doe" not in h3.text()
    assert "Dr. J. Doe" in h3.text()
    assert h3.css_first("a") is None
    # Practice + location facts render the locked redacted-dots span.
    practice = tree.css_first('div[data-fact="practice"] dd .locked-redacted')
    assert practice is not None
    location = tree.css_first('div[data-fact="location"] dd .locked-redacted')
    assert location is not None
    # Org name itself never reaches the DOM.
    assert "Open House" not in html
