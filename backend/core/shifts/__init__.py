"""
core/shifts — Shift & Cash-Drawer Management (plan Phase 3).
============================================================
Service layer: open/close register shifts and compute drawer tallies.
Routes stay thin (routes/shifts.py); money math stays deterministic here.
"""
from core.shifts.service import (   # noqa: F401
    get_open_shift,
    open_shift,
    close_shift,
    compute_tally,
    require_open_shift,
)
