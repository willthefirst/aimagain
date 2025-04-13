import os
from collections.abc import AsyncGenerator
from fastapi import Depends


from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
# Import Session and sessionmaker for ORM
from sqlalchemy.orm import sessionmaker, Session
from dotenv import load_dotenv

# Load environment variables from .env file
load_dotenv()

# Use environment variable or default to a file named chat_app.db
# Example: DATABASE_URL="sqlite:///./chat_app.db"
DATABASE_URL = os.getenv("DATABASE_URL")

engine = create_async_engine(DATABASE_URL)
async_session_maker = async_sessionmaker(engine, expire_on_commit=False)

async def create_db_and_tables():
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)


async def get_async_session() -> AsyncGenerator[AsyncSession, None]:
    async with async_session_maker() as session:
        yield session


async def get_db(session: AsyncSession = Depends(get_async_session)):
    yield SQLAlchemyUserDatabase(session, User)