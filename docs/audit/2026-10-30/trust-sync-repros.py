"""Offline reproductions using selected current functions, never app imports/DBs.

All databases are SQLite :memory:. AST extraction removes FastAPI decorators and
dependency defaults only; function bodies are from the working tree unchanged.
"""
from __future__ import annotations

import ast
import json
import logging
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace
from typing import Optional

from sqlalchemy import Column, DateTime, Integer, String, create_engine, func
from sqlalchemy.orm import Session, declarative_base

ROOT = Path(__file__).resolve().parents[3]
logging.disable(logging.CRITICAL)


def extracted(path, name, ns):
    tree = ast.parse((ROOT / path).read_text(encoding="utf-8"))
    fn = next(x for x in tree.body if isinstance(x, ast.FunctionDef) and x.name == name)
    fn.decorator_list = []
    fn.args.defaults = [ast.Constant(None) for _ in fn.args.defaults]
    fn.returns = None
    for arg in fn.args.posonlyargs + fn.args.args + fn.args.kwonlyargs:
        arg.annotation = None
    mod = ast.fix_missing_locations(ast.Module(body=[fn], type_ignores=[]))
    exec(compile(mod, str(path), "exec"), ns)
    return ns[name]


Base = declarative_base()


class Row(Base):
    __tablename__ = "customers"
    id = Column(Integer, primary_key=True)
    business_id = Column(Integer)
    updated_at = Column(DateTime)
    name = Column(String)


class User(Base):
    __tablename__ = "users"
    id = Column(Integer, primary_key=True)
    public_id = Column(String)
    parent_business_id = Column(Integer)
    staff_login_name = Column(String)
    username = Column(String)
    password = Column(String)
    role = Column(String)
    counter_prefix = Column(String)
    token_version = Column(Integer, default=0)


def pull_setup(db, serializer=None):
    ns = dict(
        datetime=datetime, timezone=timezone, Optional=Optional,
        _MODEL_MAP={"customers": Row}, TWO_SIDED_OWNER_COLUMNS={},
        _parse_dt=lambda value: datetime.fromisoformat(value) if value else None,
        _serialize_orm_obj=serializer or (lambda row, _db: {"id": row.id, "updated_at": row.updated_at.isoformat()}),
        _resolve_business_id_by_username=lambda *_a, **_kw: 1,
        logger=logging.getLogger("audit"),
    )
    return extracted("backend/routes/sync.py", "pull_changes", ns)


def main():
    eng = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(eng)
    db = Session(eng)
    stamp = datetime(2026, 10, 29, 10, 0, 0)
    db.add_all([Row(id=i, business_id=1, updated_at=stamp, name=str(i)) for i in (1, 2, 3)])
    db.commit()
    pull = pull_setup(db)
    page1 = pull(last_sync_at=None, limit=2, current_user={}, db=db)
    watermark = max(r["updated_at"] for r in page1["changes"]["customers"])
    page2 = pull(last_sync_at=watermark, limit=2, current_user={}, db=db)
    pagination = {"page1_ids": [r["id"] for r in page1["changes"]["customers"]],
                  "has_more": page1["has_more"], "page2_changes": page2["changes"],
                  "never_delivered_id": 3}
    assert pagination["has_more"] and not page2["changes"]

    # A write after the table SELECT but before response-end pulled_at has a
    # timestamp below that cursor and is absent on the next incremental pull.
    def serialize_and_commit_later(row, _db):
        result = {"id": row.id, "updated_at": row.updated_at.isoformat()}
        if row.id == 1:
            _db.add(Row(id=4, business_id=1, updated_at=datetime.now(timezone.utc).replace(tzinfo=None), name="late"))
            _db.commit()
        return result
    first = pull_setup(db, serialize_and_commit_later)(last_sync_at=None, limit=None, current_user={}, db=db)
    second = pull(last_sync_at=first["pulled_at"], limit=None, current_user={}, db=db)
    race = {"first_ids": [r["id"] for r in first["changes"]["customers"]],
            "next_changes": second["changes"], "never_delivered_id": 4}
    assert 4 not in race["first_ids"] and not second["changes"]

    # Extract the actual cursor decision branch from the worker, preserving
    # body and branch ordering. Only external effects are recorded as a list.
    sw = ast.parse((ROOT / "backend/services/sync_worker.py").read_text(encoding="utf-8"))
    decision = next(n for n in ast.walk(sw) if isinstance(n, ast.If)
                    and isinstance(n.test, ast.Name) and n.test.id == "_cloud_cursor"
                    and any(isinstance(x, ast.Name) and x.id == "_pull_row_failures" for x in ast.walk(n)))
    advances = []
    ns = dict(_cloud_cursor="2026-10-30T10:05:00", _pull_row_failures=[{"row": 5}],
              _pull_failed_tables=[{"table": "invoices"}], business_id=1, db=db,
              _PULL_FAILED_STREAK={}, logger=logging.getLogger("audit"),
              _set_pull_cursor=lambda *_a: advances.append(_a[-1]))
    exec(compile(ast.fix_missing_locations(ast.Module(body=[decision], type_ignores=[])), "worker-decision", "exec"), ns)
    assert advances

    # Run the actual existing-staff replication body and verify it changes
    # password/role but leaves the token revocation generation unchanged.
    db.add_all([User(id=10, public_id="BIZ-A", username="owner", role="enterprise"),
                User(id=11, parent_business_id=10, staff_login_name="counter", username="counter__10",
                     password="old", role="supply adder", token_version=0)])
    db.commit()
    ns = dict(User=User, func=func, logger=logging.getLogger("audit"),
              resolve_business_id_in_db=lambda *_a, **_kw: 10,
              HTTPException=RuntimeError)
    sync_staff = extracted("backend/routes/sync_staff.py", "sync_staff_push", ns)
    req = SimpleNamespace(staff=[SimpleNamespace(staff_login_name="counter", internal_username="counter__10",
                           hashed_password="new", role="cashier", counter_prefix="C1", deleted=False)])
    sync_staff(req=req, current_user={"public_id": "BIZ-A"}, db=db)
    staff = db.get(User, 11)
    staff_result = {"new_password": staff.password, "new_role": staff.role,
                    "token_version_after": staff.token_version,
                    "old_cloud_tv_claim_still_matches": staff.token_version == 0}
    assert staff.password == "new" and staff.role == "cashier" and staff.token_version == 0

    results = {"timestamp_boundary_data_loss": pagination, "response_end_cursor_race": race,
               "partial_pull_plus_rejected_row_advances": advances,
               "staff_replication_missing_revocation": staff_result}
    print(json.dumps(results, indent=2))
    db.close()


if __name__ == "__main__":
    main()
