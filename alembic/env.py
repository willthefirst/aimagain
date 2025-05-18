import os
import sys
from logging.config import fileConfig

from sqlalchemy import engine_from_config, pool

from alembic import context

# Ensure the app directory is in the Python path
# This allows us to import 'app.db' and 'app.models'
sys.path.insert(0, os.path.realpath(os.path.join(os.path.dirname(__file__), "..")))

# Import the metadata object from your models package
# from app.models import Base # Old import
from app.models import metadata  # Correct import via __init__.py

# this is the Alembic Config object, which provides
# access to the values within the .ini file in use.
config = context.config

# Interpret the config file for Python logging.
# This line sets up loggers basically.
if config.config_file_name is not None:
    fileConfig(config.config_file_name)

# ---> DATABASE_URL is no longer needed here
# ---> The URL should be set via the Config object (e.g., from alembic.ini or conftest.py)
# config.set_main_option('sqlalchemy.url', DATABASE_URL)


# add your model's MetaData object here
# for 'autogenerate' support
# Use the imported metadata
# target_metadata = Base.metadata # Old way
target_metadata = metadata  # Corrected

# other values from the config, defined by the needs of env.py,
# can be acquired:
# my_important_option = config.get_main_option("my_important_option")
# ... etc.


def run_migrations_offline() -> None:
    """Run migrations in 'offline' mode.

    This configures the context with just a URL
    and not an Engine, though an Engine is acceptable
    here as well.  By skipping the Engine creation
    we don't even need a DBAPI to be available.

    Calls to context.execute() here emit the given string to the
    script output.

    """
    # Get the URL from the config (set externally)
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
    """Run migrations in 'online' mode.

    In this scenario we need to create an Engine
    and associate a connection with the context.

    """
    # engine_from_config uses the sqlalchemy.url from the config object
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
