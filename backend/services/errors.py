"""
services/errors.py
==================
One error contract for the API.

Before: `handle()` returned `{"error": ..., "status_code": 429}` as a 200-OK
body, so clients had to parse the body to discover failure (H1). Now the
pipeline raises `AskError`, and a single FastAPI exception handler turns it into
a real HTTP status code with this body shape:

    { "error": "<human message>", "code": "<machine code>", ...extra }

`code` is a stable machine-readable string (e.g. "rate_limited"); `error` is the
human message. Optional extras (limit/used/retry_after) are included when set.
"""
from typing import Optional


class AskError(Exception):
    """Raised by the /ask pipeline to signal a real HTTP error + envelope."""

    def __init__(self, status_code: int, payload: dict):
        self.status_code = status_code
        self.payload = payload
        super().__init__(payload.get("error", "Request failed."))


def ask_error(status_code: int, code: str, message: str, **extra) -> AskError:
    """Build an AskError with the canonical error envelope. None extras are dropped."""
    payload = {"error": message, "code": code}
    for k, v in extra.items():
        if v is not None:
            payload[k] = v
    return AskError(status_code, payload)
