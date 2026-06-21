"""add parent_business_id to users (staff sub-accounts)

Adds a nullable self-referential pointer on `users`: NULL for an owner (the row
IS the business), or the owner's id for a staff (cashier) login. Additive and
nullable — safe online migration, no backfill needed.

Revision ID: c5e1a9d4f7b2
Revises: 4e78be85db86
Create Date: 2026-06-20
"""
from alembic import op
import sqlalchemy as sa

revision = 'c5e1a9d4f7b2'
down_revision = '4e78be85db86'
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table('users') as batch:
        batch.add_column(sa.Column('parent_business_id', sa.Integer(), nullable=True))
        batch.create_index('ix_users_parent_business_id', ['parent_business_id'])


def downgrade():
    with op.batch_alter_table('users') as batch:
        batch.drop_index('ix_users_parent_business_id')
        batch.drop_column('parent_business_id')
