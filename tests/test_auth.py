"""Authentication and role-gating tests."""


def test_unauthenticated_request_is_401(client):
    resp = client.get("/api/items")
    assert resp.status_code == 401


def test_login_bad_password(client):
    resp = client.post("/api/login", json={"username": "member", "password": "wrong"})
    assert resp.status_code == 401


def test_login_unknown_user(client):
    resp = client.post("/api/login", json={"username": "nobody", "password": "x"})
    assert resp.status_code == 401


def test_login_success_sets_cookie_and_returns_user(client):
    resp = client.post("/api/login", json={"username": "member", "password": "member"})
    assert resp.status_code == 200
    user = resp.json()["user"]
    assert user["username"] == "member"
    assert user["role"] == "member"
    assert "nlm_session" in resp.cookies
    # cookie now grants access to protected routes
    assert client.get("/api/items").status_code == 200


def test_me_reflects_logged_in_user(manager):
    resp = manager.get("/api/me")
    assert resp.status_code == 200
    user = resp.json()["user"]
    assert user["username"] == "manager"
    assert user["role"] == "manager"


def test_logout_invalidates_session(member):
    assert member.get("/api/me").status_code == 200
    resp = member.post("/api/logout")
    assert resp.status_code == 200
    # The server deleted the session row; even replaying the old cookie fails.
    assert member.get("/api/me").status_code == 401
    assert member.get("/api/items").status_code == 401


def test_viewer_can_read_but_not_mutate(viewer):
    assert viewer.get("/api/items").status_code == 200
    resp = viewer.post("/api/items/15/consume", json={"quantity": 1})
    assert resp.status_code == 403


def test_member_can_mutate(member):
    resp = member.post("/api/items/15/consume", json={"quantity": 1})
    assert resp.status_code == 200


def test_member_cannot_reset(member):
    assert member.post("/api/reset").status_code == 403


def test_manager_can_reset_and_keeps_session(manager):
    resp = manager.post("/api/reset")
    assert resp.status_code == 200
    assert resp.json() == {"ok": True}
    # Reset rebuilds the DB (wiping sessions) but restores the caller's.
    assert manager.get("/api/me").status_code == 200


def test_viewer_cannot_use_location_crud(viewer):
    resp = viewer.post("/api/locations", json={"kind": "room", "name": "X"})
    assert resp.status_code == 403


def test_auth_off_opens_everything_as_admin(noauth_client):
    # No login at all, yet reads, mutations, and manager-only routes work.
    me = noauth_client.get("/api/me")
    assert me.status_code == 200
    user = me.json()["user"]
    assert user["role"] == "admin"
    assert user["username"] == "admin"

    assert noauth_client.get("/api/items").status_code == 200
    assert (
        noauth_client.post("/api/items/15/consume", json={"quantity": 1}).status_code
        == 200
    )
    assert noauth_client.post("/api/reset").status_code == 200
