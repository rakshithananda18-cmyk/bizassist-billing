"""
tests/conftest.py
=================
Pin the routing mode for the test suite BEFORE the app imports (and before
db.py / main_groq.py call load_dotenv, which uses override=False and therefore
won't clobber an already-set value).

Why: most tests assert the deterministic legacy tiers — exact Groq-call counts
and TokenUsage row counts. A local `.env` with LLM_ROUTER=on would add an extra
8B classify call per query and break those assertions. Router-specific tests
(e.g. test_router_switch.py) call set_mode() at runtime, which takes precedence
over this env default, so they are unaffected.
"""
import os

# Deterministic default for the whole suite. load_dotenv(override=False) later
# will NOT overwrite this, so tests ignore whatever the dev's .env says.
os.environ["LLM_ROUTER"] = "off"
