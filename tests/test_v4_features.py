"""Tests for the v4 additions: user management, vendor catalog + add-to-inventory,
substitute groups (backorder fall-through), document attachments, the PO approval
state machine + partial receiving + auto-PO, reorder suggestions, and location
contents. Guards (last-admin/self) and stock math are checked end to end.
"""

# --------------------------------------------------------------------------- #
# user management
# --------------------------------------------------------------------------- #
def test_create_and_list_user(admin):
    r = admin.post("/api/users", json={
        "username": "newtech", "full_name": "New Tech", "role": "member",
        "password": "pw12345",
    })
    assert r.status_code == 200, r.text
    users = {u["username"]: u for u in admin.get("/api/users").json()}
    assert "newtech" in users and users["newtech"]["role"] == "member"
    assert users["newtech"]["is_active"] == 1


def test_create_user_role_gated(manager, member):
    body = {"username": "x", "full_name": "X", "role": "member", "password": "p"}
    assert manager.post("/api/users", json=body).status_code == 403
    assert member.post("/api/users", json=body).status_code == 403


def test_create_user_rejects_dupe_and_bad_role(admin):
    assert admin.post("/api/users", json={
        "username": "admin", "full_name": "Dup", "role": "member", "password": "p"
    }).status_code in (400, 409)
    assert admin.post("/api/users", json={
        "username": "z", "full_name": "Z", "role": "wizard", "password": "p"
    }).status_code == 400


def test_deactivated_user_cannot_log_in(admin, make_client, db):
    admin.post("/api/users", json={
        "username": "temp", "full_name": "Temp", "role": "member", "password": "secret1",
    })
    uid = db.execute("SELECT id FROM app_user WHERE username='temp'").fetchone()["id"]
    assert admin.patch(f"/api/users/{uid}", json={"is_active": False}).status_code == 200
    fresh = make_client()  # anonymous client
    assert fresh.post("/api/login", json={"username": "temp", "password": "secret1"}).status_code == 401


def test_cannot_delete_or_demote_last_admin(admin, db):
    aid = db.execute("SELECT id FROM app_user WHERE username='admin'").fetchone()["id"]
    # only one admin in seed -> both must be refused
    assert admin.delete(f"/api/users/{aid}").status_code == 400
    assert admin.patch(f"/api/users/{aid}", json={"is_active": False}).status_code == 400


def test_password_reset(admin, make_client, db):
    admin.post("/api/users", json={
        "username": "pwuser", "full_name": "PW", "role": "member", "password": "old",
    })
    uid = db.execute("SELECT id FROM app_user WHERE username='pwuser'").fetchone()["id"]
    assert admin.post(f"/api/users/{uid}/password", json={"password": "newpass"}).status_code == 200
    fresh = make_client()
    assert fresh.post("/api/login", json={"username": "pwuser", "password": "newpass"}).status_code == 200


# --------------------------------------------------------------------------- #
# vendor catalog
# --------------------------------------------------------------------------- #
def test_catalog_list_and_detail(member):
    rows = member.get("/api/catalog").json()
    assert rows, "seed has catalog products"
    cid = rows[0]["id"]
    detail = member.get(f"/api/catalog/{cid}").json()
    assert "siblings" in detail and detail["id"] == cid


def test_catalog_add_to_inventory(manager, db):
    cat = manager.get("/api/catalog").json()[0]
    r = manager.post(f"/api/catalog/{cat['id']}/add-to-inventory",
                     json={"quantity": 5, "reorder_threshold": 2})
    assert r.status_code == 200, r.text
    item = r.json()
    assert item["catalog_id"] == cat["id"]
    assert item["quantity_on_hand"] == 5
    # sourced fields copied
    assert item["item_name"] == cat["product_name"]


def test_catalog_add_to_inventory_role_gated(member):
    cid = member.get("/api/catalog").json()[0]["id"]
    assert member.post(f"/api/catalog/{cid}/add-to-inventory", json={}).status_code == 403


# --------------------------------------------------------------------------- #
# substitute groups: preferred = lowest-rank IN-STOCK member (backorder skipped)
# --------------------------------------------------------------------------- #
def test_substitute_preferred_skips_backorder(manager):
    groups = manager.get("/api/substitute-groups").json()
    # seed guarantees at least one group whose rank-1 member is on backorder
    assert groups
    # find a group with a preferred that is in stock
    detail = manager.get(f"/api/substitute-groups/{groups[0]['id']}").json()
    assert "members" in detail
    pref_id = detail.get("preferred_catalog_id")
    if pref_id is not None:
        pref = next(m for m in detail["members"] if m["id"] == pref_id)
        assert pref["availability"] == "in_stock"


def test_substitute_group_crud(manager, member):
    g = manager.post("/api/substitute-groups", json={"name": "Test Equivalents"}).json()
    assert g["id"]
    cid = manager.get("/api/catalog").json()[0]["id"]
    assert manager.post(f"/api/substitute-groups/{g['id']}/members",
                        json={"catalog_id": cid, "preference_rank": 1}).status_code == 200
    detail = manager.get(f"/api/substitute-groups/{g['id']}").json()
    assert any(m["id"] == cid for m in detail["members"])
    # member cannot create
    assert member.post("/api/substitute-groups", json={"name": "Nope"}).status_code == 403
    assert manager.delete(f"/api/substitute-groups/{g['id']}").json() == {"ok": True}


# --------------------------------------------------------------------------- #
# documents
# --------------------------------------------------------------------------- #
def test_document_link_lifecycle(member, manager):
    r = member.post("/api/documents", json={
        "item_id": 1, "kind": "sds", "label": "Test SDS",
        "url": "https://example.com/sds.pdf",
    })
    assert r.status_code == 200, r.text
    doc_id = r.json()["id"]
    docs = member.get("/api/documents", params={"item_id": 1}).json()
    assert any(d["id"] == doc_id for d in docs)
    # surfaced on the item detail
    detail = member.get("/api/items/1").json()
    assert any(d["id"] == doc_id for d in detail.get("documents", []))
    # delete is manager+
    assert member.delete(f"/api/documents/{doc_id}").status_code == 403
    assert manager.delete(f"/api/documents/{doc_id}").status_code == 200


def test_document_requires_one_target(member):
    # no target
    assert member.post("/api/documents", json={"kind": "sds", "url": "x"}).status_code == 400


# --------------------------------------------------------------------------- #
# purchase-order approval state machine
# --------------------------------------------------------------------------- #
def _new_po(manager):
    # qty 6 x $95 = $570, above the $500 auto-approval threshold so the manual
    # approval lifecycle (draft -> pending_approval -> approved -> ...) still runs.
    return manager.post("/api/purchase-orders", json={
        "vendor": "Sigma", "lines": [{"item_id": 1, "quantity": 6}],
    }).json()


def test_po_full_approval_lifecycle(manager, db):
    po = _new_po(manager)
    pid = po["id"]
    assert po["status"] == "draft"
    steps = ["pending_approval", "approved", "submitted", "ordered"]
    for s in steps:
        r = manager.patch(f"/api/purchase-orders/{pid}", json={"status": s})
        assert r.status_code == 200, (s, r.text)
        assert r.json()["status"] == s
    # approved should have stamped an approver
    d = manager.get(f"/api/purchase-orders/{pid}").json()
    assert d["approved_at"] and d["submitted_at"] and d["ordered_at"]
    before = db.execute("SELECT quantity_on_hand FROM inventory WHERE item_id=1").fetchone()[0]
    assert manager.patch(f"/api/purchase-orders/{pid}", json={"status": "received"}).status_code == 200
    after = db.execute("SELECT quantity_on_hand FROM inventory WHERE item_id=1").fetchone()[0]
    assert after == before + 6


def test_po_illegal_transition_rejected(manager):
    po = _new_po(manager)
    # draft -> received directly is forbidden by the approval workflow
    assert manager.patch(f"/api/purchase-orders/{po['id']}", json={"status": "received"}).status_code == 400


def test_po_partial_receive(manager, db):
    po = manager.post("/api/purchase-orders", json={
        "vendor": "NEB", "lines": [{"item_id": 1, "quantity": 10}],
    }).json()
    pid = po["id"]
    for s in ["pending_approval", "approved", "submitted", "ordered"]:
        manager.patch(f"/api/purchase-orders/{pid}", json={"status": s})
    line_id = manager.get(f"/api/purchase-orders/{pid}").json()["lines"][0]["id"]
    before = db.execute("SELECT quantity_on_hand FROM inventory WHERE item_id=1").fetchone()[0]
    r = manager.post(f"/api/purchase-orders/{pid}/receive",
                     json={"receipts": [{"line_id": line_id, "qty": 4}]})
    assert r.status_code == 200, r.text
    after = db.execute("SELECT quantity_on_hand FROM inventory WHERE item_id=1").fetchone()[0]
    assert after == before + 4
    # still not fully received -> status remains ordered
    assert manager.get(f"/api/purchase-orders/{pid}").json()["status"] == "ordered"


def test_po_auto_from_low_stock(manager, db):
    # force an item below its reorder point
    db.execute("UPDATE inventory SET quantity_on_hand = 0, reorder_threshold = 5, reorder_max = 10 WHERE item_id = 1")
    db.commit()
    r = manager.post("/api/purchase-orders/auto", json={})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body.get("created") is True
    assert body["po"]["status"] == "draft"
    assert any(ln["item_id"] == 1 for ln in body["po"]["lines"])


# --------------------------------------------------------------------------- #
# reorder suggestions + location contents
# --------------------------------------------------------------------------- #
def test_reorder_suggestions(manager, db):
    db.execute("UPDATE inventory SET quantity_on_hand = 0, reorder_threshold = 3 WHERE item_id = 1")
    db.commit()
    rows = manager.get("/api/reorder/suggestions").json()
    assert any(r["item_id"] == 1 and r["suggested_qty"] > 0 for r in rows)


def test_location_contents(manager, db):
    box_id = db.execute("SELECT box_id FROM container LIMIT 1").fetchone()[0]
    data = manager.get(f"/api/locations/{box_id}/contents").json()
    assert data["node"]["id"] == box_id
    assert isinstance(data["containers"], list) and data["containers"]
    assert "item_name" in data["containers"][0]
