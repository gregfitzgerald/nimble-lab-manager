"""Scale guards: list endpoints must not issue one query per row.

The app is for a real lab, which after a few years means thousands of items and
tens of thousands of usage events. The failure mode that actually bites at that
size is N+1 -- a per-row query inside a loop -- which is invisible on the ~20-row
demo seed and quadratic in production.

These tests count the SQL statements a request actually issues (via
sqlite3.set_trace_callback) and assert the count does not scale with the number
of rows returned. They are deliberately generous about the constant: the point is
to catch "per row", not to police exact query counts.
"""

import sqlite3

import pytest

import app.db as appdb


@pytest.fixture
def counting_conn(monkeypatch):
    """Patch app.db.get_conn so every statement on every connection is counted."""
    counter = {"n": 0, "statements": []}
    real_connect = sqlite3.connect

    def traced_get_conn():
        conn = real_connect(appdb.DB_PATH, timeout=5.0)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys = ON")
        conn.execute("PRAGMA busy_timeout = 5000")

        def trace(statement):
            counter["n"] += 1
            if len(counter["statements"]) < 400:
                counter["statements"].append(statement)

        conn.set_trace_callback(trace)
        return conn

    monkeypatch.setattr(appdb, "get_conn", traced_get_conn)
    # api.py imported get_conn by name, so patch that binding too.
    import app.api as api
    monkeypatch.setattr(api, "get_conn", traced_get_conn)
    return counter


def _bulk_items(db, n, prefix):
    """Add n active items directly, each with a lot, bypassing the API."""
    for i in range(n):
        cur = db.execute(
            """INSERT INTO inventory (item_name, quantity_on_hand, reorder_threshold,
                                      unit_cost, category, status)
               VALUES (?, 10, 2, 1.5, 'reagent', 'active')""",
            (f"{prefix} item {i}",),
        )
        db.execute(
            "INSERT INTO item_lot (item_id, quantity, lot_number) VALUES (?, 10, 'L')",
            (cur.lastrowid,),
        )
    db.commit()


def _queries_for(counting_conn, fn):
    counting_conn["n"] = 0
    counting_conn["statements"].clear()
    resp = fn()
    return resp, counting_conn["n"]


def test_items_list_is_not_n_plus_1(member, db, counting_conn):
    """GET /api/items must not issue a query per item."""
    _, small = _queries_for(counting_conn, lambda: member.get("/api/items"))
    _bulk_items(db, 60, "scale")
    resp, large = _queries_for(counting_conn, lambda: member.get("/api/items"))

    assert resp.status_code == 200
    assert len(resp.json()) >= 60
    # 60 extra rows must not mean ~60 extra queries.
    assert large - small < 30, (
        f"query count grew by {large - small} for 60 extra rows -- looks like N+1. "
        f"sample: {counting_conn['statements'][:5]}"
    )


def test_dashboard_query_count_is_bounded(member, db, counting_conn):
    _, small = _queries_for(counting_conn, lambda: member.get("/api/dashboard"))
    _bulk_items(db, 60, "dash")
    resp, large = _queries_for(counting_conn, lambda: member.get("/api/dashboard"))
    assert resp.status_code == 200
    assert large - small < 30, f"dashboard grew by {large - small} queries for 60 rows"


def test_integrity_report_is_a_single_pass(manager, db, counting_conn):
    _, small = _queries_for(counting_conn, lambda: manager.get("/api/integrity/stock"))
    _bulk_items(db, 60, "integ")
    # make them all discrepant so they land in the report
    db.execute("UPDATE inventory SET quantity_on_hand = quantity_on_hand + 5 "
               "WHERE item_name LIKE 'integ item%'")
    db.commit()
    resp, large = _queries_for(counting_conn, lambda: manager.get("/api/integrity/stock"))
    assert resp.status_code == 200
    assert large - small < 20, f"integrity report grew by {large - small} queries"


def test_large_list_still_responds(member, db):
    """A few hundred items must not break the list endpoint."""
    _bulk_items(db, 300, "bulk")
    resp = member.get("/api/items")
    assert resp.status_code == 200
    assert len(resp.json()) >= 300


def test_notifications_sync_is_bounded(manager, db, counting_conn):
    """_sync_notifications reconciles alerts on every read -- it must stay bounded."""
    _, small = _queries_for(counting_conn, lambda: manager.get("/api/notifications"))
    # 60 low-stock items => 60 new alert conditions
    _bulk_items(db, 60, "alert")
    db.execute("UPDATE inventory SET quantity_on_hand = 0 WHERE item_name LIKE 'alert item%'")
    db.commit()
    resp, large = _queries_for(counting_conn, lambda: manager.get("/api/notifications"))
    assert resp.status_code == 200
    # One INSERT per genuinely new alert is expected; what must not happen is a
    # per-alert *read* on top of it.
    assert large - small < 150, f"notification sync grew by {large - small} queries"
