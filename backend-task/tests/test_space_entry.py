"""The Space's entry point: HF runs `python space_app.py` and probes "/"."""
import space_app


def test_space_app_serves_the_same_app_on_the_space_port():
    assert space_app.APP == "app.main:app"
    assert space_app.PORT == 7860


def test_root_answers_when_the_screens_live_elsewhere(client):
    r = client.get("/")
    assert r.status_code == 200
    assert r.json() == {"service": "bizassist-task", "ok": True, "health": "/api/health"}
    assert client.get("/api/health").json()["ok"] is True
