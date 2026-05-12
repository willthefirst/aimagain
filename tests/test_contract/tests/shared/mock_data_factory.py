"""Factory for consistent mock data and dependency-override configs.

Each `create_*_dependency_config()` returns a mapping of fully-qualified
handler paths to mock configuration. The provider server fixture
(`tests/test_contract/conftest.py::provider_server`) consumes this mapping to
monkey-patch business-logic handlers, so Pact verification exercises only the
route layer.

`make_post_stub(kind, **field_overrides)` is the registry-backed builder
for Post-shaped `SimpleNamespace` stubs — the per-kind detail
relationship name and field tuple come from `POST_KINDS` in
`src/domain/models/posts/post_kinds.py`, so adding/renaming a kind's fields does not
require touching contract test code.
"""

from datetime import datetime, timezone
from types import SimpleNamespace
from typing import Any, Dict
from uuid import UUID, uuid4

from src.domain.logic.users.schema import UserRead
from src.domain.models import POST_KINDS


def make_post_stub(
    kind: str,
    *,
    post_id: UUID | None = None,
    owner_id: UUID | None = None,
    owner_username: str = "post_owner",
    **field_overrides: Any,
) -> SimpleNamespace:
    """Return a Post-shaped `SimpleNamespace` stub for `kind`.

    The right per-kind detail relationship is populated (driven by
    `POST_KINDS[kind]`); the other kinds' detail relationships are
    set to `None` so template `{% if post.X %}` checks behave correctly.

    Detail fields default to `f"stub {field}"`; override individually
    via `**field_overrides`. Unknown overrides for the kind are passed
    through onto the detail `SimpleNamespace` (caller's responsibility
    not to send cross-kind fields).
    """
    spec = POST_KINDS[kind]
    detail_values: dict[str, Any] = {f: f"stub {f}" for f in spec.detail_fields}
    detail_values.update(field_overrides)
    detail = SimpleNamespace(**detail_values)

    pid = post_id or uuid4()
    oid = owner_id or uuid4()
    now = datetime.now(timezone.utc)

    other_relationships = {
        other_spec.detail_relationship: None
        for other_kind, other_spec in POST_KINDS.items()
        if other_kind != kind
    }

    return SimpleNamespace(
        id=pid,
        kind=kind,
        owner_id=oid,
        owner=SimpleNamespace(id=oid, username=owner_username),
        created_at=now,
        updated_at=now,
        **{spec.detail_relationship: detail},
        **other_relationships,
    )


class MockDataFactory:
    """Factory for creating consistent mock data."""

    MOCK_USER_ID = "550e8400-e29b-41d4-a716-446655440001"

    TEST_EMAIL = "test.user@example.com"
    TEST_USERNAME = "testuser"
    TEST_PASSWORD = "securepassword123"

    @classmethod
    def create_user_read(
        cls,
        user_id: str = None,
        email: str = None,
        username: str = None,
        is_active: bool = True,
        is_superuser: bool = False,
        is_verified: bool = False,
    ) -> UserRead:
        return UserRead(
            id=user_id or str(uuid4()),
            email=email or cls.TEST_EMAIL,
            username=username or cls.TEST_USERNAME,
            is_active=is_active,
            is_superuser=is_superuser,
            is_verified=is_verified,
        )

    @classmethod
    def create_registration_dependency_config(
        cls, user_read: UserRead = None
    ) -> Dict[str, Any]:
        if user_read is None:
            user_read = cls.create_user_read()

        return {
            "src.domain.routes.auth_routes.handle_registration": {
                "return_value_config": user_read
            }
        }

    @classmethod
    def create_user_activation_dependency_config(
        cls, user_read: UserRead = None
    ) -> Dict[str, Any]:
        """Mock for `handle_set_user_activation`.

        The route under test (`PUT /users/{id}/activation`) reads `id`,
        `username`, and `is_active` off the handler's return value and packs
        them into the JSON response, so a `UserRead` (or any object exposing
        those attributes) is sufficient.
        """
        if user_read is None:
            user_read = cls.create_user_read(is_active=False)

        return {
            "src.domain.logic.users.handlers.handle_set_user_activation": {
                "return_value_config": user_read
            }
        }

    @classmethod
    def create_post_delete_dependency_config(cls) -> Dict[str, Any]:
        """Mock for the generic delete handler bound to posts.

        After the phase-2 B1 migration (#326), `handle_delete_post` no
        longer exists; the route file binds
        `make_delete_handler(POST_ENTITY)` and assigns it to the
        module-level `_handle_delete_post` attribute so test patches
        can target it (the mount layer's `_resolve_handler` reads
        from the handler's `__module__`).

        The route under test (`DELETE /posts/{id}`) discards the
        handler return value and emits a 204 with
        `HX-Redirect: /posts`, so `None` is a valid mock return.
        """
        return {
            "src.domain.routes.posts._handle_delete_post": {"return_value_config": None}
        }

    @classmethod
    def create_provider_create_dependency_config(cls) -> Dict[str, Any]:
        """Mock for the factory-built `_handle_create_provider`.

        The route under test (`POST /providers`) reads `id` off
        the handler's return value to build the response body and the
        `Location` / `HX-Redirect` headers. A `SimpleNamespace` exposing
        `id` is sufficient. The framework stitches the auto-bound
        handler onto the route module, so contract patches target
        `src.domain.routes.providers._handle_create_provider` (not the
        old bespoke handler in `provider_processing`).
        """
        stub_provider = SimpleNamespace(
            id=UUID("33333333-3333-3333-3333-333333333333"),
        )
        return {
            "src.domain.routes.providers._handle_create_provider": {
                "return_value_config": stub_provider
            }
        }

    @classmethod
    def create_provider_update_dependency_config(cls) -> Dict[str, Any]:
        """Mock for `handle_update_provider`.

        The route under test (`PATCH /providers/{id}`) packs the
        handler's return value through `ProviderRead.model_validate` — so
        the stub must expose every field that schema requires.
        """
        from datetime import datetime, timezone

        now = datetime.now(timezone.utc)
        stub_provider = SimpleNamespace(
            id=UUID("44444444-4444-4444-4444-444444444444"),
            owner_id=UUID("00000000-0000-0000-0000-000000000004"),
            created_at=now,
            updated_at=now,
            practice_name="Acme Counseling",
            location_city="Brooklyn",
            location_state="NY",
            location_zip="11201",
            in_person_sessions="yes",
            virtual_sessions="please_contact",
            licensures=[],
            educations=[],
            certifications=[],
        )
        # After B3 (#330) the per-entity `handle_update_provider` is gone;
        # the route binds `make_update_handler(PROVIDER_ENTITY)` and
        # assigns it to the module-level `_handle_update_provider` attr
        # so contract patches retarget here. The mount layer's
        # `_resolve_handler` reads from `__module__`.
        return {
            "src.domain.routes.providers._handle_update_provider": {
                "return_value_config": stub_provider
            }
        }
