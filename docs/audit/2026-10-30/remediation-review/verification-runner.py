"""Run selected existing tests with fresh synthetic DBs and no external access.

Usage from repo root: python <this-file> field|backend <pytest arguments...>
This imports no application until environment and network guards are established.
"""
from pathlib import Path
import os
import socket
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[4]
kind = sys.argv.pop(1)
assert kind in {'field', 'backend'}
work = Path(tempfile.mkdtemp(prefix='remediation_test_', dir=ROOT / 'scratch'))
tempfile.tempdir = str(work)
os.environ.update({
    'TEMP': str(work), 'TMP': str(work),
    'DATABASE_URL': 'sqlite:///' + (work / 'test_review.db').as_posix(),
    'BIZASSIST_TEST_DATABASE_URL': '', 'TASK_TEST_DATABASE_URL': '',
    'TASK_TEST_BILLING_SCHEMA': '', 'TASK_RLS_ADMIN_TEST_URL': '', 'TEST_PG_URL': '',
    'JWT_SECRET': 'test-only-secret-please-change-0123456789abcdef',
    'GROQ_API_KEY': 'mock_groq_api_key', 'SENTRY_DSN': '',
    'BIZASSIST_TESTING': '1', 'TASK_PURGE_LOOP': '0', 'TASK_CRON_SECRET': '',
    'SUBSCRIPTION_ENFORCED': '0', 'SPACE_ID': '', 'K_SERVICE': '', 'ENVIRONMENT': '',
    'CLOUD_API_URL': 'http://127.0.0.1:9', 'CLOUD_URL': 'http://127.0.0.1:9',
    'BIZASSIST_CLOUD_URL': 'http://127.0.0.1:9', 'VITE_API_URL': 'http://127.0.0.1:9',
    'TELEMETRY_ENABLED': '0', 'CHAT_MEMORY_ENABLED': '0', 'ANONYMIZED_TELEMETRY': 'False',
    'PYTEST_DISABLE_PLUGIN_AUTOLOAD': '1', 'LOG_LEVEL': 'WARNING', 'LOG_FORMAT': 'text',
    'PYTEST_XDIST_WORKER': 'remed_review_' + work.name,
})
os.environ.pop('BILLING_BACKEND_DIR', None)
import dotenv
dotenv.load_dotenv = lambda *_a, **_kw: False
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
app_dir = ROOT / ('backend-task' if kind == 'field' else 'backend')
os.chdir(app_dir)
sys.path.insert(0, str(app_dir))
import pytest
raise SystemExit(pytest.main(sys.argv[1:]))
