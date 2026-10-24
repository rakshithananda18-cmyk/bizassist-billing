"""Small, deliberately strict helpers for server-side PDF rendering.

WeasyPrint resolves URLs while rendering HTML.  Invoice fields are merchant
controlled, so passing a logo URL through to the renderer would turn PDF
generation into a server-side request primitive.  Keep invoice logos inline
and raster-only; a missing/legacy remote logo is safer than an internal fetch.
"""

from __future__ import annotations

import base64
import binascii
import re
from typing import Optional


# SVG is intentionally excluded: it can itself reference remote resources.
_INLINE_RASTER_LOGO = re.compile(
    r"^data:(image/(?:png|jpeg|gif|webp));base64,([A-Za-z0-9+/=\s]+)$",
    re.IGNORECASE,
)
MAX_INLINE_LOGO_BYTES = 1 * 1024 * 1024


def safe_invoice_logo(value: object) -> Optional[str]:
    """Return a bounded safe data URI or ``None``.

    Remote URLs, filesystem paths, SVGs, malformed base64, and oversized
    images are discarded.  The returned source is safe to put in an ``img``
    element without giving WeasyPrint a network or filesystem URL to fetch.
    """
    if not isinstance(value, str):
        return None
    match = _INLINE_RASTER_LOGO.fullmatch(value.strip())
    if not match:
        return None

    mime, encoded = match.groups()
    # Whitespace is tolerated by data-URI producers, but rejected by b64decode
    # with validate=True, so remove it before the validation/size check.
    encoded = "".join(encoded.split())
    try:
        raw = base64.b64decode(encoded, validate=True)
    except (ValueError, binascii.Error):
        return None
    if not raw or len(raw) > MAX_INLINE_LOGO_BYTES:
        return None
    return f"data:{mime.lower()};base64,{encoded}"
