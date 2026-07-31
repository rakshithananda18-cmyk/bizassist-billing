"""
tests/test_sync_volume_and_tenancy.py — two defects found from the owner's screen
=================================================================================

Both were reported as questions, not bugs: "why so many sync?" and "why are more
staff showing than I created?". Both turned out to be real, and neither produced
an error anywhere.

────────────────────────────────────────────────────────────────────────────────
A. THE AUDIT LOG WAS BEING REPLICATED, UNFILTERED, ON EVERY PULL
────────────────────────────────────────────────────────────────────────────────
`table_alterations` is the per-database audit log — one row per audited write,
append-only, unbounded. It was in `MODEL_MAP`, so the pull returned it.

The pull applies its incremental filter conditionally:

    if "updated_at" in cols:
        query = query.filter(model_cls.updated_at > last_sync_dt)

`TableAlteration` has only `created_at`. **No column means no filter**, so
`since` was ignored and the ENTIRE table came down on EVERY pull, for ever.

Measured on the live database 2026-07-31:
  * 2,487 audit rows locally, the largest single table in the sync set;
  * the owner's panel sat at "Cloud→Local 0/768 Table Alterations", re-fetching
    the same 768 rows every cycle;
  * it was the ONLY table in MODEL_MAP missing `updated_at`.

Replicating it is also meaningless on its own terms: two databases' audit logs
describe two different sets of writes, so merging them reconciles nothing.

────────────────────────────────────────────────────────────────────────────────
B. EVERY STAFF ACCOUNT WAS HANDED ITS OWN BizID
────────────────────────────────────────────────────────────────────────────────
`_backfill_biz_ids` selected on `public_id IS NULL` with no owner predicate, so
cashiers were given a `public_id` — the TENANT identifier that
`_resolve_business_id_by_username` resolves against and every per-business sweep
counts.

Measured on the same database: ALL 32 staff rows carried a BizID against 9 real
owners. That is why the nightly job logged

    [SCHED] Running books integrity audit for 40 business(es)...

9 owners + 32 staff ≈ 40. Every per-business sweep was doing roughly five times
the work it should, over accounts that have no books of their own.
"""
import os
import sys

os.environ.setdefault("JWT_SECRET",   "test-secret-for-sync-volume-abcdef123")
os.environ.setdefault("DATABASE_URL", "sqlite:///./test_bizassist.db")
os.environ.setdefault("GROQ_API_KEY", "mock_groq_api_key")
os.environ.setdefault("CLOUD_API_URL", "http://127.0.0.1:9")

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

import pytest

from database.db import SessionLocal
from database.models import Base, User
from database.sync_map import MODEL_MAP
from services.auth import hash_password

OWNER_ID = 77310
STAFF_ID = 77311


@pytest.fixture(scope="module", autouse=True)
def ensure_schema():
    db = SessionLocal()
    try:
        Base.metadata.create_all(bind=db.get_bind())
    finally:
        db.close()


# ═════════════════════════════════════════════════════════════════════════════
# A. every synced table must be able to answer "what changed since X?"
# ═════════════════════════════════════════════════════════════════════════════

class TestEverySyncedTableIsFilterable:

    def test_no_synced_table_is_missing_updated_at(self):
        """THE GATE. A table with no `updated_at` silently opts OUT of the pull's
        incremental filter and is returned in full, for ever, at a cost that
        grows with the table. Nothing errors and nothing is logged.
        """
        offenders = [
            name for name, model in MODEL_MAP.items()
            if "updated_at" not in {c.name for c in model.__table__.columns}
        ]
        assert not offenders, (
            f"{offenders} would be returned IN FULL on every pull — the filter "
            "`if \"updated_at\" in cols` cannot apply to them. Add the column "
            "with a migration, or keep the table out of MODEL_MAP."
        )

    def test_the_guard_runs_at_import_not_only_here(self):
        """Adding a model to MODEL_MAP is a one-line change. The check has to
        fail in front of whoever makes it, not in CI an hour later."""
        from database import sync_map
        assert hasattr(sync_map, "_assert_pull_is_filterable")
        src = open(sync_map.__file__, encoding="utf-8").read()
        assert "\n_assert_pull_is_filterable()" in src, (
            "the guard is defined but never invoked at import time"
        )

    def test_the_guard_actually_rejects_an_unfilterable_table(self, monkeypatch):
        """A guard that cannot fail is decoration."""
        from database import sync_map
        from database.models import TableAlteration

        monkeypatch.setitem(sync_map.MODEL_MAP, "table_alterations", TableAlteration)
        with pytest.raises(RuntimeError, match="updated_at"):
            sync_map._assert_pull_is_filterable()

    def test_the_audit_log_is_not_replicated(self):
        """It is the log of what happened on THIS machine. Two databases' audit
        logs describe two different sets of writes, so merging them reconciles
        nothing — and this one is unbounded."""
        assert "table_alterations" not in MODEL_MAP

    def test_the_audit_log_still_does_not_audit_itself(self):
        """Unchanged, and worth pinning: self-auditing is unbounded recursion."""
        from database.models import EXCLUDED_TABLES
        assert "table_alterations" in EXCLUDED_TABLES


# ═════════════════════════════════════════════════════════════════════════════
# C. the outbox gate and the apply set must agree
# ═════════════════════════════════════════════════════════════════════════════

class TestTheOutboxOnlyQueuesWhatTheCloudCanApply:
    """`_SYNC_TABLES` decides what enters the outbox; `MODEL_MAP` decides what
    the cloud can apply. A table in the first but not the second is queued,
    transmitted, and discarded — silently, because `push_changes` only logs a
    warning and the worker acks whatever it sent.

    `users` was exactly that: 31 rows queued, 31 acked, 0 ever applied (live
    database, 2026-07-31). And a `users` payload is the whole row — bcrypt hash
    and settings JSON — put on the wire to a server that throws it away, which
    `routes/sync_staff.py` explicitly says must not happen.
    """

    def test_every_queued_table_can_actually_be_applied(self):
        from database.models import _SYNC_TABLES
        from database.sync_map import MODEL_MAP, PULL_ONLY_TABLES
        undeliverable = sorted(
            t for t in _SYNC_TABLES
            if t not in MODEL_MAP and t not in PULL_ONLY_TABLES
        )
        assert not undeliverable, (
            f"{undeliverable} enter the outbox but are not in MODEL_MAP, so the "
            "cloud skips them as 'unknown entity' and the worker acks them "
            "anyway. Every such row is a guaranteed-wasted round trip carrying a "
            "full serialized payload."
        )

    def test_users_is_not_queued(self):
        """Its payload is the bcrypt hash and the settings JSON. Staff have a
        dedicated path (`/api/sync/staff-push`) that sends only what is needed."""
        from database.models import _SYNC_TABLES
        assert "users" not in _SYNC_TABLES

    def test_staff_replication_still_has_its_own_route(self):
        """Removing `users` from the outbox must not remove staff replication —
        it was never the mechanism, but check, because that would be the obvious
        way to break cashier logins on a second device."""
        import routes.sync_staff as ss
        assert any(getattr(r, "path", "") == "/api/sync/staff-push"
                   for r in ss.router.routes)


# ═════════════════════════════════════════════════════════════════════════════
# D. the audit log must be able to name the row it is about
# ═════════════════════════════════════════════════════════════════════════════

class TestTheAuditLogCanIdentifyInsertedRows:
    """`record_id` was `str(inspect(obj).identity[0]) if identity else None`,
    evaluated in `after_flush`. For an INSERT the identity map is not populated
    until `after_flush_postexec`, so **every INSERT ever audited stored
    `record_id = NULL`** — the log could say a row was created and never which.

    Measured on the live database 2026-07-31: all 72 audited `users` INSERTs had
    a NULL record_id. Tracing 22 unexplained staff accounts therefore had to be
    done by matching audit timestamps against `users.created_at` to the
    millisecond.

    UPDATE and DELETE were unaffected (those objects are already persistent), so
    the log looked populated and mostly worked — which is why this survived.
    """

    def test_an_inserted_row_gets_a_record_id(self):
        from sqlalchemy import create_engine, Column, Integer, String
        from sqlalchemy.orm import declarative_base, sessionmaker
        from database.models import _audit_record_id

        LocalBase = declarative_base()

        class _Row(LocalBase):
            __tablename__ = "_audit_probe"
            id = Column(Integer, primary_key=True)
            name = Column(String)

        eng = create_engine("sqlite:///:memory:")
        LocalBase.metadata.create_all(eng)
        # The audit listener is GLOBAL — it fires on any Session flush and writes
        # to `table_alterations`. A probe database that only has the probe table
        # therefore fails with "no such table: table_alterations", which is the
        # listener working, not the test's subject failing. Create it here.
        from database.models import TableAlteration
        TableAlteration.__table__.create(eng, checkfirst=True)
        db = sessionmaker(bind=eng)()
        try:
            captured = {}
            from sqlalchemy import event, inspect as sa_inspect
            from sqlalchemy.orm import Session as SASession

            @event.listens_for(SASession, "after_flush")
            def _probe(session, ctx):
                for obj in session.new:
                    captured["old"] = sa_inspect(obj).identity
                    captured["new"] = _audit_record_id(obj)

            db.add(_Row(name="x"))
            db.flush()

            assert captured["old"] is None, (
                "the premise changed: inspect().identity now resolves during "
                "after_flush, so re-check whether this fix is still needed"
            )
            assert captured["new"] is not None, (
                "_audit_record_id returned None for an inserted row — the audit "
                "log is back to recording that something was created without "
                "recording what"
            )
        finally:
            db.close()

    def test_the_helper_is_what_the_listener_uses(self):
        import inspect as _i
        from database import models
        src = _i.getsource(models.audit_after_flush)
        assert "_audit_record_id(obj)" in src
        assert "inspect(obj).identity" not in src


# ═════════════════════════════════════════════════════════════════════════════
# D2. the audit log must record the identifier that survives crossing databases
# ═════════════════════════════════════════════════════════════════════════════

class TestTheAuditLogRecordsTheBizID:
    """Local and cloud number the same business differently BY DESIGN — the BizID
    (`public_id`) is the shared spine. The audit log recorded only per-database
    integers, so a row was unattributable the moment it was read anywhere other
    than where it was written.

    That was not hypothetical: this table used to be replicated between the two
    databases. Measured 2026-07-31 on the live database —

        business_id=42        25 rows, pointing at no local user (42 is the
                              CLOUD id for a business that is 7 locally)
        user_id 9, 42, 46, 86 resolve against nothing here

    and the danger is not just the dangling reference. The day a local row is
    assigned id 42, those rows start reading as *that* business — silently
    attributing someone's writes to the wrong tenant.
    """

    def test_the_audit_table_has_a_public_id(self):
        from database.models import TableAlteration
        assert "public_id" in {c.name for c in TableAlteration.__table__.columns}

    def test_the_listener_captures_it_from_the_request_context(self):
        import inspect as _i
        from database import models
        src = _i.getsource(models.audit_before_flush)
        assert "current_bizid_var" in src, (
            "the BizID is on the request context (set by the middleware from the "
            "token's public_id claim) and must be recorded — the integer "
            "business_id alone cannot survive crossing databases"
        )
        assert src.count('"public_id": public_id') == 3, (
            "all three actions (INSERT/UPDATE/DELETE) must record it"
        )

    def test_the_insert_statement_writes_the_column(self):
        """The row is written with raw SQL, so adding the model column is not
        enough — the INSERT has to name it or the value is silently dropped."""
        import inspect as _i
        from database import models
        src = _i.getsource(models.audit_after_flush)
        assert "public_id" in src.split("INSERT INTO table_alterations")[1][:400]
        assert '"public_id": item.get("public_id")' in src

    def test_a_migration_adds_it_without_inventing_history(self):
        """Historical rows keep NULL. Their BizID cannot be derived — the integer
        may point at a renumbered row or at nothing — and a guessed attribution
        in an audit log is worse than an admitted gap."""
        import inspect as _i
        from database import migration
        src = _i.getsource(migration)
        assert "ALTER TABLE table_alterations ADD COLUMN public_id" in src
        assert "inventing one would be worse" in src

    def test_the_audit_log_is_no_longer_replicated(self):
        """The reason those 25 foreign-id rows are here at all. Pinned in section
        A too; repeated here because this is the consequence that matters."""
        assert "table_alterations" not in MODEL_MAP


# ═════════════════════════════════════════════════════════════════════════════
# E. an unused staff login must be visible as unused
# ═════════════════════════════════════════════════════════════════════════════

class TestUnusedStaffAreIdentifiable:
    """The Staff screen showed a name, a role and a counter prefix. That made 22
    logins created during testing indistinguishable from the 2 real tills, so
    they accumulated for two weeks with nothing to point at.

    `last_login IS NULL` — never authenticated — is the only signal that
    separates them safely. Not name shape (someone will legitimately name a till
    `c_2`), not age (a seasonal counter is still real), not invoice count (a
    supply-adder raises none).
    """

    def test_users_has_a_last_login_column(self):
        assert "last_login" in {c.name for c in User.__table__.columns}

    def test_it_defaults_to_null_and_is_not_backfilled(self):
        """A row that predates the column must not be given an invented login
        time — that is the kind of guess that makes an audit trail worthless."""
        import inspect as _i
        from database import migration
        src = _i.getsource(migration)
        assert "ADD COLUMN last_login DATETIME" in src
        assert "last_login" in src and "NOT backfilled" in src

    def test_the_staff_api_reports_it(self):
        import inspect as _i
        from core.api import staff as staff_api
        src = _i.getsource(staff_api._staff_out)
        assert '"last_login"' in src
        assert '"created_at"' in src

    def test_login_stamps_it(self):
        import inspect as _i
        from routes import auth as auth_routes
        src = _i.getsource(auth_routes)
        assert "user.last_login = _utc_now()" in src

    def test_the_prune_script_keys_on_it_and_dry_runs(self):
        p = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..",
                         "scripts", "prune_unused_staff.py")
        assert os.path.exists(p)
        src = open(p, encoding="utf-8").read()
        assert "DRY RUN" in src and '"--apply"' in src
        # Never prunes an account that has been used, or one real data points at.
        assert 'last_login", None) is not None' in src
        assert "_in_use(" in src
        # Never touches an owner.
        assert "User.parent_business_id == owner.id" in src


# ═════════════════════════════════════════════════════════════════════════════
# B. a BizID identifies a TENANT, and a cashier is not one
# ═════════════════════════════════════════════════════════════════════════════

class TestOnlyOwnersGetABizID:

    @pytest.fixture
    def owner_and_staff(self):
        db = SessionLocal()
        try:
            db.query(User).filter(User.id.in_([OWNER_ID, STAFF_ID])).delete(
                synchronize_session=False)
            db.commit()
            db.add(User(id=OWNER_ID, username="bizid_owner",
                        password=hash_password("TestPass1!"),
                        business_name="BizID Test Co", role="enterprise",
                        public_id=None, parent_business_id=None))
            db.add(User(id=STAFF_ID, username="bizid_staff",
                        password=hash_password("TestPass1!"),
                        business_name="BizID Test Co", role="cashier",
                        public_id=None, parent_business_id=OWNER_ID))
            db.commit()
            yield db
        finally:
            db.query(User).filter(User.id.in_([OWNER_ID, STAFF_ID])).delete(
                synchronize_session=False)
            db.commit()
            db.close()

    def test_the_backfill_gives_the_owner_a_bizid(self, owner_and_staff):
        from database.migration import _backfill_biz_ids
        db = owner_and_staff
        _backfill_biz_ids(db)
        db.expire_all()
        assert db.query(User).filter(User.id == OWNER_ID).one().public_id

    def test_the_backfill_does_NOT_give_staff_one(self, owner_and_staff):
        """THE GATE. A cashier with a BizID reads as a separate business to every
        per-business sweep — which is how a 9-owner install came to log
        "Running books integrity audit for 40 business(es)".
        """
        from database.migration import _backfill_biz_ids
        db = owner_and_staff
        _backfill_biz_ids(db)
        db.expire_all()
        staff = db.query(User).filter(User.id == STAFF_ID).one()
        assert staff.public_id is None, (
            f"staff row was handed BizID {staff.public_id!r}. `public_id` is the "
            "tenant identifier — resolved by _resolve_business_id_by_username, "
            "keyed on by LAN discovery, counted by the nightly sweeps."
        )

    def test_it_is_idempotent(self, owner_and_staff):
        """It runs on every boot."""
        from database.migration import _backfill_biz_ids
        db = owner_and_staff
        _backfill_biz_ids(db)
        db.expire_all()
        first = db.query(User).filter(User.id == OWNER_ID).one().public_id
        _backfill_biz_ids(db)
        db.expire_all()
        assert db.query(User).filter(User.id == OWNER_ID).one().public_id == first

    def test_existing_damage_is_reported_not_silently_rewritten(self):
        """Clearing a public_id that something already points at is a destructive
        guess. The boot path reports the count and names the repair script."""
        import inspect
        from database import migration
        src = inspect.getsource(migration._backfill_biz_ids)
        assert "clear_staff_bizids" in src
        assert "NOT cleared automatically" in src

    def test_the_repair_script_exists_and_dry_runs_by_default(self):
        p = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..",
                         "scripts", "clear_staff_bizids.py")
        assert os.path.exists(p)
        src = open(p, encoding="utf-8").read()
        assert '"--apply"' in src and "DRY RUN" in src
        # It must never touch an owner, and never delete anything.
        assert "User.parent_business_id != None" in src
        assert ".delete(" not in src
