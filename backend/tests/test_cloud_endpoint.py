# Observed counterexamples on the unfixed code (task 1.1), with the four
# variables removed:
#   services.sync_worker.CLOUD_URL = https://rakshit-dev-bizassist.hf.space
#   routes.b2b_proxy.CLOUD_URL     = https://rakshit-dev-bizassist.hf.space
#   services.realtime._CLOUD_URL   = https://rakshit-dev-bizassist.hf.space
# Expected for all three: https://staterbill-api-1076771386585.asia-south1.run.app
"""
tests/test_cloud_endpoint.py
============================
Bug condition exploration for C1 (bugfix 1.32 to 1.34, design Property 1 and
Property 3): with no cloud URL variable set, every backend cloud caller must
resolve the Cloud Run billing API, not the retired Hugging Face Space.

The suite sets CLOUD_API_URL before the app is imported, so the default can
only be observed in a fresh interpreter. The probe runs in a subprocess with
CLOUD_API_URL, VITE_API_URL, CLOUD_URL and BIZASSIST_CLOUD_URL removed; it keeps
the test DATABASE_URL and the mock GROQ_API_KEY, and it stops python-dotenv
from re-adding a cloud URL from a developer's .env.
"""
import json
import os
import subprocess
import sys

os.environ.setdefault("DATABASE_URL", "sqlite:///./test_bizassist.db")
os.environ.setdefault("GROQ_API_KEY", "mock_groq_api_key")
os.environ.setdefault("CLOUD_API_URL", "http://127.0.0.1:9")

BACKEND_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, BACKEND_DIR)

CLOUD_RUN_URL = "https://staterbill-api-1076771386585.asia-south1.run.app"
CLOUD_URL_VARIABLES = ("CLOUD_API_URL", "VITE_API_URL", "CLOUD_URL", "BIZASSIST_CLOUD_URL")
_PROBE_PREFIX = "CLOUD_ENDPOINT_PROBE="

# The attributes other modules import (design C1.2). The probe prints them as JSON.
_PROBE = r'''
import json, os, sys
try:
    import dotenv
    dotenv.load_dotenv = lambda *args, **kwargs: False
except ImportError:
    pass
sys.path.insert(0, os.getcwd())
import services.sync_worker as sync_worker
import routes.b2b_proxy as b2b_proxy
import services.realtime as realtime
print("%s" + json.dumps({
    "leftover_variables": [v for v in %r if v in os.environ],
    "resolved": {
        "services.sync_worker.CLOUD_URL": sync_worker.CLOUD_URL,
        "routes.b2b_proxy.CLOUD_URL": b2b_proxy.CLOUD_URL,
        "services.realtime._CLOUD_URL": realtime._CLOUD_URL,
    },
}))
''' % (_PROBE_PREFIX, CLOUD_URL_VARIABLES)


def _probe_without_cloud_variables() -> dict:
    env = {k: v for k, v in os.environ.items() if k not in CLOUD_URL_VARIABLES}
    env["DATABASE_URL"] = os.environ["DATABASE_URL"]
    env["GROQ_API_KEY"] = "mock_groq_api_key"
    proc = subprocess.run(
        [sys.executable, "-c", _PROBE],
        cwd=BACKEND_DIR, env=env, capture_output=True, text=True, timeout=180,
    )
    assert proc.returncode == 0, (
        f"probe exited with {proc.returncode}\n{proc.stderr[-3000:]}"
    )
    lines = [ln for ln in proc.stdout.splitlines() if ln.startswith(_PROBE_PREFIX)]
    assert lines, f"probe printed no result\n{proc.stdout[-2000:]}"
    return json.loads(lines[-1][len(_PROBE_PREFIX):])


def test_cloud_callers_default_to_cloud_run_without_any_variable():
    """Property 1 / Property 3, default case: no variable set -> the Cloud Run URL.

    **Validates: Requirements 1.32, 1.34 (expected 2.32, 2.34)**
    """
    probe = _probe_without_cloud_variables()
    assert probe["leftover_variables"] == [], "the probe environment still sets a cloud URL"
    resolved = probe["resolved"]
    assert resolved == {name: CLOUD_RUN_URL for name in resolved}, (
        "backend cloud callers fall back to a host other than the Cloud Run billing API: "
        f"{json.dumps(resolved, indent=2)}"
    )
