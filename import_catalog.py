#!/usr/bin/env python3
"""Import a vendor price catalog (CSV) into vendor_catalog.

Purpose: seed the app's catalog with GENUINELY-SOURCED prices. There is no free
bulk Fisher/Thermo feed to download and scraping their sites is off the table,
but two real, legal sources exist:

  1. GSA Advantage (gsaadvantage.gov) publishes each vendor's Authorized Federal
     Supply Schedule price list as a downloadable electronic catalog -- Fisher's
     channel is contract GS07F161BA. These are US-federal-negotiated prices
     (a little below list), public and free.
  2. A Fisher/Thermo PunchOut (cXML) account gives live contract prices; export
     a quote or hosted-catalog extract to CSV.

Either way you end up with a CSV; this loads it. Rows are matched to existing
catalog entries by (vendor, catalog_number) so re-importing an updated price
sheet refreshes prices instead of duplicating.

Stdlib only (csv, sqlite3, argparse), like the rest of the app.

Usage:
    python3 import_catalog.py prices.csv --vendor "Fisher Scientific"
    python3 import_catalog.py prices.csv --dry-run
    python3 import_catalog.py prices.csv --map "MFR PART=catalog_number,PRICE=list_price"
"""
import argparse
import csv
import sqlite3
import sys

# Catalog columns this tool can populate (matches schema.sql vendor_catalog).
_FIELDS = (
    "vendor", "catalog_number", "product_name", "category", "pack_size",
    "unit", "list_price", "cas_number", "hazard_class", "sds_url", "product_url",
)
_REQUIRED = ("catalog_number", "product_name")
_FLOAT_FIELDS = ("list_price",)

# Common header spellings -> our field. GSA/vendor exports vary wildly, so map
# generously; --map overrides any of these.
_ALIASES = {
    "vendor": "vendor", "manufacturer": "vendor", "mfr": "vendor", "supplier": "vendor",
    "catalog_number": "catalog_number", "catalog number": "catalog_number",
    "cat #": "catalog_number", "cat#": "catalog_number", "catalog #": "catalog_number",
    "part number": "catalog_number", "mfr part number": "catalog_number",
    "mfr part": "catalog_number", "part #": "catalog_number", "sku": "catalog_number",
    "product_name": "product_name", "product name": "product_name",
    "description": "product_name", "item description": "product_name", "name": "product_name",
    "category": "category", "class": "category",
    "pack_size": "pack_size", "pack size": "pack_size", "package": "pack_size",
    "packaging": "pack_size", "size": "pack_size",
    "unit": "unit", "uom": "unit", "unit of measure": "unit",
    "list_price": "list_price", "price": "list_price", "list price": "list_price",
    "unit price": "list_price", "contract price": "list_price", "gsa price": "list_price",
    "cas_number": "cas_number", "cas": "cas_number", "cas number": "cas_number", "cas #": "cas_number",
    "hazard_class": "hazard_class", "hazard": "hazard_class", "ghs": "hazard_class",
    "sds_url": "sds_url", "sds": "sds_url", "product_url": "product_url", "url": "product_url",
}


def _clean_price(raw):
    """'$1,234.50' / '1234.5' / '' -> float or None. Raises ValueError on junk."""
    s = str(raw).strip().replace("$", "").replace(",", "")
    if s == "":
        return None
    value = float(s)
    if value != value or value in (float("inf"), float("-inf")):
        raise ValueError("non-finite price")
    if value < 0:
        raise ValueError("negative price")
    return value


def build_mapping(headers, overrides):
    """Map CSV headers -> catalog fields via aliases, then apply --map overrides
    (which are 'HeaderName=field'). Returns {header: field}."""
    mapping = {}
    for h in headers:
        field = _ALIASES.get((h or "").strip().lower())
        if field:
            mapping[h] = field
    for pair in overrides or []:
        header, _, field = pair.partition("=")
        header, field = header.strip(), field.strip()
        if field not in _FIELDS:
            raise SystemExit(f"--map: unknown field {field!r} (valid: {', '.join(_FIELDS)})")
        mapping[header] = field
    return mapping


def parse_rows(reader, mapping, vendor_default=None):
    """Yield (rows, errors). Each row is a dict of catalog fields; bad rows are
    collected as {row, message} and skipped."""
    rows, errors = [], []
    for i, raw in enumerate(reader, start=1):
        rec = {}
        for header, field in mapping.items():
            val = (raw.get(header) or "").strip()
            if val != "":
                rec[field] = val
        if vendor_default and not rec.get("vendor"):
            rec["vendor"] = vendor_default
        missing = [f for f in _REQUIRED if not rec.get(f)]
        if missing:
            errors.append({"row": i, "message": f"missing {', '.join(missing)}"})
            continue
        if not rec.get("vendor"):
            errors.append({"row": i, "message": "no vendor (set --vendor or a vendor column)"})
            continue
        bad = None
        for f in _FLOAT_FIELDS:
            if f in rec:
                try:
                    rec[f] = _clean_price(rec[f])
                except ValueError as exc:
                    bad = f"{f}: {exc}"
                    break
        if bad:
            errors.append({"row": i, "message": bad})
            continue
        rec.setdefault("category", "other")
        rows.append(rec)
    return rows, errors


def upsert_catalog(conn, rows):
    """Insert or update catalog rows, matched on (vendor, catalog_number).
    Returns (created, updated). Caller owns the transaction."""
    created = updated = 0
    for rec in rows:
        existing = conn.execute(
            "SELECT id FROM vendor_catalog WHERE vendor = ? AND catalog_number = ?",
            (rec["vendor"], rec["catalog_number"]),
        ).fetchone()
        if existing:
            cols = [f for f in _FIELDS if f in rec and f not in ("vendor", "catalog_number")]
            if cols:
                conn.execute(
                    f"UPDATE vendor_catalog SET {', '.join(c + ' = ?' for c in cols)} WHERE id = ?",
                    [rec[c] for c in cols] + [existing[0]],
                )
            updated += 1
        else:
            cols = [f for f in _FIELDS if f in rec]
            conn.execute(
                f"INSERT INTO vendor_catalog ({', '.join(cols)}) "
                f"VALUES ({', '.join('?' for _ in cols)})",
                [rec[c] for c in cols],
            )
            created += 1
    return created, updated


def run(path, db_path, vendor_default=None, overrides=None, dry_run=False):
    with open(path, newline="", encoding="utf-8-sig") as fh:
        reader = csv.DictReader(fh)
        if not reader.fieldnames:
            raise SystemExit("CSV has no header row")
        mapping = build_mapping(reader.fieldnames, overrides)
        if "catalog_number" not in mapping.values() or "product_name" not in mapping.values():
            raise SystemExit(
                "Could not find a catalog-number and product-name column. "
                "Map them with --map, e.g. --map 'MFR PART=catalog_number,DESC=product_name'.\n"
                f"Headers seen: {', '.join(reader.fieldnames)}"
            )
        rows, errors = parse_rows(reader, mapping, vendor_default)

    conn = sqlite3.connect(db_path)
    try:
        created, updated = upsert_catalog(conn, rows)
        if dry_run:
            conn.rollback()
        else:
            conn.commit()
    finally:
        conn.close()
    return {"created": created, "updated": updated, "errors": errors, "dry_run": dry_run}


def main(argv=None):
    ap = argparse.ArgumentParser(description="Import a vendor price catalog CSV into vendor_catalog.")
    ap.add_argument("csv_path", help="CSV file (GSA electronic catalog export, vendor price sheet, ...)")
    ap.add_argument("--db", default="lab.db", help="SQLite database (default: lab.db)")
    ap.add_argument("--vendor", help="Vendor name for every row (when the file has no vendor column)")
    ap.add_argument("--map", dest="overrides", action="append",
                    help="Header=field overrides, e.g. --map 'PRICE=list_price' (repeatable)")
    ap.add_argument("--dry-run", action="store_true", help="Parse + report, write nothing")
    args = ap.parse_args(argv)

    # --map may be given as one comma-joined string or repeated; normalize.
    overrides = []
    for chunk in (args.overrides or []):
        overrides.extend(p for p in chunk.split(",") if p.strip())

    result = run(args.csv_path, args.db, args.vendor, overrides, args.dry_run)
    tag = "(dry run) " if result["dry_run"] else ""
    print(f"{tag}{result['created']} created, {result['updated']} updated, "
          f"{len(result['errors'])} skipped")
    for e in result["errors"][:20]:
        print(f"  row {e['row']}: {e['message']}", file=sys.stderr)
    if len(result["errors"]) > 20:
        print(f"  ... and {len(result['errors']) - 20} more", file=sys.stderr)


if __name__ == "__main__":
    main()
