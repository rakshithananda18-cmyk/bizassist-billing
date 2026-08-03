"""
tests/test_staff_login_name_unique.py — one login name per business, in the DB
==============================================================================

`create_staff` already refuses a duplicate, and it is correct. But it only
guards the path that goes through it, and the path that actually created the
duplicates did not: `data_transfer._upsert_users` matched staff on the INTERNAL
`username`, which each database derives differently on purpose —

    local   `_internal_staff_username`  ->  counter_1__7
    cloud   `_resolve_username`         ->  counter_1_c7

— so it never matched across a transfer and INSERTed a second row every run.
Measured on the live database 2026-07-31: business 7 held 24 cashier logins
against 2 real tills, including two rows both named `counter_1` with identical
bcrypt hashes.

Architecture rule 11: application-level uniqueness is not uniqueness.

WHAT THE DUPLICATE BROKE
------------------------
1. Login became non-deterministic. `routes/auth.py` resolves a staff login with
   `.filter(parent_business_id, lower(staff_login_name)).first()` and NO ORDER
   BY, so which row authenticates is arbitrary — and their `user_id` differs, so
   shifts and audit rows attribute to different accounts.
2. The cloud tombstone became ambiguous. `routes/sync_staff.py` deletes by
   `(parent_business_id, lower(staff_login_name))`. With one row per name that is
   exact; with two, removing a local duplicate could delete the cashier's real
   cloud account.

The index is what makes `staff_login_name` a genuinely stable key, so (2) is
safe by construction rather than by care.
"""
import os
import sys

os.environ.setdefault("JWT_SECRET",   "test-secret-for-staff-unique-abc123")
os.environ.setdefault("DATABASE_URL", "sqlite:///./test_bizassist.db")
os.environ.setdefault("GROQ_API_KEY", "mock_groq_api_key")

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

import pytest
from sqlalchemy import create_engine, text

from database.models import Base

OWNER_A = 55100
OWNER_B = 55200


@pytest.fixture
def conn(tmp_path):
    """A real database with the real schema and the real migration step."""
    eng = create_engine(f"sqlite:///{tmp_path}/staff_unique.db")
    Base.metadata.create_all(eng)
    c = eng.connect()
    for oid, name in ((OWNER_A, "Biz A"), (OWNER_B, "Biz B")):
        c.execute(text(
            "INSERT INTO users (id,username,password,business_name,role) "
            "VALUES (:i,:u,'x',:b,'enterprise')"),
            {"i": oid, "u": f"owner{oid}", "b": name})
    c.commit()
    try:
        yield c
    finally:
        c.close()


def _add_staff(c, owner, login_name, username):
    c.execute(text(
        "INSERT INTO users (username,staff_login_name,password,business_name,"
        "role,parent_business_id) VALUES (:u,:l,'x','B','cashier',:p)"),
        {"u": username, "l": login_name, "p": owner})
    c.commit()


class TestTheIndexInstallsAndHolds:

    def test_it_installs_on_a_clean_database(self, conn):
        from database.migration import _ensure_staff_login_name_unique_index
        _ensure_staff_login_name_unique_index(conn)
        found = conn.execute(text(
            "SELECT 1 FROM sqlite_master WHERE type='index' "
            "AND name='uix_users_staff_login_per_business'")).fetchone()
        assert found

    def test_a_second_row_with_the_same_name_is_rejected(self, conn):
        """THE GATE — this is the state that made staff login a coin toss."""
        from database.migration import _ensure_staff_login_name_unique_index
        from sqlalchemy.exc import IntegrityError
        _ensure_staff_login_name_unique_index(conn)

        _add_staff(conn, OWNER_A, "counter_1", "counter_1__A")
        with pytest.raises(IntegrityError):
            _add_staff(conn, OWNER_A, "counter_1", "counter_1_c7")

    def test_it_is_case_insensitive(self, conn):
        """`create_staff` and the login resolver both compare with lower(); the
        index has to agree or it guards a different rule than the code does."""
        from database.migration import _ensure_staff_login_name_unique_index
        from sqlalchemy.exc import IntegrityError
        _ensure_staff_login_name_unique_index(conn)

        _add_staff(conn, OWNER_A, "counter_1", "c1_a")
        with pytest.raises(IntegrityError):
            _add_staff(conn, OWNER_A, "COUNTER_1", "c1_a_upper")

    def test_two_businesses_may_both_have_counter_1(self, conn):
        """The name is per-BUSINESS (§9.5). A global constraint would break the
        product — `create_staff`'s own docstring says two businesses can both
        have 'counter_1'."""
        from database.migration import _ensure_staff_login_name_unique_index
        _ensure_staff_login_name_unique_index(conn)

        _add_staff(conn, OWNER_A, "counter_1", "counter_1__A")
        _add_staff(conn, OWNER_B, "counter_1", "counter_1__B")   # must not raise

        n = conn.execute(text(
            "SELECT COUNT(*) FROM users WHERE lower(staff_login_name)='counter_1'"
        )).scalar()
        assert n == 2

    def test_owners_are_unaffected(self, conn):
        """Owners have NULL parent_business_id and no login name; NULLs must not
        collide with each other or no second business could be created."""
        from database.migration import _ensure_staff_login_name_unique_index
        _ensure_staff_login_name_unique_index(conn)

        conn.execute(text(
            "INSERT INTO users (id,username,password,business_name,role) "
            "VALUES (55300,'owner3','x','Biz C','enterprise')"))
        conn.commit()
        assert conn.execute(text(
            "SELECT COUNT(*) FROM users WHERE parent_business_id IS NULL")).scalar() == 3


class TestItRefusesToInstallOverExistingDuplicates:

    def test_duplicates_block_it_and_are_reported(self, conn, caplog):
        """Two rows sharing a login name are two CREDENTIALS. Choosing which to
        drop decides who can log in — not a call a boot-time migration may make.
        Same stance as the M-3 and M-11 indexes."""
        from database.migration import _ensure_staff_login_name_unique_index
        import logging

        _add_staff(conn, OWNER_A, "counter_1", "counter_1__A")
        _add_staff(conn, OWNER_A, "counter_1", "counter_1_c7")   # pre-existing dupe

        with caplog.at_level(logging.ERROR):
            _ensure_staff_login_name_unique_index(conn)

        assert conn.execute(text(
            "SELECT 1 FROM sqlite_master WHERE type='index' "
            "AND name='uix_users_staff_login_per_business'")).fetchone() is None
        # `LogRecord.getMessage()` applies args exactly once. `r.message % r.args`
        # double-formats — caplog has already interpolated, so the second pass
        # raises "not all arguments converted during string formatting".
        assert any("one-login-name-per-business" in r.getMessage()
                   for r in caplog.records)

    def test_the_error_names_the_repair_command(self, caplog, conn):
        """A migration that reports a problem without saying what to do about it
        is a log line nobody acts on."""
        from database.migration import _ensure_staff_login_name_unique_index
        import logging

        _add_staff(conn, OWNER_A, "counter_1", "a1")
        _add_staff(conn, OWNER_A, "counter_1", "a2")
        with caplog.at_level(logging.ERROR):
            _ensure_staff_login_name_unique_index(conn)
        blob = " ".join(r.getMessage() for r in caplog.records)
        assert "prune_unused_staff.py" in blob
        assert "--dedupe-keep" in blob

    def test_it_installs_once_the_duplicates_are_gone(self, conn):
        from database.migration import _ensure_staff_login_name_unique_index
        _add_staff(conn, OWNER_A, "counter_1", "a1")
        _add_staff(conn, OWNER_A, "counter_1", "a2")
        _ensure_staff_login_name_unique_index(conn)          # blocked

        conn.execute(text("DELETE FROM users WHERE username='a2'"))
        conn.commit()
        _ensure_staff_login_name_unique_index(conn)          # now installs

        assert conn.execute(text(
            "SELECT 1 FROM sqlite_master WHERE type='index' "
            "AND name='uix_users_staff_login_per_business'")).fetchone()


class TestItIsWiredIntoTheBootPath:

    def test_the_migration_runner_calls_it(self):
        import inspect
        from database import migration
        src = inspect.getsource(migration.run_migrations_and_seed)
        assert "_ensure_staff_login_name_unique_index" in src

    def test_it_runs_through_step_so_a_failure_cannot_abort_the_boot(self):
        """Rule 58: one connection is shared by every backfill, and on Postgres a
        failed statement aborts the whole transaction."""
        import inspect
        from database import migration
        src = inspect.getsource(migration.run_migrations_and_seed)
        assert "_step(conn, _ensure_staff_login_name_unique_index)" in src


class TestTheSupersededModuleIsGone:
    """`routes/migrate.py` was DELETED on 2026-08-03.

    WHAT THIS CLASS USED TO ASSERT, AND WHY IT CHANGED
    --------------------------------------------------
    While the file was retained it had to be *loud* — three tests read its
    source and checked the deprecation banner, the two inline `⚠ DEPRECATED —
    DEFECT` markers, and that the header named every hazard. Those tests were
    the right ones for a file kept on purpose. They are meaningless for a file
    that no longer exists, and leaving them would only fail on
    FileNotFoundError, which says nothing.

    They are replaced by the property that actually matters and outlives the
    file: **it must not come back.** The module carried a live BizID-overwrite
    hazard — `_upsert_users` listed `public_id` in its update fields, so an
    import payload could overwrite the destination business's BizID, the tenant
    identity spine (`docs/CLEANUP_PLAN_2026-07-31.md` §1.2). `data_transfer.py`
    excludes it. Reviving this file, or copying `_upsert_users` out of git
    history, reopens that.

    The other tests in this class are unchanged and still meaningful: they check
    the app does not mount it, no module imports it, no client calls
    `/api/migrate/*`, and the live suites exercise `data_transfer` instead.
    """

    def test_it_is_still_unmounted(self):
        src = open(os.path.join(os.path.dirname(os.path.abspath(__file__)),
                                "..", "main_groq.py"), encoding="utf-8").read()
        assert "routes.migrate" not in src

    def test_the_file_is_gone_and_stays_gone(self):
        """The deletion itself, pinned.

        Not housekeeping: the file's `_upsert_users` could overwrite a
        business's `public_id` — the BizID, which is the only identifier that
        may cross a database boundary (core/identity.py). A file that cannot be
        executed is safe; a file someone un-comments is not, and 1,080 lines of
        commented-out code is an invitation.
        """
        p = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..",
                         "routes", "migrate.py")
        assert not os.path.exists(p), (
            "routes/migrate.py is back. It carries a BizID-overwrite hazard "
            "(`public_id` in _upsert_users' update fields) that "
            "routes/data_transfer.py deliberately excludes. Use data_transfer."
        )

    def test_its_three_siblings_are_gone_too(self):
        """`routes/{insights,smart_insights,sales}.py` went in the same pass.

        `routes/sales.py` matters for the same reason as migrate.py rather than
        for tidiness: it put `uid_token` in every invoice response. That is the
        share-link secret behind `GET /public/invoice/{uid_token}`, which serves
        an invoice to anyone holding it, unauthenticated. `core/api/sales.py`
        does not expose it (CLEANUP_PLAN §1b).
        """
        routes = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..",
                              "routes")
        for name in ("insights.py", "smart_insights.py", "sales.py"):
            assert not os.path.exists(os.path.join(routes, name)), (
                f"routes/{name} is back — it is superseded and unmounted. "
                "See docs/CLEANUP_PLAN_2026-07-31.md §1b."
            )

    def test_the_live_tests_no_longer_exercise_the_dead_copy(self):
        """Testing an unmounted module is worse than not testing it — it reports
        green for code that cannot run, while the code that does run is
        unchecked."""
        here = os.path.dirname(os.path.abspath(__file__))
        for fn in ("test_sync_migration_fixes.py", "test_uid_cross_db.py"):
            src = open(os.path.join(here, fn), encoding="utf-8").read()
            assert "from routes.data_transfer import" in src
            assert "from routes.migrate import" not in src

    def test_nothing_in_the_backend_imports_it(self):
        """THE GATE. A deprecated module with a live importer is not deprecated,
        it is just undocumented."""
        backend = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
        offenders = []
        for root, dirs, files in os.walk(backend):
            dirs[:] = [d for d in dirs
                       if d not in ("__pycache__", "venv", ".git", "chroma_db")]
            for fn in files:
                if not fn.endswith(".py"):
                    continue
                p = os.path.join(root, fn)
                if os.path.basename(p) in ("migrate.py",
                                           "test_staff_login_name_unique.py"):
                    continue
                try:
                    src = open(p, encoding="utf-8").read()
                except Exception:
                    continue
                for line in src.splitlines():
                    s = line.strip()
                    if s.startswith("#"):
                        continue          # a comment ABOUT it is fine
                    if ("from routes.migrate import" in s
                            or s == "import routes.migrate"
                            or "from routes import migrate" in s):
                        offenders.append(f"{os.path.relpath(p, backend)}: {s}")
        assert not offenders, (
            "routes/migrate.py is deprecated and unmounted, but is imported by: "
            f"{offenders}. Use routes.data_transfer."
        )

    def test_its_endpoints_are_not_served(self):
        """`/api/migrate/*` and `/api/data-transfer/*` are DIFFERENT paths. The
        deprecated module declares the former and is not mounted, so nothing may
        call those paths expecting a response.

        This is the failure mode that would be silent: a caller left on
        `/api/migrate/count` gets a 404, and the feature it drives (the
        cloud-data sync nudge in `loginSync.js`) just never fires.
        """
        backend = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
        repo = os.path.abspath(os.path.join(backend, ".."))

        # Nothing in the mounted app declares /api/migrate/*
        main_src = open(os.path.join(backend, "main_groq.py"), encoding="utf-8").read()
        assert "routes.migrate" not in main_src

        # …and no client calls it.
        callers = []
        for sub in ("frontend-billing/src", "desktop/src"):
            d = os.path.join(repo, sub)
            if not os.path.isdir(d):
                continue
            for root, dirs, files in os.walk(d):
                dirs[:] = [x for x in dirs if x not in ("node_modules", "dist")]
                for fn in files:
                    if not fn.endswith((".js", ".jsx", ".ts", ".tsx")):
                        continue
                    p = os.path.join(root, fn)
                    try:
                        if "api/migrate" in open(p, encoding="utf-8").read():
                            callers.append(os.path.relpath(p, repo))
                    except Exception:
                        continue
        assert not callers, (
            f"these call /api/migrate/* which is NOT served (the mounted module "
            f"declares /api/data-transfer/*): {callers}"
        )
