"""
app/geo.py — location is mandatory for every field action.
==========================================================
Every staff write (check-in/out, start route, arrive at shop, complete a task,
log a shop's request) carries a `GeoFix`. The server refuses the action when:

  * the fix is missing                       → 422 (pydantic, field required)
  * coordinates are out of range / (0, 0)    → 422
  * accuracy is worse than the business's `max_accuracy_m` → 422 with a
    message the agent can act on ("move to open sky and retry")

What the browser CANNOT tell us: whether the phone is faking its location
(Android "mock location" apps). Detecting that needs a native app; see
docs/MASTER_PLAN.md §Location. What we do instead: keep the reported accuracy,
the distance from the shop's pin, and the server timestamp on every row, so an
impossible trail is visible to the owner.
"""
from __future__ import annotations

import math
from typing import Optional

from fastapi import HTTPException
from pydantic import BaseModel, Field

EARTH_RADIUS_M = 6_371_008.8


class GeoFix(BaseModel):
    lat: float = Field(..., ge=-90, le=90)
    lng: float = Field(..., ge=-180, le=180)
    accuracy: Optional[float] = Field(None, ge=0, description="metres, from the browser")
    client_time: Optional[str] = Field(None, description="phone clock, ISO 8601 (evidence only)")
    speed: Optional[float] = None
    heading: Optional[float] = None
    battery: Optional[int] = Field(None, ge=0, le=100)


def validate_fix(fix: GeoFix, max_accuracy_m: int) -> GeoFix:
    if abs(fix.lat) < 1e-6 and abs(fix.lng) < 1e-6:
        # (0, 0) is what a failed/blocked GPS read serialises to on some devices.
        raise HTTPException(status_code=422, detail="Location unavailable. Turn on GPS and retry.")
    if fix.accuracy is None:
        raise HTTPException(status_code=422, detail="Location accuracy missing. Turn on precise location and retry.")
    if fix.accuracy > max_accuracy_m:
        raise HTTPException(
            status_code=422,
            detail=(
                f"Location too imprecise (±{int(fix.accuracy)} m, limit ±{max_accuracy_m} m). "
                "Turn on precise location, move to open sky and retry."
            ),
        )
    return fix


def haversine_m(lat1: float, lng1: float, lat2: float, lng2: float) -> float:
    """Great-circle distance in metres."""
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp = p2 - p1
    dl = math.radians(lng2 - lng1)
    a = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * EARTH_RADIUS_M * math.asin(math.sqrt(a))


def distance_to(lat: float | None, lng: float | None, fix: GeoFix) -> float | None:
    if lat is None or lng is None:
        return None
    return round(haversine_m(lat, lng, fix.lat, fix.lng), 1)
