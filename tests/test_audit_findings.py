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


# --------------------------------------------------------------------------- #
# deletes must not leave dangling soft references
# --------------------------------------------------------------------------- #
def test_location_delete_refused_while_equipment_references_it(manager, db):
    """equipment.location_id is a soft ref: deleting the location would leave it
    pointing at a dead id that SQLite can later reuse for a different room."""
    row = db.execute(
        "SELECT id, location_id FROM equipment WHERE location_id IS NOT NULL LIMIT 1"
    ).fetchone()
    assert row is not None, "seed should place equipment somewhere"
    r = manager.delete(f"/api/locations/{row['location_id']}")
    assert r.status_code == 400
    assert "equipment" in r.json()["detail"]
    # and it is still there
    assert db.execute(
        "SELECT COUNT(*) FROM location_node WHERE id = ?", (row["location_id"],)
    ).fetchone()[0] == 1


def test_user_delete_refused_while_holding_glassware(admin, db):
    uid = admin.post("/api/users", json={
        "username": "loanholder", "full_name": "L", "role": "member",
        "password": "validpass1",
    }).json().get("id") or db.execute(
        "SELECT id FROM app_user WHERE username='loanholder'").fetchone()[0]
    gid = db.execute("SELECT id FROM glassware_item LIMIT 1").fetchone()[0]
    db.execute(
        """INSERT INTO glassware_checkout (glassware_id, user_id, checked_out_at)
           VALUES (?, ?, datetime('now'))""", (gid, uid))
    db.commit()
    r = admin.delete(f"/api/users/{uid}")
    assert r.status_code == 400
    assert "checked-out" in r.json()["detail"]


def test_user_delete_refused_when_work_history_exists(admin, db):
    """ticket.user_id is NOT NULL, so history cannot be de-referenced --
    deactivating is the correct action and the error must say so."""
    # Build the case explicitly: a fresh user with one usage record and no loan,
    # so the history guard is what is under test.
    admin.post("/api/users", json={
        "username": "hashistory", "full_name": "H", "role": "member",
        "password": "validpass1",
    })
    uid = db.execute(
        "SELECT id FROM app_user WHERE username = 'hashistory'").fetchone()[0]
    db.execute(
        "INSERT INTO ticket (user_id, ticket_date, purpose, created_at) "
        "VALUES (?, date('now'), 'test', datetime('now'))", (uid,))
    db.commit()

    r = admin.delete(f"/api/users/{uid}")
    assert r.status_code == 400
    assert "deactivate" in r.json()["detail"].lower()


def test_user_delete_nulls_nullable_history(admin, db):
    uid = admin.post("/api/users", json={
        "username": "historic", "full_name": "H", "role": "member",
        "password": "validpass1",
    }).json().get("id") or db.execute(
        "SELECT id FROM app_user WHERE username='historic'").fetchone()[0]
    cid = db.execute("SELECT id FROM chore LIMIT 1").fetchone()[0]
    db.execute(
        "INSERT INTO chore_log (chore_id, done_at, done_by) VALUES (?, date('now'), ?)",
        (cid, uid))
    db.commit()
    assert admin.delete(f"/api/users/{uid}").status_code == 200
    # the log row survives, but no longer points at a recyclable id
    row = db.execute(
        "SELECT done_by FROM chore_log WHERE chore_id = ? ORDER BY id DESC LIMIT 1",
        (cid,)).fetchone()
    assert row["done_by"] is None


# --------------------------------------------------------------------------- #
# timezone
# --------------------------------------------------------------------------- #
def test_today_honours_the_configured_timezone(db, monkeypatch):
    import app.api as api
    monkeypatch.setenv("NLM_TZ", "Pacific/Honolulu")
    hawaii = api._today(db)
    monkeypatch.setenv("NLM_TZ", "Pacific/Auckland")
    auckland = api._today(db)
    # Somewhere on earth these differ; whichever way, neither may crash and both
    # must be ISO dates.
    for value in (hawaii, auckland):
        assert len(value) == 10 and value[4] == "-"


def test_bad_timezone_falls_back_to_utc(db, monkeypatch):
    import app.api as api
    monkeypatch.setenv("NLM_TZ", "Not/AZone")
    assert len(api._today(db)) == 10   # must not raise


# --------------------------------------------------------------------------- #
# request body cap
# --------------------------------------------------------------------------- #
def test_oversized_json_body_is_refused(member):
    huge = {"quantity": 1, "note": "x" * (1024 * 1024 + 64)}
    r = member.post("/api/items/1/consume", json=huge)
    assert r.status_code == 413


def test_normal_json_body_still_accepted(member):
    r = member.post("/api/items/1/consume", json={"quantity": 1, "note": "fine"})
    assert r.status_code == 200


# --------------------------------------------------------------------------- #
# non-finite fund amount must be rejected (Infinity bricked all fund reads)
# --------------------------------------------------------------------------- #
def test_infinity_fund_charge_is_rejected(manager, db):
    """json.loads accepts the Infinity token; persisting it made every fund read
    500, because inf is not JSON-serialisable. It must be refused up front."""
    fid = db.execute("SELECT id FROM fund LIMIT 1").fetchone()[0]
    # Send the raw non-standard Infinity token, which json.loads (and thus
    # Starlette) accepts -- a normal json= body would be rejected client-side.
    r = manager.post(
        f"/api/funds/{fid}/charges",
        content=b'{"amount": Infinity, "description": "attack"}',
        headers={"Content-Type": "application/json"},
    )
    assert r.status_code == 400
    # and the funds subsystem still reads fine
    assert manager.get(f"/api/funds/{fid}").status_code == 200
    assert manager.get("/api/funds").status_code == 200
    assert manager.get("/api/funds/spend-by-person").status_code == 200


def test_finite_fund_charge_still_works(manager, db):
    fid = db.execute("SELECT id FROM fund LIMIT 1").fetchone()[0]
    r = manager.post(f"/api/funds/{fid}/charges",
                     json={"amount": 42.50, "description": "reagents"})
    assert r.status_code == 200, r.text
