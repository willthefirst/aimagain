"""Organization repository.

The only piece of bespoke logic on top of `BaseRepository` is keeping
the ``root_org_id`` denormalization in lockstep with ``parent_org_id``:

* On insert: ``root_org_id = id`` for a root (``parent_org_id IS NULL``),
  else ``root_org_id = parent.root_org_id``.
* On patch that touches ``parent_org_id``: recompute the same way.

The invariant is documented in
``src/domain/models/organizations/README.md``. This is the only
write path today; PR 4+ (Program) and PR 2 (Provider.org_id) will
read the tree but won't widen the writer surface.
"""

import uuid
from typing import Any, Sequence

from sqlalchemy import select

from src.domain.models import Organization
from src.framework.http.exceptions import NotFoundError
from src.framework.persistence.base_repository import BaseRepository


class OrganizationRepository(BaseRepository):
    async def list_for_user(self, user_id: uuid.UUID) -> Sequence[Organization]:
        """Lists every Organization owned by ``user_id``, newest first.
        Drives the Provider create/edit form's Org-picker dropdown — users
        can only attach Providers to Orgs they own (#524 retro: Org
        ownership is the boundary for who may attach Providers, mirroring
        ``Organization.write_authz``)."""
        stmt = (
            select(Organization)
            .filter(Organization.owner_id == user_id)
            .order_by(Organization.created_at.desc())
        )
        return await self._list(stmt)

    async def _resolve_root_id(
        self, parent_org_id: uuid.UUID | None
    ) -> uuid.UUID | None:
        """Return the root for an org whose parent FK is `parent_org_id`.

        ``None`` parent → the row is a root; the caller assigns
        ``root_org_id = id`` once the id is known. Non-``None`` parent →
        fetch the parent and return its ``root_org_id``. 404 if the parent
        doesn't exist (covers both create-with-bogus-parent and reparent
        cases)."""
        if parent_org_id is None:
            return None
        parent = await self._get_by_id(Organization, parent_org_id)
        if parent is None:
            raise NotFoundError(detail=f"Parent organization {parent_org_id} not found")
        return parent.root_org_id

    async def create(self, obj: Organization) -> Organization:
        """Override the framework's public `create` to maintain the
        ``root_org_id`` invariant. The BaseModel default of `uuid.uuid4`
        only fires at flush time, so we assign the id eagerly when this
        row is its own root — otherwise we'd flush with ``root_org_id``
        unresolved."""
        if obj.id is None:
            obj.id = uuid.uuid4()
        resolved_root = await self._resolve_root_id(obj.parent_org_id)
        obj.root_org_id = obj.id if resolved_root is None else resolved_root
        return await self._persist_new(obj)

    async def patch(self, obj: Organization, **fields: Any) -> Organization:
        """Override `patch` so reparenting recomputes `root_org_id`.

        A patch that doesn't touch ``parent_org_id`` is forwarded to
        the base implementation unchanged. When ``parent_org_id`` is
        in the payload, both columns are assigned eagerly here — the
        base ``_patch`` skips ``None`` values (so a payload that promotes
        a child to root would otherwise be dropped) and would never
        see ``root_org_id`` since clients don't send it on the wire.
        """
        if "parent_org_id" in fields:
            new_parent_id = fields.pop("parent_org_id")
            resolved_root = await self._resolve_root_id(new_parent_id)
            obj.parent_org_id = new_parent_id
            obj.root_org_id = obj.id if resolved_root is None else resolved_root
        return await self._patch(obj, **fields)
