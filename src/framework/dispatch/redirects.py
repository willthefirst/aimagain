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

    @staticmethod
    def to_related_list(
        parent_collection: str,
        parent_id_param: str,
        child_collection: str,
    ) -> Callable[..., str]:
        """Build a redirect callable producing
        ``/<parent_collection>/{parent_id}/<child_collection>``.

        Used by parent-owned subentities whose post-mutation UX is "stay
        on the related-list page the user came from" rather than the
        whole-parent edit form. The clinician sub-resources (affiliations,
        licensures, educations, certifications) all use this after #1336
        promoted each into its own list page.
        """

        def _redirect(**kwargs: Any) -> str:
            return f"/{parent_collection}/{kwargs[parent_id_param]}/{child_collection}"

        return _redirect
