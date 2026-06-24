"""enable_rls_and_restrict_api

Revision ID: aea3a6d76429
Revises: f4a1c7e9b2d6
Create Date: 2026-06-24 21:42:16.938027
"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = 'aea3a6d76429'
down_revision = 'f4a1c7e9b2d6'
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name == "postgresql":
        # 1. Enable Row-Level Security (RLS) on all tables in the public schema (excluding alembic_version)
        op.execute("""
            DO $$
            DECLARE
                r RECORD;
            BEGIN
                FOR r IN 
                    SELECT tablename 
                    FROM pg_tables 
                    WHERE schemaname = 'public' AND tablename != 'alembic_version'
                LOOP
                    EXECUTE format('ALTER TABLE public.%I ENABLE ROW LEVEL SECURITY;', r.tablename);
                END LOOP;
            END $$;
        """)

        # 2. Revoke all privileges (SELECT, INSERT, UPDATE, DELETE, etc.) from public API roles
        op.execute("REVOKE ALL ON ALL TABLES IN SCHEMA public FROM public, anon, authenticated;")
        op.execute("REVOKE ALL ON ALL SEQUENCES IN SCHEMA public FROM public, anon, authenticated;")
        op.execute("REVOKE ALL ON ALL FUNCTIONS IN SCHEMA public FROM public, anon, authenticated;")

        # 3. Alter default privileges so future tables/sequences/functions don't automatically grant public API access
        op.execute("ALTER DEFAULT PRIVILEGES IN SCHEMA public REVOKE ALL ON TABLES FROM public, anon, authenticated;")
        op.execute("ALTER DEFAULT PRIVILEGES IN SCHEMA public REVOKE ALL ON SEQUENCES FROM public, anon, authenticated;")
        op.execute("ALTER DEFAULT PRIVILEGES IN SCHEMA public REVOKE ALL ON FUNCTIONS FROM public, anon, authenticated;")


def downgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name == "postgresql":
        # 1. Disable RLS on all tables in the public schema (excluding alembic_version)
        op.execute("""
            DO $$
            DECLARE
                r RECORD;
            BEGIN
                FOR r IN 
                    SELECT tablename 
                    FROM pg_tables 
                    WHERE schemaname = 'public' AND tablename != 'alembic_version'
                LOOP
                    EXECUTE format('ALTER TABLE public.%I DISABLE ROW LEVEL SECURITY;', r.tablename);
                END LOOP;
            END $$;
        """)

        # 2. Restore default privileges to standard roles
        op.execute("GRANT ALL ON ALL TABLES IN SCHEMA public TO postgres, anon, authenticated, service_role;")
        op.execute("GRANT ALL ON ALL SEQUENCES IN SCHEMA public TO postgres, anon, authenticated, service_role;")
        op.execute("GRANT ALL ON ALL FUNCTIONS IN SCHEMA public TO postgres, anon, authenticated, service_role;")

        # 3. Reset default privileges
        op.execute("ALTER DEFAULT PRIVILEGES IN SCHEMA public GRANT ALL ON TABLES TO postgres, anon, authenticated, service_role;")
        op.execute("ALTER DEFAULT PRIVILEGES IN SCHEMA public GRANT ALL ON SEQUENCES TO postgres, anon, authenticated, service_role;")
        op.execute("ALTER DEFAULT PRIVILEGES IN SCHEMA public GRANT ALL ON FUNCTIONS TO postgres, anon, authenticated, service_role;")

