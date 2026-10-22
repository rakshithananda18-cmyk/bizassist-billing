"""
Alembic environment for BizAssist Task.

Manages ONLY the `ft_*` tables (app.db.Base). Billing's tables share the
database but belong to billing's own Alembic chain, so:
  * version table is `ft_alembic_version` (billing uses `alembic_version`);
  * autogenerate ignores every table that is not `ft_*`, so a revision here can
    never propose dropping or altering a billing table.
"""
import os
import sys
from logging.config import fileConfig

from alembic import context
from sqlalchemy import engine_from_config, pool

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app import config as app_config  # noqa: E402
from app.db import Base  # noqa: E402
from app.migration_scope import VERSION_TABLE, include_object  # noqa: E402
import app.models  # noqa: E402,F401  — registers ft_* tables

config = context.config
if config.config_file_name is not None and config.attributes.get("configure_logger", True):
    fileConfig(config.config_file_name, disable_existing_loggers=False)

target_metadata = Base.metadata


def run_migrations_offline() -> None:
    context.configure(
        url=app_config.DATABASE_URL,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        version_table=VERSION_TABLE,
        include_object=include_object,
        render_as_batch=app_config.IS_SQLITE,
    )
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    connectable = config.attributes.get("connection")
    if connectable is None:
        section = config.get_section(config.config_ini_section, {})
        section["sqlalchemy.url"] = app_config.DATABASE_URL
        connectable = engine_from_config(section, prefix="sqlalchemy.", poolclass=pool.NullPool)
        with connectable.connect() as connection:
            _run(connection)
    else:
        _run(connectable)


def _run(connection) -> None:
    context.configure(
        connection=connection,
        target_metadata=target_metadata,
        version_table=VERSION_TABLE,
        include_object=include_object,
        render_as_batch=app_config.IS_SQLITE,
    )
    with context.begin_transaction():
        context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
