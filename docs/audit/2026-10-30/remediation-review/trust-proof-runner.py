"""Isolated verification runner; never loads developer env or external services."""
from pathlib import Path
import os
import socket
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[4]
work = ROOT / "scratch" / "remediation-trust-runtime"
work.mkdir(exist_ok=True)
os.environ["TEMP"] = os.environ["TMP"] = str(work)
tempfile.tempdir = str(work)
base_packages = Path(r"C:\Users\raksh\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\Lib\site-packages")
if base_packages.exists():
    sys.path.append(str(base_packages))
os.environ.update({
    "BIZASSIST_TEST_DATABASE_URL": "sqlite:///./test_remediation_trust.db",
    "DATABASE_URL": "sqlite:///./test_remediation_trust.db",
    "BIZASSIST_TESTING": "1",
    "GROQ_API_KEY": "mock_groq_api_key",
    "JWT_SECRET": "test-only-secret-please-change-0123456789abcdef",
    "SENTRY_DSN": "", "CHAT_MEMORY_ENABLED": "0", "TELEMETRY_ENABLED": "0",
    "ANONYMIZED_TELEMETRY": "False", "CLOUD_API_URL": "http://127.0.0.1:9",
    "CLOUD_URL": "http://127.0.0.1:9", "VITE_API_URL": "http://127.0.0.1:9", "TEST_PG_URL": "",
})
import dotenv
dotenv.load_dotenv = lambda *_a, **_kw: False
connect = socket.socket.connect
connect_ex = socket.socket.connect_ex
getaddrinfo = socket.getaddrinfo
def local(address):
    return not isinstance(address, tuple) or address[0] in {"localhost", "127.0.0.1", "::1"}
def guarded_connect(sock, address):
    if not local(address):
        raise OSError("External network disabled in remediation verification")
    return connect(sock, address)
def guarded_connect_ex(sock, address):
    if not local(address):
        return 10061
    return connect_ex(sock, address)
def guarded_getaddrinfo(host, *args, **kwargs):
    if host not in {None, "localhost", "127.0.0.1", "::1"}:
        raise OSError("External DNS disabled in remediation verification")
    return getaddrinfo(host, *args, **kwargs)
socket.socket.connect = guarded_connect
socket.socket.connect_ex = guarded_connect_ex
socket.getaddrinfo = guarded_getaddrinfo
for i, arg in enumerate(sys.argv[1:], 1):
    if arg.startswith("--rootdir="):
        sys.argv[i] = "--rootdir=" + str(ROOT / arg.split("=", 1)[1])
    elif arg.startswith("backend/") or arg.startswith("docs/"):
        sys.argv[i] = str(ROOT / arg)
os.chdir(work)
sys.path.insert(0, str(ROOT / "backend"))
import pytest
raise SystemExit(pytest.main(sys.argv[1:]))
