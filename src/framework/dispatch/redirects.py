"""Canned redirect-callable factories for the ``*_redirect`` spec fields."""

from typing import Any, Callable


class Redirects:
    """Canned redirect-callable factories for the `*_redirect` spec fields."""

    @staticmethod
    def to_edit_form(collection: str, id_param: str) -> Callable[..., str]:
        """Build a redirect callable producing ``/<collection>/{id}/form``.

        Reads the id from ``kwargs[id_param]``. Used by clinicians
        (post-create / post-update redirect to their own edit form) and
        by all three credential subentities (which redirect to the
        parent clinician's edit form — `id_param` is the parent's).
        """

        def _redirect(**kwargs: Any) -> str:
            return f"/{collection}/{kwargs[id_param]}/form"

        return _redirect

    @staticmethod
    def to_detail(collection: str, id_param: str) -> Callable[..., str]:
        """Build a redirect callable producing ``/<collection>/{id}``.

        Used by posts (post-update redirects to the detail page).
        """

        def _redirect(**kwargs: Any) -> str:
            return f"/{collection}/{kwargs[id_param]}"

        return _redirect
