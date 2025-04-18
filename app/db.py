import os
from collections.abc import AsyncGenerator
from typing import Any
from fastapi import Depends
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.orm import sessionmaker, Session, DeclarativeBase, declarative_base
from dotenv import load_dotenv
from fastapi_users.db import SQLAlchemyUserDatabase
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


# Removed the old get_db function which was causing confusion.
# Table creation logic should ideally be handled separately (e.g., Alembic migrations or a startup event).
# async def get_db(
#     session: AsyncGenerator[SQLAlchemyUserDatabase[User, Any], Any] = Depends(
#         get_async_session # Renamed to get_user_db
#     ),
# ):
#     async with engine.begin() as conn:
#         await conn.run_sync(metadata.create_all)

#     try:
#         yield session
#     finally:
#         await session.close() # Closing handled by context manager in get_user_db/get_db_session


# async def get_user_db(session: AsyncSession = Depends(get_async_session)): # Old definition
# yield SQLAlchemyUserDatabase(session, User)
