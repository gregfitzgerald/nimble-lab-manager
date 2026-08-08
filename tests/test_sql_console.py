"""Adversarial tests for the read-only SQL console.

This is the most dangerous surface in the app, so it is tested like one: every
layer (feature gate, role gate, read-only handle, authorizer, secret redaction,
limits) gets its own attack.
"""

import sqlite3

import pytest

import app.db as appdb
import app.sqlconsole as sqlconsole


def _enable(admin):
    cfg = admin.get("/api/config").json()
    cfg["sql_console_enabled"] = True
    assert admin.patch("/api/config", json=cfg).status_code == 200


def _q(admin, sql):
    return admin.post("/api/sql/query", json={"sql": sql})


# --------------------------------------------------------------------------- #
# gating: off by default, admin only
# --------------------------------------------------------------------------- #
def test_disabled_by_default(admin):
    assert _q(admin, "SELECT 1").status_code == 403
    assert admin.get("/api/sql/schema").status_code == 403


def test_enabling_makes_it_work(admin):
    _enable(admin)
    r = _q(admin, "SELECT COUNT(*) AS n FROM inventory")
    assert r.status_code == 200, r.text
    assert r.json()["columns"] == ["n"]


def test_manager_and_member_are_refused_even_when_enabled(admin, manager, member):
    _enable(admin)
    assert manager.post("/api/sql/query", json={"sql": "SELECT 1"}).status_code == 403
    assert member.post("/api/sql/query", json={"sql": "SELECT 1"}).status_code == 403
    assert manager.get("/api/sql/schema").status_code == 403


def test_anonymous_is_refused(client):
    assert client.post("/api/sql/query", json={"sql": "SELECT 1"}).status_code == 401


# --------------------------------------------------------------------------- #
# writes must be impossible
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize("sql", [
    "UPDATE inventory SET quantity_on_hand = 0",
    "DELETE FROM inventory",
    "INSERT INTO inventory (item_name, quantity_on_hand, reorder_threshold, unit_cost, category, status) VALUES ('x',1,1,1,'other','active')",
    "DROP TABLE inventory",
    "CREATE TABLE evil (x INTEGER)",
    "ALTER TABLE inventory ADD COLUMN evil TEXT",
])
def test_writes_are_refused(admin, db, sql):
    _enable(admin)
    before = db.execute("SELECT COUNT(*) FROM inventory").fetchone()[0]
    assert _q(admin, sql).status_code == 400
    db.commit()
    assert db.execute("SELECT COUNT(*) FROM inventory").fetchone()[0] == before


def test_write_smuggled_after_a_select_is_refused(admin, db):
    _enable(admin)
    before = db.execute("SELECT COUNT(*) FROM inventory").fetchone()[0]
    r = _q(admin, "SELECT 1; DELETE FROM inventory")
    assert r.status_code == 400
    assert "one statement" in r.json()["detail"].lower()
    db.commit()
    assert db.execute("SELECT COUNT(*) FROM inventory").fetchone()[0] == before


@pytest.mark.parametrize("sql", [
    "ATTACH DATABASE '/tmp/evil.db' AS evil",
    "PRAGMA journal_mode",
    "SELECT load_extension('evil.so')",
])
def test_escape_hatches_are_refused(admin, sql):
    _enable(admin)
    assert _q(admin, sql).status_code == 400


# --------------------------------------------------------------------------- #
# secrets stay secret, even from an admin
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize("sql", [
    "SELECT password_hash FROM app_user",
    "SELECT password_salt FROM app_user",
    "SELECT * FROM app_user",          # star expansion still touches the columns
    "SELECT token FROM session",
    "SELECT * FROM session",
])
def test_credentials_cannot_be_read(admin, sql):
    _enable(admin)
    r = _q(admin, sql)
    assert r.status_code == 400, f"{sql!r} should be refused, got {r.text}"


def test_non_secret_user_columns_are_still_queryable(admin):
    _enable(admin)
    r = _q(admin, "SELECT username, role FROM app_user ORDER BY id")
    assert r.status_code == 200, r.text
    assert "admin" in [row[0] for row in r.json()["rows"]]


def test_schema_listing_hides_secrets(admin):
    _enable(admin)
    tables = {t["name"]: t["columns"] for t in admin.get("/api/sql/schema").json()["tables"]}
    assert "session" not in tables
    assert "password_hash" not in tables.get("app_user", [])
    assert "username" in tables.get("app_user", [])
    assert "inventory" in tables


# --------------------------------------------------------------------------- #
# limits
# --------------------------------------------------------------------------- #
def test_row_cap_truncates(admin):
    _enable(admin)
    # A cross join produces far more rows than the cap.
    r = _q(admin, "SELECT a.item_id, b.item_id FROM inventory a, inventory b, inventory c")
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["row_count"] <= sqlconsole.MAX_ROWS
    assert body["truncated"] is True


def test_empty_query_is_rejected(admin):
    _enable(admin)
    assert _q(admin, "   ").status_code == 400


def test_query_is_audited(admin, db):
    _enable(admin)
    _q(admin, "SELECT 1 AS one")
    row = db.execute(
        "SELECT action, detail FROM audit_log WHERE action = 'sql.query' ORDER BY id DESC LIMIT 1"
    ).fetchone()
    assert row is not None and "SELECT 1" in row["detail"]


def test_refused_query_is_also_audited(admin, db):
    _enable(admin)
    _q(admin, "DELETE FROM inventory")
    row = db.execute(
        "SELECT action FROM audit_log WHERE action = 'sql.query.failed' ORDER BY id DESC LIMIT 1"
    ).fetchone()
    assert row is not None


# --------------------------------------------------------------------------- #
# engine-level checks (no HTTP layer)
# --------------------------------------------------------------------------- #
def test_engine_refuses_write_even_if_called_directly(db_path):
    """Belt and braces: the engine must be safe on its own, not only behind the API."""
    with pytest.raises(sqlconsole.QueryError):
        sqlconsole.run_query(str(db_path), "DELETE FROM inventory")
    conn = sqlite3.connect(db_path)
    try:
        assert conn.execute("SELECT COUNT(*) FROM inventory").fetchone()[0] > 0
    finally:
        conn.close()


def test_engine_reads_work(db_path):
    out = sqlconsole.run_query(str(db_path), "SELECT COUNT(*) AS n FROM inventory")
    assert out["columns"] == ["n"] and out["row_count"] == 1


def test_timeout_aborts_a_runaway_query(db_path):
    """A cartesian join must not be able to pin the CPU indefinitely."""
    with pytest.raises(sqlconsole.QueryError) as exc:
        sqlconsole.run_query(
            str(db_path),
            "SELECT COUNT(*) FROM inventory a, inventory b, inventory c, inventory d, "
            "inventory e, inventory f, inventory g",
            timeout=0.4,
        )
    assert "longer than" in str(exc.value).lower()


def test_db_path_is_resolved_at_call_time(admin, monkeypatch):
    """The console must follow app.db.DB_PATH, not a copy bound at import.

    Repointing at a missing file must fail. (It surfaces as a server error rather
    than a 400, because the gate check opens the database before the console
    does -- either way, a stale import-time path would have answered 200.)
    """
    _enable(admin)
    monkeypatch.setattr(appdb, "DB_PATH", "/nonexistent/nope.db")
    assert _q(admin, "SELECT 1").status_code != 200
