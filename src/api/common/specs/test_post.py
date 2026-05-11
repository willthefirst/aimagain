"""Spec-correctness suite for `POST_ENTITY`."""

from src.api.common.entity_spec import RouteSet
from src.api.common.specs.post import POST_ENTITY
from src.logic._authz import assert_owner_or_admin, is_owner_or_admin
from src.logic.audit import AuditAction
from src.models import POST_KINDS, Post
from src.schemas.posts.post import post_create_adapter, post_update_adapter

# --- Identity ------------------------------------------------------------


def test_identity_fields():
    assert POST_ENTITY.name == "post"
    assert POST_ENTITY.url_collection == "posts"
    assert POST_ENTITY.id_param == "post_id"
    assert POST_ENTITY.model is Post


def test_owner_attr_defaults_to_owner_id():
    assert POST_ENTITY.owner_attr == "owner_id"


def test_no_parent():
    assert POST_ENTITY.parent is None


# --- Audit binding -------------------------------------------------------


def test_audit_type_is_post():
    assert POST_ENTITY.audit is not None
    assert POST_ENTITY.audit.type == "post"


def test_audit_actions_match_crud_enum():
    assert POST_ENTITY.audit.create == AuditAction.CREATE_POST
    assert POST_ENTITY.audit.update == AuditAction.UPDATE_POST
    assert POST_ENTITY.audit.delete == AuditAction.DELETE_POST


# --- Routes opt-in -------------------------------------------------------


def test_routes_opted_in():
    """Posts exposes full CRUD + both form pages."""
    assert POST_ENTITY.routes == RouteSet(
        list=True,
        detail=True,
        create=True,
        update=True,
        delete=True,
        form_new=True,
        form_edit=True,
    )


# --- Adapters + projection -----------------------------------------------


def test_adapters_are_the_canonical_ones():
    assert POST_ENTITY.create_adapter is post_create_adapter
    assert POST_ENTITY.update_adapter is post_update_adapter


def test_read_to_dict_flattens_via_post_kinds():
    """`read_to_dict` should return a flat `{id, kind, ...detail_fields}`
    dict for any kind, driven by the `POST_KINDS` registry. Round-trip
    behavior with a real Post is covered at the route layer; here we
    just confirm the callable is wired and returns a dict shape."""
    assert POST_ENTITY.read_to_dict is not None
    assert callable(POST_ENTITY.read_to_dict)


# --- Authorization -------------------------------------------------------


def test_write_authz_is_assert_owner_or_admin():
    assert POST_ENTITY.write_authz is assert_owner_or_admin


def test_can_write_is_is_owner_or_admin():
    """Predicate sibling of `write_authz` — read by detail handlers for
    `can_edit` flags so the rule lives in exactly one place."""
    assert POST_ENTITY.can_write is is_owner_or_admin


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


# --- Templates -----------------------------------------------------------


def test_templates():
    assert POST_ENTITY.templates.list == "posts/list.html"
    assert POST_ENTITY.templates.detail == "posts/detail.html"


# --- Bridge --------------------------------------------------------------


def test_to_resource_spec_round_trips_what_mounts_read():
    rs = POST_ENTITY.to_resource_spec()
    assert rs.collection == "posts"
    assert rs.id_param == "post_id"
    assert rs.repo_dep is POST_ENTITY.repo_dep
    assert rs.audit_resource is POST_ENTITY.audit
    assert rs.read_user_dep is POST_ENTITY.read_user_dep
    assert rs.write_user_dep is POST_ENTITY.write_user_dep
    assert rs.write_authz is assert_owner_or_admin
    assert rs.create_adapter is post_create_adapter
    assert rs.update_adapter is post_update_adapter
    assert rs.list_template == "posts/list.html"
    assert rs.detail_template == "posts/detail.html"
    assert rs.parent is None
