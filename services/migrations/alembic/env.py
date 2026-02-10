"""Alembic environment configuration for AgentGuard.

Reads DATABASE_URL from the environment variable, falling back to the
value configured in alembic.ini.  In online mode the TimescaleDB extension
is enabled before running migrations.
"""

import os
from logging.config import fileConfig

from alembic import context
from sqlalchemy import engine_from_config, pool, text

# Alembic Config object — provides access to values in alembic.ini
config = context.config

# Override sqlalchemy.url with DATABASE_URL env var when available
database_url = os.environ.get("DATABASE_URL")
if database_url:
    config.set_main_option("sqlalchemy.url", database_url)

# Interpret the config file for Python logging unless we are being
# invoked programmatically (e.g. from tests) without a config file.
if config.config_file_name is not None:
    fileConfig(config.config_file_name)

# SQLAlchemy MetaData object for autogenerate support.
# Set this to your model's Base.metadata if you want autogenerate.
target_metadata = None


def run_migrations_offline() -> None:
    """Run migrations in 'offline' mode.

    This configures the context with just a URL and not an Engine,
    which allows SQL to be emitted to the script output without
    requiring a live database connection.
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

    Creates an Engine and associates a connection with the context.
    TimescaleDB extension is enabled before running any migrations.
    """
    connectable = engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )

    with connectable.connect() as connection:
        # Enable TimescaleDB extension before running migrations
        connection.execute(text("CREATE EXTENSION IF NOT EXISTS timescaledb"))
        connection.commit()

        context.configure(
            connection=connection,
            target_metadata=target_metadata,
        )

        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
