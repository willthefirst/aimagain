import uuid

from fastapi_users.db import SQLAlchemyBaseUserTable
from sqlalchemy import Column, Text
from sqlalchemy.orm import relationship

from src.framework.persistence.base_model import BaseModel


class User(SQLAlchemyBaseUserTable[uuid.UUID], BaseModel):
    __tablename__ = "users"

    username = Column(
        Text,
        unique=True,
        nullable=False,
        default=lambda: f"user_{uuid.uuid4()}",
    )

    # Reverse of `Clinician.owner_id`. Lazy selectin so templates and
    # framework helpers that check `user.clinicians` don't need extra queries.
    clinicians = relationship(
        "Clinician",
        foreign_keys="Clinician.owner_id",
        lazy="selectin",
        viewonly=True,
    )
    programs = relationship(
        "Program",
        foreign_keys="Program.owner_id",
        lazy="selectin",
        viewonly=True,
    )
    # Reverse of `OrgRepresentation.user_id`. Drives Claim B in the
    # capability predicates (`capabilities.any_org_rep_verified(user)`,
    # `capabilities.org_rep_verified(user, org)`,
    # `capabilities.claim_state(user)`). Lazy selectin so a single
    # `user`-shaped read picks up the rep set without a follow-up query
    # — same pattern as `clinicians` / `programs`.
    org_representations = relationship(
        "OrgRepresentation",
        foreign_keys="OrgRepresentation.user_id",
        lazy="selectin",
        viewonly=True,
    )
    # Reverse of `Organization.owner_id`. Selectin so a single `user`-shaped
    # read picks up owned orgs without a follow-up query — same pattern as
    # `clinicians` and `programs`.
    organizations = relationship(
        "Organization",
        foreign_keys="Organization.owner_id",
        lazy="selectin",
        viewonly=True,
    )
    # Owned subentity (1:N) — the user's saved searches. NOT viewonly:
    # the framework's generic create handler appends a new row through
    # this collection (`repo.add_child(user, "saved_searches", row)`),
    # so the relationship must be writable. `cascade="all, delete-orphan"`
    # mirrors the FK's `ondelete="CASCADE"` at the ORM level so deleting a
    # user evicts their saved searches in-session too.
    saved_searches = relationship(
        "SavedSearch",
        foreign_keys="SavedSearch.user_id",
        lazy="selectin",
        cascade="all, delete-orphan",
    )
