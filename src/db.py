import logging
import os
from collections.abc import AsyncGenerator
from typing import Any

from dotenv import load_dotenv
from fastapi import Depends
from fastapi_users.db import SQLAlchemyUserDatabase
from sqlalchemy import event, text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from src.domain.models import User, metadata

load_dotenv()

DATABASE_URL = os.getenv("DATABASE_URL")
if not DATABASE_URL:
    raise ValueError("DATABASE_URL environment variable is not set")

engine = create_async_engine(DATABASE_URL)
async_session_maker = async_sessionmaker(engine, expire_on_commit=False)


@event.listens_for(engine.sync_engine, "connect")
def _enable_sqlite_foreign_keys(dbapi_connection, connection_record):
    """SQLite ships with FK enforcement off by default; turn it on for every
    new connection. No-op for non-SQLite engines (e.g. future Postgres)."""
    if engine.dialect.name != "sqlite":
        return
    cursor = dbapi_connection.cursor()
    cursor.execute("PRAGMA foreign_keys = ON")
    cursor.close()


async def get_db_session() -> AsyncGenerator[AsyncSession, None]:
    async with async_session_maker() as session:
        yield session


async def get_user_db(
    session: AsyncSession = Depends(get_db_session),
) -> SQLAlchemyUserDatabase[User, Any]:
    yield SQLAlchemyUserDatabase(session, User)


async def check_database_health(skip_table_check=False) -> bool:
    """Verify connection plus presence of all metadata tables; raise if a migration is needed."""
    logger = logging.getLogger(__name__)

    try:
        async with async_session_maker() as session:
            await session.execute(text("SELECT 1"))
            logger.debug("Database connection successful")

            if skip_table_check:
                logger.debug("Skipping table existence check")
                return True

            expected_tables = set(metadata.tables.keys())

            result = await session.execute(
                text("SELECT name FROM sqlite_master WHERE type='table'")
            )
            existing_tables = {row[0] for row in result.fetchall()}

            missing_tables = expected_tables - existing_tables

            if missing_tables:
                logger.error(f"Missing required tables: {missing_tables}")
                raise RuntimeError(
                    f"Database migration required. Missing tables: {missing_tables}"
                )

            logger.debug(f"All required tables present: {expected_tables}")
            return True

    except Exception as e:
        logger.error(f"Database health check failed: {e}")
        raise
