"""Run selected existing tests with fresh synthetic DBs and no external access.

Usage from repo root: python <this-file> field|backend|backend-pg|backend-rls <pytest arguments...>
backend-pg requires an explicit loopback BIZASSIST_TEST_DATABASE_URL naming a test DB.
backend-rls keeps the app on SQLite and uses an explicit loopback TEST_PG_URL.
This imports no application until environment and network guards are established.
"""
from pathlib import Path
import os
import socket
import sys
import tempfile
from urllib.parse import urlparse

ROOT = Path(__file__).resolve().parents[1]
kind = sys.argv.pop(1)
assert kind in {'field', 'backend', 'backend-pg', 'backend-rls'}
pg_url = ''
if kind in {'backend-pg', 'backend-rls'}:
    pg_url = os.environ.get('BIZASSIST_TEST_DATABASE_URL' if kind == 'backend-pg' else 'TEST_PG_URL', '')
    parsed = urlparse(pg_url)
    if (parsed.scheme not in {'postgresql', 'postgresql+psycopg2'}
            or parsed.hostname not in {'127.0.0.1', 'localhost', '::1'}
            or 'test' not in parsed.path.lower() or not parsed.port):
        raise SystemExit('PostgreSQL tests require an explicit loopback test database and port')
app_pg_url = pg_url if kind == 'backend-pg' else ''
work = Path(tempfile.mkdtemp(prefix='remediation_test_', dir=ROOT / 'scratch'))
tempfile.tempdir = str(work)
os.environ.update({
    'TEMP': str(work), 'TMP': str(work),
    'DATABASE_URL': app_pg_url or 'sqlite:///' + (work / 'test_review.db').as_posix(),
    'BIZASSIST_TEST_DATABASE_URL': app_pg_url, 'TASK_TEST_DATABASE_URL': '',
    'TASK_TEST_BILLING_SCHEMA': '', 'TASK_RLS_ADMIN_TEST_URL': '', 'TEST_PG_URL': pg_url,
    'JWT_SECRET': 'test-only-secret-please-change-0123456789abcdef',
    'GROQ_API_KEY': 'mock_groq_api_key', 'SENTRY_DSN': '',
    'BIZASSIST_TESTING': '1', 'TASK_PURGE_LOOP': '0', 'TASK_CRON_SECRET': '',
    'SUBSCRIPTION_ENFORCED': '0', 'SPACE_ID': '', 'K_SERVICE': '', 'ENVIRONMENT': '',
    'CLOUD_API_URL': 'http://127.0.0.1:9', 'CLOUD_URL': 'http://127.0.0.1:9',
    'BIZASSIST_CLOUD_URL': 'http://127.0.0.1:9', 'VITE_API_URL': 'http://127.0.0.1:9',
    'TELEMETRY_ENABLED': '0', 'CHAT_MEMORY_ENABLED': '0', 'ANONYMIZED_TELEMETRY': 'False',
    # This runner denies external network access. Use real cached model files
    # without Hub metadata retries; a missing cache remains explicitly unavailable.
    'HF_HUB_OFFLINE': '1', 'TRANSFORMERS_OFFLINE': '1', 'HF_HUB_DISABLE_TELEMETRY': '1',
    'PYTEST_DISABLE_PLUGIN_AUTOLOAD': '1', 'LOG_LEVEL': 'WARNING', 'LOG_FORMAT': 'text',
    'PYTEST_XDIST_WORKER': 'remed_review_' + work.name,
    'BIZASSIST_TEST_RUN_ID': work.name,
})
os.environ.pop('BILLING_BACKEND_DIR', None)
import dotenv
dotenv.load_dotenv = lambda *_a, **_kw: False
# Install the same guard before Python subprocesses/xdist workers import the app.
# Environment-only DB guards do not propagate a monkeypatch into a new process.
original_connect = socket.socket.connect
original_connect_ex = socket.socket.connect_ex
original_dns = socket.getaddrinfo
def local_only(address):
    return not isinstance(address, tuple) or address[0] in {'localhost', '127.0.0.1', '::1'}
def connect(sock, address):
    if not local_only(address):
        raise OSError('External network denied during remediation review')
    return original_connect(sock, address)
def connect_ex(sock, address):
    if not local_only(address):
        return 10061
    return original_connect_ex(sock, address)
def dns(host, *args, **kwargs):
    if host not in {None, 'localhost', '127.0.0.1', '::1'}:
        raise OSError('External DNS denied during remediation review')
    return original_dns(host, *args, **kwargs)
socket.socket.connect = connect
socket.socket.connect_ex = connect_ex
socket.getaddrinfo = dns
# sitecustomize is loaded by every worker interpreter, before pytest/conftest.
(work / 'sitecustomize.py').write_text('import socket' + chr(10) + "import dotenv\ndotenv.load_dotenv = lambda *_a, **_kw: False\n# Install the same guard before Python subprocesses/xdist workers import the app.\n# Environment-only DB guards do not propagate a monkeypatch into a new process.\noriginal_connect = socket.socket.connect\noriginal_connect_ex = socket.socket.connect_ex\noriginal_dns = socket.getaddrinfo\ndef local_only(address):\n    return not isinstance(address, tuple) or address[0] in {'localhost', '127.0.0.1', '::1'}\ndef connect(sock, address):\n    if not local_only(address):\n        raise OSError('External network denied during remediation review')\n    return original_connect(sock, address)\ndef connect_ex(sock, address):\n    if not local_only(address):\n        return 10061\n    return original_connect_ex(sock, address)\ndef dns(host, *args, **kwargs):\n    if host not in {None, 'localhost', '127.0.0.1', '::1'}:\n        raise OSError('External DNS denied during remediation review')\n    return original_dns(host, *args, **kwargs)\nsocket.socket.connect = connect\nsocket.socket.connect_ex = connect_ex\nsocket.getaddrinfo = dns\n", encoding='utf-8')
os.environ['PYTHONPATH'] = str(work) + os.pathsep + os.environ.get('PYTHONPATH', '')
app_dir = ROOT / ('backend-task' if kind == 'field' else 'backend')
os.chdir(app_dir)
sys.path.insert(0, str(app_dir))
import pytest
import importlib.util
if importlib.util.find_spec('anyio') is not None and not any(arg in {'anyio.pytest_plugin', 'no:anyio', 'no:anyio.pytest_plugin'} for arg in sys.argv[1:]):
    # Autoload is disabled intentionally; name the required async plugin in
    # argv so xdist children receive the same explicit test configuration.
    sys.argv[1:1] = ['-p', 'anyio.pytest_plugin']
raise SystemExit(pytest.main(sys.argv[1:]))
