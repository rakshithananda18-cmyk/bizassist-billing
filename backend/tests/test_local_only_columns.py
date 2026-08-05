"""
tests/test_local_only_columns.py
================================
An integer id is meaningful ONLY inside the database that issued it. That rule
is enforced hard for the BizID spine; `file_id` was quietly breaking it.

`invoices.file_id` / `inventory.file_id` point at `uploaded_files.id`. That table
is not synced and has no `uid`, and the column is a plain Integer rather than a
declared ForeignKey — so `_serialize_orm_obj`'s uid resolution never saw it and
the LOCAL value was pushed verbatim.

Both databases number their uploads independently from small integers for the
same business, so the copied value does not merely become meaningless upstream:
it COLLIDES with a real, unrelated upload. `DELETE /upload/{file_id}` purges rows
by exactly this column, so deleting an upload on the cloud could purge inventory
that arrived from a different device's import.
"""
import json
import os
import sys
import uuid

os.environ.setdefault("DATABASE_URL", "sqlite:///./test_bizassist.db")
os.environ.setdefault("GROQ_API_KEY", "mock_groq_api_key")

backend_path = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, backend_path)

from fastapi.testclient import TestClient          # noqa: E402
from sqlalchemy import text                         # noqa: E402
from main_groq import app                           # noqa: E402
from database.db import SessionLocal                # noqa: E402
from database.models import Inventory, UploadedFile  # noqa: E402

client = TestClient(app)


def test_file_id_never_leaves_the_database_that_issued_it():
    uname = f"loc_{uuid.uuid4().hex[:8]}"
    r = client.post("/signup", json={
        "username": uname, "password": "TestPass123!", "business_name": "Local Col Co",
    })
    assert r.status_code == 200, r.text
    acct = r.json()
    bid = acct["user"]["id"] if isinstance(acct.get("user"), dict) else acct["id"]

    db = SessionLocal()
    try:
        db.execute(text("UPDATE users SET settings = :s WHERE id = :b"), {
            "s": json.dumps({"general": {"hosting_mode": "hybrid"}}), "b": bid,
        })
        db.commit()

        up = UploadedFile(business_id=bid, filename="stock.csv", file_type="inventory")
        db.add(up)
        db.commit()
        db.refresh(up)
        local_file_id = up.id

        db.execute(text("DELETE FROM sync_queue WHERE business_id = :b"), {"b": bid})
        db.commit()

        item = Inventory(business_id=bid, file_id=local_file_id,
                         product_name="Widget", stock=5.0)
        db.add(item)
        db.commit()

        row = db.execute(text(
            "SELECT payload FROM sync_queue WHERE business_id = :b AND entity = 'inventory' "
            "AND operation = 'INSERT' ORDER BY id DESC LIMIT 1"
        ), {"b": bid}).fetchone()
        assert row and row[0], "the inventory INSERT should have been queued"

        payload = json.loads(row[0])
        assert "product_name" in payload, "sanity: the payload really is this row"
        assert "file_id" not in payload, (
            f"a LOCAL uploaded_files id ({local_file_id}) is being pushed to the "
            "other database, where that integer belongs to a different upload"
        )
    finally:
        db.close()
