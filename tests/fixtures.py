import uuid
from typing import Any, AsyncGenerator

import pytest
from asyncstdlib import anext
from fastapi import Depends, FastAPI
from fastapi_users.db import SQLAlchemyUserDatabase
from fastapi_users.password import PasswordHelper
from httpx import ASGITransport, AsyncClient
from sqlalchemy import delete, event
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from src.auth_config import get_strategy
from src.db import get_db_session, get_user_db
from src.domain.logic.users.schema import UserCreate
from src.domain.models import User, metadata
from src.framework.rendering.templating import templates
from src.main import app

# Session-cached auth constants. We pay Argon2 + JWT generation once per
# pytest session instead of per test. The DB schema is session-scoped but
# rows are wiped per test (see `_db_schema` / `db_test_session_manager`),
# so the user row is re-inserted each test — but with the pre-hashed
# password and pre-generated cookie, no Argon2 or `/auth/jwt/login`
# round-trip is needed.
TESTUSER_ID = uuid.UUID("00000000-0000-0000-0000-000000000001")
SUPERUSER_ID = uuid.UUID("00000000-0000-0000-0000-000000000002")
TESTUSER_EMAIL = "testuser@example.com"
SUPERUSER_EMAIL = "superuser@example.com"
_PASSWORD_HELPER = PasswordHelper()

TEST_DATABASE_URL = "sqlite+aiosqlite:///:memory:"

test_engine = create_async_engine(TEST_DATABASE_URL)
async_test_sessionmaker = async_sessionmaker(test_engine, expire_on_commit=False)


@event.listens_for(test_engine.sync_engine, "connect")
def _enable_sqlite_foreign_keys(dbapi_connection, connection_record):
    """Mirror src/db.py — FK enforcement must be on for tests to catch the
    same constraint violations as production."""
    if test_engine.dialect.name != "sqlite":
        return
    cursor = dbapi_connection.cursor()
    cursor.execute("PRAGMA foreign_keys = ON")
    cursor.close()


@pytest.fixture(scope="session", autouse=True)
async def _db_schema() -> AsyncGenerator[None, None]:
    """Create the schema once per pytest session — every
    `db_test_session_manager` consumer shares it. Per-test isolation is
    provided by the function-scoped fixture's teardown, which deletes all
    rows.

    Was function-scoped (drop_all + create_all per test, ~18ms each);
    the cost compounded across ~360 DB-touching tests. Moving schema
    setup to session scope plus switching teardown from `drop_all` to
    delete-all cuts the per-test fixture cost from ~18ms to ~3ms."""
    async with test_engine.begin() as conn:
        await conn.run_sync(metadata.create_all)
    yield
    async with test_engine.begin() as conn:
        await conn.run_sync(metadata.drop_all)


@pytest.fixture(scope="function")
async def db_test_session_manager() -> (
    AsyncGenerator[async_sessionmaker[AsyncSession], None]
):
    """Yield the sessionmaker; on teardown, delete all rows so the next
    test sees an empty DB. The schema itself is owned by the
    session-scoped `_db_schema` fixture so we pay the DDL cost once,
    not per test.

    SQLite-specific: `sqlite_sequence` keeps the max-used `INTEGER PRIMARY
    KEY AUTOINCREMENT` across deletes, so a test that asserts a specific
    autoincrement id (e.g. `assert created.id == 1`) would break here.
    We don't use `AUTOINCREMENT` — every primary key is a UUID — so this
    is a non-issue today. If we ever add an autoincrement column, also
    delete from `sqlite_sequence` in teardown."""
    yield async_test_sessionmaker
    async with async_test_sessionmaker() as session:
        # Reverse FK order so child rows go first and we don't trip FK
        # enforcement (enabled by `_enable_sqlite_foreign_keys` above).
        for table in reversed(metadata.sorted_tables):
            await session.execute(delete(table))
        await session.commit()


async def override_get_db_session() -> AsyncGenerator[AsyncSession, None]:
    async with async_test_sessionmaker() as session:
        yield session


async def override_get_user_db(
    # Depend on the *original* app dependency name; FastAPI substitutes the override.
    session: AsyncSession = Depends(get_db_session),
) -> SQLAlchemyUserDatabase[User, Any]:
    yield SQLAlchemyUserDatabase(session, User)


@pytest.fixture(scope="function")
def test_app(
    db_test_session_manager: async_sessionmaker[AsyncSession],
) -> FastAPI:
    app.dependency_overrides[get_db_session] = override_get_db_session
    app.dependency_overrides[get_user_db] = override_get_user_db

    # Expose app in Jinja globals so url_for resolves during tests.
    original_app_global = templates.env.globals.get("app")
    templates.env.globals["app"] = app

    yield app
    app.dependency_overrides.clear()
    if original_app_global is not None:
        templates.env.globals["app"] = original_app_global
    elif "app" in templates.env.globals:
        del templates.env.globals["app"]


@pytest.fixture(scope="function")
async def test_client(test_app: FastAPI) -> AsyncGenerator[AsyncClient, None]:
    async with AsyncClient(
        transport=ASGITransport(app=test_app),
        base_url="http://test",
    ) as client:
        yield client


async def create_test_user(
    session_maker: async_sessionmaker[AsyncSession],
    user_data: UserCreate,
    user_manager_dependency: Any,
) -> User:
    async with session_maker() as session:
        user_manager_gen = user_manager_dependency(
            SQLAlchemyUserDatabase(session, User)
        )
        user_manager = await anext(user_manager_gen)
        try:
            user = await user_manager.create(user_data)
            await session.commit()
            await session.refresh(user)
            return user
        finally:
            try:
                await anext(user_manager_gen)
            except StopAsyncIteration:
                pass
            if hasattr(user_manager_gen, "aclose"):
                await user_manager_gen.aclose()


@pytest.fixture(scope="session")
def _cached_password_hash() -> str:
    """Argon2 is intentionally slow (~50-100ms). Hash once per session
    and reuse the digest for every fixture-built user row."""
    return _PASSWORD_HELPER.hash("password123")


async def _write_token_for(user_id: uuid.UUID) -> str:
    """Build the JWT for a fixed UUID. `write_token` only reads `.id`,
    so a transient `User` stub suffices — we don't touch the DB."""
    stub = User(id=user_id)
    return await get_strategy().write_token(stub)


@pytest.fixture(scope="session")
async def _testuser_cookie_value() -> str:
    return await _write_token_for(TESTUSER_ID)


@pytest.fixture(scope="session")
async def _superuser_cookie_value() -> str:
    return await _write_token_for(SUPERUSER_ID)


async def _insert_user_row(
    session_maker: async_sessionmaker[AsyncSession],
    *,
    user_id: uuid.UUID,
    email: str,
    username: str,
    hashed_password: str,
    is_superuser: bool = False,
) -> None:
    """Insert a verified user row directly. Bypasses
    `user_manager.create` (which re-hashes the password). The
    `on_after_register` hook in dev only sets `is_verified=True` — we
    set it inline here."""
    async with session_maker() as session:
        session.add(
            User(
                id=user_id,
                email=email,
                username=username,
                hashed_password=hashed_password,
                is_active=True,
                is_verified=True,
                is_superuser=is_superuser,
            )
        )
        await session.commit()


@pytest.fixture(scope="function")
async def authenticated_client(
    test_client: AsyncClient,
    db_test_session_manager: async_sessionmaker[AsyncSession],
    test_app: FastAPI,
    _cached_password_hash: str,
    _testuser_cookie_value: str,
) -> AsyncGenerator[AsyncClient, None]:
    await _insert_user_row(
        db_test_session_manager,
        user_id=TESTUSER_ID,
        email=TESTUSER_EMAIL,
        username="testuser",
        hashed_password=_cached_password_hash,
    )
    test_client.headers["Cookie"] = f"fastapiusersauth={_testuser_cookie_value}"
    yield test_client
    del test_client.headers["Cookie"]


@pytest.fixture(scope="function")
async def superuser_client(
    test_client: AsyncClient,
    db_test_session_manager: async_sessionmaker[AsyncSession],
    test_app: FastAPI,
    _cached_password_hash: str,
    _superuser_cookie_value: str,
) -> AsyncGenerator[AsyncClient, None]:
    await _insert_user_row(
        db_test_session_manager,
        user_id=SUPERUSER_ID,
        email=SUPERUSER_EMAIL,
        username="superuser",
        hashed_password=_cached_password_hash,
        is_superuser=True,
    )
    test_client.headers["Cookie"] = f"fastapiusersauth={_superuser_cookie_value}"
    yield test_client

    del test_client.headers["Cookie"]


@pytest.fixture(scope="function")
async def superuser_logged_in_user(
    superuser_client: AsyncClient,
    db_test_session_manager: async_sessionmaker[AsyncSession],
) -> "User":
    """Provides the User object for the default superuser."""
    async with db_test_session_manager() as session:
        from src.domain.logic.users.repository import UserRepository

        user_repo = UserRepository(session)
        user = await user_repo.get_user_by_email("superuser@example.com")
        if not user:
            pytest.fail(
                "Superuser 'superuser@example.com' not found in DB for superuser_logged_in_user fixture"
            )
        return user


@pytest.fixture(scope="function")
async def logged_in_user(
    authenticated_client: AsyncClient,
    db_test_session_manager: async_sessionmaker[AsyncSession],
) -> User:
    """Provides the User object for the default authenticated user."""
    async with db_test_session_manager() as session:
        from src.domain.logic.users.repository import UserRepository

        user_repo = UserRepository(session)
        user = await user_repo.get_user_by_email("testuser@example.com")
        if not user:
            pytest.fail(
                "Test user 'testuser@example.com' not found in DB for logged_in_user fixture"
            )
        return user
