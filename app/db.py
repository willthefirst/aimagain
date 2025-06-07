import logging
import os
from collections.abc import AsyncGenerator
from typing import Any

from dotenv import load_dotenv
from fastapi import Depends
from fastapi_users.db import SQLAlchemyUserDatabase
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from .models import User, metadata

load_dotenv()

DATABASE_URL = os.getenv("DATABASE_URL")
if not DATABASE_URL:
    raise ValueError("DATABASE_URL environment variable is not set")

engine = create_async_engine(DATABASE_URL)
async_session_maker = async_sessionmaker(engine, expire_on_commit=False)


# Dependency to get the raw SQLAlchemy AsyncSession
async def get_db_session() -> AsyncGenerator[AsyncSession, None]:
    async with async_session_maker() as session:
        yield session


# Dependency to get the FastAPI Users database adapter
async def get_user_db(
    session: AsyncSession = Depends(get_db_session),
) -> SQLAlchemyUserDatabase[User, Any]:
    yield SQLAlchemyUserDatabase(session, User)


async def check_database_health() -> bool:
    """
    Check if the database connection is working and all required tables exist.
    Returns True if healthy, raises an exception if not.
    """
    logger = logging.getLogger(__name__)

    try:
        async with async_session_maker() as session:
            # Test basic connection
            await session.execute(text("SELECT 1"))
            logger.info("Database connection successful")

            # Check if all required tables exist
            expected_tables = set(metadata.tables.keys())

            # Query for existing tables (SQLite specific)
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

            logger.info(f"All required tables present: {expected_tables}")
            return True

    except Exception as e:
        logger.error(f"Database health check failed: {e}")
        raise
