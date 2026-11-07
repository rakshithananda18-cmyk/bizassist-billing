def test_rejected_session_has_browser_visible_marker(client):
    origin = "https://bizassist-task.vercel.app"
    response = client.get("/api/auth/me", headers={"Authorization": "Bearer invalid", "Origin": origin})
    assert response.status_code == 401
    assert response.headers["WWW-Authenticate"] == 'Bearer error="invalid_token"'
    assert response.headers["Access-Control-Allow-Origin"] == origin
    assert "www-authenticate" in response.headers["Access-Control-Expose-Headers"].lower()


def test_bad_credentials_are_not_a_session_rejection(client):
    response = client.post("/api/auth/owner/login", json={"username": "unknown-session-marker-user", "password": "incorrect"})
    assert response.status_code == 401
    assert "WWW-Authenticate" not in response.headers
