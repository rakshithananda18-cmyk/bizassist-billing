"""Log lines read like billing's: component column + [BizId=…] per request."""
import io
import json
import logging

from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.logging_config import _handler, get_logger
from app.main import _bizid_log_context
from app.security import bizid_from_authorization


def _capture(logger_name="bizassist"):
    buf = io.StringIO()
    h = _handler(logging.StreamHandler(buf), use_color=False)
    logging.getLogger(logger_name).addHandler(h)
    return buf, h


def test_request_log_lines_carry_the_callers_bizid(biz):
    # The real middleware on a probe app. The route is sync, so it runs in the
    # threadpool like every real route — where a contextvar set by a sync
    # dependency would be lost (billing main_groq.py learned this the hard way).
    probe = FastAPI()
    probe.middleware("http")(_bizid_log_context)

    @probe.get("/probe")
    def _route():
        get_logger("task.probe").warning("[FIELD] probe")
        return {}

    buf, h = _capture()
    try:
        with TestClient(probe) as c:
            c.get("/probe", headers=biz.h)
            c.get("/probe")
    finally:
        logging.getLogger("bizassist").removeHandler(h)
    owner_line, anon_line = buf.getvalue().splitlines()
    assert " task.probe " in owner_line
    assert owner_line.endswith(f"[BizId={biz.public_id}] [FIELD] probe")
    assert anon_line.endswith("[BizId=-] [FIELD] probe")


def test_staff_tokens_name_their_business_for_logs(biz):
    s = biz.staff()
    tok = biz.login_staff(s["login_name"])["token"]
    assert bizid_from_authorization(f"Bearer {tok}") == biz.public_id
    assert bizid_from_authorization(biz.h["Authorization"]) == biz.public_id
    assert bizid_from_authorization("Bearer not-a-token") is None
    assert bizid_from_authorization(None) is None


def test_json_log_format(monkeypatch):
    monkeypatch.setenv("LOG_FORMAT", "json")
    buf = io.StringIO()
    lg = get_logger("task.jsonprobe")
    h = _handler(logging.StreamHandler(buf), use_color=False)
    lg.addHandler(h)
    try:
        lg.warning("[TRACK] json probe")
    finally:
        lg.removeHandler(h)
    line = json.loads(buf.getvalue().splitlines()[0])
    assert line["service.name"] == "bizassist-task"
    assert line["component"] == "task.jsonprobe"
    assert line["biz_id"] == "-" and line["message"] == "[TRACK] json probe"
