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
        # Bare PostgreSQL does not define Supabase's anon/authenticated roles.
        # Revoke PUBLIC unconditionally and any provider API roles that exist;
        # never create extra login identities merely to replay the schema.
        roles = ['PUBLIC']
        for name in ('anon', 'authenticated'):
            if bind.execute(sa.text('SELECT 1 FROM pg_roles WHERE rolname=:name'), {'name': name}).first():
                roles.append(bind.dialect.identifier_preparer.quote(name))
        grantees = ', '.join(roles)
        for kind in ('TABLES', 'SEQUENCES', 'FUNCTIONS'):
            op.execute(f'REVOKE ALL ON ALL {kind} IN SCHEMA public FROM {grantees}')
            # 3. New objects retain the same closed provider API boundary.
            op.execute(f'ALTER DEFAULT PRIVILEGES IN SCHEMA public REVOKE ALL ON {kind} FROM {grantees}')


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

