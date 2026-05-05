"""Factory for consistent mock data and dependency-override configs.

Each `create_*_dependency_config()` returns a mapping of fully-qualified
handler paths to mock configuration. The provider server fixture
(`tests/test_contract/conftest.py::provider_server`) consumes this mapping to
monkey-patch business-logic handlers, so Pact verification exercises only the
route layer.

`make_post_stub(kind, **field_overrides)` is the registry-backed builder
for Post-shaped `SimpleNamespace` stubs — the per-kind detail
relationship name and field tuple come from `REGISTERED_KINDS` in
`src/models/post_kinds.py`, so adding/renaming a kind's fields does not
require touching contract test code.
"""

from datetime import datetime, timezone
from types import SimpleNamespace
from typing import Any, Dict
from uuid import UUID, uuid4

from src.models import REGISTERED_KINDS
from src.schemas.user import UserRead


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
    `REGISTERED_KINDS[kind]`); the other kinds' detail relationships are
    set to `None` so template `{% if post.X %}` checks behave correctly.

    Detail fields default to `f"stub {field}"`; override individually
    via `**field_overrides`. Unknown overrides for the kind are passed
    through onto the detail `SimpleNamespace` (caller's responsibility
    not to send cross-kind fields).
    """
    spec = REGISTERED_KINDS[kind]
    detail_values: dict[str, Any] = {f: f"stub {f}" for f in spec.detail_fields}
    detail_values.update(field_overrides)
    detail = SimpleNamespace(**detail_values)

    pid = post_id or uuid4()
    oid = owner_id or uuid4()
    now = datetime.now(timezone.utc)

    other_relationships = {
        other_spec.detail_relationship: None
        for other_kind, other_spec in REGISTERED_KINDS.items()
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
            "src.api.routes.auth_routes.handle_registration": {
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
            "src.api.routes.users.handle_set_user_activation": {
                "return_value_config": user_read
            }
        }

    # Stable post id matching `STUB_POST_ID` in `tests/test_contract/constants.py`.
    MOCK_POST_ID = UUID("22222222-2222-2222-2222-222222222222")
    MOCK_POST_OWNER_ID = UUID(MOCK_USER_ID)

    @classmethod
    def create_post_read(
        cls,
        kind: str = "note",
        *,
        post_id: UUID | None = None,
        owner_id: UUID | None = None,
        **field_overrides: Any,
    ) -> SimpleNamespace:
        """Build a Post-shaped mock consumed by the route layer.

        Thin wrapper over `make_post_stub` that pins the post id and
        owner id to the contract-test stable values. The route under
        test reads `.id`, `.kind`, and the per-kind detail relationship
        off the return value to build the response. Override per-kind
        fields via `**field_overrides`.
        """
        return make_post_stub(
            kind,
            post_id=post_id or cls.MOCK_POST_ID,
            owner_id=owner_id or cls.MOCK_POST_OWNER_ID,
            **field_overrides,
        )

    @classmethod
    def create_post_create_dependency_config(
        cls, post_read: SimpleNamespace = None
    ) -> Dict[str, Any]:
        """Mock for `handle_create_post`.

        The route under test (`POST /posts`) reads `.id` off the handler's
        return value to populate the response body and the `Location` /
        `HX-Redirect` headers. A post-shaped `SimpleNamespace` (from
        `create_post_read`) suffices.
        """
        if post_read is None:
            post_read = cls.create_post_read()

        return {
            "src.api.routes.posts.handle_create_post": {
                "return_value_config": post_read
            }
        }

    @classmethod
    def create_post_edit_dependency_config(
        cls, post_read: SimpleNamespace = None
    ) -> Dict[str, Any]:
        """Mock for `handle_update_post`.

        The route under test (`PATCH /posts/{id}`) reads `.id`, `.kind`,
        and the per-kind detail relationship off the handler's return
        value to build the JSON response. A post-shaped `SimpleNamespace`
        (from `create_post_read`) covers that surface.
        """
        if post_read is None:
            post_read = cls.create_post_read(title="patched title", body="patched body")

        return {
            "src.api.routes.posts.handle_update_post": {
                "return_value_config": post_read
            }
        }

    @classmethod
    def create_post_delete_dependency_config(cls) -> Dict[str, Any]:
        """Mock for `handle_delete_post`.

        The route under test (`DELETE /posts/{id}`) discards the handler
        return value and emits a 204 with `HX-Redirect: /posts`, so `None`
        is a valid mock return.
        """
        return {
            "src.api.routes.posts.handle_delete_post": {"return_value_config": None}
        }
