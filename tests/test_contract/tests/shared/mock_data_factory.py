"""Factory for consistent mock data and dependency-override configs.

Each `create_*_dependency_config()` returns a mapping of fully-qualified
handler paths to mock configuration. The provider server fixture
(`tests/test_contract/conftest.py::provider_server`) consumes this mapping to
monkey-patch business-logic handlers, so Pact verification exercises only the
route layer.

`make_post_stub(kind, **field_overrides)` is the registry-backed builder
for Post-shaped `SimpleNamespace` stubs. The per-kind detail relationship
name and field tuple come from `POST_KINDS`, and the per-column default
values are inferred from the SQLAlchemy column type (JSON → ``[]``,
Boolean → ``False``, Uuid → ``uuid4()``, DateTime → ``now()``) so the
detail page renders without crashing on list-typed fields. For Text
columns that hold enum values (CHECK-constrained), `_ENUM_DEFAULTS`
supplies a per-kind realistic value so the template's display-label
lookup resolves.

Adding or renaming a column on a detail model is a one-place change —
the spec's `detail_fields` picks it up, and the type-introspecting
default picks the right primitive. New enum-typed columns need a
matching entry in `_ENUM_DEFAULTS`; the test
`test_mock_data_factory.test_make_post_stub_renders_detail_html` is
the canary that catches a missing entry by surfacing the template
crash at test time rather than waiting for a contract pair to fail.
"""

from datetime import datetime, timezone
from types import SimpleNamespace
from typing import Any, Dict
from uuid import UUID, uuid4

import sqlalchemy

from src.domain.logic.users.schema import UserRead
from src.domain.models import POST_KINDS
from src.domain.models.posts.intake_detail import (
    IntakeDetail,
)
from src.domain.models.posts.opening_detail import (
    OpeningDetail,
)
from src.domain.models.posts.referral_detail import ReferralDetail

# Per-kind detail model — keyed by the same discriminator that
# `POST_KINDS` uses. Lives in test code (not the production spec) so
# the test-only stub factory doesn't push its concerns onto the
# production registry. Adding a new kind: add an entry here and an
# entry to `_ENUM_DEFAULTS` (if the new detail row has CHECK-Text
# columns).
_DETAIL_MODELS: dict[str, type] = {
    "referral": ReferralDetail,
    "clinician_opening": OpeningDetail,
    "program_intake": IntakeDetail,
}


# Per-kind defaults for Text columns that hold enum values
# (CHECK-constrained to a vocabulary in `src.domain.models.enums`).
# Without these, columns like `gender` would default to `"stub gender"`
# — a string the detail template's display-label lookup
# (`GENDER_LABELS["stub gender"]`) can't resolve, which crashes the
# render. Values chosen here are *valid* enum members, picked for
# neutrality where possible (`gender = "prefer_not_to_say"` rather
# than the alphabetical first option).
#
# An empty dict for a kind means "no enum-typed Text columns on this
# detail row" — PA and intake hold their enum values
# on the linked Provider / Program rather than on the detail row
# itself.
_ENUM_DEFAULTS: dict[str, dict[str, Any]] = {
    "referral": {
        "location_in_person": "no",
        "location_virtual": "no",
        "gender": "prefer_not_to_say",
        "network_preference": "no_preference",
        "location_state": "NY",
        # `insurance_carrier` is nullable and only meaningful when
        # `network_preference != "no_preference"`. Default to None so
        # the detail template's gating (`if d.insurance_carrier and
        # ...`) renders nothing.
        "insurance_carrier": None,
    },
    "clinician_opening": {},
    "program_intake": {},
}


def _column_default(col: sqlalchemy.Column, kind: str) -> Any:
    """Pick a realistic default for a detail-row column.

    Type-dispatch table:

      JSON         → ``[]`` (template iterates these as lists; a
                     string default would iterate chars and crash
                     label-dict lookups)
      Boolean      → ``False``
      Uuid         → ``uuid4()`` (one fresh id per stub instance)
      DateTime     → ``datetime.now(timezone.utc)`` (no DateTime
                     columns on detail rows today; included for
                     forward-compat)
      Text         → ``_ENUM_DEFAULTS[kind][col.name]`` if the column
                     is registered there (enum-typed); else
                     ``f"stub {col.name}"``.
    """
    col_type = col.type
    if isinstance(col_type, sqlalchemy.JSON):
        return []
    if isinstance(col_type, sqlalchemy.Boolean):
        return False
    if isinstance(col_type, sqlalchemy.types.Uuid):
        return uuid4()
    if isinstance(col_type, (sqlalchemy.DateTime, sqlalchemy.types.DateTime)):
        return datetime.now(timezone.utc)
    kind_enum_defaults = _ENUM_DEFAULTS.get(kind, {})
    if col.name in kind_enum_defaults:
        return kind_enum_defaults[col.name]
    return f"stub {col.name}"


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

    Detail fields default per their SQLAlchemy column type via
    :func:`_column_default` — list-typed fields get ``[]``, enum-typed
    Text fields get the registry value from :data:`_ENUM_DEFAULTS`,
    other Text fields get ``f"stub {name}"``. Override individually
    via ``**field_overrides``. Unknown overrides for the kind are
    passed through onto the detail `SimpleNamespace` (caller's
    responsibility not to send cross-kind fields).
    """
    spec = POST_KINDS[kind]
    detail_model = _DETAIL_MODELS[kind]
    spec_field_names = set(spec.detail_fields)
    detail_values: dict[str, Any] = {}
    for col in detail_model.__table__.columns:
        if col.name not in spec_field_names:
            # `spec.detail_fields` excludes `post_id` — skip anything
            # the spec wouldn't consider a user-facing field.
            continue
        detail_values[col.name] = _column_default(col, kind)
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
    def create_forgot_password_dependency_config(cls) -> Dict[str, Any]:
        """Mocks for `POST /auth/forgot-password`.

        Unlike the local-handler pairs above, fastapi-users' bundled
        `get_reset_password_router()` calls `BaseUserManager.get_by_email`
        and then `BaseUserManager.forgot_password` directly — there is
        no local wrapper to patch. Mock both methods on our concrete
        `UserManager` subclass so the route returns 202 without
        touching the (empty) test database or attempting to send an
        email.

        `get_by_email` returns a Post-shaped `SimpleNamespace` standing
        in for a User row; `forgot_password` is a no-op AsyncMock. The
        route discards both return values, so the stub shape is
        irrelevant beyond "not None / no exception."
        """
        stub_user = SimpleNamespace(
            id=UUID("00000000-0000-0000-0000-000000000007"),
            email=cls.TEST_EMAIL,
            is_active=True,
            is_verified=True,
        )
        return {
            "src.auth_config.UserManager.get_by_email": {
                "return_value_config": stub_user
            },
            "src.auth_config.UserManager.forgot_password": {
                "return_value_config": None
            },
        }

    @classmethod
    def create_reset_password_dependency_config(cls) -> Dict[str, Any]:
        """Mock for `POST /auth/reset-password`.

        Same rationale as `create_forgot_password_dependency_config` —
        fastapi-users' router calls `BaseUserManager.reset_password`
        directly, no local handler in between. The mock returns None;
        the route discards the return value and emits 200 on success.
        """
        return {
            "src.auth_config.UserManager.reset_password": {"return_value_config": None},
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
        """Mock for the generic delete handler bound to the unified
        `/posts` URL family (the consumer-side owner-actions stub
        renders a referral-kind post via `posts/detail.html`; see
        `_setup_post_owner_actions_stub`).

        The route file `src.domain.routes.posts` binds
        `make_delete_handler(POST_ENTITY)` and assigns it to the
        module-level `_handle_delete_post` attribute so test patches
        can target it (the mount layer's `_resolve_handler` reads from
        the handler's `__module__`).

        The route under test (`DELETE /posts/{id}`) discards the
        handler return value and emits a 204 with `HX-Redirect: /posts`,
        so `None` is a valid mock return.
        """
        return {
            "src.domain.routes.posts._handle_delete_post": {"return_value_config": None}
        }

    @classmethod
    def create_clinician_create_dependency_config(cls) -> Dict[str, Any]:
        """Mock for the factory-built `_handle_create_clinician`.

        The route under test (`POST /clinicians`) reads `id` off
        the handler's return value to build the response body and the
        `Location` / `HX-Redirect` headers. A `SimpleNamespace` exposing
        `id` is sufficient. The framework stitches the auto-bound
        handler onto the route module, naming it after `spec.name`; the
        spec name flipped to `"clinician"` in #642 PR 4, so patches
        target `_handle_create_clinician` (not the pre-rename
        `_handle_create_provider`).
        """
        stub_clinician = SimpleNamespace(
            id=UUID("33333333-3333-3333-3333-333333333333"),
        )
        return {
            "src.domain.routes.clinicians._handle_create_clinician": {
                "return_value_config": stub_clinician
            }
        }

    @classmethod
    def create_organization_create_dependency_config(cls) -> Dict[str, Any]:
        """Mock for the factory-built `_handle_create_organization`.

        The route under test (`POST /organizations`) reads `id` off the
        handler's return value to build the response body and the
        `Location` / `HX-Redirect` headers. A `SimpleNamespace` exposing
        `id` is sufficient. The framework stitches the auto-bound handler
        onto the route module, so contract patches target
        `src.domain.routes.organizations._handle_create_organization`.
        """
        stub_organization = SimpleNamespace(
            id=UUID("88888888-8888-8888-8888-888888888888"),
        )
        return {
            "src.domain.routes.organizations._handle_create_organization": {
                "return_value_config": stub_organization
            }
        }

    @classmethod
    def create_program_create_dependency_config(cls) -> Dict[str, Any]:
        """Mock for the factory-built `_handle_create_program`.

        The route under test (`POST /programs`) reads `id` off the
        handler's return value to build the response body and the
        `Location` / `HX-Redirect` headers. A `SimpleNamespace` exposing
        `id` is sufficient.
        """
        stub_program = SimpleNamespace(
            id=UUID("99999999-9999-9999-9999-999999999999"),
        )
        return {
            "src.domain.routes.programs._handle_create_program": {
                "return_value_config": stub_program
            }
        }

    @classmethod
    def create_clinician_update_dependency_config(cls) -> Dict[str, Any]:
        """Mock for `handle_update_clinician` (factory-built).

        The route under test (`PATCH /clinicians/{id}`) packs the
        handler's return value through `ClinicianRead.model_validate` —
        so the stub must expose every field that schema requires. The
        framework names the auto-bound update handler after `spec.name`;
        post-#642 PR 4 that's `clinician`, so the mock targets
        `_handle_update_clinician`.
        """
        from datetime import datetime, timezone

        now = datetime.now(timezone.utc)
        stub_clinician = SimpleNamespace(
            id=UUID("44444444-4444-4444-4444-444444444444"),
            owner_id=UUID("00000000-0000-0000-0000-000000000004"),
            created_at=now,
            updated_at=now,
            # `org_id` + `org_name` replace the former `practice_name`
            # (#524). `ClinicianRead.model_validate` reads `org_name` off
            # this stub via `from_attributes`.
            org_id=UUID("55555555-5555-5555-5555-555555555555"),
            org_name="Acme Counseling",
            location_city="Brooklyn",
            location_state="NY",
            location_zip="11201",
            in_person_sessions="yes",
            virtual_sessions="please_contact",
            # Insurance posture on Clinician: empty carrier list (no
            # in-network) + OON off keeps this stub deterministic.
            accepts_out_of_network=False,
            in_network_carriers=[],
            sliding_scale=False,
            cost=None,
            licensures=[],
            educations=[],
            certifications=[],
        )
        # After B3 (#330) the per-entity `handle_update_clinician` is
        # bound by `make_update_handler(CLINICIAN_ENTITY)` and assigned
        # to the module-level `_handle_update_clinician` attr so contract
        # patches retarget here. The mount layer's `_resolve_handler`
        # reads from `__module__`.
        return {
            "src.domain.routes.clinicians._handle_update_clinician": {
                "return_value_config": stub_clinician
            }
        }
