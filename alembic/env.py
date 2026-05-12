import os
import sys
from logging.config import fileConfig

from sqlalchemy import engine_from_config, pool

from alembic import context

sys.path.insert(0, os.path.realpath(os.path.join(os.path.dirname(__file__), "..")))

from src.domain.models import metadata

config = context.config

if config.config_file_name is not None:
    fileConfig(config.config_file_name)

DATABASE_URL = os.getenv("DATABASE_URL")
if DATABASE_URL:
    if "sqlite+aiosqlite://" in DATABASE_URL:
        DATABASE_URL = DATABASE_URL.replace("sqlite+aiosqlite://", "sqlite://")
    config.set_main_option("sqlalchemy.url", DATABASE_URL)

if DATABASE_URL is None and not config.get_main_option("sqlalchemy.url"):
    raise RuntimeError(
        "DATABASE_URL is not set. For local development, run `dev setup` "
        "to create a .env file, or export DATABASE_URL directly."
    )

target_metadata = metadata


def run_migrations_offline() -> None:
    """Run migrations in 'offline' mode."""
    url = config.get_main_option("sqlalchemy.url")
    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
    )

    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    """Run migrations in 'online' mode."""
    connectable = engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )

    with connectable.connect() as connection:
        context.configure(connection=connection, target_metadata=target_metadata)

        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
