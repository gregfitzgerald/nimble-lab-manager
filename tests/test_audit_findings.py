"""Regression tests for defects found by the adversarial audit sweep.

Each test encodes a specific failure the audit proved, so the fix cannot silently
regress.
"""

import io


# --------------------------------------------------------------------------- #
# stocktake alert was auto-dismissed by the notification reconciler
# --------------------------------------------------------------------------- #
def test_stocktake_alert_survives_a_notification_poll(member, manager, db):
    """_sync_notifications must only auto-clear alerts it regenerates itself."""
    box_id = db.execute("SELECT box_id FROM container LIMIT 1").fetchone()[0]
    sid = member.post("/api/counts", json={"location_id": box_id}).json()["id"]
    member.post(f"/api/counts/{sid}/close")

    row = db.execute(
        """SELECT id, read_at FROM notification
            WHERE entity_type = 'count_session' AND entity_id = ?""", (sid,)
    ).fetchone()
    assert row is not None, "closing a count with missing containers should alert"
    assert row["read_at"] is None

    # Polling notifications runs the reconciler; the alert must still be unread.
    manager.get("/api/notifications")
    manager.get("/api/notifications")
    after = db.execute(
        "SELECT read_at FROM notification WHERE id = ?", (row["id"],)
    ).fetchone()["read_at"]
    assert after is None, "stocktake alert was swept by the reconciler"


def test_reconciler_still_clears_its_own_alerts(manager, db):
    """The narrower sweep must not stop it clearing conditions that resolved."""
    db.execute("UPDATE inventory SET quantity_on_hand = 0, reorder_threshold = 5 "
               "WHERE item_id = 1")
    db.commit()
    manager.get("/api/notifications")
    open_alert = db.execute(
        """SELECT id FROM notification
            WHERE kind = 'low_stock' AND entity_type = 'inventory'
              AND entity_id = 1 AND read_at IS NULL"""
    ).fetchone()
    assert open_alert is not None

    db.execute("UPDATE inventory SET quantity_on_hand = 99 WHERE item_id = 1")
    db.commit()
    manager.get("/api/notifications")
    assert db.execute(
        "SELECT read_at FROM notification WHERE id = ?", (open_alert["id"],)
    ).fetchone()["read_at"] is not None


# --------------------------------------------------------------------------- #
# equipment double-booking via mismatched datetime text formats
# --------------------------------------------------------------------------- #
def _equipment_id(db):
    return db.execute("SELECT id FROM equipment LIMIT 1").fetchone()[0]


def test_overlapping_reservation_is_refused_across_datetime_formats(member, db):
    """The browser posts 'YYYY-MM-DDTHH:MM'; the seed uses a space separator.
    Comparing them as raw text made the overlap check silently pass."""
    eid = _equipment_id(db)
    first = member.post(f"/api/equipment/{eid}/reservations", json={
        "starts_at": "2026-09-01 09:00:00", "ends_at": "2026-09-01 17:00:00",
    })
    assert first.status_code == 200, first.text
    # Same day, clearly overlapping, but sent in the browser's 'T' format.
    clash = member.post(f"/api/equipment/{eid}/reservations", json={
        "starts_at": "2026-09-01T10:00", "ends_at": "2026-09-01T12:00",
    })
    assert clash.status_code == 400, "overlapping booking was accepted"


def test_reservation_datetimes_are_stored_canonically(member, db):
    eid = _equipment_id(db)
    member.post(f"/api/equipment/{eid}/reservations", json={
        "starts_at": "2026-10-05T08:30", "ends_at": "2026-10-05T09:30",
    })
    row = db.execute(
        "SELECT starts_at, ends_at FROM equipment_reservation ORDER BY id DESC LIMIT 1"
    ).fetchone()
    assert "T" not in row["starts_at"] and "T" not in row["ends_at"]
    assert row["starts_at"] == "2026-10-05 08:30:00"


def test_non_overlapping_reservation_still_allowed(member, db):
    eid = _equipment_id(db)
    member.post(f"/api/equipment/{eid}/reservations", json={
        "starts_at": "2026-11-01 09:00:00", "ends_at": "2026-11-01 10:00:00",
    })
    ok = member.post(f"/api/equipment/{eid}/reservations", json={
        "starts_at": "2026-11-01T10:00", "ends_at": "2026-11-01T11:00",
    })
    assert ok.status_code == 200, ok.text


# --------------------------------------------------------------------------- #
# controlled dispense must move lots too
# --------------------------------------------------------------------------- #
def test_controlled_dispense_draws_down_lots(member, db):
    row = db.execute(
        """SELECT i.item_id FROM inventory i
            WHERE i.is_controlled = 1 AND i.quantity_on_hand > 0 LIMIT 1"""
    ).fetchone()
    assert row is not None, "seed should include a controlled substance"
    item_id = row["item_id"]
    before = db.execute(
        "SELECT COALESCE(SUM(quantity),0) FROM item_lot WHERE item_id = ?", (item_id,)
    ).fetchone()[0]

    r = member.post(f"/api/controlled/{item_id}/log",
                    json={"change": -1, "witness": "J. Chen", "reason": "test"})
    assert r.status_code == 200, r.text
    after = db.execute(
        "SELECT COALESCE(SUM(quantity),0) FROM item_lot WHERE item_id = ?", (item_id,)
    ).fetchone()[0]
    assert after == before - 1, "register moved but the lot ledger did not"


# --------------------------------------------------------------------------- #
# CSV import update path must keep lots in step
# --------------------------------------------------------------------------- #
def test_import_update_keeps_lots_in_sync(manager, db):
    item = db.execute(
        "SELECT item_id, item_name FROM inventory WHERE status='active' LIMIT 1"
    ).fetchone()
    csv = f"item_id,item_name,quantity_on_hand\n{item['item_id']},{item['item_name']},77\n"
    r = manager.post(
        "/api/import/inventory",
        files={"file": ("i.csv", io.BytesIO(csv.encode()), "text/csv")},
        data={"dry_run": "false"},
    )
    assert r.status_code == 200, r.text
    on_hand = db.execute(
        "SELECT quantity_on_hand FROM inventory WHERE item_id = ?", (item["item_id"],)
    ).fetchone()[0]
    lots = db.execute(
        "SELECT COALESCE(SUM(quantity),0) FROM item_lot WHERE item_id = ?",
        (item["item_id"],)
    ).fetchone()[0]
    assert on_hand == 77
    assert lots == 77, "import changed stock without moving the lots"


def test_import_update_is_not_counted_as_usage(manager, db):
    item = db.execute(
        "SELECT item_id, item_name FROM inventory WHERE status='active' LIMIT 1"
    ).fetchone()
    csv = f"item_id,item_name,quantity_on_hand\n{item['item_id']},{item['item_name']},5\n"
    manager.post(
        "/api/import/inventory",
        files={"file": ("i.csv", io.BytesIO(csv.encode()), "text/csv")},
        data={"dry_run": "false"},
    )
    ev = db.execute(
        "SELECT event_type FROM usage_event WHERE item_id = ? ORDER BY id DESC LIMIT 1",
        (item["item_id"],)
    ).fetchone()
    assert ev["event_type"] == "adjust"


# --------------------------------------------------------------------------- #
# CSV formula injection
# --------------------------------------------------------------------------- #
def test_export_neutralizes_spreadsheet_formulas(manager, db):
    db.execute(
        "UPDATE inventory SET item_name = '=cmd|calc' WHERE item_id = 1"
    )
    db.commit()
    body = manager.get("/api/export/inventory.csv").text
    assert "=cmd|calc" not in body.replace("'=cmd|calc", "")
    assert "'=cmd|calc" in body


# --------------------------------------------------------------------------- #
# login throttle
# --------------------------------------------------------------------------- #
def test_oversized_login_fields_are_rejected(client):
    """An unauthenticated caller must not be able to force a huge PBKDF2 hash."""
    r = client.post("/api/login", json={"username": "a" * 5000, "password": "b" * 5000})
    assert r.status_code == 422


def test_import_rejects_oversized_upload(manager, monkeypatch):
    """The read is capped, so a huge upload cannot be pulled into memory whole.
    (The cap is lowered here rather than shipping a multi-megabyte fixture.)"""
    import app.api as api
    monkeypatch.setattr(api, "_IMPORT_MAX_BYTES", 512)
    big = b"item_name,quantity_on_hand\n" + b"x,1\n" * 500
    r = manager.post(
        "/api/import/inventory",
        files={"file": ("big.csv", io.BytesIO(big), "text/csv")},
        data={"dry_run": "true"},
    )
    assert r.status_code == 400
    assert "too large" in r.json()["detail"]


# --------------------------------------------------------------------------- #
# uploaded files must require a session
# --------------------------------------------------------------------------- #
def test_uploads_require_authentication(client, member, tmp_path):
    """Files under web/uploads were served by the unauthenticated static mount."""
    import os

    from app.server import UPLOADS_DIR

    os.makedirs(os.path.join(UPLOADS_DIR, "docs"), exist_ok=True)
    probe = os.path.join(UPLOADS_DIR, "docs", "_authprobe.txt")
    with open(probe, "w", encoding="utf-8") as fh:
        fh.write("secret")
    try:
        assert client.get("/uploads/docs/_authprobe.txt").status_code == 401
        ok = member.get("/uploads/docs/_authprobe.txt")
        assert ok.status_code == 200 and ok.text == "secret"
    finally:
        os.remove(probe)


def test_upload_path_traversal_is_blocked(member):
    r = member.get("/uploads/../../schema.sql")
    assert r.status_code == 404


# --------------------------------------------------------------------------- #
# PO receive input validation
# --------------------------------------------------------------------------- #
def test_receive_rejects_non_numeric_qty(manager, db):
    po = manager.post("/api/purchase-orders", json={
        "vendor": "Sigma", "lines": [{"item_id": 1, "quantity": 4}],
    }).json()
    pid = po["id"]
    for s in ["pending_approval", "approved", "submitted", "ordered"]:
        manager.patch(f"/api/purchase-orders/{pid}", json={"status": s})
    line_id = manager.get(f"/api/purchase-orders/{pid}").json()["lines"][0]["id"]
    r = manager.post(f"/api/purchase-orders/{pid}/receive",
                     json={"receipts": [{"line_id": line_id, "qty": "lots"}]})
    assert r.status_code == 400, f"expected 400, got {r.status_code}"


def test_receive_and_set_fund_in_one_request_charges_the_fund(manager, db):
    """The fund write used to land after the charge decision, so nothing booked."""
    fund_id = db.execute("SELECT id FROM fund LIMIT 1").fetchone()[0]
    po = manager.post("/api/purchase-orders", json={
        "vendor": "NEB", "lines": [{"item_id": 1, "quantity": 6, "unit_cost": 95}],
    }).json()
    pid = po["id"]
    for s in ["pending_approval", "approved", "submitted", "ordered"]:
        manager.patch(f"/api/purchase-orders/{pid}", json={"status": s})
    before = db.execute(
        "SELECT COUNT(*) FROM fund_charge WHERE fund_id = ?", (fund_id,)
    ).fetchone()[0]
    r = manager.patch(f"/api/purchase-orders/{pid}",
                      json={"status": "received", "fund_id": fund_id})
    assert r.status_code == 200, r.text
    after = db.execute(
        "SELECT COUNT(*) FROM fund_charge WHERE fund_id = ?", (fund_id,)
    ).fetchone()[0]
    assert after == before + 1, "receiving with a fund in the same request booked nothing"
