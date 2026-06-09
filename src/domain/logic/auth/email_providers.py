"""Webmail-provider smart-link lookup for the "check your email" CTA.

Stripe-style: when we recognize the email's domain as a webmail provider
that supports a URL-driven inbox search, return an "Open Gmail" / "Open
Yahoo Mail" deep link pre-filtered to messages from our verify sender.
When we don't, return ``(None, None)`` — the page falls back to a plain
"check your inbox" sentence with no link.

The table is deliberately conservative: only providers whose URL search
syntax is publicly documented and stable land here. Providers without
URL-driven search (Outlook, iCloud, AOL, Proton) fall back to the plain
sentence rather than ship a misleading "Open X" button that lands on
the inbox root.
"""

from __future__ import annotations

from typing import Callable
from urllib.parse import quote


def _gmail_search_url(from_address: str) -> str:
    # Gmail honors `#search/<query>` on its hash route. The query is the
    # same syntax shown in the search box, so `from:<addr>` filters by
    # sender. quote(safe="") encodes ":" and "@" so the URL fragment
    # survives intact across clients.
    query = quote(f"from:{from_address}", safe="")
    return f"https://mail.google.com/mail/u/0/#search/{query}"


def _yahoo_search_url(from_address: str) -> str:
    query = quote(f"from:{from_address}", safe="")
    return f"https://mail.yahoo.com/d/search/keyword={query}"


_PROVIDERS: dict[str, tuple[str, Callable[[str], str]]] = {
    "gmail.com": ("Gmail", _gmail_search_url),
    "googlemail.com": ("Gmail", _gmail_search_url),
    "yahoo.com": ("Yahoo Mail", _yahoo_search_url),
    "yahoo.co.uk": ("Yahoo Mail", _yahoo_search_url),
}


def email_provider_search_url(
    email: str, from_address: str
) -> tuple[str | None, str | None]:
    """Return ``(provider_label, search_url)`` for a recognized webmail
    provider, or ``(None, None)`` when the domain isn't in the table.

    ``provider_label`` is the human-readable name used in CTA copy
    ("Open Gmail"). ``search_url`` opens that provider's inbox
    pre-filtered to messages from ``from_address``.
    """
    if "@" not in email:
        return None, None
    local, _, domain = email.rpartition("@")
    local = local.strip()
    domain = domain.strip().lower()
    if not local or not domain:
        return None, None
    entry = _PROVIDERS.get(domain)
    if entry is None:
        return None, None
    label, builder = entry
    return label, builder(from_address)
