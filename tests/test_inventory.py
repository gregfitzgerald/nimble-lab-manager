"""Inventory list/detail, restock, and consume behavior on the seeded DB.

Seed facts used here (from seed.sql):
- item 3  (4% Paraformaldehyde): lots expiring 2026-06-15 (qty 2) and
  2026-09-30 (qty 4). The 06-15 lot is permanently in the past, so the
  item-level expiry_flag is 'expired' whenever the suite runs.
- item 4  (Anti-GABA antibody): quantity_on_hand 0, threshold 1, no lots.
- item 5  (Microscope slides): one lot with NULL expiry -> flag 'none'.
- item 7  (DMEM): two lots and several containers in Box A1.
- item 15 (PBS 10x): quantity_on_hand 10 backed by a single 10-unit lot.
"""

VALID_FLAGS = {"ok", "expiring", "expired", "none"}


def _on_hand(db, item_id):
    return db.execute(
        "SELECT quantity_on_hand FROM inventory WHERE item_id = ?", (item_id,)
    ).fetchone()[0]


def _lot_sum(db, item_id):
    return db.execute(
        "SELECT COALESCE(SUM(quantity), 0) FROM item_lot WHERE item_id = ?",
        (item_id,),
    ).fetchone()[0]


# --------------------------------------------------------------------------- #
# list + detail shapes
# --------------------------------------------------------------------------- #
def test_items_list_shape_and_flags(viewer):
    # include_deprecated so all 21 seeded items are present (item 4 is a
    # deprecated soft-delete demo and is hidden from the default list).
    rows = viewer.get("/api/items?include_deprecated=true").json()
    assert len(rows) == 21  # seed.sql inserts 6 + 12 lab items + 3 office items
    by_id = {r["item_id"]: r for r in rows}
    for r in rows:
        for key in (
            "item_id", "item_name", "vendor", "unit", "quantity_on_hand",
            "reorder_threshold", "unit_cost", "nearest_expiry",
            "is_low_stock", "expiry_flag",
        ):
            assert key in r, f"missing {key} in items row"
        assert r["expiry_flag"] in VALID_FLAGS
        assert r["is_low_stock"] == (
            r["quantity_on_hand"] <= r["reorder_threshold"]
        )
    # deterministic flag cases
    assert by_id[3]["expiry_flag"] == "expired"
    assert by_id[5]["expiry_flag"] == "none"
    assert by_id[4]["expiry_flag"] == "none"  # zero on hand, no lots
    assert by_id[4]["is_low_stock"] is True


def test_item_detail_has_lots_and_located_containers(viewer):
    resp = viewer.get("/api/items/7")
    assert resp.status_code == 200
    data = resp.json()
    assert data["item"]["item_id"] == 7
    assert data["item"]["item_name"] == "DMEM High Glucose"

    lots = data["lots"]
    assert {ln["lot_number"] for ln in lots} == {"DMEM-2606", "DMEM-2612"}
    assert all(ln["item_id"] == 7 for ln in lots)
    # ordered by expiry (nulls last)
    dates = [ln["expiry_date"] for ln in lots]
    assert dates == sorted(dates)

    containers = data["containers"]
    assert containers, "DMEM has containers in seed.sql"
    for c in containers:
        assert c["location_path"], "every container should resolve a path"
        assert "Box A1" in c["location_path"]
        assert c["location_path"].startswith("Room 201")


def test_item_detail_404(viewer):
    assert viewer.get("/api/items/99999").status_code == 404


# --------------------------------------------------------------------------- #
# restock
# --------------------------------------------------------------------------- #
def test_restock_creates_lot_and_increments(member, db):
    before = _on_hand(db, 4)
    assert before == 0
    resp = member.post(
        "/api/items/4/restock",
        json={"quantity": 5, "lot_number": "GABA-TEST", "expiry_date": "2030-01-01"},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["quantity_on_hand"] == 5
    lot_id = body["lot_id"]

    lot = db.execute("SELECT * FROM item_lot WHERE id = ?", (lot_id,)).fetchone()
    assert lot["item_id"] == 4
    assert lot["lot_number"] == "GABA-TEST"
    assert lot["quantity"] == 5
    assert _on_hand(db, 4) == _lot_sum(db, 4) == 5

    # restocking the same lot_number tops up the existing lot, no new row
    resp2 = member.post(
        "/api/items/4/restock", json={"quantity": 2, "lot_number": "GABA-TEST"}
    )
    assert resp2.status_code == 200
    assert resp2.json()["lot_id"] == lot_id
    assert resp2.json()["quantity_on_hand"] == 7
    lot_count = db.execute(
        "SELECT COUNT(*) FROM item_lot WHERE item_id = 4"
    ).fetchone()[0]
    assert lot_count == 1
    assert _on_hand(db, 4) == _lot_sum(db, 4) == 7

    # both restocks were logged
    events = db.execute(
        "SELECT quantity FROM usage_event WHERE item_id = 4 AND event_type = 'restock'"
    ).fetchall()
    assert sorted(e["quantity"] for e in events) == [2, 5]


def test_restock_rejects_nonpositive_quantity(member):
    assert member.post("/api/items/15/restock", json={"quantity": 0}).status_code == 400
    assert member.post("/api/items/15/restock", json={"quantity": -3}).status_code == 400


def test_restock_unknown_item_404(member):
    assert member.post("/api/items/99999/restock", json={"quantity": 1}).status_code == 404


# --------------------------------------------------------------------------- #
# consume
# --------------------------------------------------------------------------- #
def test_consume_decrements_and_logs_event(member, db):
    assert _on_hand(db, 15) == 10
    resp = member.post("/api/items/15/consume", json={"quantity": 4, "note": "assay"})
    assert resp.status_code == 200
    assert resp.json()["quantity_on_hand"] == 6
    assert _on_hand(db, 15) == 6
    # lots stay in sync with on-hand
    assert _lot_sum(db, 15) == 6
    row = db.execute(
        """SELECT quantity, note FROM usage_event
           WHERE item_id = 15 AND event_type = 'consume'
           ORDER BY id DESC LIMIT 1"""
    ).fetchone()
    assert row["quantity"] == 4
    assert row["note"] == "assay"


def test_consume_beyond_stock_is_400_and_no_change(member, db):
    before = _on_hand(db, 15)
    resp = member.post("/api/items/15/consume", json={"quantity": before + 1})
    assert resp.status_code == 400
    assert _on_hand(db, 15) == before
    assert _lot_sum(db, 15) == before


def test_consume_rejects_nonpositive_quantity(member):
    assert member.post("/api/items/15/consume", json={"quantity": 0}).status_code == 400
    assert member.post("/api/items/15/consume", json={"quantity": -1}).status_code == 400


def test_consume_unknown_item_404(member):
    assert member.post("/api/items/99999/consume", json={"quantity": 1}).status_code == 404


def test_on_hand_never_goes_below_zero(member, db):
    # drain item 15 exactly to zero, then verify the floor holds
    assert member.post("/api/items/15/consume", json={"quantity": 10}).status_code == 200
    assert _on_hand(db, 15) == 0
    assert _lot_sum(db, 15) == 0
    assert member.post("/api/items/15/consume", json={"quantity": 1}).status_code == 400
    assert _on_hand(db, 15) == 0


def test_consume_drains_lots_first_expiry_first(member, db):
    # item 3: lot 3 (2026-06-15, qty 2) expires before lot 4 (2026-09-30, qty 4)
    resp = member.post("/api/items/3/consume", json={"quantity": 3})
    assert resp.status_code == 200
    lots = {
        r["lot_number"]: r["quantity"]
        for r in db.execute(
            "SELECT lot_number, quantity FROM item_lot WHERE item_id = 3"
        ).fetchall()
    }
    assert lots["PFA-2405"] == 0  # earliest expiry emptied first
    assert lots["PFA-2509"] == 3  # remainder taken from the later lot
