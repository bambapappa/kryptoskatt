"""Alembic environment configuration."""

import os
import sys
from logging.config import fileConfig

from sqlalchemy import engine_from_config, pool
from alembic import context

# Add src to path for model imports
# Get the project root from alembic directory location
alembic_dir = os.path.dirname(__file__)
project_root = os.path.dirname(alembic_dir)
src_path = os.path.join(project_root, "src")
sys.path.insert(0, src_path)
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from kryptoskatt.config import settings
from kryptoskatt.db import normalize_db_url
from kryptoskatt.models import Base

# this is the Alembic Config object, which provides
# access to the values within the .ini file in use.
config = context.config

# Override sqlalchemy.url from settings (normalized to the psycopg 3 driver)
config.set_main_option("sqlalchemy.url", normalize_db_url(settings.database_url))

# Interpret the config file for Python logging.
# This line sets up loggers basically.
if config.config_file_name is not None:
    fileConfig(config.config_file_name)

# add your model's MetaData object here
# for 'autogenerate' support
target_metadata = Base.metadata

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
    connectable = engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )

    with connectable.connect() as connection:
        # Serialize migrations across replicas: several containers starting at
        # once must not run `alembic upgrade head` concurrently. The advisory
        # lock is session-scoped and released when this connection closes.
        # Commit immediately: the lock survives commit, and leaving this
        # implicit transaction open would swallow alembic's own transaction
        # (migrations would roll back on connection close).
        if connection.dialect.name == "postgresql":
            from sqlalchemy import text
            connection.execute(text("SELECT pg_advisory_lock(884729131)"))
            connection.commit()

        context.configure(connection=connection, target_metadata=target_metadata)

        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
