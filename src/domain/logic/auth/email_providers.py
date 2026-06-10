"""Webmail-provider smart-link lookup for the "check your email" CTA.

Stripe-style: when we recognize the email's domain as a webmail provider
that supports a URL-driven inbox search, return an "Open Gmail" / "Open
Yahoo Mail" deep link pre-filtered to messages from our verify sender.
When we don't, return ``(None, None, None)`` — the page falls back to a
plain "check your inbox" sentence with no link.

The table is deliberately conservative: only providers whose URL search
syntax is publicly documented and stable land here. Providers without
URL-driven search (Outlook, iCloud, AOL, Proton) fall back to the plain
sentence rather than ship a misleading "Open X" button that lands on
the inbox root.

``ios_app_url`` is the iOS URL scheme that opens the provider's native
app — only set when the provider publishes one. On iOS, mobile Safari
opens ``https://mail.google.com/...`` in mobile web rather than handing
off to the Gmail app (universal links don't fire reliably for
``target="_blank"`` navigations), so the template overrides the click
on iPhone/iPad to use the ``googlegmail://`` scheme instead. The scheme
opens Gmail at its default inbox view — the inbox search filter is
lost, but the verification email is the most recent so it sits at the
top anyway.
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


# `(label, web_url_builder, ios_app_url)`. ``ios_app_url`` is the URL
# scheme that opens the provider's native iOS app — None when the
# provider doesn't publish one we trust.
_PROVIDERS: dict[str, tuple[str, Callable[[str], str], str | None]] = {
    "gmail.com": ("Gmail", _gmail_search_url, "googlegmail://"),
    "googlemail.com": ("Gmail", _gmail_search_url, "googlegmail://"),
    "yahoo.com": ("Yahoo Mail", _yahoo_search_url, None),
    "yahoo.co.uk": ("Yahoo Mail", _yahoo_search_url, None),
}


def email_provider_search_url(
    email: str, from_address: str
) -> tuple[str | None, str | None, str | None]:
    """Return ``(provider_label, web_search_url, ios_app_url)`` for a
    recognized webmail provider, or ``(None, None, None)`` when the
    domain isn't in the table.

    ``provider_label`` is the human-readable name used in CTA copy
    ("Open Gmail"). ``web_search_url`` opens that provider's inbox
    pre-filtered to messages from ``from_address``. ``ios_app_url`` is
    the URL scheme the template uses on iOS to hand off to the
    provider's native app instead of loading mobile web; ``None`` when
    the provider doesn't publish one.
    """
    if "@" not in email:
        return None, None, None
    local, _, domain = email.rpartition("@")
    local = local.strip()
    domain = domain.strip().lower()
    if not local or not domain:
        return None, None, None
    entry = _PROVIDERS.get(domain)
    if entry is None:
        return None, None, None
    label, builder, ios_url = entry
    return label, builder(from_address), ios_url
