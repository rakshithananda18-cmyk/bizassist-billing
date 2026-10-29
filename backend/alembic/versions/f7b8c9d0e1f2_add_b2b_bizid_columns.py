"""Add seller_bizid and buyer_bizid to b2b_orders and b2b_connections.

Revision ID: f7b8c9d0e1f2
Revises: e0a1b2c3d4e5
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.sql import text

revision = "f7b8c9d0e1f2"
down_revision = "e0a1b2c3d4e5"
branch_labels = None
depends_on = None


def upgrade():
    bind = op.get_bind()
    insp = sa.inspect(bind)

    # 1. b2b_connections
    if insp.has_table("b2b_connections"):
        conn_cols = {c["name"] for c in insp.get_columns("b2b_connections")}
        if "seller_bizid" not in conn_cols:
            op.add_column("b2b_connections", sa.Column("seller_bizid", sa.String(length=16), nullable=True))
            try:
                op.create_index("ix_b2b_connections_seller_bizid", "b2b_connections", ["seller_bizid"])
            except Exception:
                pass
        if "buyer_bizid" not in conn_cols:
            op.add_column("b2b_connections", sa.Column("buyer_bizid", sa.String(length=16), nullable=True))
            try:
                op.create_index("ix_b2b_connections_buyer_bizid", "b2b_connections", ["buyer_bizid"])
            except Exception:
                pass

    # 2. b2b_orders
    if insp.has_table("b2b_orders"):
        order_cols = {c["name"] for c in insp.get_columns("b2b_orders")}
        if "seller_bizid" not in order_cols:
            op.add_column("b2b_orders", sa.Column("seller_bizid", sa.String(length=16), nullable=True))
            try:
                op.create_index("ix_b2b_orders_seller_bizid", "b2b_orders", ["seller_bizid"])
            except Exception:
                pass
        if "buyer_bizid" not in order_cols:
            op.add_column("b2b_orders", sa.Column("buyer_bizid", sa.String(length=16), nullable=True))
            try:
                op.create_index("ix_b2b_orders_buyer_bizid", "b2b_orders", ["buyer_bizid"])
            except Exception:
                pass

    # 3. Backfill from users.public_id
    try:
        bind.execute(text("""
            UPDATE b2b_connections
            SET seller_bizid = (SELECT public_id FROM users WHERE users.id = b2b_connections.seller_business_id)
            WHERE (seller_bizid IS NULL OR seller_bizid = '') AND seller_business_id IS NOT NULL;
        """))
        bind.execute(text("""
            UPDATE b2b_connections
            SET buyer_bizid = (SELECT public_id FROM users WHERE users.id = b2b_connections.buyer_business_id)
            WHERE (buyer_bizid IS NULL OR buyer_bizid = '') AND buyer_business_id IS NOT NULL;
        """))
        bind.execute(text("""
            UPDATE b2b_orders
            SET seller_bizid = (SELECT public_id FROM users WHERE users.id = b2b_orders.seller_business_id)
            WHERE (seller_bizid IS NULL OR seller_bizid = '') AND seller_business_id IS NOT NULL;
        """))
        bind.execute(text("""
            UPDATE b2b_orders
            SET buyer_bizid = (SELECT public_id FROM users WHERE users.id = b2b_orders.buyer_business_id)
            WHERE (buyer_bizid IS NULL OR buyer_bizid = '') AND buyer_business_id IS NOT NULL;
        """))
    except Exception:
        pass


def downgrade():
    try:
        op.drop_index("ix_b2b_orders_buyer_bizid", table_name="b2b_orders")
    except Exception:
        pass
    try:
        op.drop_index("ix_b2b_orders_seller_bizid", table_name="b2b_orders")
    except Exception:
        pass
    try:
        op.drop_column("b2b_orders", "buyer_bizid")
    except Exception:
        pass
    try:
        op.drop_column("b2b_orders", "seller_bizid")
    except Exception:
        pass
    try:
        op.drop_index("ix_b2b_connections_buyer_bizid", table_name="b2b_connections")
    except Exception:
        pass
    try:
        op.drop_index("ix_b2b_connections_seller_bizid", table_name="b2b_connections")
    except Exception:
        pass
    try:
        op.drop_column("b2b_connections", "buyer_bizid")
    except Exception:
        pass
    try:
        op.drop_column("b2b_connections", "seller_bizid")
    except Exception:
        pass
