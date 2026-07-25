"""Production-hardening tests: CSRF double-submit, security headers, docs,
and login rate limiting. Relies on the shared conftest fixtures (auth on,
isolated temp DB)."""


def test_csrf_missing_header_rejected(make_client):
    """A logged-in client that drops X-CSRF-Token gets 403 on a mutation."""
    member = make_client("member")
    # make_client set this automatically; strip it to simulate a forged request.
    member.headers.pop("X-CSRF-Token", None)
    resp = member.post("/api/items/1/consume", json={"quantity": 1})
    assert resp.status_code == 403
    assert resp.json()["detail"] == "CSRF token missing or invalid"


def test_csrf_present_header_succeeds(make_client):
    """With the matching header the same mutation is allowed through."""
    member = make_client("member")
    assert member.headers.get("X-CSRF-Token")
    resp = member.post("/api/items/1/consume", json={"quantity": 1})
    # Not a CSRF rejection; the request reaches the handler (200, or a
    # domain error like 400/404 -- never 403 for CSRF).
    assert resp.status_code != 403


def test_security_headers_present(make_client):
    member = make_client("member")
    resp = member.get("/api/dashboard")
    assert resp.headers["X-Content-Type-Options"] == "nosniff"
    assert resp.headers["X-Frame-Options"] == "DENY"
    assert resp.headers["Referrer-Policy"] == "no-referrer"
    assert "Permissions-Policy" in resp.headers
    csp = resp.headers["Content-Security-Policy"]
    assert "default-src 'self'" in csp
    assert "script-src 'self'" in csp
    assert "style-src 'self' 'unsafe-inline'" in csp
    assert "frame-ancestors 'none'" in csp


def test_docs_and_openapi_available(client):
    """Swagger docs and the OpenAPI schema are not shadowed by the SPA mount."""
    r_openapi = client.get("/openapi.json")
    assert r_openapi.status_code == 200
    assert r_openapi.json()["info"]["title"] == "Nimble Lab Manager"
    r_docs = client.get("/docs")
    assert r_docs.status_code == 200


def test_login_rate_limit(client):
    """>= 8 failed attempts for a username within the window -> 429."""
    codes = []
    for _ in range(9):
        r = client.post(
            "/api/login", json={"username": "ratelimit_user", "password": "wrong"}
        )
        codes.append(r.status_code)
    # First 8 are credential failures (401); the 9th is locked out (429).
    assert codes[:8] == [401] * 8
    assert codes[8] == 429
