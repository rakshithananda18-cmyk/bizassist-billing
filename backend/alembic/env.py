"""
Alembic migration environment for BizAssist.

Reads the database URL from the DATABASE_URL env var (same as the app), and
takes target metadata from the app's SQLAlchemy Base so `--autogenerate` sees
every model. Run alembic from the backend/ directory.
"""
import os
import sys
from logging.config import fileConfig

from sqlalchemy import engine_from_config, pool
from alembic import context

# Make the backend package importable when alembic runs from backend/.
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from database.db import Base, DATABASE_URL  # noqa: E402
import database.models  # noqa: E402,F401  — registers all tables on Base.metadata

config = context.config

if config.config_file_name is not None:
    fileConfig(config.config_file_name)

# URL comes from the environment, not alembic.ini.
# configparser uses % for interpolation, so percent-encoded chars (e.g. %40)
# must be doubled to %% before being set as a config option.
config.set_main_option("sqlalchemy.url", DATABASE_URL.replace("%", "%%"))

target_metadata = Base.metadata


def include_object(obj, name, type_, reflected, compare_to):
    """Keep autogenerate inside billing's own tables.

    The cloud database is shared with BizAssist Task, whose tables are all
    `ft_*` and are migrated by that repo's own chain (version table
    `ft_alembic_version`). Billing's models do not declare them, so without
    this filter `alembic revision --autogenerate` against the cloud DB would
    emit `op.drop_table(...)` for every one of them.
    """
    if type_ == "table" and name and name.startswith("ft_"):
        return False
    return True


def run_migrations_offline() -> None:
    """Emit SQL without a live DB connection."""
    context.configure(
        url=DATABASE_URL,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        render_as_batch=DATABASE_URL.startswith("sqlite"),  # SQLite ALTER support
        include_object=include_object,
    )
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    """Run migrations against a live DB connection."""
    section = config.get_section(config.config_ini_section, {})
    section["sqlalchemy.url"] = DATABASE_URL
    connectable = engine_from_config(
        section,
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )
    with connectable.connect() as connection:
        context.configure(
            connection=connection,
            target_metadata=target_metadata,
            render_as_batch=DATABASE_URL.startswith("sqlite"),
            include_object=include_object,
        )
        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
