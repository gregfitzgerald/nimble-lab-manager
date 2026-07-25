"""Tests for the deferred-feature waves: notifications, chemical-compatibility
checker, requisition + spend-threshold auto-approval, cycle-count reconciliation,
kits/BOM assembly, equipment registry/booking/maintenance, and grant/fund budgets.
"""

import pytest


# --------------------------------------------------------------------------- #
# notifications
# --------------------------------------------------------------------------- #
def test_notifications_sync_and_read(manager):
    data = manager.get("/api/notifications").json()
    assert "unread_count" in data and "notifications" in data
    assert data["unread_count"] >= 1  # seed has low stock / expiring / compatibility
    kinds = {n["kind"] for n in data["notifications"]}
    assert kinds & {"low_stock", "expiring", "compatibility", "approval_pending"}
    # mark one read
    nid = data["notifications"][0]["id"]
    assert manager.post(f"/api/notifications/{nid}/read", json={}).status_code == 200
    # read-all
    r = manager.post("/api/notifications/read-all", json={}).json()
    assert r["ok"] is True


# --------------------------------------------------------------------------- #
# chemical-compatibility checker
# --------------------------------------------------------------------------- #
def test_compatibility_conflicts_seeded(manager):
    conflicts = manager.get("/api/compatibility/conflicts").json()
    assert conflicts, "seed co-locates a flammable + oxidizer pair"
    assert any(c["severity"] == "danger" for c in conflicts)
    pairs = {frozenset((c["hazard_a"], c["hazard_b"])) for c in conflicts}
    assert frozenset(("flammable", "oxidizer")) in pairs


def test_compatibility_rules(member):
    rules = member.get("/api/compatibility/rules").json()
    assert rules and all("severity" in r for r in rules)


# --------------------------------------------------------------------------- #
# requisition + spend-threshold auto-approval
# --------------------------------------------------------------------------- #
def test_member_can_raise_requisition(member):
    r = member.post("/api/purchase-orders", json={
        "vendor": "Sigma", "lines": [{"item_id": 1, "quantity": 1}],
    })
    assert r.status_code == 200
    assert r.json()["status"] == "draft"


def test_threshold_auto_approves_small_po(admin, manager):
    admin.patch("/api/settings", json={"po_approval_threshold": "100000"})
    po = manager.post("/api/purchase-orders", json={
        "vendor": "NEB", "lines": [{"item_id": 1, "quantity": 1}],
    }).json()
    r = manager.patch(f"/api/purchase-orders/{po['id']}", json={"status": "pending_approval"}).json()
    assert r["status"] == "approved"
    assert r.get("auto_approved") is True


def test_threshold_holds_large_po(admin, manager):
    admin.patch("/api/settings", json={"po_approval_threshold": "1"})
    po = manager.post("/api/purchase-orders", json={
        "vendor": "NEB", "lines": [{"item_id": 1, "quantity": 5}],
    }).json()
    r = manager.patch(f"/api/purchase-orders/{po['id']}", json={"status": "pending_approval"}).json()
    assert r["status"] == "pending_approval"


# --------------------------------------------------------------------------- #
# cycle-count reconciliation
# --------------------------------------------------------------------------- #
def test_count_start_scan_close(manager, db):
    box_id = db.execute("SELECT box_id FROM container LIMIT 1").fetchone()[0]
    sess = manager.post("/api/counts", json={"location_id": box_id, "name": "T"}).json()
    sid = sess["id"]
    assert sess["summary"]["expected"] >= 1
    # mark one line found via PATCH
    line = manager.get(f"/api/counts/{sid}").json()["lines"][0]
    manager.patch(f"/api/counts/{sid}/lines/{line['id']}", json={"status": "found"})
    closed = manager.post(f"/api/counts/{sid}/close", json={}).json()
    assert closed["status"] == "closed"
    assert 0.0 <= closed["summary"]["accuracy"] <= 1.0


# --------------------------------------------------------------------------- #
# kits / BOM
# --------------------------------------------------------------------------- #
def test_kit_assemble_consumes_stock(manager, member, db):
    it = next(i for i in manager.get("/api/items").json() if i["quantity_on_hand"] >= 4)
    kit = manager.post("/api/kits", json={
        "name": "Test Recipe", "lines": [{"item_id": it["item_id"], "quantity": 2}],
    }).json()
    before = db.execute("SELECT quantity_on_hand FROM inventory WHERE item_id=?", (it["item_id"],)).fetchone()[0]
    r = member.post(f"/api/kits/{kit['id']}/assemble", json={"count": 2})
    assert r.status_code == 200, r.text
    after = db.execute("SELECT quantity_on_hand FROM inventory WHERE item_id=?", (it["item_id"],)).fetchone()[0]
    assert after == before - 4  # 2 per kit x 2


def test_kit_assemble_insufficient_rejected(manager, member, db):
    it = manager.get("/api/items").json()[0]
    on_hand = it["quantity_on_hand"]
    kit = manager.post("/api/kits", json={
        "name": "Greedy Recipe", "lines": [{"item_id": it["item_id"], "quantity": on_hand + 100}],
    }).json()
    before = db.execute("SELECT quantity_on_hand FROM inventory WHERE item_id=?", (it["item_id"],)).fetchone()[0]
    assert member.post(f"/api/kits/{kit['id']}/assemble", json={"count": 1}).status_code == 400
    after = db.execute("SELECT quantity_on_hand FROM inventory WHERE item_id=?", (it["item_id"],)).fetchone()[0]
    assert after == before  # rolled back


# --------------------------------------------------------------------------- #
# equipment registry / booking / maintenance
# --------------------------------------------------------------------------- #
def test_equipment_booking_overlap_rejected(manager):
    eq = manager.post("/api/equipment", json={"name": "Test Rig"}).json()
    eid = eq["id"]
    b1 = manager.post(f"/api/equipment/{eid}/reservations",
                      json={"starts_at": "2026-08-01 09:00", "ends_at": "2026-08-01 11:00"})
    assert b1.status_code == 200
    # overlapping
    b2 = manager.post(f"/api/equipment/{eid}/reservations",
                      json={"starts_at": "2026-08-01 10:00", "ends_at": "2026-08-01 12:00"})
    assert b2.status_code == 400
    # adjacent (no overlap) ok
    b3 = manager.post(f"/api/equipment/{eid}/reservations",
                      json={"starts_at": "2026-08-01 11:00", "ends_at": "2026-08-01 12:00"})
    assert b3.status_code == 200


def test_equipment_maintenance_advances_service(manager):
    eq = manager.post("/api/equipment", json={
        "name": "Cal Rig", "service_interval_days": 30,
    }).json()
    detail = manager.post(f"/api/equipment/{eq['id']}/maintenance", json={
        "kind": "calibration", "performed_at": "2026-07-01",
    }).json()
    assert detail["last_service_date"] == "2026-07-01"
    assert detail["next_service_date"] == "2026-07-31"  # +30 days


def test_equipment_role_gated(member):
    assert member.post("/api/equipment", json={"name": "X"}).status_code == 403


# --------------------------------------------------------------------------- #
# funds / budget
# --------------------------------------------------------------------------- #
def test_fund_charge_and_budget_math(manager):
    fund = manager.post("/api/funds", json={"name": "T-Fund", "budget": 1000}).json()
    fid = fund["id"]
    manager.post(f"/api/funds/{fid}/charges", json={"amount": 250, "source_type": "manual"})
    d = manager.get(f"/api/funds/{fid}").json()
    assert d["spent"] == 250 and d["remaining"] == 750


def test_fund_charge_po_defaults_to_total(manager):
    # find a received PO (seed has one) or build one
    pos = manager.get("/api/purchase-orders").json()
    received = [p for p in pos if p["status"] == "received"]
    assert received, "seed has a received PO"
    po = received[0]
    fund = manager.post("/api/funds", json={"name": "PO-Fund", "budget": 100000}).json()
    manager.post(f"/api/funds/{fund['id']}/charges",
                 json={"source_type": "purchase_order", "source_id": po["id"]})
    d = manager.get(f"/api/funds/{fund['id']}").json()
    assert d["spent"] == pytest.approx(po["total_cost"], rel=1e-3)


def test_funds_role_gated(member):
    assert member.post("/api/funds", json={"name": "X", "budget": 1}).status_code == 403
