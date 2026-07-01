"""rename_tables_phase_3

Revision ID: ac832002b0db
Revises: 04f94642987a
Create Date: 2026-07-01 23:45:28.539179
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy import inspect


# revision identifiers, used by Alembic.
revision = 'ac832002b0db'
down_revision = '04f94642987a'
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = inspect(bind)
    tables = inspector.get_table_names()

    # Drop the empty new tables if they were auto-created by create_all
    if 'b2b_invite_codes' in tables:
        op.drop_table('b2b_invite_codes')
    if 'b2b_ledgers' in tables:
        op.drop_table('b2b_ledgers')
    if 'action_logs' in tables:
        op.drop_table('action_logs')
    if 'ai_feedback' in tables:
        op.drop_table('ai_feedback')
    if 'ai_query_overrides' in tables:
        op.drop_table('ai_query_overrides')

    # Rename tables (both SQLite and Postgres)
    op.rename_table('connection_codes', 'b2b_invite_codes')
    op.rename_table('shared_ledgers', 'b2b_ledgers')
    op.rename_table('action_log', 'action_logs')
    op.rename_table('feedback', 'ai_feedback')
    op.rename_table('query_override', 'ai_query_overrides')

    # Postgres specific renames (indexes, constraints, policies)
    is_postgres = bind.dialect.name == 'postgresql'
    if is_postgres:
        safe_execute = """
        DO $$
        BEGIN
            -- 1. b2b_invite_codes
            BEGIN ALTER INDEX ix_connection_codes_code RENAME TO ix_b2b_invite_codes_code; EXCEPTION WHEN OTHERS THEN END;
            BEGIN ALTER INDEX ix_connection_codes_id RENAME TO ix_b2b_invite_codes_id; EXCEPTION WHEN OTHERS THEN END;
            BEGIN ALTER INDEX ix_connection_codes_seller_code RENAME TO ix_b2b_invite_codes_seller_code; EXCEPTION WHEN OTHERS THEN END;
            BEGIN ALTER TABLE b2b_invite_codes RENAME CONSTRAINT pk_connection_codes TO pk_b2b_invite_codes; EXCEPTION WHEN OTHERS THEN END;
            BEGIN ALTER TABLE b2b_invite_codes RENAME CONSTRAINT fk_connection_codes_seller_business_id_users TO fk_b2b_invite_codes_seller_business_id_users; EXCEPTION WHEN OTHERS THEN END;
            BEGIN ALTER POLICY connection_codes_tenant_isolation ON b2b_invite_codes RENAME TO b2b_invite_codes_tenant_isolation; EXCEPTION WHEN OTHERS THEN END;

            -- 2. b2b_ledgers
            BEGIN ALTER INDEX ix_shared_ledgers_id RENAME TO ix_b2b_ledgers_id; EXCEPTION WHEN OTHERS THEN END;
            BEGIN ALTER INDEX ix_shared_ledgers_seller_buyer RENAME TO ix_b2b_ledgers_seller_buyer; EXCEPTION WHEN OTHERS THEN END;
            BEGIN ALTER TABLE b2b_ledgers RENAME CONSTRAINT pk_shared_ledgers TO pk_b2b_ledgers; EXCEPTION WHEN OTHERS THEN END;
            BEGIN ALTER TABLE b2b_ledgers RENAME CONSTRAINT fk_shared_ledgers_buyer_business_id_users TO fk_b2b_ledgers_buyer_business_id_users; EXCEPTION WHEN OTHERS THEN END;
            BEGIN ALTER TABLE b2b_ledgers RENAME CONSTRAINT fk_shared_ledgers_seller_business_id_users TO fk_b2b_ledgers_seller_business_id_users; EXCEPTION WHEN OTHERS THEN END;
            BEGIN ALTER POLICY shared_ledgers_tenant_isolation ON b2b_ledgers RENAME TO b2b_ledgers_tenant_isolation; EXCEPTION WHEN OTHERS THEN END;

            -- 3. action_logs
            BEGIN ALTER INDEX ix_action_log_id RENAME TO ix_action_logs_id; EXCEPTION WHEN OTHERS THEN END;
            BEGIN ALTER INDEX ix_action_log_reference_id RENAME TO ix_action_logs_reference_id; EXCEPTION WHEN OTHERS THEN END;
            BEGIN ALTER TABLE action_logs RENAME CONSTRAINT pk_action_log TO pk_action_logs; EXCEPTION WHEN OTHERS THEN END;
            BEGIN ALTER TABLE action_logs RENAME CONSTRAINT fk_action_log_business_id_users TO fk_action_logs_business_id_users; EXCEPTION WHEN OTHERS THEN END;
            BEGIN ALTER POLICY action_log_tenant_isolation ON action_logs RENAME TO action_logs_tenant_isolation; EXCEPTION WHEN OTHERS THEN END;

            -- 4. ai_feedback
            BEGIN ALTER INDEX ix_feedback_id RENAME TO ix_ai_feedback_id; EXCEPTION WHEN OTHERS THEN END;
            BEGIN ALTER TABLE ai_feedback RENAME CONSTRAINT pk_feedback TO pk_ai_feedback; EXCEPTION WHEN OTHERS THEN END;
            BEGIN ALTER TABLE ai_feedback RENAME CONSTRAINT fk_feedback_business_id_users TO fk_ai_feedback_business_id_users; EXCEPTION WHEN OTHERS THEN END;
            BEGIN ALTER POLICY feedback_tenant_isolation ON ai_feedback RENAME TO ai_feedback_tenant_isolation; EXCEPTION WHEN OTHERS THEN END;

            -- 5. ai_query_overrides
            BEGIN ALTER INDEX ix_query_override_id RENAME TO ix_ai_query_overrides_id; EXCEPTION WHEN OTHERS THEN END;
            BEGIN ALTER TABLE ai_query_overrides RENAME CONSTRAINT pk_query_override TO pk_ai_query_overrides; EXCEPTION WHEN OTHERS THEN END;
            BEGIN ALTER TABLE ai_query_overrides RENAME CONSTRAINT fk_query_override_business_id_users TO fk_ai_query_overrides_business_id_users; EXCEPTION WHEN OTHERS THEN END;
            BEGIN ALTER POLICY query_override_tenant_isolation ON ai_query_overrides RENAME TO ai_query_overrides_tenant_isolation; EXCEPTION WHEN OTHERS THEN END;
        END $$;
        """
        op.execute(safe_execute)


def downgrade() -> None:
    # Rename tables back
    op.rename_table('b2b_invite_codes', 'connection_codes')
    op.rename_table('b2b_ledgers', 'shared_ledgers')
    op.rename_table('action_logs', 'action_log')
    op.rename_table('ai_feedback', 'feedback')
    op.rename_table('ai_query_overrides', 'query_override')

    bind = op.get_bind()
    is_postgres = bind.dialect.name == 'postgresql'
    if is_postgres:
        # 1. connection_codes
        op.execute("ALTER INDEX ix_b2b_invite_codes_code RENAME TO ix_connection_codes_code")
        op.execute("ALTER INDEX ix_b2b_invite_codes_id RENAME TO ix_connection_codes_id")
        op.execute("ALTER INDEX ix_b2b_invite_codes_seller_code RENAME TO ix_connection_codes_seller_code")
        op.execute("ALTER TABLE connection_codes RENAME CONSTRAINT pk_b2b_invite_codes TO pk_connection_codes")
        op.execute("ALTER TABLE connection_codes RENAME CONSTRAINT fk_b2b_invite_codes_seller_business_id_users TO fk_connection_codes_seller_business_id_users")
        op.execute("ALTER POLICY b2b_invite_codes_tenant_isolation ON connection_codes RENAME TO connection_codes_tenant_isolation")

        # 2. shared_ledgers
        op.execute("ALTER INDEX ix_b2b_ledgers_id RENAME TO ix_shared_ledgers_id")
        op.execute("ALTER INDEX ix_b2b_ledgers_seller_buyer RENAME TO ix_shared_ledgers_seller_buyer")
        op.execute("ALTER TABLE shared_ledgers RENAME CONSTRAINT pk_b2b_ledgers TO pk_shared_ledgers")
        op.execute("ALTER TABLE shared_ledgers RENAME CONSTRAINT fk_b2b_ledgers_buyer_business_id_users TO fk_shared_ledgers_buyer_business_id_users")
        op.execute("ALTER TABLE shared_ledgers RENAME CONSTRAINT fk_b2b_ledgers_seller_business_id_users TO fk_shared_ledgers_seller_business_id_users")
        op.execute("ALTER POLICY b2b_ledgers_tenant_isolation ON shared_ledgers RENAME TO shared_ledgers_tenant_isolation")

        # 3. action_log
        op.execute("ALTER INDEX ix_action_logs_business_id RENAME TO ix_action_log_business_id")
        op.execute("ALTER INDEX ix_action_logs_id RENAME TO ix_action_log_id")
        op.execute("ALTER TABLE action_log RENAME CONSTRAINT pk_action_logs TO pk_action_log")

        # 4. feedback
        op.execute("ALTER INDEX ix_ai_feedback_id RENAME TO ix_feedback_id")
        op.execute("ALTER TABLE feedback RENAME CONSTRAINT pk_ai_feedback TO pk_feedback")

        # 5. query_override
        op.execute("ALTER INDEX ix_ai_query_overrides_id RENAME TO ix_query_override_id")
        op.execute("ALTER TABLE query_override RENAME CONSTRAINT pk_ai_query_overrides TO pk_query_override")
        op.execute("ALTER TABLE query_override RENAME CONSTRAINT uq_ai_query_overrides_biz_query TO uq_query_override_biz_query")
