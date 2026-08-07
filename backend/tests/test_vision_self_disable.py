"""
tests/test_vision_self_disable.py
=================================
Stop paying for a model this key cannot have.

Vision is an OPTIMISATION for bill scanning, not a requirement — a photo can
always go image → Tesseract → text → Groq text model, reaching the same
structured JSON the vision path reaches in one hop. So when the vision model is
refused, the correct behaviour is to stop asking, not to fail the upload.

Observed 2026-08-07: `meta-llama/llama-4-scout-17b-16e-instruct` returns
404 "does not exist or you do not have access to it" for a key that
authenticates fine and serves the text models. That is an account entitlement.
No retry changes it, yet every scanned bill paid a full round trip to rediscover
it before falling back.

Same shape as `_SELF_SIGNED_REJECTED` in services/sync_worker.py: remember a
failure that cannot self-heal, so it costs one call instead of one per request.
The distinction this pins is which failures qualify — latch on an entitlement,
never on a busy model.
"""
import importlib
import os
import sys

os.environ.setdefault("DATABASE_URL", "sqlite:///./test_bizassist.db")
os.environ.setdefault("GROQ_API_KEY", "mock_groq_api_key")

backend_path = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, backend_path)

import pytest                                        # noqa: E402


@pytest.fixture
def ocr():
    import services.purchase_ocr as P
    importlib.reload(P)          # a fresh, un-latched module per test
    return P


def test_a_model_entitlement_refusal_latches_off(ocr):
    ocr._note_vision_failure(Exception(
        "Error code: 404 - {'error': {'message': 'The model "
        "`meta-llama/llama-4-scout-17b-16e-instruct` does not exist or you do "
        "not have access to it.', 'code': 'model_not_found'}}"))
    assert ocr._VISION_UNAVAILABLE is True


@pytest.mark.parametrize("transient", [
    "Error code: 429 - rate_limit_exceeded: tokens per day",
    "Request timed out after 60s",
    "Error code: 500 - internal server error",
    "Connection aborted",
])
def test_transient_failures_do_not_latch(ocr, transient):
    """A busy or briefly-broken model must stay enabled. Latching here would
    disable vision for the life of the process over one blip."""
    ocr._note_vision_failure(Exception(transient))
    assert ocr._VISION_UNAVAILABLE is False, f"latched on a transient: {transient}"


def test_latching_is_reported_once_not_per_upload(ocr, caplog):
    """The log line names the fix. Repeating it on every scan would bury it."""
    err = Exception("404 model_not_found: model does not exist or you do not "
                    "have access to it")
    with caplog.at_level("ERROR"):
        for _ in range(5):
            ocr._note_vision_failure(err)
    hits = [r for r in caplog.records if "vision model refused" in r.getMessage()]
    assert len(hits) == 1, f"logged {len(hits)} times"
    assert "Tesseract" in hits[0].getMessage(), "must say scanning still works"


def test_a_restart_re_checks_entitlement(ocr):
    """The flag is per-process on purpose. If the account gains vision access,
    a restart resumes it — nothing to remember, nothing to unset."""
    ocr._note_vision_failure(Exception("404 model_not_found"))
    assert ocr._VISION_UNAVAILABLE is True

    import services.purchase_ocr as P
    importlib.reload(P)
    assert P._VISION_UNAVAILABLE is False
