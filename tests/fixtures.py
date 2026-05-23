from typing import Any, AsyncGenerator

import pytest
from asyncstdlib import anext
from fastapi import Depends, FastAPI
from fastapi_users.db import SQLAlchemyUserDatabase
from httpx import ASGITransport, AsyncClient
from sqlalchemy import delete, event
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from src.db import get_db_session, get_user_db
from src.domain.logic.users.schema import UserCreate
from src.domain.models import User, metadata
from src.framework.rendering.templating import templates
from src.main import app

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


@pytest.fixture(scope="function")
async def authenticated_client(
    test_client: AsyncClient,
    db_test_session_manager: async_sessionmaker[AsyncSession],
    test_app: FastAPI,
) -> AsyncGenerator[AsyncClient, None]:
    from src.auth_config import get_user_manager

    user_data = UserCreate(
        email="testuser@example.com",
        password="password123",
        username="testuser",
    )
    user_manager_dependency = test_app.dependency_overrides.get(
        get_user_db, get_user_db
    )

    await create_test_user(db_test_session_manager, user_data, get_user_manager)

    login_data = {
        # fastapi-users uses email as the OAuth2 "username" field.
        "username": user_data.email,
        "password": user_data.password,
    }
    res = await test_client.post("/auth/jwt/login", data=login_data)

    cookie = res.headers["Set-Cookie"]
    access_token = cookie.split(";")[0].split("=")[1]

    test_client.headers["Cookie"] = f"fastapiusersauth={access_token}"

    yield test_client

    del test_client.headers["Cookie"]


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
