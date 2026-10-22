"""
app/models.py — the field-team tables (all `ft_*`).
===================================================
Tenant key: `business_id` = the owner's `users.id` in the shared cloud database,
the same integer every billing cloud table is scoped by. It comes from the
verified token only, never from a request body (billing FOUNDATION §2.1).

Shape of a working day:

    FieldShop ──< FieldRouteStop >── FieldRoute          (owner's templates)
                                         │ planned for a date
                                         ▼
    FieldRun (route × date × staff) ──< FieldRunStop (one visit per shop)
                                                 │
                                                 └──< FieldTask (delivery,
                                                      return pickup, payment
                                                      collection, order taking…)

Points are append-only (`FieldPointsEntry`) — a correction is a new negative
row, never an UPDATE — the same discipline billing applies to money and stock.
"""
from __future__ import annotations

import uuid

from sqlalchemy import (
    Boolean, Column, DateTime, Float, ForeignKey, Index, Integer, String, Text,
    UniqueConstraint,
)
from sqlalchemy.orm import relationship

from app.db import Base, utc_now


def _uid() -> str:
    return str(uuid.uuid4())


class TimestampMixin:
    created_at = Column(DateTime, default=utc_now, nullable=False)
    updated_at = Column(DateTime, default=utc_now, onupdate=utc_now, nullable=False)


class FieldSettings(Base, TimestampMixin):
    """One row per business. Created lazily with defaults on first read."""
    __tablename__ = "ft_settings"

    id = Column(Integer, primary_key=True)
    business_id = Column(Integer, nullable=False, unique=True, index=True)
    # single_session — a new login signs the previous device out.
    # bound          — the account is locked to the first device it signs in on;
    #                  only the owner can release it. Also single-session.
    device_policy = Column(String, nullable=False, default="single_session")
    # A GPS fix worse than this is refused for every field action.
    max_accuracy_m = Column(Integer, nullable=False, default=150)
    # Arrival farther than this from the shop's pin is flagged (or refused when
    # geofence_enforced).
    geofence_radius_m = Column(Integer, nullable=False, default=200)
    geofence_enforced = Column(Boolean, nullable=False, default=False)
    # How often the open app sends a background ping.
    ping_interval_s = Column(Integer, nullable=False, default=60)
    # Attendance: check-in after workday_start + late_grace_min is "late".
    workday_start = Column(String, nullable=False, default="09:30")  # HH:MM business time
    late_grace_min = Column(Integer, nullable=False, default=15)
    # Gamification. A task's own `points` are earned when done by its due time;
    # done late earns `late_points_pct` % of them (rounded down).
    default_task_points = Column(Integer, nullable=False, default=10)
    late_points_pct = Column(Integer, nullable=False, default=0)
    on_time_checkin_points = Column(Integer, nullable=False, default=5)


class FieldStaff(Base, TimestampMixin):
    """A delivery agent / field worker.

    Deliberately NOT a billing `users` row. Billing's role guard is a deny-list
    (`restrict_cashier` blocks only "cashier" and "supply adder"), so a `users`
    row with any new role would be treated as OWNER by every billing endpoint.
    Field staff live here and their tokens are signed with a key billing cannot
    verify (app/security.py) — they can never reach billing data.
    """
    __tablename__ = "ft_staff"
    __table_args__ = (
        UniqueConstraint("business_id", "login_name", name="uq_ft_staff_business_login"),
    )

    id = Column(Integer, primary_key=True)
    uid = Column(String(36), nullable=False, default=_uid, unique=True)
    business_id = Column(Integer, nullable=False, index=True)
    name = Column(String, nullable=False)
    login_name = Column(String, nullable=False)  # lower-cased, unique per business
    phone = Column(String, nullable=True)
    password_hash = Column(String, nullable=False)
    role = Column(String, nullable=False, default="delivery")  # delivery | field | supervisor
    is_active = Column(Boolean, nullable=False, default=True)
    # Session control. Every token carries `tv` and `sid`; both must match.
    token_version = Column(Integer, nullable=False, default=0)
    active_session_id = Column(String, nullable=True)
    active_device_id = Column(String, nullable=True)
    active_device_label = Column(String, nullable=True)
    # Device binding (device_policy == "bound").
    bound_device_id = Column(String, nullable=True)
    bound_device_label = Column(String, nullable=True)
    bound_at = Column(DateTime, nullable=True)
    last_login = Column(DateTime, nullable=True)
    last_seen_at = Column(DateTime, nullable=True)
    last_lat = Column(Float, nullable=True)
    last_lng = Column(Float, nullable=True)
    last_accuracy_m = Column(Float, nullable=True)


class FieldAttendance(Base, TimestampMixin):
    """One row per staff per business-day. Times are SERVER time (UTC); the
    phone's clock is stored only as evidence (`*_client_at`)."""
    __tablename__ = "ft_attendance"
    __table_args__ = (
        UniqueConstraint("staff_id", "work_date", name="uq_ft_attendance_staff_date"),
        Index("ix_ft_attendance_business_date", "business_id", "work_date"),
    )

    id = Column(Integer, primary_key=True)
    business_id = Column(Integer, nullable=False)
    staff_id = Column(Integer, ForeignKey("ft_staff.id", ondelete="CASCADE"), nullable=False)
    work_date = Column(String, nullable=False)  # YYYY-MM-DD in business timezone
    status = Column(String, nullable=False, default="present")  # present | late
    minutes_late = Column(Integer, nullable=False, default=0)
    device_id = Column(String, nullable=True)
    check_in_at = Column(DateTime, nullable=False)
    check_in_lat = Column(Float, nullable=False)
    check_in_lng = Column(Float, nullable=False)
    check_in_accuracy_m = Column(Float, nullable=True)
    check_in_client_at = Column(DateTime, nullable=True)
    check_out_at = Column(DateTime, nullable=True)
    check_out_lat = Column(Float, nullable=True)
    check_out_lng = Column(Float, nullable=True)
    check_out_accuracy_m = Column(Float, nullable=True)
    check_out_client_at = Column(DateTime, nullable=True)

    staff = relationship("FieldStaff", lazy="joined")


class FieldShop(Base, TimestampMixin):
    """A delivery point — for a distributor, a retail/medical shop."""
    __tablename__ = "ft_shops"
    __table_args__ = (Index("ix_ft_shops_business_name", "business_id", "name"),)

    id = Column(Integer, primary_key=True)
    uid = Column(String(36), nullable=False, default=_uid, unique=True)
    business_id = Column(Integer, nullable=False, index=True)
    name = Column(String, nullable=False)
    contact_name = Column(String, nullable=True)
    phone = Column(String, nullable=True)
    address = Column(Text, nullable=True)
    area = Column(String, nullable=True)
    lat = Column(Float, nullable=True)
    lng = Column(Float, nullable=True)
    # owner (typed/picked) | staff (pinned on first visit)
    location_source = Column(String, nullable=True)
    # Link to billing `customers.id` (same business). Lets a shop's deliveries,
    # requests and — later — B2B orders line up with its billing ledger.
    customer_id = Column(Integer, nullable=True, index=True)
    notes = Column(Text, nullable=True)
    is_active = Column(Boolean, nullable=False, default=True)


class FieldRoute(Base, TimestampMixin):
    """A reusable beat/route: an ordered list of shops, run on given weekdays."""
    __tablename__ = "ft_routes"

    id = Column(Integer, primary_key=True)
    uid = Column(String(36), nullable=False, default=_uid, unique=True)
    business_id = Column(Integer, nullable=False, index=True)
    name = Column(String, nullable=False)
    description = Column(Text, nullable=True)
    # Comma-separated ISO weekdays, Monday=1 … Sunday=7. Empty = any day.
    weekdays = Column(String, nullable=True)
    default_staff_id = Column(Integer, ForeignKey("ft_staff.id", ondelete="SET NULL"), nullable=True)
    due_time = Column(String, nullable=False, default="18:00")  # HH:MM — deliveries due by
    is_active = Column(Boolean, nullable=False, default=True)

    stops = relationship(
        "FieldRouteStop", order_by="FieldRouteStop.seq",
        cascade="all, delete-orphan", lazy="selectin",
    )


class FieldRouteStop(Base, TimestampMixin):
    __tablename__ = "ft_route_stops"
    __table_args__ = (Index("ix_ft_route_stops_route_seq", "route_id", "seq"),)

    id = Column(Integer, primary_key=True)
    business_id = Column(Integer, nullable=False, index=True)
    route_id = Column(Integer, ForeignKey("ft_routes.id", ondelete="CASCADE"), nullable=False)
    shop_id = Column(Integer, ForeignKey("ft_shops.id", ondelete="CASCADE"), nullable=False)
    seq = Column(Integer, nullable=False, default=0)

    shop = relationship("FieldShop", lazy="joined")


class FieldRun(Base, TimestampMixin):
    """One route, on one calendar day, assigned to one person."""
    __tablename__ = "ft_runs"
    __table_args__ = (Index("ix_ft_runs_business_date", "business_id", "run_date"),)

    id = Column(Integer, primary_key=True)
    uid = Column(String(36), nullable=False, default=_uid, unique=True)
    business_id = Column(Integer, nullable=False)
    route_id = Column(Integer, ForeignKey("ft_routes.id", ondelete="SET NULL"), nullable=True)
    name = Column(String, nullable=False)  # snapshot of the route name
    run_date = Column(String, nullable=False)  # YYYY-MM-DD business date
    staff_id = Column(Integer, ForeignKey("ft_staff.id", ondelete="SET NULL"), nullable=True, index=True)
    status = Column(String, nullable=False, default="planned")  # planned | in_progress | completed | cancelled
    started_at = Column(DateTime, nullable=True)
    start_lat = Column(Float, nullable=True)
    start_lng = Column(Float, nullable=True)
    completed_at = Column(DateTime, nullable=True)
    end_lat = Column(Float, nullable=True)
    end_lng = Column(Float, nullable=True)
    notes = Column(Text, nullable=True)

    staff = relationship("FieldStaff", lazy="joined")
    stops = relationship(
        "FieldRunStop", order_by="FieldRunStop.seq",
        cascade="all, delete-orphan", lazy="selectin",
    )


class FieldRunStop(Base, TimestampMixin):
    """A planned visit to one shop within a run."""
    __tablename__ = "ft_run_stops"
    __table_args__ = (Index("ix_ft_run_stops_run_seq", "run_id", "seq"),)

    id = Column(Integer, primary_key=True)
    business_id = Column(Integer, nullable=False, index=True)
    run_id = Column(Integer, ForeignKey("ft_runs.id", ondelete="CASCADE"), nullable=False)
    shop_id = Column(Integer, ForeignKey("ft_shops.id", ondelete="CASCADE"), nullable=False)
    seq = Column(Integer, nullable=False, default=0)
    status = Column(String, nullable=False, default="pending")  # pending | arrived | done | skipped
    arrived_at = Column(DateTime, nullable=True)
    arrived_lat = Column(Float, nullable=True)
    arrived_lng = Column(Float, nullable=True)
    arrived_accuracy_m = Column(Float, nullable=True)
    # Metres between the arrival fix and the shop pin; NULL when the shop has no pin.
    arrival_distance_m = Column(Float, nullable=True)
    outside_geofence = Column(Boolean, nullable=False, default=False)
    done_at = Column(DateTime, nullable=True)
    skip_reason = Column(Text, nullable=True)

    shop = relationship("FieldShop", lazy="joined")
    tasks = relationship("FieldTask", order_by="FieldTask.id", lazy="selectin", viewonly=True)


TASK_TYPES = (
    "delivery",         # drop boxes / orders at the shop
    "return_pickup",    # collect returns / expired stock
    "payment_collect",  # collect a due amount
    "order_taking",     # note the shop's next order
    "stock_check",      # check shelf / expiry at the shop
    "general",
)


class FieldTask(Base, TimestampMixin):
    """The unit of work and of points. Owner assigns; staff performs on site."""
    __tablename__ = "ft_tasks"
    __table_args__ = (
        Index("ix_ft_tasks_business_staff_status", "business_id", "staff_id", "status"),
        Index("ix_ft_tasks_business_due", "business_id", "due_at"),
    )

    id = Column(Integer, primary_key=True)
    uid = Column(String(36), nullable=False, default=_uid, unique=True)
    business_id = Column(Integer, nullable=False)
    task_type = Column(String, nullable=False, default="general")
    title = Column(String, nullable=False)
    description = Column(Text, nullable=True)
    staff_id = Column(Integer, ForeignKey("ft_staff.id", ondelete="SET NULL"), nullable=True)
    shop_id = Column(Integer, ForeignKey("ft_shops.id", ondelete="SET NULL"), nullable=True)
    run_id = Column(Integer, ForeignKey("ft_runs.id", ondelete="CASCADE"), nullable=True, index=True)
    run_stop_id = Column(Integer, ForeignKey("ft_run_stops.id", ondelete="CASCADE"), nullable=True, index=True)
    due_at = Column(DateTime, nullable=True)  # UTC
    points = Column(Integer, nullable=False, default=10)
    status = Column(String, nullable=False, default="pending")  # pending | done | cancelled
    # Delivery specifics (NULL for other task types).
    boxes_planned = Column(Integer, nullable=True)
    boxes_delivered = Column(Integer, nullable=True)
    orders_count = Column(Integer, nullable=True)  # orders sent for delivery to this shop
    reference = Column(String, nullable=True)  # invoice / order numbers, free text
    amount_expected = Column(Float, nullable=True)  # payment_collect
    amount_collected = Column(Float, nullable=True)
    # Completion evidence.
    completed_at = Column(DateTime, nullable=True)
    completed_lat = Column(Float, nullable=True)
    completed_lng = Column(Float, nullable=True)
    completed_accuracy_m = Column(Float, nullable=True)
    completion_distance_m = Column(Float, nullable=True)
    completion_note = Column(Text, nullable=True)
    on_time = Column(Boolean, nullable=True)
    points_awarded = Column(Integer, nullable=False, default=0)
    created_by = Column(String, nullable=True)  # "owner:<user_id>"

    staff = relationship("FieldStaff", lazy="joined")
    shop = relationship("FieldShop", lazy="joined")


class FieldItemRequest(Base, TimestampMixin):
    """What a shop asked for — an order note or a product requirement list.
    Manual today; later converted into a billing B2B order / sale draft."""
    __tablename__ = "ft_item_requests"
    __table_args__ = (Index("ix_ft_item_requests_business_status", "business_id", "status"),)

    id = Column(Integer, primary_key=True)
    uid = Column(String(36), nullable=False, default=_uid, unique=True)
    business_id = Column(Integer, nullable=False)
    shop_id = Column(Integer, ForeignKey("ft_shops.id", ondelete="CASCADE"), nullable=False)
    staff_id = Column(Integer, ForeignKey("ft_staff.id", ondelete="SET NULL"), nullable=True)
    run_stop_id = Column(Integer, ForeignKey("ft_run_stops.id", ondelete="SET NULL"), nullable=True)
    kind = Column(String, nullable=False, default="requirement")  # requirement | order
    items_json = Column(Text, nullable=False, default="[]")  # [{name, qty, unit, note}]
    note = Column(Text, nullable=True)
    status = Column(String, nullable=False, default="new")  # new | acknowledged | fulfilled | closed
    lat = Column(Float, nullable=True)
    lng = Column(Float, nullable=True)
    accuracy_m = Column(Float, nullable=True)

    shop = relationship("FieldShop", lazy="joined")
    staff = relationship("FieldStaff", lazy="joined")


class FieldLocationPing(Base):
    """Raw GPS trail. Append-only; purged after TASK_PING_RETENTION_DAYS."""
    __tablename__ = "ft_location_pings"
    __table_args__ = (
        Index("ix_ft_pings_business_staff_time", "business_id", "staff_id", "recorded_at"),
        Index("ix_ft_pings_recorded_at", "recorded_at"),
    )

    id = Column(Integer, primary_key=True)
    business_id = Column(Integer, nullable=False)
    staff_id = Column(Integer, ForeignKey("ft_staff.id", ondelete="CASCADE"), nullable=False)
    recorded_at = Column(DateTime, nullable=False, default=utc_now)  # server time
    client_at = Column(DateTime, nullable=True)
    lat = Column(Float, nullable=False)
    lng = Column(Float, nullable=False)
    accuracy_m = Column(Float, nullable=True)
    speed_mps = Column(Float, nullable=True)
    heading = Column(Float, nullable=True)
    battery_pct = Column(Integer, nullable=True)
    source = Column(String, nullable=False, default="watch")  # watch | event
    event = Column(String, nullable=True)  # check_in | arrive | task_done | …


class FieldPointsEntry(Base):
    """Append-only points ledger — the scorecard is SUM(points)."""
    __tablename__ = "ft_points_ledger"
    __table_args__ = (Index("ix_ft_points_business_staff", "business_id", "staff_id"),)

    id = Column(Integer, primary_key=True)
    business_id = Column(Integer, nullable=False)
    staff_id = Column(Integer, ForeignKey("ft_staff.id", ondelete="CASCADE"), nullable=False)
    points = Column(Integer, nullable=False)
    reason = Column(String, nullable=False)  # task_on_time | task_late | checkin_on_time | adjustment
    task_id = Column(Integer, ForeignKey("ft_tasks.id", ondelete="SET NULL"), nullable=True)
    attendance_id = Column(Integer, ForeignKey("ft_attendance.id", ondelete="SET NULL"), nullable=True)
    work_date = Column(String, nullable=False)  # business date the points belong to
    note = Column(Text, nullable=True)
    created_at = Column(DateTime, nullable=False, default=utc_now)


class FieldActivity(Base):
    """Human-readable audit trail of every field action (who, what, where, when)."""
    __tablename__ = "ft_activity"
    __table_args__ = (Index("ix_ft_activity_business_time", "business_id", "created_at"),)

    id = Column(Integer, primary_key=True)
    business_id = Column(Integer, nullable=False)
    actor = Column(String, nullable=False)  # "owner:<id>" | "staff:<id>"
    staff_id = Column(Integer, ForeignKey("ft_staff.id", ondelete="SET NULL"), nullable=True)
    action = Column(String, nullable=False)
    entity = Column(String, nullable=True)
    entity_id = Column(Integer, nullable=True)
    summary = Column(Text, nullable=True)
    lat = Column(Float, nullable=True)
    lng = Column(Float, nullable=True)
    created_at = Column(DateTime, nullable=False, default=utc_now)
