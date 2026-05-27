"""Consumer server management for contract tests.

The consumer server hosts only the HTML page(s) whose form submission is the
contract under test. It is deliberately minimal — Playwright drives a browser
against it, intercepts the outbound API call, and forwards it to the Pact mock
service. Anything that talks to a real database or service is out of scope.
"""

import logging
import uuid
from typing import Optional

import uvicorn
from fastapi import FastAPI, Request

from src.auth_config import current_active_user, current_admin_user
from src.domain import template_globals  # noqa: F401  # populates Jinja env globals
from src.domain.logic.clinicians.schema import ClinicianCreate
from src.domain.logic.programs.schema import ProgramCreate
from src.domain.models.enums import (
    ORGANIZATION_TYPES,
    ORGANIZATION_TYPES_LABELS,
)
from src.domain.routes import auth_pages
from src.framework import APIResponse

from ..utilities.mocks import MockAuthManager, create_mock_user
from .base import ServerManager, setup_health_check_route

# Stable UUID used by the admin-actions stub page so consumer tests can build
# the pact path against a known target id without round-tripping a database.
STUB_TARGET_USER_ID = uuid.UUID("11111111-1111-1111-1111-111111111111")

# Stable UUID used by the post-edit stub page; matches `STUB_POST_ID` in
# `tests/test_contract/constants.py`.
STUB_POST_ID = uuid.UUID("22222222-2222-2222-2222-222222222222")

# Stable UUID used by the clinician-edit stub page; matches
# `STUB_CLINICIAN_ID` in `tests/test_contract/constants.py`.
STUB_CLINICIAN_ID = uuid.UUID("44444444-4444-4444-4444-444444444444")

# Stable Org id seeded by the program-create stub page so the form's
# `org_id` dropdown has a deterministic option to select; matches
# `STUB_PROGRAM_FORM_ORG_ID` in `tests/test_contract/constants.py`.
STUB_PROGRAM_FORM_ORG_ID = uuid.UUID("77777777-7777-7777-7777-777777777777")


class ConsumerServerConfig:
    """Toggles for which page routes the consumer server should mount.

    Add a new flag (and a matching `app.include_router(...)` call in
    `setup_consumer_app_routes`) when introducing a contract test pair for a
    new HTML form.
    """

    def __init__(
        self,
        auth_pages: bool = True,
        users_admin_actions: bool = False,
        posts_owner_actions: bool = False,
        clinician_create_form: bool = False,
        clinician_edit_form: bool = False,
        organization_create_form: bool = False,
        program_create_form: bool = False,
        mock_auth: bool = True,
    ):
        self.auth_pages = auth_pages
        self.users_admin_actions = users_admin_actions
        self.posts_owner_actions = posts_owner_actions
        self.clinician_create_form = clinician_create_form
        self.clinician_edit_form = clinician_edit_form
        self.organization_create_form = organization_create_form
        self.program_create_form = program_create_form
        self.mock_auth = mock_auth


def _setup_users_admin_actions_stub(app: FastAPI) -> None:
    """Mount a stub page that renders the real `users/detail.html` template
    with hardcoded admin and target user objects, so the admin-actions partial
    is exercised without needing a database. The contract surface is the
    HTMX-decorated buttons inside the partial; what we render here is the same
    partial production code paths render.
    """

    class _StubUser:
        def __init__(self, **kwargs):
            self.__dict__.update(kwargs)

    @app.get("/users/{target_user_id}")
    async def admin_actions_stub_page(request: Request, target_user_id: uuid.UUID):
        target_user = _StubUser(
            id=target_user_id,
            username="target_user",
            email="target@example.com",
            is_active=True,
            is_superuser=False,
            is_verified=True,
        )
        # The page route relies on `current_user` being set in context; the
        # mocked `current_active_user` dependency above places it on
        # request.state via fastapi-users, but for the stub we pass it directly.
        current_user = _StubUser(
            id=uuid.UUID("00000000-0000-0000-0000-000000000001"),
            username="admin_user",
            is_superuser=True,
        )
        return APIResponse.html_response(
            template_name="users/detail.html",
            # `can_admin_actions` mirrors what the production handler would
            # compute (admin viewing a non-self target). The contract under
            # test is the admin-actions partial's HTMX shape; pass the flag
            # the partial reads after the named-flag refactor.
            context={
                "target_user": target_user,
                "current_user": current_user,
                "can_admin_actions": True,
            },
            request=request,
        )


def _setup_post_owner_actions_stub(app: FastAPI) -> None:
    """Mount a stub page that renders the real `posts/referrals/detail.html`
    template with hardcoded post + current_user, so the
    `posts/_shared/_owner_actions.html` partial is exercised without
    needing a database. The contract surface is the HTMX-decorated
    Delete button inside the partial; what we render here is the same
    partial production code paths render.

    `referral` is the canonical kind for this contract — the
    owner-actions partial is shared across both URL families and the
    HTMX wire shape is identical, so picking one kind covers the
    contract surface.
    """
    from ...tests.shared.mock_data_factory import make_post_stub

    class _StubAttrs:
        def __init__(self, **kwargs):
            self.__dict__.update(kwargs)

    @app.get("/referrals/{post_id}")
    async def post_owner_actions_stub_page(request: Request, post_id: uuid.UUID):
        # `make_post_stub` populates the per-kind detail relationship
        # with realistic per-column defaults (JSON columns → `[]`,
        # enum-typed Text columns → values from `_ENUM_DEFAULTS`) so
        # the detail template renders cleanly without per-stub
        # overrides. Owner id equals post id here so the partial's
        # owner-or-admin gate is a don't-care (current_user is a
        # superuser).
        post = make_post_stub(
            "referral",
            post_id=post_id,
            owner_id=post_id,
            owner_username="post_owner",
        )
        # The mock auth in `run_consumer_server_process` makes current_user a
        # superuser when `posts_owner_actions=True`, so the partial's
        # owner-or-admin gate renders the buttons regardless of post.owner_id.
        current_user = _StubAttrs(
            id=uuid.UUID("00000000-0000-0000-0000-000000000002"),
            username="admin_user",
            is_superuser=True,
        )
        return APIResponse.html_response(
            template_name="posts/referrals/detail.html",
            # The detail template reads `referral` from context (the
            # framework injects it as `spec.name`); `entity_name` lets
            # the shared `_owner_actions.html` partial build kind-aware
            # URLs. `can_edit` mirrors what the production handler
            # computes for an admin viewer.
            context={
                "referral": post,
                "entity_name": "referral",
                "current_user": current_user,
                "can_edit": True,
            },
            request=request,
        )


def _setup_clinician_create_form_stub(app: FastAPI) -> None:
    """Mount a stub page that renders the real `clinicians/form_new.html`
    template, so the create-form's HTMX submit is exercised without
    needing a database. The contract surface is the form's `POST
    /clinicians` request shape (URL family renamed in #642 PR 4);
    what we render here is the same template production code paths
    render.
    """

    class _StubAttrs:
        def __init__(self, **kwargs):
            self.__dict__.update(kwargs)

    @app.get("/clinicians/form")
    async def clinician_create_form_stub_page(request: Request):
        current_user = _StubAttrs(
            id=uuid.UUID("00000000-0000-0000-0000-000000000003"),
            username="clinician_user",
            is_superuser=False,
        )
        # The Org-picker dropdown reads `orgs` from the template context
        # (#524). One stub Org keeps the contract test deterministic.
        org = _StubAttrs(
            id=uuid.UUID("66666666-6666-6666-6666-666666666666"),
            name="Acme Counseling",
        )
        return APIResponse.html_response(
            template_name="clinicians/form_new.html",
            # `schema` is what the template's `field_for` macro
            # introspects to derive each control — same key the
            # production `make_new_form_handler` binds from
            # `spec.create_adapter`.
            context={
                "current_user": current_user,
                "schema": ClinicianCreate,
                "orgs": [org],
            },
            request=request,
        )


def _setup_clinician_edit_form_stub(app: FastAPI) -> None:
    """Mount a stub page that renders the real `clinicians/form_edit.html`
    template with a hardcoded clinician, so the practice-fields PATCH form is
    exercised without needing a database. The contract surface is the form's
    `PATCH /clinicians/{id}` request shape (URL family renamed in #642 PR 4).
    """

    class _StubAttrs:
        def __init__(self, **kwargs):
            self.__dict__.update(kwargs)

    @app.get("/clinicians/{clinician_id}/form")
    async def clinician_edit_form_stub_page(request: Request, clinician_id: uuid.UUID):
        org_id = uuid.UUID("55555555-5555-5555-5555-555555555555")
        org = _StubAttrs(id=org_id, name="Acme Counseling")
        clinician = _StubAttrs(
            id=clinician_id,
            # `org_id` + `org.name` replaces the former `practice_name`
            # column (#524). The form template reads `clinician.org_id`
            # for the dropdown's selected option and iterates the
            # `orgs` context var to render options.
            org_id=org_id,
            org=org,
            # `first_name`, `last_name`, and `npi` are empty optional
            # text inputs on the stub. They live in the "Clinician"
            # fieldset which renders first, so the form serializes them
            # ahead of `org_id` in the encoded body.
            first_name=None,
            last_name=None,
            npi=None,
            location_city="Brooklyn",
            location_state="NY",
            location_zip="11201",
            in_person_sessions="yes",
            virtual_sessions="please_contact",
            # Insurance posture stub: empty carrier list (no in-network) +
            # OON off keeps the form's bool radios deterministic.
            accepts_out_of_network=False,
            in_network_carriers=[],
            sliding_scale=False,
            cost=None,
            # `affiliations` is the inline list (#642 PR 1) the template
            # renders below the practice-fields form. Empty here so the
            # "No affiliations yet." branch renders without adding extra
            # forms that would compete for the practice form's selectors.
            affiliations=[],
            licensures=[],
            educations=[],
            certifications=[],
        )
        current_user = _StubAttrs(
            id=uuid.UUID("00000000-0000-0000-0000-000000000004"),
            username="clinician_user",
            is_superuser=False,
        )
        return APIResponse.html_response(
            template_name="clinicians/form_edit.html",
            # The framework binds `context[spec.name] = target`; after
            # #642 PR 4 the entity name is "clinician".
            context={
                "clinician": clinician,
                "current_user": current_user,
                "orgs": [org],
            },
            request=request,
        )


def _setup_organization_create_form_stub(app: FastAPI) -> None:
    """Mount a stub page that renders the real `organizations/form_new.html`
    template, so the create-form's HTMX submit is exercised without a
    database. The template reads `ORGANIZATION_TYPES` /
    `ORGANIZATION_TYPES_LABELS` directly from context (the production
    path injects them from `ORGANIZATION_ENTITY.static_context`), so the
    stub does the same."""

    class _StubAttrs:
        def __init__(self, **kwargs):
            self.__dict__.update(kwargs)

    @app.get("/organizations/form")
    async def organization_create_form_stub_page(request: Request):
        current_user = _StubAttrs(
            id=uuid.UUID("00000000-0000-0000-0000-000000000005"),
            username="organization_owner",
            is_superuser=False,
        )
        return APIResponse.html_response(
            template_name="organizations/form_new.html",
            context={
                "current_user": current_user,
                "ORGANIZATION_TYPES": ORGANIZATION_TYPES,
                "ORGANIZATION_TYPES_LABELS": ORGANIZATION_TYPES_LABELS,
                # The `?type=` picker bypasses this stub's no-db path;
                # when `?type=` is set the form branch renders
                # `parent_org_options`. Empty list = no parent choices,
                # which is the correct stub default (no db).
                "parent_org_options": [],
            },
            request=request,
        )


def _setup_program_create_form_stub(app: FastAPI) -> None:
    """Mount a stub page that renders the real `programs/form_new.html`
    template, so the create-form's HTMX submit is exercised without a
    database. The form's `org_id` dropdown reads `organizations` from
    context (production path: `program_form_extras` scopes the list to
    the user's owned Orgs); the stub seeds one Org so the pact body is
    deterministic."""

    class _StubAttrs:
        def __init__(self, **kwargs):
            self.__dict__.update(kwargs)

    @app.get("/programs/form")
    async def program_create_form_stub_page(request: Request):
        current_user = _StubAttrs(
            id=uuid.UUID("00000000-0000-0000-0000-000000000006"),
            username="program_owner",
            is_superuser=False,
        )
        org = _StubAttrs(id=STUB_PROGRAM_FORM_ORG_ID, name="Acme Counseling")
        return APIResponse.html_response(
            template_name="programs/form_new.html",
            context={
                "current_user": current_user,
                "schema": ProgramCreate,
                "organizations": [org],
            },
            request=request,
        )


def setup_consumer_app_routes(app: FastAPI, config: ConsumerServerConfig) -> None:
    if config.auth_pages:
        app.include_router(auth_pages.auth_pages_api_router)
    if config.users_admin_actions:
        _setup_users_admin_actions_stub(app)
    if config.posts_owner_actions:
        _setup_post_owner_actions_stub(app)
    if config.clinician_create_form:
        _setup_clinician_create_form_stub(app)
    if config.clinician_edit_form:
        _setup_clinician_edit_form_stub(app)
    if config.organization_create_form:
        _setup_organization_create_form_stub(app)
    if config.program_create_form:
        _setup_program_create_form_stub(app)


def run_consumer_server_process(
    host: str, port: int, config: Optional[ConsumerServerConfig] = None
) -> None:
    logger = logging.getLogger("consumer_server")

    if config is None:
        config = ConsumerServerConfig()

    consumer_app = FastAPI(title="Consumer Test Server Process")
    setup_health_check_route(consumer_app)

    setup_consumer_app_routes(consumer_app, config)

    if config.mock_auth:
        logger.info("Adding mock auth for contract tests")
        # When an admin/owner-actions stub is mounted, the mock user must be
        # a superuser so the partial's `is_superuser` (or owner-or-admin)
        # gate renders the buttons.
        mock_user = create_mock_user(
            email="test@example.com",
            username="contract_test_user",
            is_superuser=config.users_admin_actions or config.posts_owner_actions,
        )
        MockAuthManager.setup_mock_auth(
            consumer_app, mock_user, current_active_user, current_admin_user
        )

    uvicorn.run(consumer_app, host=host, port=port, log_level="warning")


class ConsumerServerManager(ServerManager):
    def start_with_config(self, config: Optional[ConsumerServerConfig] = None) -> None:
        self.start(run_consumer_server_process, config)
