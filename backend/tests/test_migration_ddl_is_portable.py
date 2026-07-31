"""
tests/test_migration_ddl_is_portable.py — the ALTERs run on two databases
=========================================================================

`_COLUMN_MIGRATIONS` is ~150 hand-written `ALTER TABLE … ADD COLUMN` strings,
and every one of them is executed against **both** the local SQLite file and the
cloud Postgres.

SQLite has no real type system. `ADD COLUMN x DATETIME` is accepted there
because SQLite accepts *any* type name — including ones that do not exist. So a
SQLite-only spelling is indistinguishable from a correct one until the day it
reaches Postgres.

WHAT THIS COST — 2026-08-01
---------------------------
    ALTER TABLE users ADD COLUMN last_login DATETIME
    → psycopg2.errors.UndefinedObject: type "datetime" does not exist
    → _check_schema_integrity then found users.last_login still missing
    → RuntimeError raised at import time, uvicorn could not load the app
    → the Space crash-looped; every device got HTTP 503

WHY IT HAD NOT FIRED BEFORE
---------------------------
About a hundred earlier entries also say `DATETIME` and none has ever failed,
which is exactly what made this look safe. `create_all` had already created
those columns on the fresh Postgres database, so the ALTER was skipped as a
no-op. **`create_all` creates missing TABLES, never missing COLUMNS on a table
that already exists.** The landmine only arms for a column added to an EXISTING
table after the cloud moved to Postgres — `users.last_login` was the first one,
and without this gate every future one would be the same.

That is the property worth pinning: not "no entry says DATETIME" (they all do,
and rewriting them would be a large diff for no behaviour change) but "every
entry, as it will actually be executed, names a type Postgres has".
"""
import os
import re
import sys

os.environ.setdefault("JWT_SECRET",   "test-secret-for-migration-ddl-abc123")
os.environ.setdefault("DATABASE_URL", "sqlite:///./test_bizassist.db")
os.environ.setdefault("GROQ_API_KEY", "mock_groq_api_key")

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

import pytest

from database.migration import (
    _ADD_COLUMN_TYPE_RE,
    _COLUMN_MIGRATIONS,
    _TYPE_TRANSLATIONS,
    _portable_ddl,
)

# Base types Postgres actually has. A migration naming anything outside this set
# needs an entry in `_TYPE_TRANSLATIONS`, not a hopeful deploy.
_POSTGRES_TYPES = {
    "BIGINT", "BOOLEAN", "BYTEA", "CHAR", "CHARACTER", "DATE", "DECIMAL",
    "DOUBLE", "FLOAT", "INT", "INTEGER", "JSON", "JSONB", "NUMERIC", "REAL",
    "SMALLINT", "TEXT", "TIME", "TIMESTAMP", "UUID", "VARCHAR",
}


def _type_token(ddl: str):
    m = _ADD_COLUMN_TYPE_RE.search(ddl)
    return m.group(2).upper() if m else None


class TestEveryMigrationSurvivesPostgres:

    def test_the_list_is_not_empty(self):
        """Guard the guard.

        Every assertion below is a loop over `_COLUMN_MIGRATIONS`. If an import
        or a refactor ever left that list empty, all of them would pass while
        checking nothing.
        """
        assert len(_COLUMN_MIGRATIONS) > 50

    def test_every_type_token_is_parseable(self):
        """A DDL the regex cannot read is one it cannot translate either."""
        unparsed = [m["ddl"] for m in _COLUMN_MIGRATIONS
                    if _type_token(m["ddl"]) is None]
        assert not unparsed, (
            f"{len(unparsed)} migration(s) do not match the ADD COLUMN pattern, "
            f"so their types are never translated: {unparsed[:5]}"
        )

    def test_every_migration_names_a_type_postgres_has(self):
        """THE GATE. This is the test that would have caught the outage."""
        offenders = []
        for m in _COLUMN_MIGRATIONS:
            rendered = _portable_ddl(m["ddl"], "postgresql")
            token = _type_token(rendered)
            if token not in _POSTGRES_TYPES:
                offenders.append(f'{m["table"]}.{m["column"]} -> {token}')
        assert not offenders, (
            "These migrations would fail on the cloud Postgres. SQLite accepts "
            "any type name, so they look fine locally and take the Space down "
            "on deploy. Add a translation to _TYPE_TRANSLATIONS['postgresql']:\n"
            + "\n".join(offenders)
        )


class TestTheTranslationItself:

    def test_datetime_becomes_timestamp_on_postgres(self):
        assert _portable_ddl(
            "ALTER TABLE users ADD COLUMN last_login DATETIME", "postgresql"
        ) == "ALTER TABLE users ADD COLUMN last_login TIMESTAMP"

    def test_sqlite_is_left_exactly_as_written(self):
        """SQLite is the dialect these strings were written for.

        Translating there would change ~150 statements to fix a problem SQLite
        does not have.
        """
        ddl = "ALTER TABLE users ADD COLUMN last_login DATETIME"
        assert _portable_ddl(ddl, "sqlite") == ddl

    def test_a_trailing_default_is_preserved(self):
        """Only the type token moves. The rest of the statement is not ours."""
        out = _portable_ddl(
            "ALTER TABLE invoices ADD COLUMN created_at DATETIME DEFAULT NULL",
            "postgresql")
        assert out == "ALTER TABLE invoices ADD COLUMN created_at TIMESTAMP DEFAULT NULL"

    def test_a_column_named_like_a_type_is_not_rewritten(self):
        """The regex anchors on `ADD COLUMN <name> <TYPE>`, so the NAME is safe.

        A blanket string replace of "DATETIME" would corrupt this statement.
        """
        out = _portable_ddl(
            "ALTER TABLE logs ADD COLUMN datetime TEXT", "postgresql")
        assert out == "ALTER TABLE logs ADD COLUMN datetime TEXT"

    def test_an_unknown_dialect_is_left_alone(self):
        ddl = "ALTER TABLE users ADD COLUMN last_login DATETIME"
        assert _portable_ddl(ddl, "mysql") == ddl

    def test_translation_is_case_insensitive_on_the_type(self):
        assert _portable_ddl(
            "ALTER TABLE users ADD COLUMN last_login datetime", "postgresql"
        ) == "ALTER TABLE users ADD COLUMN last_login TIMESTAMP"


class TestTheColumnThatCausedTheOutage:

    def test_users_last_login_is_registered(self):
        entry = next((m for m in _COLUMN_MIGRATIONS
                      if m["table"] == "users" and m["column"] == "last_login"),
                     None)
        assert entry is not None, (
            "users.last_login is on the User model; without a migration entry "
            "_check_schema_integrity raises at import time and the app will not "
            "start at all"
        )

    def test_it_renders_valid_postgres(self):
        entry = next(m for m in _COLUMN_MIGRATIONS
                     if m["table"] == "users" and m["column"] == "last_login")
        assert _type_token(_portable_ddl(entry["ddl"], "postgresql")) == "TIMESTAMP"


class TestModelAndMigrationsAgree:
    """
    NOT TESTED HERE, deliberately: "every model column has a migration entry".

    I wrote that assertion first and it reported 100+ offenders — `users.
    username`, `vendors.name`, `products.sku` and so on. All false. Those
    columns were part of their tables from the first `create_all`, so no ALTER
    was ever needed and none exists. `_COLUMN_MIGRATIONS` holds only the columns
    ADDED to a table after it shipped, and nothing in the source distinguishes
    an original column from a later one — the information simply is not there.

    So the honest boundary is: a static test can check that every migration
    names a real model column (below), and that every migration is portable
    (above). Whether a model column NEEDS a migration is a question about
    deployment history, and `_check_schema_integrity` answers it at boot against
    the real database — which is exactly where it was answered on 2026-08-01.
    """

    def test_every_migration_targets_a_column_the_model_declares(self):
        """A migration for a column no model has is dead SQL.

        It runs on every fresh database, adds a column nothing reads, and is
        never noticed — the inverse of the outage, and the direction that IS
        statically decidable.
        """
        from database.models import Base

        # Some migrations legitimately target tables owned by other metadata
        # (core.models); those are not visible here and are not offenders.
        known_tables = set(Base.metadata.tables)

        orphans = []
        for m in _COLUMN_MIGRATIONS:
            table = Base.metadata.tables.get(m["table"])
            if table is None:
                if m["table"] in known_tables:
                    orphans.append(f'{m["table"]} (table missing from metadata)')
                continue
            if m["column"] not in table.c:
                orphans.append(f'{m["table"]}.{m["column"]}')

        assert not orphans, (
            "These migrations add columns no model declares — they run on every "
            "fresh database and nothing ever reads the result:\n"
            + "\n".join(sorted(orphans))
        )
