"""Tests for provider orchestration handlers.

Exercises happy-path + ownership / not-found / bad-request error cases for
each handler. Audit-row assertions verify that mutation handlers honor the
discipline (`test_audit_discipline.py` enforces it statically; these tests
verify the rows actually land with the expected `action` and snapshots).
"""

import uuid

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker
from starlette.requests import Request

from src.domain.logic.favorites.repository import UserFavoriteRepository
from src.domain.logic.organizations.repository import OrganizationRepository
from src.domain.logic.providers.handlers import (
    handle_list_user_providers,
    provider_detail_extras,
    provider_form_extras,
)
from src.domain.logic.providers.repository import ProviderRepository
from src.domain.logic.providers.schema import (
    ProviderCertificationCreate,
    ProviderCreate,
    ProviderEducationCreate,
    ProviderLicensureCreate,
)
from src.domain.logic.users.repository import UserRepository
from src.domain.logic.verifications.repository import VerificationRepository
from src.domain.models import (
    Provider,
    ProviderLicensure,
    User,
)
from src.domain.specs.provider import PROVIDER_ENTITY
from src.framework.audit.core import AuditAction
from src.framework.audit.log import AuditLog
from src.framework.audit.repository import AuditRepository
from src.framework.dispatch.handlers import handle_create, handle_detail, handle_list
from src.framework.http.exceptions import ForbiddenError, NotFoundError
from tests.helpers import (
    create_test_user,
    make_organization_row,
    make_provider_certification,
    make_provider_education,
    make_provider_licensure,
    make_provider_with_org,
)

pytestmark = pytest.mark.asyncio


def _fake_request(query_string: bytes = b"") -> Request:
    """Minimal Starlette Request used as a placeholder for handlers that
    forward the request into a template context. `query_string` is
    consumed by `parse_page` / `base_query` when the handler paginates;
    callers that don't care leave the default empty."""
    return Request(
        {
            "type": "http",
            "headers": [],
            "method": "GET",
            "path": "/",
            "query_string": query_string,
        }
    )


# --- Seeding helpers -----------------------------------------------------


async def _seed_user(
    db_test_session_manager: async_sessionmaker[AsyncSession],
    *,
    is_superuser: bool = False,
) -> User:
    user = create_test_user(username=f"u-{uuid.uuid4()}", is_superuser=is_superuser)
    async with db_test_session_manager() as session:
        async with session.begin():
            session.add(user)
    return user


async def _seed_provider(
    db_test_session_manager: async_sessionmaker[AsyncSession],
    *,
    user_id: uuid.UUID,
    with_licensure: bool = False,
    with_education: bool = False,
    with_certification: bool = False,
) -> tuple[uuid.UUID, uuid.UUID | None, uuid.UUID | None, uuid.UUID | None]:
    provider = make_provider_with_org(owner_id=user_id)
    async with db_test_session_manager() as session:
        async with session.begin():
            session.add(provider)
        await session.refresh(provider)
        provider_id = provider.id
        clinician_id = provider.clinician_id

    licensure_id: uuid.UUID | None = None
    education_id: uuid.UUID | None = None
    certification_id: uuid.UUID | None = None
    async with db_test_session_manager() as session:
        async with session.begin():
            if with_licensure:
                lic = make_provider_licensure(clinician_id=clinician_id)
                session.add(lic)
            if with_education:
                edu = make_provider_education(clinician_id=clinician_id)
                session.add(edu)
            if with_certification:
                cert = make_provider_certification(clinician_id=clinician_id)
                session.add(cert)
        if with_licensure:
            await session.refresh(lic)
            licensure_id = lic.id
        if with_education:
            await session.refresh(edu)
            education_id = edu.id
        if with_certification:
            await session.refresh(cert)
            certification_id = cert.id

    return provider_id, licensure_id, education_id, certification_id


async def _seed_org(
    db_test_session_manager: async_sessionmaker[AsyncSession],
    *,
    owner_id: uuid.UUID,
    name: str = "Acme Health",
) -> uuid.UUID:
    """Persist a root Organization and return its id. Provider create
    payloads require ``org_id`` on the wire (#524); tests seed an Org
    first and reference its id."""
    org = make_organization_row(owner_id=owner_id, name=name)
    async with db_test_session_manager() as session:
        async with session.begin():
            session.add(org)
    return org.id


def _provider_create_payload(*, org_id: uuid.UUID, **overrides) -> ProviderCreate:
    base = dict(
        org_id=org_id,
        location_city="Springfield",
        location_state="IL",
        location_zip="62701",
        in_person_sessions="yes",
        virtual_sessions="no",
    )
    base.update(overrides)
    return ProviderCreate(**base)


async def _audit_rows_for(
    db_test_session_manager: async_sessionmaker[AsyncSession],
    *,
    resource_type: str,
    resource_id: uuid.UUID,
) -> list[AuditLog]:
    async with db_test_session_manager() as session:
        repo = AuditRepository(session)
        rows = await repo.list_for_resource(
            resource_type=resource_type, resource_id=resource_id
        )
        return list(rows)


# --- Provider reads -------------------------------------------------------


async def test_list_providers_returns_persisted_rows(
    db_test_session_manager: async_sessionmaker[AsyncSession],
):
    user_a = await _seed_user(db_test_session_manager)
    user_b = await _seed_user(db_test_session_manager)
    await _seed_provider(db_test_session_manager, user_id=user_a.id)
    await _seed_provider(db_test_session_manager, user_id=user_b.id)

    async with db_test_session_manager() as session:
        repo = ProviderRepository(session)
        context = await handle_list(
            PROVIDER_ENTITY,
            request=_fake_request(),
            repo=repo,
            requesting_user=None,
            filter_values={"license_type": None, "issuing_state": None},
        )
        # Framework binds `context[spec.url_collection] = items`; the
        # collection flipped to "clinicians" in #642 PR 4. The list still
        # holds `Provider` instances under the hood.
        assert len(context["clinicians"]) == 2
        assert context["selected_license_type"] is None
        assert context["selected_issuing_state"] is None


async def test_list_providers_filters_by_license_type(
    db_test_session_manager: async_sessionmaker[AsyncSession],
):
    user_a = await _seed_user(db_test_session_manager)
    user_b = await _seed_user(db_test_session_manager)
    provider_a, *_ = await _seed_provider(
        db_test_session_manager, user_id=user_a.id, with_licensure=True
    )
    provider_b, *_ = await _seed_provider(db_test_session_manager, user_id=user_b.id)
    # Add a non-matching licensure to provider_b
    async with db_test_session_manager() as session:
        async with session.begin():
            clinician_b = (
                await session.execute(
                    select(Provider.clinician_id).where(Provider.id == provider_b)
                )
            ).scalar_one()
            session.add(
                make_provider_licensure(clinician_id=clinician_b, license_type="lpc")
            )

    async with db_test_session_manager() as session:
        repo = ProviderRepository(session)
        context = await handle_list(
            PROVIDER_ENTITY,
            request=_fake_request(),
            repo=repo,
            requesting_user=None,
            filter_values={"license_type": ["lcsw"], "issuing_state": None},
        )
        assert [p.id for p in context["clinicians"]] == [provider_a]
        assert context["selected_license_type"] == ["lcsw"]


async def test_get_provider_detail_returns_context(
    db_test_session_manager: async_sessionmaker[AsyncSession],
):
    user = await _seed_user(db_test_session_manager)
    provider_id, *_ = await _seed_provider(db_test_session_manager, user_id=user.id)

    async with db_test_session_manager() as session:
        context = await handle_detail(
            PROVIDER_ENTITY,
            request=_fake_request(),
            target_id=provider_id,
            repo=ProviderRepository(session),
            requesting_user=user,
            extras=provider_detail_extras,
            extra_kwargs={
                "user_favorite_repo": UserFavoriteRepository(session),
                "verification_repo": VerificationRepository(session),
            },
        )
        # Framework binds `context[spec.name] = target`; the spec name
        # flipped to "clinician" in #642 PR 4. The underlying row is
        # still a `Provider` instance.
        assert context["clinician"].id == provider_id
        assert context["current_user"] is user
        assert "request" in context
        # Owner viewing own provider → can_edit True. Non-owner / admin
        # cases are exercised at the route level
        # (test_get_provider_hides_edit_link_for_non_owner et al.).
        assert context["can_edit"] is True
        # `is_favorited` is a per-viewer derived field; the owner here
        # has not favorited their own provider.
        assert context["is_favorited"] is False
        # `verification_status` is `None` when no Verification row exists
        # yet for the provider — the template renders the UI-only
        # "Pending" state in that case (#707 stage 2).
        assert context["verification_status"] is None


async def test_get_provider_detail_surfaces_verification_status(
    db_test_session_manager: async_sessionmaker[AsyncSession],
):
    """The provider's `Verification.status` is forwarded to the
    template context. "Newest wins" multi-row semantics are pinned
    elsewhere by `VerificationRepository.latest_for_provider`'s own
    tests; this only verifies that the handler threads the value
    through (#707 stage 2)."""
    from src.domain.models import Verification

    user = await _seed_user(db_test_session_manager)
    provider_id, *_ = await _seed_provider(db_test_session_manager, user_id=user.id)

    async with db_test_session_manager() as session:
        async with session.begin():
            session.add(
                Verification(
                    provider_id=provider_id,
                    status="verified",
                    flags=[],
                    nppes_result={"NPI": "1234567890"},
                    oig_match=False,
                    name_match_score=1.0,
                )
            )

    async with db_test_session_manager() as session:
        context = await handle_detail(
            PROVIDER_ENTITY,
            request=_fake_request(),
            target_id=provider_id,
            repo=ProviderRepository(session),
            requesting_user=user,
            extras=provider_detail_extras,
            extra_kwargs={
                "user_favorite_repo": UserFavoriteRepository(session),
                "verification_repo": VerificationRepository(session),
            },
        )
        assert context["verification_status"] == "verified"


async def test_get_provider_detail_404_for_unknown_id(
    db_test_session_manager: async_sessionmaker[AsyncSession],
):
    user = await _seed_user(db_test_session_manager)
    async with db_test_session_manager() as session:
        with pytest.raises(NotFoundError):
            await handle_detail(
                PROVIDER_ENTITY,
                request=_fake_request(),
                target_id=uuid.uuid4(),
                repo=ProviderRepository(session),
                requesting_user=user,
                extras=provider_detail_extras,
                extra_kwargs={
                    "user_favorite_repo": UserFavoriteRepository(session),
                    "verification_repo": VerificationRepository(session),
                },
            )


async def test_get_provider_detail_is_favorited_true_when_self_favorited(
    db_test_session_manager: async_sessionmaker[AsyncSession],
):
    """A viewer who has favorited the provider sees `is_favorited=True`."""
    user = await _seed_user(db_test_session_manager)
    other = await _seed_user(db_test_session_manager)
    provider_id, *_ = await _seed_provider(db_test_session_manager, user_id=other.id)

    async with db_test_session_manager() as session:
        fav_repo = UserFavoriteRepository(session)
        await fav_repo.add_favorite(user_id=user.id, provider_id=provider_id)
        await session.commit()

    async with db_test_session_manager() as session:
        context = await handle_detail(
            PROVIDER_ENTITY,
            request=_fake_request(),
            target_id=provider_id,
            repo=ProviderRepository(session),
            requesting_user=user,
            extras=provider_detail_extras,
            extra_kwargs={
                "user_favorite_repo": UserFavoriteRepository(session),
                "verification_repo": VerificationRepository(session),
            },
        )
        assert context["is_favorited"] is True


async def test_get_provider_detail_is_favorited_false_for_anonymous_viewer(
    db_test_session_manager: async_sessionmaker[AsyncSession],
):
    """A `None` `requesting_user` never sees `is_favorited=True` — the
    flag is meaningless without an actor. Today `PROVIDER_ENTITY.read_user_dep`
    forces auth so this branch is defensive; the test pins the contract
    in case the read dep ever loosens."""
    other = await _seed_user(db_test_session_manager)
    provider_id, *_ = await _seed_provider(db_test_session_manager, user_id=other.id)

    async with db_test_session_manager() as session:
        context = await handle_detail(
            PROVIDER_ENTITY,
            request=_fake_request(),
            target_id=provider_id,
            repo=ProviderRepository(session),
            requesting_user=None,
            extras=provider_detail_extras,
            extra_kwargs={
                "user_favorite_repo": UserFavoriteRepository(session),
                "verification_repo": VerificationRepository(session),
            },
        )
        assert context["is_favorited"] is False


# --- handle_list_user_providers --------------------------------


async def test_list_user_providers_self_returns_owned(
    db_test_session_manager: async_sessionmaker[AsyncSession],
):
    user = await _seed_user(db_test_session_manager)
    first_id, *_ = await _seed_provider(db_test_session_manager, user_id=user.id)
    second_id, *_ = await _seed_provider(db_test_session_manager, user_id=user.id)

    async with db_test_session_manager() as session:
        provider_repo = ProviderRepository(session)
        user_repo = UserRepository(session)
        context = await handle_list_user_providers(
            request=_fake_request(),
            user_id=user.id,
            repo=provider_repo,
            user_repo=user_repo,
            requesting_user=user,
        )

    assert context["is_self"] is True
    assert context["target_user"].id == user.id
    assert {p.id for p in context["providers"]} == {first_id, second_id}


async def test_list_user_providers_self_returns_empty_when_none(
    db_test_session_manager: async_sessionmaker[AsyncSession],
):
    user = await _seed_user(db_test_session_manager)

    async with db_test_session_manager() as session:
        provider_repo = ProviderRepository(session)
        user_repo = UserRepository(session)
        context = await handle_list_user_providers(
            request=_fake_request(),
            user_id=user.id,
            repo=provider_repo,
            user_repo=user_repo,
            requesting_user=user,
        )

    assert context["is_self"] is True
    assert list(context["providers"]) == []


async def test_list_user_providers_admin_can_view_anyone(
    db_test_session_manager: async_sessionmaker[AsyncSession],
):
    target = await _seed_user(db_test_session_manager)
    admin = await _seed_user(db_test_session_manager, is_superuser=True)
    provider_id, *_ = await _seed_provider(db_test_session_manager, user_id=target.id)

    async with db_test_session_manager() as session:
        provider_repo = ProviderRepository(session)
        user_repo = UserRepository(session)
        context = await handle_list_user_providers(
            request=_fake_request(),
            user_id=target.id,
            repo=provider_repo,
            user_repo=user_repo,
            requesting_user=admin,
        )

    assert context["is_self"] is False
    assert context["target_user"].id == target.id
    assert [p.id for p in context["providers"]] == [provider_id]


async def test_list_user_providers_non_admin_cannot_view_other(
    db_test_session_manager: async_sessionmaker[AsyncSession],
):
    target = await _seed_user(db_test_session_manager)
    other = await _seed_user(db_test_session_manager)

    async with db_test_session_manager() as session:
        provider_repo = ProviderRepository(session)
        user_repo = UserRepository(session)
        with pytest.raises(ForbiddenError):
            await handle_list_user_providers(
                request=_fake_request(),
                user_id=target.id,
                repo=provider_repo,
                user_repo=user_repo,
                requesting_user=other,
            )


async def test_list_user_providers_404_when_target_user_missing(
    db_test_session_manager: async_sessionmaker[AsyncSession],
):
    admin = await _seed_user(db_test_session_manager, is_superuser=True)

    async with db_test_session_manager() as session:
        provider_repo = ProviderRepository(session)
        user_repo = UserRepository(session)
        with pytest.raises(NotFoundError):
            await handle_list_user_providers(
                request=_fake_request(),
                user_id=uuid.uuid4(),
                repo=provider_repo,
                user_repo=user_repo,
                requesting_user=admin,
            )


# --- handle_create (provider, via the generic framework) -----------------


# Provider create goes through the framework's `handle_create`. The
# inline-children loop now lives in `_generic.py`, driven by
# `PROVIDER_ENTITY.children`.
async def test_create_provider_persists_row_and_writes_audit(
    db_test_session_manager: async_sessionmaker[AsyncSession],
):
    user = await _seed_user(db_test_session_manager)
    org_id = await _seed_org(db_test_session_manager, owner_id=user.id)
    payload = _provider_create_payload(org_id=org_id)

    async with db_test_session_manager() as session:
        repo = ProviderRepository(session)
        audit_repo = AuditRepository(session)
        created = await handle_create(
            PROVIDER_ENTITY,
            payload=payload,
            repo=repo,
            audit_repo=audit_repo,
            requesting_user=user,
        )

    assert created.owner_id == user.id
    assert created.org_id == org_id
    assert created.org.name == "Acme Health"

    rows = await _audit_rows_for(
        db_test_session_manager,
        resource_type="clinician",
        resource_id=created.id,
    )
    assert len(rows) == 1
    assert rows[0].action == AuditAction.CREATE_PROVIDER
    assert rows[0].actor_id == user.id
    assert rows[0].before is None
    # The audit snapshot mirrors `ProviderRead` — `org_name` is the
    # practice's display name post-#524.
    assert rows[0].after["org_name"] == "Acme Health"
    assert rows[0].after["org_id"] == str(org_id)


async def test_create_provider_with_inline_children_captures_them_in_audit(
    db_test_session_manager: async_sessionmaker[AsyncSession],
):
    user = await _seed_user(db_test_session_manager)
    org_id = await _seed_org(db_test_session_manager, owner_id=user.id)
    payload = _provider_create_payload(
        org_id=org_id,
        licensures=[
            ProviderLicensureCreate(
                license_type="lcsw", license_number="L-1", issuing_state="IL"
            )
        ],
        educations=[
            ProviderEducationCreate(education_type="msw", institution="State U")
        ],
        certifications=[
            ProviderCertificationCreate(
                certification_type="emdr", certifying_body="EMDRIA"
            )
        ],
    )

    async with db_test_session_manager() as session:
        repo = ProviderRepository(session)
        audit_repo = AuditRepository(session)
        created = await handle_create(
            PROVIDER_ENTITY,
            payload=payload,
            repo=repo,
            audit_repo=audit_repo,
            requesting_user=user,
        )

    rows = await _audit_rows_for(
        db_test_session_manager,
        resource_type="clinician",
        resource_id=created.id,
    )
    assert len(rows) == 1
    after = rows[0].after
    assert len(after["licensures"]) == 1
    assert after["licensures"][0]["license_number"] == "L-1"
    assert len(after["educations"]) == 1
    assert len(after["certifications"]) == 1

    # Sub-rows actually persisted, too.
    async with db_test_session_manager() as session:
        licensures = (
            (
                await session.execute(
                    select(ProviderLicensure).filter(
                        ProviderLicensure.clinician_id == created.clinician_id
                    )
                )
            )
            .scalars()
            .all()
        )
        assert len(licensures) == 1


async def test_create_provider_allows_multiple_per_user(
    db_test_session_manager: async_sessionmaker[AsyncSession],
):
    """A user may own multiple providers. The handler creates a second provider
    successfully without surfacing the previously-enforced 1:1 rejection."""
    user = await _seed_user(db_test_session_manager)
    first_id, *_ = await _seed_provider(db_test_session_manager, user_id=user.id)
    second_org_id = await _seed_org(
        db_test_session_manager, owner_id=user.id, name="Second Practice"
    )

    async with db_test_session_manager() as session:
        repo = ProviderRepository(session)
        audit_repo = AuditRepository(session)
        second = await handle_create(
            PROVIDER_ENTITY,
            payload=_provider_create_payload(org_id=second_org_id),
            repo=repo,
            audit_repo=audit_repo,
            requesting_user=user,
        )

    assert second.id != first_id
    assert second.owner_id == user.id
    assert second.org.name == "Second Practice"


# --- provider_form_extras (#533) -----------------------------------------


async def test_provider_form_extras_returns_owners_visible_orgs(
    db_test_session_manager: async_sessionmaker[AsyncSession],
):
    """Owner sees only the Orgs they own. Mirrors the previous
    `handle_get_provider_new_form` behavior, now provided by the
    framework via `form_extras_path`."""
    owner = await _seed_user(db_test_session_manager)
    stranger = await _seed_user(db_test_session_manager)
    owned_id = await _seed_org(db_test_session_manager, owner_id=owner.id, name="Mine")
    await _seed_org(db_test_session_manager, owner_id=stranger.id, name="Other")

    async with db_test_session_manager() as session:
        org_repo = OrganizationRepository(session)
        # Create path: target is None.
        result = await provider_form_extras(
            target=None,
            requesting_user=owner,
            organization_repo=org_repo,
        )
        assert [o.id for o in result["orgs"]] == [owned_id]


async def test_provider_form_extras_superuser_sees_all_orgs(
    db_test_session_manager: async_sessionmaker[AsyncSession],
):
    """Superusers see every Org regardless of ownership — same
    semantics as the previous bespoke handler."""
    admin = await _seed_user(db_test_session_manager, is_superuser=True)
    other = await _seed_user(db_test_session_manager)
    await _seed_org(db_test_session_manager, owner_id=admin.id, name="Admin Org")
    await _seed_org(db_test_session_manager, owner_id=other.id, name="Other Org")

    async with db_test_session_manager() as session:
        org_repo = OrganizationRepository(session)
        result = await provider_form_extras(
            target=None,
            requesting_user=admin,
            organization_repo=org_repo,
        )
        org_names = {o.name for o in result["orgs"]}
        assert "Admin Org" in org_names
        assert "Other Org" in org_names


async def test_provider_form_extras_edit_path_passes_target(
    db_test_session_manager: async_sessionmaker[AsyncSession],
):
    """On the edit path the framework passes the loaded Provider as
    `target`. The current implementation doesn't read it, but the
    callable must accept it without complaint — the contract is the
    same on both paths."""
    owner = await _seed_user(db_test_session_manager)
    await _seed_org(db_test_session_manager, owner_id=owner.id, name="Owned")
    provider_id, *_ = await _seed_provider(db_test_session_manager, user_id=owner.id)

    async with db_test_session_manager() as session:
        provider_repo = ProviderRepository(session)
        provider = await provider_repo.get_by_model_id(Provider, provider_id)
        org_repo = OrganizationRepository(session)
        result = await provider_form_extras(
            target=provider,
            requesting_user=owner,
            organization_repo=org_repo,
        )
        assert "orgs" in result
