from typing import Any, Sequence
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.models import (
    ProviderCertification,
    ProviderEducation,
    ProviderLicensure,
    ProviderProfile,
)

from .base import BaseRepository


class ProviderProfileRepository(BaseRepository):
    def __init__(self, session: AsyncSession):
        super().__init__(session)

    # --- ProviderProfile reads --------------------------------------------

    async def get_by_id(self, profile_id: UUID) -> ProviderProfile | None:
        """Retrieves a provider profile by its ID. Sub-table relationships
        (licensures, educations, certifications) are eager-loaded via
        `lazy="selectin"` on the model."""
        stmt = select(ProviderProfile).filter(ProviderProfile.id == profile_id)
        result = await self.session.execute(stmt)
        return result.scalars().first()

    async def get_by_user_id(self, user_id: UUID) -> ProviderProfile | None:
        """Retrieves a provider profile by its owning user ID. The
        `uq_provider_profiles_user_id` constraint guarantees at most one."""
        stmt = select(ProviderProfile).filter(ProviderProfile.user_id == user_id)
        result = await self.session.execute(stmt)
        return result.scalars().first()

    async def list_profiles(
        self,
        *,
        license_type: str | None = None,
        issuing_state: str | None = None,
    ) -> Sequence[ProviderProfile]:
        """Lists provider profiles, newest first. When `license_type` or
        `issuing_state` is set, joins through `provider_licensures` and
        filters; `.distinct()` prevents duplicate parents when multiple
        licensures on the same profile match."""
        stmt = select(ProviderProfile)
        if license_type is not None or issuing_state is not None:
            stmt = stmt.join(
                ProviderLicensure,
                ProviderLicensure.profile_id == ProviderProfile.id,
            )
            if license_type is not None:
                stmt = stmt.filter(ProviderLicensure.license_type == license_type)
            if issuing_state is not None:
                stmt = stmt.filter(ProviderLicensure.issuing_state == issuing_state)
            stmt = stmt.distinct()
        stmt = stmt.order_by(ProviderProfile.created_at.desc())
        result = await self.session.execute(stmt)
        return result.scalars().all()

    # --- ProviderProfile mutations ----------------------------------------

    async def create_profile(self, user_id: UUID, **fields: Any) -> ProviderProfile:
        """Creates a new provider profile for the given user; the caller
        commits."""
        profile = ProviderProfile(user_id=user_id, **fields)
        self.session.add(profile)
        await self.session.flush()
        await self.session.refresh(profile)
        return profile

    async def update_profile(
        self, profile: ProviderProfile, **fields: Any
    ) -> ProviderProfile:
        """Mutates the provided fields on the profile and flushes; the
        caller commits. Fields whose value is `None` are skipped, mirroring
        `PostRepository.update_post`."""
        for field_name, value in fields.items():
            if value is None:
                continue
            setattr(profile, field_name, value)
        self.session.add(profile)
        await self.session.flush()
        await self.session.refresh(profile)
        return profile

    async def delete_profile(self, profile: ProviderProfile) -> None:
        """Hard-deletes the profile; the caller commits. Sub-rows are
        removed by ORM cascade (`all, delete-orphan`) and FK
        `ON DELETE CASCADE`."""
        await self.session.delete(profile)
        await self.session.flush()

    # --- Licensure sub-table ----------------------------------------------

    async def get_licensure_by_id(self, licensure_id: UUID) -> ProviderLicensure | None:
        """Retrieves a licensure by its ID."""
        stmt = select(ProviderLicensure).filter(ProviderLicensure.id == licensure_id)
        result = await self.session.execute(stmt)
        return result.scalars().first()

    async def add_licensure(
        self, profile: ProviderProfile, **fields: Any
    ) -> ProviderLicensure:
        """Creates a new licensure attached to the profile; the caller
        commits."""
        licensure = ProviderLicensure(profile_id=profile.id, **fields)
        self.session.add(licensure)
        await self.session.flush()
        await self.session.refresh(licensure)
        return licensure

    async def update_licensure(
        self, licensure: ProviderLicensure, **fields: Any
    ) -> ProviderLicensure:
        """Mutates the provided fields on the licensure and flushes; the
        caller commits. `None` values are skipped."""
        for field_name, value in fields.items():
            if value is None:
                continue
            setattr(licensure, field_name, value)
        self.session.add(licensure)
        await self.session.flush()
        await self.session.refresh(licensure)
        return licensure

    async def delete_licensure(self, licensure: ProviderLicensure) -> None:
        """Hard-deletes the licensure; the caller commits."""
        await self.session.delete(licensure)
        await self.session.flush()

    # --- Education sub-table ----------------------------------------------

    async def get_education_by_id(self, education_id: UUID) -> ProviderEducation | None:
        """Retrieves an education entry by its ID."""
        stmt = select(ProviderEducation).filter(ProviderEducation.id == education_id)
        result = await self.session.execute(stmt)
        return result.scalars().first()

    async def add_education(
        self, profile: ProviderProfile, **fields: Any
    ) -> ProviderEducation:
        """Creates a new education entry attached to the profile; the
        caller commits."""
        education = ProviderEducation(profile_id=profile.id, **fields)
        self.session.add(education)
        await self.session.flush()
        await self.session.refresh(education)
        return education

    async def update_education(
        self, education: ProviderEducation, **fields: Any
    ) -> ProviderEducation:
        """Mutates the provided fields on the education entry and flushes;
        the caller commits. `None` values are skipped."""
        for field_name, value in fields.items():
            if value is None:
                continue
            setattr(education, field_name, value)
        self.session.add(education)
        await self.session.flush()
        await self.session.refresh(education)
        return education

    async def delete_education(self, education: ProviderEducation) -> None:
        """Hard-deletes the education entry; the caller commits."""
        await self.session.delete(education)
        await self.session.flush()

    # --- Certification sub-table ------------------------------------------

    async def get_certification_by_id(
        self, certification_id: UUID
    ) -> ProviderCertification | None:
        """Retrieves a certification by its ID."""
        stmt = select(ProviderCertification).filter(
            ProviderCertification.id == certification_id
        )
        result = await self.session.execute(stmt)
        return result.scalars().first()

    async def add_certification(
        self, profile: ProviderProfile, **fields: Any
    ) -> ProviderCertification:
        """Creates a new certification attached to the profile; the caller
        commits."""
        certification = ProviderCertification(profile_id=profile.id, **fields)
        self.session.add(certification)
        await self.session.flush()
        await self.session.refresh(certification)
        return certification

    async def update_certification(
        self, cert: ProviderCertification, **fields: Any
    ) -> ProviderCertification:
        """Mutates the provided fields on the certification and flushes;
        the caller commits. `None` values are skipped."""
        for field_name, value in fields.items():
            if value is None:
                continue
            setattr(cert, field_name, value)
        self.session.add(cert)
        await self.session.flush()
        await self.session.refresh(cert)
        return cert

    async def delete_certification(self, cert: ProviderCertification) -> None:
        """Hard-deletes the certification; the caller commits."""
        await self.session.delete(cert)
        await self.session.flush()
