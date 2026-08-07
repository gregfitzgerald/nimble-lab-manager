"""Secure-by-default bootstrap tests.

Demo seeding is opt-in (NLM_SEED_DEMO): a deployed instance starts with an
EMPTY database and a single bootstrapped admin instead of the well-known
admin/admin demo logins. Passwords have a minimum length, and the destructive
reset is limited to demo instances.
"""

import sqlite3

import app.auth as auth
import app.db as appdb


def _init_empty(tmp_path, monkeypatch, **env):
    """Build a fresh non-demo database at an isolated path; return the path."""
    path = tmp_path / "empty.db"
    monkeypatch.setattr(appdb, "DB_PATH", str(path))
    for key, value in env.items():
        monkeypatch.setenv(key, value)
    appdb.init_db(force=True, seed_demo=False)
    return path


def _users(path):
    conn = sqlite3.connect(path)
    try:
        return conn.execute(
            "SELECT username, role FROM app_user ORDER BY id"
        ).fetchall()
    finally:
        conn.close()


def test_empty_start_bootstraps_single_admin(tmp_path, monkeypatch):
    monkeypatch.delenv("NLM_ADMIN_USER", raising=False)
    monkeypatch.delenv("NLM_ADMIN_PASSWORD", raising=False)
    path = _init_empty(tmp_path, monkeypatch)
    # Exactly one admin, and none of the demo accounts (admin/admin etc.).
    assert _users(path) == [("admin", "admin")]


def test_empty_start_has_no_demo_data(tmp_path, monkeypatch):
    path = _init_empty(tmp_path, monkeypatch)
    conn = sqlite3.connect(path)
    try:
        assert conn.execute("SELECT COUNT(*) FROM inventory").fetchone()[0] == 0
    finally:
        conn.close()


def test_bootstrap_respects_admin_env(tmp_path, monkeypatch):
    path = _init_empty(
        tmp_path, monkeypatch,
        NLM_ADMIN_USER="root", NLM_ADMIN_PASSWORD="supersecret1",
    )
    assert _users(path) == [("root", "admin")]
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    try:
        assert auth.login_user(conn, "root", "supersecret1") is not None
        assert auth.login_user(conn, "root", "wrong") is None
    finally:
        conn.close()


def test_bootstrap_is_idempotent(tmp_path, monkeypatch):
    path = _init_empty(tmp_path, monkeypatch, NLM_ADMIN_PASSWORD="firstpass1")
    # A second init must not add another admin or disturb the first.
    appdb.init_db(seed_demo=False)  # DB_PATH is still monkeypatched
    assert _users(path) == [("admin", "admin")]


def test_password_policy_rejects_short_on_create(admin):
    r = admin.post("/api/users", json={
        "username": "shorty", "full_name": "S", "role": "member", "password": "short1",
    })
    assert r.status_code == 400
    assert "8" in r.json()["detail"]


def test_password_policy_rejects_short_on_reset(admin, db):
    admin.post("/api/users", json={
        "username": "resetme", "full_name": "R", "role": "member",
        "password": "validpass1",
    })
    uid = db.execute("SELECT id FROM app_user WHERE username='resetme'").fetchone()["id"]
    r = admin.post(f"/api/users/{uid}/password", json={"password": "short"})
    assert r.status_code == 400


def test_reset_disabled_outside_demo(manager, monkeypatch):
    monkeypatch.delenv("NLM_SEED_DEMO", raising=False)
    monkeypatch.delenv("NLM_ALLOW_RESET", raising=False)
    assert manager.post("/api/reset").status_code == 403
