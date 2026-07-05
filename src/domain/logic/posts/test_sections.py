"""Tests for the referral section-title single source."""

from __future__ import annotations

from src.domain.logic.posts.sections import (
    REFERRAL_SECTION_ORDER,
    REFERRAL_SECTIONS,
)


def test_section_order_covers_every_named_section_once() -> None:
    """`REFERRAL_SECTION_ORDER` lists every section in `REFERRAL_SECTIONS`
    exactly once — so a section added to the namespace can't be silently
    dropped from (or duplicated in) the ordered contract the form and
    detail render from."""
    named = list(vars(REFERRAL_SECTIONS).values())
    assert list(REFERRAL_SECTION_ORDER) == named
