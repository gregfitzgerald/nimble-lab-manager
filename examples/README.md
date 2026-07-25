# Example document repository -- SDS and CoA references

This folder is the bundled "document evidence" that Nimble Lab Manager points at
from its inventory, lots, and purchase orders. It has two kinds of content:

## 1. Safety Data Sheets (SDS) -- real manufacturer links

An SDS is a public, product-level document (not lot-specific). Every chemical or
reagent item in the seed links to its **real manufacturer SDS page** using that
vendor's normal SDS URL pattern (Sigma-Aldrich `/US/en/sds/<brand>/<catalog>`,
Thermo Fisher's document-connect viewer, NEB, Bio-Rad, EMS, Agilent, etc.).

See [`sds-index.md`](./sds-index.md) for the full item -> SDS URL table. These are
the same URLs stored in `inventory.sds_url`, `vendor_catalog.sds_url`, and the
`item_document` rows of kind `sds` in `seed.sql`.

## 2. Certificates of Analysis (CoA) -- representative samples

A CoA is **lot-specific**: it reports the QC test results for one manufactured
lot of one product, and vendors do **not** publish CoAs at a public URL -- you
receive the PDF with your shipment or pull it from a gated portal using your
lot number. Because there is no public link to point at, the CoA references in
this demo point at **representative sample documents** in [`coa/`](./coa/).

Each sample is a clean, self-contained, printable HTML file (no external assets,
fonts, scripts, or images -- everything is inline) styled like a real vendor CoA:
vendor and product header, catalog and lot number, a test-parameter table with
specification vs. result, an overall disposition, and a QC sign-off block. The
lot numbers, dates, and results were chosen to match the corresponding lots in
`seed.sql` so the demo is internally consistent. They are illustrative samples
for a portfolio demo, not certificates for any real manufactured lot.

### CoA samples in `coa/`

| File | Product | Vendor | Catalog # | Lot # |
|------|---------|--------|-----------|-------|
| `fbs-coa.html` | Fetal Bovine Serum, qualified, US origin | Gibco | 16000044 | FBS-2701 |
| `taq-polymerase-coa.html` | Taq DNA Polymerase | NEB | M0273 | TAQ-2612 |
| `neun-antibody-coa.html` | Anti-NeuN Antibody, clone A60 | Millipore Sigma | MAB377 | NEUN-2507 |
| `paraformaldehyde-coa.html` | Paraformaldehyde, reagent grade, powder | Sigma-Aldrich | P6148 | PFA-2509 |
| `dmem-coa.html` | DMEM, high glucose, pyruvate | Gibco | 11965092 | DMEM-2606 |

Open any file directly in a browser -- they are standalone and print cleanly.
