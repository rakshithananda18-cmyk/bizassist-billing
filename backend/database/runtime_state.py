"""Durable deployment and scheduled-work state, excluded from business sync."""
from sqlalchemy import Column, String, DateTime, Text, Integer, Float
from database.db import Base


class SchemaState(Base):
    __tablename__ = "schema_state"
    key = Column(String(100), primary_key=True)
    signature = Column(String(64), nullable=False)
    applied_at = Column(DateTime(timezone=True), nullable=False)
    applied_by = Column(String(200))


class ScheduledJobRun(Base):
    __tablename__ = "scheduled_job_runs"
    job = Column(String(100), primary_key=True)
    period = Column(String(20), primary_key=True)
    status = Column(String(20), nullable=False)
    cursor = Column(Integer)
    lease_until = Column(DateTime)
    started_at = Column(DateTime)
    finished_at = Column(DateTime)
    error = Column(Text)


class DiscoveryRegistration(Base):
    __tablename__ = "discovery_registrations"
    biz_id = Column(String(100), primary_key=True)
    ip = Column(String(100), primary_key=True)
    port = Column(Integer, primary_key=True)
    url = Column(String(300), nullable=False)
    registered_at = Column(Float, nullable=False)
    last_seen = Column(Float, nullable=False, index=True)
