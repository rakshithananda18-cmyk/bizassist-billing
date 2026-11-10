"""Upgrade a populated predecessor schema, including SQLite table rebuilding."""
from sqlalchemy import create_engine, inspect, text


def test_existing_schema_upgrade_preserves_order_lines_and_is_idempotent(tmp_path):
    from core.party_archive_schema import install_party_archive_schema
    engine = create_engine("sqlite:///" + (tmp_path / "test_legacy.db").as_posix())
    with engine.begin() as conn:
        for ddl in (
            "CREATE TABLE users(id INTEGER PRIMARY KEY)",
            "CREATE TABLE products(id INTEGER PRIMARY KEY)",
            "CREATE TABLE b2b_connections(id INTEGER PRIMARY KEY, seller_business_id INTEGER, buyer_business_id INTEGER)",
            "CREATE TABLE b2b_orders(id INTEGER PRIMARY KEY, seller_business_id INTEGER, buyer_business_id INTEGER)",
            "CREATE TABLE b2b_order_line_items(id INTEGER PRIMARY KEY, order_id INTEGER NOT NULL REFERENCES b2b_orders(id), product_id INTEGER NOT NULL REFERENCES products(id), product_name TEXT, quantity REAL, line_total REAL)",
            "INSERT INTO users VALUES(1)", "INSERT INTO products VALUES(9)",
            "INSERT INTO b2b_orders VALUES(7,1,2)",
            "INSERT INTO b2b_order_line_items VALUES(11,7,9,'Historical item',3,45)",
        ):
            conn.execute(text(ddl))
        install_party_archive_schema(conn)
        install_party_archive_schema(conn)
        assert next(c for c in inspect(conn).get_columns("b2b_order_line_items") if c["name"] == "product_id")["nullable"]
        assert conn.execute(text("SELECT id,order_id,product_id,product_name,quantity,line_total FROM b2b_order_line_items")).one() == (11, 7, 9, "Historical item", 3, 45)
        assert {"seller_snapshot", "buyer_snapshot", "seller_deleted", "buyer_deleted", "seller_invoice_uid", "seller_invoice_number"} <= {c["name"] for c in inspect(conn).get_columns("b2b_orders")}
        assert inspect(conn).has_table("document_party_snapshots")
        conn.execute(text("UPDATE b2b_order_line_items SET product_id=NULL WHERE id=11"))
        assert conn.execute(text("SELECT COUNT(*) FROM b2b_order_line_items WHERE product_id IS NULL")).scalar() == 1
    engine.dispose()
