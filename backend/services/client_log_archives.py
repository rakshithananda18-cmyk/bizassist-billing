"""Durable bounded support archives; callers bind tenant identity on uploads."""
from sqlalchemy import func, text
from database.models import ClientLogArchive
from services.dates import utc_now

_ARCHIVES_PER_BUSINESS = 5
_ARCHIVE_TOTAL_BYTES = 200 * 1024 * 1024


def store_archive(db, *, business_id, filename, content, feedback_id=None, kind="feedback"):
    if db.bind.dialect.name == "postgresql":
        # Serialize the small retention transaction so two concurrent uploads
        # cannot each leave a sixth archive or exceed the platform byte cap.
        db.execute(text("SELECT pg_advisory_xact_lock(18065102)"))
    archive = ClientLogArchive(business_id=business_id, feedback_id=feedback_id, kind=kind, filename=filename, content=content, size=len(content), created_at=utc_now())
    db.add(archive)
    db.flush()
    # Admin-owned retention is intentionally platform-wide. Upload owners can
    # remove only their own rows under a constrained runtime's RLS boundary.
    stale = db.query(ClientLogArchive).filter(ClientLogArchive.business_id == business_id).order_by(ClientLogArchive.created_at.desc(), ClientLogArchive.id.desc()).offset(_ARCHIVES_PER_BUSINESS).all()
    for row in stale:
        db.delete(row)
    db.flush()
    total = db.query(func.coalesce(func.sum(ClientLogArchive.size),0)).scalar()
    while total > _ARCHIVE_TOTAL_BYTES:
        oldest = db.query(ClientLogArchive).order_by(ClientLogArchive.created_at,ClientLogArchive.id).first()
        if oldest is None:
            break
        total -= oldest.size
        db.delete(oldest)
        db.flush()
    return archive
