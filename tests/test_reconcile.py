"""Stock reconciliation: POST /items/{id}/set-quantity.

The action a physical count produces -- "the shelf has 7, make it 7" -- in one
audited step, rather than faking the difference as consumption.
"""


def _on_hand(db, item_id=1):
    return db.execute(
        "SELECT quantity_on_hand FROM inventory WHERE item_id = ?", (item_id,)
    ).fetchone()[0]


def _lot_total(db, item_id=1):
    return db.execute(
        "SELECT COALESCE(SUM(quantity), 0) FROM item_lot WHERE item_id = ?", (item_id,)
    ).fetchone()[0]


def test_set_quantity_down_records_negative_delta(member, db):
    before = _on_hand(db)
    target = max(before - 3, 0)
    r = member.post("/api/items/1/set-quantity",
                    json={"quantity": target, "reason": "annual count"})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["previous"] == before
    assert body["quantity_on_hand"] == target
    assert body["delta"] == target - before
    assert _on_hand(db) == target


def test_set_quantity_up_is_allowed(member, db):
    before = _on_hand(db)
    r = member.post("/api/items/1/set-quantity", json={"quantity": before + 5})
    assert r.status_code == 200
    assert _on_hand(db) == before + 5
    assert r.json()["delta"] == 5


def test_adjustment_is_recorded_as_adjust_event(member, db):
    member.post("/api/items/1/set-quantity",
                json={"quantity": 2, "reason": "recount"})
    row = db.execute(
        """SELECT event_type, quantity, note FROM usage_event
            WHERE item_id = 1 ORDER BY id DESC LIMIT 1"""
    ).fetchone()
    assert row["event_type"] == "adjust"
    assert row["note"] == "recount"


def test_adjustment_excluded_from_consumption_analytics(member, db):
    """A recount must never look like usage."""
    before = member.get("/api/analytics/usage").json()
    member.post("/api/items/1/set-quantity", json={"quantity": 1})
    after = member.get("/api/analytics/usage").json()
    assert after == before


def test_lots_trimmed_when_count_is_below_lot_total(member, db):
    total = _lot_total(db)
    if total <= 1:
        # seed guarantees lots on item 1; guard keeps the test honest if not
        return
    target = total - 1
    r = member.post("/api/items/1/set-quantity", json={"quantity": target})
    assert r.status_code == 200
    assert r.json()["lots_trimmed"] >= 1
    # lots no longer over-state physical stock (which is what drives expiry alerts)
    assert _lot_total(db) <= target


def test_count_above_lot_total_reports_untracked(member, db):
    total = _lot_total(db)
    r = member.post("/api/items/1/set-quantity", json={"quantity": total + 4})
    assert r.status_code == 200
    body = r.json()
    assert body["lots_trimmed"] == 0
    assert body["untracked_by_lot"] >= 4


def test_set_quantity_rejects_negative(member):
    assert member.post("/api/items/1/set-quantity",
                       json={"quantity": -1}).status_code == 400


def test_set_quantity_404_for_unknown_item(member):
    assert member.post("/api/items/999999/set-quantity",
                       json={"quantity": 1}).status_code == 404


def test_set_quantity_requires_member(viewer):
    assert viewer.post("/api/items/1/set-quantity",
                       json={"quantity": 1}).status_code == 403


def test_set_quantity_is_audited(member, db):
    member.post("/api/items/1/set-quantity", json={"quantity": 3})
    row = db.execute(
        """SELECT action, detail FROM audit_log
            WHERE entity_type = 'inventory' AND entity_id = 1
            ORDER BY id DESC LIMIT 1"""
    ).fetchone()
    assert row["action"] == "item.set_quantity"
    assert "-> 3" in row["detail"]
