"""Tests for the v2 additions: item category + SDS/CoA links, and real
floor-plan images + portable layout import/export.

These cover the schema fields (inventory.category, inventory.sds_url,
item_lot.coa_url), the category filter + /api/categories, the manager-only
PATCH /api/items, floor image upload/serve/delete, and the /api/layout
export -> import round trip, including role gating on every mutation.
"""

import base64
import os

import pytest

import app.db as appdb

# Floor images are written to <repo>/web/uploads/floors, which the temp-DB
# fixture does NOT isolate. Snapshot that directory and delete anything these
# tests create so the suite never leaves files in the repo.
_UPLOAD_DIR = os.path.join(appdb.ROOT_DIR, "web", "uploads", "floors")


@pytest.fixture(autouse=True)
def _clean_uploads():
    before = set(os.listdir(_UPLOAD_DIR)) if os.path.isdir(_UPLOAD_DIR) else set()
    yield
    if os.path.isdir(_UPLOAD_DIR):
        for name in set(os.listdir(_UPLOAD_DIR)) - before:
            try:
                os.remove(os.path.join(_UPLOAD_DIR, name))
            except OSError:
                pass


# A 4x4 red PNG (smallest valid image we can upload).
_PNG_4x4 = base64.b64decode(
    "iVBORw0KGgoAAAANSUhEUgAAAAQAAAAECAYAAACp8Z5+AAAAEUlEQVR42mNk"
    "+M9QzwAEjDAaADr4A/8Y0i2iAAAAAElFTkSuQmCC"
)

_ALLOWED_CATEGORIES = {
    "reagent", "supply", "chemical", "antibody", "enzyme",
    "media", "animal", "equipment", "office", "other",
}


# --------------------------------------------------------------------------- #
# item classification + SDS / CoA
# --------------------------------------------------------------------------- #
def test_items_carry_category_and_sds(manager):
    items = manager.get("/api/items").json()
    assert items, "seed should have items"
    for it in items:
        assert "category" in it and it["category"] in _ALLOWED_CATEGORIES
        assert "sds_url" in it  # nullable, but the key must be present


def test_category_filter(manager):
    chem = manager.get("/api/items", params={"category": "chemical"}).json()
    assert chem, "seed has chemical items"
    assert all(it["category"] == "chemical" for it in chem)


def test_categories_endpoint_counts_all_items(manager):
    payload = manager.get("/api/categories").json()
    cats = payload["categories"]
    names = {c["name"] for c in cats}
    assert _ALLOWED_CATEGORIES.issubset(names)  # zero-count categories included
    total = sum(c["count"] for c in cats)
    n_items = len(manager.get("/api/items").json())
    assert total == n_items


def test_item_detail_lots_have_coa_url(manager):
    detail = manager.get("/api/items/1").json()
    assert detail["item"]["category"] in _ALLOWED_CATEGORIES
    assert "sds_url" in detail["item"]
    for lot in detail["lots"]:
        assert "coa_url" in lot  # nullable, key present


def test_patch_item_updates_category_and_sds(manager, db):
    r = manager.patch(
        "/api/items/1",
        json={"category": "reagent", "sds_url": "https://example.com/sds/x.pdf"},
    )
    assert r.status_code == 200
    row = db.execute(
        "SELECT category, sds_url FROM inventory WHERE item_id = 1"
    ).fetchone()
    assert row["category"] == "reagent"
    assert row["sds_url"] == "https://example.com/sds/x.pdf"


def test_patch_item_rejects_unknown_category(manager):
    r = manager.patch("/api/items/1", json={"category": "not-a-category"})
    assert r.status_code == 400


def test_patch_item_role_gated(viewer, member):
    assert viewer.patch("/api/items/1", json={"category": "reagent"}).status_code == 403
    assert member.patch("/api/items/1", json={"category": "reagent"}).status_code == 403


def test_restock_stores_coa_url(manager, db):
    r = manager.post(
        "/api/items/1/restock",
        json={"quantity": 2, "lot_number": "LOT-COA-1",
              "coa_url": "https://example.com/coa/lot-coa-1.pdf"},
    )
    assert r.status_code == 200
    row = db.execute(
        "SELECT coa_url FROM item_lot WHERE lot_number = 'LOT-COA-1'"
    ).fetchone()
    assert row["coa_url"] == "https://example.com/coa/lot-coa-1.pdf"


# --------------------------------------------------------------------------- #
# floors: real floor-plan images
# --------------------------------------------------------------------------- #
def test_floors_expose_image_fields(manager):
    floors = manager.get("/api/floors").json()
    assert floors
    f = floors[0]
    for key in ("floor_id", "name", "image_url", "image_width", "image_height", "units"):
        assert key in f
    assert f["image_url"] is None  # seed ships a schematic floor, no image


def _create_floor_with_image(manager):
    fid = manager.post("/api/floors", json={"name": "Blueprint"}).json()["floor_id"]
    r = manager.post(
        f"/api/floors/{fid}/image",
        files={"file": ("plan.png", _PNG_4x4, "image/png")},
        data={"width": "4", "height": "4"},
    )
    return fid, r


def test_floor_image_upload_and_serve(manager):
    fid, r = _create_floor_with_image(manager)
    assert r.status_code == 200
    body = r.json()
    assert body["image_url"] and body["image_url"].startswith("/uploads/floors/")
    assert body["image_width"] == 4 and body["image_height"] == 4
    served = manager.get(body["image_url"])
    assert served.status_code == 200
    assert served.headers["content-type"].startswith("image/")
    assert served.content == _PNG_4x4


def test_floor_image_rejects_bad_extension(manager):
    fid = manager.post("/api/floors", json={"name": "Bad"}).json()["floor_id"]
    r = manager.post(
        f"/api/floors/{fid}/image",
        files={"file": ("evil.exe", b"MZ", "application/octet-stream")},
        data={"width": "4", "height": "4"},
    )
    assert r.status_code == 400


def test_floor_image_role_gated(viewer):
    # viewer cannot even create a floor, let alone upload
    assert viewer.post("/api/floors", json={"name": "X"}).status_code == 403


def test_floor_image_delete(manager):
    fid, _ = _create_floor_with_image(manager)
    assert manager.delete(f"/api/floors/{fid}/image").json() == {"ok": True}
    floors = {f["floor_id"]: f for f in manager.get("/api/floors").json()}
    assert floors[fid]["image_url"] is None


# --------------------------------------------------------------------------- #
# portable layout export / import
# --------------------------------------------------------------------------- #
def test_layout_export_shape(manager):
    layout = manager.get("/api/layout").json()
    assert "floors" in layout and "locations" in layout
    assert layout["locations"], "seed has locations"


def test_layout_roundtrip(manager):
    layout = manager.get("/api/layout").json()
    r = manager.post("/api/layout", json=layout)
    assert r.status_code == 200
    body = r.json()
    assert body["ok"] is True
    assert body["counts"]["locations"] == len(layout["locations"])


def test_layout_import_role_gated(viewer, member, manager):
    layout = manager.get("/api/layout").json()
    assert viewer.post("/api/layout", json=layout).status_code == 403
    assert member.post("/api/layout", json=layout).status_code == 403


def test_layout_import_rejects_unknown_kind(manager):
    bad = {"locations": [{"id": 99999, "parent_id": None, "kind": "wormhole",
                          "name": "Nope"}]}
    assert manager.post("/api/layout", json=bad).status_code == 400
