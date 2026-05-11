"""Entity-specific facts for `POST_ENTITY`.

Universal invariants (identity, audit-type, templates, round-trip)
live in `test_spec_conformance.py`. This file pins what's unique to
posts: the discriminator binding (polymorphic registry), the update
redirect to the detail page, and the list-extras binding.
"""

from src.api.common.entity_spec import OWNER_OR_ADMIN
from src.api.common.specs.post import POST_ENTITY
from src.models import POST_KINDS
from src.schemas.posts.post import post_create_adapter, post_update_adapter

# --- Authorization (post-specific) ---------------------------------------


def test_auth_policy_is_owner_or_admin():
    assert POST_ENTITY.auth_policy is OWNER_OR_ADMIN


# --- Adapters are the canonical ones ------------------------------------


def test_adapters_are_the_canonical_typeadapters():
    """Posts uses a pre-built discriminated-union TypeAdapter (not a
    plain Pydantic class). Pin identity so a refactor can't silently
    swap a different adapter."""
    assert POST_ENTITY.create_adapter is post_create_adapter
    assert POST_ENTITY.update_adapter is post_update_adapter


# --- Redirects -----------------------------------------------------------


def test_update_redirect_points_at_detail_page():
    assert POST_ENTITY.update_redirect is not None
    assert POST_ENTITY.update_redirect(post_id="abc-123") == "/posts/abc-123"


def test_create_and_delete_redirects_unset():
    """Posts uses the mount layer's defaults for create and delete."""
    assert POST_ENTITY.create_redirect is None
    assert POST_ENTITY.delete_redirect is None


# --- Discriminator binding -----------------------------------------------


def test_discriminator_is_post_kinds():
    """The spec's binding to the polymorphism registry is load-bearing:
    the route file builds its kind-Literal from
    `POST_ENTITY.discriminator.names`. Pinning identity here proves
    that path is wired to the right registry."""
    assert POST_ENTITY.discriminator is POST_KINDS


def test_discriminator_names_match_registry():
    """The registry's `names` are what the route file reads to build
    the form's kind-Literal."""
    assert POST_ENTITY.discriminator.names == POST_KINDS.names


# --- Extras binding ------------------------------------------------------


def test_list_extras_path_points_at_post_list_extras():
    assert (
        POST_ENTITY.list_extras_path
        == "src.logic.posts.post_processing.post_list_extras"
    )
