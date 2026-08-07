"""POST /api/scan/resolve -- turn a scanned code into an item.

The client should never have to know the code formats, so the server accepts
any of them: the QR deep link the printed labels encode, a bare item id, or a
vendor catalog number.
"""


def test_resolves_qr_deep_link(member, db):
    item = db.execute(
        "SELECT item_id, item_name FROM inventory LIMIT 1"
    ).fetchone()
    r = member.post("/api/scan/resolve",
                    json={"code": f"http://localhost:8770/?item={item['item_id']}"})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["matched"] is True
    assert body["item"]["item_id"] == item["item_id"]
    assert body["item"]["item_name"] == item["item_name"]


def test_resolves_bare_item_id(member, db):
    item_id = db.execute("SELECT item_id FROM inventory LIMIT 1").fetchone()[0]
    body = member.post("/api/scan/resolve", json={"code": str(item_id)}).json()
    assert body["matched"] is True and body["item"]["item_id"] == item_id


def test_resolves_vendor_catalog_number(member, db):
    row = db.execute(
        """SELECT i.item_id, vc.catalog_number
             FROM inventory i JOIN vendor_catalog vc ON vc.id = i.catalog_id
            WHERE vc.catalog_number IS NOT NULL AND vc.catalog_number <> ''
            LIMIT 1"""
    ).fetchone()
    assert row is not None, "seed should link an item to a catalog product"
    body = member.post("/api/scan/resolve",
                       json={"code": row["catalog_number"]}).json()
    assert body["matched"] is True
    assert body["item"]["item_id"] == row["item_id"]


def test_unknown_code_reports_no_match(member):
    body = member.post("/api/scan/resolve", json={"code": "NOT-A-REAL-CODE"}).json()
    assert body["matched"] is False
    assert body["item"] is None


def test_empty_code_reports_no_match(member):
    assert member.post("/api/scan/resolve", json={"code": ""}).json()["matched"] is False


def test_scan_resolve_requires_login(client):
    assert client.post("/api/scan/resolve", json={"code": "1"}).status_code == 401


def test_camera_is_permitted_by_policy(member):
    """Permissions-Policy must not block the camera, or scanning cannot start."""
    resp = member.get("/api/items")
    policy = resp.headers.get("Permissions-Policy", "")
    assert "camera=(self)" in policy
    # the others stay locked down
    assert "microphone=()" in policy and "geolocation=()" in policy
