import os
from collections.abc import AsyncGenerator
from fastapi import Depends
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.orm import sessionmaker, Session, DeclarativeBase, declarative_base
from dotenv import load_dotenv
from fastapi_users.db import SQLAlchemyUserDatabase
from .models import User, metadata

load_dotenv()

DATABASE_URL = os.getenv("DATABASE_URL")

engine = create_async_engine(DATABASE_URL)
async_session_maker = async_sessionmaker(engine, expire_on_commit=False)

async def get_async_session() -> AsyncGenerator[AsyncSession, None]:
    async with async_session_maker() as session:
        yield session

async def get_db(session: AsyncSession = Depends(get_async_session)):
    async with engine.begin() as conn:
        await conn.run_sync(metadata.create_all)

    try:
        yield session
    finally:
        await session.close()

async def get_user_db(session: AsyncSession = Depends(get_async_session)):
    yield SQLAlchemyUserDatabase(session, User)