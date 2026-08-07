"""CSV import must identify items by a stable key, not the product name.

Matching on name alone duplicates rows or merges distinct reagents that happen
to share a name. Precedence: catalog_number -> item_id -> item_name.
"""

import io


def _upload(client, text, dry_run=False):
    return client.post(
        "/api/import/inventory",
        files={"file": ("import.csv", io.BytesIO(text.encode()), "text/csv")},
        data={"dry_run": "true" if dry_run else "false"},
    )


def _catalogued_item(db):
    """An item that is linked to a vendor_catalog row (so it has a cat#)."""
    return db.execute(
        """SELECT i.item_id, i.item_name, vc.catalog_number
             FROM inventory i JOIN vendor_catalog vc ON vc.id = i.catalog_id
            WHERE vc.catalog_number IS NOT NULL AND vc.catalog_number <> ''
            LIMIT 1"""
    ).fetchone()


def test_catalog_number_matches_despite_different_name(manager, db):
    """The key case: a vendor sheet whose product name differs from ours."""
    row = _catalogued_item(db)
    assert row is not None, "seed should link at least one item to the catalog"
    before = db.execute("SELECT COUNT(*) FROM inventory").fetchone()[0]

    csv = ("item_name,catalog_number,unit_cost\n"
           f"Totally Different Name,{row['catalog_number']},42.5\n")
    r = _upload(manager, csv)
    assert r.status_code == 200, r.text
    assert r.json()["updated"] == 1
    assert r.json()["created"] == 0
    # no duplicate row was created
    assert db.execute("SELECT COUNT(*) FROM inventory").fetchone()[0] == before
    # and the update landed on the catalog-matched item
    assert db.execute(
        "SELECT unit_cost FROM inventory WHERE item_id = ?", (row["item_id"],)
    ).fetchone()[0] == 42.5


def test_item_id_matches_when_no_catalog_number(manager, db):
    row = db.execute(
        "SELECT item_id, item_name FROM inventory ORDER BY item_id LIMIT 1"
    ).fetchone()
    csv = ("item_id,item_name,unit_cost\n"
           f"{row['item_id']},Renamed In Sheet,7.25\n")
    r = _upload(manager, csv)
    assert r.status_code == 200, r.text
    assert r.json()["updated"] == 1
    assert db.execute(
        "SELECT unit_cost FROM inventory WHERE item_id = ?", (row["item_id"],)
    ).fetchone()[0] == 7.25


def test_name_still_matches_as_fallback(manager, db):
    row = db.execute(
        "SELECT item_name FROM inventory ORDER BY item_id LIMIT 1"
    ).fetchone()
    csv = f"item_name,unit_cost\n{row['item_name']},3.5\n"
    r = _upload(manager, csv)
    assert r.status_code == 200
    assert r.json()["updated"] == 1


def test_unknown_row_still_creates(manager):
    csv = "item_name,catalog_number,quantity_on_hand\nBrand New Reagent,ZZ-9999,4\n"
    r = _upload(manager, csv)
    assert r.status_code == 200, r.text
    assert r.json()["created"] == 1


def test_export_carries_catalog_number(member):
    r = member.get("/api/export/inventory.csv")
    assert r.status_code == 200
    header = r.text.splitlines()[0]
    assert "catalog_number" in header
