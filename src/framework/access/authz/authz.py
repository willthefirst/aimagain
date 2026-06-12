"""Authorization helpers. The predicate forms are the source of truth;
asserting forms wrap them so `write_authz` (raising) and `can_write`
(predicate) stay derivable from one rule per spec."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, Awaitable, Callable

from src.framework.http.exceptions import ForbiddenError

if TYPE_CHECKING:
    from pydantic import BaseModel

    from src.framework.access.actor.actor import Actor


def is_admin(user: Actor | None) -> bool:
    """True iff `user` is authenticated and is a superuser."""
    return user is not None and user.is_superuser


def is_owner(obj, user: Actor | None, *, owner_attr: str = "owner_id") -> bool:
    """True iff `user` is authenticated and `obj`'s owner-FK matches.

    `owner_attr` names the foreign-key column on `obj` that points at
    the owning user. Defaults to `"owner_id"`, which matches both
    `Post.owner_id` and `Clinician.owner_id`; the knob is kept for future
    entities whose owner FK is not literally named `owner_id`.
    """
    if user is None:
        return False
    return getattr(obj, owner_attr) == user.id


def is_owner_or_admin(obj, user: Actor | None, *, owner_attr: str = "owner_id") -> bool:
    """True iff `user` owns `obj` (by FK) or is a superuser.

    Predicate form of `assert_owner_or_admin`. The two forms share one
    composition — `assert_owner_or_admin` delegates here — so a future
    rule change happens in exactly one place. Bound to
    `EntitySpec.can_write` for entities whose write rule is owner-or-admin
    (posts, clinicians, clinician credentials).
    """
    return is_owner(obj, user, owner_attr=owner_attr) or is_admin(user)


def is_self_or_admin(actor: Actor | None, target) -> bool:
    """True iff `actor` is authenticated and is either `target` itself or a superuser.

    Distinct signature from `is_owner`: the resource *is* the user, not
    an FK to one, so there is no `owner_attr` knob — equality is between
    `actor.id` and `target.id` directly.
    """
    if actor is None:
        return False
    return actor.id == target.id or actor.is_superuser


def forbid_self_action(target, actor: Actor, *, detail: str) -> None:
    """Raise `ForbiddenError` if `actor` is operating on themselves.

    For admin-only mutations whose target is a `User` row, the route's
    `current_admin_user` dep already blocks non-admins — but an admin
    could still aim the verb at their own account. The product rule is
    that admins cannot self-mutate via these endpoints; this helper is
    the single place that rule is expressed. `detail` is the full
    error message so each call can phrase the action naturally
    (activation, deletion, …).
    """
    if target.id == actor.id:
        raise ForbiddenError(detail=detail)


def assert_self_or_admin(
    target,
    actor: Actor,
    *,
    action: str = "view this resource",
) -> None:
    """Raise `ForbiddenError` unless `actor` is `target` or a superuser.

    Asserting wrapper over `is_self_or_admin` — for user-shaped resources
    where the row *is* the user (not an FK to one). `action` is
    interpolated: ``"Only the user themselves or an admin can {action}"``.
    """
    if not is_self_or_admin(actor, target):
        raise ForbiddenError(
            detail=f"Only the user themselves or an admin can {action}"
        )


def assert_owner_or_admin(
    obj,
    user: Actor,
    *,
    owner_attr: str = "owner_id",
    action: str = "edit this resource",
) -> None:
    """Raise `ForbiddenError` unless `user` owns `obj` or is a superuser.

    Asserting wrapper over `is_owner_or_admin` — the predicate is the
    rule, this function is the raising form for `EntitySpec.write_authz`.
    `action` is interpolated into the error message: ``"Only the owner
    or an admin can {action}"``.
    """
    if not is_owner_or_admin(obj, user, owner_attr=owner_attr):
        raise ForbiddenError(detail=f"Only the owner or an admin can {action}")


async def list_visible_to(repo, user: "Actor", model, *, owner_attr: str = "owner_id"):
    """Return the rows of `model` a user may pick from in a form picker.

    Owners see only the rows they own; superusers see every row. Drives
    every "your X" form-extras dropdown (Clinician's Org picker,
    Program's Org picker, Organization's parent-Org picker, post-kind
    Clinician/Program pickers) so the same boundary lives in one place.

    Calls `repo.list_for_user(user.id)` for the owner path and
    `repo.list_default(model, order_by=...)` for the superuser path
    — both already exist on `BaseRepository` subclasses today. The
    `owner_attr` kwarg is plumbed through for future entities whose
    owner-FK isn't literally `owner_id`.
    """
    if user.is_superuser:
        return list(await repo.list_default(model, order_by=model.created_at.desc()))
    return list(await repo.list_for_user(user.id))


async def list_picker_options_for(
    repo,
    requesting_user: "Actor",
    model,
    *,
    attached_id=None,
    owner_attr: str = "owner_id",
):
    """Return picker options for a form field, with the attached row
    re-included when it would otherwise be missing.

    Generalization of `list_visible_to` for edit forms whose row is
    attached to a parent the requesting user no longer owns (ownership
    transferred, viewer is a superuser editing someone else's row,
    etc.). Without re-inclusion, a `<select>` rendered from the visible
    set would silently drop the FK on submit; the framework's
    `payload_authz` still gates whether the user may *change* the FK,
    but the picker shouldn't pretend the current attachment doesn't
    exist.

    `attached_id=None` → equivalent to `list_visible_to` (create-form,
    or an edit-form whose attachment is already in the visible set).
    """
    visible = await list_visible_to(repo, requesting_user, model, owner_attr=owner_attr)
    if attached_id is None:
        return visible
    if any(getattr(row, "id", None) == attached_id for row in visible):
        return visible
    attached = await repo.get_by_model_id(model, attached_id)
    if attached is None:
        return visible
    return [*visible, attached]


async def assert_fk_ownership(
    *,
    payload,
    attr: str,
    requesting_user: "Actor",
    parent_repo,
    parent_model,
    parent_noun: str,
    child_noun: str,
) -> None:
    """Reject a create/update payload whose `attr` FK points at a parent
    row the requesting user doesn't own (superusers bypass).

    Generic form of the per-entity `_assert_X_payload_org_ownership`
    helpers — every call shape was identical except the noun in the
    error messages, so the noun is a kwarg now.

    - 404 when the parent doesn't exist (no info leak about other
      users' parent ids).
    - 403 when it exists but belongs to someone else.
    - PATCH payloads where `attr` is `None` (the PATCH didn't touch
      the FK) are a no-op.

    Used by every entity whose Create/Update payload carries an FK to
    another user-owned entity (Clinician→Org, Program→Org, post→
    Clinician/Program, etc.).
    """
    fk_id = getattr(payload, attr, None)
    if fk_id is None:
        return
    parent = await parent_repo.get_by_model_id(parent_model, fk_id)
    if parent is None:
        from src.framework.http.exceptions import NotFoundError

        raise NotFoundError(detail=f"{parent_noun} {fk_id} not found")
    if not requesting_user.is_superuser and parent.owner_id != requesting_user.id:
        raise ForbiddenError(
            detail=f"You may only attach a {child_noun} to a {parent_noun} you own"
        )


def make_fk_ownership_payload_authz(
    *,
    attr: str,
    parent_model,
    parent_noun: str,
    child_noun: str,
    parent_repo_kwarg: str,
) -> Callable[..., Awaitable[None]]:
    """Build the `payload_authz` callable an `EntitySpec` references via
    `payload_authz_path`.

    Closes over the four nouns/columns that distinguish the per-entity
    FK-ownership rule and returns an async hook with the framework-
    expected signature (``async def hook(*, payload, requesting_user,
    **typed_repos) -> None``). `parent_repo_kwarg` names the kwarg the
    framework injects from `payload_authz_repos` (e.g.
    ``"organization_repo"``).

    Replaces the per-entity ``_assert_<x>_payload_org_ownership``
    wrappers that used to exist solely to give the spec's
    ``payload_authz_path`` a dotted target. The result is module-level
    bound (so the dotted path resolves) but declarative.
    """

    async def _payload_authz(
        *,
        payload: "BaseModel",
        requesting_user: "Actor",
        **typed_repos: Any,
    ) -> None:
        await assert_fk_ownership(
            payload=payload,
            attr=attr,
            requesting_user=requesting_user,
            parent_repo=typed_repos[parent_repo_kwarg],
            parent_model=parent_model,
            parent_noun=parent_noun,
            child_noun=child_noun,
        )

    return _payload_authz
