"""
tests/test_data_transfer_staff_identity.py — the transfer that duplicated staff
===============================================================================

THE DEFECT
----------
`routes/data_transfer.py::_upsert_users` matched staff rows on `username` — the
INTERNAL, globally-unique name. Each database derives that name differently, on
purpose:

    local   `_internal_staff_username`  ->  counter_1__7    (<bare>__<owner_id>)
    cloud   `_resolve_username`         ->  counter_1_c7    (<preferred>_c<n>)

Both name the same cashier. Matching on it therefore NEVER matched across a
transfer, so every cloud→local migration INSERTed a second row for every staff
member — and every subsequent run added more.

MEASURED ON THE LIVE DATABASE, 2026-07-31
-----------------------------------------
Business 7 held 24 cashier logins where the owner had created 2:

    id=88  counter_1__7   prefix C1     id=94  counter_1_c7   prefix C1
    id=89  counter_2__7   prefix C2     id=90  counter_2_c7   prefix C2
    + 20 more from earlier runs

88/94 and 89/90 have IDENTICAL bcrypt hashes — salted, so identical means
copied, not independently created. Their `created_at` values are ISO-`T`
strings carried verbatim from the source database's JSON, which is the
signature of this import path rather than of the sync engine.

WHY IT MATTERS BEYOND CLUTTER
-----------------------------
Staff login resolves with:

    db.query(User).filter(parent_business_id == owner.id,
                          lower(staff_login_name) == name).first()

`.first()` with no ORDER BY — so which of two rows named `counter_1`
authenticates is arbitrary, and their `user_id` differs, so shifts and audit
entries attribute to different rows.

THE FIX
-------
Match on `staff_login_name` scoped to the destination owner. That is the
per-business identity the cashier actually types, it is what `create_staff`
enforces as unique within a business, and it means the same thing in both
databases. Same rule as the BizID — see core/identity.py.
"""
import os
import sys

os.environ.setdefault("JWT_SECRET",   "test-secret-for-transfer-identity-abc123")
os.environ.setdefault("DATABASE_URL", "sqlite:///./test_bizassist.db")
os.environ.setdefault("GROQ_API_KEY", "mock_groq_api_key")
os.environ.setdefault("CLOUD_API_URL", "http://127.0.0.1:9")

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

import pytest
from sqlalchemy import inspect as sa_inspect

from database.db import SessionLocal
from database.models import Base, User
from services.auth import hash_password

OWNER_ID = 66400


@pytest.fixture(scope="module", autouse=True)
def ensure_schema():
    db = SessionLocal()
    try:
        Base.metadata.create_all(bind=db.get_bind())
    finally:
        db.close()


@pytest.fixture
def db():
    s = SessionLocal()
    s.query(User).filter(
        (User.id == OWNER_ID) | (User.parent_business_id == OWNER_ID)
    ).delete(synchronize_session=False)
    s.commit()
    s.add(User(id=OWNER_ID, username="transfer_owner",
               password=hash_password("TestPass1!"),
               business_name="Transfer Test Co", role="enterprise",
               public_id="BA-XFER01", parent_business_id=None))
    # The DESTINATION already has this cashier, under its own internal name.
    s.add(User(username="counter_1__%d" % OWNER_ID,
               staff_login_name="counter_1",
               password=hash_password("CashPass1!"),
               business_name="Transfer Test Co", role="cashier",
               counter_prefix="C1", parent_business_id=OWNER_ID))
    s.commit()
    try:
        yield s
    finally:
        s.query(User).filter(
            (User.id == OWNER_ID) | (User.parent_business_id == OWNER_ID)
        ).delete(synchronize_session=False)
        s.commit()
        s.close()


def _staff(db):
    return db.query(User).filter(User.parent_business_id == OWNER_ID).all()


def _incoming_from_the_other_database():
    """The SAME cashier as the destination already has, but carrying the other
    database's internal username — exactly what an export from the cloud looks
    like."""
    return [{
        "id": 9999,
        "username": "counter_1_c7",          # cloud's `_resolve_username` shape
        "staff_login_name": "counter_1",     # the identity that actually matches
        "password": hash_password("CashPass1!"),
        "business_name": "Transfer Test Co",
        "role": "cashier",
        "counter_prefix": "C1",
        "parent_business_id": 4242,          # the SOURCE's owner id, remapped below
    }]


class TestATransferDoesNotDuplicateStaff:

    def test_importing_the_same_cashier_updates_rather_than_inserts(self, db):
        """THE GATE. This is what produced 24 logins for 2 tills."""
        from routes.data_transfer import _upsert_users
        existing_tables = set(sa_inspect(db.bind).get_table_names())

        before = len(_staff(db))
        _upsert_users(db, _incoming_from_the_other_database(), OWNER_ID, existing_tables)
        db.commit()
        after = _staff(db)

        assert len(after) == before, (
            f"the import created a second row for a cashier that already exists: "
            f"{[(u.id, u.username, u.staff_login_name) for u in after]}"
        )
        assert sum(1 for u in after if u.staff_login_name == "counter_1") == 1

    def test_running_it_twice_is_idempotent(self, db):
        """Every transfer used to add another copy. An owner who migrated three
        times had three of everything."""
        from routes.data_transfer import _upsert_users
        existing_tables = set(sa_inspect(db.bind).get_table_names())

        for _ in range(3):
            _upsert_users(db, _incoming_from_the_other_database(), OWNER_ID, existing_tables)
            db.commit()

        assert len(_staff(db)) == 1

    def test_the_destination_keeps_its_own_internal_username(self, db):
        """Overwriting it with the source's would rename the row into a foreign
        scheme and re-open the mismatch on the next transfer."""
        from routes.data_transfer import _upsert_users
        existing_tables = set(sa_inspect(db.bind).get_table_names())

        _upsert_users(db, _incoming_from_the_other_database(), OWNER_ID, existing_tables)
        db.commit()

        row = _staff(db)[0]
        assert row.username == "counter_1__%d" % OWNER_ID
        assert row.staff_login_name == "counter_1"

    def test_a_genuinely_new_cashier_is_still_inserted(self, db):
        """The fix must not turn every import into a no-op."""
        from routes.data_transfer import _upsert_users
        existing_tables = set(sa_inspect(db.bind).get_table_names())

        rows = _incoming_from_the_other_database()
        rows[0] = dict(rows[0], username="counter_9_c7",
                       staff_login_name="counter_9", counter_prefix="C9")
        _upsert_users(db, rows, OWNER_ID, existing_tables)
        db.commit()

        names = {u.staff_login_name for u in _staff(db)}
        assert names == {"counter_1", "counter_9"}

    def test_it_matches_on_the_login_name_not_the_internal_one(self):
        import inspect
        from routes import data_transfer
        src = inspect.getsource(data_transfer._upsert_users)
        assert "lower(staff_login_name) = lower(:ln)" in src, (
            "staff are being matched on `username` again — that name is a "
            "per-database artefact and never matches across a transfer"
        )
        assert "parent_business_id = :bid" in src, (
            "the match must be scoped to the destination owner, or it can pull "
            "in another business's cashier of the same name"
        )


class TestTheSupersededCopyIsMarked:
    """`routes/migrate.py` is an older, unmounted copy of these endpoints whose
    `_upsert_users` still has the defect — and, on SQLite, an
    `INSERT OR REPLACE INTO users` that resolves on the PRIMARY KEY and would
    overwrite an unrelated local user outright."""

    def test_it_is_not_mounted(self):
        src = open(os.path.join(os.path.dirname(os.path.abspath(__file__)),
                                "..", "main_groq.py"), encoding="utf-8").read()
        assert "data_transfer_router" in src
        assert "routes.migrate" not in src

    def test_it_warns_against_being_revived_as_is(self):
        p = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..",
                         "routes", "migrate.py")
        head = open(p, encoding="utf-8").read()[:2500]
        assert "SUPERSEDED" in head and "DO NOT REVIVE AS-IS" in head
        assert "INSERT OR REPLACE" in head
