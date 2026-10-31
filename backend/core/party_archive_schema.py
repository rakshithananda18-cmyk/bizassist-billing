"""Idempotent desktop/Alembic upgrade for retained B2B history."""
from sqlalchemy import inspect, text


def install_party_archive_schema(conn):
    from core.party_archive import DocumentPartySnapshot
    for table in ("b2b_connections", "b2b_orders"):
        if not inspect(conn).has_table(table):
            continue
        cols = {c["name"] for c in inspect(conn).get_columns(table)}
        additions = {"seller_snapshot": "TEXT", "buyer_snapshot": "TEXT",
                     "seller_deleted": "BOOLEAN NOT NULL DEFAULT false",
                     "buyer_deleted": "BOOLEAN NOT NULL DEFAULT false"}
        if table == "b2b_orders":
            additions.update(seller_invoice_uid="VARCHAR(36)", seller_invoice_number="VARCHAR")
        for name, datatype in additions.items():
            if name not in cols:
                conn.execute(text(f'ALTER TABLE "{table}" ADD COLUMN "{name}" {datatype}'))
    table = "b2b_order_line_items"
    if inspect(conn).has_table(table):
        column = next(c for c in inspect(conn).get_columns(table) if c["name"] == "product_id")
        if not column["nullable"]:
            if conn.dialect.name == "postgresql":
                conn.execute(text('ALTER TABLE b2b_order_line_items ALTER COLUMN product_id DROP NOT NULL'))
            else:
                from alembic.migration import MigrationContext
                from alembic.operations import Operations
                # This table has no inbound FKs. Preserve IDs, indexes and all
                # snapshots while SQLite rebuilds its NOT NULL declaration.
                with Operations(MigrationContext.configure(conn)).batch_alter_table(table) as batch:
                    batch.alter_column("product_id", nullable=True)
    DocumentPartySnapshot.__table__.create(conn, checkfirst=True)
    owner_fk = next((fk for fk in inspect(conn).get_foreign_keys("document_party_snapshots")
                     if fk["constrained_columns"] == ["business_id"]), None)
    if owner_fk and owner_fk.get("options", {}).get("ondelete", "").upper() != "CASCADE":
        if conn.dialect.name == "postgresql":
            # Constraint identifiers come from database metadata, not requests.
            name = owner_fk["name"].replace('"', '""')
            conn.execute(text(f'ALTER TABLE document_party_snapshots DROP CONSTRAINT "{name}"'))
            conn.execute(text('ALTER TABLE document_party_snapshots ADD CONSTRAINT fk_party_snapshot_owner '
                              'FOREIGN KEY (business_id) REFERENCES users(id) ON DELETE CASCADE'))
        else:
            from alembic.migration import MigrationContext
            from alembic.operations import Operations
            naming = {"fk": "fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s"}
            with Operations(MigrationContext.configure(conn)).batch_alter_table("document_party_snapshots", naming_convention=naming) as batch:
                batch.drop_constraint(owner_fk["name"] or "fk_document_party_snapshots_business_id_users", type_="foreignkey")
                batch.create_foreign_key("fk_party_snapshot_owner", "users", ["business_id"], ["id"], ondelete="CASCADE")
    if conn.dialect.name == "postgresql":
        conn.execute(text('ALTER TABLE document_party_snapshots ENABLE ROW LEVEL SECURITY'))
        conn.execute(text('ALTER TABLE document_party_snapshots FORCE ROW LEVEL SECURITY'))
        conn.execute(text('DROP POLICY IF EXISTS party_snapshot_tenant ON document_party_snapshots'))
        conn.execute(text("CREATE POLICY party_snapshot_tenant ON document_party_snapshots USING "
            "(business_id = NULLIF(current_setting('app.current_business_id',true),'')::integer) "
            "WITH CHECK (business_id = NULLIF(current_setting('app.current_business_id',true),'')::integer)"))
