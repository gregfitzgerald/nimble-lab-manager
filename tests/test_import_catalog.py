"""Tests for import_catalog.py -- the vendor price-catalog importer.

Covers header aliasing (GSA-style names), price cleaning, bad-row skipping,
dry-run, and upsert-not-duplicate on re-import.
"""
import csv
import io
import sqlite3

import import_catalog as ic


def _reader(text):
    return csv.DictReader(io.StringIO(text))


def test_header_aliases_map_gsa_style_names():
    headers = ["MFR PART NUMBER", "ITEM DESCRIPTION", "GSA PRICE", "PACKAGING", "CAS #"]
    mapping = ic.build_mapping(headers, [])
    assert mapping["MFR PART NUMBER"] == "catalog_number"
    assert mapping["ITEM DESCRIPTION"] == "product_name"
    assert mapping["GSA PRICE"] == "list_price"
    assert mapping["PACKAGING"] == "pack_size"
    assert mapping["CAS #"] == "cas_number"


def test_map_override_wins():
    mapping = ic.build_mapping(["WIDGET"], ["WIDGET=catalog_number"])
    assert mapping["WIDGET"] == "catalog_number"


def test_price_cleaning():
    assert ic._clean_price("$1,234.50") == 1234.50
    assert ic._clean_price("") is None
    for bad in ("Infinity", "-5", "abc"):
        try:
            ic._clean_price(bad)
            raise AssertionError(f"{bad!r} should have raised")
        except ValueError:
            pass


def test_parse_skips_bad_rows_and_defaults_vendor():
    text = ("catalog_number,product_name,price\n"
            "A1,Widget,10.00\n"
            ",No Cat Number,5\n"
            "A3,Bad Price,not-a-number\n")
    mapping = ic.build_mapping(next(csv.reader(io.StringIO(text))), [])
    rows, errors = ic.parse_rows(_reader(text), mapping, vendor_default="Acme")
    assert len(rows) == 1 and rows[0]["catalog_number"] == "A1"
    assert rows[0]["vendor"] == "Acme" and rows[0]["list_price"] == 10.0
    assert len(errors) == 2  # missing cat#, bad price


def test_run_upserts_not_duplicates(tmp_path):
    import app.db as appdb
    db = tmp_path / "cat.db"
    orig = appdb.DB_PATH
    appdb.DB_PATH = str(db)
    try:
        appdb.init_db(force=True, seed_demo=True)
    finally:
        appdb.DB_PATH = orig

    csv_path = tmp_path / "prices.csv"
    csv_path.write_text("MFR PART,DESCRIPTION,PRICE\nZZ-1,Test reagent,20.00\n")

    r1 = ic.run(str(csv_path), str(db), vendor_default="Fisher Scientific",
                overrides=["MFR PART=catalog_number", "DESCRIPTION=product_name"])
    assert r1["created"] == 1 and r1["updated"] == 0

    # re-import with a new price -> updates, does not duplicate
    csv_path.write_text("MFR PART,DESCRIPTION,PRICE\nZZ-1,Test reagent,17.50\n")
    r2 = ic.run(str(csv_path), str(db), vendor_default="Fisher Scientific",
                overrides=["MFR PART=catalog_number", "DESCRIPTION=product_name"])
    assert r2["created"] == 0 and r2["updated"] == 1

    conn = sqlite3.connect(db)
    try:
        n = conn.execute(
            "SELECT COUNT(*) FROM vendor_catalog WHERE catalog_number='ZZ-1'"
        ).fetchone()[0]
        price = conn.execute(
            "SELECT list_price FROM vendor_catalog WHERE catalog_number='ZZ-1'"
        ).fetchone()[0]
    finally:
        conn.close()
    assert n == 1 and price == 17.50


def test_dry_run_writes_nothing(tmp_path):
    import app.db as appdb
    db = tmp_path / "cat2.db"
    orig = appdb.DB_PATH
    appdb.DB_PATH = str(db)
    try:
        appdb.init_db(force=True, seed_demo=True)
    finally:
        appdb.DB_PATH = orig
    before = sqlite3.connect(db).execute("SELECT COUNT(*) FROM vendor_catalog").fetchone()[0]

    csv_path = tmp_path / "p.csv"
    csv_path.write_text("catalog_number,product_name,list_price\nDRY-1,Nope,9.99\n")
    res = ic.run(str(csv_path), str(db), vendor_default="Acme", dry_run=True)
    assert res["created"] == 1 and res["dry_run"] is True

    after = sqlite3.connect(db).execute("SELECT COUNT(*) FROM vendor_catalog").fetchone()[0]
    assert after == before  # rolled back
