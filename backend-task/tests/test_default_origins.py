"""Bug condition exploration, task 1.5 (Property 1; clause 1.4).

Expected behaviour (2.4, design.md C3 item 2): the production Field Team
origin passes the CORS preflight for `/api/auth/exchange` by default, and an
`ALLOWED_ORIGINS` list is added to the defaults instead of replacing them.

`app.main` builds its CORS middleware from `config.ALLOWED_ORIGINS` at import,
so each case imports the app in a fresh interpreter with its own environment.
That interpreter does not load a developer's local .env: the deployed image
has none, and the case must see exactly the variables it sets.
"""
# Observed on the unfixed code (task 1.5, both cases fail as expected):
#   ALLOWED_ORIGINS unset
#       -> ALLOWED_ORIGINS = [http://localhost:5176, http://127.0.0.1:5176, http://localhost:4173,
#          http://127.0.0.1:4173]; preflight from https://bizassist-task.vercel.app: 400, no
#          access-control-allow-origin
#   ALLOWED_ORIGINS=https://team.staterbill.com
#       -> ALLOWED_ORIGINS = [https://team.staterbill.com]; preflight from https://team.staterbill.com
#          is 200, but https://bizassist-task.vercel.app gets 400: the list replaces the defaults
# Confirms root cause 12 (the built-in default lists only localhost) for 1.4.

import json
import os
import subprocess
import sys
from pathlib import Path

PRODUCTION_ORIGIN = "https://bizassist-task.vercel.app"
LISTED_ORIGIN = "https://team.staterbill.com"  # adopted later through ALLOWED_ORIGINS (assumption 3)
BACKEND_TASK_DIR = Path(__file__).resolve().parents[1]

_PROBE = r"""
import json, sys
import dotenv
dotenv.load_dotenv = lambda *args, **kwargs: False
from fastapi.testclient import TestClient
from app import config
from app.main import app

client = TestClient(app)
result = {"allowed_origins": config.ALLOWED_ORIGINS, "preflight": {}}
for origin in json.loads(sys.argv[1]):
    r = client.options("/api/auth/exchange", headers={
        "Origin": origin,
        "Access-Control-Request-Method": "POST",
        "Access-Control-Request-Headers": "content-type",
    })
    result["preflight"][origin] = {"status": r.status_code,
                                   "allow_origin": r.headers.get("access-control-allow-origin")}
print(json.dumps(result))
"""


def _probe(tmp_path, origins, allowed_origins=None):
    env = {k: v for k, v in os.environ.items()
           if k not in ("ALLOWED_ORIGINS", "SPACE_ID", "K_SERVICE", "ENVIRONMENT")}
    env.update({
        "DATABASE_URL": f"sqlite:///{tmp_path / 'origins_test.db'}",  # never opened: no lifespan runs
        "TASK_CREATE_BILLING_MIRROR": "1",
        "JWT_SECRET": os.environ["JWT_SECRET"],
        "LOG_LEVEL": "WARNING",
        "TASK_PURGE_LOOP": "0",
    })
    if allowed_origins is not None:
        env["ALLOWED_ORIGINS"] = allowed_origins
    done = subprocess.run([sys.executable, "-c", _PROBE, json.dumps(origins)], cwd=BACKEND_TASK_DIR, env=env,
                          capture_output=True, text=True, timeout=120)
    assert done.returncode == 0, f"probe failed:\n{done.stderr[-2000:]}"
    return json.loads(done.stdout.strip().splitlines()[-1])


def _assert_preflight_allowed(result, origin):
    seen = result["preflight"][origin]
    assert seen == {"status": 200, "allow_origin": origin}, (
        f"preflight from {origin} refused: {seen}; ALLOWED_ORIGINS={result['allowed_origins']}")


def test_production_origin_is_allowed_without_allowed_origins(tmp_path):
    """**Validates: Requirements 1.4, 2.4** (no ALLOWED_ORIGINS in the environment)."""
    result = _probe(tmp_path, [PRODUCTION_ORIGIN])
    _assert_preflight_allowed(result, PRODUCTION_ORIGIN)


def test_allowed_origins_are_added_to_the_defaults(tmp_path):
    """**Validates: Requirements 1.4, 2.4** (ALLOWED_ORIGINS set: listed origins and defaults both pass)."""
    result = _probe(tmp_path, [PRODUCTION_ORIGIN, LISTED_ORIGIN], allowed_origins=LISTED_ORIGIN)
    _assert_preflight_allowed(result, LISTED_ORIGIN)
    _assert_preflight_allowed(result, PRODUCTION_ORIGIN)
