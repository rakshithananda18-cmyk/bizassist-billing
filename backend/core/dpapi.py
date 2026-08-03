"""Windows DPAPI — wrap a secret so a COPIED FILE is useless.

WHY THIS EXISTS
---------------
The packaged desktop app has to hold secrets that survive a reboot with **no
human present** (`services/scheduler.py` starts 12 background jobs, including
sync, before anyone logs in). So the secret cannot be behind a passphrase, which
leaves exactly one honest option: store it bound to something the machine has and
a copied file does not.

`CryptProtectData` with the default flags binds the blob to the **current Windows
user on this machine**. Copying the file to a USB stick, pulling the disk, or
mailing a support bundle yields ciphertext.

WHAT IT DOES NOT DO — read this before quoting it in a claim
------------------------------------------------------------
It does **not** protect against anything running as that same Windows user. A
thief who has the Windows password, or malware in the user's session, unwraps
this as easily as we do. See
`docs/DECISION_LOCAL_DB_ENCRYPTION_2026-08-03.md` §1 for the threat table this
covers (T1, T4, T5) and the two it does not (T2, T3).

NO ENTROPY PARAMETER, DELIBERATELY
----------------------------------
`CryptProtectData` accepts optional extra entropy that must be supplied again to
unwrap. It is omitted because any constant we pass ships inside the binary, so it
is readable by the same attacker it would supposedly stop. It would add a moving
part and a migration hazard while buying nothing against the threats above.

STDLIB ONLY
-----------
`ctypes` against `crypt32.dll`. `pywin32` would do the same thing and is a new
dependency in a PyInstaller bundle that is already large.
"""
from __future__ import annotations

import ctypes
import sys
from typing import Optional

_IS_WINDOWS = sys.platform == "win32"

# Never show a UI. This runs in a background process spawned by Electron; a
# blocking prompt there is an invisible hang, not a prompt.
_CRYPTPROTECT_UI_FORBIDDEN = 0x01


if _IS_WINDOWS:  # pragma: no cover - exercised only on Windows
    from ctypes import wintypes

    class _Blob(ctypes.Structure):
        _fields_ = [
            ("cbData", wintypes.DWORD),
            ("pbData", ctypes.POINTER(ctypes.c_char)),
        ]

    _crypt32 = ctypes.WinDLL("crypt32", use_last_error=True)
    _kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)

    _crypt32.CryptProtectData.restype = wintypes.BOOL
    _crypt32.CryptUnprotectData.restype = wintypes.BOOL
    _kernel32.LocalFree.argtypes = [ctypes.c_void_p]


def available() -> bool:
    """True when wrapping is possible here. False on Linux/macOS (dev + CI)."""
    return _IS_WINDOWS


def _make_blob(data: bytes):
    """Returns (blob, keepalive). The buffer MUST outlive the call — a local
    `create_string_buffer` that goes out of scope leaves pbData dangling."""
    buf = ctypes.create_string_buffer(data, len(data))
    return _Blob(len(data), ctypes.cast(buf, ctypes.POINTER(ctypes.c_char))), buf


def _call(fn, data: bytes) -> Optional[bytes]:
    blob_in, _keepalive = _make_blob(data)
    blob_out = _Blob()
    ok = fn(ctypes.byref(blob_in), None, None, None, None,
            _CRYPTPROTECT_UI_FORBIDDEN, ctypes.byref(blob_out))
    if not ok:
        return None
    try:
        return ctypes.string_at(blob_out.pbData, blob_out.cbData)
    finally:
        _kernel32.LocalFree(blob_out.pbData)


def protect(data: bytes) -> Optional[bytes]:
    """Wrap `data` for the current Windows user. None if unavailable or refused.

    None is a normal answer, not an error: on Linux/macOS there is no DPAPI, and
    the caller is expected to have a documented fallback rather than crash.
    """
    if not _IS_WINDOWS:
        return None
    return _call(_crypt32.CryptProtectData, data)


def unprotect(blob: bytes) -> Optional[bytes]:
    """Unwrap a blob from `protect`. None when it cannot be unwrapped.

    None here is the load-bearing case: it is what a DIFFERENT Windows user, a
    reinstalled profile, or a data directory restored onto another machine looks
    like. Callers must treat it as "this secret is gone" and have an answer —
    for `jwt-secret` that answer is "mint a new one, everyone logs in again",
    which is why that secret is safe to wrap this way and a DATABASE key is not.
    """
    if not _IS_WINDOWS:
        return None
    return _call(_crypt32.CryptUnprotectData, blob)
