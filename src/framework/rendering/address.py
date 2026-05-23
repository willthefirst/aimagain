"""Address composition helpers — domain-agnostic text formatters.

Templates that render an address row (`provider.full_address`,
`post.full_address`) read a pre-composed string instead of re-checking
each location field. The composition logic was previously duplicated in
`src/domain/logic/posts/view.py` and `src/domain/logic/providers/view.py`
because cross-cluster imports between domain logic modules aren't
allowed — the framework is the right home for the shared shape.
"""

from __future__ import annotations


def full_address(
    city: str | None, state: str | None, zip_code: str | None
) -> str | None:
    """Compose ``"City, ST ZIP"`` from three optional location parts.

    Returns ``None`` when every part is empty so templates can write
    ``{% if view.full_address %}`` and skip the row entirely. The
    comma joins city + state; the ZIP appends with a space. Partial
    inputs degrade naturally — only the parts that are present
    appear, and the punctuation between them adjusts.
    """
    if not any((city, state, zip_code)):
        return None
    head = ", ".join(p for p in (city, state) if p)
    if zip_code:
        return f"{head} {zip_code}" if head else zip_code
    return head or None
