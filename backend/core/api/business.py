"""
core/api/business.py — Business Template System HTTP layer (Phase 1B).
=====================================================================
Thin routes over core.templates. They authenticate, scope to the caller's
business, and read/write `business_settings`. No business logic here — the
template resolution + override validation live in core.templates.loader.

Lives under core/api/ (the billing ecosystem's HTTP layer) and is wired into
the app via core.api.core_router — the app entry point never imports it
directly. Conventions per backend/FOUNDATION.md.

  GET   /business/templates   list {key,label} for the signup picker (public-ish)
  POST  /business/setup       choose/switch the vertical for this business
  GET   /business/config      the RESOLVED config for the logged-in business
  PATCH /business/config      owner overrides (deep-merged, guardrailed)
"""
import json
import logging
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session

from database.db import get_db
from core.models import BusinessSettings
from services.auth import get_active_user, restrict_cashier
from core import templates as T

router = APIRouter()
logger = logging.getLogger("bizassist.core.api.business")


# ── Schemas ──────────────────────────────────────────────────────────────────

class SetupRequest(BaseModel):
    template_key: Optional[str] = None
    # Multi-type business (plan Phase 2): ordered list, first = primary.
    # `template_key` alone still works (single-type, fully backward-compatible).
    template_keys: Optional[list] = None


class ConfigPatch(BaseModel):
    overrides: dict


def _get_or_create_settings(db: Session, business_id: int) -> BusinessSettings:
    row = (
        db.query(BusinessSettings)
        .filter(BusinessSettings.business_id == business_id)
        .first()
    )
    if row is None:
        row = BusinessSettings(business_id=business_id, template_key=T.FALLBACK_KEY, overrides=None)
        db.add(row)
        db.flush()
    return row


# ── Routes ───────────────────────────────────────────────────────────────────

@router.get("/business/templates")
def list_templates():
    """All available verticals for the signup business-type picker."""
    return {"templates": list(T.list_templates())}


@router.post("/business/setup")
def setup_business(req: SetupRequest,
                   current_user: dict = Depends(restrict_cashier),
                   db: Session = Depends(get_db)):
    """
    Choose (or switch) the vertical(s) for this business. Accepts either a single
    `template_key` (legacy, unchanged) or an ordered `template_keys` list whose
    first entry is the primary (plan Phase 2 multi-type). Unknown keys fall back
    to `general`. Switching the PRIMARY clears prior overrides (they were keyed
    to the old vertical's schema). Returns the resolved config.
    """
    bid = current_user["id"]

    # Normalise the request into an ordered, deduped, known-key list.
    requested = req.template_keys if req.template_keys else [req.template_key]
    keys, seen = [], set()
    for k in requested:
        norm = T.get_template(k)["key"]               # normalises unknown → general
        if norm not in seen:
            seen.add(norm)
            keys.append(norm)
    if not keys:
        raise HTTPException(status_code=422, detail="at least one business type is required")
    primary = keys[0]

    row = _get_or_create_settings(db, bid)
    if row.template_key != primary:
        row.overrides = None                          # reset overrides on primary change
    row.template_key = primary
    row.business_types = json.dumps(keys)
    db.commit()
    logger.info("[BUSINESS] biz=%s template set to '%s' (types=%s)", bid, primary, keys)
    return {"template_key": primary, "business_types": keys,
            "config": T.resolve_for(bid, db)}


@router.get("/business/billing-profile")
def get_billing_profile(mode: Optional[str] = None,
                        current_user: dict = Depends(get_active_user),
                        db: Session = Depends(get_db)):
    """
    The RESOLVED billing-counter profile (plan Phase 2): entry mode, customer
    gating, line fields, counter widgets, payment modes, and the invoice-template
    default — for the business's primary vertical, or `?mode=<key>` for any of
    its other registered business types (the counter mode switcher).
    """
    bid = current_user["id"]
    profile = T.resolve_billing_profile(bid, db, mode_key=mode)
    return {"profile": profile}


@router.get("/business/config")
def get_config(current_user: dict = Depends(get_active_user),
               db: Session = Depends(get_db)):
    """The RESOLVED config (template ⊕ overrides) for the logged-in business —
    the frontend's source of truth for labels, fields, and defaults."""
    bid = current_user["id"]
    cfg = T.resolve_for(bid, db)
    return {"config": cfg, "attributes_schema": T.attributes_schema(cfg["key"])}


@router.patch("/business/config")
def patch_config(req: ConfigPatch,
                 current_user: dict = Depends(restrict_cashier),
                 db: Session = Depends(get_db)):
    """
    Apply owner overrides (e.g. turn batch tracking off, rename a label). The
    override is validated against the template guardrails (presentation/defaults
    only) and stored; the resolved config is returned. 422 on an invalid override.
    """
    bid = current_user["id"]
    row = _get_or_create_settings(db, bid)

    # Merge the new overrides over any existing ones, then validate the result.
    existing = {}
    if row.overrides:
        try:
            existing = json.loads(row.overrides)
        except (ValueError, TypeError):
            existing = {}
    merged = {**existing, **req.overrides}

    try:
        resolved = T.validate_overrides(row.template_key, merged)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc))

    row.overrides = json.dumps(merged)
    db.commit()
    logger.info("[BUSINESS] biz=%s overrides updated (keys=%s)", bid, sorted(req.overrides.keys()))
    return {"template_key": row.template_key, "config": resolved}
