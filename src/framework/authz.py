"""Authorization helpers. The predicate forms are the source of truth;
asserting forms wrap them so `write_authz` (raising) and `can_write`
(predicate) stay derivable from one rule per spec."""

from __future__ import annotations

from typing import TYPE_CHECKING

from src.framework.http.exceptions import ForbiddenError

if TYPE_CHECKING:
    from src.framework.actor import Actor


def is_admin(user: Actor | None) -> bool:
    """True iff `user` is authenticated and is a superuser."""
    return user is not None and user.is_superuser


def is_owner(obj, user: Actor | None, *, owner_attr: str = "owner_id") -> bool:
    """True iff `user` is authenticated and `obj`'s owner-FK matches.

    `owner_attr` names the foreign-key column on `obj` that points at
    the owning user. Defaults to `"owner_id"`, which matches both
    `Post.owner_id` and `Provider.owner_id`; the knob is kept for future
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
    (posts, providers, provider credentials).
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
    every "your X" form-extras dropdown (Provider's Org picker,
    Program's Org picker, Organization's parent-Org picker, post-kind
    Provider/Program pickers) so the same boundary lives in one place.

    Calls `repo.list_for_user(user.id)` for the owner path and
    `repo.list_default(model, order_by=...)` for the superuser path
    — both already exist on `BaseRepository` subclasses today. The
    `owner_attr` kwarg is plumbed through for future entities whose
    owner-FK isn't literally `owner_id`.
    """
    if user.is_superuser:
        return list(await repo.list_default(model, order_by=model.created_at.desc()))
    return list(await repo.list_for_user(user.id))


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
    another user-owned entity (Provider→Org, Program→Org, post→
    Provider/Program, etc.).
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
