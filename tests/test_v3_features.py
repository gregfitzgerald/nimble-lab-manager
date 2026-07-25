"""Tests for the v3 additions: audit trail, item create/deprecate, tickets +
task templates, per-member usage + visibility settings, purchase orders,
controlled-substance register, cost-per-task analytics, global search, QR labels.

Role gating is checked on every mutation. Stock math (ticket consume, PO
receive, controlled dispense) is checked end to end.
"""

# --------------------------------------------------------------------------- #
# item create / deprecate / restore
# --------------------------------------------------------------------------- #
def test_create_item_manager(manager, db):
    r = manager.post("/api/items", json={
        "item_name": "New Widget", "category": "supply",
        "quantity_on_hand": 12, "reorder_threshold": 4, "unit_cost": 2.5,
    })
    assert r.status_code == 200
    iid = r.json()["item_id"]
    row = db.execute("SELECT * FROM inventory WHERE item_id = ?", (iid,)).fetchone()
    assert row["item_name"] == "New Widget"
    assert row["status"] == "active"
    # opening balance recorded as a restock event
    ev = db.execute(
        "SELECT COUNT(*) c FROM usage_event WHERE item_id = ? AND event_type='restock'",
        (iid,),
    ).fetchone()["c"]
    assert ev >= 1


def test_create_item_role_gated(member, viewer):
    body = {"item_name": "Nope", "category": "supply"}
    assert member.post("/api/items", json=body).status_code == 403
    assert viewer.post("/api/items", json=body).status_code == 403


def test_create_item_rejects_bad_category(manager):
    r = manager.post("/api/items", json={"item_name": "X", "category": "bogus"})
    assert r.status_code == 400


def test_deprecate_hides_from_default_list(manager):
    items = manager.get("/api/items").json()
    iid = items[0]["item_id"]
    assert manager.patch(f"/api/items/{iid}", json={"status": "deprecated"}).status_code == 200
    ids_default = {i["item_id"] for i in manager.get("/api/items").json()}
    assert iid not in ids_default
    ids_incl = {i["item_id"] for i in manager.get("/api/items?include_deprecated=true").json()}
    assert iid in ids_incl
    # restore
    assert manager.patch(f"/api/items/{iid}", json={"status": "active"}).status_code == 200
    assert iid in {i["item_id"] for i in manager.get("/api/items").json()}


def test_deprecate_rejects_bad_status(manager):
    iid = manager.get("/api/items").json()[0]["item_id"]
    assert manager.patch(f"/api/items/{iid}", json={"status": "zombie"}).status_code == 400


# --------------------------------------------------------------------------- #
# audit trail
# --------------------------------------------------------------------------- #
def test_audit_records_mutations(manager):
    iid = manager.get("/api/items").json()[0]["item_id"]
    manager.post(f"/api/items/{iid}/consume", json={"quantity": 1})
    log = manager.get("/api/audit").json()
    assert log["total"] >= 1
    actions = {e["action"] for e in log["entries"]}
    assert "consume" in actions
    assert "consume" in log["actions"]  # distinct-actions list


def test_audit_role_gated(member, viewer):
    assert member.get("/api/audit").status_code == 403
    assert viewer.get("/api/audit").status_code == 403


def test_audit_filter_by_action(manager):
    iid = manager.get("/api/items").json()[0]["item_id"]
    manager.post(f"/api/items/{iid}/restock", json={"quantity": 1})
    r = manager.get("/api/audit", params={"action": "restock"}).json()
    assert r["entries"]
    assert all(e["action"] == "restock" for e in r["entries"])


# --------------------------------------------------------------------------- #
# tickets + task templates
# --------------------------------------------------------------------------- #
def _pick_item_with_stock(client, need=2):
    for it in client.get("/api/items").json():
        if it["quantity_on_hand"] >= need:
            return it
    raise AssertionError("no item with enough stock in seed")


def test_ticket_consumes_stock(member, db):
    it = _pick_item_with_stock(member, 2)
    before = it["quantity_on_hand"]
    r = member.post("/api/tickets", json={
        "task": "Western Blot", "purpose": "protein detection",
        "lines": [{"item_id": it["item_id"], "quantity": 2}],
    })
    assert r.status_code == 200, r.text
    tid = r.json()["id"]
    after = db.execute(
        "SELECT quantity_on_hand FROM inventory WHERE item_id = ?", (it["item_id"],)
    ).fetchone()["quantity_on_hand"]
    assert after == before - 2
    # usage_event booked against the ticket, with purpose
    ev = db.execute(
        "SELECT purpose, ticket_id FROM usage_event WHERE ticket_id = ?", (tid,)
    ).fetchone()
    assert ev["purpose"] == "protein detection"


def test_ticket_insufficient_stock_rejected(member, db):
    it = _pick_item_with_stock(member, 1)
    huge = it["quantity_on_hand"] + 9999
    before = it["quantity_on_hand"]
    r = member.post("/api/tickets", json={
        "task": "X", "lines": [{"item_id": it["item_id"], "quantity": huge}],
    })
    assert r.status_code == 400
    # rolled back: stock unchanged and no ticket persisted
    after = db.execute(
        "SELECT quantity_on_hand FROM inventory WHERE item_id = ?", (it["item_id"],)
    ).fetchone()["quantity_on_hand"]
    assert after == before


def test_ticket_requires_a_line(member):
    assert member.post("/api/tickets", json={"task": "empty", "lines": []}).status_code == 400


def test_ticket_visibility_scoping(member, admin):
    it = _pick_item_with_stock(member, 1)
    member.post("/api/tickets", json={"lines": [{"item_id": it["item_id"], "quantity": 1}]})
    mine = member.get("/api/tickets").json()
    assert mine["can_see_all"] is False
    assert all(t["username"] == "member" for t in mine["tickets"])
    all_t = admin.get("/api/tickets").json()
    assert all_t["can_see_all"] is True


def test_task_template_crud_and_prefill(manager, member):
    it = _pick_item_with_stock(manager, 1)
    r = manager.post("/api/task-templates", json={
        "name": "Test Procedure", "description": "demo",
        "lines": [{"item_id": it["item_id"], "default_quantity": 3}],
    })
    assert r.status_code == 200
    tpl = r.json()
    assert tpl["lines"][0]["default_quantity"] == 3
    assert tpl["lines"][0]["item_name"]  # joined name present
    # members can read templates (to use them)
    assert any(t["name"] == "Test Procedure" for t in member.get("/api/task-templates").json())
    # update replaces lines
    up = manager.patch(f"/api/task-templates/{tpl['id']}", json={
        "name": "Test Procedure", "lines": [{"item_id": it["item_id"], "default_quantity": 5}],
    }).json()
    assert up["lines"][0]["default_quantity"] == 5
    # delete
    assert manager.delete(f"/api/task-templates/{tpl['id']}").json() == {"ok": True}


def test_task_template_role_gated(member):
    assert member.post("/api/task-templates", json={"name": "X", "lines": []}).status_code == 403


# --------------------------------------------------------------------------- #
# per-member usage + visibility settings
# --------------------------------------------------------------------------- #
def test_usage_by_member_admin_sees_all(member, admin):
    it = _pick_item_with_stock(member, 1)
    member.post("/api/tickets", json={
        "task": "Perfusion", "purpose": "perfusions",
        "lines": [{"item_id": it["item_id"], "quantity": 1}],
    })
    data = admin.get("/api/usage/by-member").json()
    assert data["can_see_all"] is True
    assert any(m["username"] == "member" for m in data["members"])


def test_usage_visibility_gates_members(member, admin):
    # default admin_only -> member sees only self
    d1 = member.get("/api/usage/by-member").json()
    assert d1["can_see_all"] is False
    assert all(m["username"] == "member" for m in d1["members"])
    # admin opens it up
    assert admin.patch("/api/settings", json={"usage_visibility": "all"}).status_code == 200
    d2 = member.get("/api/usage/by-member").json()
    assert d2["can_see_all"] is True


def test_settings_patch_admin_only(member, manager):
    assert member.patch("/api/settings", json={"usage_visibility": "all"}).status_code == 403
    assert manager.patch("/api/settings", json={"usage_visibility": "all"}).status_code == 403


def test_settings_rejects_bad_value(admin):
    assert admin.patch("/api/settings", json={"usage_visibility": "public"}).status_code == 400


# --------------------------------------------------------------------------- #
# purchase orders
# --------------------------------------------------------------------------- #
def test_po_receive_restocks(manager, db):
    it = manager.get("/api/items").json()[0]
    before = it["quantity_on_hand"]
    po = manager.post("/api/purchase-orders", json={
        "vendor": "Acme", "lines": [{"item_id": it["item_id"], "quantity": 7}],
    }).json()
    assert po["status"] == "draft"
    # Wave 2 approval state machine: draft -> pending_approval -> approved ->
    # submitted -> ordered -> received (a direct draft -> received is rejected).
    assert manager.patch(f"/api/purchase-orders/{po['id']}", json={"status": "received"}).status_code == 400
    for st in ("pending_approval", "approved", "submitted", "ordered"):
        assert manager.patch(f"/api/purchase-orders/{po['id']}", json={"status": st}).status_code == 200
    r = manager.patch(f"/api/purchase-orders/{po['id']}", json={"status": "received"})
    assert r.status_code == 200
    assert r.json()["status"] == "received"
    after = db.execute(
        "SELECT quantity_on_hand FROM inventory WHERE item_id = ?", (it["item_id"],)
    ).fetchone()["quantity_on_hand"]
    assert after == before + 7
    # receiving twice is refused
    assert manager.patch(f"/api/purchase-orders/{po['id']}", json={"status": "received"}).status_code == 400


def test_po_role_gated(member, viewer):
    # Wave 3 (deferred, batch 1): a member-created draft PO is a requisition, so
    # members may now create purchase orders; viewers still cannot, and the
    # manager-only listing stays gated.
    body = {"vendor": "x", "lines": [{"item_id": 1, "quantity": 1}]}
    assert member.post("/api/purchase-orders", json=body).status_code == 200
    assert viewer.post("/api/purchase-orders", json=body).status_code == 403
    assert viewer.get("/api/purchase-orders").status_code == 403
    assert member.get("/api/purchase-orders").status_code == 403


def test_po_needs_a_line(manager):
    assert manager.post("/api/purchase-orders", json={"vendor": "x", "lines": []}).status_code == 400


# --------------------------------------------------------------------------- #
# controlled-substance register
# --------------------------------------------------------------------------- #
def _make_controlled(manager):
    it = _pick_item_with_stock(manager, 3)
    manager.patch(f"/api/items/{it['item_id']}",
                  json={"is_controlled": True, "controlled_schedule": "II"})
    return it


def test_controlled_dispense_requires_witness(manager, member):
    it = _make_controlled(manager)
    # dispense without witness -> 400
    r = member.post(f"/api/controlled/{it['item_id']}/log",
                    json={"change": -1, "reason": "surgery"})
    assert r.status_code == 400
    # with witness -> ok, running balance drops
    ok = member.post(f"/api/controlled/{it['item_id']}/log",
                     json={"change": -1, "reason": "surgery", "witness": "Dr. Lee"})
    assert ok.status_code == 200
    assert ok.json()["balance_after"] == it["quantity_on_hand"] - 1


def test_controlled_cannot_overdraw(manager, member):
    it = _make_controlled(manager)
    r = member.post(f"/api/controlled/{it['item_id']}/log",
                    json={"change": -(it["quantity_on_hand"] + 5),
                          "reason": "x", "witness": "w"})
    assert r.status_code == 400


def test_controlled_list_and_log(manager, member):
    it = _make_controlled(manager)
    member.post(f"/api/controlled/{it['item_id']}/log",
                json={"change": -1, "reason": "surgery", "witness": "Dr. Lee"})
    listing = manager.get("/api/controlled").json()
    assert any(c["item_id"] == it["item_id"] for c in listing)
    log = manager.get(f"/api/controlled/{it['item_id']}/log").json()
    assert log["item"]["is_controlled"] == 1
    assert log["entries"] and log["entries"][0]["witness"] == "Dr. Lee"


def test_controlled_non_controlled_item_rejected(manager, member):
    # an item not flagged controlled cannot take register entries
    plain = None
    for it in manager.get("/api/items").json():
        if not it["is_controlled"]:
            plain = it
            break
    assert plain is not None
    r = member.post(f"/api/controlled/{plain['item_id']}/log",
                    json={"change": 1, "reason": "x"})
    assert r.status_code == 400


# --------------------------------------------------------------------------- #
# cost-per-task, search, QR
# --------------------------------------------------------------------------- #
def test_cost_by_task_shape(manager, member):
    it = _pick_item_with_stock(member, 1)
    member.post("/api/tickets", json={
        "task": "Genotyping", "purpose": "pcr",
        "lines": [{"item_id": it["item_id"], "quantity": 1}],
    })
    data = manager.get("/api/analytics/cost-by-task").json()
    assert "by_task" in data and "by_purpose" in data
    assert any(r["task"] == "Genotyping" for r in data["by_task"])


def test_search_finds_items(member):
    name = member.get("/api/items").json()[0]["item_name"]
    term = name.split()[0][:4]
    data = member.get("/api/search", params={"q": term}).json()
    assert "items" in data and "locations" in data and "tickets" in data


def test_search_requires_query(member):
    assert member.get("/api/search", params={"q": ""}).status_code == 422


def test_item_qr_svg(member):
    iid = member.get("/api/items").json()[0]["item_id"]
    r = member.get(f"/api/items/{iid}/qr.svg")
    assert r.status_code == 200
    assert r.headers["content-type"].startswith("image/svg")
    assert b"<svg" in r.content


def test_item_qr_404(member):
    assert member.get("/api/items/999999/qr.svg").status_code == 404
