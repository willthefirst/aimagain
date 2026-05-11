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

from src.api.common import APIResponse
from src.api.routes import auth_pages
from src.auth_config import current_active_user, current_admin_user
from src.schemas.providers.provider import ProviderCreate

from ..utilities.mocks import MockAuthManager, create_mock_user
from .base import ServerManager, setup_health_check_route

# Stable UUID used by the admin-actions stub page so consumer tests can build
# the pact path against a known target id without round-tripping a database.
STUB_TARGET_USER_ID = uuid.UUID("11111111-1111-1111-1111-111111111111")

# Stable UUID used by the post-edit stub page; matches `STUB_POST_ID` in
# `tests/test_contract/constants.py`.
STUB_POST_ID = uuid.UUID("22222222-2222-2222-2222-222222222222")

# Stable UUID used by the provider-edit stub page; matches
# `STUB_PROVIDER_ID` in `tests/test_contract/constants.py`.
STUB_PROVIDER_ID = uuid.UUID("44444444-4444-4444-4444-444444444444")


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
        provider_create_form: bool = False,
        provider_edit_form: bool = False,
        mock_auth: bool = True,
    ):
        self.auth_pages = auth_pages
        self.users_admin_actions = users_admin_actions
        self.posts_owner_actions = posts_owner_actions
        self.provider_create_form = provider_create_form
        self.provider_edit_form = provider_edit_form
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
    """Mount a stub page that renders the real `posts/detail.html` template
    with hardcoded post + current_user, so the `_owner_actions.html` partial
    is exercised without needing a database. The contract surface is the
    HTMX-decorated Delete button inside the partial; what we render here is
    the same partial production code paths render.
    """
    from ...tests.shared.mock_data_factory import make_post_stub

    class _StubAttrs:
        def __init__(self, **kwargs):
            self.__dict__.update(kwargs)

    @app.get("/posts/{post_id}")
    async def post_owner_actions_stub_page(request: Request, post_id: uuid.UUID):
        # The detail template reads the per-kind detail relationship;
        # `make_post_stub` populates it off `POST_KINDS`. Owner id
        # equals post id here so the partial's owner-or-admin gate is a
        # don't-care (current_user is a superuser).
        post = make_post_stub(
            "client_referral",
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
            template_name="posts/detail.html",
            # `can_edit` mirrors what the production handler would compute
            # for an admin viewer; the partial reads the named flag after
            # the affordance refactor (#279).
            context={"post": post, "current_user": current_user, "can_edit": True},
            request=request,
        )


def _setup_provider_create_form_stub(app: FastAPI) -> None:
    """Mount a stub page that renders the real `providers/form_new.html`
    template, so the create-form's HTMX submit is exercised without
    needing a database. The contract surface is the form's `POST
    /providers` request shape; what we render here is the same
    template production code paths render.
    """

    class _StubAttrs:
        def __init__(self, **kwargs):
            self.__dict__.update(kwargs)

    @app.get("/providers/form")
    async def provider_create_form_stub_page(request: Request):
        current_user = _StubAttrs(
            id=uuid.UUID("00000000-0000-0000-0000-000000000003"),
            username="provider_user",
            is_superuser=False,
        )
        return APIResponse.html_response(
            template_name="providers/form_new.html",
            # `schema` is what the template's `field_for` macro
            # introspects to derive each control — same key the
            # production `handle_get_provider_form` puts in context.
            context={"current_user": current_user, "schema": ProviderCreate},
            request=request,
        )


def _setup_provider_edit_form_stub(app: FastAPI) -> None:
    """Mount a stub page that renders the real `providers/form_edit.html`
    template with a hardcoded provider, so the practice-fields PATCH form is
    exercised without needing a database. The contract surface is the form's
    `PATCH /providers/{id}` request shape.
    """

    class _StubAttrs:
        def __init__(self, **kwargs):
            self.__dict__.update(kwargs)

    @app.get("/providers/{provider_id}/form")
    async def provider_edit_form_stub_page(request: Request, provider_id: uuid.UUID):
        provider = _StubAttrs(
            id=provider_id,
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
        current_user = _StubAttrs(
            id=uuid.UUID("00000000-0000-0000-0000-000000000004"),
            username="provider_user",
            is_superuser=False,
        )
        return APIResponse.html_response(
            template_name="providers/form_edit.html",
            context={"provider": provider, "current_user": current_user},
            request=request,
        )


def setup_consumer_app_routes(app: FastAPI, config: ConsumerServerConfig) -> None:
    if config.auth_pages:
        app.include_router(auth_pages.auth_pages_api_router)
    if config.users_admin_actions:
        _setup_users_admin_actions_stub(app)
    if config.posts_owner_actions:
        _setup_post_owner_actions_stub(app)
    if config.provider_create_form:
        _setup_provider_create_form_stub(app)
    if config.provider_edit_form:
        _setup_provider_edit_form_stub(app)


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
