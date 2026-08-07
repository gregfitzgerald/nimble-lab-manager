"""Shared fixtures for the Nimble Lab Manager test suite.

Isolation strategy: app.db derives every connection from the module-global
app.db.DB_PATH, read at call time by get_conn()/init_db(). We repoint that
global at a per-test temp file, so the suite never touches the repo's dev
lab.db.

Speed: init_db() PBKDF2-hashes the four demo passwords (210k iterations
each), which is the slow part. We build one template database per test
session and file-copy it into each test's tmp_path, so the hashing cost is
paid exactly once.
"""

import shutil
import sqlite3

import pytest
from fastapi.testclient import TestClient

import app.db as appdb


@pytest.fixture(scope="session")
def template_db(tmp_path_factory):
    """Build the seeded database (schema.sql + seed.sql + demo users) once."""
    path = tmp_path_factory.mktemp("nlm-template") / "template.db"
    original = appdb.DB_PATH
    appdb.DB_PATH = str(path)
    try:
        # The suite asserts against the seeded demo lab and logs in as the four
        # demo roles, so build the template with demo seeding on explicitly
        # (independent of the ambient NLM_SEED_DEMO, which defaults off).
        appdb.init_db(force=True, seed_demo=True)
    finally:
        appdb.DB_PATH = original
    return path


@pytest.fixture
def db_path(template_db, tmp_path, monkeypatch):
    """Fresh copy of the seeded DB, with app.db.DB_PATH pointed at it.

    Also pins NLM_AUTH=on so tests are deterministic regardless of the
    invoking shell's environment.
    """
    path = tmp_path / "lab.db"
    shutil.copy(template_db, path)
    monkeypatch.setattr(appdb, "DB_PATH", str(path))
    monkeypatch.setenv("NLM_AUTH", "on")
    return path


@pytest.fixture
def db(db_path):
    """Direct sqlite3 connection to the test DB, for white-box assertions."""
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    yield conn
    conn.close()


@pytest.fixture
def make_client(db_path):
    """Factory for TestClients against the isolated DB.

    make_client() -> anonymous client (no session cookie).
    make_client("member") -> client logged in via POST /api/login; the
    TestClient cookie jar keeps the session for subsequent requests.
    Each call returns a separate client with its own cookie jar, so one test
    can hold several roles at once.
    """
    from app.server import app

    clients = []

    def factory(role=None):
        client = TestClient(app)
        client.__enter__()  # run startup (init_db is a no-op on the copy)
        clients.append(client)
        if role is not None:
            resp = client.post(
                "/api/login", json={"username": role, "password": role}
            )
            assert resp.status_code == 200, f"login as {role!r} failed: {resp.text}"
            # Double-submit CSRF: echo the login-issued cookie back as a header
            # so all mutating requests from role clients pass the check.
            client.headers["X-CSRF-Token"] = client.cookies.get("nlm_csrf")
        return client

    yield factory
    for client in clients:
        client.__exit__(None, None, None)


@pytest.fixture
def client(make_client):
    """Anonymous client (auth on, not logged in)."""
    return make_client()


@pytest.fixture
def viewer(make_client):
    return make_client("viewer")


@pytest.fixture
def member(make_client):
    return make_client("member")


@pytest.fixture
def manager(make_client):
    return make_client("manager")


@pytest.fixture
def admin(make_client):
    return make_client("admin")


@pytest.fixture
def noauth_client(db_path, monkeypatch):
    """Client with NLM_AUTH=off: every request acts as a synthetic admin."""
    monkeypatch.setenv("NLM_AUTH", "off")
    from app.server import app

    with TestClient(app) as client:
        yield client
