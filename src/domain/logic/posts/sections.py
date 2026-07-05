"""Canonical section titles for the referral form and its detail mirror.

The referral create/edit form (`domain/templates/posts/_form_referral.html`)
and the read-side detail (`domain/templates/posts/_shared/_referral_facts.html`)
group the same fields under the same titled sections — the read view
mirrors the write view (`test_referral_detail_groups_facts_like_the_form`
pins that). These titles are a copy *contract* shared across both
templates and the tests that assert them.

Keeping the strings here (exposed as the `REFERRAL_SECTIONS` Jinja global
and imported directly by tests) makes that contract single-sourced: a
rename is one edit and cannot drift between the form heading
(`form_section(...)`) and the detail heading (`fact_group(...)`). The
per-section *descriptions* on the form (the `<hgroup>` perspective lines)
stay inline in the form template — they're write-side guidance, not part
of the mirror.
"""

from __future__ import annotations

from types import SimpleNamespace

# Section titles, keyed by role. Attribute access works in both Jinja
# (`REFERRAL_SECTIONS.logistics`) and Python (tests).
REFERRAL_SECTIONS = SimpleNamespace(
    logistics="Logistics",
    service_type="Service type",
    about_client="About the client",
    payment="Payment options",
)

# The four sections in form (and mirrored detail) order. The detail
# suppresses empty groups, so a given render may show a subset — but any
# titles it shows appear in this order.
REFERRAL_SECTION_ORDER: tuple[str, ...] = (
    REFERRAL_SECTIONS.logistics,
    REFERRAL_SECTIONS.service_type,
    REFERRAL_SECTIONS.about_client,
    REFERRAL_SECTIONS.payment,
)
