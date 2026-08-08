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


# --------------------------------------------------------------------------- #
# a wider battery of escape attempts against the engine
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize("label,sql", [
    ("alias hides the column", "SELECT u.password_hash AS x FROM app_user u"),
    ("subquery", "SELECT (SELECT password_hash FROM app_user LIMIT 1) AS leak"),
    ("join to session", "SELECT s.token FROM session s JOIN app_user u ON u.id = s.user_id"),
    ("cte", "WITH c AS (SELECT password_salt FROM app_user) SELECT * FROM c"),
    ("temp table", "CREATE TEMP TABLE evil AS SELECT 1"),
    ("create view", "CREATE VIEW v AS SELECT 1"),
    ("update behind a cte", "WITH c AS (SELECT 1) UPDATE inventory SET quantity_on_hand = 0"),
    ("vacuum", "VACUUM"),
    ("attach via uri", "ATTACH DATABASE 'file:/etc/passwd?mode=ro' AS p"),
])
def test_escape_attempts_are_refused(db_path, label, sql):
    with pytest.raises(sqlconsole.QueryError):
        sqlconsole.run_query(str(db_path), sql, timeout=2.0)


def test_recursive_cte_bomb_is_stopped(db_path):
    """An unbounded recursive CTE must hit the deadline, not hang the server."""
    with pytest.raises(sqlconsole.QueryError) as exc:
        sqlconsole.run_query(
            str(db_path),
            "WITH RECURSIVE c(x) AS (SELECT 1 UNION ALL SELECT x+1 FROM c) "
            "SELECT COUNT(*) FROM c",
            timeout=1.0,
        )
    assert "longer than" in str(exc.value).lower()


def test_refusals_read_as_plain_english(db_path):
    """Users see these constantly, so they must not be raw SQLite strings."""
    for sql in ("VACUUM", "DELETE FROM inventory", "SELECT password_hash FROM app_user"):
        with pytest.raises(sqlconsole.QueryError) as exc:
            sqlconsole.run_query(str(db_path), sql, timeout=2.0)
        assert "Not allowed" in str(exc.value), f"{sql!r} -> {exc.value}"


def test_ordinary_analytics_queries_still_work(db_path):
    """The console has to remain useful, not just safe."""
    out = sqlconsole.run_query(
        str(db_path),
        """SELECT i.category, COUNT(*) AS n, ROUND(SUM(i.quantity_on_hand * i.unit_cost), 2) AS value
             FROM inventory i WHERE i.status = 'active'
            GROUP BY i.category ORDER BY value DESC""",
    )
    assert out["row_count"] > 0
    assert out["columns"] == ["category", "n", "value"]


# --------------------------------------------------------------------------- #
# result marshalling must never produce a 500 or invalid JSON
# --------------------------------------------------------------------------- #
def test_non_finite_float_is_returned_as_text(db_path):
    """json.dumps emits bare Infinity for these, which is not valid JSON."""
    import json
    out = sqlconsole.run_query(str(db_path), "SELECT 1e400 AS big")
    json.dumps(out)  # must not raise
    assert isinstance(out["rows"][0][0], str)


def test_huge_blob_is_summarised_not_returned(db_path):
    out = sqlconsole.run_query(str(db_path), "SELECT zeroblob(50000000) AS b")
    assert "bytes>" in str(out["rows"][0][0])


def test_huge_string_cell_is_clipped(db_path):
    out = sqlconsole.run_query(str(db_path), "SELECT hex(zeroblob(5000000)) AS s")
    assert len(out["rows"][0][0]) <= sqlconsole.MAX_CELL_CHARS + 40


def test_byte_budget_truncates_wide_results(db_path):
    """Row count alone is not enough of a cap when rows can be enormous.

    Each cell is clipped first, so the byte budget only bites on rows that are
    wide as well as long -- which is exactly the case the row cap misses.
    """
    out = sqlconsole.run_query(
        str(db_path),
        "WITH RECURSIVE n(i) AS (SELECT 1 UNION ALL SELECT i+1 FROM n WHERE i < 900) "
        "SELECT i, hex(zeroblob(3000)) a, hex(zeroblob(3000)) b, "
        "hex(zeroblob(3000)) c, hex(zeroblob(3000)) d FROM n",
        timeout=5.0,
    )
    assert out["truncated"] is True
    assert out["row_count"] < 900


def test_sql_console_endpoint_never_500s_on_odd_results(admin):
    _enable(admin)
    for sql in ("SELECT 1e400 AS x", "SELECT zeroblob(10000000) AS b", "SELECT NULL AS n"):
        r = _q(admin, sql)
        assert r.status_code == 200, f"{sql!r} -> {r.status_code} {r.text[:120]}"
        r.json()  # response must be parseable JSON
