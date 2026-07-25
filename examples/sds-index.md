# SDS index -- item to real manufacturer Safety Data Sheet

These are the real manufacturer SDS URLs referenced from the seed data
(`inventory.sds_url`, `vendor_catalog.sds_url`, and `item_document` rows of kind
`sds`). SDS documents are product-level and public; the links use each vendor's
normal SDS URL pattern.

## Inventory items (from `seed.sql` inventory rows)

| Item | CAS # | Vendor | Catalog # | SDS URL |
|------|-------|--------|-----------|---------|
| Isoflurane | 26675-46-7 | Sigma-Aldrich | 792632 | https://www.sigmaaldrich.com/US/en/sds/aldrich/792632 |
| Ketamine HCl | 6740-88-1 | Sigma-Aldrich | K2753 | https://www.sigmaaldrich.com/US/en/sds/sigma/k2753 |
| 4% Paraformaldehyde | 30525-89-4 | Sigma-Aldrich | P6148 | https://www.sigmaaldrich.com/US/en/sds/sigma/p6148 |
| Trypsin-EDTA 0.25% | -- | Gibco | 25200056 | https://www.thermofisher.com/document-connect/document-connect.html?url=https%3A%2F%2Fassets.thermofisher.com%2FTFS-Assets%2FLSG%2FSDS%2F25200056_SDS.pdf |
| dNTP Mix 10mM | -- | NEB | N0447 | https://www.neb.com/-/media/nebus/files/sds/n0447_sds.pdf |
| PBS 10x | -- | Gibco | 70011044 | https://www.thermofisher.com/document-connect/document-connect.html?url=https%3A%2F%2Fassets.thermofisher.com%2FTFS-Assets%2FLSG%2FSDS%2F70011044_SDS.pdf |
| Tris-HCl 1M pH 8.0 | 1185-53-1 | Invitrogen | 15568025 | https://www.thermofisher.com/document-connect/document-connect.html?url=https%3A%2F%2Fassets.thermofisher.com%2FTFS-Assets%2FLSG%2FSDS%2F15568025_SDS.pdf |
| Agarose | 9012-36-6 | Bio-Rad | 1613101 | https://www.bio-rad.com/webroot/web/pdf/lsr/sds/1613101.pdf |

## Vendor catalog chemicals (from `seed.sql` vendor_catalog rows)

| Product | CAS # | Vendor | Catalog # | SDS URL |
|---------|-------|--------|-----------|---------|
| Paraformaldehyde, powder | 30525-89-4 | Sigma-Aldrich | P6148 | https://www.sigmaaldrich.com/US/en/sds/sigma/p6148 |
| Paraformaldehyde, granular | 30525-89-4 | Electron Microscopy Sciences | 19200 | https://www.emsdiasum.com/sds/19200 |
| Paraformaldehyde, 96% | 30525-89-4 | Thermo Scientific | A11313 | https://www.thermofisher.com/document-connect/document-connect.html?url=https%3A%2F%2Fassets.thermofisher.com%2FTFS-Assets%2FLSG%2FSDS%2FA11313_SDS.pdf |
| DMSO, Hybri-Max | 67-68-5 | Sigma-Aldrich | D2650 | https://www.sigmaaldrich.com/US/en/sds/sigma/d2650 |
| Triton X-100 | 9002-93-1 | Sigma-Aldrich | X100 | https://www.sigmaaldrich.com/US/en/sds/sigma/x100 |
| Ethanol, 200 proof | 64-17-5 | Sigma-Aldrich | E7023 | https://www.sigmaaldrich.com/US/en/sds/sigma/e7023 |
| Methanol, anhydrous | 67-56-1 | Sigma-Aldrich | 179337 | https://www.sigmaaldrich.com/US/en/sds/sial/179337 |
| Glutaraldehyde, 25% | 111-30-8 | Electron Microscopy Sciences | 16000 | https://www.emsdiasum.com/sds/16000 |
