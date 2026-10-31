"""Archive local repair exports using AES-GCM and a Windows DPAPI-wrapped key.

Source files are preserved. The encrypted archive is recoverable by the same
Windows user. Export it to an independent password-protected recovery vault
before retiring that Windows profile. No keys or financial contents are logged.
"""
import argparse
import base64
import ctypes
from ctypes import wintypes
import hashlib
import json
import os
from pathlib import Path
import uuid


class Blob(ctypes.Structure):
    _fields_ = [("length", wintypes.DWORD), ("data", ctypes.POINTER(ctypes.c_ubyte))]


def dpapi(data, *, decrypt=False):
    if os.name != "nt":
        raise RuntimeError("This vault uses the Windows user's DPAPI key")
    memory = (ctypes.c_ubyte * len(data)).from_buffer_copy(data)
    source = Blob(len(data), memory)
    output = Blob()
    library = ctypes.WinDLL("crypt32", use_last_error=True)
    function = library.CryptUnprotectData if decrypt else library.CryptProtectData
    function.restype = wintypes.BOOL
    # CRYPTPROTECT_UI_FORBIDDEN: automation never opens a credential dialog.
    success = function(ctypes.byref(source), None, None, None, None, 1, ctypes.byref(output))
    if not success:
        raise ctypes.WinError(ctypes.get_last_error())
    try:
        return ctypes.string_at(output.data, output.length)
    finally:
        free = ctypes.WinDLL("kernel32").LocalFree
        free.argtypes = [ctypes.c_void_p]
        free.restype = ctypes.c_void_p
        free(output.data)


def archive(paths, destination):
    from cryptography.hazmat.primitives.ciphers.aead import AESGCM
    entries = []
    for raw in paths:
        path = Path(raw).resolve(strict=True)
        data = path.read_bytes()
        entries.append({"name": path.name, "sha256": hashlib.sha256(data).hexdigest(),
                        "contents": base64.b64encode(data).decode()})
    if not entries or len({e["name"] for e in entries}) != len(entries):
        raise ValueError("Provide source files with distinct names")
    key, nonce = AESGCM.generate_key(bit_length=256), os.urandom(12)
    aad = b"bizassist-private-evidence-v1"
    plaintext = json.dumps(entries).encode()
    ciphertext = AESGCM(key).encrypt(nonce, plaintext, aad)
    protected = dpapi(key)
    recovered = dpapi(protected, decrypt=True)
    if AESGCM(recovered).decrypt(nonce, ciphertext, aad) != plaintext:
        raise RuntimeError("Evidence recovery verification failed")
    b64 = lambda value: base64.b64encode(value).decode()
    payload = {"format": aad.decode(), "wrapped_key": b64(protected), "nonce": b64(nonce),
               "ciphertext": b64(ciphertext), "count": len(entries)}
    destination = Path(destination)
    destination.mkdir(parents=True, exist_ok=True)
    path = destination / ("repair-evidence-" + uuid.uuid4().hex + ".vault.json")
    with path.open("x", encoding="utf-8") as stream:
        json.dump(payload, stream)
    return path


def recover(archive_path, destination):
    from cryptography.hazmat.primitives.ciphers.aead import AESGCM
    payload = json.loads(Path(archive_path).read_text(encoding="utf-8"))
    if payload.get("format") != "bizassist-private-evidence-v1":
        raise ValueError("Unsupported private evidence format")
    dec = base64.b64decode
    entries = json.loads(AESGCM(dpapi(dec(payload["wrapped_key"]), decrypt=True)).decrypt(
        dec(payload["nonce"]), dec(payload["ciphertext"]), payload["format"].encode()))
    destination = Path(destination)
    # Preflight all names and bytes before creating the new recovery directory.
    for entry in entries:
        name, data = entry["name"], dec(entry["contents"])
        if Path(name).name != name or name in {".", ".."} or hashlib.sha256(data).hexdigest() != entry["sha256"]:
            raise ValueError("Invalid evidence entry")
    destination.mkdir(parents=True, exist_ok=False)
    for entry in entries:
        with (destination / entry["name"]).open("xb") as stream:
            stream.write(dec(entry["contents"]))
    return len(entries)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--destination", required=True)
    parser.add_argument("--recover", help="Vault to recover into a new directory")
    parser.add_argument("sources", nargs="*")
    args = parser.parse_args()
    if args.recover:
        print("Recovered files:", recover(args.recover, args.destination))
    else:
        print("Encrypted evidence vault:", archive(args.sources, args.destination))
