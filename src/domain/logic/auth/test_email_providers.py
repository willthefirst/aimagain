"""Tests for `src/domain/logic/auth/email_providers.py`.

Pin the URL shape for every supported provider so a silent drift in the
table (or a botched URL-encode of the ``from`` address) trips a test
rather than ships a broken "Open Gmail" button.
"""

from __future__ import annotations

import pytest

from src.domain.logic.auth.email_providers import email_provider_search_url

FROM = "no-reply@bedlamconnect.com"
ENCODED_QUERY = "from%3Ano-reply%40bedlamconnect.com"


@pytest.mark.parametrize(
    "email,expected_label,expected_url",
    [
        (
            "alice@gmail.com",
            "Gmail",
            f"https://mail.google.com/mail/u/0/#search/{ENCODED_QUERY}",
        ),
        (
            "ALICE@GMAIL.COM",
            "Gmail",
            f"https://mail.google.com/mail/u/0/#search/{ENCODED_QUERY}",
        ),
        (
            "bob@googlemail.com",
            "Gmail",
            f"https://mail.google.com/mail/u/0/#search/{ENCODED_QUERY}",
        ),
        (
            "carol@yahoo.com",
            "Yahoo Mail",
            f"https://mail.yahoo.com/d/search/keyword={ENCODED_QUERY}",
        ),
        (
            "dave@yahoo.co.uk",
            "Yahoo Mail",
            f"https://mail.yahoo.com/d/search/keyword={ENCODED_QUERY}",
        ),
    ],
)
def test_known_provider_returns_label_and_search_url(
    email: str, expected_label: str, expected_url: str
):
    label, url = email_provider_search_url(email, FROM)
    assert label == expected_label
    assert url == expected_url


@pytest.mark.parametrize(
    "email",
    [
        # Providers without a documented URL-driven search → fall back
        # to the plain sentence rather than ship a misleading button.
        "alice@outlook.com",
        "alice@hotmail.com",
        "alice@icloud.com",
        "alice@aol.com",
        "alice@proton.me",
        # Custom / unknown domains.
        "alice@example.com",
        "alice@somecompany.io",
    ],
)
def test_unknown_provider_returns_none(email: str):
    label, url = email_provider_search_url(email, FROM)
    assert label is None
    assert url is None


@pytest.mark.parametrize("malformed", ["", "noatsign", "alice@", "@gmail.com"])
def test_malformed_email_returns_none(malformed: str):
    label, url = email_provider_search_url(malformed, FROM)
    assert label is None
    assert url is None


def test_from_address_is_url_encoded():
    """A from address with characters that need encoding (`+`, spaces)
    must still produce a valid URL fragment."""
    label, url = email_provider_search_url(
        "alice@gmail.com", "no-reply+verify@bedlamconnect.com"
    )
    assert label == "Gmail"
    # `+` must be percent-encoded (Gmail's hash-search treats `+` as
    # operator-ish in some clients; safer to encode).
    assert "%2B" in url
    assert "no-reply%2Bverify%40bedlamconnect.com" in url
