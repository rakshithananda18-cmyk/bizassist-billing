"""Regression checks for migration cost and error classification."""
import os
os.environ.setdefault("DATABASE_URL", "sqlite:///./test_bizassist.db")
os.environ.setdefault("GROQ_API_KEY", "mock_groq_api_key")
os.environ.setdefault("CLOUD_API_URL", "http://127.0.0.1:9")
from sqlalchemy import create_engine, event, text


def test_seed_has_no_per_row_existence_select():
    from database.change_feed import install_change_feed
    engine = create_engine("sqlite:///:memory:")
    with engine.begin() as conn:
        conn.execute(text("CREATE TABLE customers(id INTEGER PRIMARY KEY,uid TEXT,business_id INTEGER,name TEXT)"))
        conn.execute(text("INSERT INTO customers VALUES(:id,:uid,1,'test')"), [{"id":i,"uid":f"u{i}"} for i in range(1,20)])
        statements = []
        event.listen(engine, "before_cursor_execute", lambda c,cur,sql,p,ctx,many: statements.append(sql))
        install_change_feed(conn)
        install_change_feed(conn)
        assert not any("SELECT 1 FROM sync_feed_events" in sql for sql in statements)
        assert conn.execute(text("SELECT count(*) FROM sync_feed_events")).scalar() == 19


def test_error_code_comes_from_driver_not_message():
    from database.change_feed import _sqlstate
    class DriverError(Exception):
        pgcode = "40P01"
    class Wrapped(Exception):
        orig = DriverError()
    assert _sqlstate(Wrapped()) == "40P01"
    assert _sqlstate(RuntimeError("transaction block")) is None


def test_schema_signature_stable_and_build_sensitive(monkeypatch):
    from database.migration import compute_schema_signature
    from sqlalchemy.dialects.postgresql import dialect
    monkeypatch.setenv("BIZASSIST_BUILD_ID", "a")
    first = compute_schema_signature(dialect())
    assert first == compute_schema_signature(dialect())
    monkeypatch.setenv("BIZASSIST_BUILD_ID", "b")
    assert first != compute_schema_signature(dialect())
