"""ft initial schema — every BizAssist Task table (all `ft_*`).

Additive only: creates new tables, never touches billing's. On Postgres it also
applies the same fail-closed tenant policy billing uses
(billing alembic 9c2f4b8a1d3e_fail_closed_rls_policies).

Revision ID: 0001_ft_initial
Revises: 
Create Date: 2026-10-22 15:29:41.820140
"""
from alembic import op
import sqlalchemy as sa


revision = '0001_ft_initial'
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table('ft_settings',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('business_id', sa.Integer(), nullable=False),
    sa.Column('device_policy', sa.String(), nullable=False),
    sa.Column('max_accuracy_m', sa.Integer(), nullable=False),
    sa.Column('geofence_radius_m', sa.Integer(), nullable=False),
    sa.Column('geofence_enforced', sa.Boolean(), nullable=False),
    sa.Column('ping_interval_s', sa.Integer(), nullable=False),
    sa.Column('workday_start', sa.String(), nullable=False),
    sa.Column('late_grace_min', sa.Integer(), nullable=False),
    sa.Column('default_task_points', sa.Integer(), nullable=False),
    sa.Column('late_points_pct', sa.Integer(), nullable=False),
    sa.Column('on_time_checkin_points', sa.Integer(), nullable=False),
    sa.Column('created_at', sa.DateTime(), nullable=False),
    sa.Column('updated_at', sa.DateTime(), nullable=False),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_ft_settings'))
    )
    with op.batch_alter_table('ft_settings', schema=None) as batch_op:
        batch_op.create_index(batch_op.f('ix_ft_settings_business_id'), ['business_id'], unique=True)

    op.create_table('ft_shops',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('uid', sa.String(length=36), nullable=False),
    sa.Column('business_id', sa.Integer(), nullable=False),
    sa.Column('name', sa.String(), nullable=False),
    sa.Column('contact_name', sa.String(), nullable=True),
    sa.Column('phone', sa.String(), nullable=True),
    sa.Column('address', sa.Text(), nullable=True),
    sa.Column('area', sa.String(), nullable=True),
    sa.Column('lat', sa.Float(), nullable=True),
    sa.Column('lng', sa.Float(), nullable=True),
    sa.Column('location_source', sa.String(), nullable=True),
    sa.Column('customer_id', sa.Integer(), nullable=True),
    sa.Column('notes', sa.Text(), nullable=True),
    sa.Column('is_active', sa.Boolean(), nullable=False),
    sa.Column('created_at', sa.DateTime(), nullable=False),
    sa.Column('updated_at', sa.DateTime(), nullable=False),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_ft_shops')),
    sa.UniqueConstraint('uid', name=op.f('uq_ft_shops_uid'))
    )
    with op.batch_alter_table('ft_shops', schema=None) as batch_op:
        batch_op.create_index(batch_op.f('ix_ft_shops_business_id'), ['business_id'], unique=False)
        batch_op.create_index('ix_ft_shops_business_name', ['business_id', 'name'], unique=False)
        batch_op.create_index(batch_op.f('ix_ft_shops_customer_id'), ['customer_id'], unique=False)

    op.create_table('ft_staff',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('uid', sa.String(length=36), nullable=False),
    sa.Column('business_id', sa.Integer(), nullable=False),
    sa.Column('name', sa.String(), nullable=False),
    sa.Column('login_name', sa.String(), nullable=False),
    sa.Column('phone', sa.String(), nullable=True),
    sa.Column('password_hash', sa.String(), nullable=False),
    sa.Column('role', sa.String(), nullable=False),
    sa.Column('is_active', sa.Boolean(), nullable=False),
    sa.Column('token_version', sa.Integer(), nullable=False),
    sa.Column('active_session_id', sa.String(), nullable=True),
    sa.Column('active_device_id', sa.String(), nullable=True),
    sa.Column('active_device_label', sa.String(), nullable=True),
    sa.Column('bound_device_id', sa.String(), nullable=True),
    sa.Column('bound_device_label', sa.String(), nullable=True),
    sa.Column('bound_at', sa.DateTime(), nullable=True),
    sa.Column('last_login', sa.DateTime(), nullable=True),
    sa.Column('last_seen_at', sa.DateTime(), nullable=True),
    sa.Column('last_lat', sa.Float(), nullable=True),
    sa.Column('last_lng', sa.Float(), nullable=True),
    sa.Column('last_accuracy_m', sa.Float(), nullable=True),
    sa.Column('created_at', sa.DateTime(), nullable=False),
    sa.Column('updated_at', sa.DateTime(), nullable=False),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_ft_staff')),
    sa.UniqueConstraint('business_id', 'login_name', name='uq_ft_staff_business_login'),
    sa.UniqueConstraint('uid', name=op.f('uq_ft_staff_uid'))
    )
    with op.batch_alter_table('ft_staff', schema=None) as batch_op:
        batch_op.create_index(batch_op.f('ix_ft_staff_business_id'), ['business_id'], unique=False)

    op.create_table('ft_activity',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('business_id', sa.Integer(), nullable=False),
    sa.Column('actor', sa.String(), nullable=False),
    sa.Column('staff_id', sa.Integer(), nullable=True),
    sa.Column('action', sa.String(), nullable=False),
    sa.Column('entity', sa.String(), nullable=True),
    sa.Column('entity_id', sa.Integer(), nullable=True),
    sa.Column('summary', sa.Text(), nullable=True),
    sa.Column('lat', sa.Float(), nullable=True),
    sa.Column('lng', sa.Float(), nullable=True),
    sa.Column('created_at', sa.DateTime(), nullable=False),
    sa.ForeignKeyConstraint(['staff_id'], ['ft_staff.id'], name=op.f('fk_ft_activity_staff_id_ft_staff'), ondelete='SET NULL'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_ft_activity'))
    )
    with op.batch_alter_table('ft_activity', schema=None) as batch_op:
        batch_op.create_index('ix_ft_activity_business_time', ['business_id', 'created_at'], unique=False)

    op.create_table('ft_attendance',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('business_id', sa.Integer(), nullable=False),
    sa.Column('staff_id', sa.Integer(), nullable=False),
    sa.Column('work_date', sa.String(), nullable=False),
    sa.Column('status', sa.String(), nullable=False),
    sa.Column('minutes_late', sa.Integer(), nullable=False),
    sa.Column('device_id', sa.String(), nullable=True),
    sa.Column('check_in_at', sa.DateTime(), nullable=False),
    sa.Column('check_in_lat', sa.Float(), nullable=False),
    sa.Column('check_in_lng', sa.Float(), nullable=False),
    sa.Column('check_in_accuracy_m', sa.Float(), nullable=True),
    sa.Column('check_in_client_at', sa.DateTime(), nullable=True),
    sa.Column('check_out_at', sa.DateTime(), nullable=True),
    sa.Column('check_out_lat', sa.Float(), nullable=True),
    sa.Column('check_out_lng', sa.Float(), nullable=True),
    sa.Column('check_out_accuracy_m', sa.Float(), nullable=True),
    sa.Column('check_out_client_at', sa.DateTime(), nullable=True),
    sa.Column('created_at', sa.DateTime(), nullable=False),
    sa.Column('updated_at', sa.DateTime(), nullable=False),
    sa.ForeignKeyConstraint(['staff_id'], ['ft_staff.id'], name=op.f('fk_ft_attendance_staff_id_ft_staff'), ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_ft_attendance')),
    sa.UniqueConstraint('staff_id', 'work_date', name='uq_ft_attendance_staff_date')
    )
    with op.batch_alter_table('ft_attendance', schema=None) as batch_op:
        batch_op.create_index('ix_ft_attendance_business_date', ['business_id', 'work_date'], unique=False)

    op.create_table('ft_location_pings',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('business_id', sa.Integer(), nullable=False),
    sa.Column('staff_id', sa.Integer(), nullable=False),
    sa.Column('recorded_at', sa.DateTime(), nullable=False),
    sa.Column('client_at', sa.DateTime(), nullable=True),
    sa.Column('lat', sa.Float(), nullable=False),
    sa.Column('lng', sa.Float(), nullable=False),
    sa.Column('accuracy_m', sa.Float(), nullable=True),
    sa.Column('speed_mps', sa.Float(), nullable=True),
    sa.Column('heading', sa.Float(), nullable=True),
    sa.Column('battery_pct', sa.Integer(), nullable=True),
    sa.Column('source', sa.String(), nullable=False),
    sa.Column('event', sa.String(), nullable=True),
    sa.ForeignKeyConstraint(['staff_id'], ['ft_staff.id'], name=op.f('fk_ft_location_pings_staff_id_ft_staff'), ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_ft_location_pings'))
    )
    with op.batch_alter_table('ft_location_pings', schema=None) as batch_op:
        batch_op.create_index('ix_ft_pings_business_staff_time', ['business_id', 'staff_id', 'recorded_at'], unique=False)
        batch_op.create_index('ix_ft_pings_recorded_at', ['recorded_at'], unique=False)

    op.create_table('ft_routes',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('uid', sa.String(length=36), nullable=False),
    sa.Column('business_id', sa.Integer(), nullable=False),
    sa.Column('name', sa.String(), nullable=False),
    sa.Column('description', sa.Text(), nullable=True),
    sa.Column('weekdays', sa.String(), nullable=True),
    sa.Column('default_staff_id', sa.Integer(), nullable=True),
    sa.Column('due_time', sa.String(), nullable=False),
    sa.Column('is_active', sa.Boolean(), nullable=False),
    sa.Column('created_at', sa.DateTime(), nullable=False),
    sa.Column('updated_at', sa.DateTime(), nullable=False),
    sa.ForeignKeyConstraint(['default_staff_id'], ['ft_staff.id'], name=op.f('fk_ft_routes_default_staff_id_ft_staff'), ondelete='SET NULL'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_ft_routes')),
    sa.UniqueConstraint('uid', name=op.f('uq_ft_routes_uid'))
    )
    with op.batch_alter_table('ft_routes', schema=None) as batch_op:
        batch_op.create_index(batch_op.f('ix_ft_routes_business_id'), ['business_id'], unique=False)

    op.create_table('ft_route_stops',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('business_id', sa.Integer(), nullable=False),
    sa.Column('route_id', sa.Integer(), nullable=False),
    sa.Column('shop_id', sa.Integer(), nullable=False),
    sa.Column('seq', sa.Integer(), nullable=False),
    sa.Column('created_at', sa.DateTime(), nullable=False),
    sa.Column('updated_at', sa.DateTime(), nullable=False),
    sa.ForeignKeyConstraint(['route_id'], ['ft_routes.id'], name=op.f('fk_ft_route_stops_route_id_ft_routes'), ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['shop_id'], ['ft_shops.id'], name=op.f('fk_ft_route_stops_shop_id_ft_shops'), ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_ft_route_stops'))
    )
    with op.batch_alter_table('ft_route_stops', schema=None) as batch_op:
        batch_op.create_index(batch_op.f('ix_ft_route_stops_business_id'), ['business_id'], unique=False)
        batch_op.create_index('ix_ft_route_stops_route_seq', ['route_id', 'seq'], unique=False)

    op.create_table('ft_runs',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('uid', sa.String(length=36), nullable=False),
    sa.Column('business_id', sa.Integer(), nullable=False),
    sa.Column('route_id', sa.Integer(), nullable=True),
    sa.Column('name', sa.String(), nullable=False),
    sa.Column('run_date', sa.String(), nullable=False),
    sa.Column('staff_id', sa.Integer(), nullable=True),
    sa.Column('status', sa.String(), nullable=False),
    sa.Column('started_at', sa.DateTime(), nullable=True),
    sa.Column('start_lat', sa.Float(), nullable=True),
    sa.Column('start_lng', sa.Float(), nullable=True),
    sa.Column('completed_at', sa.DateTime(), nullable=True),
    sa.Column('end_lat', sa.Float(), nullable=True),
    sa.Column('end_lng', sa.Float(), nullable=True),
    sa.Column('notes', sa.Text(), nullable=True),
    sa.Column('created_at', sa.DateTime(), nullable=False),
    sa.Column('updated_at', sa.DateTime(), nullable=False),
    sa.ForeignKeyConstraint(['route_id'], ['ft_routes.id'], name=op.f('fk_ft_runs_route_id_ft_routes'), ondelete='SET NULL'),
    sa.ForeignKeyConstraint(['staff_id'], ['ft_staff.id'], name=op.f('fk_ft_runs_staff_id_ft_staff'), ondelete='SET NULL'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_ft_runs')),
    sa.UniqueConstraint('uid', name=op.f('uq_ft_runs_uid'))
    )
    with op.batch_alter_table('ft_runs', schema=None) as batch_op:
        batch_op.create_index('ix_ft_runs_business_date', ['business_id', 'run_date'], unique=False)
        batch_op.create_index(batch_op.f('ix_ft_runs_staff_id'), ['staff_id'], unique=False)

    op.create_table('ft_run_stops',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('business_id', sa.Integer(), nullable=False),
    sa.Column('run_id', sa.Integer(), nullable=False),
    sa.Column('shop_id', sa.Integer(), nullable=False),
    sa.Column('seq', sa.Integer(), nullable=False),
    sa.Column('status', sa.String(), nullable=False),
    sa.Column('arrived_at', sa.DateTime(), nullable=True),
    sa.Column('arrived_lat', sa.Float(), nullable=True),
    sa.Column('arrived_lng', sa.Float(), nullable=True),
    sa.Column('arrived_accuracy_m', sa.Float(), nullable=True),
    sa.Column('arrival_distance_m', sa.Float(), nullable=True),
    sa.Column('outside_geofence', sa.Boolean(), nullable=False),
    sa.Column('done_at', sa.DateTime(), nullable=True),
    sa.Column('skip_reason', sa.Text(), nullable=True),
    sa.Column('created_at', sa.DateTime(), nullable=False),
    sa.Column('updated_at', sa.DateTime(), nullable=False),
    sa.ForeignKeyConstraint(['run_id'], ['ft_runs.id'], name=op.f('fk_ft_run_stops_run_id_ft_runs'), ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['shop_id'], ['ft_shops.id'], name=op.f('fk_ft_run_stops_shop_id_ft_shops'), ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_ft_run_stops'))
    )
    with op.batch_alter_table('ft_run_stops', schema=None) as batch_op:
        batch_op.create_index(batch_op.f('ix_ft_run_stops_business_id'), ['business_id'], unique=False)
        batch_op.create_index('ix_ft_run_stops_run_seq', ['run_id', 'seq'], unique=False)

    op.create_table('ft_item_requests',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('uid', sa.String(length=36), nullable=False),
    sa.Column('business_id', sa.Integer(), nullable=False),
    sa.Column('shop_id', sa.Integer(), nullable=False),
    sa.Column('staff_id', sa.Integer(), nullable=True),
    sa.Column('run_stop_id', sa.Integer(), nullable=True),
    sa.Column('kind', sa.String(), nullable=False),
    sa.Column('items_json', sa.Text(), nullable=False),
    sa.Column('note', sa.Text(), nullable=True),
    sa.Column('status', sa.String(), nullable=False),
    sa.Column('lat', sa.Float(), nullable=True),
    sa.Column('lng', sa.Float(), nullable=True),
    sa.Column('accuracy_m', sa.Float(), nullable=True),
    sa.Column('created_at', sa.DateTime(), nullable=False),
    sa.Column('updated_at', sa.DateTime(), nullable=False),
    sa.ForeignKeyConstraint(['run_stop_id'], ['ft_run_stops.id'], name=op.f('fk_ft_item_requests_run_stop_id_ft_run_stops'), ondelete='SET NULL'),
    sa.ForeignKeyConstraint(['shop_id'], ['ft_shops.id'], name=op.f('fk_ft_item_requests_shop_id_ft_shops'), ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['staff_id'], ['ft_staff.id'], name=op.f('fk_ft_item_requests_staff_id_ft_staff'), ondelete='SET NULL'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_ft_item_requests')),
    sa.UniqueConstraint('uid', name=op.f('uq_ft_item_requests_uid'))
    )
    with op.batch_alter_table('ft_item_requests', schema=None) as batch_op:
        batch_op.create_index('ix_ft_item_requests_business_status', ['business_id', 'status'], unique=False)

    op.create_table('ft_tasks',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('uid', sa.String(length=36), nullable=False),
    sa.Column('business_id', sa.Integer(), nullable=False),
    sa.Column('task_type', sa.String(), nullable=False),
    sa.Column('title', sa.String(), nullable=False),
    sa.Column('description', sa.Text(), nullable=True),
    sa.Column('staff_id', sa.Integer(), nullable=True),
    sa.Column('shop_id', sa.Integer(), nullable=True),
    sa.Column('run_id', sa.Integer(), nullable=True),
    sa.Column('run_stop_id', sa.Integer(), nullable=True),
    sa.Column('due_at', sa.DateTime(), nullable=True),
    sa.Column('points', sa.Integer(), nullable=False),
    sa.Column('status', sa.String(), nullable=False),
    sa.Column('boxes_planned', sa.Integer(), nullable=True),
    sa.Column('boxes_delivered', sa.Integer(), nullable=True),
    sa.Column('orders_count', sa.Integer(), nullable=True),
    sa.Column('reference', sa.String(), nullable=True),
    sa.Column('amount_expected', sa.Float(), nullable=True),
    sa.Column('amount_collected', sa.Float(), nullable=True),
    sa.Column('completed_at', sa.DateTime(), nullable=True),
    sa.Column('completed_lat', sa.Float(), nullable=True),
    sa.Column('completed_lng', sa.Float(), nullable=True),
    sa.Column('completed_accuracy_m', sa.Float(), nullable=True),
    sa.Column('completion_distance_m', sa.Float(), nullable=True),
    sa.Column('completion_note', sa.Text(), nullable=True),
    sa.Column('on_time', sa.Boolean(), nullable=True),
    sa.Column('points_awarded', sa.Integer(), nullable=False),
    sa.Column('created_by', sa.String(), nullable=True),
    sa.Column('created_at', sa.DateTime(), nullable=False),
    sa.Column('updated_at', sa.DateTime(), nullable=False),
    sa.ForeignKeyConstraint(['run_id'], ['ft_runs.id'], name=op.f('fk_ft_tasks_run_id_ft_runs'), ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['run_stop_id'], ['ft_run_stops.id'], name=op.f('fk_ft_tasks_run_stop_id_ft_run_stops'), ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['shop_id'], ['ft_shops.id'], name=op.f('fk_ft_tasks_shop_id_ft_shops'), ondelete='SET NULL'),
    sa.ForeignKeyConstraint(['staff_id'], ['ft_staff.id'], name=op.f('fk_ft_tasks_staff_id_ft_staff'), ondelete='SET NULL'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_ft_tasks')),
    sa.UniqueConstraint('uid', name=op.f('uq_ft_tasks_uid'))
    )
    with op.batch_alter_table('ft_tasks', schema=None) as batch_op:
        batch_op.create_index('ix_ft_tasks_business_due', ['business_id', 'due_at'], unique=False)
        batch_op.create_index('ix_ft_tasks_business_staff_status', ['business_id', 'staff_id', 'status'], unique=False)
        batch_op.create_index(batch_op.f('ix_ft_tasks_run_id'), ['run_id'], unique=False)
        batch_op.create_index(batch_op.f('ix_ft_tasks_run_stop_id'), ['run_stop_id'], unique=False)

    op.create_table('ft_points_ledger',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('business_id', sa.Integer(), nullable=False),
    sa.Column('staff_id', sa.Integer(), nullable=False),
    sa.Column('points', sa.Integer(), nullable=False),
    sa.Column('reason', sa.String(), nullable=False),
    sa.Column('task_id', sa.Integer(), nullable=True),
    sa.Column('attendance_id', sa.Integer(), nullable=True),
    sa.Column('work_date', sa.String(), nullable=False),
    sa.Column('note', sa.Text(), nullable=True),
    sa.Column('created_at', sa.DateTime(), nullable=False),
    sa.ForeignKeyConstraint(['attendance_id'], ['ft_attendance.id'], name=op.f('fk_ft_points_ledger_attendance_id_ft_attendance'), ondelete='SET NULL'),
    sa.ForeignKeyConstraint(['staff_id'], ['ft_staff.id'], name=op.f('fk_ft_points_ledger_staff_id_ft_staff'), ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['task_id'], ['ft_tasks.id'], name=op.f('fk_ft_points_ledger_task_id_ft_tasks'), ondelete='SET NULL'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_ft_points_ledger'))
    )
    with op.batch_alter_table('ft_points_ledger', schema=None) as batch_op:
        batch_op.create_index('ix_ft_points_business_staff', ['business_id', 'staff_id'], unique=False)

    _apply_rls()


BID = "nullif(current_setting('app.current_business_id', true), '')::integer"

FT_TABLES = [
    "ft_settings", "ft_staff", "ft_attendance", "ft_shops", "ft_routes", "ft_route_stops",
    "ft_runs", "ft_run_stops", "ft_tasks", "ft_item_requests", "ft_location_pings",
    "ft_points_ledger", "ft_activity",
]


def _apply_rls() -> None:
    if op.get_bind().dialect.name != "postgresql":
        return
    for table in FT_TABLES:
        op.execute(f"ALTER TABLE public.{table} ENABLE ROW LEVEL SECURITY;")
        op.execute(f"ALTER TABLE public.{table} FORCE ROW LEVEL SECURITY;")
        op.execute(f"DROP POLICY IF EXISTS {table}_tenant_isolation ON public.{table};")
        op.execute(f"""
            CREATE POLICY {table}_tenant_isolation ON public.{table}
            USING (business_id = {BID})
            WITH CHECK (business_id = {BID});
        """)


def downgrade() -> None:
    with op.batch_alter_table('ft_points_ledger', schema=None) as batch_op:
        batch_op.drop_index('ix_ft_points_business_staff')

    op.drop_table('ft_points_ledger')
    with op.batch_alter_table('ft_tasks', schema=None) as batch_op:
        batch_op.drop_index(batch_op.f('ix_ft_tasks_run_stop_id'))
        batch_op.drop_index(batch_op.f('ix_ft_tasks_run_id'))
        batch_op.drop_index('ix_ft_tasks_business_staff_status')
        batch_op.drop_index('ix_ft_tasks_business_due')

    op.drop_table('ft_tasks')
    with op.batch_alter_table('ft_item_requests', schema=None) as batch_op:
        batch_op.drop_index('ix_ft_item_requests_business_status')

    op.drop_table('ft_item_requests')
    with op.batch_alter_table('ft_run_stops', schema=None) as batch_op:
        batch_op.drop_index('ix_ft_run_stops_run_seq')
        batch_op.drop_index(batch_op.f('ix_ft_run_stops_business_id'))

    op.drop_table('ft_run_stops')
    with op.batch_alter_table('ft_runs', schema=None) as batch_op:
        batch_op.drop_index(batch_op.f('ix_ft_runs_staff_id'))
        batch_op.drop_index('ix_ft_runs_business_date')

    op.drop_table('ft_runs')
    with op.batch_alter_table('ft_route_stops', schema=None) as batch_op:
        batch_op.drop_index('ix_ft_route_stops_route_seq')
        batch_op.drop_index(batch_op.f('ix_ft_route_stops_business_id'))

    op.drop_table('ft_route_stops')
    with op.batch_alter_table('ft_routes', schema=None) as batch_op:
        batch_op.drop_index(batch_op.f('ix_ft_routes_business_id'))

    op.drop_table('ft_routes')
    with op.batch_alter_table('ft_location_pings', schema=None) as batch_op:
        batch_op.drop_index('ix_ft_pings_recorded_at')
        batch_op.drop_index('ix_ft_pings_business_staff_time')

    op.drop_table('ft_location_pings')
    with op.batch_alter_table('ft_attendance', schema=None) as batch_op:
        batch_op.drop_index('ix_ft_attendance_business_date')

    op.drop_table('ft_attendance')
    with op.batch_alter_table('ft_activity', schema=None) as batch_op:
        batch_op.drop_index('ix_ft_activity_business_time')

    op.drop_table('ft_activity')
    with op.batch_alter_table('ft_staff', schema=None) as batch_op:
        batch_op.drop_index(batch_op.f('ix_ft_staff_business_id'))

    op.drop_table('ft_staff')
    with op.batch_alter_table('ft_shops', schema=None) as batch_op:
        batch_op.drop_index(batch_op.f('ix_ft_shops_customer_id'))
        batch_op.drop_index('ix_ft_shops_business_name')
        batch_op.drop_index(batch_op.f('ix_ft_shops_business_id'))

    op.drop_table('ft_shops')
    with op.batch_alter_table('ft_settings', schema=None) as batch_op:
        batch_op.drop_index(batch_op.f('ix_ft_settings_business_id'))

    op.drop_table('ft_settings')
