"""Lot/stock integrity: stock must always have a lot behind it.

quantity_on_hand and SUM(item_lot.quantity) are separate numbers. When they
disagree, the stock figure and the expiry alerts (which read item_lot) tell
different stories. Item creation and CSV import used to set stock with no lot at
all, so imported stock was permanently invisible to expiry tracking.
"""

import io


def _lot_total(db, item_id):
    return db.execute(
        "SELECT COALESCE(SUM(quantity), 0) FROM item_lot WHERE item_id = ?", (item_id,)
    ).fetchone()[0]


# --------------------------------------------------------------------------- #
# opening balances create a lot
# --------------------------------------------------------------------------- #
def test_created_item_has_a_lot_for_its_opening_stock(manager, db):
    r = manager.post("/api/items", json={
        "item_name": "Integrity Test Reagent", "quantity_on_hand": 12,
        "reorder_threshold": 2, "unit_cost": 1.0, "category": "reagent",
    })
    assert r.status_code == 200, r.text
    item_id = r.json()["item_id"]
    assert _lot_total(db, item_id) == 12


def test_created_item_with_zero_stock_has_no_lot(manager, db):
    r = manager.post("/api/items", json={
        "item_name": "Empty Shelf Reagent", "quantity_on_hand": 0,
        "reorder_threshold": 1, "unit_cost": 1.0, "category": "reagent",
    })
    item_id = r.json()["item_id"]
    assert _lot_total(db, item_id) == 0


def test_imported_item_has_a_lot(manager, db):
    csv = "item_name,quantity_on_hand\nImported Integrity Item,7\n"
    r = manager.post(
        "/api/import/inventory",
        files={"file": ("i.csv", io.BytesIO(csv.encode()), "text/csv")},
        data={"dry_run": "false"},
    )
    assert r.status_code == 200, r.text
    item_id = db.execute(
        "SELECT item_id FROM inventory WHERE item_name = 'Imported Integrity Item'"
    ).fetchone()[0]
    assert _lot_total(db, item_id) == 7


def test_import_uses_expiry_column_when_present(manager, db):
    csv = "item_name,quantity_on_hand,expiry_date\nDated Import Item,3,2027-01-31\n"
    manager.post(
        "/api/import/inventory",
        files={"file": ("i.csv", io.BytesIO(csv.encode()), "text/csv")},
        data={"dry_run": "false"},
    )
    row = db.execute(
        """SELECT l.expiry_date FROM item_lot l JOIN inventory i ON i.item_id = l.item_id
            WHERE i.item_name = 'Dated Import Item'"""
    ).fetchone()
    assert row["expiry_date"] == "2027-01-31"


# --------------------------------------------------------------------------- #
# lots are editable -- the bit that makes imported stock trackable
# --------------------------------------------------------------------------- #
def test_lot_expiry_can_be_set_after_the_fact(manager, db):
    item_id = manager.post("/api/items", json={
        "item_name": "Needs Expiry", "quantity_on_hand": 5,
        "reorder_threshold": 1, "unit_cost": 1.0, "category": "reagent",
    }).json()["item_id"]
    lot_id = db.execute(
        "SELECT id FROM item_lot WHERE item_id = ?", (item_id,)
    ).fetchone()[0]

    r = manager.patch(f"/api/lots/{lot_id}",
                      json={"expiry_date": "2026-09-30", "lot_number": "LOT-42"})
    assert r.status_code == 200, r.text
    assert r.json()["expiry_date"] == "2026-09-30"
    assert r.json()["lot_number"] == "LOT-42"


def test_lot_patch_validates_date_format(manager, db):
    lot_id = db.execute("SELECT id FROM item_lot LIMIT 1").fetchone()[0]
    assert manager.patch(f"/api/lots/{lot_id}",
                         json={"expiry_date": "31/01/2027"}).status_code == 400


def test_lot_patch_404_and_role_gate(manager, viewer, db):
    lot_id = db.execute("SELECT id FROM item_lot LIMIT 1").fetchone()[0]
    assert manager.patch("/api/lots/999999",
                         json={"lot_number": "x"}).status_code == 404
    assert viewer.patch(f"/api/lots/{lot_id}",
                        json={"lot_number": "x"}).status_code == 403


def test_setting_expiry_makes_stock_visible_to_expiry_alerts(manager, db):
    """The payoff: previously-untrackable stock can now raise an expiry alert."""
    item_id = manager.post("/api/items", json={
        "item_name": "Soon Expiring Import", "quantity_on_hand": 4,
        "reorder_threshold": 1, "unit_cost": 1.0, "category": "reagent",
    }).json()["item_id"]
    lot_id = db.execute(
        "SELECT id FROM item_lot WHERE item_id = ?", (item_id,)
    ).fetchone()[0]
    # An expiry in the past must surface on the dashboard's expired count.
    manager.patch(f"/api/lots/{lot_id}", json={"expiry_date": "2020-01-01"})
    alerts = manager.get("/api/notifications").json()["notifications"]
    assert any("Soon Expiring Import" in a["message"] for a in alerts)


# --------------------------------------------------------------------------- #
# drift reporting
# --------------------------------------------------------------------------- #
def test_integrity_report_flags_untracked_stock(manager, db):
    # Simulate legacy data: stock with no lot behind it.
    db.execute(
        """INSERT INTO inventory (item_name, quantity_on_hand, reorder_threshold,
                                  unit_cost, category, status)
           VALUES ('Legacy Untracked', 9, 1, 1.0, 'reagent', 'active')"""
    )
    db.commit()
    report = manager.get("/api/integrity/stock").json()
    hit = next((r for r in report["items"] if r["item_name"] == "Legacy Untracked"), None)
    assert hit is not None
    assert hit["untracked"] == 9 and hit["over_lotted"] == 0
    assert report["untracked_items"] >= 1


def test_integrity_report_flags_over_lotted(manager, db):
    item_id = db.execute(
        "SELECT item_id FROM inventory WHERE status = 'active' LIMIT 1"
    ).fetchone()[0]
    db.execute("UPDATE inventory SET quantity_on_hand = 0 WHERE item_id = ?", (item_id,))
    db.execute(
        "INSERT INTO item_lot (item_id, quantity, lot_number) VALUES (?, 5, 'ghost')",
        (item_id,),
    )
    db.commit()
    report = manager.get("/api/integrity/stock").json()
    hit = next(r for r in report["items"] if r["item_id"] == item_id)
    assert hit["over_lotted"] >= 5


def test_integrity_report_is_manager_only(member):
    assert member.get("/api/integrity/stock").status_code == 403


def test_reconciling_clears_the_discrepancy(manager, db):
    """set-quantity trims over-lotted stock, so the report stops flagging it."""
    item_id = db.execute(
        "SELECT item_id FROM inventory WHERE status = 'active' LIMIT 1"
    ).fetchone()[0]
    lot_total = _lot_total(db, item_id)
    manager.post(f"/api/items/{item_id}/set-quantity", json={"quantity": lot_total})
    report = manager.get("/api/integrity/stock").json()
    assert not any(r["item_id"] == item_id for r in report["items"])
